<div align="center">

# Control

**Physical control layer for Claude Code.**  
Map a MIDI fader board to AI behavior. Dial in exactly how Claude thinks and acts — in real time.

*A DAW for AI coding agents. You perform instead of prompt.*

</div>

---

## What It Is

Control maps a **Korg nanoKONTROL2** (or mouse/iPad) to behavioral parameters that shape how Claude Code operates. Four tracks. Twelve parameters. Same task, different state — measurably different output.

Not a prompt template. Not a configuration file. A machine you play.

---

## Track Layout

| Track | Fader | Knob | Buttons |
|-------|-------|------|---------|
| **T1 — MODE** | Intensity | Depth | EXPLORE / FIX / BUILD |
| **T2 — CONF** | Certainty | Risk | LIST / GUIDE / DECIDE |
| **T3 — SCOPE** | Scope | Bandwidth | FILE / MODULE / PROJECT |
| **T4 — VOICE** | Room | Decay | DIRECT / STUDIO / OPEN |

**MODE** controls what Claude is allowed to do.  
**CONF** controls how certain and how risky Claude should be.  
**SCOPE** controls how wide or narrow Claude looks.  
**VOICE** controls the register and density of Claude's output.

---

## How to Run

```bash
# Terminal 1 — MIDI bridge (nanoKONTROL2)
ctrl nano --start

# Terminal 2 — Visual UI
python3 /path/to/control/mvm_ui.py

# Terminal 3 — Run a task
ctrl run "your task here"
```

Visual UI: [http://127.0.0.1:5570](http://127.0.0.1:5570)

---

## Key Files

| File | Role |
|------|------|
| `ctrl` | CLI — reads `state.json`, calls `claude --print` |
| `mvm_ui.py` | Flask UI — SSE stream, live prompt preview, run log |
| `nano_bridge.py` | MIDI bridge — maps nanoKONTROL2 CC to `state.json` |
| `~/.streamfader/state.json` | Shared state between all three processes |

---

## Mouse-Only Mode

No controller required. Every fader, knob, and button is fully clickable. Double-click any fader or knob to reset to 50%.

---

## The Logic

**EXPLORE + LIST** — Claude analyzes, lists options, touches nothing. Use when you don't know what you want yet.

**BUILD + DECIDE** — Claude picks the best approach and implements it. No explanations, no alternatives. Just done.

Same task. Different fader positions. Different output. That's the instrument.

---

## Requirements

```
Python 3.9+
Flask
mido
python-rtmidi
anthropic
```

```bash
pip install flask mido python-rtmidi anthropic
```

---

## Stack

Python · Flask · SSE · mido · rtmidi · Anthropic SDK · Vanilla JS  
Korg nanoKONTROL2 · macOS · iPad (via local network)

---

<div align="center">

**Creative Konsoles** · [creativekonsoles.com](https://creativekonsoles.com) · [@papjamzzz](https://github.com/papjamzzz)

</div>
