"""Focused tests for the static H10 meditation MIDI mapping."""

import io
import json
import math
import os
import sys
from contextlib import redirect_stdout

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bridge as bridge  # noqa: E402


CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mapping_config.json")


def load_mapping_config():
    with open(CONFIG_PATH, encoding="utf-8") as stream:
        return json.load(stream)


def capture_dry_run(fn):
    sink = bridge.MidiSink(dry_run=True, port_name=None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(sink)
    msgs = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    return sink, msgs


def process_messages(events, config=None):
    cfg = config or load_mapping_config()
    states = {}
    derived = bridge.DerivedInputs(rr_window=int(cfg.get("derived_rr_window", 20)))

    def scenario(sink):
        for event in events:
            augmented = derived.update(event)
            bridge.process_event(augmented, cfg, states, sink)

    _, msgs = capture_dry_run(scenario)
    return msgs


def test_active_config_only_contains_static_meditation_outputs():
    cfg = load_mapping_config()
    bridge.validate_config(cfg)
    outputs = []
    for mapping in cfg["mappings"]:
        mode = mapping["mode"]
        if mode == "cc":
            outputs.append(("cc", mapping["cc"]))
        elif mode == "pulse":
            outputs.append(("note", mapping["note"]))
        else:
            outputs.append((mode, None))
    assert outputs == [("cc", 10), ("cc", 11), ("note", 36), ("cc", 14)]


@pytest.mark.parametrize(
    ("hr", "expected"),
    [
        (40, 0),
        (110, 64),
        (180, 127),
        (30, 0),
        (220, 127),
    ],
)
def test_hr_range_maps_to_cc10_values(hr, expected):
    assert bridge.map_range_to_midi(hr, 40, 180) == expected


def test_rmssd_calculation_from_known_rr_sequence():
    assert bridge.calculate_rmssd([800.0, 850.0, 820.0, 860.0]) == pytest.approx(
        math.sqrt(5000.0 / 3.0),
        rel=1e-9,
    )


def test_rmssd_absent_until_two_valid_rr_samples():
    derived = bridge.DerivedInputs()
    first = derived.update({"beat": 1, "rr_ms": 800})
    second = derived.update({"beat": 1, "rr_ms": 810})
    assert "hrv_rmssd" not in first
    assert "hrv_rmssd" in second


@pytest.mark.parametrize("bad", [0, -100, 5000, 10, None, "x", float("nan"), float("inf")])
def test_invalid_rr_values_are_rejected_before_rmssd(bad):
    derived = bridge.DerivedInputs()
    event = derived.update({"beat": 1, "rr_ms": bad})
    assert "rr_ms" not in event
    assert "hrv_rmssd" not in event
    assert list(derived.rr_history) == []


@pytest.mark.parametrize(
    ("rr", "expected"),
    [
        (400, 0),
        (950, 64),
        (1500, 127),
        (300, 0),
        (2000, 127),
    ],
)
def test_rr_range_maps_to_cc14_values(rr, expected):
    assert bridge.map_range_to_midi(rr, 400, 1500) == expected


def test_heartbeat_emits_exactly_one_note36_on_and_matching_off():
    msgs = process_messages([{"beat": 1}])
    note_ons = [m for m in msgs if m["type"] == "note_on" and m["note"] == 36]
    note_offs = [m for m in msgs if m["type"] == "note_off" and m["note"] == 36]
    assert len(note_ons) == 1
    assert len(note_offs) == 1
    assert note_ons[0]["velocity"] == 80
    assert note_offs[0]["velocity"] == 0


def test_duplicate_cc_values_are_suppressed():
    msgs = process_messages([{"bpm": 72}, {"bpm": 72}, {"bpm": 72}])
    cc10 = [m for m in msgs if m["type"] == "cc" and m["cc"] == 10]
    assert len(cc10) == 1


def test_rmssd_to_cc11_waits_for_enough_data_then_emits():
    msgs = process_messages([
        {"beat": 1, "rr_ms": 800},
        {"beat": 1, "rr_ms": 850},
    ])
    cc11 = [m for m in msgs if m["type"] == "cc" and m["cc"] == 11]
    assert len(cc11) == 1
    assert cc11[0]["value"] == bridge.map_range_to_midi(50, 5, 100)


def test_rr_to_cc14_uses_valid_current_rr_only():
    msgs = process_messages([
        {"rr_ms": 0},
        {"rr_ms": 950},
    ])
    cc14 = [m for m in msgs if m["type"] == "cc" and m["cc"] == 14]
    assert len(cc14) == 1
    assert cc14[0]["value"] == 64


def test_nan_and_infinity_do_not_emit_cc_messages():
    cfg = load_mapping_config()
    states = {}

    def scenario(sink):
        for value in [float("nan"), float("inf")]:
            bridge.process_event({"bpm": value, "rr_ms": value, "hrv_rmssd": value}, cfg, states, sink)

    _, msgs = capture_dry_run(scenario)
    assert [m for m in msgs if m["type"] == "cc"] == []


def test_close_releases_active_notes_and_sends_all_notes_off():
    def scenario(sink):
        sink.send_note_on(10, 36, 80, {"source": "beat"})
        sink.close()

    sink, msgs = capture_dry_run(scenario)
    note_offs = [m for m in msgs if m["type"] == "note_off" and m["note"] == 36]
    all_notes_off = [m for m in msgs if m["type"] == "cc" and m["cc"] == bridge.CC_ALL_NOTES_OFF]
    assert len(note_offs) == 1
    assert len(all_notes_off) == 1
    assert all_notes_off[0]["channel"] == 10
    assert sink.active_notes == set()


def test_validate_config_exits_on_error():
    with pytest.raises(SystemExit):
        bridge.validate_config({"mappings": [{"mode": "cc", "channel": 99}]})


def test_config_rejects_non_contract_mapping():
    with pytest.raises(SystemExit):
        bridge.validate_config({
            "mappings": [
                {"input": "bpm", "mode": "cc", "cc": 74, "channel": 1}
            ]
        })


@pytest.mark.parametrize("mode", ["pitchbend", "program_change"])
def test_legacy_performance_modes_are_rejected(mode):
    errs = bridge.validate_mapping(0, {"input": "bpm", "mode": mode, "channel": 1})
    assert any("unknown mode" in err for err in errs)
