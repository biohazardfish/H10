# H10 → MIDI 映射路由

資料流：`h10_hr_live.py`（BLE，每拍一行 JSONL）→ `monitor.py`（儀表板，透明穿透）→ `bridge.py`（映射引擎）→ 虛擬埠 "H10 Bridge" → REAPER（`h10_heartbeat.RPP`）。

## 事件格式

每次心跳一行：`{"timestamp": "...", "bpm": 110, "rr_ms": 543, "beat": 1}`

- `bpm` — H10 平滑後的心率
- `rr_ms` — 這一跳與上一跳的真實間隔（毫秒），HRV 的原始素材
- `beat` — 恆為 1，作為「一次心跳」的觸發訊號

bridge 另外衍生（`DerivedInputs`，視窗 20 拍）：

- `rr_delta` — |RR_n − RR_(n−1)|，逐拍變異
- `hrv_rmssd` — 相鄰 RR 差的均方根，短期 HRV 標準指標
- `hrv_sdnn` — RR 標準差（目前沒有映射使用）
- `bpm_accel` — |BPM_n − BPM_(n−1)|（目前沒有映射使用）

## 路由表（mapping_config.json v3）

每條路都走同一條加工線：**正規化 [min,max]→0..1 → 響應曲線 → 平滑 → MIDI**。

| # | 輸入 | 範圍 | 曲線 | 平滑 | MIDI 輸出 | 聽感 |
|---|------|------|------|------|-----------|------|
| 1 | `beat` | 0–1 | – | – | pulse note 36 (C1) ch10, vel 100 | 每次心跳一聲 kick |
| 2 | `beat` | 0–1 | – | – | note 48 (C3) ch1 持續按住 | drone 底音（載體） |
| 3 | `bpm` | 50–180 | log | EMA α=0.2 | CC 74 ch1（min_change 2） | 心率快 = 濾波器亮 |
| 4 | `rr_ms` | 400–1200 | s-curve | median w=5 | CC 71 ch1（min_change 2） | 間隔長 = 共鳴強 |
| 5 | `hrv_rmssd` | 0–100 | exp | 移動平均 w=8 | CC 1 ch1（min_change 3） | 越放鬆 = 調變越多 |
| 6 | `rr_delta` | −80–80 | s-curve | rate_limit 0.05 | pitch bend ch1 | drone 音高逐拍微飄 |
| 7 | `bpm` | 140–200 | – | – | pulse note 38 ch10, vel 隨 bpm | ≥140 bpm 觸發 snare |
| 8 | `bpm` | 50–200 | – | – | program change 42 ch1 | 進入 [150,200] 區間切音色 |

路 6 的 min 設 −80 是刻意的：`rr_delta` 恆 ≥0，把 0 對齊到正規化的 0.5，pitch bend 才會以原音高為中心（rr_delta=0 → bend=0）。

## REAPER 端

- **Heartbeat Kick** 軌：輸入 All MIDI ch10，ReaSynth
- **HRV Drone** 軌：輸入 All MIDI ch1，ReaSynth（收 drone 音符 + pitch bend + CC）
- CC74/CC71/CC1 要有聽感需在 REAPER 內做 parameter modulation → MIDI link（GUI 操作，尚未綁定）

## 已知陷阱

- **零長度音符會被合成器吃掉**：pulse 模式若 note_on 後立刻 note_off，兩則訊息落在同一音訊區塊，音符在發聲前就被取消（實測 60 秒 ~100 拍只活了 2 聲）。現已改為「按住到下一拍才放開」；搭配 ReaSynth Sustain=0 才是打擊樂聽感。
- **drone 的 note_on 只在第一拍送一次**：REAPER 若錯過（transport 重置、埠重連），drone 無聲。補救：`RPR.StuffMIDIMessage(0, 0x90, 48, 100)` 塞進虛擬鍵盤佇列。
- **虛擬埠每次 bridge 重啟都是新實例**：REAPER 介面上顯示已啟用，實際訂閱的是死掉的舊埠。重啟管線後要觸發 action 41175（Reset all MIDI devices）。
- **REAPER transport 啟停會重置合成器**（all-notes-off），錄音開始/結束都會切掉按住的音。
