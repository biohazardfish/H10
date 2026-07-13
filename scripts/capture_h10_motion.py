#!/usr/bin/env python3
"""Capture Polar H10 HR/RR plus PMD motion data into a timestamped folder."""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from bleak import BleakClient
from bleakheart import HeartRate, PolarMeasurementData

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from h10_common import H10NotFoundError, resolve_h10_address  # noqa: E402


def finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) >= 2 else 0.0,
    }


def rmssd(rrs: list[float]) -> float | None:
    if len(rrs) < 2:
        return None
    diffs_sq = [(rrs[i] - rrs[i - 1]) ** 2 for i in range(1, len(rrs))]
    return math.sqrt(sum(diffs_sq) / len(diffs_sq))


def iso_from_ns(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1_000_000_000, tz=dt.timezone.utc).astimezone().isoformat(timespec="milliseconds")


def magnitude(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z)


async def drain_hr(queue: asyncio.Queue, raw_f, csv_writer, events: list[dict[str, Any]], start_mono: float) -> None:
    while True:
        dtype, t_ns, payload, energy = await queue.get()
        hr, rr = payload
        elapsed = time.monotonic() - start_mono
        event = {
            "capture_elapsed_s": round(elapsed, 6),
            "sensor_timestamp_ns": t_ns,
            "timestamp": iso_from_ns(t_ns),
            "bpm": hr,
            "rr_ms": rr,
            "beat": 1,
            "energy": energy,
        }
        raw_f.write(json.dumps(event, ensure_ascii=False) + "\n")
        csv_writer.writerow(event)
        events.append(event)


async def drain_acc(queue: asyncio.Queue, raw_f, csv_writer, samples: list[dict[str, Any]], start_mono: float) -> None:
    while True:
        dtype, t_ns, payload = await queue.get()
        if not payload:
            continue
        # BleakHeart timestamp is for the last sample in the frame.
        frame_elapsed = time.monotonic() - start_mono
        frame_dt_ns = int(1_000_000_000 / max(1, len(payload)))
        first_ns = t_ns - frame_dt_ns * (len(payload) - 1)
        for i, (x, y, z) in enumerate(payload):
            sample_ns = first_ns + i * frame_dt_ns
            mag = magnitude(x, y, z)
            sample = {
                "capture_elapsed_s": round(frame_elapsed, 6),
                "sensor_timestamp_ns": sample_ns,
                "timestamp": iso_from_ns(sample_ns),
                "x_mg": x,
                "y_mg": y,
                "z_mg": z,
                "magnitude_mg": round(mag, 3),
            }
            raw_f.write(json.dumps(sample, ensure_ascii=False) + "\n")
            csv_writer.writerow(sample)
            samples.append(sample)


async def drain_raw(queue: asyncio.Queue, raw_f, rows: list[dict[str, Any]], start_mono: float) -> None:
    while True:
        dtype, t_ns, payload = await queue.get()
        row = {
            "capture_elapsed_s": round(time.monotonic() - start_mono, 6),
            "sensor_timestamp_ns": t_ns,
            "timestamp": iso_from_ns(t_ns),
            "type": dtype,
            "payload_hex": bytes(payload).hex(),
        }
        raw_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)


async def capture(args: argparse.Namespace) -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = ROOT / "captures" / f"{stamp}_h10_{args.duration}s_motion"
    out_dir.mkdir(parents=True, exist_ok=True)

    hr_jsonl = (out_dir / "h10_hr_events.jsonl").open("w", encoding="utf-8")
    acc_jsonl = (out_dir / "h10_acc_samples.jsonl").open("w", encoding="utf-8")
    raw_jsonl = (out_dir / "h10_raw_motion_frames.jsonl").open("w", encoding="utf-8")
    hr_csv_f = (out_dir / "h10_hr_events.csv").open("w", encoding="utf-8", newline="")
    acc_csv_f = (out_dir / "h10_acc_samples.csv").open("w", encoding="utf-8", newline="")
    log_f = (out_dir / "capture.log").open("w", encoding="utf-8")

    hr_writer = csv.DictWriter(hr_csv_f, fieldnames=["capture_elapsed_s", "sensor_timestamp_ns", "timestamp", "bpm", "rr_ms", "beat", "energy"])
    hr_writer.writeheader()
    acc_writer = csv.DictWriter(acc_csv_f, fieldnames=["capture_elapsed_s", "sensor_timestamp_ns", "timestamp", "x_mg", "y_mg", "z_mg", "magnitude_mg"])
    acc_writer.writeheader()

    hr_queue: asyncio.Queue = asyncio.Queue()
    acc_queue: asyncio.Queue = asyncio.Queue()
    raw_queue: asyncio.Queue = asyncio.Queue()
    hr_events: list[dict[str, Any]] = []
    acc_samples: list[dict[str, Any]] = []
    raw_frames: list[dict[str, Any]] = []
    available_pmd: list[str] = []
    acc_started = False
    gyro_started = False
    acc_start_response: Any = None
    gyro_start_response: Any = None

    def log(message: str) -> None:
        print(message, flush=True)
        log_f.write(message + "\n")
        log_f.flush()

    address = await resolve_h10_address()
    log(f"CAPTURE_DIR={out_dir}")
    log(f"Connecting to Polar H10 at {address}")

    async with BleakClient(address) as client:
        if not client.is_connected:
            raise RuntimeError("BLE connection failed")

        start_wall = dt.datetime.now().astimezone()
        start_mono = time.monotonic()
        hr = HeartRate(client, queue=hr_queue, instant_rate=False, unpack=True)
        pmd = PolarMeasurementData(client, acc_queue=acc_queue, raw_queue=raw_queue)
        await hr.start_notify()
        try:
            available_pmd = await pmd.available_measurements()
            log(f"Available PMD measurements: {available_pmd}")
        except Exception as exc:
            log(f"PMD availability check failed: {exc!r}")

        if "ACC" in available_pmd:
            acc_start_response = await pmd.start_streaming("ACC", sample_rate=args.acc_rate, range=args.acc_range)
            acc_started = acc_start_response[0] == 0
            log(f"ACC start response: {acc_start_response}")
        else:
            log("ACC not reported as available by this H10 connection.")

        if "GYRO" in available_pmd:
            gyro_start_response = await pmd.start_streaming("GYRO")
            gyro_started = gyro_start_response[0] == 0
            log(f"GYRO start response: {gyro_start_response}")
        else:
            log("GYRO not available; Polar H10 normally exposes accelerometer, not gyroscope.")

        tasks = [
            asyncio.create_task(drain_hr(hr_queue, hr_jsonl, hr_writer, hr_events, start_mono)),
            asyncio.create_task(drain_acc(acc_queue, acc_jsonl, acc_writer, acc_samples, start_mono)),
            asyncio.create_task(drain_raw(raw_queue, raw_jsonl, raw_frames, start_mono)),
        ]

        log(f"Recording {args.duration}s. Move slowly now.")
        deadline = start_mono + args.duration
        next_notice = start_mono
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            now = time.monotonic()
            if now >= next_notice:
                next_notice = now + 10
                log(f"elapsed={now - start_mono:.1f}s hr_events={len(hr_events)} acc_samples={len(acc_samples)} raw_motion_frames={len(raw_frames)}")

        await hr.stop_notify()
        if acc_started:
            await pmd.stop_streaming("ACC")
        if gyro_started:
            await pmd.stop_streaming("GYRO")
        end_wall = dt.datetime.now().astimezone()

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    hr_jsonl.close()
    acc_jsonl.close()
    raw_jsonl.close()
    hr_csv_f.close()
    acc_csv_f.close()
    log_f.close()

    bpms = [v for v in (finite(e.get("bpm")) for e in hr_events) if v is not None]
    rrs = [v for v in (finite(e.get("rr_ms")) for e in hr_events) if v is not None and 270 <= v <= 2000]
    acc_mags = [v for v in (finite(s.get("magnitude_mg")) for s in acc_samples) if v is not None]
    acc_dynamic = [abs(v - 1000.0) for v in acc_mags]

    summary = {
        "capture_folder": str(out_dir),
        "started_at": start_wall.isoformat(timespec="seconds"),
        "ended_at": end_wall.isoformat(timespec="seconds"),
        "duration_s": args.duration,
        "available_pmd_measurements": available_pmd,
        "acc_started": acc_started,
        "gyro_started": gyro_started,
        "acc_start_response": repr(acc_start_response),
        "gyro_start_response": repr(gyro_start_response),
        "hr_event_count": len(hr_events),
        "acc_sample_count": len(acc_samples),
        "raw_motion_frame_count": len(raw_frames),
        "bpm": stats(bpms),
        "rr_ms": stats(rrs),
        "rmssd_ms": rmssd(rrs),
        "sdnn_ms": statistics.stdev(rrs) if len(rrs) >= 2 else None,
        "acc_magnitude_mg": stats(acc_mags),
        "acc_dynamic_abs_mg_from_1g": stats(acc_dynamic),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = f"""# Polar H10 120-second movement capture

This folder contains a two-minute capture of Polar H10 heart data plus motion data.

## Important Hardware Note

Polar's public H10 SDK documentation lists heart rate/RR, ECG, and accelerometer data for H10. It does not list gyroscope data for H10. This capture therefore records `ACC` accelerometer data when available. If a future/other device reports `GYRO`, raw gyro frames are saved in `h10_raw_motion_frames.jsonl`.

## Files

- `h10_hr_events.jsonl` / `h10_hr_events.csv`: one heartbeat event per RR interval.
- `h10_acc_samples.jsonl` / `h10_acc_samples.csv`: accelerometer samples in milli-g (`x_mg`, `y_mg`, `z_mg`) plus vector magnitude.
- `h10_raw_motion_frames.jsonl`: raw non-ACC PMD motion frames, e.g. gyro if the device exposes it.
- `summary.json`: computed statistics.
- `capture.log`: connection, PMD availability, and progress log.

## Parameter Meaning

- `bpm`: heart rate reported by the H10.
- `rr_ms`: beat-to-beat interval in milliseconds.
- `beat`: heartbeat trigger, always `1` per event.
- `x_mg`, `y_mg`, `z_mg`: chest-strap acceleration by axis in milli-g. Around 1000 mg magnitude means static gravity; deviations and axis changes show body movement.
- `magnitude_mg`: sqrt(x^2 + y^2 + z^2), useful as a simple movement-intensity proxy.
- `RMSSD`: short-term HRV from successive valid RR intervals.
- `SDNN`: standard deviation of valid RR intervals.

## Summary At Capture End

See `summary.json`; key counts are:

- HR events: `{len(hr_events)}`
- ACC samples: `{len(acc_samples)}`
- Raw motion frames: `{len(raw_frames)}`
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    return out_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Polar H10 HR/RR and ACC motion data.")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--acc-rate", type=int, default=50)
    parser.add_argument("--acc-range", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        out_dir = asyncio.run(capture(args))
    except H10NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"OUTPUT_DIR={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
