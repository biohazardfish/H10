# H10 MIDI Bridge

This bridge reads Polar H10 JSONL events on stdin and emits the current V3 static meditation MIDI contract.

## Active Mapping

- `bpm` → CC10 on channel 1, linear 40..180 BPM.
- rolling RMSSD from valid `rr_ms` values → CC11 on channel 1, linear 5..100 ms.
- `beat` → Note 36 on channel 10, velocity 80, 80 ms gate.
- current valid `rr_ms` → CC14 on channel 1, linear 400..1500 ms.

No other H10-derived mappings are active. In particular, the bridge does not emit CC12/CC15, motion controls, pitch bend, program change, drone notes, snare triggers, accelerometer, gyroscope, or ECG mappings.

## Files

- `bridge.py`: reads JSONL input, calculates RMSSD, applies mapping config, and sends MIDI.
- `mapping_config.json`: the four active mappings and rate-limited diagnostics setting.
- `examples/h10_sample_events.jsonl`: a calm sample stream.
- `examples/h10_demo_events.jsonl`: a dynamic sample stream.
- `run_demo.sh`: runs the bridge in dry-run mode or opens the virtual MIDI port.

## Quick Demo Without H10

```bash
./midi_bridge/run_demo.sh --dry-run
```

To send the simulated stream to REAPER through a virtual MIDI port named `H10 Bridge`:

```bash
./midi_bridge/run_demo.sh --sound
```

The real live pipeline is:

```bash
./venv/bin/python h10_hr_live.py | \
  ./venv/bin/python midi_bridge/bridge.py \
    --config midi_bridge/mapping_config.json \
    --virtual --port "H10 Bridge"
```

Normal MIDI mode fails clearly with a non-zero exit code if `mido` cannot be imported or the MIDI port cannot be opened. MIDI-intent JSON is only emitted in `--dry-run` mode.
