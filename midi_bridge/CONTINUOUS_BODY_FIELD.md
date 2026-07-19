# H10 Continuous Body Field

A parallel performance system to V4 (`performance_bridge.py`, untouched).
Where V4 classifies the performer into one of five ordered scenes and
switches sound per scene, this version has **no scenes**: body state maps
continuously to sound-control axes at all times. There is no scene enum,
no scene ordering, no thresholds, no hold timers, no manual scene forcing,
and no scene-specific chord switching anywhere in `continuous_bridge.py`.

Core model: **body state → continuous physiological/movement features →
continuous sound morphology.** Never body state → classify into a scene →
play scene sound.

This document covers Phase 1 only: the Python bridge, config, commands,
and tests. REAPER sound design (HEART/EARTH/BODY/AIR/SPACE) is Phase 2+.

## What's reused vs. new

- **Producer**: `h10_performance_live.py` (unmodified). It already emits
  everything needed — heartbeat (`bpm`/`rr_ms`) and motion
  (`motion_rms_mg`, `jerk_rms_mg_s`, `rotation_rms_deg_s`, `gravity_unit`)
  — so no new producer was created.
- **Scene-agnostic helpers**: imported directly from `performance_bridge.py`
  (also unmodified) — `RRArtifactFilter`, `AsymmetricSmoother`,
  `PerformanceMidiSink` (gate/panic/close), `calculate_rmssd`, and the
  normalize/smoothstep/log-normalize/vector math helpers. None of these
  reference scenes.
- **New**: `continuous_bridge.py` defines `ContinuousEngine`, which keeps
  the same calibration, RR filtering, dropout handling, smoothing, and MIDI
  gate/panic behaviour as V4's `PerformanceEngine`, but with every
  scene-coupled method (`Scene` enum, `_set_scene`, `_advance_scene`,
  `_condition_held`, `manual_mode`, scene-forcing pad handling) removed.

## Continuous axes and MIDI contract

Same 8 CCs as V4, channel 1, values 0–127:

| Axis | CC |
|---|---:|
| Arousal | 10 |
| Regulation | 11 |
| Motion (activity) | 12 |
| Uprightness (verticality) | 13 |
| Pulse gap | 14 |
| Fluidity | 15 |
| Rotation | 16 |
| Stillness | 17 |

Plus performance gate on CC119 (channel 1) and heartbeat on Note 36,
channel 10 — identical to V4.

**CC18 is unused.** It no longer carries a five-step scene position, and
nothing repurposes it in Phase 1. `continuous_mapping.json` fails to load
if `scene_cc`, `scene_values`, or `state_machine` are present, so scene
config can't silently creep back in.

### Recovery (internal only, not yet a CC)

A ninth axis, `recovery`, is computed inside the engine to capture "the
body has physically settled, but the heart has not fully recovered." It
targets the inverse of the already-smoothed arousal value, then applies
its *own*, much slower attack (20s) than release (3s) — so if arousal
declines, recovery climbs slowly and visibly lags behind stillness/
uprightness (which release back to baseline in a few seconds). If arousal
spikes again, recovery drops quickly. This is exposed in the `Continuous
diag` stderr line and in tests, but is **not** sent as a MIDI CC yet — the
spec's preferred option is to leave CC18 unused, so recovery stays internal
until a later phase proposes (with approval) either a dedicated CC or a
derivation purely inside the REAPER JSFX from the existing arousal/
stillness/uprightness CCs.

## Pads

Only Pad 8 (Note 43, channel 3) does anything: it latches panic (gate
down, active notes released, `CC_ALL_NOTES_OFF` sent). Pads 1–7 (Notes
36–42) are read and explicitly ignored — no scene forcing, no AUTO resume,
no recalibration, no freeze, no hidden debug function. Panic is a one-way
latch in this version: there is no "AUTO resume" pad, so recovering from
panic means restarting the bridge process. This follows directly from
"Pad 1 through Pad 7 must do nothing" plus "no AUTO resume" in the spec.

The existing `H10 Performance V4.minilab3` hardware template is untouched
and not required to change — the continuous bridge simply ignores the
notes those pads already send.

## Commands

```sh
# Live (wears the H10, opens virtual port "H10 Continuous Body Field")
midi_bridge/run_continuous_live.sh

# Demo, no H10 needed — replays captured/synthetic data
midi_bridge/run_continuous_demo.sh --dry-run   # prints MIDI as JSON, no MIDI backend needed
midi_bridge/run_continuous_demo.sh --sound     # opens the virtual MIDI port for REAPER

# Audition command: keeps the virtual MIDI port open indefinitely by
# looping the replay instead of exiting after one ~75s cycle. Use this for
# REAPER setup and auditioning — the port stays visible the whole time.
# Stop with Ctrl+C (sends gate 0, note-off, and all-notes-off before exit).
./midi_bridge/run_continuous_demo.sh --sound --loop
```

`run_continuous_demo.sh` reuses `midi_bridge/examples/replay_performance.py`
— that script's `demo_scene` field is descriptive metadata only;
`continuous_bridge.py` never reads it, so scene labels in the replay data
have no effect on continuous behaviour.

### `--loop`

Without `--loop`, `replay_performance.py` emits one ~75-second cycle and
exits — which closes its stdout, so the piped-in bridge sees EOF, shuts
down, and closes the virtual MIDI port. That's what caused REAPER to show
`H10 Continuous Body Field <not found>` once a demo cycle finished.

`--loop` (added to `replay_performance.py`, opt-in, off by default) keeps
the same process, and therefore the same bridge and the same virtual MIDI
port, alive indefinitely:

- Each cycle's existing final "disconnected" status event is followed,
  4 virtual seconds later, by one more "still disconnected" status event.
  That gap is longer than `all_lost_gate_seconds` (3.0 in
  `continuous_mapping.json`), so the bridge's own dropout logic safely
  lowers the performance gate on its own — no process kill involved.
- The next cycle's "reconnected" status event then reopens the gate and
  the recorded stream restarts from `lying_open`.
- Ctrl+C still stops everything cleanly: `continuous_bridge.py`'s existing
  shutdown path (unchanged) sends gate 0, note-off, and all-notes-off.

`--loop` is off by default, so any plain `replay_performance.py`
invocation is byte-for-byte unaffected — confirmed by diffing a
`--speed 1000 --no-sleep` capture before and after this change
(905 lines, 2 status events either way).

The live/demo virtual port is always `H10 Continuous Body Field`, never
`H10 Performance V4`. (The V4 rig itself was archived on 2026-07-15; see
the `archive-pre-continuous-cleanup` tag.)

## Tests

`midi_bridge/tests/test_continuous_bridge.py` (15 tests, all passing
alongside the existing 62 V3/V4 tests — 77 total unaffected):

- RR artifact rejection and RMSSD stability against the real capture used
  by the V4 test suite (identical filter, identical numbers).
- Calibration completes with no scene state anywhere (`hasattr` checks).
- Uprightness rises continuously with no scene-triggered discontinuity.
- Fluidity distinguishes smooth vs. jerky motion.
- Recovery visibly lags arousal's decline, then narrows over time.
- Pads 1–7 are no-ops (zero output emitted); Pad 8 latches panic.
- Shutdown emits gate-zero and all-notes-off.
- Periodic snapshot / 10 Hz CC rate limiting (ported from V4).
- ACC/HR dropout handling (ported from V4).
- Config rejects `scene_cc`/missing `dropout` contract.
- Full replay-data integration smoke test end-to-end.

Manually verified in this phase: `run_continuous_demo.sh --dry-run` and
`--sound` both run the full ~75s replay without error, calibrate, stream
all 8 CCs, and shut down cleanly with gate/notes-off — using the venv
Python (`mido[ports-rtmidi]`) for `--sound`.

## REAPER project (Phases 2-7, complete)

`reaper_projects/H10 Continuous Body Field.RPP` — eight tracks:

| # | Track | Input | FX |
|---|---|---|---|
| 1 | H10 CONTROL | `H10 Continuous Body Field`, all ch | — (MIDI fan-out) |
| 2 | MINILAB CONTROL | `Arturia - Minilab3 - MIDI`, all ch | — (MIDI fan-out) |
| 3 | HEART | — | `H10/Continuous/h10_continuous_heart` |
| 4 | EARTH | — | `H10/Continuous/h10_continuous_earth` |
| 5 | BODY | — | `H10/Continuous/h10_continuous_body` |
| 6 | AIR | — | `H10/Continuous/h10_continuous_air` |
| 7 | SPACE | — | `H10/Continuous/h10_continuous_space` |
| 8 | MELODY VOICE | `Arturia - Minilab3 - MIDI`, ch 2 | `H10/Continuous/h10_continuous_melody_voice` |

Master: `H10/Continuous/h10_continuous_master_guard` (DC block + soft
limit; uses an exp-based `soft_tanh` because EEL2 has **no `tanh`
builtin** — a bare `tanh()` silently disables the whole section).

Routing: H10 CONTROL sends MIDI (all→all, audio none) to HEART, EARTH,
BODY, AIR, SPACE and MELODY VOICE (the melody send carries the bounded
H10 tint CCs plus CC123 panic/shutdown). MINILAB CONTROL sends MIDI to
the five instrument tracks (pads ch3 + macro CCs ch2). Audio sends into
SPACE: HEART 0.05, EARTH 0.15, BODY 0.40, AIR 0.65, MELODY 0.06.

Sound identities (warm restrained ambient palette — one shared world,
anchored on EARTH). A first redesign pass (2026-07-15) fixed an earlier
version that read as too bright/fragmented/game-like; a follow-up pass
(2026-07-20) then widened dynamic range and shortened internal glide
times after live testing showed the first pass had over-corrected into
sounding static and undifferentiated — same restrained/warm character,
now with meaningfully audible reaction to body signals within a
30-60s window instead of 1-2 barely-perceptible transitions:

EARTH = the reference layer and tonal floor (low D2 drone, mostly mono,
spectral drift now on a ~21-45s cycle rather than 45-110s, rolled off
tighter below ~200 Hz to clear BODY's band; harmonic identity unchanged).
EARTH now also reads motion (CC12) as a distinct axis from BODY's —
nudging spectral agitation/drift speed rather than level — and its
internal recovery smoother was shortened from 20s/3s to 3s/1s attack/
release since the bridge already smooths arousal upstream; level swing
widened accordingly. HEART = a soft pulse: muted internal thump (64 Hz
body + quiet 170 Hz pressure bloom, ~7 ms soft attack, dark lowpass, no
noise, no bright transient; identifiable by timing and envelope, never
brightness; arousal's effect on firmness/decay widened from earlier
±12%/-30ms to ±22%/-45ms; fixed safe level, no fader). BODY = slow
breathing harmony (four near-mono detuned voices on D/A/E/G; glide times
shortened -- register ~5s, colour ~3.5s, motion-thinning ~1.5s -- level
range widened, high-passed at 170 Hz to further clear EARTH's band; no
fragmentation). AIR = a breath veil, still the quietest layer by far but
raised from a near-inaudible 0.09 to 0.16 base level and given faster
motion-tracking (1.2s/3s slew); dark filtered pink noise, no grains, no
whistle, no events; fluidity now nudges its stereo drift rate as a small
identity axis distinct from BODY's use of fluidity. SPACE = glue (dark
short-to-medium room, doubly damped highs, high-passed input; stillness/
rotation response ranges widened slightly; still deliberately near-static
-- no memory theatrics, no destabilisation, not a body-driven voice).

## MELODY VOICE (MiniLab keyboard)

A soft electric-piano / felted hybrid
(`h10_continuous_melody_voice.jsfx`), played manually on the MiniLab
keys (ch 2): rounded low-mid body (detuned fundamental pair + gentle
2nd/3rd harmonics), a soft felt bump at the onset (no mallet strike, no
noise, no bell/FM partials), slow shared chorus movement, and a dark
per-voice lowpass hard-capped at 4.2 kHz so the tone moves from dark to
moderately open, never piercing. Strictly performer-driven: no
arpeggiator, sequencer, automatic notes/chords, scale filtering, or
quantisation; chromatic 12-TET. 8-voice polyphonic with a full
knob-controlled ADSR (see knob map below); CC64 sustain; pitch bend
±12 st smooth; velocity shapes level, attack speed and a small
brightness amount; CC1 gives a small bounded brightness assist. H10
influence is depth-controlled by Knob 8 and only breathes tone/warmth —
it never changes pitch, timing, duration or note count. CC123 (bridge
panic or shutdown) clears every voice including pedal-sustained ones.
Foreground by register, envelope and midrange placement; short dark
in-JSFX ambience plus only a 0.06 send into SPACE.

## MiniLab control policy (Continuous)

- Keyboard (ch2): plays MELODY VOICE only. The V4 root-selection
  function does not exist here (`continuous_bridge.py` ignores ch2).
- Pads 1-7 (ch3, notes 36-42): do nothing, by design.
- Pad 8 (ch3, note 43): panic — gate down, notes released, CC123
  everywhere (also clears sustained melody notes).
- Knobs (ch2) — direct MELODY VOICE synthesis controls:
  CC20 Attack, CC21 Decay, CC22 Sustain, CC23 Release, CC24
  Tone/Brightness (bounded, dark→moderately open), CC25 Warmth/Filter,
  CC26 Space (short dark ambience), CC27 H10 Influence (0 = almost no
  tint, max = noticeable but controlled tonal breathing).
- Faders (ch2): CC28 MELODY VOICE, CC29 EARTH, CC30 BODY, CC31
  AIR+SPACE. HEART has no fader — it sits at a fixed safe level so the
  pulse can never dominate the mix.

The MiniLab hardware template (`User 2`, V4) is untouched — the
Continuous JSFX simply interpret the CCs that template already sends.

## Not yet done

A live H10 rehearsal (the only remaining validation that needs the
performer wearing the strap).
