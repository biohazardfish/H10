# Polar H10 BLE Scripts

Project overview: simple Python utilities for Polar H10 BLE heart rate measurement.
- `scan_h10.py`: scan nearby BLE devices to find the H10 address.
- `h10_hr_live.py`: connect to H10 and emit one JSONL event per heartbeat.
- `h10_hr_log.py`: connect to H10, print BPM, and append to CSV.
- `monitor.py`: transparent pipeline stage serving a live dashboard at `localhost:8931`.

## Full chain (heartbeat → sound)
Run in a terminal that has Bluetooth permission:
```
./venv/bin/python h10_hr_live.py | ./venv/bin/python monitor.py | \
  ./venv/bin/python midi_bridge/bridge.py --config midi_bridge/mapping_config.json --virtual --port "H10 Bridge"
```
Open http://localhost:8931 to watch BPM / RR / HRV live. REAPER (with the
"H10 Bridge" MIDI input enabled) receives kick-per-beat on ch10 and a drone
with HRV pitch bend on ch1.

Demo without the strap (no BLE, no MIDI):
```
./venv/bin/python midi_bridge/examples/sim_heartbeat.py midi_bridge/examples/h10_sample_events.jsonl | \
  ./venv/bin/python monitor.py | ./venv/bin/python midi_bridge/bridge.py --config midi_bridge/mapping_config.json --dry-run > /dev/null
```

## Folder layout
```
H10/
  scan_h10.py
  h10_hr_live.py
  h10_hr_log.py
  midi_bridge/
  README.md
  .gitignore
```

## How to run
All scripts are standalone. They rely on the `bleak` package (BLE); the
MIDI bridge additionally uses `mido` for real MIDI output.

1) Create and activate a virtual environment:
```
python3 -m venv venv
source venv/bin/activate
```

2) Install dependencies:
```
pip3 install -r requirements.txt
```

3) Scan for the device address (10-second scan):
```
python3 scan_h10.py
```

4) Update the device address in `h10_hr_live.py` and/or `h10_hr_log.py`:
- `H10_ADDRESS = "..."`

5) Live output:
```
python3 h10_hr_live.py
```

6) Log to CSV:
```
python3 h10_hr_log.py
```

## Output formats
### Live output
`h10_hr_live.py` prints lines like:
```
HR: <bpm> bpm   (raw: <hex>)
```

### CSV output
`h10_hr_log.py` appends to `h10_hr_log.csv` with columns:
- `timestamp` (ISO 8601, seconds precision)
- `bpm` (integer)

Example (from the existing log file):
```
timestamp,bpm
2025-12-01T12:54:34,90
```

## Troubleshooting (from code + macOS constraints)
- If `scan_h10.py` finds no devices, it only scans for 10 seconds; rerun as needed.
- If `h10_hr_live.py`/`h10_hr_log.py` says connection failed, verify `H10_ADDRESS` matches the scan output.
- On macOS, Terminal (or the Python runtime you use) must be allowed to access Bluetooth in System Settings.

## MIDI bridge scaffold
See `midi_bridge/README_MIDI.md` for a JSONL-to-MIDI mapping scaffold and a dry-run demo.
