"""Focused tests for the shared H10 BLE parser and live producer."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from h10_common import parse_heart_rate  # noqa: E402
import h10_hr_live  # noqa: E402
import h10_hr_log  # noqa: E402


def packet(flags, bpm_bytes, *rr_raw, energy_bytes=b""):
    payload = bytes([flags]) + bytes(bpm_bytes)
    if flags & 0x08:
        payload += bytes(energy_bytes)
    for value in rr_raw:
        payload += int(value).to_bytes(2, "little")
    return payload


def test_live_and_log_import_the_same_shared_parser():
    assert h10_hr_live.parse_heart_rate is parse_heart_rate
    assert h10_hr_log.parse_heart_rate is parse_heart_rate


def test_parse_8_bit_heart_rate_and_one_rr():
    parsed = parse_heart_rate(packet(0x10, [72], 1024))
    assert parsed == {"bpm": 72, "rr_intervals": [1000]}


def test_parse_16_bit_heart_rate_and_one_rr():
    parsed = parse_heart_rate(packet(0x11, [0x2C, 0x01], 512))
    assert parsed == {"bpm": 300, "rr_intervals": [500]}


def test_parse_multiple_rr_intervals():
    parsed = parse_heart_rate(packet(0x10, [70], 819, 1024, 1280))
    assert parsed["bpm"] == 70
    assert parsed["rr_intervals"] == [800, 1000, 1250]


def test_parse_packet_without_rr():
    parsed = parse_heart_rate(packet(0x00, [65]))
    assert parsed == {"bpm": 65, "rr_intervals": []}


def test_parse_skips_energy_expended_before_rr():
    parsed = parse_heart_rate(packet(0x18, [80], 1024, energy_bytes=b"\x34\x12"))
    assert parsed == {"bpm": 80, "rr_intervals": [1000]}


@pytest.mark.parametrize("data", [b"", b"\x01", b"\x11\x2c"])
def test_truncated_packets_are_safe(data):
    assert parse_heart_rate(data)["rr_intervals"] == []


def test_live_producer_omits_rr_ms_when_packet_has_no_rr(capsys):
    h10_hr_live.handle_hr_notification(0, bytes([0x00, 72]))
    output = capsys.readouterr().out.strip()
    event = json.loads(output)
    assert event["bpm"] == 72
    assert event["beat"] == 1
    assert "rr_ms" not in event


def test_live_producer_emits_one_json_event_per_rr(capsys):
    h10_hr_live.handle_hr_notification(0, packet(0x10, [72], 1024, 1050))
    output = capsys.readouterr().out.splitlines()
    events = [json.loads(line) for line in output]
    assert [event["rr_ms"] for event in events] == [1000, 1025]
