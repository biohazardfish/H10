# Polar H10 BLE Scripts

Project overview: simple Python utilities for Polar H10 BLE heart rate measurement.
- `scan_h10.py`: scan nearby BLE devices to find the H10 address.
- `h10_hr_live.py`: connect to H10 and print live heart rate (BPM).
- `h10_hr_log.py`: connect to H10, print BPM, and append to CSV.

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
All scripts are standalone. They rely on the `bleak` package.

1) (Optional) activate the local venv if you want to use it:
```
source venv/bin/activate
```

2) Install dependency (if not already installed):
```
pip3 install bleak
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
