#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
PYTHON="${H10_PYTHON:-$ROOT/venv/bin/python}"
SPEED="${PERFORMANCE_DEMO_SPEED:-2}"
MODE="${1:---dry-run}"

if [[ "$MODE" == "--sound" ]]; then
  "$PYTHON" "$ROOT/midi_bridge/examples/replay_performance.py" --speed "$SPEED" | \
    "$PYTHON" "$ROOT/midi_bridge/performance_bridge.py" \
      --config "$ROOT/midi_bridge/performance_mapping.json" \
      --virtual --port "H10 Performance V4"
elif [[ "$MODE" == "--dry-run" ]]; then
  "$PYTHON" "$ROOT/midi_bridge/examples/replay_performance.py" --speed "$SPEED" | \
    "$PYTHON" "$ROOT/midi_bridge/performance_bridge.py" \
      --config "$ROOT/midi_bridge/performance_mapping.json" \
      --dry-run --no-controller
else
  print -u2 "Usage: $0 [--dry-run|--sound]"
  exit 2
fi
