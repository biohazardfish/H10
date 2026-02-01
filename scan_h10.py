import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning for BLE devices for 10 seconds...")
    devices = await BleakScanner.discover(timeout=10.0)

    if not devices:
        print("沒有找到任何 BLE 裝置")
        return

    print("\n找到的 BLE 裝置：")
    for d in devices:
        print(f"- {d.name}  ({d.address})")

    print("\n請在上面列表裡找有沒有類似 'Polar H10' 的名稱，或 Polar 開頭的裝置。")

if __name__ == "__main__":
    asyncio.run(main())