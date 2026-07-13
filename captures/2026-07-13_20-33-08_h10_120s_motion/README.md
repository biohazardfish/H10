# Polar H10 120-second movement capture

This folder contains a two-minute capture of Polar H10 heart data plus motion data.

## Important Hardware Note

Polar's public H10 SDK documentation lists heart rate/RR, ECG, and accelerometer data for H10. It does not list gyroscope data for H10. This capture therefore records `ACC` accelerometer data when available. If a future/other device reports `GYRO`, raw gyro frames are saved in `h10_raw_motion_frames.jsonl`.

## Files

- `h10_hr_events.jsonl` / `h10_hr_events.csv`: one heartbeat event per RR interval.
- `h10_acc_samples.jsonl` / `h10_acc_samples.csv`: accelerometer samples in milli-g (`x_mg`, `y_mg`, `z_mg`) plus vector magnitude.
- `h10_raw_motion_frames.jsonl`: raw non-ACC PMD motion frames, e.g. gyro if the device exposes it.
- `summary.json`: computed statistics.
- `capture.log`: connection, PMD availability, and progress log.

## Parameter Meaning

- `bpm`: heart rate reported by the H10.
- `rr_ms`: beat-to-beat interval in milliseconds.
- `beat`: heartbeat trigger, always `1` per event.
- `x_mg`, `y_mg`, `z_mg`: chest-strap acceleration by axis in milli-g. Around 1000 mg magnitude means static gravity; deviations and axis changes show body movement.
- `magnitude_mg`: sqrt(x^2 + y^2 + z^2), useful as a simple movement-intensity proxy.
- `RMSSD`: short-term HRV from successive valid RR intervals.
- `SDNN`: standard deviation of valid RR intervals.

## Summary At Capture End

See `summary.json`; key counts are:

- HR events: `258`
- ACC samples: `6084`
- Raw motion frames: `0`
