import io
import json
import math
import os
import statistics
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BRIDGE_DIR)
sys.path.insert(0, BRIDGE_DIR)

import performance_bridge as perf  # noqa: E402


CONFIG = perf.load_config(os.path.join(BRIDGE_DIR, "performance_mapping.json"))


def sink_and_engine():
    return perf.PerformanceMidiSink(True, None), perf.PerformanceEngine(CONFIG)


def read_capture(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def test_real_capture_rr_artifact_is_rejected_and_rmssd_is_stable():
    rows = read_capture(
        Path(ROOT) / "captures/2026-07-13_20-33-08_h10_120s_motion/h10_hr_events.jsonl"
    )
    rr_filter = perf.RRArtifactFilter(CONFIG["rr_filter"])
    accepted = [
        value
        for row in rows
        if (value := rr_filter.accept(row.get("rr_ms"), row.get("bpm"))) is not None
    ]
    assert len(accepted) == 257
    assert rr_filter.rejected == 1
    assert max(accepted) < 600
    assert perf.calculate_rmssd(accepted) == pytest.approx(3.79, abs=0.02)


def test_static_capture_rmssd_remains_approximately_7_7_ms():
    rows = read_capture(Path(ROOT) / "captures/2026-07-13_20-22-57_h10_60s/h10_events.jsonl")
    rr_filter = perf.RRArtifactFilter(CONFIG["rr_filter"])
    accepted = [
        value
        for row in rows
        if (value := rr_filter.accept(row.get("rr_ms"), row.get("bpm"))) is not None
    ]
    assert perf.calculate_rmssd(accepted) == pytest.approx(7.707, abs=0.01)


def test_rmssd_and_sdnn_known_rr_sequence():
    values = [500.0, 510.0, 490.0, 505.0]
    assert perf.calculate_rmssd(values) == pytest.approx(15.5456, abs=0.001)
    assert perf.calculate_sdnn(values) == pytest.approx(statistics.stdev(values))


def motion_event(t, gravity, motion=70, jerk=700, rotation=1):
    return {
        "kind": "motion",
        "t_monotonic_s": t,
        "gravity_unit": gravity,
        "motion_rms_mg": motion,
        "jerk_rms_mg_s": jerk,
        "rotation_rms_deg_s": rotation,
    }


def heartbeat_event(t, bpm=109, rr=550):
    return {
        "kind": "heartbeat",
        "t_monotonic_s": t,
        "bpm": bpm,
        "rr_ms": rr,
        "beat": 1,
    }


def feed_stable_calibration(engine, sink, start=0.0):
    for step in range(111):
        t = start + step / 10
        engine.process_event(motion_event(t, (0, 0, -1)), sink)
        if step % 5 == 0:
            engine.process_event(heartbeat_event(t + 0.001), sink)


def test_ordered_scene_state_machine_reaches_all_five_scenes():
    sink, engine = sink_and_engine()
    with redirect_stdout(io.StringIO()):
        feed_stable_calibration(engine, sink)
        assert engine.calibrated
        assert engine.scene == perf.Scene.LYING_OPEN

        for step in range(23):
            engine.process_event(motion_event(11.1 + step / 10, (-1, 0, 0), 100), sink)
        assert engine.scene == perf.Scene.RISING

        for step in range(75):
            engine.process_event(motion_event(13.4 + step / 10, (-1, 0, 0), 350, 2600, 25), sink)
        assert engine.scene == perf.Scene.DANCE

        for step in range(65):
            engine.process_event(motion_event(20.9 + step / 10, (-1, 0, 0), 70), sink)
        assert engine.scene == perf.Scene.SITTING_RETURN

        for step in range(55):
            engine.process_event(motion_event(27.4 + step / 10, (0, 0, -1), 70), sink)
        assert engine.scene == perf.Scene.LYING_FINAL


def test_rolling_during_dance_does_not_skip_to_final_scene():
    sink, engine = sink_and_engine()
    engine.calibrated = True
    engine.baseline_gravity = (0, 0, -1)
    engine.scene = perf.Scene.DANCE
    engine.scene_entered_at = 0
    with redirect_stdout(io.StringIO()):
        for step in range(100):
            engine.process_event(
                motion_event(step / 10, (0, 0, -1), 400, 3000, 30), sink
            )
    assert engine.scene == perf.Scene.DANCE


def test_fluidity_distinguishes_smooth_from_jerky_motion():
    _, engine = sink_and_engine()
    engine.update_motion(motion_event(0, (0, 0, -1), 300, 1800, 10), 0)
    smooth = engine.targets["fluidity"]
    engine.update_motion(motion_event(1, (0, 0, -1), 300, 7800, 10), 1)
    jerky = engine.targets["fluidity"]
    assert smooth == pytest.approx(1.0)
    assert jerky == pytest.approx(0.0)


def test_minilab_manual_override_auto_resume_and_panic():
    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        engine.handle_control(SimpleNamespace(type="note_on", channel=2, note=38, velocity=100), sink, 1)
        assert engine.scene == perf.Scene.DANCE
        assert engine.manual_mode
        engine.handle_control(SimpleNamespace(type="note_on", channel=2, note=43, velocity=100), sink, 2)
        assert engine.panic_latched
        engine.handle_control(SimpleNamespace(type="note_on", channel=2, note=41, velocity=100), sink, 3)
    assert not engine.panic_latched
    assert not engine.manual_mode
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    gate = [message["value"] for message in messages if message.get("cc") == 119]
    assert 0 in gate and 127 in gate


def test_recalibration_requires_two_second_pad_hold():
    sink, engine = sink_and_engine()
    engine.calibrated = True
    engine.baseline_gravity = (0, 0, -1)
    with redirect_stdout(io.StringIO()):
        engine.handle_control(SimpleNamespace(type="note_on", channel=2, note=42, velocity=100), sink, 1)
        engine.handle_control(SimpleNamespace(type="note_off", channel=2, note=42, velocity=0), sink, 3.1)
    assert not engine.calibrated


def test_final_lying_does_not_force_arousal_to_opening_value():
    sink, engine = sink_and_engine()
    engine.calibrated = True
    engine.baseline_bpm = 109
    engine.baseline_gravity = (0, 0, -1)
    engine.scene = perf.Scene.LYING_FINAL
    with redirect_stdout(io.StringIO()):
        engine.process_event(heartbeat_event(1, bpm=124, rr=484), sink)
        engine.process_event(motion_event(1.1, (0, 0, -1), 70), sink)
    assert engine.targets["uprightness"] == 0
    assert engine.targets["arousal"] > 0.4


def test_shutdown_emits_gate_zero_and_all_notes_off():
    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        engine.process_event(heartbeat_event(1), sink)
        engine.shutdown(sink)
        sink.close()
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert any(message.get("cc") == 119 and message.get("value") == 0 for message in messages)
    assert any(message.get("cc") == 123 for message in messages)


def test_periodic_snapshot_refreshes_gate_and_controls_after_midi_reconnect():
    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        engine.tick(0.0, sink)
        engine.tick(0.5, sink)
        engine.tick(1.1, sink)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    gate_on = [
        message for message in messages
        if message.get("cc") == 119 and message.get("value") == 127
    ]
    arousal = [message for message in messages if message.get("cc") == 10]
    assert len(gate_on) == 2
    assert len(arousal) == 2


def test_continuous_cc_output_is_rate_limited_to_ten_hz():
    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        engine.tick(0.0, sink)
        initial_count = len(output.getvalue().splitlines())
        engine.targets["motion"] = 1.0
        engine.tick(0.05, sink)
        assert len(output.getvalue().splitlines()) == initial_count
        engine.tick(0.11, sink)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert any(message.get("cc") == 12 and message.get("value", 0) > 0 for message in messages)


def test_acc_dropout_freezes_auto_scene_and_hr_dropout_releases_arousal():
    sink, engine = sink_and_engine()
    engine.calibrated = True
    engine.baseline_gravity = (0, 0, -1)
    engine.scene = perf.Scene.DANCE
    with redirect_stdout(io.StringIO()):
        engine.process_event(heartbeat_event(1.0, bpm=130, rr=462), sink)
        engine.process_event(motion_event(1.0, (-1, 0, 0), 500, 3000, 30), sink)
        engine.tick(4.0, sink)
    assert not engine.heart_available
    assert not engine.motion_available
    assert engine.targets["arousal"] == 0.0
    assert engine.scene == perf.Scene.DANCE


def test_hr_dropout_brings_arousal_close_to_neutral_within_ten_seconds():
    sink, engine = sink_and_engine()
    with redirect_stdout(io.StringIO()):
        engine.process_event(heartbeat_event(0.0, bpm=139, rr=432), sink)
        for step in range(1, 31):
            engine.tick(step / 10, sink)
        assert engine.smoothers["arousal"].value > 0.5
        for step in range(31, 131):
            engine.tick(step / 10, sink)
    assert not engine.heart_available
    assert engine.smoothers["arousal"].value < 0.05


def test_both_signal_dropout_closes_gate_after_three_seconds_and_recovers():
    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        engine.process_event(
            {"kind": "status", "t_monotonic_s": 0.0,
             "heart_available": False, "motion_available": False},
            sink,
        )
        engine.tick(2.9, sink)
        engine.tick(3.1, sink)
        engine.process_event(heartbeat_event(3.2), sink)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    gate_values = [message["value"] for message in messages if message.get("cc") == 119]
    assert 0 in gate_values
    assert gate_values[-1] == 127


def test_config_has_exact_v4_midi_contract():
    assert CONFIG["midi"]["signals"] == {
        "arousal": 10,
        "regulation": 11,
        "motion": 12,
        "uprightness": 13,
        "pulse_gap": 14,
        "fluidity": 15,
        "rotation": 16,
        "stillness": 17,
    }
    assert CONFIG["midi"]["scene_cc"] == 18
    assert CONFIG["midi"]["performance_gate_cc"] == 119


def test_config_validation_rejects_missing_dropout_contract(tmp_path):
    broken = json.loads(json.dumps(CONFIG))
    broken.pop("dropout")
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="dropout"):
        perf.load_config(path)
