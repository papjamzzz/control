#!/usr/bin/env python3
"""Control — visual console UI"""

import json
import time
import os
import importlib.util
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


# Load build_system_prompt from ctrl script without importing the whole CLI
import importlib.machinery
_ctrl_path = Path(__file__).resolve().parent / "ctrl"
if _ctrl_path.exists():
    _loader = importlib.machinery.SourceFileLoader("_ctrl", str(_ctrl_path))
    _spec   = importlib.util.spec_from_loader("_ctrl", _loader)
    _ctrl   = importlib.util.module_from_spec(_spec)
    _loader.exec_module(_ctrl)
    _build_prompt = _ctrl.build_system_prompt
else:
    _build_prompt = lambda s: "You are a helpful AI assistant."


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

@app.route("/exec", methods=["POST"])
def exec_task():
    """Run Claude Code directly with current fader state — full file access."""
    import subprocess, shutil as _shutil
    data = request.get_json() or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "No task provided"}), 400

    pid_file  = Path.home() / ".streamfader" / "ctrl.pid"
    last_file = Path.home() / ".streamfader" / "last_task.txt"

    # Build the claude command directly — bypass ctrl run to keep stdout attached
    state = read_state()
    try:
        cmd = _ctrl.build_cmd(state, task)
    except SystemExit as e:
        return jsonify({"error": f"claude not found in PATH: {e}"}), 500

    def generate():
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            try:
                pid_file.parent.mkdir(parents=True, exist_ok=True)
                pid_file.write_text(str(proc.pid))
                last_file.write_text(task)
            except Exception:
                pass
            for line in iter(proc.stdout.readline, ""):
                yield f"data: {json.dumps({'text': line})}\n\n"
            proc.wait()
            yield f"data: {json.dumps({'done': True, 'exit_code': proc.returncode})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass

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
:root {
  --bg:        #16191C;
  --panel:     #1E2226;
  --panel2:    #272C32;
  --border:    #2E3439;
  --border2:   #3C444C;
  --accent:    #C8922A;
  --accent2:   #E8A830;
  --green:     #6EE7B7;
  --text:      #C8D0D8;
  --text2:     #62707C;
  --text3:     #424C56;
  --chrome:    #7A8490;
  --chrome2:   #B8C4CC;
  --fader-bg:  #0E1114;
  --fader-trk: #0A0D10;
  --thumb-hi:  #C8D0D8;
  --thumb-lo:  #48545E;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);font-family:'Inter',sans-serif;color:var(--text);height:100vh;display:flex;flex-direction:column;user-select:none;overflow:hidden;}

/* ── HEADER ─────────────────────────────────────────────── */
.hdr{
  padding:0 16px;
  border-bottom:1px solid var(--border);
  background:#111416;
  display:flex;align-items:center;gap:10px;
  flex-shrink:0;height:42px;
}
.logo-mark{flex-shrink:0;}
.brand{font-family:'Abril Fatface',serif;font-size:17px;color:var(--accent2);letter-spacing:.02em;line-height:1;}
.hdr-sep{width:1px;height:18px;background:var(--border);flex-shrink:0;}
.hdr-badge{
  font-size:10px;font-weight:800;letter-spacing:.12em;
  padding:2px 8px;border-radius:2px;border-left:2px solid;
  transition:all .25s;
}
.hdr-vals{font-size:10px;color:var(--text2);letter-spacing:.06em;font-weight:600;font-variant-numeric:tabular-nums;}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:8px;}
.faq-btn{
  width:24px;height:24px;border-radius:50%;
  border:1px solid var(--border2);background:transparent;
  color:var(--text2);font-size:11px;font-weight:800;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  transition:all .15s;line-height:1;
}
.faq-btn:hover{background:var(--panel2);color:var(--accent2);border-color:var(--accent);}

/* ── HERO ───────────────────────────────────────────────── */
.hero{position:relative;flex-shrink:0;height:108px;overflow:hidden;border-bottom:2px solid var(--border);}
.hero svg{position:absolute;inset:0;width:100%;height:100%;}
.hero-left{position:absolute;left:22px;top:50%;transform:translateY(-52%);pointer-events:none;z-index:1;}
.hero-brand{font-family:'Abril Fatface',serif;font-size:62px;color:#1A0A2E;line-height:1;}
.hero-tagline{font-size:11px;font-weight:700;letter-spacing:.28em;color:#1A0A2E;text-transform:uppercase;margin-top:4px;}

/* ── MAIN 3-COLUMN CONSOLE ──────────────────────────────── */
.console{flex:1;display:flex;overflow:hidden;min-height:0;}

/* ── CHANNEL STRIP (shared L/R) ─────────────────────────── */
.channel-bank{
  width:148px;flex-shrink:0;
  display:flex;flex-direction:column;
  background:linear-gradient(180deg,#1A1E22 0%,#141820 100%);
  border-right:1px solid var(--border);
  overflow:hidden;
  box-shadow:inset -1px 0 0 rgba(255,255,255,.03);
}
.channel-bank.right{border-right:none;border-left:1px solid var(--border);}
.bank-hd{
  padding:4px 10px;
  font-size:8px;font-weight:800;letter-spacing:.22em;
  color:var(--text3);text-transform:uppercase;
  border-bottom:1px solid var(--border);
  background:#111416;flex-shrink:0;
}

/* each individual channel strip */
.ch{
  flex:1;display:flex;flex-direction:column;align-items:center;
  border-bottom:1px solid var(--border);
  padding:10px 6px 8px;gap:0;min-height:0;overflow:hidden;
  background:linear-gradient(160deg,#252A2F 0%,#1A1E22 40%,#1E2226 100%);
  position:relative;
}
.ch:last-child{border-bottom:none;}

/* colored top accent per channel */
.ch-accent{position:absolute;top:0;left:0;right:0;height:3px;}
.ch.t1 .ch-accent{background:linear-gradient(90deg,#C8922A,#E8A830);}
.ch.t2 .ch-accent{background:linear-gradient(90deg,#A87820,#C89028);}
.ch.t3 .ch-accent{background:linear-gradient(90deg,#20887A,#30A890);}
.ch.t4 .ch-accent{background:linear-gradient(90deg,#1A6868,#288888);}

.ch-id{
  font-size:8px;font-weight:800;letter-spacing:.2em;
  color:var(--text2);text-transform:uppercase;
  margin-top:6px;margin-bottom:10px;flex-shrink:0;
}

/* ── HARDWARE FADER ─────────────────────────────────────── */
.fader-wrap{
  display:flex;flex-direction:column;align-items:center;
  flex:1;min-height:80px;max-height:240px;
  width:100%;gap:4px;
}
.fader-lbl{font-size:8px;color:var(--text2);font-weight:700;letter-spacing:.1em;text-transform:uppercase;flex-shrink:0;}

/* the rail assembly */
.fader-rail{
  position:relative;
  width:100%;flex:1;min-height:60px;
  display:flex;justify-content:center;align-items:stretch;
}
/* tick marks column — left of the groove */
.fader-ticks{
  position:absolute;right:calc(50% + 9px);top:0;bottom:0;
  width:14px;display:flex;flex-direction:column;
  justify-content:space-between;padding:0;
  pointer-events:none;
}
.tick{
  display:flex;align-items:center;gap:2px;justify-content:flex-end;
  height:1px;
}
.tick-line{height:1px;background:var(--border2);flex-shrink:0;}
.tick-line.major{background:var(--chrome);height:1px;}
.tick-lbl{
  font-size:6px;color:var(--text3);font-variant-numeric:tabular-nums;
  font-weight:600;letter-spacing:0;line-height:1;white-space:nowrap;
}

/* the groove/track */
.fader-track{
  width:10px;flex:1;
  background:linear-gradient(180deg,#08090C 0%,#0C0E12 50%,#08090C 100%);
  border:1px solid #1A2028;
  border-radius:2px;
  position:relative;
  cursor:ns-resize;
  touch-action:none;
  box-shadow:inset 0 2px 4px rgba(0,0,0,.9),inset 0 0 0 1px rgba(255,255,255,.04),0 0 0 1px rgba(255,255,255,.02);
}
/* fill bar inside groove */
.fader-fill{
  position:absolute;bottom:0;left:0;right:0;
  border-radius:3px;
  background:linear-gradient(0deg,var(--accent) 0%,var(--accent2) 60%,#E8C060 100%);
  opacity:.28;
  pointer-events:none;
}

/* the hardware thumb cap */
.fader-thumb{
  position:absolute;
  width:34px;height:18px;
  left:50%;transform:translateX(-50%);
  cursor:ns-resize;z-index:3;touch-action:none;
  border-radius:3px;
  /* machined steel look */
  background:linear-gradient(180deg,
    var(--thumb-hi) 0%,
    #A8B4BC 18%,
    #58666E 35%,
    #38444C 48%,
    #38444C 52%,
    #58666E 65%,
    #A8B4BC 82%,
    var(--thumb-hi) 100%
  );
  border:1px solid #1C2830;
  border-top-color:#C8D4DC;
  border-bottom-color:#18222A;
  box-shadow:
    0 2px 6px rgba(0,0,0,.6),
    0 0 0 1px rgba(255,255,255,.08),
    inset 0 1px 0 rgba(255,255,255,.15);
}
/* grip lines on thumb */
.fader-thumb::before,.fader-thumb::after{
  content:'';position:absolute;
  left:16%;right:16%;height:1px;
  background:linear-gradient(90deg,transparent,rgba(0,0,0,.5) 20%,rgba(0,0,0,.5) 80%,transparent);
}
.fader-thumb::before{top:calc(50% - 2px);}
.fader-thumb::after {top:calc(50% + 2px);}
/* center line on thumb */
.fader-thumb .thumb-center{
  position:absolute;left:25%;right:25%;top:50%;
  height:1px;transform:translateY(-50%);
  background:rgba(255,255,255,.18);
}

.fader-val{
  font-size:8px;font-weight:700;color:var(--accent);
  font-variant-numeric:tabular-nums;flex-shrink:0;
}

/* ── HARDWARE KNOB ──────────────────────────────────────── */
.knob-wrap{
  display:flex;flex-direction:column;align-items:center;
  gap:4px;width:100%;flex-shrink:0;
  padding:8px 0 6px;
  border-top:1px solid var(--border);
}
.knob-lbl{font-size:8px;color:var(--text2);font-weight:700;letter-spacing:.1em;text-transform:uppercase;}
.knob{
  width:38px;height:38px;border-radius:50%;
  position:relative;cursor:grab;touch-action:none;
  /* outer ring */
  background:conic-gradient(
    var(--border2) 0deg,
    var(--accent) 0deg 0deg,
    var(--border2) 0deg 360deg
  );
  box-shadow:
    0 3px 8px rgba(0,0,0,.7),
    0 1px 2px rgba(0,0,0,.5),
    inset 0 1px 0 rgba(255,255,255,.06);
}
.knob:active{cursor:grabbing;}
/* inner body */
.knob-body{
  position:absolute;inset:4px;border-radius:50%;
  background:radial-gradient(circle at 38% 32%,#3A4450,#141C24);
  border:1px solid rgba(0,0,0,.5);
  box-shadow:inset 0 1px 3px rgba(255,255,255,.06);
}
/* indicator dot */
.knob-dot{
  position:absolute;
  width:3px;height:10px;
  background:var(--accent2);
  border-radius:1px;
  top:7px;left:50%;
  transform-origin:50% calc(50% + 12px - 7px);
  transform:translateX(-50%) rotate(0deg);
  box-shadow:0 0 4px rgba(232,168,48,.6);
}
.knob-val{font-size:8px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums;}

/* ── CHANNEL BUTTONS ────────────────────────────────────── */
.ch-btns{
  display:flex;flex-direction:column;
  gap:3px;width:100%;flex-shrink:0;
  border-top:1px solid var(--border);
  padding-top:7px;
}
.ch-btn{
  height:26px;border-radius:3px;
  border:1px solid var(--border2);
  background:var(--fader-bg);
  color:var(--text2);
  font-size:9px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;
  cursor:pointer;transition:all .1s;
  display:flex;align-items:center;justify-content:center;
}
.ch-btn:hover{background:var(--panel2);border-color:var(--accent);color:var(--accent2);}
.ch-btn.active{
  background:linear-gradient(180deg,#1A1E10,#12160A);
  color:var(--accent2);border-color:var(--accent);
  box-shadow:0 0 8px rgba(200,146,42,.25),inset 0 1px 0 rgba(255,255,255,.05);
}

/* ── CENTER MONITORING PANEL ───────────────────────────── */
.monitor{
  flex:1;display:flex;flex-direction:column;
  overflow:hidden;background:#111416;min-width:0;
}
.panel-hd{
  padding:4px 14px;font-size:9px;font-weight:800;
  letter-spacing:.24em;color:var(--chrome);text-transform:uppercase;
  border-bottom:1px solid var(--border);background:#0E1114;flex-shrink:0;
}

/* METERS */
.meters-wrap{padding:8px 14px 7px;border-bottom:1px solid var(--border);flex-shrink:0;}
.section-hd{font-size:9px;font-weight:800;letter-spacing:.22em;color:var(--chrome2);text-transform:uppercase;margin-bottom:6px;}
.meters-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;}
.meter-row{display:flex;align-items:center;gap:5px;}
.meter-lbl{font-size:9px;color:var(--text);font-weight:700;letter-spacing:.04em;text-transform:uppercase;width:60px;flex-shrink:0;}
.meter-track{flex:1;height:4px;background:#0A0806;border-radius:2px;overflow:hidden;border:1px solid var(--border);}
.meter-fill{height:100%;background:linear-gradient(90deg,#4A8060 0%,var(--accent) 65%,#E8A030 100%);transition:width .12s ease;border-radius:1px;}
.meter-val{font-size:10px;font-weight:700;color:var(--accent2);font-variant-numeric:tabular-nums;width:28px;text-align:right;flex-shrink:0;}
.meter-lvl{font-size:8px;font-weight:800;letter-spacing:.04em;width:26px;flex-shrink:0;}
.lvl-low{color:#4A8060;}.lvl-med{color:var(--accent);}.lvl-high{color:#E8A030;}

/* PILLS */
.pills-wrap{padding:5px 14px;border-bottom:1px solid var(--border);display:flex;gap:6px;align-items:center;flex-shrink:0;flex-wrap:wrap;}
.pill-group{display:flex;align-items:center;gap:4px;}
.pill-lbl{font-size:8px;color:var(--chrome);font-weight:700;letter-spacing:.12em;text-transform:uppercase;}
.pill{padding:2px 8px;border-radius:2px;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;transition:all .2s;}

/* PREVIEW RUN */
.preview-wrap{padding:8px 14px 7px;border-bottom:1px solid var(--border);flex-shrink:0;}
.preview-top{display:flex;align-items:center;gap:8px;margin-bottom:5px;}
.preview-hd{font-size:8px;font-weight:800;letter-spacing:.2em;color:var(--text3);text-transform:uppercase;}
.api-tag{font-size:8px;font-weight:700;padding:2px 6px;border-radius:2px;background:rgba(200,146,42,.1);color:#A87820;letter-spacing:.04em;border:1px solid rgba(200,146,42,.25);}
.task-row{display:flex;gap:6px;align-items:center;}
.launch-wrap{
  padding:10px 14px 8px;border-bottom:1px solid var(--border);
  display:flex;gap:7px;align-items:center;flex-shrink:0;
}
.launch-input{
  flex:1;height:32px;border:1px solid var(--border2);border-radius:3px;
  background:#0A0D10;padding:0 10px;
  font-family:'Inter',sans-serif;font-size:12px;color:var(--text);
  outline:none;transition:border-color .15s;user-select:text;
}
.launch-input:focus{border-color:var(--green);box-shadow:0 0 0 2px rgba(110,231,183,.07);}
.launch-input::placeholder{color:var(--text3);}
.launch-btn{
  height:32px;padding:0 16px;
  background:linear-gradient(180deg,#0E2820,#091C14);
  color:var(--green);
  border:1px solid rgba(110,231,183,.35);
  border-radius:3px;
  font-family:'Inter',sans-serif;font-size:9px;font-weight:800;
  letter-spacing:.14em;text-transform:uppercase;
  cursor:pointer;transition:all .12s;white-space:nowrap;
  box-shadow:0 0 8px rgba(110,231,183,.10);
}
.launch-btn:hover{background:linear-gradient(180deg,#122E22,#0D2018);box-shadow:0 0 14px rgba(110,231,183,.2);}
.launch-btn:disabled{opacity:.3;cursor:not-allowed;box-shadow:none;}
.launch-running{font-size:9px;color:var(--green);letter-spacing:.06em;display:none;}
.launch-running.show{display:block;}
.task-input{
  flex:1;height:30px;border:1px solid var(--border2);border-radius:3px;
  background:#0A0806;padding:0 10px;
  font-family:'Inter',sans-serif;font-size:12px;color:var(--text);
  outline:none;transition:border-color .15s;user-select:text;
}
.task-input:focus{border-color:var(--accent);box-shadow:0 0 0 2px rgba(200,146,42,.08);}
.task-input::placeholder{color:var(--text3);}
.run-btn{
  height:30px;padding:0 14px;
  background:linear-gradient(180deg,#2A2010,#1C180C);
  color:var(--accent2);
  border:1px solid var(--accent);
  border-radius:3px;
  font-family:'Inter',sans-serif;font-size:9px;font-weight:800;
  letter-spacing:.14em;text-transform:uppercase;
  cursor:pointer;transition:all .12s;white-space:nowrap;
  box-shadow:0 0 8px rgba(200,146,42,.15);
}
.run-btn:hover{background:linear-gradient(180deg,#382A14,#2A2010);box-shadow:0 0 12px rgba(200,146,42,.25);}
.run-btn:disabled{opacity:.3;cursor:not-allowed;box-shadow:none;}
.resp-wrap{overflow:hidden;max-height:0;transition:max-height .25s ease;}
.resp-wrap.open{max-height:110px;}
.resp-box{
  margin-top:5px;padding:8px 10px;
  background:#0A0806;border:1px solid var(--border);border-radius:3px;
  font-size:11px;line-height:1.6;color:var(--text);
  white-space:pre-wrap;max-height:100px;overflow-y:auto;
  font-family:'Inter',sans-serif;
}
.resp-box .err{color:#E05050;font-weight:600;}

/* LIVE PROMPT PREVIEW */
.prompt-preview-wrap{flex:1;display:flex;flex-direction:column;min-height:0;border-bottom:1px solid var(--border);}
.prompt-preview-hd{padding:4px 14px;font-size:9px;font-weight:800;letter-spacing:.22em;color:var(--chrome);text-transform:uppercase;border-bottom:1px solid var(--border);background:#0E1114;flex-shrink:0;}
.prompt-preview-box{flex:1;overflow-y:auto;padding:8px 14px;font-family:monospace;font-size:9.5px;line-height:1.6;color:var(--text2);white-space:pre-wrap;word-break:break-word;}
.prompt-preview-box .pp-key{color:var(--accent2);font-weight:700;}
.prompt-preview-box .pp-val{color:var(--text);}

/* INFO BOX */
.info-wrap{flex-shrink:0;border-top:1px solid var(--border);padding:7px 14px;background:#0E1114;min-height:62px;display:flex;flex-direction:column;justify-content:center;}
.info-label{font-size:9px;font-weight:800;color:var(--accent);text-transform:uppercase;letter-spacing:.1em;margin-bottom:3px;}
.info-text{font-size:11px;color:var(--text);line-height:1.5;}

/* HISTORY */
.history-wrap{flex-shrink:0;height:90px;overflow-y:auto;padding:6px 14px 8px;border-top:1px solid var(--border);}
.history-empty{font-size:11px;color:var(--text3);font-style:italic;text-align:center;padding:14px 0;}
.history-hd-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;}
.clear-btn{height:20px;padding:0 8px;border-radius:2px;border:1px solid var(--border);background:transparent;color:var(--text3);font-size:8px;font-weight:700;cursor:pointer;letter-spacing:.06em;text-transform:uppercase;transition:all .1s;}
.clear-btn:hover{background:#4A1010;color:#F08080;border-color:#7F1D1D;}
.hc{background:var(--panel);border:1px solid var(--border);border-radius:3px;padding:6px 9px;margin-bottom:4px;cursor:pointer;transition:border-color .1s;}
.hc:hover{border-color:var(--border2);}
.hc.open{border-color:var(--accent);}
.hc-top{display:flex;gap:6px;align-items:center;margin-bottom:3px;}
.hc-time{font-size:9px;color:var(--text3);font-variant-numeric:tabular-nums;font-weight:600;}
.hc-mode{font-size:9px;font-weight:800;padding:1px 5px;border-radius:2px;background:var(--panel2);color:var(--accent2);letter-spacing:.08em;border:1px solid var(--border2);}
.hc-peek{font-size:9px;color:var(--text3);font-weight:600;margin-left:auto;font-variant-numeric:tabular-nums;}
.hc-chevron{font-size:8px;color:var(--text3);transition:transform .15s;flex-shrink:0;}
.hc.open .hc-chevron{transform:rotate(180deg);}
.hc-task{font-size:12px;font-weight:700;color:var(--text);margin-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.hc-preview{font-size:10px;color:var(--text3);line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.hc-body{display:none;margin-top:7px;padding-top:7px;border-top:1px solid var(--border);}
.hc.open .hc-body{display:block;}
.hc-state-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:3px;margin-bottom:7px;}
.hc-si{background:var(--fader-bg);border-radius:2px;padding:4px 5px;border:1px solid var(--border);}
.hc-si-lbl{font-size:7px;color:var(--text3);font-weight:700;text-transform:uppercase;letter-spacing:.06em;}
.hc-si-val{font-size:11px;color:var(--accent2);font-weight:800;margin-top:1px;font-variant-numeric:tabular-nums;}
.hc-full{font-size:11px;line-height:1.6;color:var(--text);white-space:pre-wrap;background:#0A0806;border:1px solid var(--border);border-radius:3px;padding:8px 10px;max-height:180px;overflow-y:auto;margin-bottom:6px;font-family:'Inter',sans-serif;}
.hc-actions{display:flex;gap:5px;justify-content:flex-end;}
.hc-copy{height:24px;padding:0 10px;border-radius:2px;border:1px solid var(--border2);background:var(--panel);color:var(--text2);font-size:9px;font-weight:700;cursor:pointer;transition:all .1s;letter-spacing:.06em;text-transform:uppercase;}
.hc-copy:hover{background:var(--panel2);color:var(--accent2);border-color:var(--accent);}

/* FAQ PANEL */
.faq-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:100;}
.faq-overlay.open{display:block;}
.faq-panel{position:fixed;right:-500px;top:0;bottom:0;width:480px;background:var(--panel);z-index:101;transition:right .26s cubic-bezier(.4,0,.2,1);overflow-y:auto;border-left:2px solid var(--accent);display:flex;flex-direction:column;}
.faq-panel.open{right:0;}
.faq-hd{padding:13px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-shrink:0;background:#0D0A07;}
.faq-title{font-family:'Abril Fatface',serif;font-size:20px;color:var(--accent2);}
.faq-close{width:26px;height:26px;border:1px solid var(--border2);background:transparent;cursor:pointer;font-size:13px;color:var(--text2);border-radius:50%;transition:background .12s;display:flex;align-items:center;justify-content:center;font-weight:700;}
.faq-close:hover{background:var(--panel2);color:var(--accent2);border-color:var(--accent);}
.faq-body{padding:18px;flex:1;}
.faq-s{margin-bottom:20px;}
.faq-s-title{font-size:8px;font-weight:800;letter-spacing:.24em;text-transform:uppercase;color:var(--accent2);margin-bottom:7px;}
.faq-p{font-size:12px;line-height:1.7;color:var(--text2);margin-bottom:7px;}
.faq-track{margin-bottom:8px;padding:9px 12px;background:#0D0A07;border-radius:3px;border-left:3px solid var(--accent);}
.faq-track-name{font-size:10px;font-weight:800;color:var(--accent2);margin-bottom:3px;letter-spacing:.06em;}
.faq-track-desc{font-size:11px;color:var(--text2);line-height:1.6;}
.faq-code{font-family:'Courier New',monospace;font-size:11px;background:#0A0806;padding:7px 10px;border-radius:3px;color:var(--accent2);margin:5px 0;display:block;border:1px solid var(--border);}
</style>
</head>
<body>

<!-- ── HEADER ─────────────────────────────────────────────────── -->
<div class="hdr">
  <svg class="logo-mark" width="56" height="28" viewBox="0 0 56 28" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="56" height="28" rx="3" fill="#071410"/>
    <rect x="2" y="2" width="52" height="24" rx="2" fill="#0B1E15"/>
    <line x1="2" y1="10" x2="54" y2="10" stroke="#183325" stroke-width="0.5"/>
    <line x1="2" y1="14" x2="54" y2="14" stroke="#183325" stroke-width="0.5"/>
    <line x1="2" y1="18" x2="54" y2="18" stroke="#183325" stroke-width="0.5"/>
    <line x1="28" y1="2" x2="28" y2="26" stroke="#3A6A4A" stroke-width="0.8" stroke-dasharray="2,2"/>
    <polyline points="3,14 5,9 7,19 9,7 11,20 13,11 15,17 17,6 19,18 21,14 28,14" stroke="#F59E0B" stroke-width="1.3" stroke-linejoin="round" fill="none"/>
    <path d="M28,14 C31,14 32,5 34,5 C36,5 37,23 39,23 C41,23 42,5 44,5 C46,5 47,14 53,14" stroke="#6EE7B7" stroke-width="1.8" fill="none"/>
    <circle cx="4" cy="4" r="1.2" fill="#1E3D28"/>
    <circle cx="52" cy="4" r="1.2" fill="#1E3D28"/>
    <circle cx="4" cy="24" r="1.2" fill="#1E3D28"/>
    <circle cx="52" cy="24" r="1.2" fill="#1E3D28"/>
    <rect width="56" height="28" rx="3" fill="none" stroke="#2A5A3A" stroke-width="1"/>
  </svg>
  <span class="brand">control</span>
  <div class="hdr-sep"></div>
  <div class="hdr-badge" id="hdr-badge">—</div>
  <div class="hdr-vals" id="hdr-vals">—</div>
  <div class="hdr-right">
    <button class="faq-btn" onclick="openFaq()">?</button>
  </div>
</div>

<!-- ── HERO BANNER ─────────────────────────────────────────────── -->
<div class="hero">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 108" preserveAspectRatio="xMidYMid slice">
    <defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#FFFCE0"/>
        <stop offset="100%" stop-color="#FFE033"/>
      </linearGradient>
    </defs>
    <rect width="1200" height="108" fill="url(#sky)"/>


    <!-- TIM BURTON CITY (right) -->
    <rect x="748" y="68" width="4" height="40" fill="#1A0A2E"/>
    <circle cx="750" cy="58" r="11" fill="#1A0A2E"/>
    <circle cx="750" cy="46" r="7.5" fill="#1A0A2E"/>
    <circle cx="750" cy="37" r="5" fill="#1A0A2E"/>
    <rect x="770" y="72" width="46" height="36" fill="#1A0A2E"/>
    <rect x="774" y="58" width="10" height="16" fill="#1A0A2E"/>
    <rect x="795" y="58" width="10" height="16" fill="#1A0A2E"/>
    <polygon points="822,108 822,10 835,0 848,10 848,108" fill="#1A0A2E"/>
    <circle cx="835" cy="22" r="6" fill="#FFE033" opacity="0.45"/>
    <rect x="853" y="44" width="60" height="64" fill="#1A0A2E"/>
    <ellipse cx="883" cy="44" rx="30" ry="13" fill="#1A0A2E"/>
    <circle cx="883" cy="32" r="7" fill="#FFE033" opacity="0.38"/>
    <polygon points="919,108 919,5 931,0 943,5 943,108" fill="#1A0A2E"/>
    <circle cx="931" cy="18" r="5.5" fill="#FFE033" opacity="0.45"/>
    <rect x="947" y="52" width="46" height="56" fill="#1A0A2E"/>
    <rect x="951" y="38" width="10" height="16" fill="#1A0A2E"/>
    <rect x="969" y="38" width="10" height="16" fill="#1A0A2E"/>
    <rect x="997" y="66" width="38" height="42" fill="#1A0A2E"/>
    <rect x="1039" y="74" width="36" height="34" fill="#1A0A2E"/>
    <polygon points="997,66 1016,50 1035,66" fill="#1A0A2E"/>
    <rect x="1079" y="72" width="121" height="36" fill="#1A0A2E"/>

    <!-- SUN -->
    <g transform="translate(1110,42)">
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
    <!-- GROUND WAVE -->
    <path d="M0,102 Q250,90 450,102 Q650,114 850,98 Q1050,84 1200,102 L1200,108 L0,108 Z" fill="#1A0A2E"/>
  </svg>
  <div class="hero-left">
    <div class="hero-brand">control</div>
    <div class="hero-tagline">dial it in.</div>
  </div>
</div>

<!-- ── 3-COLUMN CONSOLE ────────────────────────────────────────── -->
<div class="console">

  <!-- LEFT BANK: T1 + T2 -->
  <div class="channel-bank">
    <div class="bank-hd">T1 · T2</div>

    <!-- CHANNEL T1: MODE / DRIVE -->
    <div class="ch t1">
      <div class="ch-accent"></div>
      <div class="ch-id">T1 — MODE</div>

      <div class="fader-wrap">
        <div class="fader-lbl">INTENSITY</div>
        <div class="fader-rail">
          <!-- tick marks -->
          <div class="fader-ticks" id="ticks-intensity"></div>
          <div class="fader-track" id="ft-intensity">
            <div class="fader-fill" id="ff-intensity"></div>
            <div class="fader-thumb" id="fth-intensity"><div class="thumb-center"></div></div>
          </div>
        </div>
        <div class="fader-val" id="fv-intensity">0.50</div>
      </div>

      <div class="knob-wrap">
        <div class="knob-lbl">DEPTH</div>
        <div class="knob" id="knob-depth">
          <div class="knob-body"></div>
          <div class="knob-dot" id="kd-depth"></div>
        </div>
        <div class="knob-val" id="kv-depth">0.50</div>
      </div>

      <div class="ch-btns">
        <div class="ch-btn" data-field="mode" data-val="EXPLORE" onclick="set('mode','EXPLORE')">EXPLORE</div>
        <div class="ch-btn" data-field="mode" data-val="FIX"     onclick="set('mode','FIX')">FIX</div>
        <div class="ch-btn" data-field="mode" data-val="BUILD"   onclick="set('mode','BUILD')">BUILD</div>
      </div>
    </div>

    <!-- CHANNEL T2: CONFIDENCE -->
    <div class="ch t2">
      <div class="ch-accent"></div>
      <div class="ch-id">T2 — CONF</div>

      <div class="fader-wrap">
        <div class="fader-lbl">CERTAINTY</div>
        <div class="fader-rail">
          <div class="fader-ticks" id="ticks-certainty"></div>
          <div class="fader-track" id="ft-certainty">
            <div class="fader-fill" id="ff-certainty"></div>
            <div class="fader-thumb" id="fth-certainty"><div class="thumb-center"></div></div>
          </div>
        </div>
        <div class="fader-val" id="fv-certainty">0.50</div>
      </div>

      <div class="knob-wrap">
        <div class="knob-lbl">RISK</div>
        <div class="knob" id="knob-risk">
          <div class="knob-body"></div>
          <div class="knob-dot" id="kd-risk"></div>
        </div>
        <div class="knob-val" id="kv-risk">0.50</div>
      </div>

      <div class="ch-btns">
        <div class="ch-btn" data-field="stance" data-val="LIST"   onclick="set('stance','LIST')">LIST</div>
        <div class="ch-btn" data-field="stance" data-val="GUIDE"  onclick="set('stance','GUIDE')">GUIDE</div>
        <div class="ch-btn" data-field="stance" data-val="DECIDE" onclick="set('stance','DECIDE')">DECIDE</div>
      </div>
    </div>

  </div><!-- /left bank -->

  <!-- CENTER: MONITORING -->
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

    <!-- CTRL RUN LAUNCHER -->
    <div class="launch-wrap">
      <input class="launch-input" id="launch-input" type="text" placeholder="type a task and hit Enter — launches ctrl run with current fader state">
      <span class="launch-running" id="launch-running">● RUNNING</span>
      <button class="launch-btn" id="launch-btn">LAUNCH</button>
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

    <!-- LIVE PROMPT PREVIEW -->
    <div class="prompt-preview-wrap">
      <div class="prompt-preview-hd">LIVE PROMPT</div>
      <div class="prompt-preview-box" id="prompt-preview">—</div>
    </div>

    <!-- INFO BOX -->
    <div class="info-wrap">
      <div class="info-label" id="info-label">hover any control</div>
      <div class="info-text" id="info-text">Move a fader, knob, or button to see what it does.</div>
    </div>

    <!-- RUN LOG -->
    <div class="history-wrap">
      <div class="history-hd-row">
        <div class="section-hd">RUN LOG</div>
        <button class="clear-btn" onclick="clearHistory()">Clear</button>
      </div>
      <div id="history"><div class="history-empty">no runs yet</div></div>
    </div>
  </div>

  <!-- RIGHT BANK: T3 + T4 -->
  <div class="channel-bank right">
    <div class="bank-hd">T3 · T4</div>

    <!-- CHANNEL T3: SCOPE -->
    <div class="ch t3">
      <div class="ch-accent"></div>
      <div class="ch-id">T3 — SCOPE</div>

      <div class="fader-wrap">
        <div class="fader-lbl">SCOPE</div>
        <div class="fader-rail">
          <div class="fader-ticks" id="ticks-scope"></div>
          <div class="fader-track" id="ft-scope">
            <div class="fader-fill" id="ff-scope"></div>
            <div class="fader-thumb" id="fth-scope"><div class="thumb-center"></div></div>
          </div>
        </div>
        <div class="fader-val" id="fv-scope">0.50</div>
      </div>

      <div class="knob-wrap">
        <div class="knob-lbl">BANDW</div>
        <div class="knob" id="knob-bandwidth">
          <div class="knob-body"></div>
          <div class="knob-dot" id="kd-bandwidth"></div>
        </div>
        <div class="knob-val" id="kv-bandwidth">0.50</div>
      </div>

      <div class="ch-btns">
        <div class="ch-btn" data-field="filter" data-val="FILE"    onclick="set('filter','FILE')">FILE</div>
        <div class="ch-btn" data-field="filter" data-val="MODULE"  onclick="set('filter','MODULE')">MODULE</div>
        <div class="ch-btn" data-field="filter" data-val="PROJECT" onclick="set('filter','PROJECT')">PROJECT</div>
      </div>
    </div>

    <!-- CHANNEL T4: VOICE -->
    <div class="ch t4">
      <div class="ch-accent"></div>
      <div class="ch-id">T4 — VOICE</div>

      <div class="fader-wrap">
        <div class="fader-lbl">ROOM</div>
        <div class="fader-rail">
          <div class="fader-ticks" id="ticks-room"></div>
          <div class="fader-track" id="ft-room">
            <div class="fader-fill" id="ff-room"></div>
            <div class="fader-thumb" id="fth-room"><div class="thumb-center"></div></div>
          </div>
        </div>
        <div class="fader-val" id="fv-room">0.30</div>
      </div>

      <div class="knob-wrap">
        <div class="knob-lbl">DECAY</div>
        <div class="knob" id="knob-decay">
          <div class="knob-body"></div>
          <div class="knob-dot" id="kd-decay"></div>
        </div>
        <div class="knob-val" id="kv-decay">0.30</div>
      </div>

      <div class="ch-btns">
        <div class="ch-btn" data-field="voice" data-val="DIRECT" onclick="set('voice','DIRECT')">DIRECT</div>
        <div class="ch-btn" data-field="voice" data-val="STUDIO" onclick="set('voice','STUDIO')">STUDIO</div>
        <div class="ch-btn" data-field="voice" data-val="OPEN"   onclick="set('voice','OPEN')">OPEN</div>
      </div>
    </div>

  </div><!-- /right bank -->

</div><!-- /console -->

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
      <p class="faq-p">Control is a behavioral interface for Claude Code. A mixing board for how an AI coding agent thinks. Every fader, knob, and button adjusts a parameter in the system prompt. Same task. Different state. Measurably different output. Every time.</p>
    </div>
    <div class="faq-s">
      <div class="faq-s-title">the four tracks</div>
      <div class="faq-track">
        <div class="faq-track-name">T1 — MODE · fader: Intensity · knob: Depth</div>
        <div class="faq-track-desc">EXPLORE (analyze only), FIX (one root cause), BUILD (one atomic change). Intensity compresses output. Depth controls reasoning depth.</div>
      </div>
      <div class="faq-track" style="border-left-color:#A87820">
        <div class="faq-track-name">T2 — CONFIDENCE · fader: Certainty · knob: Risk</div>
        <div class="faq-track-desc">How committed Claude is. Certainty = how strongly it picks a path. Risk = how bold the changes. Stance: LIST shows alternatives, GUIDE recommends then acts, DECIDE just does it.</div>
      </div>
      <div class="faq-track" style="border-left-color:#20887A">
        <div class="faq-track-name">T3 — SCOPE · fader: Scope · knob: Bandwidth</div>
        <div class="faq-track-desc">How wide Claude looks. Filter: FILE (this file only), MODULE (this module), PROJECT (full codebase).</div>
      </div>
      <div class="faq-track" style="border-left-color:#1A6868">
        <div class="faq-track-name">T4 — VOICE · fader: Room · knob: Decay</div>
        <div class="faq-track-desc">The feel of output. Room = breathing space. Decay = how long ideas echo. Voice: DIRECT (output only), STUDIO (clean), OPEN (thinks out loud).</div>
      </div>
    </div>
    <div class="faq-s">
      <div class="faq-s-title">preview vs. ctrl run</div>
      <p class="faq-p">Preview Run calls Claude API directly — same model, no file access. The real workflow:</p>
      <code class="faq-code">ctrl run "refactor the auth module"</code>
      <p class="faq-p">This invokes Claude Code with full tool access. The state set here shapes how it works.</p>
    </div>
    <div class="faq-s">
      <div class="faq-s-title">physical controller</div>
      <code class="faq-code">ctrl nano --start</code>
      <p class="faq-p">Faders map to parameters in real time. State file at <code style="background:#0A0806;padding:1px 4px;border-radius:2px;font-size:10px">~/.streamfader/state.json</code>.</p>
    </div>
    <div class="faq-s">
      <div class="faq-s-title">the proof</div>
      <p class="faq-p">Set MODE to EXPLORE, intensity LOW, stance LIST. Ask Claude anything. Then flip to BUILD, intensity HIGH, stance DECIDE. The outputs are measurably different.</p>
      <p class="faq-p" style="opacity:.3;font-style:italic">That's the machine. You hold the dial.</p>
    </div>
  </div>
</div>

<script>
const THUMB_H = 18;
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
const FIELD_DEFAULTS = {room:0.3, decay:0.3};
const METERS   = ['intensity','depth','certainty','risk','scope','bandwidth','room','decay'];
const BADGE_C  = {EXPLORE:'#0369A1', FIX:'#C87020', BUILD:'#8A6018'};
const PILL_C   = ['#8A6018','#C87020','#207868','#186858'];

let isDragging = false;
let lastState  = {};

const INFO = {
  intensity:  ['INTENSITY',  'How hard Claude pushes. HIGH = minimal output, direct execution. LOW = verbose reasoning, exploratory tone.'],
  depth:      ['DEPTH',      'How deep Claude diagnoses. HIGH = full root cause analysis. LOW = surface-level reasoning only.'],
  certainty:  ['CERTAINTY',  'Commitment to one answer. HIGH = single solution, no alternatives. LOW = 2-3 approaches with pros/cons.'],
  risk:       ['RISK',       'How bold the changes. HIGH = best solution even if significant refactor. LOW = stay close to existing patterns.'],
  scope:      ['SCOPE',      'How wide Claude looks. HIGH = full codebase. MED = module + dependencies. LOW = this file only.'],
  bandwidth:  ['BANDWIDTH',  'Adjacent context. HIGH = pull in everything related. LOW = surgical, touch nothing adjacent.'],
  room:       ['ROOM',       'Space in output. WET = thinks out loud, breathing room. DRY = close-mic\'d, just the result.'],
  decay:      ['DECAY',      'Language density. LONG = ideas echo and build. SHORT = tight and compressed, every word counts.'],
  EXPLORE:    ['EXPLORE',    'Analysis only. No code changes. Claude maps the problem and ends with a single decision point.'],
  FIX:        ['FIX',        'One root cause, one fix. No secondary issues touched. Scalpel, not a sledgehammer.'],
  BUILD:      ['BUILD',      'One atomic change implemented. No refactoring unless explicitly required.'],
  LIST:       ['LIST',       'Present alternatives only. Nothing gets implemented. Use before committing to a direction.'],
  GUIDE:      ['GUIDE',      'Recommend then implement. Claude gives brief reasoning for its choice, then acts.'],
  DECIDE:     ['DECIDE',     'Pick one and ship it. Zero explanation of alternatives. Maximum commitment.'],
  FILE:       ['FILE',       'This file only. No cross-module context pulled. Strictest local scope.'],
  MODULE:     ['MODULE',     'This module and its direct dependencies. Selective, shaped context.'],
  PROJECT:    ['PROJECT',    'Full codebase in scope. Global context available. Pair with high SCOPE.'],
  DIRECT:     ['DIRECT',     'Dead room. Output only — zero commentary or preamble. Just the result.'],
  STUDIO:     ['STUDIO',     'Professional and measured. Clean response with minimal framing. Default voice.'],
  OPEN:       ['OPEN',       'Collaborative. Claude thinks out loud with you, full reasoning visible.'],
  MODE:       ['MODE',       'What Claude is allowed to do. EXPLORE = read only. FIX = one bug. BUILD = one change.'],
  STANCE:     ['STANCE',     'How Claude presents its work. LIST = options only. GUIDE = recommends + acts. DECIDE = just ships.'],
  FILTER:     ['FILTER',     'Context boundary. FILE = this file. MODULE = this module. PROJECT = full codebase.'],
  VOICE:      ['VOICE',      'Output style. DIRECT = no commentary. STUDIO = clean + measured. OPEN = thinks out loud.'],
};

function showInfo(key) {
  const entry = INFO[key];
  if (!entry) return;
  document.getElementById('info-label').textContent = entry[0];
  document.getElementById('info-text').textContent  = entry[1];
}
function clearInfo() {
  document.getElementById('info-label').textContent = 'hover any control';
  document.getElementById('info-text').textContent  = 'Move a fader, knob, or button to see what it does.';
}

function buildPromptPreview(s) {
  const i=s.intensity??0.5, d=s.depth??0.5, c=s.certainty??0.5, r=s.risk??0.5;
  const sc=s.scope??0.5, bw=s.bandwidth??0.5, ro=s.room??0.3, dc=s.decay??0.3;
  const lines = [];
  const kv = (k,v) => `<span class="pp-key">${k}:</span> <span class="pp-val">${v}</span>`;
  if (s.mode==='EXPLORE') lines.push(kv('MODE','EXPLORE — analysis only, no code changes'));
  else if (s.mode==='FIX') lines.push(kv('MODE','FIX — one root cause, one fix'));
  else lines.push(kv('MODE','BUILD — one atomic change'));
  lines.push(kv('INTENSITY', i>=0.7?'HIGH — minimal output, direct execution':i>=0.4?'MED — concise reasoning':'LOW — verbose reasoning, exploratory'));
  lines.push(kv('DEPTH',     d>=0.7?'HIGH — deeper diagnostic reasoning':d>=0.4?'MED — moderate analysis':'LOW — surface-level only'));
  lines.push(kv('CERTAINTY', c>=0.7?'HIGH — one solution, no alternatives':c>=0.4?'MED — recommendation + brief reasoning':'LOW — show 2-3 approaches, do not pick'));
  lines.push(kv('RISK',      r>=0.7?'HIGH — best solution, even if significant changes':r>=0.4?'MED — prefer existing patterns where reasonable':'LOW — stay close to existing, minimal disruption'));
  if (s.stance==='LIST')   lines.push(kv('STANCE','LIST — present alternatives only, do not implement'));
  else if (s.stance==='DECIDE') lines.push(kv('STANCE','DECIDE — pick one, implement it, zero explanation'));
  else lines.push(kv('STANCE','GUIDE — recommend with brief reasoning, then implement'));
  lines.push(kv('SCOPE',     sc>=0.7?'WIDE — full codebase':sc>=0.4?'MED — module + dependencies':'NARROW — immediate file or function only'));
  lines.push(kv('BANDWIDTH', bw>=0.7?'WIDE — pull in adjacent concerns freely':bw>=0.4?'MED — related things welcome if relevant':'NARROW — surgical, touch nothing adjacent'));
  if (s.filter==='FILE')    lines.push(kv('FILTER','FILE — this file only, no cross-module context'));
  else if (s.filter==='PROJECT') lines.push(kv('FILTER','PROJECT — full project scope, global context'));
  else lines.push(kv('FILTER','MODULE — shaped band around the module'));
  lines.push(kv('ROOM',      ro>=0.7?'WET — open space, think out loud':ro>=0.4?'MED — some space, conversational':'DRY — close-mic\'d, no space, just output'));
  lines.push(kv('DECAY',     dc>=0.7?'LONG — ideas echo and build':dc>=0.4?'MED — moderate density':'SHORT — tight, every word counts'));
  if (s.voice==='DIRECT') lines.push(kv('VOICE','DIRECT — dead room, output only, zero preamble'));
  else if (s.voice==='OPEN') lines.push(kv('VOICE','OPEN — collaborative, thinks out loud'));
  else lines.push(kv('VOICE','STUDIO — professional, measured, clean'));
  return lines.join('\n');
}

/* build tick marks for a fader */
function buildTicks(containerId) {
  const c = document.getElementById(containerId); if (!c) return;
  const ticks = [
    {v:1.0, lbl:'1.0', major:true},
    {v:0.9, lbl:'',    major:false},
    {v:0.8, lbl:'0.8', major:false},
    {v:0.7, lbl:'',    major:false},
    {v:0.6, lbl:'0.6', major:false},
    {v:0.5, lbl:'0.5', major:true},
    {v:0.4, lbl:'0.4', major:false},
    {v:0.3, lbl:'',    major:false},
    {v:0.2, lbl:'0.2', major:false},
    {v:0.1, lbl:'',    major:false},
    {v:0.0, lbl:'0.0', major:true},
  ];
  c.innerHTML = ticks.map(t =>
    `<div class="tick">
      <span class="tick-lbl">${t.lbl}</span>
      <div class="tick-line${t.major?' major':''}" style="width:${t.major?6:4}px"></div>
    </div>`
  ).join('');
}

function getRange(trackId) {
  const el = document.getElementById(trackId);
  return el ? Math.max(20, el.offsetHeight - THUMB_H) : 80;
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
  const dot = document.getElementById(k.dot);
  if (dot) dot.style.transform = `translateX(-50%) rotate(${-135+v*270}deg)`;
  const val = document.getElementById(k.val);
  if (val) val.textContent = v.toFixed(2);
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
  document.querySelectorAll(`.ch-btn[data-field="${field}"]`).forEach(b =>
    b.classList.toggle('active', b.dataset.val === active));
}
function setPill(id, text, color) {
  const el = document.getElementById(id); if (!el) return;
  el.textContent = text;
  el.style.background = color+'28';
  el.style.color = color;
}
function applyState(s) {
  lastState = s;
  Object.keys(FADERS).forEach(f => setFader(f, s[f] ?? (FIELD_DEFAULTS[f] ?? 0.5)));
  Object.keys(KNOBS).forEach(f  => setKnob(f,  s[f] ?? (FIELD_DEFAULTS[f] ?? 0.5)));
  METERS.forEach(f => setMeter(f, s[f] ?? (FIELD_DEFAULTS[f] ?? 0.5)));
  setButtons('mode',   s.mode);
  setButtons('stance', s.stance);
  setButtons('filter', s.filter);
  setButtons('voice',  s.voice);
  const col = BADGE_C[s.mode] || '#C8922A';
  const badge = document.getElementById('hdr-badge');
  badge.textContent = s.mode||'—';
  badge.style.color = col;
  badge.style.background = col+'22';
  badge.style.borderLeftColor = col;
  document.getElementById('hdr-vals').textContent =
    `I ${(s.intensity??0).toFixed(2)}  D ${(s.depth??0).toFixed(2)}  C ${(s.certainty??0).toFixed(2)}  R ${(s.risk??0).toFixed(2)}`;
  setPill('pill-mode',   s.mode  ||'—', PILL_C[0]);
  setPill('pill-stance', s.stance||'—', PILL_C[1]);
  setPill('pill-filter', s.filter||'—', PILL_C[2]);
  setPill('pill-voice',  s.voice ||'—', PILL_C[3]);
  document.getElementById('prompt-preview').innerHTML = buildPromptPreview(s);
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

/* fader drag */
Object.entries(FADERS).forEach(([field, ids]) => {
  const trackEl = document.getElementById(ids.track);
  const thumbEl = document.getElementById(ids.thumb);
  const getV    = () => parseFloat(document.getElementById(ids.val).textContent);
  const move    = (sy,cy,sv) => setFader(field, Math.max(0, Math.min(1, sv+(sy-cy)/getRange(ids.track))));
  const drop    = () => set(field, Math.round(getV()*1000)/1000);
  const reset   = () => { const d = FIELD_DEFAULTS[field]??0.5; setFader(field,d); set(field,d); };
  bindDrag(trackEl, getV, move, drop);
  bindDrag(thumbEl, getV, move, drop);
  trackEl.addEventListener('dblclick', reset);
  thumbEl.addEventListener('dblclick', reset);
});

/* knob drag */
Object.entries(KNOBS).forEach(([field, ids]) => {
  const knobEl = document.getElementById('knob-'+field);
  const getV   = () => parseFloat(document.getElementById(ids.val).textContent);
  const move   = (sy,cy,sv) => setKnob(field, Math.max(0, Math.min(1, sv+(sy-cy)/120)));
  const drop   = () => set(field, Math.round(getV()*1000)/1000);
  const reset  = () => { const d = FIELD_DEFAULTS[field]??0.5; setKnob(field,d); set(field,d); };
  if (knobEl) { bindDrag(knobEl, getV, move, drop); knobEl.addEventListener('dblclick', reset); }
});

/* info box hover — attach to all labeled controls */
document.querySelectorAll('.fader-lbl,.knob-lbl').forEach(el => {
  const field = el.textContent.trim().toLowerCase();
  el.addEventListener('mouseenter', () => showInfo(field));
  el.addEventListener('mouseleave', clearInfo);
});
document.querySelectorAll('.ch-btn').forEach(el => {
  const key = el.dataset.val;
  el.addEventListener('mouseenter', () => showInfo(key));
  el.addEventListener('mouseleave', clearInfo);
});
document.querySelectorAll('.pill-lbl').forEach(el => {
  const key = el.textContent.trim();
  el.addEventListener('mouseenter', () => showInfo(key));
  el.addEventListener('mouseleave', clearInfo);
});
document.querySelectorAll('.meter-lbl').forEach(el => {
  const field = el.textContent.trim().toLowerCase();
  el.addEventListener('mouseenter', () => showInfo(field));
  el.addEventListener('mouseleave', clearInfo);
});
document.querySelectorAll('.fader-track,.fader-thumb,.knob').forEach(el => {
  el.addEventListener('mouseenter', () => {
    const field = el.id?.replace('knob-','').replace('ft-','').replace('fth-','');
    if (field) showInfo(field);
  });
  el.addEventListener('mouseleave', clearInfo);
});

/* build tick marks after layout */
['intensity','certainty','scope','room'].forEach(f => buildTicks('ticks-'+f));

// ── RUN LOG ───────────────────────────────────────────────────────
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

// ── PREVIEW RUN ───────────────────────────────────────────────────
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

// ── CTRL RUN LAUNCHER ────────────────────────────────────────────
const launchInput   = document.getElementById('launch-input');
const launchBtn     = document.getElementById('launch-btn');
const launchRunning = document.getElementById('launch-running');

async function launchTask() {
  const task = launchInput.value.trim();
  if (!task || launchBtn.disabled) return;
  launchBtn.disabled = true; launchBtn.textContent = '···';
  launchRunning.classList.add('show');
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
  let output = '';
  const done = () => {
    launchBtn.disabled = false; launchBtn.textContent = 'LAUNCH';
    launchRunning.classList.remove('show');
  };
  try {
    const res = await fetch('/exec', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task})});
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const {done: rd, value} = await reader.read(); if (rd) break;
      buf += dec.decode(value, {stream:true});
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const d = JSON.parse(line.slice(6));
        if (d.text) output += d.text;
        if (d.error) { done(); }
        if (d.done) {
          done();
          if (output) {
            history.unshift({t:new Date().toLocaleTimeString(), task, resp:output, ...snap});
            if (history.length > 30) history.pop();
            saveHistory(); renderHistory();
            launchInput.value = '';
          }
        }
      }
    }
  } catch(e) { done(); }
}
launchBtn.addEventListener('click', launchTask);
launchInput.addEventListener('keydown', e => { if (e.key === 'Enter') launchTask(); });

// ── FAQ ───────────────────────────────────────────────────────────
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
