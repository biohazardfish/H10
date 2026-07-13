#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

CONFIG="$ROOT/midi_bridge/mapping_config.json"
EVENTS="$ROOT/midi_bridge/examples/h10_demo_events.jsonl"
SIM="$ROOT/midi_bridge/examples/sim_heartbeat.py"
BRIDGE="$ROOT/midi_bridge/bridge.py"
PORT="${H10_MIDI_PORT:-H10 Bridge}"
MODE="${1:---dry-run}"

case "$MODE" in
  --dry-run)
    exec "$PYTHON" "$BRIDGE" --config "$CONFIG" --dry-run < "$EVENTS"
    ;;
  --sound)
    SPEED="${DEMO_SPEED:-1.0}"
    BEATS="${DEMO_BEATS:-0}"
    echo "Simulating H10 → virtual MIDI: $PORT (Ctrl-C to stop)" >&2
    echo "Speed: ${SPEED}x" >&2
    "$PYTHON" "$SIM" "$EVENTS" --speed "$SPEED" --beats "$BEATS" |
      "$PYTHON" "$BRIDGE" --config "$CONFIG" --virtual --port "$PORT"
    ;;
  *)
    echo "Usage: $0 [--dry-run|--sound]" >&2
    echo "  --dry-run  validate mappings and print MIDI intents (default)" >&2
    echo "  --sound    simulate H10 events into REAPER's '$PORT' MIDI port" >&2
    exit 2
    ;;
esac
