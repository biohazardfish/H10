# H10 Live Performance V4

V4 is a parallel live-performance pipeline. It does not replace the validated
V3 static-meditation bridge or its REAPER project.

## Performance arc

The ordered automatic state machine follows:

`lying open → rising → dance / rolling → sitting return → lying final`

The first ten seconds of still lying calibrate the performer's gravity vector,
median heart rate, and median RR interval. Scene detection only moves forward,
so rolling into a lying orientation during the dance cannot accidentally end
the performance.

The final lying scene does not force heart rate back to its opening value.
Posture and harmony return first; arousal continues to follow the performer's
actual heart-rate recovery.

## Live JSONL schema

`h10_performance_live.py` outputs two event types plus connection status:

```json
{"kind":"heartbeat","t_monotonic_s":123.4,"bpm":109,"rr_ms":550,"beat":1}
{"kind":"motion","t_monotonic_s":123.5,"gravity_unit":[-0.42,0,-0.91],"motion_rms_mg":70,"jerk_rms_mg_s":700,"rotation_rms_deg_s":1}
```

The Polar H10 provides accelerometer data, not a gyroscope stream.
`rotation_rms_deg_s` is the rate of change of the low-pass accelerometer gravity
direction and is named accordingly in diagnostics.

RR intervals pass three checks before entering RMSSD or MIDI mapping:

1. finite and within 270–2000 ms;
2. within `max(40 ms, 15%)` of `60000 / bpm`;
3. within 30% of the rolling median after five accepted intervals.

The 879 ms artifact in the two-minute movement capture is rejected. The
artifact-filtered movement RMSSD is about 3.79 ms instead of 39.1 ms; the
60-second lying capture remains about 7.71 ms.

## MIDI contract

| MIDI | Meaning |
|---|---|
| CC10 ch1 | personalised heart-rate arousal |
| CC11 ch1 | artifact-filtered RMSSD colour |
| CC12 ch1 | log-scaled movement energy |
| CC13 ch1 | uprightness relative to calibrated lying vector |
| CC14 ch1 | accepted RR / pulse gap |
| CC15 ch1 | fluidity derived from jerk-to-motion ratio |
| CC16 ch1 | accelerometer-derived orientation movement |
| CC17 ch1 | slow stillness |
| CC18 ch1 | crossfaded five-scene position |
| CC119 ch1 | performance gate; zero on panic or shutdown |
| Note36 ch10 | heartbeat pulse, velocity 42–72 |

Control changes are rate-limited to 10 Hz and use asymmetric smoothing. The
bridge also refreshes a complete CC/gate snapshot once per second so REAPER can
recover automatically after a MIDI-device reset or late port connection.

## Run

Start the virtual MIDI port before opening or refreshing the V4 REAPER project:

```bash
./midi_bridge/run_performance_live.sh
```

Then open:

`reaper_projects/H10 Live Performance V4.RPP`

One-time REAPER setup: in `Preferences > Audio > MIDI Inputs`, enable both
`H10 Performance V4` and `Arturia - Minilab3 - MIDI` for track input. If the
bridge starts after REAPER, use `Reset all MIDI devices`; the one-second V4
snapshot keepalive restores the gate and current controls without restarting
the performance.

To hear the entire five-scene arc without wearing the H10:

```bash
PERFORMANCE_DEMO_SPEED=2 ./midi_bridge/run_performance_demo.sh --sound
```

For MIDI-intent JSON only:

```bash
./midi_bridge/run_performance_demo.sh --dry-run
```

## REAPER sound architecture

- `H10 CONTROL`: receives `H10 Performance V4`; MIDI only.
- `MINILAB CONTROL`: receives MiniLab channel 2; MIDI only.
- `HEART`: low sine/body pulse with no click transient.
- `EARTH DRONE`: D/A low bed with a retained final-scene ninth.
- `BODY PAD`: modal D/A/E layer controlled by posture and filtered RMSSD.
- `AIR MOTION`: soft grains driven by movement fluidity and orientation change.
- `SPACE RETURN`: dark stereo multi-tap diffusion, with low frequencies kept dry.
- Master: DC blocker and soft safety ceiling.

All continuous generators listen to CC119 and also fade after three seconds
without H10 MIDI activity.

If ACC alone drops, automatic scene advancement freezes and MiniLab manual
control remains available. If HR alone drops, heartbeat notes stop and arousal
releases to neutral within ten seconds. If both streams remain unavailable for
three seconds, the bridge lowers CC119 to zero; any recovered stream restores
the gate unless panic is latched.

## MiniLab 3 User 2

The hardware `User 2` program is reserved for V4. `User 1` remains unchanged.

- Keyboard, knobs, and faders use channel 2.
- Pads use channel 3 and Note 36–43.
- Pads 1–5 force the five scenes.
- Pad 6 resumes AUTO and clears panic.
- Pad 7 held for two seconds recalibrates.
- Pad 8 latches panic.
- Any keyboard note changes root pitch class using a four-second crossfade.
- Knobs CC20–27: room, delay, warmth, movement response, HR response,
  HRV response, stereo width, biosignal depth.
- Faders CC28–31: HEART, EARTH, BODY, AIR levels.

The source template is `midi_bridge/minilab/H10 Performance V4.minilab3`.
The pre-write User 2 backup was saved by MIDI Control Center as
`User 2 2026_07_13 21.12.43.minilab3`.
