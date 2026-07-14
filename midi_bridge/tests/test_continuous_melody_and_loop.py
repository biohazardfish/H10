"""Phase B/E tests: MELODY VOICE control policy, no auto-notes, --loop clock.

The Melody Voice instrument itself is a REAPER JSFX (audio behaviour is
verified in-REAPER); these tests pin the bridge-side contract (keyboard has
no bridge function, panic reaches the melody track via CC123 on channel 1)
and static properties of the JSFX/setup sources that a pytest can check.
"""

import io
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BRIDGE_DIR)
sys.path.insert(0, BRIDGE_DIR)

import continuous_bridge as cont  # noqa: E402

CONFIG = cont.load_config(os.path.join(BRIDGE_DIR, "continuous_mapping.json"))
CONTINUOUS_DIR = Path(ROOT) / "reaper" / "continuous"
MELODY_JSFX = (CONTINUOUS_DIR / "h10_continuous_melody_voice.jsfx").read_text()
SETUP_LUA = (CONTINUOUS_DIR / "setup_h10_continuous.lua").read_text()


def sink_and_engine():
    return cont.PerformanceMidiSink(True, None), cont.ContinuousEngine(CONFIG)


def test_keyboard_notes_have_no_root_selection_or_any_bridge_function():
    """MiniLab keyboard (channel 2) must be a bridge no-op: melody notes go
    straight to REAPER and never change bridge state or emit MIDI."""
    sink, engine = sink_and_engine()
    before = dict(engine.targets)
    output = io.StringIO()
    with redirect_stdout(output):
        for note in (48, 50, 55, 62, 69, 74):
            engine.handle_control(
                SimpleNamespace(type="note_on", channel=1, note=note, velocity=100), sink, 1
            )
            engine.handle_control(
                SimpleNamespace(type="note_off", channel=1, note=note, velocity=0), sink, 1
            )
    assert output.getvalue() == ""
    assert engine.targets == before
    assert not engine.panic_latched
    assert not hasattr(engine, "root")
    assert not hasattr(engine, "root_pitch_class")


def test_engine_emits_no_notes_other_than_heartbeat_note36_channel10():
    """No arpeggiator / sequencer / automatic note generation anywhere: a
    full replay cycle may only ever produce the heartbeat note."""
    examples_dir = os.path.join(BRIDGE_DIR, "examples")
    sys.path.insert(0, examples_dir)
    import replay_performance

    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        for _t, event in replay_performance.build_events(base_time=0.0):
            engine.process_event(event, sink)
        engine.shutdown(sink)
        sink.close()
    notes = [
        json.loads(line)
        for line in output.getvalue().splitlines()
        if json.loads(line).get("type") in ("note_on", "note_off")
    ]
    assert notes, "heartbeat notes should exist"
    assert all(m["channel"] == 10 and m["note"] == 36 for m in notes)


def test_pad8_panic_reaches_melody_channel_via_cc123_on_channel_1():
    """The melody JSFX clears sustained voices on CC123 arriving from the
    H10 CONTROL send; the bridge must therefore emit CC123 on channel 1."""
    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        engine.handle_control(
            SimpleNamespace(type="note_on", channel=2, note=43, velocity=100), sink, 1
        )
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    cc123_channels = {m["channel"] for m in messages if m.get("cc") == 123}
    assert 1 in cc123_channels
    assert 10 in cc123_channels


def test_loop_replay_timestamps_are_monotonic_and_anchored_to_monotonic_clock():
    """--loop cycles must keep t_monotonic_s in the SAME clock domain the
    bridge's idle tick uses (time.monotonic()) and strictly non-decreasing
    across cycle boundaries; a 0-based anchor makes every event look stale
    and permanently closes the performance gate (regression 2026-07-14)."""
    anchor = time.monotonic()
    proc = subprocess.Popen(
        [
            sys.executable,
            os.path.join(BRIDGE_DIR, "examples", "replay_performance.py"),
            "--speed", "1000", "--no-sleep", "--loop",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    lines = []
    try:
        for line in proc.stdout:
            lines.append(json.loads(line))
            if len(lines) >= 2200:  # comfortably past one ~905-event cycle
                break
    finally:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5)

    stamps = [e["t_monotonic_s"] for e in lines]
    assert all(b >= a for a, b in zip(stamps, stamps[1:])), "timestamps must never rewind"
    assert stamps[0] >= anchor - 1.0, "loop timestamps must anchor to time.monotonic()"
    # the run crossed at least one cycle boundary (gap event 4 s after the
    # cycle's own disconnect) and kept increasing afterwards
    statuses = [e for e in lines if e.get("kind") == "status" and e.get("connected") is False]
    assert len(statuses) >= 2


def strip_jsfx_comments(source):
    return "\n".join(line.split("//")[0] for line in source.splitlines())


def test_no_jsfx_uses_the_nonexistent_tanh_builtin():
    """EEL2 has no tanh(); a bare call silently breaks the section (the
    master guard shipped inert this way). Only soft_tanh implementations
    may appear."""
    for path in sorted(CONTINUOUS_DIR.glob("*.jsfx")):
        source = strip_jsfx_comments(path.read_text())
        bare = re.findall(r"(?<![a-z_])tanh\s*\(", source)
        assert not bare, f"{path.name} calls tanh(), which does not exist in EEL2"


def test_melody_jsfx_contract():
    """Static contract of the melody instrument source."""
    # sustain pedal, panic, pitch bend all handled
    assert "data1 == 64" in MELODY_JSFX
    assert "data1 == 123" in MELODY_JSFX
    assert "$xE0" in MELODY_JSFX
    # +/-12 semitone bend range
    assert "/ 8192 * 12" in MELODY_JSFX
    # at least 4-voice polyphony
    nvoices = re.search(r"NVOICES\s*=\s*(\d+)", MELODY_JSFX)
    assert nvoices and int(nvoices.group(1)) >= 4
    # keyboard channel 2 (chan index 1) and H10 tint channel 1 (chan index 0)
    assert "chan == 1 ?" in MELODY_JSFX
    # H10 tint stays bounded and never rewrites pitch: the only place note
    # frequency is derived must be note_freq(note) at note-on
    assert MELODY_JSFX.count("note_freq(") == 2  # definition + voice_start
    # no arpeggiator/sequencer/auto-generation constructs in actual code
    code_only = strip_jsfx_comments(MELODY_JSFX).lower()
    for banned in ("arp", "sequenc", "auto_note", "quantiz"):
        assert banned not in code_only


def test_melody_knobs_control_adsr_tone_warmth_space_and_h10_influence():
    """Knobs 1-8 (ch2 CC20-27) are direct Melody Voice synthesis controls."""
    for cc, name in ((20, "k_attack"), (21, "k_decay"), (22, "k_sustain"),
                     (23, "k_release"), (24, "k_tone"), (25, "k_warmth"),
                     (26, "k_space"), (27, "k_infl")):
        assert re.search(rf"data1 == {cc} \? {name} = data2 / 127", MELODY_JSFX), \
            f"CC{cc} must set {name}"
    # ADSR values actually shape envelope coefficients
    for var in ("a_coef", "d_coef", "r_coef", "sustain_k"):
        assert var in MELODY_JSFX
    # tone is hard-capped so the voice can never turn piercing
    assert "min(4200" in MELODY_JSFX
    # H10 influence is depth-scaled and bounded (multiplied by infl_k)
    assert "* infl_k" in MELODY_JSFX
    # ambience wet is bounded
    assert re.search(r"amb_wet = space_k \* 0\.3", MELODY_JSFX)


def test_fader_mapping_melody_earth_body_airspace():
    """Faders 1-4 (ch2 CC28-31): MELODY, EARTH, BODY, AIR+SPACE.
    HEART deliberately has no fader (fixed safe level)."""
    sources = {
        name: (CONTINUOUS_DIR / f"h10_continuous_{name}.jsfx").read_text()
        for name in ("melody_voice", "earth", "body", "air", "space", "heart")
    }
    assert "data1 == 28 ? fader_level" in sources["melody_voice"]
    assert "data1 == 29 ? fader_level" in sources["earth"]
    assert "data1 == 30 ? fader_level" in sources["body"]
    assert "data1 == 31 ? fader_level" in sources["air"]
    assert "data1 == 31 ? fader_level" in sources["space"]
    # HEART reads no ch2 (MiniLab) CCs at all
    assert "chan == 1" not in strip_jsfx_comments(sources["heart"])
    # the retired abstract macros are gone from the instruments
    for name in ("earth", "body", "air", "space", "heart"):
        code = strip_jsfx_comments(sources[name])
        for cc in (20, 21, 22, 23, 24, 25, 26, 27):
            assert f"data1 == {cc} ?" not in code, f"{name} still reads CC{cc}"


def test_air_has_no_bright_event_generator():
    """AIR is a low-level veil: no whistle tone, no grain scheduler, no
    bright descending events."""
    air = strip_jsfx_comments((CONTINUOUS_DIR / "h10_continuous_air.jsfx").read_text())
    for banned in ("tone_phase", "grain", "gliss", "meteor", "counter >= period"):
        assert banned not in air
    heart = strip_jsfx_comments((CONTINUOUS_DIR / "h10_continuous_heart.jsfx").read_text())
    # HEART has no noise burst / bandpass knock either
    for banned in ("rand(", "knock", "bp_f"):
        assert banned not in heart


def test_setup_script_builds_melody_voice_track():
    assert 'MELODY VOICE' in SETUP_LUA
    assert "h10_continuous_melody_voice" in SETUP_LUA
    # MiniLab keyboard channel 2 -> midi_input(mini_index, 1)
    assert re.search(r"midi_input\(mini_index,\s*1\)", SETUP_LUA)
    # melody keeps a deliberately small SPACE send
    assert re.search(r"set_space_send_volume\(melody,\s*space,\s*0\.0\d", SETUP_LUA)
