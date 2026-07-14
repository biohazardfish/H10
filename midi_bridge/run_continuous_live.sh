#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
PYTHON="${H10_PYTHON:-$ROOT/venv/bin/python}"

"$PYTHON" "$ROOT/h10_performance_live.py" | \
  "$PYTHON" "$ROOT/midi_bridge/continuous_bridge.py" \
    --config "$ROOT/midi_bridge/continuous_mapping.json" \
    --virtual --port "H10 Continuous Body Field" \
    --control-port "Minilab3 MIDI"
