import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from h10_performance_live import MotionFeatureExtractor, angle_degrees  # noqa: E402


def test_static_acceleration_produces_low_motion():
    extractor = MotionFeatureExtractor(sample_rate=50)
    for index in range(100):
        extractor.add_sample((-420 + index % 2, 0, -910 - index % 2))
    event = extractor.snapshot(timestamp=10.0)
    assert event["kind"] == "motion"
    assert event["motion_rms_mg"] < 5
    assert event["jerk_rms_mg_s"] < 100


def test_axis_change_produces_rotation_and_dynamic_motion():
    extractor = MotionFeatureExtractor(sample_rate=50)
    for _ in range(60):
        extractor.add_sample((0, 0, -1000))
    for index in range(60):
        angle = (index + 1) / 60 * math.pi / 2
        extractor.add_sample((-1000 * math.sin(angle), 0, -1000 * math.cos(angle)))
    event = extractor.snapshot(timestamp=12.0)
    assert event["rotation_rms_deg_s"] > 10
    assert event["motion_rms_mg"] > 100


def test_accelerometer_angle_is_not_called_gyro():
    assert angle_degrees((0, 0, -1), (-1, 0, 0)) == pytest.approx(90)
