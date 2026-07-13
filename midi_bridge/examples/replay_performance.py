#!/usr/bin/env python3
"""Replay a five-scene H10 V4 performance without wearing the strap."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MOVEMENT_CAPTURE = ROOT / "captures/2026-07-13_20-33-08_h10_120s_motion"

LYING_VECTOR = (-0.42, 0.0, -0.91)
UPRIGHT_VECTOR = (-0.93, 0.0, 0.36)
PHASES = (
    ("lying_open", 12.0),
    ("rising", 8.0),
    ("dance", 30.0),
    ("sitting_return", 10.0),
    ("lying_final", 15.0),
)


def unit(values: tuple[float, float, float]) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(value * value for value in values))
    return tuple(value / magnitude for value in values)  # type: ignore[return-value]


def blend(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
    amount: float,
) -> tuple[float, float, float]:
    return unit(tuple(a + amount * (b - a) for a, b in zip(left, right)))


def load_dance_profile() -> list[dict[str, Any]]:
    path = MOVEMENT_CAPTURE / "h10_acc_samples.jsonl"
    if not path.exists():
        return []
    bins: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        bins[int(float(row["capture_elapsed_s"]))].append(row)

    profile = []
    previous: tuple[float, float, float] | None = None
    for second in sorted(bins):
        rows = bins[second]
        axes = [
            tuple(float(row[key]) for key in ("x_mg", "y_mg", "z_mg"))
            for row in rows
        ]
        mean = tuple(statistics.fmean(axis[index] for axis in axes) for index in range(3))
        gravity = unit(mean)
        dynamic = math.sqrt(
            statistics.fmean(
                sum((axis[index] - mean[index]) ** 2 for index in range(3))
                for axis in axes
            )
        )
        jerk = max(1200.0, dynamic * 10.0)
        rotation = 8.0 if previous is None else min(
            50.0,
            math.degrees(
                math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(previous, gravity)))))
            ),
        )
        profile.append(
            {
                "gravity": gravity,
                "motion": max(180.0, dynamic),
                "jerk": jerk,
                "rotation": max(8.0, rotation),
            }
        )
        previous = gravity
    return profile


def phase_at(t: float) -> tuple[str, float, float]:
    start = 0.0
    for name, duration in PHASES:
        if t < start + duration:
            return name, t - start, duration
        start += duration
    return PHASES[-1][0], PHASES[-1][1], PHASES[-1][1]


def bpm_for(name: str, within: float, duration: float, dance_bpms: list[float]) -> float:
    progress = min(1.0, within / max(0.001, duration))
    if name == "lying_open":
        return 109.0 + math.sin(within * 0.7) * 1.2
    if name == "rising":
        return 109.0 + progress * 15.0
    if name == "dance":
        if dance_bpms:
            index = min(len(dance_bpms) - 1, int(progress * len(dance_bpms)))
            return dance_bpms[index]
        return 128.0 + math.sin(within * 0.25) * 6.0
    if name == "sitting_return":
        return 129.0 - progress * 5.0
    return 124.0 - progress * 11.0


def motion_for(
    name: str,
    within: float,
    duration: float,
    dance_profile: list[dict[str, Any]],
) -> dict[str, Any]:
    progress = min(1.0, within / max(0.001, duration))
    if name == "lying_open":
        return {"gravity": LYING_VECTOR, "motion": 70.0, "jerk": 700.0, "rotation": 1.0}
    if name == "rising":
        return {
            "gravity": blend(LYING_VECTOR, UPRIGHT_VECTOR, progress),
            "motion": 120.0 + 70.0 * math.sin(progress * math.pi),
            "jerk": 1500.0,
            "rotation": 15.0,
        }
    if name == "dance":
        if dance_profile:
            index = min(len(dance_profile) - 1, int(progress * len(dance_profile)))
            return dance_profile[index]
        return {
            "gravity": blend(UPRIGHT_VECTOR, LYING_VECTOR, 0.5 + 0.5 * math.sin(within)),
            "motion": 350.0,
            "jerk": 2800.0,
            "rotation": 24.0,
        }
    if name == "sitting_return":
        return {"gravity": UPRIGHT_VECTOR, "motion": 75.0, "jerk": 750.0, "rotation": 2.0}
    lie_progress = min(1.0, progress * 3.0)
    return {
        "gravity": blend(UPRIGHT_VECTOR, LYING_VECTOR, lie_progress),
        "motion": 75.0 if lie_progress >= 1.0 else 110.0,
        "jerk": 800.0,
        "rotation": 2.0 if lie_progress >= 1.0 else 12.0,
    }


def captured_dance_bpms() -> list[float]:
    path = MOVEMENT_CAPTURE / "h10_hr_events.jsonl"
    if not path.exists():
        return []
    return [float(json.loads(line)["bpm"]) for line in path.read_text().splitlines() if line]


def build_events(base_time: float) -> list[tuple[float, dict[str, Any]]]:
    total_duration = sum(duration for _name, duration in PHASES)
    profile = load_dance_profile()
    dance_bpms = captured_dance_bpms()
    events: list[tuple[float, dict[str, Any]]] = []

    events.append(
        (
            0.0,
            {
                "kind": "status",
                "connected": True,
                "heart_available": True,
                "motion_available": True,
                "available_pmd": ["ECG", "ACC"],
            },
        )
    )

    t = 0.0
    while t <= total_duration:
        name, within, duration = phase_at(t)
        values = motion_for(name, within, duration, profile)
        events.append(
            (
                t,
                {
                    "kind": "motion",
                    "gravity_unit": list(values["gravity"]),
                    "acc_mean_mg": [value * 1000.0 for value in values["gravity"]],
                    "motion_rms_mg": values["motion"],
                    "jerk_rms_mg_s": values["jerk"],
                    "rotation_rms_deg_s": values["rotation"],
                    "demo_scene": name,
                },
            )
        )
        t += 0.1

    beat_time = 0.0
    beat_index = 0
    while beat_time <= total_duration:
        name, within, duration = phase_at(beat_time)
        bpm = bpm_for(name, within, duration, dance_bpms)
        rr_ms = 60000.0 / bpm + math.sin(beat_index * 0.8) * (4.0 if name != "dance" else 2.0)
        events.append(
            (
                beat_time,
                {
                    "kind": "heartbeat",
                    "bpm": round(bpm, 2),
                    "rr_ms": round(rr_ms, 2),
                    "beat": 1,
                    "demo_scene": name,
                },
            )
        )
        beat_time += 60.0 / bpm
        beat_index += 1

    events.append(
        (
            total_duration + 0.2,
            {
                "kind": "status",
                "connected": False,
                "heart_available": False,
                "motion_available": False,
            },
        )
    )
    events.sort(key=lambda item: (item[0], item[1].get("kind") != "motion"))
    for virtual_time, event in events:
        event["t_monotonic_s"] = base_time + virtual_time
        event["timestamp"] = dt.datetime.now().astimezone().isoformat(timespec="milliseconds")
    return events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay the H10 V4 five-scene performance.")
    parser.add_argument("--speed", type=float, default=2.0)
    parser.add_argument("--no-sleep", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    speed = max(0.1, args.speed)
    started = time.monotonic()
    base_time = started
    for virtual_time, event in build_events(base_time):
        if not args.no_sleep:
            due = started + virtual_time / speed
            remaining = due - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
