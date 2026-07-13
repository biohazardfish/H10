# Polar H10 60-second capture

Capture folder: `2026-07-13_20-22-57_h10_60s`

## Files

- `h10_events.jsonl`: raw heartbeat events from `h10_hr_live.py`, one JSON object per heartbeat.
- `h10_events.csv`: the same events in spreadsheet-friendly form.
- `h10_capture.log`: Bluetooth connection and rate-limited live diagnostics from stderr.
- `summary.json`: computed statistics for this 60-second capture.
- `capture_meta.json`: command/path metadata for reproducibility.

## Capture Summary

- Start: `2026-07-13T20:23:05+08:00`
- End: `2026-07-13T20:24:05+08:00`
- Requested duration: `60 s`
- Observed duration: `59.194 s`
- Heartbeat event count: `108`
- Valid RR interval count: `108`
- Mean BPM from H10 packets: `108.6 bpm`  (min `106.0`, max `111.0`)
- Effective BPM from counted beats: `109.5 bpm`
- Mean RR interval: `553.0 ms`
- RMSSD: `7.7 ms`
- SDNN: `13.7 ms`

## What The Parameters Mean

- `timestamp`: computer-local ISO timestamp when the BLE notification was handled.
- `bpm`: heart rate reported by the Polar H10 Heart Rate Measurement packet. This is the signal mapped to MIDI `CC10` in the current V3 bridge.
- `rr_ms`: RR interval in milliseconds. It is the time between successive heartbeats derived from the H10 RR field. It is the signal mapped to MIDI `CC14`. Missing `rr_ms` means that packet did not contain an RR interval; this capture filters clearly invalid RR values out of HRV stats.
- `beat`: heartbeat trigger. Current producer emits `1` for each heartbeat event. This is the signal mapped to MIDI Note `36`.
- `_capture_elapsed_s`: seconds elapsed since the first captured heartbeat event in this recording folder.
- `RMSSD`: root mean square of successive RR differences. It estimates short-term heart-rate variability and is mapped to MIDI `CC11` by the current V3 bridge.
- `SDNN`: standard deviation of valid RR intervals during this capture. It is included for physiology context, but the current V3 MIDI bridge does not emit SDNN.

## Current V3 MIDI Meaning

The current bridge intentionally emits only four H10-derived mappings:

- `CC10`: heart rate (`bpm`), range 40..180 bpm.
- `CC11`: RMSSD, range 5..100 ms.
- `Note 36`: one pulse per heartbeat (`beat`).
- `CC14`: current RR interval (`rr_ms`), range 400..1500 ms.

No REAPER project state was changed by this capture.
