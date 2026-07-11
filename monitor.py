#!/usr/bin/env python3
"""H10 管線即時監控：stdin 的 JSONL 原樣轉發到 stdout，
同時在本機開一個儀表板網頁（SSE 推送，純標準庫）。

用法（插在 h10_hr_live 和 bridge 中間）：
  h10_hr_live.py | monitor.py --port 8931 | bridge.py --virtual ...
"""
import argparse
import collections
import json
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HISTORY = collections.deque(maxlen=300)
CLIENTS = []          # 每個瀏覽器連線一個 queue
CLIENTS_LOCK = threading.Lock()
STREAM_ENDED = threading.Event()


def broadcast(payload: str) -> None:
    with CLIENTS_LOCK:
        for q in CLIENTS:
            q.put(payload)


def reader(server) -> None:
    """讀 stdin、轉發 stdout、廣播給所有瀏覽器。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            print(line, flush=True)
        except BrokenPipeError:
            break  # 下游 bridge 已結束
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event["_recv"] = time.time()
        HISTORY.append(event)
        broadcast(json.dumps(event))
    STREAM_ENDED.set()
    broadcast(json.dumps({"_status": "ended"}))
    try:
        sys.stdout.close()
    except Exception:
        pass
    # 串流結束後保留頁面 30 秒讓人看到最終狀態，然後釋放埠退出，
    # 避免上游掛掉時殘留程序一直佔著埠
    print("上游串流結束，30 秒後關閉監控頁面", file=sys.stderr)
    time.sleep(30)
    server.shutdown()


PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>H10 心跳監控</title>
<style>
:root {
  --surface: #1a1a19; --card: #232322; --grid: #333331;
  --ink: #ececea; --ink-2: #9a9a97; --heart: #e8654f; --calm: #3987e5;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--surface); color: var(--ink); min-height: 100vh;
  font-family: -apple-system, "PingFang TC", sans-serif; padding: 24px;
  display: flex; flex-direction: column; gap: 16px; max-width: 900px; margin: 0 auto;
}
header { display: flex; align-items: center; gap: 12px; }
h1 { font-size: 18px; font-weight: 600; }
#status {
  font-size: 13px; padding: 3px 10px; border-radius: 99px;
  background: var(--card); color: var(--ink-2); border: 1px solid var(--grid);
}
#status.live { color: #7ec98f; border-color: #2e5238; }
#status.dead { color: var(--heart); border-color: #5a2d25; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.tile { background: var(--card); border: 1px solid var(--grid); border-radius: 10px; padding: 16px; }
.tile .label { font-size: 12px; color: var(--ink-2); margin-bottom: 6px; }
.tile .value { font-size: 40px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
.tile .unit { font-size: 13px; color: var(--ink-2); margin-left: 4px; }
#heart {
  display: inline-block; color: var(--heart); transform-origin: center;
  transition: transform 80ms ease-out; margin-left: 8px; font-size: 28px;
}
#heart.pump { transform: scale(1.35); }
.chart { background: var(--card); border: 1px solid var(--grid); border-radius: 10px; padding: 16px; }
.chart .label { font-size: 12px; color: var(--ink-2); margin-bottom: 10px; }
canvas { width: 100%; height: 160px; display: block; }
#tip {
  position: fixed; pointer-events: none; display: none; background: #2c2c2a;
  border: 1px solid var(--grid); border-radius: 6px; padding: 6px 9px;
  font-size: 12px; color: var(--ink); z-index: 9;
}
footer { font-size: 12px; color: var(--ink-2); }
</style>
</head>
<body>
<header>
  <h1>H10 心跳監控</h1>
  <span id="status">連線中…</span>
</header>
<div class="tiles">
  <div class="tile"><div class="label">心率</div>
    <div><span class="value" id="bpm">--</span><span class="unit">BPM</span><span id="heart">&#10084;</span></div></div>
  <div class="tile"><div class="label">最新 RR 間隔</div>
    <div><span class="value" id="rr">--</span><span class="unit">ms</span></div></div>
  <div class="tile"><div class="label">HRV RMSSD（近 20 拍）</div>
    <div><span class="value" id="rmssd" style="color: var(--calm)">--</span><span class="unit">ms</span></div></div>
  <div class="tile"><div class="label">累計心跳</div>
    <div><span class="value" id="beats">0</span><span class="unit">拍</span></div></div>
</div>
<div class="chart">
  <div class="label">RR 間隔（近 120 拍）—— 線越波動 = 心率變異越大</div>
  <canvas id="spark" width="1720" height="320"></canvas>
</div>
<div id="tip"></div>
<footer>資料流：h10_hr_live → <b>monitor（本頁）</b> → bridge → REAPER。這頁只旁聽，不影響 MIDI。</footer>
<script>
const rrs = [];            // {rr, bpm, t}
let beats = 0, lastEvent = 0, ended = false;
const $ = id => document.getElementById(id);
const canvas = $('spark'), ctx = canvas.getContext('2d');

function setStatus(text, cls) { const s = $('status'); s.textContent = text; s.className = cls || ''; }

function rmssd() {
  const w = rrs.slice(-20).map(o => o.rr);
  if (w.length < 2) return null;
  let s = 0;
  for (let i = 1; i < w.length; i++) s += (w[i] - w[i-1]) ** 2;
  return Math.sqrt(s / (w.length - 1));
}

function draw(hover) {
  const W = canvas.width, H = canvas.height, pad = 30;
  ctx.clearRect(0, 0, W, H);
  const data = rrs.slice(-120);
  if (data.length < 2) return;
  const vals = data.map(o => o.rr);
  const lo = Math.min(...vals) - 15, hi = Math.max(...vals) + 15;
  const x = i => pad + i * (W - 2*pad) / (data.length - 1);
  const y = v => H - pad - (v - lo) * (H - 2*pad) / (hi - lo);
  ctx.strokeStyle = '#333331'; ctx.lineWidth = 1; ctx.beginPath();
  [lo + (hi-lo)*0.25, lo + (hi-lo)*0.75].forEach(v => { ctx.moveTo(pad, y(v)); ctx.lineTo(W-pad, y(v)); });
  ctx.stroke();
  ctx.fillStyle = '#9a9a97'; ctx.font = '20px sans-serif';
  ctx.fillText(Math.round(hi) + ' ms', 4, y(hi) + 18);
  ctx.fillText(Math.round(lo) + ' ms', 4, y(lo));
  ctx.strokeStyle = '#e8654f'; ctx.lineWidth = 4; ctx.beginPath();
  data.forEach((o, i) => i ? ctx.lineTo(x(i), y(o.rr)) : ctx.moveTo(x(i), y(o.rr)));
  ctx.stroke();
  if (hover != null && data[hover]) {
    ctx.fillStyle = '#ececea'; ctx.beginPath();
    ctx.arc(x(hover), y(data[hover].rr), 8, 0, 7); ctx.fill();
  }
  canvas._map = { data, x, y };
}

canvas.addEventListener('mousemove', e => {
  const m = canvas._map; if (!m) return;
  const r = canvas.getBoundingClientRect();
  const px = (e.clientX - r.left) * canvas.width / r.width;
  let best = 0, bd = 1e9;
  m.data.forEach((o, i) => { const d = Math.abs(m.x(i) - px); if (d < bd) { bd = d; best = i; } });
  draw(best);
  const tip = $('tip'), o = m.data[best];
  tip.style.display = 'block';
  tip.style.left = (e.clientX + 12) + 'px'; tip.style.top = (e.clientY - 10) + 'px';
  tip.textContent = `RR ${o.rr} ms · ${o.bpm} BPM`;
});
canvas.addEventListener('mouseleave', () => { $('tip').style.display = 'none'; draw(); });

function onEvent(ev) {
  if (ev._status === 'ended') { ended = true; setStatus('串流已結束', 'dead'); return; }
  lastEvent = Date.now(); beats++;
  $('bpm').textContent = ev.bpm ?? '--';
  if (ev.rr_ms) { $('rr').textContent = ev.rr_ms; rrs.push({ rr: ev.rr_ms, bpm: ev.bpm }); if (rrs.length > 600) rrs.shift(); }
  const v = rmssd(); $('rmssd').textContent = v == null ? '--' : v.toFixed(0);
  $('beats').textContent = beats;
  const h = $('heart'); h.classList.add('pump'); setTimeout(() => h.classList.remove('pump'), 120);
  setStatus('接收中', 'live');
  draw();
}

new EventSource('/events').onmessage = e => onEvent(JSON.parse(e.data));
setInterval(() => {
  if (!ended && lastEvent && Date.now() - lastEvent > 3000) setStatus('超過 3 秒沒有心跳事件', 'dead');
}, 1000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 保持 stderr 乾淨
        pass

    def do_GET(self):
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q: queue.Queue = queue.Queue()
            with CLIENTS_LOCK:
                CLIENTS.append(q)
            try:
                for ev in list(HISTORY):  # 先補歷史
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                if STREAM_ENDED.is_set():
                    self.wfile.write(b'data: {"_status": "ended"}\n\n')
                self.wfile.flush()
                while True:
                    try:
                        payload = q.get(timeout=15)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with CLIENTS_LOCK:
                    CLIENTS.remove(q)
            return

        self.send_response(200 if self.path == "/" else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.path == "/":
            self.wfile.write(PAGE.encode())


def main() -> int:
    parser = argparse.ArgumentParser(description="H10 JSONL pass-through monitor")
    parser.add_argument("--port", type=int, default=8931)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=reader, args=(server,), daemon=True).start()
    print(f"監控頁面: http://localhost:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
