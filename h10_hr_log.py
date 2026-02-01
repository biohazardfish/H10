import asyncio
import datetime
from bleak import BleakClient

# 用你剛剛掃描到的 Polar H10 地址
H10_ADDRESS = "BCBA9017-479D-B12A-933D-204CBCA3DF70"

# 標準 Heart Rate Measurement characteristic UUID
HEART_RATE_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

log_file = None  # 之後會在 main 裡打開


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


async def main():
    global log_file

    # 打開 / 建立 CSV 檔案（跟這個 .py 同一個資料夾）
    log_file = open("h10_hr_log.csv", "a", buffering=1, encoding="utf-8")

    # 如果是新檔（檔案位置在開頭），寫入表頭
    if log_file.tell() == 0:
        log_file.write("timestamp,bpm\n")

    print(f"Connecting to Polar H10 at {H10_ADDRESS} ...")
    async with BleakClient(H10_ADDRESS) as client:
        if not client.is_connected:
            print("連線失敗")
            log_file.close()
            return

        print("Connected! 開始訂閱心率資料並寫入 h10_hr_log.csv（按 Ctrl+C 停止）")

        # 定義通知 callback，放在 main 裡，這樣拿得到 log_file
        def handle_hr_notification(sender: int, data: bytearray):
            bpm = parse_heart_rate(data)
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            # 終端顯示
            print(f"{ts}  HR: {bpm} bpm")
            # 寫入 CSV
            log_file.write(f"{ts},{bpm}\n")

        # 開始訂閱 Heart Rate Measurement 通知
        await client.start_notify(HEART_RATE_CHAR_UUID, handle_hr_notification)

        try:
            while True:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print("\n停止訂閱，準備關閉檔案與連線...")
        finally:
            try:
                await client.stop_notify(HEART_RATE_CHAR_UUID)
            except Exception:
                pass
            if log_file and not log_file.closed:
                log_file.close()
            print("已關閉 h10_hr_log.csv，程式結束。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 再保險一次，確保 Ctrl+C 不會丟一堆 traceback 嚇你
        print("\n手動停止程式。")