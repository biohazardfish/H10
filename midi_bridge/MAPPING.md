# H10 MIDI Mapping V3: Static Meditation

資料流：

`h10_hr_live.py`（Polar H10 BLE，每個心跳事件一行 JSONL）→ `monitor.py`（可選，透明 pass-through）→ `midi_bridge/bridge.py` → 虛擬埠 `H10 Bridge` → REAPER。

## JSONL 事件

典型事件：

```json
{"timestamp":"2026-07-13T12:00:00.123","bpm":72,"rr_ms":1000,"beat":1}
```

- `bpm`：H10 Heart Rate Measurement 內的 heart rate。
- `rr_ms`：有效 RR interval，單位毫秒；無 RR 時省略，不輸出 `0`。
- `beat`：一次 heartbeat trigger。
- `hrv_rmssd`：bridge 由 rolling valid RR window 衍生，至少兩個有效 RR 後才存在。

Invalid / malformed RR 不會進入 RMSSD，也不會被映射到 MIDI。

## Active MIDI Contract

`mapping_config.json` 目前只啟用以下四個 H10-derived MIDI 訊號：

| Signal | Input | Range | MIDI Output | Smoothing |
|---|---|---:|---|---|
| Heart rate | `bpm` | 40..180 BPM | CC10, ch1 | EMA alpha 0.2 |
| RMSSD | `hrv_rmssd` | 5..100 ms | CC11, ch1 | moving average window 8 |
| Heartbeat | `beat` | event trigger | Note 36, ch10, velocity 80, gate 80ms | none |
| RR interval | `rr_ms` | 400..1500 ms | CC14, ch1 | EMA alpha 0.5 |

Mapping is linear and clamped to MIDI 0..127 for CC values. Duplicate CC values are suppressed when the integer MIDI value has not changed.

The active bridge does not emit CC12, CC15, movement, accelerometer, gyroscope, ECG, pitch bend, program change, drone note 48, or extra snare triggers.

## Diagnostics

The bridge prints rate-limited diagnostics to stderr when enabled in `mapping_config.json`:

```text
H10 diag raw_hr=72.0 smooth_hr=72.0 rr=1000 rmssd=- cc10=29 cc11=- cc14=69 note36=on
```

stdout remains either clean MIDI-intent JSON in `--dry-run` mode or unused in real MIDI mode.

## REAPER Context

Code does not hard-code REAPER plugin parameters. The intended semantic split is:

- `H10 CONTROL`: receives CC10, CC11, Note 36, and CC14; no audio.
- `HEART PULSE`: receives Note 36 and produces a soft pulse.
- `DRONE`: receives CC10 for restrained energy / brightness.
- `BREATH PAD`: receives CC11 for spaciousness / modulation.
- `RR TEXTURE`: receives CC14 for subtle timing or texture variation.

Track creation and plugin parameter MIDI learn stay in REAPER.
