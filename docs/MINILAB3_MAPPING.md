# MiniLab 3 Mapping - H10 Ambient Preset Template v3

## Input

- REAPER device: `Arturia - Minilab3 - MIDI` (input index 0)
- Project input: MIDI channel 1 (`I_RECINPUT=4097`)
- Track: `SOFT FELT - Piano Remains 1 (MINILAB)`
- Record arm and input monitoring: enabled
- Octave transpose: none
- FX order: Surge XT (`Piano Remains 1`), then the retained stock arpeggiator (bypassed)
- The original felt MIDI item is retained but muted. Pitch, rhythm, velocity, and phrasing come from the MiniLab.

The connected MiniLab 3 is firmware 1.2.0, device memory `User 1`, with default keyboard channel 1. MIDI Control Center reports all eight knobs as absolute CC controls over 0-127 and all four faders as absolute faders over 0-127.

## Performance Mapping

| Control | MIDI | Target | Safe range |
|---|---:|---|---|
| Knob 1 | CC74 | Surge A Filter 1 Cutoff | 793.10-2269.29 Hz |
| Knob 2 | CC71 | Surge A Amp EG Attack | 5.6-69.8 ms |
| Knob 3 | CC76 | Surge A Amp EG Release | 554.8 ms-2.57 s |
| Knob 4 | CC77 | Surge A LFO 2 Amplitude | 14-26% |
| Knob 5 | CC93 | Surge factory Delay S1 send | -35.59 to -14.53 dB |
| Knob 6 | CC18 | Surge factory Delay S1 feedback | 50-70% |
| Knob 7 | CC19 | Surge scene width | 56-100% |
| Knob 8 | CC16 | Surge Osc 1 Shape | 10-17% |
| Fader 1 | CC82 | Surge Global Volume (melody only) | -9.60 to 0.00 dB |

Knob 5 uses the preset's existing dark delay instead of the shared reverb. This keeps MiniLab performance control separate from H10 CC17 and avoids shared reverb buildup.

## Other Controls

| Control | MIDI behavior | Project behavior |
|---|---|---|
| Fader 2 | CC83, absolute 0-127 | Unmapped |
| Fader 3 | CC85, absolute 0-127 | Unmapped |
| Fader 4 | CC17, absolute 0-127 | Unmapped; reserved to avoid H10 CC17 ambiguity |
| Modulation strip | CC1, 0-127 | Passed directly to Surge XT |
| Pitch strip | Pitch bend | Passed directly to Surge XT, +/-2 semitones |
| Control/pedal input | Sustain CC64 when available | Passed directly to Surge XT |

## H10 Separation

The local replay remains `captures/2026-07-13_20-33-08_h10_120s_motion/` through the existing `h10demoplay` workflow. No live Polar H10 input is used.

- CC11 regulation: Warmbo brightness, unchanged
- CC12 motion: moved from the bypassed arp to a narrow Air Spray global-volume range (-4.80 to 0.00 dB inside Surge)
- CC15 fluidity: Air Spray modulation depth, unchanged
- CC16 rotation: dark delay stereo movement, unchanged
- CC17 stillness: shared reverb behavior, unchanged
- CC10 arousal and heartbeat note sonification: not mapped

The H10 CONTROL send to the felt track is MIDI-disabled. This prevents heartbeat notes and same-number H10/MiniLab CCs from entering the melody chain. MiniLab data affects only the felt track; H10 continues to affect the ambient background and shared environment.

## Verification

- H10 replay without melody: master peak `-13.40 dBFS`
- Representative H10 + melody/control test: master peak `-13.38 dBFS`; felt peak `-20.36 dBFS`
- Low, medium, and high velocity; legato; repeated notes; intervals; small chords; pitch bend; modulation; sustain messages; and every mapped control endpoint were exercised with temporary MIDI test events.
- Transport stop and panic decayed to approximately `-154 dBFS`; no stuck notes remained.
- REAPER MIDI reset rediscovered `Arturia - Minilab3 - MIDI` successfully.

Physical knob/fader movement and a physical pedal event were not captured during this pass; the CC assignments and absolute modes above were read directly from the connected device memory in MIDI Control Center. Physical USB unplug/replug was not performed.
