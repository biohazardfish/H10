"""Emit sample heartbeat JSONL at a controllable, repeatable pace."""

import argparse
import itertools
import json
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate Polar H10 JSONL events")
    parser.add_argument("events", help="JSONL event file")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="playback speed multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--beats",
        type=int,
        default=0,
        help="number of events to emit; 0 means loop forever",
    )
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be greater than zero")
    if args.beats < 0:
        parser.error("--beats must be zero or greater")

    with open(args.events, encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream if line.strip()]
    if not events:
        parser.error("event file is empty")

    count = 0
    try:
        for event in itertools.cycle(events):
            if args.beats and count >= args.beats:
                break
            print(json.dumps(event), flush=True)
            count += 1
            rr_ms = event.get("rr_ms")
            interval_ms = rr_ms if isinstance(rr_ms, (int, float)) and rr_ms > 0 else 800
            time.sleep(max(interval_ms, 300) / 1000.0 / args.speed)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
