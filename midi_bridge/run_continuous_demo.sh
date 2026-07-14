#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
PYTHON="${H10_PYTHON:-$ROOT/venv/bin/python}"
SPEED="${CONTINUOUS_DEMO_SPEED:-2}"

MODE="--dry-run"
REPLAY_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --dry-run|--sound) MODE="$arg" ;;
    --loop) REPLAY_ARGS+=(--loop) ;;
    *)
      print -u2 "Usage: $0 [--dry-run|--sound] [--loop]"
      exit 2
      ;;
  esac
done

if [[ "$MODE" == "--sound" ]]; then
  "$PYTHON" "$ROOT/midi_bridge/examples/replay_performance.py" --speed "$SPEED" "${REPLAY_ARGS[@]}" | \
    "$PYTHON" "$ROOT/midi_bridge/continuous_bridge.py" \
      --config "$ROOT/midi_bridge/continuous_mapping.json" \
      --virtual --port "H10 Continuous Body Field"
elif [[ "$MODE" == "--dry-run" ]]; then
  "$PYTHON" "$ROOT/midi_bridge/examples/replay_performance.py" --speed "$SPEED" "${REPLAY_ARGS[@]}" | \
    "$PYTHON" "$ROOT/midi_bridge/continuous_bridge.py" \
      --config "$ROOT/midi_bridge/continuous_mapping.json" \
      --dry-run --no-controller
fi
