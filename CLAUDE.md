# Control — Living Doc
*A physical MIDI mixing board for Claude Code. Dial in AI behavior in real time.*

---

## What It Is
Control maps a Korg nanoKONTROL2 (or mouse) to behavioral parameters that shape how Claude Code thinks and acts. Same task, different state = measurably different output. It's a DAW for AI coding agents — you perform instead of prompt.

## How to Run
```
# Terminal 1 — MIDI bridge
ctrl nano --start

# Terminal 2 — Visual UI
python3 /Users/miahsm1/control/mvm_ui.py

# Terminal 3 — Run a task
ctrl run "your task here"
```
UI: http://127.0.0.1:5570
iPad: http://192.168.1.24:5570

## Track Layout
| Track | Fader | Knob | Buttons |
|-------|-------|------|---------|
| T1 — MODE | intensity | depth | EXPLORE / FIX / BUILD |
| T2 — CONF | certainty | risk | LIST / GUIDE / DECIDE |
| T3 — SCOPE | scope | bandwidth | FILE / MODULE / PROJECT |
| T4 — VOICE | room | decay | DIRECT / STUDIO / OPEN |

## Key Files
- `ctrl` — CLI tool, reads state.json, calls `claude --print`
- `mvm_ui.py` — Flask UI, SSE stream, preview run via Anthropic API
- `nano_bridge.py` — MIDI bridge, maps nanoKONTROL2 CC to state.json
- `~/.streamfader/state.json` — shared state between all three
- `~/.streamfader/ctrl.pid` — PID file for STOP button kill switch
- `~/.streamfader/last_task.txt` — last task for PLAY button replay

## Architecture Note
`ctrl` symlink lives at `/opt/homebrew/bin/ctrl` → points to `/Users/miahsm1/control/ctrl`.
`mvm_ui.py` loads `build_system_prompt` from `./ctrl` via importlib (no duplication).

---

## Roadmap

### V1 — Current
- [x] 4-track MIDI mapping (nanoKONTROL2)
- [x] Visual UI with SSE live state
- [x] STOP/PLAY transport buttons
- [x] Run log with localStorage persistence
- [x] Mouse-only mode (no controller required)
- [x] iPad support

### V2 — Token Efficiency
Track cumulative token usage per run logged to `~/.streamfader/run_log.jsonl`.
Surface as a trend over time — not a per-run meter (misleading).
The real metric is cost-per-outcome, not cost-per-run.
EXPLORE runs that prevent bad BUILD runs are MORE efficient even if they use more tokens.
Build after launch when there's real usage data to make it meaningful.

### V3 — Track 5: Voice Input
**Concept:** Voice → structured prompt → ctrl run with current fader state.
- Fader: Voice level (raw speech → heavily structured)
- Knob: Structure density (loose → rigid template)
- Buttons: CAPTURE (push-to-talk) / TRANSCRIBE / INJECT
- Tech: Web Speech API (free) for transcription, one API call to structure, inject into ctrl run
- Why it matters: speaking is 3-5x faster than typing for context-heavy tasks
- Build after Track 5 hardware mapping is solid and video is shipped

---

## The Story (for video/Twitter)
- "A DAW for AI coding agents" — Grok's framing, use it
- "You perform instead of prompt" — the core idea
- EXPLORE+LIST → analysis, no code touched
- BUILD+DECIDE → same task, code changed, done
- Before/after: 147 lines → 9 lines (real example from dogfood run)

## Last Session
2026-05-29 — All 4 tracks fully working. UI redesign in progress (VST metal skin). Video planned for today.
