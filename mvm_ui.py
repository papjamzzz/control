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
    stance    = state.get("stance",    "GUESS")

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

    if stance == "OPTIONS":
        stance_rule = "STANCE: OPTIONS — present alternatives only, do not implement anything."
    elif stance == "DECIDE":
        stance_rule = "STANCE: DECIDE — pick one approach and implement it, zero explanation of alternatives."
    else:
        stance_rule = "STANCE: GUESS — give your best recommendation with brief reasoning, then implement."

    scope     = state.get("scope",     0.5)
    bandwidth = state.get("bandwidth", 0.5)
    filter_   = state.get("filter",    "PARAMETRIC")

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

    if filter_ == "HIGHPASS":
        filter_rule = "FILTER: HIGHPASS — cut everything below this file, strict local scope."
    elif filter_ == "LOWPASS":
        filter_rule = "FILTER: LOWPASS — full spectrum allowed, global context welcome."
    else:
        filter_rule = "FILTER: PARAMETRIC — shaped band around the problem, selective context."

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

    if voice == "ANECHOIC":
        voice_rule = "VOICE: ANECHOIC — dead room, output only, zero commentary or preamble."
    elif voice == "HALL":
        voice_rule = "VOICE: HALL — full resonance, collaborative, thinks out loud with you."
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
            "certainty": 0.5, "risk": 0.5, "stance": "GUESS",
            "scope": 0.5, "bandwidth": 0.5, "filter": "PARAMETRIC",
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
body{background:#EDF4EF;font-family:'Inter',sans-serif;color:#0F2419;height:100vh;display:flex;flex-direction:column;user-select:none;overflow:hidden;}

/* HEADER */
.hdr{padding:0 20px;border-bottom:1px solid rgba(6,78,59,.08);background:#fff;display:flex;align-items:center;gap:12px;flex-shrink:0;height:34px;}
.hdr-badge{font-size:9.5px;font-weight:700;letter-spacing:.14em;padding:2px 8px 2px 6px;border-radius:3px;border-left:2px solid;transition:all .25s;}
.hdr-vals{font-size:7.5px;color:rgba(6,78,59,.38);letter-spacing:.08em;font-variant-numeric:tabular-nums;}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:8px;}
.faq-btn{width:21px;height:21px;border-radius:50%;border:1.5px solid rgba(6,78,59,.22);background:transparent;color:rgba(6,78,59,.45);font-size:11px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;line-height:1;}
.faq-btn:hover{border-color:#064E3B;color:#064E3B;background:#F0FAF4;}

/* HERO */
.hero{position:relative;flex-shrink:0;height:112px;overflow:hidden;border-bottom:1px solid rgba(6,78,59,.1);}
.hero svg{position:absolute;inset:0;width:100%;height:100%;}
.hero-left{position:absolute;left:24px;top:50%;transform:translateY(-52%);pointer-events:none;z-index:1;}
.hero-brand{font-family:'Abril Fatface',serif;font-size:68px;color:#1A0A2E;line-height:1;}
.hero-tagline{font-size:7px;font-weight:600;letter-spacing:.3em;color:rgba(26,10,46,.36);text-transform:uppercase;margin-top:3px;}
@keyframes spin-cw  {to{transform:rotate( 360deg);}}
@keyframes spin-ccw {to{transform:rotate(-360deg);}}
.gear-cw  {animation:spin-cw  12s linear infinite;transform-origin:0 0;}
.gear-ccw {animation:spin-ccw  8s linear infinite;transform-origin:0 0;}
.gear-sm  {animation:spin-cw   5s linear infinite;transform-origin:0 0;}

/* MAIN SPLIT */
.main{flex:1;display:flex;overflow:hidden;min-height:0;}

/* SURFACE PANEL (left) */
.surface{width:38%;min-width:260px;border-right:1px solid rgba(6,78,59,.1);background:#F5FBF7;display:flex;flex-direction:column;overflow:hidden;}
.panel-hd{padding:5px 12px;font-size:6.5px;font-weight:700;letter-spacing:.22em;color:rgba(6,78,59,.28);text-transform:uppercase;border-bottom:1px solid rgba(6,78,59,.06);flex-shrink:0;}
.strips-grid{flex:1;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:5px;padding:6px;min-height:0;}

/* STRIP */
.strip{background:#fff;border:1px solid rgba(6,78,59,.09);border-radius:6px;padding:8px 8px 7px;display:flex;flex-direction:column;align-items:center;gap:6px;position:relative;overflow:hidden;}
.strip-top{position:absolute;top:0;left:50%;transform:translateX(-50%);height:2px;width:36px;border-radius:0 0 2px 2px;}
.strip.t1 .strip-top{background:#064E3B;}
.strip.t2 .strip-top{background:#065F46;}
.strip.t3 .strip-top{background:#047857;}
.strip.t4 .strip-top{background:#059669;}
.strip-id{font-size:6px;font-weight:700;letter-spacing:.16em;color:rgba(6,78,59,.28);text-transform:uppercase;margin-top:2px;flex-shrink:0;}

/* KNOB */
.knob-wrap{display:flex;flex-direction:column;align-items:center;gap:3px;width:100%;flex-shrink:0;}
.knob{width:38px;height:38px;border-radius:50%;background:radial-gradient(circle at 36% 30%,#eaf3ec,#cfe3d7);border:1.5px solid rgba(6,78,59,.16);position:relative;cursor:grab;touch-action:none;}
.knob:active{cursor:grabbing;}
.knob-dot{position:absolute;width:2.5px;height:10px;background:#064E3B;border-radius:2px;top:4px;left:50%;transform-origin:50% 15px;transform:translateX(-50%) rotate(0deg);}
.knob-meta{display:flex;justify-content:space-between;width:100%;padding:0 1px;}
.knob-lbl,.knob-val{font-size:6px;letter-spacing:.08em;text-transform:uppercase;}
.knob-lbl{color:rgba(6,78,59,.38);}
.knob-val{font-weight:600;color:rgba(6,78,59,.55);font-variant-numeric:tabular-nums;}

/* FADER */
.fader-section{display:flex;flex-direction:column;align-items:center;gap:3px;flex:1;min-height:0;}
.fader-lbl{font-size:6px;color:rgba(6,78,59,.38);letter-spacing:.08em;text-transform:uppercase;flex-shrink:0;}
.fader-track{width:11px;flex:1;min-height:36px;max-height:88px;background:#E4EFE7;border:1px solid rgba(6,78,59,.13);border-radius:6px;position:relative;cursor:ns-resize;touch-action:none;}
.fader-fill{position:absolute;bottom:0;left:0;right:0;border-radius:6px;background:linear-gradient(0deg,#A7F3D0,#065F46);pointer-events:none;}
.fader-thumb{position:absolute;width:32px;height:15px;border-radius:3px;left:50%;transform:translateX(-50%);background:linear-gradient(180deg,#fff,#eaf0ec);border:1px solid rgba(6,78,59,.18);box-shadow:0 1px 5px rgba(6,78,59,.13);cursor:ns-resize;z-index:2;touch-action:none;}
.fader-thumb::before,.fader-thumb::after{content:'';position:absolute;left:20%;right:20%;height:1px;background:rgba(6,78,59,.13);}
.fader-thumb::before{top:calc(50% - 2px);}
.fader-thumb::after{top:calc(50% + 2px);}
.fader-val{font-size:6px;font-weight:600;color:rgba(6,78,59,.45);font-variant-numeric:tabular-nums;flex-shrink:0;}

/* BUTTONS */
.btns{display:flex;flex-direction:column;gap:3px;width:100%;flex-shrink:0;}
.btn{height:22px;border-radius:3px;border:1px solid rgba(6,78,59,.13);background:#fff;color:rgba(6,78,59,.38);font-size:6.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;cursor:pointer;transition:all .1s;display:flex;align-items:center;justify-content:center;}
.btn:hover{border-color:rgba(6,78,59,.3);color:rgba(6,78,59,.7);background:#F0FAF4;}
.btn.active{background:#064E3B;color:#fff;border-color:#064E3B;}

/* MONITOR PANEL (right) */
.monitor{flex:1;display:flex;flex-direction:column;overflow:hidden;background:#fff;min-width:0;}

/* METERS */
.meters-wrap{padding:10px 16px 8px;border-bottom:1px solid rgba(6,78,59,.07);flex-shrink:0;}
.section-hd{font-size:6.5px;font-weight:700;letter-spacing:.2em;color:rgba(6,78,59,.28);text-transform:uppercase;margin-bottom:7px;}
.meters-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 18px;}
.meter-row{display:flex;align-items:center;gap:5px;}
.meter-lbl{font-size:6px;color:rgba(6,78,59,.38);letter-spacing:.06em;text-transform:uppercase;width:58px;flex-shrink:0;}
.meter-track{flex:1;height:5px;background:#E4EFE7;border-radius:3px;overflow:hidden;}
.meter-fill{height:100%;background:linear-gradient(90deg,#6EE7B7 0%,#059669 55%,#F59E0B 100%);transition:width .12s ease;border-radius:3px;}
.meter-val{font-size:6px;font-weight:600;color:rgba(6,78,59,.45);font-variant-numeric:tabular-nums;width:24px;text-align:right;flex-shrink:0;}
.meter-lvl{font-size:5.5px;font-weight:700;letter-spacing:.05em;width:22px;flex-shrink:0;}
.lvl-low{color:#34D399;} .lvl-med{color:#059669;} .lvl-high{color:#F59E0B;}

/* STATE PILLS */
.pills-wrap{padding:5px 16px;border-bottom:1px solid rgba(6,78,59,.07);display:flex;gap:6px;align-items:center;flex-shrink:0;flex-wrap:wrap;}
.pill-group{display:flex;align-items:center;gap:4px;}
.pill-lbl{font-size:6px;color:rgba(6,78,59,.28);letter-spacing:.1em;text-transform:uppercase;}
.pill{padding:2px 8px;border-radius:2px;font-size:7px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;transition:all .2s;}

/* PREVIEW */
.preview-wrap{padding:9px 16px 8px;border-bottom:1px solid rgba(6,78,59,.07);flex-shrink:0;}
.preview-top{display:flex;align-items:center;gap:8px;margin-bottom:6px;}
.preview-hd{font-size:6.5px;font-weight:700;letter-spacing:.2em;color:rgba(6,78,59,.28);text-transform:uppercase;}
.api-tag{font-size:6px;font-weight:600;padding:1px 6px;border-radius:2px;background:#FEF3C7;color:#92400E;letter-spacing:.06em;}
.task-row{display:flex;gap:6px;align-items:center;}
.task-input{flex:1;height:28px;border:1.5px solid rgba(6,78,59,.16);border-radius:4px;background:#F8FDF9;padding:0 10px;font-family:'Inter',sans-serif;font-size:11px;color:#0F2419;outline:none;transition:border-color .15s;user-select:text;}
.task-input:focus{border-color:#064E3B;box-shadow:0 0 0 2px rgba(6,78,59,.06);}
.task-input::placeholder{color:rgba(6,78,59,.25);}
.run-btn{height:28px;padding:0 14px;background:#064E3B;color:#fff;border:none;border-radius:4px;font-family:'Inter',sans-serif;font-size:8.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;cursor:pointer;transition:background .12s;white-space:nowrap;}
.run-btn:hover{background:#065F46;}
.run-btn:disabled{opacity:.4;cursor:not-allowed;}
.resp-wrap{overflow:hidden;max-height:0;transition:max-height .25s ease;}
.resp-wrap.open{max-height:120px;}
.resp-box{margin-top:6px;padding:8px 11px;background:#F2FAF5;border:1px solid rgba(6,78,59,.09);border-radius:4px;font-size:10.5px;line-height:1.6;color:#0F2419;white-space:pre-wrap;max-height:110px;overflow-y:auto;font-family:'Inter',sans-serif;}
.resp-box .err{color:#B91C1C;}

/* HISTORY */
.history-wrap{flex:1;overflow-y:auto;padding:8px 16px 10px;min-height:0;}
.history-empty{font-size:10px;color:rgba(6,78,59,.22);font-style:italic;text-align:center;padding:18px 0;}
.hc{background:#F5FBF7;border:1px solid rgba(6,78,59,.07);border-radius:5px;padding:7px 9px;margin-bottom:5px;transition:border-color .1s;}
.hc:hover{border-color:rgba(6,78,59,.18);}
.hc-top{display:flex;gap:7px;align-items:center;margin-bottom:3px;}
.hc-time{font-size:6.5px;color:rgba(6,78,59,.32);font-variant-numeric:tabular-nums;}
.hc-mode{font-size:6.5px;font-weight:700;padding:1px 5px;border-radius:2px;background:#064E3B;color:#fff;letter-spacing:.08em;}
.hc-state{font-size:6.5px;color:rgba(6,78,59,.35);font-variant-numeric:tabular-nums;margin-left:auto;}
.hc-task{font-size:10px;font-weight:600;color:#0F2419;margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.hc-resp{font-size:9px;color:rgba(6,78,59,.5);line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}

/* STATUS BAR */
.statusbar{padding:5px 20px;border-top:1px solid rgba(6,78,59,.07);background:#fff;display:flex;gap:18px;font-size:7px;letter-spacing:.08em;color:rgba(6,78,59,.28);flex-shrink:0;}
.sb-item em{font-style:normal;color:rgba(6,78,59,.65);font-weight:600;}

/* FAQ */
.faq-overlay{display:none;position:fixed;inset:0;background:rgba(6,20,13,.4);z-index:100;}
.faq-overlay.open{display:block;}
.faq-panel{position:fixed;right:-500px;top:0;bottom:0;width:470px;background:#fff;z-index:101;transition:right .26s cubic-bezier(.4,0,.2,1);overflow-y:auto;border-left:1px solid rgba(6,78,59,.1);display:flex;flex-direction:column;}
.faq-panel.open{right:0;}
.faq-hd{padding:14px 18px;border-bottom:1px solid rgba(6,78,59,.08);display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
.faq-title{font-family:'Abril Fatface',serif;font-size:20px;color:#1A0A2E;}
.faq-close{width:26px;height:26px;border:none;background:transparent;cursor:pointer;font-size:14px;color:rgba(6,78,59,.38);border-radius:50%;transition:background .12s;display:flex;align-items:center;justify-content:center;}
.faq-close:hover{background:#F0FAF4;color:#064E3B;}
.faq-body{padding:18px;flex:1;}
.faq-s{margin-bottom:20px;}
.faq-s-title{font-size:8.5px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:#064E3B;margin-bottom:7px;}
.faq-p{font-size:11.5px;line-height:1.7;color:rgba(6,20,13,.65);margin-bottom:7px;}
.faq-track{margin-bottom:8px;padding:9px 11px;background:#F5FBF7;border-radius:4px;border-left:3px solid #064E3B;}
.faq-track-name{font-size:9.5px;font-weight:700;color:#064E3B;margin-bottom:2px;}
.faq-track-desc{font-size:10.5px;color:rgba(6,20,13,.55);line-height:1.55;}
.faq-code{font-family:'Courier New',monospace;font-size:11px;background:#F0F7F2;padding:7px 11px;border-radius:4px;color:#064E3B;margin:5px 0;display:block;}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-badge" id="hdr-badge">—</div>
  <div class="hdr-vals" id="hdr-vals">—</div>
  <div class="hdr-right">
    <button class="faq-btn" onclick="openFaq()">?</button>
  </div>
</div>

<div class="hero">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 112" preserveAspectRatio="xMidYMid slice">
    <defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#FFFCE0"/>
        <stop offset="100%" stop-color="#FFE033"/>
      </linearGradient>
    </defs>
    <rect width="1200" height="112" fill="url(#sky)"/>
    <g transform="translate(572,50)"><g class="gear-cw">
      <circle r="28" fill="#1A0A2E"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E" transform="rotate(45)"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E" transform="rotate(90)"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E" transform="rotate(135)"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E" transform="rotate(180)"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E" transform="rotate(225)"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E" transform="rotate(270)"/>
      <rect x="-5.5" y="-37" width="11" height="11" rx="2" fill="#1A0A2E" transform="rotate(315)"/>
      <circle r="10" fill="#FFE033"/><circle r="3" fill="#1A0A2E"/>
    </g></g>
    <g transform="translate(617,70)"><g class="gear-ccw">
      <circle r="19" fill="#1A0A2E"/>
      <rect x="-4.5" y="-26" width="9" height="8" rx="2" fill="#1A0A2E"/>
      <rect x="-4.5" y="-26" width="9" height="8" rx="2" fill="#1A0A2E" transform="rotate(60)"/>
      <rect x="-4.5" y="-26" width="9" height="8" rx="2" fill="#1A0A2E" transform="rotate(120)"/>
      <rect x="-4.5" y="-26" width="9" height="8" rx="2" fill="#1A0A2E" transform="rotate(180)"/>
      <rect x="-4.5" y="-26" width="9" height="8" rx="2" fill="#1A0A2E" transform="rotate(240)"/>
      <rect x="-4.5" y="-26" width="9" height="8" rx="2" fill="#1A0A2E" transform="rotate(300)"/>
      <circle r="7" fill="#FFE033"/><circle r="2.5" fill="#1A0A2E"/>
    </g></g>
    <g transform="translate(649,85)"><g class="gear-sm">
      <circle r="12" fill="#1A0A2E"/>
      <rect x="-3.5" y="-17" width="7" height="6" rx="2" fill="#1A0A2E"/>
      <rect x="-3.5" y="-17" width="7" height="6" rx="2" fill="#1A0A2E" transform="rotate(60)"/>
      <rect x="-3.5" y="-17" width="7" height="6" rx="2" fill="#1A0A2E" transform="rotate(120)"/>
      <rect x="-3.5" y="-17" width="7" height="6" rx="2" fill="#1A0A2E" transform="rotate(180)"/>
      <rect x="-3.5" y="-17" width="7" height="6" rx="2" fill="#1A0A2E" transform="rotate(240)"/>
      <rect x="-3.5" y="-17" width="7" height="6" rx="2" fill="#1A0A2E" transform="rotate(300)"/>
      <circle r="4" fill="#FFE033"/><circle r="1.5" fill="#1A0A2E"/>
    </g></g>
    <g transform="translate(500,103)" stroke="#1A0A2E" stroke-linecap="round" fill="none">
      <circle cx="0" cy="-24" r="6" fill="#1A0A2E" stroke="none"/>
      <line x1="0" y1="-18" x2="0" y2="-5" stroke-width="2.5"/>
      <line x1="0" y1="-13" x2="-9" y2="-6" stroke-width="2"/>
      <line x1="0" y1="-13" x2="14" y2="-30" stroke-width="2"/>
      <line x1="0" y1="-5" x2="-6" y2="7" stroke-width="2"/>
      <line x1="0" y1="-5" x2="6" y2="7" stroke-width="2"/>
    </g>
    <rect x="668" y="70" width="5" height="42" fill="#1A0A2E"/>
    <circle cx="670" cy="60" r="12" fill="#1A0A2E"/>
    <circle cx="670" cy="47" r="8" fill="#1A0A2E"/>
    <circle cx="670" cy="38" r="5" fill="#1A0A2E"/>
    <rect x="690" y="74" width="48" height="38" fill="#1A0A2E"/>
    <rect x="694" y="60" width="10" height="16" fill="#1A0A2E"/>
    <rect x="716" y="60" width="10" height="16" fill="#1A0A2E"/>
    <polygon points="744,112 744,14 757,2 770,14 770,112" fill="#1A0A2E"/>
    <circle cx="757" cy="26" r="6" fill="#FFE033" opacity="0.45"/>
    <rect x="775" y="46" width="64" height="66" fill="#1A0A2E"/>
    <ellipse cx="807" cy="46" rx="32" ry="14" fill="#1A0A2E"/>
    <circle cx="807" cy="34" r="7" fill="#FFE033" opacity="0.4"/>
    <polygon points="845,112 845,7 857,0 869,7 869,112" fill="#1A0A2E"/>
    <circle cx="857" cy="20" r="6" fill="#FFE033" opacity="0.45"/>
    <rect x="874" y="52" width="48" height="60" fill="#1A0A2E"/>
    <rect x="878" y="38" width="11" height="16" fill="#1A0A2E"/>
    <rect x="896" y="38" width="11" height="16" fill="#1A0A2E"/>
    <rect x="926" y="66" width="42" height="46" fill="#1A0A2E"/>
    <rect x="972" y="80" width="38" height="32" fill="#1A0A2E"/>
    <polygon points="926,66 947,51 968,66" fill="#1A0A2E"/>
    <rect x="1014" y="76" width="186" height="36" fill="#1A0A2E"/>
    <g transform="translate(1105,22)">
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300"/>
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300" transform="rotate(45)"/>
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300" transform="rotate(90)"/>
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300" transform="rotate(135)"/>
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300" transform="rotate(180)"/>
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300" transform="rotate(225)"/>
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300" transform="rotate(270)"/>
      <polygon points="0,-36 -5,-25 5,-25" fill="#FFB300" transform="rotate(315)"/>
      <circle r="20" fill="#FFB300"/>
      <circle cx="-5.5" cy="-2" r="2.8" fill="#1A0A2E"/>
      <circle cx=" 5.5" cy="-2" r="2.8" fill="#1A0A2E"/>
      <path d="M-6,5 Q0,13 6,5" stroke="#1A0A2E" stroke-width="2" fill="none" stroke-linecap="round"/>
    </g>
    <path d="M0,105 Q250,93 450,105 Q650,117 850,101 Q1050,87 1200,105 L1200,112 L0,112 Z" fill="#1A0A2E"/>
  </svg>
  <div class="hero-left">
    <div class="hero-brand">control</div>
    <div class="hero-tagline">you hold the dial</div>
  </div>
</div>

<div class="main">

  <!-- LEFT: CONTROL SURFACE -->
  <div class="surface">
    <div class="panel-hd">CONTROL SURFACE</div>
    <div class="strips-grid">

      <div class="strip t1">
        <div class="strip-top"></div>
        <div class="strip-id">T1 · MODE / DRIVE</div>
        <div class="knob-wrap">
          <div class="knob" id="knob-depth"><div class="knob-dot" id="kd-depth"></div></div>
          <div class="knob-meta"><span class="knob-lbl">depth</span><span class="knob-val" id="kv-depth">0.50</span></div>
        </div>
        <div class="fader-section">
          <div class="fader-lbl">intensity</div>
          <div class="fader-track" id="ft-intensity">
            <div class="fader-fill" id="ff-intensity"></div>
            <div class="fader-thumb" id="fth-intensity"></div>
          </div>
          <div class="fader-val" id="fv-intensity">0.50</div>
        </div>
        <div class="btns">
          <div class="btn" data-field="mode" data-val="EXPLORE" onclick="set('mode','EXPLORE')">EXPLORE</div>
          <div class="btn" data-field="mode" data-val="FIX"     onclick="set('mode','FIX')">FIX</div>
          <div class="btn" data-field="mode" data-val="BUILD"   onclick="set('mode','BUILD')">BUILD</div>
        </div>
      </div>

      <div class="strip t2">
        <div class="strip-top"></div>
        <div class="strip-id">T2 · CONFIDENCE</div>
        <div class="knob-wrap">
          <div class="knob" id="knob-risk"><div class="knob-dot" id="kd-risk"></div></div>
          <div class="knob-meta"><span class="knob-lbl">risk</span><span class="knob-val" id="kv-risk">0.50</span></div>
        </div>
        <div class="fader-section">
          <div class="fader-lbl">certainty</div>
          <div class="fader-track" id="ft-certainty">
            <div class="fader-fill" id="ff-certainty"></div>
            <div class="fader-thumb" id="fth-certainty"></div>
          </div>
          <div class="fader-val" id="fv-certainty">0.50</div>
        </div>
        <div class="btns">
          <div class="btn" data-field="stance" data-val="OPTIONS" onclick="set('stance','OPTIONS')">OPTIONS</div>
          <div class="btn" data-field="stance" data-val="GUESS"   onclick="set('stance','GUESS')">GUESS</div>
          <div class="btn" data-field="stance" data-val="DECIDE"  onclick="set('stance','DECIDE')">DECIDE</div>
        </div>
      </div>

      <div class="strip t3">
        <div class="strip-top"></div>
        <div class="strip-id">T3 · EQ / SCOPE</div>
        <div class="knob-wrap">
          <div class="knob" id="knob-bandwidth"><div class="knob-dot" id="kd-bandwidth"></div></div>
          <div class="knob-meta"><span class="knob-lbl">bandwidth</span><span class="knob-val" id="kv-bandwidth">0.50</span></div>
        </div>
        <div class="fader-section">
          <div class="fader-lbl">scope</div>
          <div class="fader-track" id="ft-scope">
            <div class="fader-fill" id="ff-scope"></div>
            <div class="fader-thumb" id="fth-scope"></div>
          </div>
          <div class="fader-val" id="fv-scope">0.50</div>
        </div>
        <div class="btns">
          <div class="btn" data-field="filter" data-val="HIGHPASS"   onclick="set('filter','HIGHPASS')">HIGHPASS</div>
          <div class="btn" data-field="filter" data-val="PARAMETRIC" onclick="set('filter','PARAMETRIC')">PARAMETRIC</div>
          <div class="btn" data-field="filter" data-val="LOWPASS"    onclick="set('filter','LOWPASS')">LOWPASS</div>
        </div>
      </div>

      <div class="strip t4">
        <div class="strip-top"></div>
        <div class="strip-id">T4 · ROOM / VOICE</div>
        <div class="knob-wrap">
          <div class="knob" id="knob-decay"><div class="knob-dot" id="kd-decay"></div></div>
          <div class="knob-meta"><span class="knob-lbl">decay</span><span class="knob-val" id="kv-decay">0.30</span></div>
        </div>
        <div class="fader-section">
          <div class="fader-lbl">room</div>
          <div class="fader-track" id="ft-room">
            <div class="fader-fill" id="ff-room"></div>
            <div class="fader-thumb" id="fth-room"></div>
          </div>
          <div class="fader-val" id="fv-room">0.30</div>
        </div>
        <div class="btns">
          <div class="btn" data-field="voice" data-val="ANECHOIC" onclick="set('voice','ANECHOIC')">ANECHOIC</div>
          <div class="btn" data-field="voice" data-val="STUDIO"   onclick="set('voice','STUDIO')">STUDIO</div>
          <div class="btn" data-field="voice" data-val="HALL"     onclick="set('voice','HALL')">HALL</div>
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
        <span class="api-tag">API only · no file access · not Claude Code</span>
      </div>
      <div class="task-row">
        <input class="task-input" id="task-input" type="text" placeholder="type a task to preview parameter effects…">
        <span style="font-size:7px;color:rgba(6,78,59,.25);white-space:nowrap;user-select:none">⌘↵</span>
        <button class="run-btn" id="run-btn">Run</button>
      </div>
      <div class="resp-wrap" id="resp-wrap">
        <div class="resp-box" id="resp-box"></div>
      </div>
    </div>

    <div class="history-wrap">
      <div class="section-hd">RUN HISTORY</div>
      <div id="history"><div class="history-empty">no runs yet — use <code>ctrl run</code> in terminal, or preview above</div></div>
    </div>
  </div>

</div>

<div class="statusbar">
  <span class="sb-item">MODE <em id="sb-mode">—</em></span>
  <span class="sb-item">STANCE <em id="sb-stance">—</em></span>
  <span class="sb-item">FILTER <em id="sb-filter">—</em></span>
  <span class="sb-item">VOICE <em id="sb-voice">—</em></span>
  <span style="margin-left:auto" id="sb-time">—</span>
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
      <p class="faq-p">Every knob, fader, and button adjusts a parameter in the system prompt. Same task. Different state. Measurably different output. Every time.</p>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">the four tracks</div>
      <div class="faq-track">
        <div class="faq-track-name">T1 — Mode / Drive</div>
        <div class="faq-track-desc">What Claude is doing: EXPLORE (analyze only, no edits), FIX (one root cause, one fix), BUILD (one atomic change). Intensity compresses output. Depth controls reasoning depth.</div>
      </div>
      <div class="faq-track" style="border-left-color:#065F46">
        <div class="faq-track-name" style="color:#065F46">T2 — Confidence</div>
        <div class="faq-track-desc">How committed Claude is. Certainty = how strongly it picks a path. Risk = how bold the changes. Stance: OPTIONS shows alternatives, GUESS recommends then acts, DECIDE just does it.</div>
      </div>
      <div class="faq-track" style="border-left-color:#047857">
        <div class="faq-track-name" style="color:#047857">T3 — EQ / Scope</div>
        <div class="faq-track-desc">How wide Claude looks. Scope = how much of the codebase to consider. Bandwidth = adjacent concerns. Filter: HIGHPASS (strict local), PARAMETRIC (selective), LOWPASS (global context).</div>
      </div>
      <div class="faq-track" style="border-left-color:#059669">
        <div class="faq-track-name" style="color:#059669">T4 — Room / Voice</div>
        <div class="faq-track-desc">The feel of output. Room = breathing space in the response. Decay = how long ideas echo. Voice: ANECHOIC (output only, zero preamble), STUDIO (clean and professional), HALL (thinks out loud with you).</div>
      </div>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">preview vs. ctrl run</div>
      <p class="faq-p">The <strong>Preview Run</strong> on this dashboard calls Claude API directly — same model, no tools, no file access. It's good for seeing how parameters visibly change output style.</p>
      <p class="faq-p">The real workflow is your terminal:</p>
      <code class="faq-code">ctrl run "refactor the auth module"</code>
      <p class="faq-p">This invokes Claude Code with full tool access — reads files, writes code, runs bash. The state set here (or via the physical controller) shapes how it works.</p>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">physical controller</div>
      <p class="faq-p">With a Korg nanoKONTROL2 set to External LED mode:</p>
      <code class="faq-code">ctrl nano --start</code>
      <p class="faq-p">Faders map to parameters in real time. LEDs on the hardware light up to match active button states. The controller and this dashboard share the same state file at <code style="background:#F0F7F2;padding:1px 4px;border-radius:2px;font-size:10px">~/.streamfader/state.json</code>.</p>
    </div>

    <div class="faq-s">
      <div class="faq-s-title">the proof</div>
      <p class="faq-p">Set MODE to EXPLORE, intensity LOW, stance OPTIONS. Ask Claude anything. Then flip to BUILD, intensity HIGH, stance DECIDE. Ask the same thing. The answers are measurably different — not in what Claude knows, but in how it thinks.</p>
      <p class="faq-p" style="font-style:italic;color:rgba(6,20,13,.35)">That's the machine. You hold the dial.</p>
    </div>

  </div>
</div>

<script>
const THUMB_H = 15;
const FADERS = {
  intensity: {fill:'ff-intensity', thumb:'fth-intensity', val:'fv-intensity', track:'ft-intensity'},
  certainty: {fill:'ff-certainty', thumb:'fth-certainty', val:'fv-certainty', track:'ft-certainty'},
  scope:     {fill:'ff-scope',     thumb:'fth-scope',     val:'fv-scope',     track:'ft-scope'},
  room:      {fill:'ff-room',      thumb:'fth-room',      val:'fv-room',      track:'ft-room'},
};
const KNOBS = {
  depth:     {dot:'kd-depth',     val:'kv-depth'},
  risk:      {dot:'kd-risk',      val:'kv-risk'},
  bandwidth: {dot:'kd-bandwidth', val:'kv-bandwidth'},
  decay:     {dot:'kd-decay',     val:'kv-decay'},
};
const METERS   = ['intensity','depth','certainty','risk','scope','bandwidth','room','decay'];
const BADGE_C  = {EXPLORE:'#0369A1', FIX:'#B45309', BUILD:'#064E3B'};
const PILL_C   = ['#064E3B','#065F46','#047857','#059669'];

let isDragging = false;

function getRange(trackId) {
  const el = document.getElementById(trackId);
  return el ? Math.max(20, el.offsetHeight - THUMB_H) : 70;
}
function setFader(field, v) {
  const f = FADERS[field]; if (!f) return;
  const r = getRange(f.track);
  document.getElementById(f.fill).style.height  = (v*100)+'%';
  document.getElementById(f.thumb).style.bottom = (v*r)+'px';
  document.getElementById(f.val).textContent    = v.toFixed(2);
}
function setKnob(field, v) {
  const k = KNOBS[field]; if (!k) return;
  document.getElementById(k.dot).style.transform = `translateX(-50%) rotate(${-135+v*270}deg)`;
  document.getElementById(k.val).textContent = v.toFixed(2);
}
function setMeter(field, v) {
  const f = document.getElementById('m-'+field);
  const val = document.getElementById('mv-'+field);
  const lvl = document.getElementById('ml-'+field);
  if (f)   f.style.width = (v*100)+'%';
  if (val) val.textContent = v.toFixed(2);
  if (lvl) {
    const cls = v>=0.7?'lvl-high':v>=0.4?'lvl-med':'lvl-low';
    const lbl = v>=0.7?'HIGH':v>=0.4?'MED':'LOW';
    lvl.className = 'meter-lvl '+cls;
    lvl.textContent = lbl;
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
  setFader('intensity', s.intensity ?? 0.5);
  setFader('certainty', s.certainty ?? 0.5);
  setFader('scope',     s.scope     ?? 0.5);
  setFader('room',      s.room      ?? 0.3);
  setKnob('depth',     s.depth     ?? 0.5);
  setKnob('risk',      s.risk      ?? 0.5);
  setKnob('bandwidth', s.bandwidth ?? 0.5);
  setKnob('decay',     s.decay     ?? 0.3);
  METERS.forEach(f => setMeter(f, s[f] ?? 0.5));
  setButtons('mode',   s.mode);
  setButtons('stance', s.stance);
  setButtons('filter', s.filter);
  setButtons('voice',  s.voice);
  const col = BADGE_C[s.mode] || '#555';
  const badge = document.getElementById('hdr-badge');
  badge.textContent = s.mode||'—'; badge.style.color=col; badge.style.background=col+'18'; badge.style.borderLeftColor=col;
  document.getElementById('hdr-vals').textContent =
    `I ${(s.intensity??0).toFixed(2)}  D ${(s.depth??0).toFixed(2)}  C ${(s.certainty??0).toFixed(2)}  R ${(s.risk??0).toFixed(2)}`;
  document.getElementById('sb-mode').textContent   = s.mode  ||'—';
  document.getElementById('sb-stance').textContent = s.stance||'—';
  document.getElementById('sb-filter').textContent = s.filter||'—';
  document.getElementById('sb-voice').textContent  = s.voice ||'—';
  document.getElementById('sb-time').textContent   = new Date().toLocaleTimeString();
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
    function up()    { isDragging=false; el.removeEventListener('pointermove',move); el.removeEventListener('pointerup',up); el.removeEventListener('pointercancel',up); onDrop(); }
    el.addEventListener('pointermove',move);
    el.addEventListener('pointerup',up);
    el.addEventListener('pointercancel',up);
  });
}

Object.entries(FADERS).forEach(([field, ids]) => {
  const trackEl = document.getElementById(ids.track);
  const thumbEl = document.getElementById(ids.thumb);
  const getV  = () => parseFloat(document.getElementById(ids.val).textContent);
  const move  = (sy,cy,sv) => setFader(field, Math.max(0,Math.min(1, sv+(sy-cy)/getRange(ids.track))));
  const drop  = () => set(field, Math.round(getV()*1000)/1000);
  bindDrag(trackEl, getV, move, drop);
  bindDrag(thumbEl, getV, move, drop);
});

Object.entries(KNOBS).forEach(([field, ids]) => {
  const knobEl = document.getElementById('knob-'+field);
  const getV  = () => parseFloat(document.getElementById(ids.val).textContent);
  const move  = (sy,cy,sv) => setKnob(field, Math.max(0,Math.min(1, sv+(sy-cy)/120)));
  const drop  = () => set(field, Math.round(getV()*1000)/1000);
  bindDrag(knobEl, getV, move, drop);
});

// ── RUN HISTORY ──────────────────────────────────────────────────────────────
const history = [];
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function renderHistory() {
  const el = document.getElementById('history');
  if (!history.length) { el.innerHTML='<div class="history-empty">no runs yet — use <code>ctrl run</code> in terminal, or preview above</div>'; return; }
  el.innerHTML = history.map(r=>`
    <div class="hc">
      <div class="hc-top">
        <span class="hc-time">${r.t}</span>
        <span class="hc-mode">${esc(r.mode)}</span>
        <span class="hc-state">I${r.i} D${r.d} C${r.c} R${r.r}</span>
      </div>
      <div class="hc-task">${esc(r.task)}</div>
      <div class="hc-resp">${esc(r.resp)}</div>
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
    mode: document.getElementById('sb-mode').textContent,
    i: (parseFloat(document.getElementById('mv-intensity').textContent)||0).toFixed(2),
    d: (parseFloat(document.getElementById('mv-depth').textContent)||0).toFixed(2),
    c: (parseFloat(document.getElementById('mv-certainty').textContent)||0).toFixed(2),
    r: (parseFloat(document.getElementById('mv-risk').textContent)||0).toFixed(2),
  };
  try {
    const res = await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task})});
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf='';
    while(true) {
      const {done,value} = await reader.read(); if(done) break;
      buf += dec.decode(value,{stream:true});
      const lines = buf.split('\n'); buf = lines.pop();
      for(const line of lines) {
        if(!line.startsWith('data: ')) continue;
        const d = JSON.parse(line.slice(6));
        if(d.text)  { full+=d.text; respBox.textContent=full; respBox.scrollTop=respBox.scrollHeight; }
        if(d.error) { respBox.innerHTML='<span class="err">'+esc(d.error)+'</span>'; }
        if(d.done)  {
          runBtn.disabled=false; runBtn.textContent='Run';
          if(full) {
            history.unshift({t:new Date().toLocaleTimeString(),task,resp:full,...snap});
            if(history.length>8) history.pop();
            renderHistory();
          }
        }
      }
    }
  } catch(e) {
    respBox.innerHTML='<span class="err">'+esc(e.message)+'</span>';
  } finally { runBtn.disabled=false; runBtn.textContent='Run'; }
}
runBtn.addEventListener('click', runTask);
taskInput.addEventListener('keydown', e => { if((e.metaKey||e.ctrlKey)&&e.key==='Enter') runTask(); });

// ── FAQ ──────────────────────────────────────────────────────────────────────
function openFaq()  { document.getElementById('faq-overlay').classList.add('open'); document.getElementById('faq-panel').classList.add('open'); }
function closeFaq() { document.getElementById('faq-overlay').classList.remove('open'); document.getElementById('faq-panel').classList.remove('open'); }
document.addEventListener('keydown', e => { if(e.key==='Escape') closeFaq(); });
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
