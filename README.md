# H10 Continuous Body Field

A live ambient performance system: a Polar H10 chest strap streams heartbeat
(HR/RR) and accelerometer data over BLE, a Python bridge turns body state
into continuous MIDI control signals, and a REAPER project renders six
warm, restrained sound layers — plus a manually played melody instrument on
an Arturia MiniLab 3.

There are no scenes and no state machine: body state maps continuously to
sound morphology at all times.

```
Polar H10 ──BLE──▶ h10_performance_live.py ──JSONL──▶ midi_bridge/continuous_bridge.py
                                                            │  virtual MIDI port
                                                            ▼  "H10 Continuous Body Field"
MiniLab 3 keys/knobs/faders ──────────────────────────▶ REAPER: H10 Continuous Body Field.RPP
```

Full design, MIDI contract, MiniLab knob/fader map, and layer descriptions:
[midi_bridge/CONTINUOUS_BODY_FIELD.md](midi_bridge/CONTINUOUS_BODY_FIELD.md).
REAPER assets and setup: [reaper/continuous/README.md](reaper/continuous/README.md).

## Install

```bash
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

On macOS, grant Bluetooth access to Terminal (BLE fails with SIGABRT from
sandboxed shells).

## Run

Live (wearing the H10; run from your own Terminal):

```bash
./midi_bridge/run_continuous_live.sh
```

Demo / audition without the strap — replays recorded capture data and keeps
the virtual MIDI port alive across loop cycles:

```bash
./h10demoplay                                     # audible, waits for REAPER, binds only when H10 CONTROL is open
./h10demoplay --once                              # audible, one replay cycle
./midi_bridge/run_continuous_demo.sh --dry-run    # prints MIDI as JSON, no audio
```

Ctrl+C always shuts down cleanly: performance gate to 0, note-offs, and
All-Notes-Off on every used channel. `h10demoplay` keeps a PID file and
refuses to start a second copy — if you left it running in the background,
stop it with `./h10demostop`.

In REAPER, open a project whose first track is `H10 CONTROL` before the
bridge tries to bind. `h10demoplay` now keeps retrying until it sees that
track, so you can open REAPER manually whenever you are ready. If the
bridge was restarted, reset REAPER's MIDI devices (action 41175) so it
subscribes to the new virtual-port instance. The idempotent setup/repair
script lives at `reaper/continuous/setup_h10_continuous.lua`.

## Utilities

- `scan_h10.py` — find the strap's current CoreBluetooth address when the
  pinned one goes stale (`./venv/bin/python scan_h10.py`).
- `scripts/capture_h10_motion.py` — record new HR + accelerometer captures
  into `captures/` (the replay demo and tests are built on these).

## Tests

```bash
./venv/bin/python -m pytest midi_bridge/tests -q
```

The suite covers the continuous engine (calibration, RR artifact filtering,
dropout, pads/panic, snapshot refresh), the melody/loop contracts, and the
shared V3/V4-era core modules (`midi_bridge/bridge.py`,
`midi_bridge/performance_bridge.py`) that `continuous_bridge.py` builds on.

## Layout

```
h10_common.py                 shared BLE address/discovery helpers
h10_performance_live.py       BLE producer: heartbeat + motion JSONL
h10_hr_live.py                minimal HR-only producer (kept: exercised by tests)
h10_hr_log.py                 HR CSV logger (kept: exercised by tests)
scan_h10.py                   BLE address scanner
scripts/capture_h10_motion.py capture recorder
captures/                     recorded sessions used by replay + tests
midi_bridge/
  continuous_bridge.py        body state → continuous MIDI (the system core)
  continuous_mapping.json     calibration/ranges/CC contract
  bridge.py                   shared MIDI sink core (dependency, V3-era)
  performance_bridge.py       shared calibration/filter/sink (dependency, V4-era)
  mapping_config.json         config fixture for bridge.py tests
  performance_mapping.json    config fixture for performance_bridge.py tests
  run_continuous_live.sh      live entry point
  run_continuous_demo.sh      replay entry point (--sound/--dry-run, --loop)
  minilab/                    MiniLab 3 hardware template (User 2)
  examples/                   replay_performance.py + sample event fixtures
  tests/                      pytest suite
reaper/continuous/            JSFX instruments + setup/audit ReaScripts
reaper_projects/              H10 Continuous Body Field.RPP
```

## History

Superseded systems (V3 meditation mapping, the V4 five-scene performance
rig, and early experiments) were removed from the working tree on
2026-07-15 but remain fully recoverable:

```bash
git checkout archive-pre-continuous-cleanup -- <path>   # restore any old file
git show archive-pre-continuous-cleanup:<path>          # just view it
```

The independent performance-brief website now lives in its own repository
at `../H10-site`.
