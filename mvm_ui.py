#!/usr/bin/env python3
"""Control — visual console UI"""

import json
import time
import os
from pathlib import Path
from flask import Flask, Response, request, jsonify

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None

STATE_FILE = Path.home() / ".streamfader" / "state.json"
PORT  = int(os.environ.get("PORT", 5570))
MODEL = os.environ.get("CTRL_MODEL", "claude-sonnet-4-6")


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(state: dict) -> str:
    mode      = state["mode"]
    intensity = state["intensity"]
    depth     = state["depth"]

    if mode == "EXPLORE":
        mode_rules = (
            "MODE: EXPLORE\n"
            "- Analysis only. No code changes.\n"
            "- End with a single decision point. Nothing else."
        )
    elif mode == "FIX":
        mode_rules = (
            "MODE: FIX\n"
            "- Identify one root cause only.\n"
            "- Produce one fix only.\n"
            "- Do not address secondary issues."
        )
    else:
        mode_rules = (
            "MODE: BUILD\n"
            "- Implement one atomic change only.\n"
            "- No refactoring unless explicitly required."
        )

    if intensity >= 0.7:
        intensity_rule = "INTENSITY: HIGH — minimal output, direct execution only."
    elif intensity >= 0.4:
        intensity_rule = "INTENSITY: MED — concise reasoning, focused output."
    else:
        intensity_rule = "INTENSITY: LOW — verbose reasoning, exploratory tone."

    if depth >= 0.7:
        depth_rule = "DEPTH: HIGH — deeper diagnostic reasoning allowed."
    elif depth >= 0.4:
        depth_rule = "DEPTH: MED — moderate analysis depth."
    else:
        depth_rule = "DEPTH: LOW — surface-level reasoning only."

    certainty = state.get("certainty", 0.5)
    risk      = state.get("risk",      0.5)
    stance    = state.get("stance",    "GUIDE")

    if certainty >= 0.7:
        certainty_rule = "CERTAINTY: HIGH — commit to one solution, do not present alternatives."
    elif certainty >= 0.4:
        certainty_rule = "CERTAINTY: MED — give a recommendation with brief reasoning."
    else:
        certainty_rule = "CERTAINTY: LOW — show 2-3 approaches with pros and cons, do not pick."

    if risk >= 0.7:
        risk_rule = "RISK: HIGH — best solution even if it requires significant changes."
    elif risk >= 0.4:
        risk_rule = "RISK: MED — balanced approach, prefer existing patterns where reasonable."
    else:
        risk_rule = "RISK: LOW — stay close to existing patterns, minimal disruption."

    if stance == "LIST":
        stance_rule = "STANCE: LIST — present alternatives only, do not implement anything."
    elif stance == "DECIDE":
        stance_rule = "STANCE: DECIDE — pick one approach and implement it, zero explanation of alternatives."
    else:
        stance_rule = "STANCE: GUIDE — give your best recommendation with brief reasoning, then implement."

    scope     = state.get("scope",     0.5)
    bandwidth = state.get("bandwidth", 0.5)
    filter_   = state.get("filter",    "MODULE")

    if scope >= 0.7:
        scope_rule = "SCOPE: WIDE — consider the full codebase, pull in all related context."
    elif scope >= 0.4:
        scope_rule = "SCOPE: MED — consider this module and its direct dependencies."
    else:
        scope_rule = "SCOPE: NARROW — stay inside the immediate file or function only."

    if bandwidth >= 0.7:
        bandwidth_rule = "BANDWIDTH: WIDE — broad strokes, pull in adjacent concerns freely."
    elif bandwidth >= 0.4:
        bandwidth_rule = "BANDWIDTH: MED — shaped focus, related things welcome if directly relevant."
    else:
        bandwidth_rule = "BANDWIDTH: NARROW — surgical precision, touch nothing adjacent."

    if filter_ == "FILE":
        filter_rule = "FILTER: FILE — strict local scope, this file only, no cross-module context."
    elif filter_ == "PROJECT":
        filter_rule = "FILTER: PROJECT — full project scope allowed, global context welcome."
    else:
        filter_rule = "FILTER: MODULE — shaped band around the module, selective context."

    room  = state.get("room",  0.3)
    decay = state.get("decay", 0.3)
    voice = state.get("voice", "STUDIO")

    if room >= 0.7:
        room_rule = "ROOM: WET — open space around your output, breathing room, think out loud."
    elif room >= 0.4:
        room_rule = "ROOM: MED — some space, conversational but not dry."
    else:
        room_rule = "ROOM: DRY — close-mic'd, no space, just the output."

    if decay >= 0.7:
        decay_rule = "DECAY: LONG — ideas can echo and build, spacious language."
    elif decay >= 0.4:
        decay_rule = "DECAY: MED — moderate density, words earn their place."
    else:
        decay_rule = "DECAY: SHORT — tight, compressed, every word counts."

    if voice == "DIRECT":
        voice_rule = "VOICE: DIRECT — dead room, output only, zero commentary or preamble."
    elif voice == "OPEN":
        voice_rule = "VOICE: OPEN — full resonance, collaborative, thinks out loud with you."
    else:
        voice_rule = "VOICE: STUDIO — professional, measured, clean response with minimal framing."

    state_block = json.dumps(state)

    return "\n".join([
        mode_rules,
        intensity_rule,
        depth_rule,
        certainty_rule,
        risk_rule,
        stance_rule,
        scope_rule,
        bandwidth_rule,
        filter_rule,
        room_rule,
        decay_rule,
        voice_rule,
        "",
        "GLOBAL CONSTRAINTS:",
        "- One action per run.",
        "- No multi-step planning chains.",
        "- No combined modes.",
        "- Stop immediately after completing the task.",
        "",
        "OUTPUT FORMAT:",
        "STATE:",
        state_block,
        "",
        "ACTION:",
        "<what you will do — one line>",
        "",
        "RESULT:",
        "<final output>",
    ])


app = Flask(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {
            "mode": "BUILD", "intensity": 0.5, "depth": 0.5,
            "certainty": 0.5, "risk": 0.5, "stance": "GUIDE",
            "scope": 0.5, "bandwidth": 0.5, "filter": "MODULE",
            "room": 0.3, "decay": 0.3, "voice": "STUDIO",
        }

def write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(STATE_FILE)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML

@app.route("/stream")
def stream():
    def generate():
        last = {}
        while True:
            state = read_state()
            if state != last:
                last = state.copy()
                yield f"data: {json.dumps(state)}\n\n"
            time.sleep(0.05)
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.route("/set", methods=["POST"])
def set_state():
    data = request.get_json()
    state = read_state()
    state.update(data)
    write_state(state)
    return jsonify({"ok": True})

@app.route("/run", methods=["POST"])
def run_task():
    data    = request.get_json() or {}
    task    = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "No task provided"}), 400
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    def generate():
        if not _anthropic:
            yield f"data: {json.dumps({'error': 'anthropic not installed'})}\n\n"
            return
        if not api_key:
            yield f"data: {json.dumps({'error': 'ANTHROPIC_API_KEY not set'})}\n\n"
            return
        state  = read_state()
        system = _build_prompt(state)
        try:
            client = _anthropic.Anthropic(api_key=api_key)
            with client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": task}],
            ) as s:
                for text in s.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/health")
def health():
    return jsonify({"ok": True, "model": MODEL,
                    "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))})


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Control</title>
<link href="https://fonts.googleapis.com/css2?family=Abril+Fatface&family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#070F09;font-family:'Inter',sans-serif;color:#C4E8D0;height:100vh;display:flex;flex-direction:column;user-select:none;overflow:hidden;}

/* HEADER */
.hdr{padding:0 16px;border-bottom:1px solid #1A3A28;background:#040A06;display:flex;align-items:center;gap:10px;flex-shrink:0;height:44px;}
.brand{font-family:'Abril Fatface',serif;font-size:17px;color:#6EE7B7;letter-spacing:.02em;line-height:1;}
.hdr-sep{width:1px;height:18px;background:#1A3A28;flex-shrink:0;}
.hdr-badge{font-size:10px;font-weight:800;letter-spacing:.12em;padding:2px 8px;border-radius:2px;border-left:2px solid;transition:all .25s;}
.hdr-vals{font-size:10px;color:#3A7A5A;letter-spacing:.06em;font-weight:600;font-variant-numeric:tabular-nums;}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:8px;}
.faq-btn{width:24px;height:24px;border-radius:50%;border:1px solid #1A3A28;background:transparent;color:#3A7A5A;font-size:11px;font-weight:800;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;line-height:1;}
.faq-btn:hover{background:#064E3B;color:#6EE7B7;border-color:#6EE7B7;}

/* MAIN SPLIT */
.main{flex:1;display:flex;overflow:hidden;min-height:0;}

/* SURFACE PANEL */
.surface{width:36%;min-width:240px;border-right:1px solid #1A3A28;background:#070F09;display:flex;flex-direction:column;overflow:hidden;}
.panel-hd{padding:4px 12px;font-size:8px;font-weight:800;letter-spacing:.24em;color:#2A5A3A;text-transform:uppercase;border-bottom:1px solid #1A3A28;flex-shrink:0;background:#040A06;}

/* STRIPS STACK */
.strips-stack{flex:1;display:flex;flex-direction:column;gap:1px;background:#1A3A28;overflow:hidden;}

/* STRIP */
.strip{display:flex;flex-direction:row;align-items:stretch;background:#070F09;flex:1;min-height:70px;overflow:hidden;}
.strip-accent{width:3px;flex-shrink:0;}
.strip.t1 .strip-accent{background:#064E3B;}
.strip.t2 .strip-accent{background:#065F46;}
.strip.t3 .strip-accent{background:#047857;}
.strip.t4 .strip-accent{background:#059669;}

/* FADER COLUMNS */
.fader-col{width:32px;display:flex;flex-direction:column;align-items:center;padding:7px 0 5px;flex-shrink:0;gap:3px;}
.fader-lbl{font-size:7px;color:#2A5A3A;font-weight:700;letter-spacing:.08em;text-transform:uppercase;flex-shrink:0;text-align:center;}
.fader-track{width:8px;flex:1;min-height:48px;background:#060E09;border:1px solid #1A3A28;border-radius:4px;position:relative;cursor:ns-resize;touch-action:none;}
.fader-fill{position:absolute;bottom:0;left:0;right:0;border-radius:4px;background:linear-gradient(0deg,#6EE7B7 0%,#064E3B 100%);pointer-events:none;}
.fader-thumb{position:absolute;width:22px;height:10px;border-radius:2px;left:50%;transform:translateX(-50%);background:linear-gradient(180deg,#1A3A28,#0F2A1C);border:1px solid #6EE7B7;box-shadow:0 0 6px rgba(110,231,183,.18);cursor:ns-resize;z-index:2;touch-action:none;}
.fader-thumb::before{content:'';position:absolute;left:22%;right:22%;height:1px;background:rgba(110,231,183,.45);top:50%;transform:translateY(-50%);}
.fader-val{font-size:7px;font-weight:700;color:#3A7A5A;font-variant-numeric:tabular-nums;flex-shrink:0;}

/* STRIP CENTER */
.strip-center{flex:1;display:flex;flex-direction:column;justify-content:center;gap:6px;padding:8px 8px 8px 6px;min-width:0;}
.strip-id{font-size:8px;font-weight:800;letter-spacing:.2em;color:#2A5A3A;text-transform:uppercase;}

/* BUTTONS */
.btns{display:flex;flex-direction:row;gap:3px;}
.btn{flex:1;height:34px;border-radius:3px;border:1px solid #1A3A28;background:#060E09;color:#3A7A5A;font-size:9px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;cursor:pointer;transition:all .1s;display:flex;align-items:center;justify-content:center;min-width:0;padding:0 2px;}
.btn:hover{background:#0F2A1C;border-color:#2A5A3A;color:#6EE7B7;}
.btn.active{background:#064E3B;color:#6EE7B7;border-color:#6EE7B7;box-shadow:0 0 8px rgba(110,231,183,.12);}

/* MONITOR PANEL */
.monitor{flex:1;display:flex;flex-direction:column;overflow:hidden;background:#060E09;min-width:0;}

/* METERS */
.meters-wrap{padding:8px 14px 7px;border-bottom:1px solid #1A3A28;flex-shrink:0;}
.section-hd{font-size:8px;font-weight:800;letter-spacing:.24em;color:#2A5A3A;text-transform:uppercase;margin-bottom:6px;}
.meters-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 14px;}
.meter-row{display:flex;align-items:center;gap:5px;}
.meter-lbl{font-size:8px;color:#2A5A3A;font-weight:700;letter-spacing:.04em;text-transform:uppercase;width:60px;flex-shrink:0;}
.meter-track{flex:1;height:4px;background:#060E09;border-radius:2px;overflow:hidden;border:1px solid #1A3A28;}
.meter-fill{height:100%;background:linear-gradient(90deg,#6EE7B7 0%,#059669 55%,#F59E0B 100%);transition:width .12s ease;border-radius:1px;}
.meter-val{font-size:8px;font-weight:700;color:#3A7A5A;font-variant-numeric:tabular-nums;width:26px;text-align:right;flex-shrink:0;}
.meter-lvl{font-size:7px;font-weight:800;letter-spacing:.04em;width:22px;flex-shrink:0;}
.lvl-low{color:#059669;} .lvl-med{color:#3A7A5A;} .lvl-high{color:#F59E0B;}

/* STATE PILLS */
.pills-wrap{padding:5px 14px;border-bottom:1px solid #1A3A28;display:flex;gap:7px;align-items:center;flex-shrink:0;flex-wrap:wrap;}
.pill-group{display:flex;align-items:center;gap:4px;}
.pill-lbl{font-size:7px;color:#2A5A3A;font-weight:700;letter-spacing:.12em;text-transform:uppercase;}
.pill{padding:2px 7px;border-radius:2px;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;transition:all .2s;}

/* PREVIEW */
.preview-wrap{padding:8px 14px 7px;border-bottom:1px solid #1A3A28;flex-shrink:0;}
.preview-top{display:flex;align-items:center;gap:8px;margin-bottom:5px;}
.preview-hd{font-size:8px;font-weight:800;letter-spacing:.2em;color:#2A5A3A;text-transform:uppercase;}
.api-tag{font-size:8px;font-weight:700;padding:2px 6px;border-radius:2px;background:rgba(245,158,11,.08);color:#B45309;letter-spacing:.04em;border:1px solid rgba(245,158,11,.2);}
.task-row{display:flex;gap:6px;align-items:center;}
.task-input{flex:1;height:30px;border:1px solid #1A3A28;border-radius:3px;background:#060E09;padding:0 10px;font-family:'Inter',sans-serif;font-size:12px;color:#C4E8D0;outline:none;transition:border-color .15s;user-select:text;}
.task-input:focus{border-color:#6EE7B7;box-shadow:0 0 0 2px rgba(110,231,183,.06);}
.task-input::placeholder{color:#1A3A28;}
.run-btn{height:30px;padding:0 14px;background:#064E3B;color:#6EE7B7;border:1px solid #6EE7B7;border-radius:3px;font-family:'Inter',sans-serif;font-size:9px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;cursor:pointer;transition:background .12s;white-space:nowrap;}
.run-btn:hover{background:#047857;}
.run-btn:disabled{opacity:.3;cursor:not-allowed;}
.resp-wrap{overflow:hidden;max-height:0;transition:max-height .25s ease;}
.resp-wrap.open{max-height:110px;}
.resp-box{margin-top:5px;padding:8px 10px;background:#060E09;border:1px solid #1A3A28;border-radius:3px;font-size:11px;line-height:1.6;color:#C4E8D0;white-space:pre-wrap;max-height:100px;overflow-y:auto;font-family:'Inter',sans-serif;}
.resp-box .err{color:#EF4444;font-weight:600;}

/* HISTORY */
.history-wrap{flex:1;overflow-y:auto;padding:7px 14px 10px;min-height:0;}
.history-empty{font-size:11px;color:#1A3A28;font-style:italic;text-align:center;padding:14px 0;}
.history-hd-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;}
.clear-btn{height:20px;padding:0 8px;border-radius:2px;border:1px solid #1A3A28;background:transparent;color:#2A5A3A;font-size:8px;font-weight:700;cursor:pointer;letter-spacing:.06em;text-transform:uppercase;transition:all .1s;}
.clear-btn:hover{background:#7F1D1D;color:#FCA5A5;border-color:#7F1D1D;}
.hc{background:#060E09;border:1px solid #1A3A28;border-radius:3px;padding:6px 9px;margin-bottom:4px;cursor:pointer;transition:border-color .1s;}
.hc:hover{border-color:#2A5A3A;}
.hc.open{border-color:#6EE7B7;}
.hc-top{display:flex;gap:6px;align-items:center;margin-bottom:3px;}
.hc-time{font-size:9px;color:#2A5A3A;font-variant-numeric:tabular-nums;font-weight:600;}
.hc-mode{font-size:9px;font-weight:800;padding:1px 5px;border-radius:2px;background:#064E3B;color:#6EE7B7;letter-spacing:.08em;}
.hc-peek{font-size:9px;color:#2A5A3A;font-weight:600;margin-left:auto;font-variant-numeric:tabular-nums;}
.hc-chevron{font-size:8px;color:#1A3A28;transition:transform .15s;flex-shrink:0;}
.hc.open .hc-chevron{transform:rotate(180deg);}
.hc-task{font-size:12px;font-weight:700;color:#C4E8D0;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.hc-preview{font-size:10px;color:#2A5A3A;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.hc-body{display:none;margin-top:7px;padding-top:7px;border-top:1px solid #1A3A28;}
.hc.open .hc-body{display:block;}
.hc-state-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:3px;margin-bottom:7px;}
.hc-si{background:#070F09;border-radius:2px;padding:4px 5px;border:1px solid #1A3A28;}
.hc-si-lbl{font-size:7px;color:#2A5A3A;font-weight:700;text-transform:uppercase;letter-spacing:.06em;}
.hc-si-val{font-size:11px;color:#6EE7B7;font-weight:800;margin-top:1px;font-variant-numeric:tabular-nums;}
.hc-full{font-size:11px;line-height:1.6;color:#C4E8D0;white-space:pre-wrap;background:#040A06;border:1px solid #1A3A28;border-radius:3px;padding:8px 10px;max-height:180px;overflow-y:auto;margin-bottom:6px;font-family:'Inter',sans-serif;}
.hc-actions{display:flex;gap:5px;justify-content:flex-end;}
.hc-copy{height:24px;padding:0 10px;border-radius:2px;border:1px solid #1A3A28;background:#070F09;color:#3A7A5A;font-size:9px;font-weight:700;cursor:pointer;transition:all .1s;letter-spacing:.06em;text-transform:uppercase;}
.hc-copy:hover{background:#064E3B;color:#6EE7B7;border-color:#6EE7B7;}

/* FAQ */
.faq-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:100;}
.faq-overlay.open{display:block;}
.faq-panel{position:fixed;right:-500px;top:0;bottom:0;width:480px;background:#070F09;z-index:101;transition:right .26s cubic-bezier(.4,0,.2,1);overflow-y:auto;border-left:2px solid #064E3B;display:flex;flex-direction:column;}
.faq-panel.open{right:0;}
.faq-hd{padding:13px 18px;border-bottom:1px solid #1A3A28;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;background:#040A06;}
.faq-title{font-family:'Abril Fatface',serif;font-size:20px;color:#6EE7B7;}
.faq-close{width:26px;height:26px;border:1px solid #1A3A28;background:transparent;cursor:pointer;font-size:13px;color:#3A7A5A;border-radius:50%;transition:background .12s;display:flex;align-items:center;justify-content:center;font-weight:700;}
.faq-close:hover{background:#064E3B;color:#6EE7B7;border-color:#6EE7B7;}
.faq-body{padding:18px;flex:1;}
.faq-s{margin-bottom:20px;}
.faq-s-title{font-size:8px;font-weight:800;letter-spacing:.24em;text-transform:uppercase;color:#6EE7B7;margin-bottom:7px;}
.faq-p{font-size:12px;line-height:1.7;color:#6EE7B7;opacity:.6;margin-bottom:7px;}
.faq-track{margin-bottom:8px;padding:9px 12px;background:#060E09;border-radius:3px;border-left:3px solid #064E3B;}
.faq-track-name{font-size:10px;font-weight:800;color:#6EE7B7;margin-bottom:3px;letter-spacing:.06em;}
.faq-track-desc{font-size:11px;color:#6EE7B7;opacity:.55;line-height:1.6;}
.faq-code{font-family:'Courier New',monospace;font-size:11px;background:#040A06;padding:7px 10px;border-radius:3px;color:#6EE7B7;margin:5px 0;display:block;border:1px solid #1A3A28;}
</style>
</head>
<body>

<div class="hdr">
  <!-- Logo mark: chaotic → controlled waveform -->
  <svg width="40" height="20" viewBox="0 0 40 20" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">
    <rect width="40" height="20" rx="2" fill="#040A06"/>
    <line x1="2" y1="10" x2="38" y2="10" stroke="#1A3A28" stroke-width="0.5"/>
    <line x1="20" y1="1" x2="20" y2="19" stroke="#2A5A3A" stroke-width="0.8" stroke-dasharray="2,1.5"/>
    <polyline points="2,10 4,5 6,15 8,3 10,16 12,7 14,12 16,2 18,14 20,10" stroke="#F59E0B" stroke-width="1.2" stroke-linejoin="round" fill="none"/>
    <path d="M20,10 C22.5,10 23.5,3 25,3 C26.5,3 27.5,17 29,17 C30.5,17 31.5,3 33,3 C34.5,3 35.5,10 38,10" stroke="#6EE7B7" stroke-width="1.2" fill="none"/>
    <rect width="40" height="20" rx="2" fill="none" stroke="#1A3A28" stroke-width="1"/>
  </svg>
  <span class="brand">control</span>
  <div class="hdr-sep"></div>
  <div class="hdr-badge" id="hdr-badge">—</div>
  <div class="hdr-vals" id="hdr-vals">—</div>
  <div class="hdr-right">
    <button class="faq-btn" onclick="openFaq()">?</button>
  </div>
</div>

<div class="main">

  <!-- LEFT: CONTROL SURFACE -->
  <div class="surface">
    <div class="panel-hd">CONTROL SURFACE</div>
    <div class="strips-stack">

      <!-- T1: MODE -->
      <div class="strip t1">
        <div class="strip-accent"></div>
        <div class="fader-col">
          <div class="fader-track" id="ft-intensity">
            <div class="fader-fill" id="ff-intensity"></div>
            <div class="fader-thumb" id="fth-intensity"></div>
          </div>
          <div class="fader-val" id="fv-intensity">0.50</div>
          <div class="fader-lbl">INTEN</div>
        </div>
        <div class="strip-center">
          <div class="strip-id">T1 — MODE</div>
          <div class="btns">
            <div class="btn" data-field="mode" data-val="EXPLORE" onclick="set('mode','EXPLORE')">EXPLORE</div>
            <div class="btn" data-field="mode" data-val="FIX"     onclick="set('mode','FIX')">FIX</div>
            <div class="btn" data-field="mode" data-val="BUILD"   onclick="set('mode','BUILD')">BUILD</div>
          </div>
        </div>
        <div class="fader-col">
          <div class="fader-track" id="ft-depth">
            <div class="fader-fill" id="ff-depth"></div>
            <div class="fader-thumb" id="fth-depth"></div>
          </div>
          <div class="fader-val" id="fv-depth">0.50</div>
          <div class="fader-lbl">DEPTH</div>
        </div>
      </div>

      <!-- T2: CONFIDENCE -->
      <div class="strip t2">
        <div class="strip-accent"></div>
        <div class="fader-col">
          <div class="fader-track" id="ft-certainty">
            <div class="fader-fill" id="ff-certainty"></div>
            <div class="fader-thumb" id="fth-certainty"></div>
          </div>
          <div class="fader-val" id="fv-certainty">0.50</div>
          <div class="fader-lbl">CERT</div>
        </div>
        <div class="strip-center">
          <div class="strip-id">T2 — CONFIDENCE</div>
          <div class="btns">
            <div class="btn" data-field="stance" data-val="LIST"   onclick="set('stance','LIST')">LIST</div>
            <div class="btn" data-field="stance" data-val="GUIDE"  onclick="set('stance','GUIDE')">GUIDE</div>
            <div class="btn" data-field="stance" data-val="DECIDE" onclick="set('stance','DECIDE')">DECIDE</div>
          </div>
        </div>
        <div class="fader-col">
          <div class="fader-track" id="ft-risk">
            <div class="fader-fill" id="ff-risk"></div>
            <div class="fader-thumb" id="fth-risk"></div>
          </div>
          <div class="fader-val" id="fv-risk">0.50</div>
          <div class="fader-lbl">RISK</div>
        </div>
      </div>

      <!-- T3: SCOPE -->
      <div class="strip t3">
        <div class="strip-accent"></div>
        <div class="fader-col">
          <div class="fader-track" id="ft-scope">
            <div class="fader-fill" id="ff-scope"></div>
            <div class="fader-thumb" id="fth-scope"></div>
          </div>
          <div class="fader-val" id="fv-scope">0.50</div>
          <div class="fader-lbl">SCOPE</div>
        </div>
        <div class="strip-center">
          <div class="strip-id">T3 — SCOPE</div>
          <div class="btns">
            <div class="btn" data-field="filter" data-val="FILE"    onclick="set('filter','FILE')">FILE</div>
            <div class="btn" data-field="filter" data-val="MODULE"  onclick="set('filter','MODULE')">MODULE</div>
            <div class="btn" data-field="filter" data-val="PROJECT" onclick="set('filter','PROJECT')">PROJECT</div>
          </div>
        </div>
        <div class="fader-col">
          <div class="fader-track" id="ft-bandwidth">
            <div class="fader-fill" id="ff-bandwidth"></div>
            <div class="fader-thumb" id="fth-bandwidth"></div>
          </div>
          <div class="fader-val" id="fv-bandwidth">0.50</div>
          <div class="fader-lbl">BW</div>
        </div>
      </div>

      <!-- T4: VOICE -->
      <div class="strip t4">
        <div class="strip-accent"></div>
        <div class="fader-col">
          <div class="fader-track" id="ft-room">
            <div class="fader-fill" id="ff-room"></div>
            <div class="fader-thumb" id="fth-room"></div>
          </div>
          <div class="fader-val" id="fv-room">0.30</div>
          <div class="fader-lbl">ROOM</div>
        </div>
        <div class="strip-center">
          <div class="strip-id">T4 — VOICE</div>
          <div class="btns">
            <div class="btn" data-field="voice" data-val="DIRECT" onclick="set('voice','DIRECT')">DIRECT</div>
            <div class="btn" data-field="voice" data-val="STUDIO" onclick="set('voice','STUDIO')">STUDIO</div>
            <div class="btn" data-field="voice" data-val="OPEN"   onclick="set('voice','OPEN')">OPEN</div>
          </div>
        </div>
        <div class="fader-col">
          <div class="fader-track" id="ft-decay">
            <div class="fader-fill" id="ff-decay"></div>
            <div class="fader-thumb" id="fth-decay"></div>
          </div>
          <div class="fader-val" id="fv-decay">0.30</div>
          <div class="fader-lbl">DECAY</div>
        </div>
      </div>

    </div>
  </div>

  <!-- RIGHT: MONITORING -->
  <div class="monitor">
    <div class="panel-hd">MONITORING</div>

    <div class="meters-wrap">
      <div class="section-hd">PARAMETER LEVELS</div>
      <div class="meters-grid">
        <div class="meter-row"><span class="meter-lbl">INTENSITY</span><div class="meter-track"><div class="meter-fill" id="m-intensity" style="width:50%"></div></div><span class="meter-val" id="mv-intensity">0.50</span><span class="meter-lvl lvl-med" id="ml-intensity">MED</span></div>
        <div class="meter-row"><span class="meter-lbl">CERTAINTY</span><div class="meter-track"><div class="meter-fill" id="m-certainty" style="width:50%"></div></div><span class="meter-val" id="mv-certainty">0.50</span><span class="meter-lvl lvl-med" id="ml-certainty">MED</span></div>
        <div class="meter-row"><span class="meter-lbl">DEPTH</span><div class="meter-track"><div class="meter-fill" id="m-depth" style="width:50%"></div></div><span class="meter-val" id="mv-depth">0.50</span><span class="meter-lvl lvl-med" id="ml-depth">MED</span></div>
        <div class="meter-row"><span class="meter-lbl">RISK</span><div class="meter-track"><div class="meter-fill" id="m-risk" style="width:50%"></div></div><span class="meter-val" id="mv-risk">0.50</span><span class="meter-lvl lvl-med" id="ml-risk">MED</span></div>
        <div class="meter-row"><span class="meter-lbl">SCOPE</span><div class="meter-track"><div class="meter-fill" id="m-scope" style="width:50%"></div></div><span class="meter-val" id="mv-scope">0.50</span><span class="meter-lvl lvl-med" id="ml-scope">MED</span></div>
        <div class="meter-row"><span class="meter-lbl">ROOM</span><div class="meter-track"><div class="meter-fill" id="m-room" style="width:30%"></div></div><span class="meter-val" id="mv-room">0.30</span><span class="meter-lvl lvl-low" id="ml-room">LOW</span></div>
        <div class="meter-row"><span class="meter-lbl">BANDWIDTH</span><div class="meter-track"><div class="meter-fill" id="m-bandwidth" style="width:50%"></div></div><span class="meter-val" id="mv-bandwidth">0.50</span><span class="meter-lvl lvl-med" id="ml-bandwidth">MED</span></div>
        <div class="meter-row"><span class="meter-lbl">DECAY</span><div class="meter-track"><div class="meter-fill" id="m-decay" style="width:30%"></div></div><span class="meter-val" id="mv-decay">0.30</span><span class="meter-lvl lvl-low" id="ml-decay">LOW</span></div>
      </div>
    </div>

    <div class="pills-wrap">
      <div class="pill-group"><span class="pill-lbl">MODE</span><div class="pill" id="pill-mode">—</div></div>
      <div class="pill-group"><span class="pill-lbl">STANCE</span><div class="pill" id="pill-stance">—</div></div>
      <div class="pill-group"><span class="pill-lbl">FILTER</span><div class="pill" id="pill-filter">—</div></div>
      <div class="pill-group"><span class="pill-lbl">VOICE</span><div class="pill" id="pill-voice">—</div></div>
    </div>

    <div class="preview-wrap">
      <div class="preview-top">
        <span class="preview-hd">PREVIEW RUN</span>
        <span class="api-tag">Claude API · no file access</span>
      </div>
      <div class="task-row">
        <input class="task-input" id="task-input" type="text" placeholder="type a task to preview parameter effects…">
        <button class="run-btn" id="run-btn">RUN</button>
      </div>
      <div class="resp-wrap" id="resp-wrap">
        <div class="resp-box" id="resp-box"></div>
      </div>
    </div>

    <div class="history-wrap">
      <div class="history-hd-row">
        <div class="section-hd">RUN LOG</div>
        <button class="clear-btn" onclick="clearHistory()">Clear</button>
      </div>
      <div id="history"><div class="history-empty">no runs yet</div></div>
    </div>
  </div>

</div>

<!-- FAQ -->
<div class="faq-overlay" id="faq-overlay" onclick="closeFaq()"></div>
<div class="faq-panel" id="faq-panel">
  <div class="faq-hd">
    <span class="faq-title">control</span>
    <button class="faq-close" onclick="closeFaq()">✕</button>
  </div>
  <div class="faq-body">

    <div class="faq-s">
      <div class="faq-s-title">what is this?</div>
      <p class="faq-p">Control is a behavioral interface for Claude Code. Not a chatbot. Not a prompt playground. A mixing board for how an AI coding agent thinks.</p>
      <p class="faq-p">Every fader and button adjusts a parameter in the system prompt. Same task. Different state. Measurably different output. Every time.</p>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">the four tracks</div>
      <div class="faq-track">
        <div class="faq-track-name">T1 — MODE</div>
        <div class="faq-track-desc">What Claude is doing: EXPLORE (analyze only, no edits), FIX (one root cause, one fix), BUILD (one atomic change). Intensity compresses output. Depth controls reasoning depth.</div>
      </div>
      <div class="faq-track" style="border-left-color:#065F46">
        <div class="faq-track-name">T2 — CONFIDENCE</div>
        <div class="faq-track-desc">How committed Claude is. Certainty = how strongly it picks a path. Risk = how bold the changes. Stance: LIST shows alternatives, GUIDE recommends then acts, DECIDE just does it.</div>
      </div>
      <div class="faq-track" style="border-left-color:#047857">
        <div class="faq-track-name">T3 — SCOPE</div>
        <div class="faq-track-desc">How wide Claude looks. Scope = how much of the codebase to consider. Bandwidth = adjacent concerns. Filter: FILE (this file only), MODULE (this module), PROJECT (full codebase).</div>
      </div>
      <div class="faq-track" style="border-left-color:#059669">
        <div class="faq-track-name">T4 — VOICE</div>
        <div class="faq-track-desc">The feel of output. Room = breathing space. Decay = how long ideas echo. Voice: DIRECT (output only, zero preamble), STUDIO (clean and professional), OPEN (thinks out loud with you).</div>
      </div>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">preview vs. ctrl run</div>
      <p class="faq-p">Preview Run calls Claude API directly — same model, no tools, no file access. Good for seeing how parameters change output style.</p>
      <p class="faq-p">The real workflow is your terminal:</p>
      <code class="faq-code">ctrl run "refactor the auth module"</code>
      <p class="faq-p">This invokes Claude Code with full tool access. The state set here shapes how it works.</p>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">physical controller</div>
      <p class="faq-p">With a Korg nanoKONTROL2 set to External LED mode:</p>
      <code class="faq-code">ctrl nano --start</code>
      <p class="faq-p">Faders map to parameters in real time. State file at <code style="background:#040A06;padding:1px 4px;border-radius:2px;font-size:10px">~/.streamfader/state.json</code>.</p>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">the proof</div>
      <p class="faq-p">Set MODE to EXPLORE, intensity LOW, stance LIST. Ask Claude anything. Then flip to BUILD, intensity HIGH, stance DECIDE. Ask the same thing. The outputs are measurably different.</p>
      <p class="faq-p" style="opacity:.3;font-style:italic">That's the machine. You hold the dial.</p>
    </div>

  </div>
</div>

<script>
const THUMB_H = 10;
const FADERS = {
  intensity: {fill:'ff-intensity', thumb:'fth-intensity', val:'fv-intensity', track:'ft-intensity'},
  certainty: {fill:'ff-certainty', thumb:'fth-certainty', val:'fv-certainty', track:'ft-certainty'},
  scope:     {fill:'ff-scope',     thumb:'fth-scope',     val:'fv-scope',     track:'ft-scope'},
  room:      {fill:'ff-room',      thumb:'fth-room',      val:'fv-room',      track:'ft-room'},
  depth:     {fill:'ff-depth',     thumb:'fth-depth',     val:'fv-depth',     track:'ft-depth'},
  risk:      {fill:'ff-risk',      thumb:'fth-risk',      val:'fv-risk',      track:'ft-risk'},
  bandwidth: {fill:'ff-bandwidth', thumb:'fth-bandwidth', val:'fv-bandwidth', track:'ft-bandwidth'},
  decay:     {fill:'ff-decay',     thumb:'fth-decay',     val:'fv-decay',     track:'ft-decay'},
};
const FIELD_DEFAULTS = {room:0.3, decay:0.3};
const METERS   = ['intensity','depth','certainty','risk','scope','bandwidth','room','decay'];
const BADGE_C  = {EXPLORE:'#0369A1', FIX:'#B45309', BUILD:'#064E3B'};
const PILL_C   = ['#064E3B','#065F46','#047857','#059669'];

let isDragging = false;
let lastState  = {};

function getRange(trackId) {
  const el = document.getElementById(trackId);
  return el ? Math.max(20, el.offsetHeight - THUMB_H) : 60;
}
function setFader(field, v) {
  const f = FADERS[field]; if (!f) return;
  const r = getRange(f.track);
  document.getElementById(f.fill).style.height  = (v*100)+'%';
  document.getElementById(f.thumb).style.bottom = (v*r)+'px';
  document.getElementById(f.val).textContent    = v.toFixed(2);
}
function setMeter(field, v) {
  const f   = document.getElementById('m-'+field);
  const val = document.getElementById('mv-'+field);
  const lvl = document.getElementById('ml-'+field);
  if (f)   f.style.width = (v*100)+'%';
  if (val) val.textContent = v.toFixed(2);
  if (lvl) {
    lvl.className = 'meter-lvl '+(v>=0.7?'lvl-high':v>=0.4?'lvl-med':'lvl-low');
    lvl.textContent = v>=0.7?'HIGH':v>=0.4?'MED':'LOW';
  }
}
function setButtons(field, active) {
  document.querySelectorAll(`.btn[data-field="${field}"]`).forEach(b =>
    b.classList.toggle('active', b.dataset.val === active));
}
function setPill(id, text, color) {
  const el = document.getElementById(id); if (!el) return;
  el.textContent = text;
  el.style.background = color+'1A';
  el.style.color = color;
}
function applyState(s) {
  lastState = s;
  Object.keys(FADERS).forEach(f => setFader(f, s[f] ?? (FIELD_DEFAULTS[f] ?? 0.5)));
  METERS.forEach(f => setMeter(f, s[f] ?? (FIELD_DEFAULTS[f] ?? 0.5)));
  setButtons('mode',   s.mode);
  setButtons('stance', s.stance);
  setButtons('filter', s.filter);
  setButtons('voice',  s.voice);
  const col = BADGE_C[s.mode] || '#6EE7B7';
  const badge = document.getElementById('hdr-badge');
  badge.textContent = s.mode||'—';
  badge.style.color = col;
  badge.style.background = col+'18';
  badge.style.borderLeftColor = col;
  document.getElementById('hdr-vals').textContent =
    `I ${(s.intensity??0).toFixed(2)}  D ${(s.depth??0).toFixed(2)}  C ${(s.certainty??0).toFixed(2)}  R ${(s.risk??0).toFixed(2)}`;
  setPill('pill-mode',   s.mode  ||'—', PILL_C[0]);
  setPill('pill-stance', s.stance||'—', PILL_C[1]);
  setPill('pill-filter', s.filter||'—', PILL_C[2]);
  setPill('pill-voice',  s.voice ||'—', PILL_C[3]);
}

async function set(field, value) {
  await fetch('/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[field]:value})});
}

const es = new EventSource('/stream');
es.onmessage = e => { if (!isDragging) applyState(JSON.parse(e.data)); };
es.onerror   = () => { document.getElementById('hdr-vals').textContent = 'reconnecting…'; };

function bindDrag(el, getV, onMove, onDrop) {
  el.addEventListener('pointerdown', e => {
    e.preventDefault(); e.stopPropagation();
    try { el.setPointerCapture(e.pointerId); } catch(_) {}
    isDragging = true;
    const sy = e.clientY, sv = getV();
    function move(e2) { onMove(sy, e2.clientY, sv); }
    function up() {
      isDragging = false;
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      onDrop();
    }
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  });
}

Object.entries(FADERS).forEach(([field, ids]) => {
  const trackEl = document.getElementById(ids.track);
  const thumbEl = document.getElementById(ids.thumb);
  const getV  = () => parseFloat(document.getElementById(ids.val).textContent);
  const move  = (sy,cy,sv) => setFader(field, Math.max(0, Math.min(1, sv+(sy-cy)/getRange(ids.track))));
  const drop  = () => set(field, Math.round(getV()*1000)/1000);
  bindDrag(trackEl, getV, move, drop);
  bindDrag(thumbEl, getV, move, drop);
});

// ── RUN LOG ──────────────────────────────────────────────────────────────────
const history = [];
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function saveHistory()  { try { localStorage.setItem('ctrl_log', JSON.stringify(history.slice(0,30))); } catch(_) {} }
function loadHistory()  { try { const s=localStorage.getItem('ctrl_log'); if(s){JSON.parse(s).forEach(r=>history.push(r)); renderHistory();} } catch(_) {} }
function clearHistory() {
  if (!confirm('Clear the run log?')) return;
  history.length = 0;
  try { localStorage.removeItem('ctrl_log'); } catch(_) {}
  renderHistory();
}
function toggleCard(i) { const el=document.getElementById('hc-'+i); if(el) el.classList.toggle('open'); }
function copyResp(i, e) {
  e.stopPropagation();
  const r = history[i]; if (!r) return;
  navigator.clipboard.writeText(
    'TASK: '+r.task+'\n\nSTATE:\nMODE='+r.mode+' STANCE='+r.stance+' FILTER='+r.filter+' VOICE='+r.voice+
    '\nI='+r.intensity+' D='+r.depth+' C='+r.certainty+' R='+r.risk+
    ' SCOPE='+r.scope+' BW='+r.bandwidth+' ROOM='+r.room+' DECAY='+r.decay+
    '\n\nRESPONSE:\n'+r.resp
  ).then(() => { const btn=e.target; btn.textContent='Copied!'; setTimeout(()=>btn.textContent='Copy',1500); });
}
function renderHistory() {
  const el = document.getElementById('history');
  if (!history.length) { el.innerHTML='<div class="history-empty">no runs yet</div>'; return; }
  el.innerHTML = history.map((r,i) => `
    <div class="hc" id="hc-${i}" onclick="toggleCard(${i})">
      <div class="hc-top">
        <span class="hc-time">${esc(r.t)}</span>
        <span class="hc-mode">${esc(r.mode)}</span>
        <span class="hc-peek">I${r.intensity} D${r.depth} C${r.certainty} R${r.risk}</span>
        <span class="hc-chevron">▼</span>
      </div>
      <div class="hc-task">${esc(r.task)}</div>
      <div class="hc-preview">${esc(r.resp.slice(0,140))}${r.resp.length>140?'…':''}</div>
      <div class="hc-body">
        <div class="hc-state-grid">
          <div class="hc-si"><div class="hc-si-lbl">MODE</div><div class="hc-si-val">${esc(r.mode)}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">STANCE</div><div class="hc-si-val">${esc(r.stance)}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">FILTER</div><div class="hc-si-val">${esc(r.filter)}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">VOICE</div><div class="hc-si-val">${esc(r.voice)}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">INTENSITY</div><div class="hc-si-val">${r.intensity}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">DEPTH</div><div class="hc-si-val">${r.depth}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">CERTAINTY</div><div class="hc-si-val">${r.certainty}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">RISK</div><div class="hc-si-val">${r.risk}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">SCOPE</div><div class="hc-si-val">${r.scope}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">BANDWIDTH</div><div class="hc-si-val">${r.bandwidth}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">ROOM</div><div class="hc-si-val">${r.room}</div></div>
          <div class="hc-si"><div class="hc-si-lbl">DECAY</div><div class="hc-si-val">${r.decay}</div></div>
        </div>
        <div class="hc-full">${esc(r.resp)}</div>
        <div class="hc-actions"><button class="hc-copy" onclick="copyResp(${i},event)">Copy</button></div>
      </div>
    </div>`).join('');
}

// ── PREVIEW RUN ──────────────────────────────────────────────────────────────
const taskInput = document.getElementById('task-input');
const runBtn    = document.getElementById('run-btn');
const respWrap  = document.getElementById('resp-wrap');
const respBox   = document.getElementById('resp-box');

async function runTask() {
  const task = taskInput.value.trim();
  if (!task || runBtn.disabled) return;
  runBtn.disabled = true; runBtn.textContent = '···';
  respBox.textContent = ''; respWrap.classList.add('open');
  let full = '';
  const snap = {
    mode:      lastState.mode      || '—',
    stance:    lastState.stance    || '—',
    filter:    lastState.filter    || '—',
    voice:     lastState.voice     || '—',
    intensity: (lastState.intensity ?? 0).toFixed(2),
    depth:     (lastState.depth     ?? 0).toFixed(2),
    certainty: (lastState.certainty ?? 0).toFixed(2),
    risk:      (lastState.risk      ?? 0).toFixed(2),
    scope:     (lastState.scope     ?? 0).toFixed(2),
    bandwidth: (lastState.bandwidth ?? 0).toFixed(2),
    room:      (lastState.room      ?? 0).toFixed(2),
    decay:     (lastState.decay     ?? 0).toFixed(2),
  };
  try {
    const res = await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task})});
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const {done,value} = await reader.read(); if (done) break;
      buf += dec.decode(value,{stream:true});
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const d = JSON.parse(line.slice(6));
        if (d.text)  { full+=d.text; respBox.textContent=full; respBox.scrollTop=respBox.scrollHeight; }
        if (d.error) { respBox.innerHTML='<span class="err">'+esc(d.error)+'</span>'; }
        if (d.done)  {
          runBtn.disabled=false; runBtn.textContent='RUN';
          if (full) {
            history.unshift({t:new Date().toLocaleTimeString(), task, resp:full, ...snap});
            if (history.length>30) history.pop();
            saveHistory();
            renderHistory();
          }
        }
      }
    }
  } catch(e) {
    respBox.innerHTML='<span class="err">'+esc(e.message)+'</span>';
  } finally { runBtn.disabled=false; runBtn.textContent='RUN'; }
}
runBtn.addEventListener('click', runTask);
taskInput.addEventListener('keydown', e => { if ((e.metaKey||e.ctrlKey)&&e.key==='Enter') runTask(); });
loadHistory();

// ── FAQ ──────────────────────────────────────────────────────────────────────
function openFaq()  { document.getElementById('faq-overlay').classList.add('open'); document.getElementById('faq-panel').classList.add('open'); }
function closeFaq() { document.getElementById('faq-overlay').classList.remove('open'); document.getElementById('faq-panel').classList.remove('open'); }
document.addEventListener('keydown', e => { if (e.key==='Escape') closeFaq(); });
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"┌──────────────────────────────────────────────┐")
    print(f"│   Control  ·  visual console                 │")
    print(f"│   http://127.0.0.1:{PORT}                      │")
    print(f"│   Open on iPad: http://<your-mac-ip>:{PORT}   │")
    print(f"│   Ctrl+C to stop                             │")
    print(f"└──────────────────────────────────────────────┘")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
