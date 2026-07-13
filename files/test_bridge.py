"""Focused reliability tests for the H10 -> MIDI bridge (item 7, bridge side).

These cover the pure-Python logic and need no BLE hardware or MIDI backend:
  - HRV RMSSD / SDNN maths
  - invalid-RR filtering (Fix 2)
  - signed rr_delta (Fix 3)
  - Note cleanup / All-Notes-Off on shutdown (Fix 1)
  - Program Change zone exit & re-entry (Fix 4)
  - config validation
"""

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bridge_fixed as bridge  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def feed(derived, **event):
    return derived.update(event)


def capture_dry_run(fn):
    """Run *fn(sink)* on a dry-run sink, returning the emitted JSON messages."""
    import io
    from contextlib import redirect_stdout
    sink = bridge.MidiSink(dry_run=True, port_name=None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(sink)
    msgs = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
    return sink, msgs


# ---------------------------------------------------------------------------
# HRV maths
# ---------------------------------------------------------------------------

def test_rmssd_and_sdnn_match_manual_calc():
    d = bridge.DerivedInputs(rr_window=20)
    seq = [800.0, 850.0, 820.0, 860.0]
    aug = {}
    for rr in seq:
        aug = feed(d, beat=1, rr_ms=rr)

    # SDNN over [800,850,820,860]: mean 832.5, var 568.75
    assert aug["hrv_sdnn"] == pytest.approx(math.sqrt(568.75), rel=1e-9)
    # RMSSD over successive diffs [50,-30,40]: sqrt(5000/3)
    assert aug["hrv_rmssd"] == pytest.approx(math.sqrt(5000.0 / 3.0), rel=1e-9)


def test_hrv_absent_until_two_samples():
    d = bridge.DerivedInputs()
    a1 = feed(d, beat=1, rr_ms=800)
    assert "hrv_rmssd" not in a1 and "hrv_sdnn" not in a1
    a2 = feed(d, beat=1, rr_ms=810)
    assert "hrv_rmssd" in a2 and "hrv_sdnn" in a2


# ---------------------------------------------------------------------------
# Fix 2 — invalid RR filtering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [0, -100, 5000, 10, None, "x", float("nan")])
def test_invalid_rr_is_dropped(bad):
    d = bridge.DerivedInputs()
    aug = feed(d, beat=1, rr_ms=bad)
    assert "rr_ms" not in aug          # stripped so no mapping consumes it
    assert "rr_delta" not in aug
    assert "hrv_rmssd" not in aug
    assert len(d.rr_history) == 0      # bogus value never enters HRV maths


def test_valid_rr_after_invalid_still_clean():
    d = bridge.DerivedInputs()
    feed(d, beat=1, rr_ms=0)           # dropped
    feed(d, beat=1, rr_ms=-5)          # dropped
    aug = feed(d, beat=1, rr_ms=800)   # first real sample
    assert aug["rr_ms"] == 800
    assert list(d.rr_history) == [800.0]
    assert "rr_delta" not in aug       # no prior valid sample yet


def test_is_valid_rr_bounds():
    assert bridge.is_valid_rr(270) and bridge.is_valid_rr(2000)
    assert not bridge.is_valid_rr(269.9)
    assert not bridge.is_valid_rr(2000.1)
    assert not bridge.is_valid_rr(0)
    assert not bridge.is_valid_rr(None)


# ---------------------------------------------------------------------------
# Fix 3 — signed rr_delta
# ---------------------------------------------------------------------------

def test_rr_delta_is_signed():
    d = bridge.DerivedInputs()
    feed(d, beat=1, rr_ms=800)
    up = feed(d, beat=1, rr_ms=850)    # lengthening -> positive
    assert up["rr_delta"] == pytest.approx(50.0)
    down = feed(d, beat=1, rr_ms=820)  # shortening -> negative (was abs() before)
    assert down["rr_delta"] == pytest.approx(-30.0)


def test_signed_delta_drives_bidirectional_pitchbend():
    # -80..80 mapping: delta 0 -> centre, +80 -> up, -80 -> down
    assert bridge.to_pitchbend(bridge.normalize(0.0, -80, 80)) == pytest.approx(0, abs=1)
    assert bridge.to_pitchbend(bridge.normalize(80.0, -80, 80)) == 8191
    assert bridge.to_pitchbend(bridge.normalize(-80.0, -80, 80)) == -8192


# ---------------------------------------------------------------------------
# Fix 1 — note cleanup on shutdown
# ---------------------------------------------------------------------------

def test_close_releases_active_notes_and_all_notes_off():
    def scenario(sink):
        # drone note_on (ch1) + kick pulse (ch10), nothing turned off yet
        sink.send_note_on(1, 48, 80, {"source": "beat"})
        sink.send_note_on(10, 36, 100, {"source": "beat"})
        sink.send_cc(1, 74, 60, {"source": "bpm"})   # touches ch1 (already used)
        sink.close()

    sink, msgs = capture_dry_run(scenario)

    note_offs = {(m["channel"], m["note"]) for m in msgs if m["type"] == "note_off"}
    assert (1, 48) in note_offs and (10, 36) in note_offs   # drone + kick released

    all_notes_off = {m["channel"] for m in msgs
                     if m["type"] == "cc" and m["cc"] == bridge.CC_ALL_NOTES_OFF}
    assert all_notes_off == {1, 10}          # CC123 on every used channel
    assert sink.active_notes == set()        # bookkeeping cleared


def test_close_is_idempotent():
    def scenario(sink):
        sink.send_note_on(1, 60, 90, {"source": "beat"})
        sink.close()
        sink.close()   # second call must not double-emit or error
    sink, msgs = capture_dry_run(scenario)
    offs = [m for m in msgs if m["type"] == "note_off" and m["note"] == 60]
    assert len(offs) == 1


# ---------------------------------------------------------------------------
# Fix 4 — Program Change zone exit & re-entry
# ---------------------------------------------------------------------------

def _pc_config():
    return {
        "mappings": [
            {"input": "bpm", "mode": "program_change", "channel": 1,
             "program": 42, "min": 50, "max": 200, "zone": [150, 200]}
        ]
    }

def test_program_change_fires_on_entry_and_reentry():
    cfg = _pc_config()
    states = {}

    def run_bpm(sink, bpm):
        process_ev = bridge.process_event
        process_ev({"bpm": bpm}, cfg, states, sink)

    def scenario(sink):
        run_bpm(sink, 120)   # outside zone  -> no PC
        run_bpm(sink, 160)   # ENTER zone    -> PC #1
        run_bpm(sink, 170)   # still inside  -> no PC
        run_bpm(sink, 130)   # LEAVE zone    -> no PC
        run_bpm(sink, 165)   # RE-ENTER      -> PC #2

    _, msgs = capture_dry_run(scenario)
    pcs = [m for m in msgs if m["type"] == "program_change"]
    assert len(pcs) == 2                    # fired twice (V3 fired once)
    assert all(m["program"] == 42 for m in pcs)


# ---------------------------------------------------------------------------
# config validation
# ---------------------------------------------------------------------------

def test_valid_mapping_has_no_errors():
    ok = {"input": "beat", "mode": "pulse", "note": 36, "channel": 10}
    assert bridge.validate_mapping(0, ok) == []

def test_invalid_mapping_collects_errors():
    bad = {"input": "bpm", "mode": "cc", "cc": 999, "channel": 42, "curve": "nope"}
    errs = bridge.validate_mapping(0, bad)
    assert any("cc must be 0-127" in e for e in errs)
    assert any("channel must be 1-16" in e for e in errs)
    assert any("unknown curve" in e for e in errs)

def test_bad_zone_shape_rejected():
    errs = bridge.validate_mapping(0, {"input": "bpm", "mode": "cc", "zone": [1, 2, 3]})
    assert any("zone" in e for e in errs)

def test_validate_config_exits_on_error():
    with pytest.raises(SystemExit):
        bridge.validate_config({"mappings": [{"mode": "cc", "channel": 99}]})
