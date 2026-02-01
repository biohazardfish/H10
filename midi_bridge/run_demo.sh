#!/bin/sh
set -e
cd "$(dirname "$0")"
cat examples/h10_sample_events.jsonl | python3 bridge.py --dry-run
