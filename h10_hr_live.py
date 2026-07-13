import asyncio
import argparse
import datetime
import json
import sys
import time
from h10_common import (
    HEART_RATE_CHAR_UUID,
    H10NotFoundError,
    parse_heart_rate,
    resolve_h10_address,
)


DEBUG_BLE = False
LOG_INTERVAL_SEC = 1.0
_last_log_at = 0.0


def handle_hr_notification(sender: int, data: bytearray):
    """每收到 BLE 通知，為每一次心跳輸出一行 JSONL。"""
    global _last_log_at
    parsed = parse_heart_rate(data)
    bpm = parsed["bpm"]
    ts = datetime.datetime.now().isoformat(timespec="milliseconds")

    if parsed["rr_intervals"]:
        # 每一個 RR interval = 一次心跳 → 輸出一行
        for rr_ms in parsed["rr_intervals"]:
            event = {"timestamp": ts, "bpm": bpm, "rr_ms": rr_ms, "beat": 1}
            print(json.dumps(event), flush=True)
    else:
        # H10 沒回傳 RR（少見），仍輸出 BPM
        # Omit rr_ms rather than emitting 0: zero is not a physiological RR
        # interval and would otherwise be consumed by downstream mappings.
        event = {"timestamp": ts, "bpm": bpm, "beat": 1}
        print(json.dumps(event), flush=True)

    # stderr diagnostics are rate-limited so stdout stays the clean JSONL stream.
    now = time.monotonic()
    if DEBUG_BLE or now - _last_log_at >= LOG_INTERVAL_SEC:
        _last_log_at = now
        rr_str = ",".join(str(r) for r in parsed["rr_intervals"]) if parsed["rr_intervals"] else "N/A"
        raw = f"  raw: {data.hex()}" if DEBUG_BLE else ""
        print(f"HR: {bpm} bpm  RR: [{rr_str}] ms{raw}", file=sys.stderr)


async def resolve_address() -> str:
    """Compatibility wrapper around the shared H10 discovery function."""
    return await resolve_h10_address()


async def main():
    from bleak import BleakClient

    parser = argparse.ArgumentParser(description="Stream Polar H10 heartbeats as JSONL")
    parser.add_argument("--debug-raw", action="store_true", help="log every BLE packet with raw hex")
    args = parser.parse_args()
    global DEBUG_BLE
    DEBUG_BLE = args.debug_raw

    address = await resolve_address()
    print(f"Connecting to Polar H10 at {address} ...", file=sys.stderr)
    async with BleakClient(address) as client:
        if not client.is_connected:
            print("連線失敗", file=sys.stderr)
            return

        print("Connected! 每一次心跳輸出一行 JSONL（按 Ctrl+C 停止）", file=sys.stderr)

        await client.start_notify(HEART_RATE_CHAR_UUID, handle_hr_notification)

        try:
            while True:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print("\n停止訂閱，斷線中...", file=sys.stderr)
        finally:
            await client.stop_notify(HEART_RATE_CHAR_UUID)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except H10NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
