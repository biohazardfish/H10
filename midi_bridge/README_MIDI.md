# H10 → MIDI Mapping Scaffold

This scaffold is a lightweight bridge that turns **H10 parameter events** into **MIDI intents**. It is intentionally modular so you can tweak the mapping later without touching code.

## Concept
1) H10 parameters (e.g., `bpm`, `rr_ms`, `contact`, `motion`) arrive as **JSON lines** on stdin.
2) Each parameter is normalized into 0..1 using configurable ranges.
3) The normalized signal is mapped to MIDI CC or notes.

## “Blade Runner 1982” mapping template (defaults, adjustable)
These are starter defaults designed to evoke a classic, cinematic, slightly “wet” analog vibe:
- **HR (bpm)** → filter cutoff / brightness (CC74)
- **RR-interval variability proxy (rr_ms)** → resonance / Q (CC71)
- **Contact quality / battery (contact)** → reverb send / noise amount (CC91)
- **Motion proxy (motion)** → modulation / vibrato depth (CC1)
- **HR peak trigger** → kick or bass pulse (Note 36)

All of the above are editable in `mapping_config.json`.

## Files
- `bridge.py`: reads JSONL input, applies mapping config, outputs MIDI or MIDI-intent JSON.
- `mapping_config.json`: the mapping table (input, ranges, smoothing, MIDI target).
- `examples/h10_sample_events.jsonl`: a short fake sample stream.
- `run_demo.sh`: runs the dry-run demo with no external dependencies.

## Assumptions used in the demo
The existing code and CSV log only show `bpm`, so the demo includes **best-guess placeholders** for `rr_ms`, `contact`, and `motion`. These are documented here so you can replace them later.

## Integration plan (no BLE changes)
To connect real H10 data later without editing existing scripts:
1) Create a **new adapter script** that reads from `h10_hr_log.csv` (tail -f) or wraps live prints.
2) Emit JSONL with fields matching `mapping_config.json` (at minimum `bpm`).
3) Pipe into `bridge.py`.

## Quick demo (dry-run)
```
./run_demo.sh
```
This will print MIDI-intent JSON lines (no MIDI port required).
