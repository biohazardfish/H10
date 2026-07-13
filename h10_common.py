"""Shared Polar H10 BLE discovery and Heart Rate Measurement parsing.

The live JSONL producer and the CSV logger intentionally use the same
Bluetooth address preference, characteristic UUID, and packet parser.  The
Bleak import stays inside discovery so the pure parser can be tested without
Bluetooth dependencies installed.
"""

from __future__ import annotations

import sys
from typing import Any


# macOS exposes the H10 address as a CoreBluetooth UUID rather than a classic
# Bluetooth MAC address.  Name-based discovery remains the fallback because
# this identifier can change after pairing/resetting the strap.
H10_ADDRESS = "E4C4B7DF-21E1-D1F5-9332-BC6D394F15C8"
HEART_RATE_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


class H10NotFoundError(RuntimeError):
    """Raised when no Polar H10-like device can be discovered."""


def parse_heart_rate(data: bytes | bytearray) -> dict[str, Any]:
    """Parse a Bluetooth Heart Rate Measurement (0x2A37) notification.

    The returned RR intervals are integer milliseconds.  Heart Rate Profile
    RR values are uint16 counts in 1/1024 second units; a notification may
    contain zero, one, or several RR values.

    Malformed/truncated packets return the fields that can be decoded safely
    and never raise an indexing error in a BLE callback.
    """

    result: dict[str, Any] = {"bpm": 0, "rr_intervals": []}
    if not data:
        return result

    packet = bytes(data)
    flags = packet[0]
    offset = 1

    # Flags bit 0: heart rate value format (uint8 or uint16 little-endian).
    if flags & 0x01:
        if offset + 2 > len(packet):
            return result
        result["bpm"] = int.from_bytes(packet[offset:offset + 2], "little")
        offset += 2
    else:
        if offset + 1 > len(packet):
            return result
        result["bpm"] = packet[offset]
        offset += 1

    # Flags bit 3: Energy Expended Status.  It occupies two bytes before RR.
    if flags & 0x08:
        if offset + 2 > len(packet):
            return result
        offset += 2

    # Flags bit 4: one or more RR-Interval uint16 values, 1/1024 second.
    if flags & 0x10:
        rr_intervals = result["rr_intervals"]
        while offset + 2 <= len(packet):
            rr_raw = int.from_bytes(packet[offset:offset + 2], "little")
            rr_intervals.append(int(round(rr_raw * 1000.0 / 1024.0)))
            offset += 2

    return result


def _is_h10_name(name: str | None) -> bool:
    normalized = (name or "").lower()
    return "polar" in normalized or "h10" in normalized


def _is_h10_device(device: Any, advertisement_data: Any) -> bool:
    return _is_h10_name(getattr(device, "name", None)) or _is_h10_name(
        getattr(advertisement_data, "local_name", None)
    )


async def resolve_h10_address(
    preferred_address: str = H10_ADDRESS,
    address_timeout: float = 5.0,
    scan_timeout: float = 10.0,
) -> str:
    """Resolve a usable H10 address, preferring the known macOS identifier."""

    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise H10NotFoundError(
            "Bleak is not installed; run pip install -r requirements.txt."
        ) from exc

    try:
        device = await BleakScanner.find_device_by_address(
            preferred_address, timeout=address_timeout
        )
    except Exception as exc:
        print(f"Preferred H10 lookup failed ({exc}); falling back to name scan.", file=sys.stderr)
        device = None

    if device is not None:
        return getattr(device, "address", None) or preferred_address

    print("既有位址掃不到，改用名稱搜尋 Polar H10（約 10 秒）...", file=sys.stderr)
    try:
        device = await BleakScanner.find_device_by_filter(
            _is_h10_device,
            timeout=scan_timeout,
        )
    except Exception as exc:
        raise H10NotFoundError(f"Polar H10 name scan failed: {exc}") from exc

    if device is None:
        raise H10NotFoundError(
            "掃不到 Polar H10。請確認：1) 錶帶電極貼緊皮膚（有接觸才會廣播）"
            " 2) 手機的 Polar Flow / 其他 app 沒有佔住連線"
        )

    address = getattr(device, "address", None)
    if not address:
        raise H10NotFoundError("找到 Polar H10，但裝置沒有可用的 BLE address。")

    print(
        f"找到 {getattr(device, 'name', 'Polar H10')} @ {address}"
        "（可在 h10_common.py 更新 H10_ADDRESS 以加快下次連線）",
        file=sys.stderr,
    )
    return address
