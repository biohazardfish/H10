import asyncio
from bleak import BleakClient

# 把這裡換成你剛剛掃描到的 Polar H10 地址（括號裡那串）
H10_ADDRESS = "BCBA9017-479D-B12A-933D-204CBCA3DF70"

# 標準 Heart Rate Measurement characteristic UUID
HEART_RATE_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_heart_rate(data: bytes) -> int:
    """依照 Bluetooth Heart Rate Profile 解析 BPM"""
    if not data:
        return 0

    flags = data[0]
    hr_16bit = flags & 0x01  # 第 0 bit：0 = uint8, 1 = uint16

    if hr_16bit == 0 and len(data) >= 2:
        # uint8 心率
        return data[1]
    elif hr_16bit == 1 and len(data) >= 3:
        # uint16 心率（小端）
        return int.from_bytes(data[1:3], byteorder="little")
    else:
        return 0


def handle_hr_notification(sender: int, data: bytearray):
    bpm = parse_heart_rate(data)
    print(f"HR: {bpm} bpm   (raw: {data.hex()})")


async def main():
    print(f"Connecting to Polar H10 at {H10_ADDRESS} ...")
    async with BleakClient(H10_ADDRESS) as client:
        if not client.is_connected:
            print("連線失敗")
            return

        print("Connected! 開始訂閱心率資料（按 Ctrl+C 停止）")

        # 開始訂閱 Heart Rate Measurement 通知
        await client.start_notify(HEART_RATE_CHAR_UUID, handle_hr_notification)

        try:
            # 一直等，讓通知持續跑；每秒睡一下
            while True:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print("\n停止訂閱，斷線中...")
        finally:
            await client.stop_notify(HEART_RATE_CHAR_UUID)

if __name__ == "__main__":
    asyncio.run(main())