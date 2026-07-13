# MiniLab 3 → H10 V4 / REAPER

## V4 hardware program (User 2)

The V4 performance mapping is stored in MiniLab 3 hardware `User 2`. `User 1`
and the earlier ReaSynth playground mapping remain available as fallback.

| Control | MIDI | V4 target |
|---|---:|---|
| Keyboard | channel 2 notes | root pitch class, 4-second crossfade |
| Knob 1–8 | CC20–27, ch2 | room, delay, warmth, motion, HR, HRV, width, biosignal depth |
| Fader 1–4 | CC28–31, ch2 | HEART, EARTH, BODY, AIR levels |
| Pad 1–5 | Note36–40, ch3 | force scenes 1–5 |
| Pad 6 | Note41, ch3 | resume AUTO / clear panic |
| Pad 7 | Note42, ch3 | hold two seconds to recalibrate |
| Pad 8 | Note43, ch3 | latch panic |

Template source: `midi_bridge/minilab/H10 Performance V4.minilab3`.

## Legacy ReaSynth playground

The current REAPER project contains a track named `MiniLab 3 Tuning Input`.
It listens to the physical `Arturia - Minilab3 - MIDI` input on all MIDI
channels and routes MIDI to both `H10 HRV Drone` and `H10 Kick`.

The prepared ReaSynth Learn assignments use MIDI channel 2 and absolute MIDI
CC values. H10 remains on channels 1 and 10, so the controller does not collide
with the heartbeat bridge.

## MiniLab 3 User Program

In MIDI Control Center, create or edit one User Program and set its MIDI
channel to 2. Use these CC assignments:

| Control | CC | REAPER target |
|---|---:|---|
| Encoder 1 | 20 | Drone: Attack |
| Encoder 2 | 21 | Drone: Decay |
| Encoder 3 | 22 | Drone: Sustain |
| Encoder 4 | 23 | Drone: Release |
| Encoder 5 | 24 | Drone: Saw mix |
| Encoder 6 | 25 | Drone: Triangle mix |
| Encoder 7 | 26 | Drone: Extra sine mix |
| Encoder 8 | 27 | Drone: Pulse Width |
| Fader 1 | 28 | Kick: Volume |
| Fader 2 | 29 | Kick: Extra sine mix |
| Fader 3 | 30 | Kick: Decay |
| Fader 4 | 31 | Kick: Saw mix |

Keep the keyboard on MIDI channel 2. Pitch bend can remain Pitch Bend; the
modulation strip can remain Mod Wheel for now.

## REAPER operation

The Learn assignments are already stored in the current project. Enable the
MiniLab's `MiniLab 3 MIDI` input if REAPER does not show activity. Arm and
monitor `MiniLab 3 Tuning Input`; it is already configured to do both.

If the project is opened on another machine, the fallback manual procedure is:

1. Open a ReaSynth instance and click `Param`.
2. Choose `FX parameter list` → `Learn` for the target parameter.
3. Move the corresponding MiniLab control once.
4. Use absolute mode and enable soft takeover where available.

The project currently has one undo step named `Set up MiniLab 3 User Program
MIDI routing and ReaSynth Learn`.
