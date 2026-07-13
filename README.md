# Polar H10 Heartbeat Sonification

## Live Performance V4

The repository now also contains a parallel body-narrative performance rig
using heartbeat, RR, and Polar H10 accelerometer data. It adds personalised
lying calibration, artifact-filtered RMSSD, movement/posture features, an
ordered five-scene state machine, MiniLab User 2 controls, and a new spatial
REAPER project. The validated V3 pipeline below remains available unchanged.

Run live:

```bash
./midi_bridge/run_performance_live.sh
```

Hear the complete performance without wearing the H10:

```bash
PERFORMANCE_DEMO_SPEED=2 ./midi_bridge/run_performance_demo.sh --sound
```

See `midi_bridge/PERFORMANCE_V4.md` for the MIDI contract, state thresholds,
MiniLab controls, REAPER routing, and failure behaviour.

This project reads heartbeat measurements from a Polar H10 over BLE, emits
one JSONL event per heartbeat, and maps the stream to MIDI for REAPER:

```
Polar H10 → h10_hr_live.py → monitor.py (optional) → midi_bridge/bridge.py → REAPER
```

The current V3 bridge is a static meditation mapping:

- heart rate maps to CC10 on MIDI channel 1;
- rolling RMSSD maps to CC11 on MIDI channel 1;
- every heartbeat triggers note 36 on MIDI channel 10 with a short fixed gate;
- current valid RR interval maps to CC14 on MIDI channel 1;
- shutdown releases active notes and sends CC123 All-Notes-Off on every used channel.

## Install

Use Python 3.14 (or another supported Python 3 version) and install the
runtime dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

On macOS, grant Bluetooth access to Terminal or to the Python runtime used by
the virtual environment.

## Find and connect to the H10

Scan for nearby devices:

```bash
./venv/bin/python scan_h10.py
```

`h10_common.py` contains the single preferred macOS address and the shared
name-based fallback discovery used by both `h10_hr_live.py` and
`h10_hr_log.py`. If the strap address changes, name discovery can find a
device whose name contains `Polar` or `H10`.

Live JSONL output:

```bash
./venv/bin/python h10_hr_live.py
```

When an RR interval is present, the producer emits one line such as:

```json
{"timestamp":"2026-07-13T12:00:00.123","bpm":72,"rr_ms":1000,"beat":1}
```

A BLE packet containing multiple RR intervals produces one event per RR. If
the packet has no RR interval, the event contains no `rr_ms` field; it never
uses `rr_ms: 0`, because zero is not a valid physiological interval.

The CSV logger preserves its existing command and file format:

```bash
./venv/bin/python h10_hr_log.py
```

It appends `timestamp,bpm` rows to `h10_hr_log.csv`.

## Run the full sound pipeline

With a MIDI input named `H10 Bridge` enabled in REAPER:

```bash
./venv/bin/python h10_hr_live.py | \
  ./venv/bin/python monitor.py | \
  ./venv/bin/python midi_bridge/bridge.py \
    --config midi_bridge/mapping_config.json \
    --virtual --port "H10 Bridge"
```

Open <http://localhost:8931> if `monitor.py` is included. It is a transparent
observer and does not change the JSONL events sent to the bridge.

If the virtual MIDI port already exists in REAPER from an earlier bridge
process, reset REAPER's MIDI devices before retrying so it subscribes to the
current virtual-port instance.

## Hear the result without wearing the H10

This is the recommended development loop. Open the REAPER project, enable its
MIDI input named `H10 Bridge`, then run:

```bash
./midi_bridge/run_demo.sh --sound
```

The simulator feeds a deliberately dynamic heartbeat sequence into the same
bridge used by the real strap. It demonstrates CC10 heart rate, CC11 RMSSD,
heartbeat note 36, and CC14 RR interval without wearing the H10. Press Ctrl-C
to stop; the bridge sends note-off and CC123 cleanup messages before exiting.

Useful development overrides:

```bash
DEMO_SPEED=2 ./midi_bridge/run_demo.sh --sound
DEMO_BEATS=20 ./midi_bridge/run_demo.sh --sound
H10_MIDI_PORT="Another MIDI Port" ./midi_bridge/run_demo.sh --sound
```

## Test without BLE or MIDI hardware

The dry-run path prints MIDI-intent JSON and does not require `mido` or a MIDI
port:

```bash
./midi_bridge/run_demo.sh --dry-run
```

In normal mode the bridge fails clearly with a non-zero exit code if `mido`
cannot be imported or the requested MIDI port cannot be opened. JSON output
is only a dry-run feature.

Run the focused reliability and parser tests:

```bash
python3 -m pytest midi_bridge/tests -v
```

The tests do not require a BLE strap or real MIDI hardware.

## Project files

```text
H10/
  h10_common.py              shared H10 discovery and 0x2A37 parser
  h10_hr_live.py             one JSONL event per heartbeat
  h10_hr_log.py              BPM CSV logger
  scan_h10.py                BLE device scanner
  monitor.py                 optional live JSONL dashboard/pass-through
  midi_bridge/
    bridge.py                V3 JSONL-to-MIDI mapping engine
    mapping_config.json      current static meditation V3 mapping
    tests/                   bridge and parser tests
```

See `midi_bridge/MAPPING.md` for the detailed routing table and REAPER-side
setup notes.
