#!/usr/bin/env python3
"""Stream Polar H10 heartbeat and accelerometer features as JSONL.

This is the V4 live-performance producer.  It deliberately lives beside the
validated HR-only producer instead of replacing it.  The Polar H10 exposes an
accelerometer, not a gyroscope; ``rotation_rms_deg_s`` is derived from changes
in the low-pass gravity vector.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import datetime as dt
import json
import math
import sys
import time
from typing import Any, Deque, Iterable

from h10_common import H10NotFoundError, resolve_h10_address


def finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def vector_magnitude(values: Iterable[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def normalize_vector(values: Iterable[float]) -> tuple[float, float, float]:
    vector = tuple(float(value) for value in values)
    magnitude = vector_magnitude(vector)
    if magnitude <= 1e-9:
        return (0.0, 0.0, 1.0)
    return tuple(value / magnitude for value in vector)  # type: ignore[return-value]


def angle_degrees(a: Iterable[float], b: Iterable[float]) -> float:
    left = normalize_vector(a)
    right = normalize_vector(b)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(left, right))))
    return math.degrees(math.acos(dot))


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


class MotionFeatureExtractor:
    """Turn sequential ACC samples into stable one-second motion features."""

    def __init__(
        self,
        sample_rate: float = 50.0,
        window_seconds: float = 1.0,
        gravity_tau_seconds: float = 1.0,
    ) -> None:
        self.sample_rate = float(sample_rate)
        self.window_size = max(2, int(round(self.sample_rate * window_seconds)))
        self.gravity_alpha = 1.0 - math.exp(
            -1.0 / max(1.0, self.sample_rate * gravity_tau_seconds)
        )
        self.gravity: list[float] | None = None
        self.previous_sample: list[float] | None = None
        self.previous_gravity_unit: tuple[float, float, float] | None = None
        self.dynamic_history: Deque[float] = collections.deque(maxlen=self.window_size)
        self.jerk_history: Deque[float] = collections.deque(maxlen=self.window_size)
        self.rotation_history: Deque[float] = collections.deque(maxlen=self.window_size)
        self.axis_history: Deque[tuple[float, float, float]] = collections.deque(
            maxlen=self.window_size
        )
        self.sample_count = 0

    def add_sample(self, sample: Iterable[Any]) -> None:
        values = [finite(value) for value in sample]
        if any(value is None for value in values):
            return
        current = [float(value) for value in values if value is not None]
        if len(current) != 3:
            return

        if self.gravity is None:
            self.gravity = list(current)
        else:
            self.gravity = [
                self.gravity[index]
                + self.gravity_alpha * (current[index] - self.gravity[index])
                for index in range(3)
            ]

        gravity_unit = normalize_vector(self.gravity)
        dynamic = vector_magnitude(
            current[index] - self.gravity[index] for index in range(3)
        )
        if self.previous_sample is None:
            jerk = 0.0
        else:
            jerk = vector_magnitude(
                current[index] - self.previous_sample[index] for index in range(3)
            ) * self.sample_rate
        if self.previous_gravity_unit is None:
            rotation = 0.0
        else:
            rotation = angle_degrees(gravity_unit, self.previous_gravity_unit) * self.sample_rate

        self.dynamic_history.append(dynamic)
        self.jerk_history.append(jerk)
        self.rotation_history.append(rotation)
        self.axis_history.append(tuple(current))
        self.previous_sample = current
        self.previous_gravity_unit = gravity_unit
        self.sample_count += 1

    @staticmethod
    def _rms(values: Iterable[float]) -> float:
        values = tuple(values)
        if not values:
            return 0.0
        return math.sqrt(sum(value * value for value in values) / len(values))

    def ready(self) -> bool:
        return len(self.dynamic_history) >= max(5, self.window_size // 4)

    def snapshot(self, timestamp: float | None = None) -> dict[str, Any]:
        if self.gravity is None:
            raise RuntimeError("no accelerometer samples have been added")
        axes = tuple(self.axis_history)
        axis_mean = [
            sum(sample[index] for sample in axes) / len(axes)
            for index in range(3)
        ]
        return {
            "kind": "motion",
            "timestamp": now_iso(),
            "t_monotonic_s": time.monotonic() if timestamp is None else float(timestamp),
            "sample_count": self.sample_count,
            "acc_mean_mg": [round(value, 3) for value in axis_mean],
            "gravity_unit": [round(value, 8) for value in normalize_vector(self.gravity)],
            "motion_rms_mg": round(self._rms(self.dynamic_history), 3),
            "jerk_rms_mg_s": round(self._rms(self.jerk_history), 3),
            "rotation_rms_deg_s": round(self._rms(self.rotation_history), 4),
        }


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)


async def drain_heart_rate(queue: asyncio.Queue) -> None:
    while True:
        _dtype, sensor_timestamp_ns, payload, energy = await queue.get()
        bpm, rr_ms = payload
        event: dict[str, Any] = {
            "kind": "heartbeat",
            "timestamp": now_iso(),
            "t_monotonic_s": time.monotonic(),
            "sensor_timestamp_ns": sensor_timestamp_ns,
            "bpm": bpm,
            "beat": 1,
        }
        if finite(rr_ms) is not None:
            event["rr_ms"] = rr_ms
        if energy is not None:
            event["energy"] = energy
        emit(event)


async def drain_accelerometer(
    queue: asyncio.Queue,
    extractor: MotionFeatureExtractor,
    output_hz: float,
) -> None:
    minimum_interval = 1.0 / max(1.0, output_hz)
    last_output_at = 0.0
    while True:
        _dtype, _sensor_timestamp_ns, payload = await queue.get()
        for sample in payload or ():
            extractor.add_sample(sample)
        now = time.monotonic()
        if extractor.ready() and now - last_output_at >= minimum_interval:
            last_output_at = now
            emit(extractor.snapshot(timestamp=now))


async def run_live(args: argparse.Namespace) -> int:
    # Keep BLE dependencies out of module import so feature math and tests can
    # run on machines without Bluetooth packages installed.
    from bleak import BleakClient
    from bleakheart import HeartRate, PolarMeasurementData

    address = await resolve_h10_address()
    print(f"Connecting to Polar H10 at {address} ...", file=sys.stderr)

    heart_queue: asyncio.Queue = asyncio.Queue()
    acc_queue: asyncio.Queue = asyncio.Queue()
    raw_queue: asyncio.Queue = asyncio.Queue()
    extractor = MotionFeatureExtractor(sample_rate=args.acc_rate)

    async with BleakClient(address) as client:
        if not client.is_connected:
            raise RuntimeError("Polar H10 BLE connection failed")

        heart = HeartRate(client, queue=heart_queue, instant_rate=False, unpack=True)
        motion = PolarMeasurementData(client, acc_queue=acc_queue, raw_queue=raw_queue)
        await heart.start_notify()

        available: list[str] = []
        acc_started = False
        try:
            available = await motion.available_measurements()
            if "ACC" in available:
                response = await motion.start_streaming(
                    "ACC", sample_rate=args.acc_rate, range=args.acc_range
                )
                acc_started = response[0] == 0
                print(f"ACC start response: {response}", file=sys.stderr)
            else:
                print("Polar H10 did not report ACC as available.", file=sys.stderr)

            emit(
                {
                    "kind": "status",
                    "timestamp": now_iso(),
                    "t_monotonic_s": time.monotonic(),
                    "connected": True,
                    "heart_available": True,
                    "motion_available": acc_started,
                    "available_pmd": available,
                    "note": "rotation is accelerometer-derived; Polar H10 has no gyroscope stream",
                }
            )

            tasks = [asyncio.create_task(drain_heart_rate(heart_queue))]
            if acc_started:
                tasks.append(
                    asyncio.create_task(
                        drain_accelerometer(acc_queue, extractor, args.motion_hz)
                    )
                )

            print(
                "V4 stream active: heartbeat + accelerometer features (Ctrl+C to stop)",
                file=sys.stderr,
            )
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            emit(
                {
                    "kind": "status",
                    "timestamp": now_iso(),
                    "t_monotonic_s": time.monotonic(),
                    "connected": False,
                    "heart_available": False,
                    "motion_available": False,
                }
            )
            await heart.stop_notify()
            if acc_started:
                await motion.stop_streaming("ACC")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream Polar H10 heartbeat and ACC performance features as JSONL."
    )
    parser.add_argument("--acc-rate", type=int, default=50)
    parser.add_argument("--acc-range", type=int, default=2)
    parser.add_argument("--motion-hz", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run_live(args))
    except KeyboardInterrupt:
        print("Stopped by user.", file=sys.stderr)
        return 0
    except H10NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
