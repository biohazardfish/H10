#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
PYTHON="${H10_PYTHON:-$ROOT/venv/bin/python}"

"$PYTHON" "$ROOT/h10_performance_live.py" | \
  "$PYTHON" "$ROOT/midi_bridge/performance_bridge.py" \
    --config "$ROOT/midi_bridge/performance_mapping.json" \
    --virtual --port "H10 Performance V4" \
    --control-port "Minilab3 MIDI"
