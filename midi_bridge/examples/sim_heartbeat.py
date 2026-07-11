"""循環播放範例心跳事件，按 rr_ms 的真實節奏輸出 JSONL。"""
import json, sys, time, itertools

events = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
for ev in itertools.cycle(events):
    print(json.dumps(ev), flush=True)
    time.sleep(max(ev.get("rr_ms", 800), 300) / 1000.0)
