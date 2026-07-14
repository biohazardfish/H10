import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BRIDGE_DIR)
sys.path.insert(0, BRIDGE_DIR)

import continuous_bridge as cont  # noqa: E402


CONFIG = cont.load_config(os.path.join(BRIDGE_DIR, "continuous_mapping.json"))


def sink_and_engine():
    return cont.PerformanceMidiSink(True, None), cont.ContinuousEngine(CONFIG)


def read_capture(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


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
    return {"kind": "heartbeat", "t_monotonic_s": t, "bpm": bpm, "rr_ms": rr, "beat": 1}


def feed_stable_calibration(engine, sink, start=0.0):
    for step in range(111):
        t = start + step / 10
        engine.process_event(motion_event(t, (0, 0, -1)), sink)
        if step % 5 == 0:
            engine.process_event(heartbeat_event(t + 0.001), sink)


def test_real_capture_rr_artifact_is_rejected_and_rmssd_is_stable():
    rows = read_capture(
        Path(ROOT) / "captures/2026-07-13_20-33-08_h10_120s_motion/h10_hr_events.jsonl"
    )
    rr_filter = cont.RRArtifactFilter(CONFIG["rr_filter"])
    accepted = [
        value
        for row in rows
        if (value := rr_filter.accept(row.get("rr_ms"), row.get("bpm"))) is not None
    ]
    assert len(accepted) == 257
    assert rr_filter.rejected == 1
    assert cont.calculate_rmssd(accepted) == pytest.approx(3.79, abs=0.02)


def test_calibration_completes_with_no_scene_state_anywhere():
    sink, engine = sink_and_engine()
    with redirect_stdout(io.StringIO()):
        feed_stable_calibration(engine, sink)
    assert engine.calibrated
    assert not hasattr(engine, "scene")
    assert not hasattr(engine, "manual_mode")
    assert "scene" not in engine.targets


def test_uprightness_rises_continuously_with_no_scene_triggered_jump():
    sink, engine = sink_and_engine()
    engine.calibrated = True
    engine.baseline_gravity = (0, 0, -1)
    readings = []
    with redirect_stdout(io.StringIO()):
        for step in range(21):
            progress = step / 20
            gravity = (-progress, 0, -(1 - progress))
            engine.update_motion(motion_event(step, gravity), step)
            readings.append(engine.targets["uprightness"])
    assert readings[0] < readings[-1]
    diffs = [b - a for a, b in zip(readings, readings[1:])]
    assert all(diff > -0.05 for diff in diffs)


def test_fluidity_distinguishes_smooth_from_jerky_motion():
    _, engine = sink_and_engine()
    engine.update_motion(motion_event(0, (0, 0, -1), 300, 1800, 10), 0)
    smooth = engine.targets["fluidity"]
    engine.update_motion(motion_event(1, (0, 0, -1), 300, 7800, 10), 1)
    jerky = engine.targets["fluidity"]
    assert smooth == pytest.approx(1.0)
    assert jerky == pytest.approx(0.0)


def test_recovery_lags_behind_arousal_decline_then_narrows():
    sink, engine = sink_and_engine()
    with redirect_stdout(io.StringIO()):
        engine.process_event(heartbeat_event(0.0, bpm=139, rr=432), sink)
        for step in range(1, 51):
            engine.tick(step / 10, sink)
        arousal_5s = engine.smoothers["arousal"].value
        recovery_5s = engine.smoothers["recovery"].value
        gap_5s = (1.0 - arousal_5s) - recovery_5s

        for step in range(51, 3001):
            engine.tick(step / 10, sink)
        arousal_300s = engine.smoothers["arousal"].value
        recovery_300s = engine.smoothers["recovery"].value
        gap_300s = (1.0 - arousal_300s) - recovery_300s

    assert gap_5s > 0.05
    assert gap_300s < gap_5s


def test_pads_one_through_seven_are_no_ops_and_pad_eight_panics():
    sink, engine = sink_and_engine()
    output = io.StringIO()
    with redirect_stdout(output):
        for note in range(36, 43):
            engine.handle_control(
                SimpleNamespace(type="note_on", channel=2, note=note, velocity=100), sink, 1
            )
        assert not engine.panic_latched
        assert output.getvalue() == ""

        engine.handle_control(
            SimpleNamespace(type="note_on", channel=2, note=43, velocity=100), sink, 2
        )
    assert engine.panic_latched
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    gate_values = [message["value"] for message in messages if message.get("cc") == 119]
    assert 0 in gate_values


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


def test_acc_dropout_freezes_motion_and_hr_dropout_releases_arousal():
    sink, engine = sink_and_engine()
    engine.calibrated = True
    engine.baseline_gravity = (0, 0, -1)
    with redirect_stdout(io.StringIO()):
        engine.process_event(heartbeat_event(1.0, bpm=130, rr=462), sink)
        engine.process_event(motion_event(1.0, (-1, 0, 0), 500, 3000, 30), sink)
        engine.tick(4.0, sink)
    assert not engine.heart_available
    assert not engine.motion_available
    assert engine.targets["arousal"] == 0.0


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


def test_config_has_exact_continuous_midi_contract_and_no_scene_cc():
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
    assert CONFIG["midi"]["performance_gate_cc"] == 119
    assert "scene_cc" not in CONFIG["midi"]
    assert "scene_values" not in CONFIG["midi"]
    assert "state_machine" not in CONFIG
    assert 18 not in CONFIG["midi"]["signals"].values()


def test_config_validation_rejects_scene_cc(tmp_path):
    broken = json.loads(json.dumps(CONFIG))
    broken["midi"]["scene_cc"] = 18
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="scene_cc"):
        cont.load_config(path)


def test_config_validation_rejects_missing_dropout_contract(tmp_path):
    broken = json.loads(json.dumps(CONFIG))
    broken.pop("dropout")
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="dropout"):
        cont.load_config(path)


def test_replay_performance_events_drive_continuous_engine_without_scene_coupling():
    examples_dir = os.path.join(BRIDGE_DIR, "examples")
    sys.path.insert(0, examples_dir)
    import replay_performance  # noqa: E402

    sink, engine = sink_and_engine()
    events = replay_performance.build_events(base_time=0.0)
    with redirect_stdout(io.StringIO()):
        for _virtual_time, event in events[:200]:
            engine.process_event(event, sink)
    assert engine.stable_started_at is not None or engine.calibrated
    assert "scene" not in engine.targets
