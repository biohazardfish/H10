import asyncio
import datetime
import json
import sys
from bleak import BleakClient, BleakScanner

# 上次掃描到的 Polar H10 位址（macOS 的 BLE UUID 可能會變，
# 找不到時會自動改用名稱掃描）
H10_ADDRESS = "E4C4B7DF-21E1-D1F5-9332-BC6D394F15C8"

# 標準 Heart Rate Measurement characteristic UUID
HEART_RATE_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_heart_rate(data: bytes) -> dict:
    """依照 Bluetooth Heart Rate Profile 解析 BPM 和 RR intervals。

    回傳 {"bpm": int, "rr_intervals": [int, ...]}
    rr_intervals 以毫秒為單位，每一個值代表兩次心跳之間的間隔。
    """
    result = {"bpm": 0, "rr_intervals": []}
    if not data:
        return result

    flags = data[0]
    hr_16bit = flags & 0x01        # bit 0: HR value format
    rr_present = (flags >> 4) & 0x01  # bit 4: RR-Interval present

    offset = 1
    if hr_16bit == 0 and len(data) >= 2:
        result["bpm"] = data[1]
        offset = 2
    elif hr_16bit == 1 and len(data) >= 3:
        result["bpm"] = int.from_bytes(data[1:3], byteorder="little")
        offset = 3

    # Energy Expended（bit 3）佔 2 bytes，跳過
    if (flags >> 3) & 0x01:
        offset += 2

    # 解析 RR intervals（每個 uint16，單位 1/1024 秒）
    if rr_present:
        while offset + 1 < len(data):
            rr_raw = int.from_bytes(data[offset:offset + 2], byteorder="little")
            rr_ms = int(round(rr_raw * 1000 / 1024))  # 轉毫秒
            result["rr_intervals"].append(rr_ms)
            offset += 2

    return result


def handle_hr_notification(sender: int, data: bytearray):
    """每收到 BLE 通知，為每一次心跳輸出一行 JSONL。"""
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
        event = {"timestamp": ts, "bpm": bpm, "rr_ms": 0, "beat": 1}
        print(json.dumps(event), flush=True)

    # 同時在 stderr 顯示簡要資訊，方便除錯
    rr_str = ",".join(str(r) for r in parsed["rr_intervals"]) if parsed["rr_intervals"] else "N/A"
    print(f"HR: {bpm} bpm  RR: [{rr_str}] ms  (raw: {data.hex()})", file=sys.stderr)


async def resolve_address() -> str:
    """先試既有位址；掃不到就改用裝置名稱搜尋 Polar。"""
    device = await BleakScanner.find_device_by_address(H10_ADDRESS, timeout=5.0)
    if device is not None:
        return H10_ADDRESS

    print("既有位址掃不到，改用名稱搜尋 Polar（約 10 秒）...", file=sys.stderr)
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: bool(d.name and "polar" in d.name.lower()),
        timeout=10.0,
    )
    if device is None:
        print(
            "掃不到 Polar H10。請確認：1) 錶帶電極貼緊皮膚（有接觸才會廣播）"
            " 2) 手機的 Polar Flow / 其他 app 沒有佔住連線",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"找到 {device.name} @ {device.address}"
        f"（可更新 h10_hr_live.py 的 H10_ADDRESS 以加快下次連線）",
        file=sys.stderr,
    )
    return device.address


async def main():
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
    asyncio.run(main())