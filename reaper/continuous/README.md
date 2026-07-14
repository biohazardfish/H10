# H10 Continuous Body Field REAPER assets

Source-controlled JSFX and setup script for the parallel Continuous Body
Field performance rig. (Its predecessor `reaper/v4/` was archived on
2026-07-15 — recover via the `archive-pre-continuous-cleanup` tag.)

Installed locations:

- `~/Library/Application Support/REAPER/Effects/H10/Continuous/`
- `~/Library/Application Support/REAPER/Scripts/H10/Continuous/`

The setup script creates a new project tab, resolves MIDI input names
instead of hard-coding device numbers, builds the seven-track routing
graph, installs the master guard, and saves:

`/Users/taichengwong/Projects/H10/reaper_projects/H10 Continuous Body Field.RPP`

It never edits the V3 or V4 project tabs.

REAPER's MIDI inputs are global, not project-local. Enable `H10 Continuous
Body Field` and `Arturia - Minilab3 - MIDI` once under Preferences > Audio >
MIDI Inputs. The setup script resolves their current names/IDs and warns
when a resolved device is disabled.

## Phase 2 scope

The six voice JSFX are a warm, restrained ambient palette anchored on
EARTH (2026-07-14 artistic redesign; the earlier bright/fragmented pass
was rejected):

- `h10_continuous_earth.jsfx` — the reference layer, unchanged: low D2
  drone, mostly mono, slow drifting harmonics, rolled off above ~250 Hz
- `h10_continuous_heart.jsfx` — soft pulse: muted low/low-mid thump, soft
  attack, dark lowpass, no noise or bright transient, fixed safe level
- `h10_continuous_body.jsfx` — slow breathing harmony: four near-mono
  detuned voices (D/A/E/G), ~12 s register glides, no fragmentation
- `h10_continuous_air.jsfx` — barely-there breath veil: dark filtered
  noise, slow level slew, no grains/whistle/events
- `h10_continuous_space.jsfx` — dark restrained room: doubly damped,
  high-passed input, short-to-medium tail, glue not subject
- `h10_continuous_melody_voice.jsfx` — soft electric-piano / felted
  hybrid for the MiniLab keyboard (ch2): knob-controlled ADSR, bounded
  tone (hard 4.2 kHz cap), warmth, short dark ambience, H10-influence
  depth. Manual playing only — no arpeggiator or note generation.

MiniLab (ch2): knobs CC20-27 = Melody Attack/Decay/Sustain/Release/
Tone/Warmth/Space/H10-Influence; faders CC28-31 = MELODY, EARTH, BODY,
AIR+SPACE. HEART has no fader (fixed safe level). See
midi_bridge/CONTINUOUS_BODY_FIELD.md for details.

`h10_continuous_master_guard.jsfx` is the V4 master guard with one real
fix: EEL2 has **no `tanh` builtin** -- the V4 original's `tanh()` calls
silently fail to compile and the guard passes audio through unprocessed.
The Continuous version uses `soft_tanh(x) = 1 - 2/(exp(2x)+1)`.
(The V4 copy still has the inert-limiter bug; it was left untouched by
policy.)

## Running the setup script

REAPER's Lua ReaScript API isn't reachable from outside the REAPER
process, so this script must be run from inside REAPER:

1. Actions list (`?`) > New action > Load ReaScript...
2. Select `setup_h10_continuous.lua` (installed copy under
   `~/Library/Application Support/REAPER/Scripts/H10/Continuous/`).
3. Run it. Check the console for `[H10 Continuous setup]` lines — it warns
   if `H10 Continuous Body Field` or the MiniLab input isn't found/enabled.

## Verifying MIDI port, routing, gate, audio, and shutdown silence

With `midi_bridge/run_continuous_demo.sh --sound` running (opens the
`H10 Continuous Body Field` virtual port and streams the replay data):

1. Preferences > Audio > MIDI Inputs — confirm `H10 Continuous Body Field`
   is listed and enabled.
2. In the project, confirm `H10 CONTROL` shows MIDI activity and the five
   voice tracks show input meter movement.
3. Run `audit_h10_continuous_runtime.lua` from the Actions list while the
   demo is running — it writes per-track/master peak levels and FX state
   to `/tmp/h10_continuous_runtime_audit.txt`. Non-zero peaks on HEART/
   EARTH/BODY/AIR/SPACE and the master confirm audio output and routing.
4. Run `audit_h10_continuous_midi_input.lua` to capture 5 seconds of the
   `H10 CONTROL` input and confirm `note36` (heartbeat) and `cc119`
   (performance gate) counts are non-zero in
   `/tmp/h10_continuous_midi_input_audit.txt`.
5. Stop the demo bridge (Ctrl+C) and re-run the runtime audit — all track
   and master peaks should read at/near `0.000000` shortly after, since
   the bridge sends gate=0 and all-notes-off on shutdown.
