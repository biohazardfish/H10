# H10 Project File Audit (Unused / Redundant / Unclear)

This audit is based on direct file inspection (imports/references) and observed file purpose.

| File | Purpose inferred | Used by / referenced from | Likely unused? | Evidence |
| --- | --- | --- | --- | --- |
| scan_h10.py | BLE scan utility to list nearby devices and find Polar H10 address | Not imported; standalone CLI script | no | Only script that performs scanning; referenced in its own output text. |
| h10_hr_live.py | Live BLE HR notifications to stdout | Not imported; standalone CLI script | no | Directly connects and prints BPM; distinct from logging script. |
| h10_hr_log.py | Live BLE HR notifications + appends to CSV | Not imported; standalone CLI script | no | Creates/updates `h10_hr_log.csv` and prints BPM; distinct from live-only script. |
| h10_hr_log.csv | Logged output (timestamp,bpm) | Written by `h10_hr_log.py` | yes | Output artifact; not read by any script in this repo. |
| venv/ | Local Python virtual environment | Not referenced by code | maybe | Typical one-off environment; no repo scripts reference it; could be optional for running. |

Notes:
- `h10_hr_live.py` and `h10_hr_log.py` duplicate `parse_heart_rate` logic, but their runtime roles differ (live vs log), so neither is redundant based on behavior.
