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

    if voice == "DIRECT":
        voice_rule = "VOICE: DIRECT — dead room, output only, zero commentary or preamble."
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
body{background:#D6EDE0;font-family:'Inter',sans-serif;color:#0A1F12;height:100vh;display:flex;flex-direction:column;user-select:none;overflow:hidden;}

/* HEADER */
.hdr{padding:0 20px;border-bottom:2px solid #1B5E38;background:#fff;display:flex;align-items:center;gap:12px;flex-shrink:0;height:42px;}
.hdr-badge{font-size:13px;font-weight:800;letter-spacing:.1em;padding:3px 10px 3px 8px;border-radius:3px;border-left:3px solid;transition:all .25s;}
.hdr-vals{font-size:12px;color:#1B5E38;letter-spacing:.06em;font-weight:600;font-variant-numeric:tabular-nums;}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:8px;}
.faq-btn{width:26px;height:26px;border-radius:50%;border:2px solid #1B5E38;background:transparent;color:#1B5E38;font-size:13px;font-weight:800;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;line-height:1;}
.faq-btn:hover{background:#064E3B;color:#fff;}

/* HERO */
.hero{position:relative;flex-shrink:0;height:112px;overflow:hidden;border-bottom:2px solid #1B5E38;}
.hero svg{position:absolute;inset:0;width:100%;height:100%;}
.hero-left{position:absolute;left:24px;top:50%;transform:translateY(-52%);pointer-events:none;z-index:1;}
.hero-brand{font-family:'Abril Fatface',serif;font-size:68px;color:#1A0A2E;line-height:1;}
.hero-tagline{font-size:12px;font-weight:700;letter-spacing:.28em;color:#1A0A2E;text-transform:uppercase;margin-top:4px;}

/* MAIN SPLIT */
.main{flex:1;display:flex;overflow:hidden;min-height:0;}

/* SURFACE PANEL (left) */
.surface{width:38%;min-width:280px;border-right:2px solid #1B5E38;background:#EAF6EE;display:flex;flex-direction:column;overflow:hidden;}
.panel-hd{padding:6px 14px;font-size:11px;font-weight:800;letter-spacing:.2em;color:#0A3D20;text-transform:uppercase;border-bottom:1px solid #A8D4B8;flex-shrink:0;background:#D6EDE0;}
.strips-grid{flex:1;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:6px;padding:7px;min-height:0;}

/* STRIP */
.strip{background:#fff;border:1.5px solid #8FC4A4;border-radius:7px;padding:9px 9px 8px;display:flex;flex-direction:column;align-items:center;gap:6px;position:relative;overflow:hidden;}
.strip-top{position:absolute;top:0;left:50%;transform:translateX(-50%);height:3px;width:40px;border-radius:0 0 3px 3px;}
.strip.t1 .strip-top{background:#064E3B;}
.strip.t2 .strip-top{background:#065F46;}
.strip.t3 .strip-top{background:#047857;}
.strip.t4 .strip-top{background:#059669;}
.strip-id{font-size:10px;font-weight:800;letter-spacing:.14em;color:#0A3D20;text-transform:uppercase;margin-top:3px;flex-shrink:0;}

/* KNOB */
.knob-wrap{display:flex;flex-direction:column;align-items:center;gap:4px;width:100%;flex-shrink:0;}
.knob{width:40px;height:40px;border-radius:50%;background:radial-gradient(circle at 36% 30%,#d4edda,#9ECFAF);border:2px solid #3A8A5A;position:relative;cursor:grab;touch-action:none;}
.knob:active{cursor:grabbing;}
.knob-dot{position:absolute;width:3px;height:11px;background:#064E3B;border-radius:2px;top:4px;left:50%;transform-origin:50% 16px;transform:translateX(-50%) rotate(0deg);}
.knob-meta{display:flex;justify-content:space-between;width:100%;padding:0 2px;}
.knob-lbl,.knob-val{font-size:11px;letter-spacing:.06em;text-transform:uppercase;}
.knob-lbl{color:#1B5E38;font-weight:600;}
.knob-val{font-weight:700;color:#0A3D20;font-variant-numeric:tabular-nums;}

/* FADER */
.fader-section{display:flex;flex-direction:column;align-items:center;gap:4px;flex:1;min-height:0;}
.fader-lbl{font-size:11px;color:#1B5E38;font-weight:600;letter-spacing:.06em;text-transform:uppercase;flex-shrink:0;}
.fader-track{width:13px;flex:1;min-height:40px;max-height:90px;background:#B8DECA;border:1.5px solid #3A8A5A;border-radius:7px;position:relative;cursor:ns-resize;touch-action:none;}
.fader-fill{position:absolute;bottom:0;left:0;right:0;border-radius:7px;background:linear-gradient(0deg,#6EE7B7,#064E3B);pointer-events:none;}
.fader-thumb{position:absolute;width:36px;height:16px;border-radius:4px;left:50%;transform:translateX(-50%);background:linear-gradient(180deg,#fff,#d4edda);border:2px solid #3A8A5A;box-shadow:0 2px 6px rgba(6,78,59,.3);cursor:ns-resize;z-index:2;touch-action:none;}
.fader-thumb::before,.fader-thumb::after{content:'';position:absolute;left:18%;right:18%;height:1px;background:#3A8A5A;}
.fader-thumb::before{top:calc(50% - 2px);}
.fader-thumb::after{top:calc(50% + 2px);}
.fader-val{font-size:11px;font-weight:700;color:#0A3D20;font-variant-numeric:tabular-nums;flex-shrink:0;}

/* BUTTONS */
.btns{display:flex;flex-direction:column;gap:4px;width:100%;flex-shrink:0;}
.btn{height:28px;border-radius:4px;border:1.5px solid #3A8A5A;background:#EAF6EE;color:#0A3D20;font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;cursor:pointer;transition:all .1s;display:flex;align-items:center;justify-content:center;}
.btn:hover{background:#C8E8D4;border-color:#064E3B;color:#064E3B;}
.btn.active{background:#064E3B;color:#fff;border-color:#064E3B;box-shadow:0 0 0 2px rgba(6,78,59,.25);}

/* MONITOR PANEL (right) */
.monitor{flex:1;display:flex;flex-direction:column;overflow:hidden;background:#F5FBF7;min-width:0;}

/* METERS */
.meters-wrap{padding:10px 18px 8px;border-bottom:1px solid #A8D4B8;flex-shrink:0;}
.section-hd{font-size:11px;font-weight:800;letter-spacing:.2em;color:#0A3D20;text-transform:uppercase;margin-bottom:8px;}
.meters-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 20px;}
.meter-row{display:flex;align-items:center;gap:7px;}
.meter-lbl{font-size:11px;color:#1B5E38;font-weight:600;letter-spacing:.04em;text-transform:uppercase;width:76px;flex-shrink:0;}
.meter-track{flex:1;height:7px;background:#B8DECA;border-radius:4px;overflow:hidden;border:1px solid #3A8A5A;}
.meter-fill{height:100%;background:linear-gradient(90deg,#6EE7B7 0%,#059669 55%,#F59E0B 100%);transition:width .12s ease;border-radius:3px;}
.meter-val{font-size:11px;font-weight:700;color:#0A3D20;font-variant-numeric:tabular-nums;width:30px;text-align:right;flex-shrink:0;}
.meter-lvl{font-size:10px;font-weight:800;letter-spacing:.04em;width:28px;flex-shrink:0;}
.lvl-low{color:#059669;} .lvl-med{color:#047857;} .lvl-high{color:#D97706;}

/* STATE PILLS */
.pills-wrap{padding:7px 18px;border-bottom:1px solid #A8D4B8;display:flex;gap:8px;align-items:center;flex-shrink:0;flex-wrap:wrap;background:#EAF6EE;}
.pill-group{display:flex;align-items:center;gap:5px;}
.pill-lbl{font-size:10px;color:#1B5E38;font-weight:700;letter-spacing:.1em;text-transform:uppercase;}
.pill{padding:3px 10px;border-radius:3px;font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;transition:all .2s;}

/* PREVIEW */
.preview-wrap{padding:10px 18px 9px;border-bottom:1px solid #A8D4B8;flex-shrink:0;}
.preview-top{display:flex;align-items:center;gap:10px;margin-bottom:7px;}
.preview-hd{font-size:11px;font-weight:800;letter-spacing:.18em;color:#0A3D20;text-transform:uppercase;}
.api-tag{font-size:10px;font-weight:700;padding:2px 8px;border-radius:3px;background:#FEF3C7;color:#92400E;letter-spacing:.04em;border:1px solid #FCD34D;}
.task-row{display:flex;gap:8px;align-items:center;}
.task-input{flex:1;height:34px;border:2px solid #3A8A5A;border-radius:5px;background:#fff;padding:0 12px;font-family:'Inter',sans-serif;font-size:13px;color:#0A1F12;outline:none;transition:border-color .15s;user-select:text;}
.task-input:focus{border-color:#064E3B;box-shadow:0 0 0 3px rgba(6,78,59,.12);}
.task-input::placeholder{color:#6BAE8A;}
.run-btn{height:34px;padding:0 18px;background:#064E3B;color:#fff;border:none;border-radius:5px;font-family:'Inter',sans-serif;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;cursor:pointer;transition:background .12s;white-space:nowrap;}
.run-btn:hover{background:#047857;}
.run-btn:disabled{opacity:.4;cursor:not-allowed;}
.resp-wrap{overflow:hidden;max-height:0;transition:max-height .25s ease;}
.resp-wrap.open{max-height:130px;}
.resp-box{margin-top:7px;padding:10px 13px;background:#fff;border:1.5px solid #3A8A5A;border-radius:5px;font-size:12px;line-height:1.65;color:#0A1F12;white-space:pre-wrap;max-height:120px;overflow-y:auto;font-family:'Inter',sans-serif;}
.resp-box .err{color:#B91C1C;font-weight:600;}

/* HISTORY */
.history-wrap{flex:1;overflow-y:auto;padding:9px 18px 12px;min-height:0;}
.history-empty{font-size:12px;color:#1B5E38;font-style:italic;text-align:center;padding:20px 0;}
.hc{background:#fff;border:1.5px solid #8FC4A4;border-radius:6px;padding:8px 11px;margin-bottom:6px;transition:border-color .1s;}
.hc:hover{border-color:#064E3B;}
.hc-top{display:flex;gap:8px;align-items:center;margin-bottom:4px;}
.hc-time{font-size:11px;color:#1B5E38;font-variant-numeric:tabular-nums;font-weight:600;}
.hc-mode{font-size:11px;font-weight:800;padding:1px 7px;border-radius:3px;background:#064E3B;color:#fff;letter-spacing:.08em;}
.hc-state{font-size:11px;color:#1B5E38;font-variant-numeric:tabular-nums;font-weight:600;margin-left:auto;}
.hc-task{font-size:13px;font-weight:700;color:#0A1F12;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.hc-resp{font-size:11px;color:#1B5E38;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}

/* STATUS BAR */
.statusbar{padding:6px 20px;border-top:2px solid #1B5E38;background:#D6EDE0;display:flex;gap:20px;font-size:11px;font-weight:600;letter-spacing:.08em;color:#1B5E38;flex-shrink:0;}
.sb-item em{font-style:normal;color:#0A3D20;font-weight:800;}

/* FAQ */
.faq-overlay{display:none;position:fixed;inset:0;background:rgba(6,20,13,.5);z-index:100;}
.faq-overlay.open{display:block;}
.faq-panel{position:fixed;right:-500px;top:0;bottom:0;width:480px;background:#fff;z-index:101;transition:right .26s cubic-bezier(.4,0,.2,1);overflow-y:auto;border-left:3px solid #064E3B;display:flex;flex-direction:column;}
.faq-panel.open{right:0;}
.faq-hd{padding:16px 20px;border-bottom:2px solid #1B5E38;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;background:#EAF6EE;}
.faq-title{font-family:'Abril Fatface',serif;font-size:22px;color:#1A0A2E;}
.faq-close{width:30px;height:30px;border:2px solid #1B5E38;background:transparent;cursor:pointer;font-size:16px;color:#1B5E38;border-radius:50%;transition:background .12s;display:flex;align-items:center;justify-content:center;font-weight:700;}
.faq-close:hover{background:#064E3B;color:#fff;}
.faq-body{padding:20px;flex:1;}
.faq-s{margin-bottom:22px;}
.faq-s-title{font-size:11px;font-weight:800;letter-spacing:.2em;text-transform:uppercase;color:#064E3B;margin-bottom:8px;}
.faq-p{font-size:13px;line-height:1.7;color:#0A3D20;margin-bottom:8px;}
.faq-track{margin-bottom:9px;padding:10px 13px;background:#EAF6EE;border-radius:5px;border-left:4px solid #064E3B;}
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

    <!-- ── OSCILLOSCOPE SCREEN ── -->
    <!-- outer bezel -->
    <rect x="348" y="12" width="392" height="76" rx="6" fill="#071410"/>
    <!-- inner screen -->
    <rect x="353" y="17" width="382" height="66" rx="3" fill="#0B1E15"/>
    <!-- grid horizontals -->
    <line x1="353" y1="39" x2="735" y2="39" stroke="#183325" stroke-width="0.7"/>
    <line x1="353" y1="50" x2="735" y2="50" stroke="#183325" stroke-width="0.7"/>
    <line x1="353" y1="61" x2="735" y2="61" stroke="#183325" stroke-width="0.7"/>
    <!-- grid verticals -->
    <line x1="448" y1="17" x2="448" y2="83" stroke="#183325" stroke-width="0.7"/>
    <line x1="543" y1="17" x2="543" y2="83" stroke="#183325" stroke-width="0.7"/>
    <line x1="638" y1="17" x2="638" y2="83" stroke="#183325" stroke-width="0.7"/>

    <!-- center divider — the before / after line -->
    <line x1="543" y1="12" x2="543" y2="88" stroke="#3A6A4A" stroke-width="1.2" stroke-dasharray="3,2.5"/>

    <!-- BEFORE: chaotic / untuned (amber) -->
    <path d="M357,50 L362,36 L367,63 L372,31 L377,67 L382,40 L387,61 L392,27 L397,68 L402,38 L407,58 L412,29 L417,65 L422,41 L427,59 L432,26 L437,64 L441,43 L447,50 L543,50"
          stroke="#F59E0B" stroke-width="1.6" fill="none" opacity="0.9" stroke-linejoin="round"/>
    <!-- glow behind chaotic line -->
    <path d="M357,50 L362,36 L367,63 L372,31 L377,67 L382,40 L387,61 L392,27 L397,68 L402,38 L407,58 L412,29 L417,65 L422,41 L427,59 L432,26 L437,64 L441,43 L447,50 L543,50"
          stroke="#F59E0B" stroke-width="5" fill="none" opacity="0.12" stroke-linejoin="round"/>

    <!-- AFTER: clean sine (mint) -->
    <!-- glow layer -->
    <path d="M543,50 C556,50 560,22 573,22 C586,22 590,78 603,78 C616,78 620,22 633,22 C646,22 650,78 663,78 C676,78 680,22 693,22 C706,22 710,50 731,50"
          stroke="#6EE7B7" stroke-width="6" fill="none" opacity="0.15"/>
    <!-- main line -->
    <path d="M543,50 C556,50 560,22 573,22 C586,22 590,78 603,78 C616,78 620,22 633,22 C646,22 650,78 663,78 C676,78 680,22 693,22 C706,22 710,50 731,50"
          stroke="#6EE7B7" stroke-width="2.2" fill="none"/>

    <!-- tiny labels inside screen -->
    <text x="448" y="90" font-family="monospace" font-size="5.5" fill="#F59E0B" text-anchor="middle" opacity="0.65">UNTUNED</text>
    <text x="638" y="90" font-family="monospace" font-size="5.5" fill="#6EE7B7" text-anchor="middle" opacity="0.75">CONTROLLED</text>

    <!-- corner screws -->
    <circle cx="356" cy="20" r="2.2" fill="#1E3D28"/>
    <circle cx="732" cy="20" r="2.2" fill="#1E3D28"/>
    <circle cx="356" cy="80" r="2.2" fill="#1E3D28"/>
    <circle cx="732" cy="80" r="2.2" fill="#1E3D28"/>

    <!-- bezel frame -->
    <rect x="348" y="12" width="392" height="76" rx="6" fill="none" stroke="#2A5A3A" stroke-width="2"/>

    <!-- knob below-left of screen (the operator's hand on the control) -->
    <circle cx="368" cy="96" r="8" fill="#1A0A2E"/>
    <line x1="368" y1="88" x2="368" y2="95" stroke="#FFE033" stroke-width="1.8" stroke-linecap="round"/>
    <circle cx="368" cy="96" r="8" fill="none" stroke="#2A5A3A" stroke-width="1"/>

    <!-- operator figure reaching toward screen -->
    <g transform="translate(314,103)" stroke="#1A0A2E" stroke-linecap="round" fill="none">
      <circle cx="0" cy="-22" r="5.5" fill="#1A0A2E" stroke="none"/>
      <line x1="0" y1="-16" x2="0" y2="-4" stroke-width="2.5"/>
      <line x1="0" y1="-10" x2="-8" y2="-3" stroke-width="2"/>
      <line x1="0" y1="-10" x2="50" y2="-16" stroke-width="2"/>
      <line x1="0" y1="-4" x2="-5" y2="9" stroke-width="2"/>
      <line x1="0" y1="-4" x2="5" y2="9" stroke-width="2"/>
    </g>

    <!-- ── TIM BURTON CITY (right of screen) ── -->
    <!-- topiary tree -->
    <rect x="748" y="70" width="4" height="42" fill="#1A0A2E"/>
    <circle cx="750" cy="60" r="11" fill="#1A0A2E"/>
    <circle cx="750" cy="48" r="7.5" fill="#1A0A2E"/>
    <circle cx="750" cy="39" r="5" fill="#1A0A2E"/>

    <rect x="770" y="74" width="46" height="38" fill="#1A0A2E"/>
    <rect x="774" y="60" width="10" height="16" fill="#1A0A2E"/>
    <rect x="795" y="60" width="10" height="16" fill="#1A0A2E"/>

    <polygon points="822,112 822,12 835,1 848,12 848,112" fill="#1A0A2E"/>
    <circle cx="835" cy="24" r="6" fill="#FFE033" opacity="0.45"/>

    <rect x="853" y="46" width="60" height="66" fill="#1A0A2E"/>
    <ellipse cx="883" cy="46" rx="30" ry="13" fill="#1A0A2E"/>
    <circle cx="883" cy="34" r="7" fill="#FFE033" opacity="0.38"/>

    <polygon points="919,112 919,7 931,0 943,7 943,112" fill="#1A0A2E"/>
    <circle cx="931" cy="20" r="5.5" fill="#FFE033" opacity="0.45"/>

    <rect x="947" y="54" width="46" height="58" fill="#1A0A2E"/>
    <rect x="951" y="40" width="10" height="16" fill="#1A0A2E"/>
    <rect x="969" y="40" width="10" height="16" fill="#1A0A2E"/>

    <rect x="997" y="68" width="38" height="44" fill="#1A0A2E"/>
    <rect x="1039" y="76" width="36" height="36" fill="#1A0A2E"/>
    <polygon points="997,68 1016,52 1035,68" fill="#1A0A2E"/>
    <rect x="1079" y="74" width="121" height="38" fill="#1A0A2E"/>

    <!-- ── SUN top right ── -->
    <g transform="translate(1110,24)">
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300"/>
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300" transform="rotate(45)"/>
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300" transform="rotate(90)"/>
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300" transform="rotate(135)"/>
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300" transform="rotate(180)"/>
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300" transform="rotate(225)"/>
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300" transform="rotate(270)"/>
      <polygon points="0,-36 -5,-24 5,-24" fill="#FFB300" transform="rotate(315)"/>
      <circle r="21" fill="#FFB300"/>
      <circle cx="-5.5" cy="-2" r="2.8" fill="#1A0A2E"/>
      <circle cx=" 5.5" cy="-2" r="2.8" fill="#1A0A2E"/>
      <path d="M-6,5 Q0,13 6,5" stroke="#1A0A2E" stroke-width="2" fill="none" stroke-linecap="round"/>
    </g>

    <!-- ── GROUND WAVE ── -->
    <path d="M0,105 Q250,93 450,105 Q650,117 850,101 Q1050,87 1200,105 L1200,112 L0,112 Z" fill="#1A0A2E"/>
  </svg>
  <div class="hero-left">
    <div class="hero-brand">control</div>
    <div class="hero-tagline">dial it in.</div>
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
          <div class="btn" data-field="voice" data-val="DIRECT" onclick="set('voice','DIRECT')">DIRECT</div>
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
        <div class="faq-track-desc">The feel of output. Room = breathing space in the response. Decay = how long ideas echo. Voice: DIRECT (output only, zero preamble), STUDIO (clean and professional), HALL (thinks out loud with you).</div>
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
