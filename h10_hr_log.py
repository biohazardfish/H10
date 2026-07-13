import asyncio
import datetime
import sys

from h10_common import (
    HEART_RATE_CHAR_UUID,
    H10NotFoundError,
    parse_heart_rate,
    resolve_h10_address,
)

log_file = None  # 之後會在 main 裡打開


async def main():
    global log_file
    from bleak import BleakClient

    address = await resolve_h10_address()
    print(f"Connecting to Polar H10 at {address} ...")

    # 打開 / 建立 CSV 檔案（跟這個 .py 同一個資料夾）
    log_file = open("h10_hr_log.csv", "a", buffering=1, encoding="utf-8")

    # 如果是新檔（檔案位置在開頭），寫入表頭
    if log_file.tell() == 0:
        log_file.write("timestamp,bpm\n")

    async with BleakClient(address) as client:
        if not client.is_connected:
            print("連線失敗")
            log_file.close()
            return

        print("Connected! 開始訂閱心率資料並寫入 h10_hr_log.csv（按 Ctrl+C 停止）")

        # 定義通知 callback，放在 main 裡，這樣拿得到 log_file
        def handle_hr_notification(sender: int, data: bytearray):
            parsed = parse_heart_rate(data)
            bpm = parsed["bpm"]
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
    except H10NotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        # 再保險一次，確保 Ctrl+C 不會丟一堆 traceback 嚇你
        print("\n手動停止程式。")
