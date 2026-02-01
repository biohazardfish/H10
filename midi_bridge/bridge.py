#!/usr/bin/env python3
import argparse
import json
import sys
from typing import Any, Dict, Optional


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def load_config(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        eprint(f"Config not found: {path}")
        sys.exit(2)
    except json.JSONDecodeError as exc:
        eprint(f"Invalid JSON in config: {path}: {exc}")
        sys.exit(2)


def clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def normalize(value: float, vmin: float, vmax: float) -> float:
    if vmax == vmin:
        return 0.0
    return clamp((value - vmin) / (vmax - vmin), 0.0, 1.0)


def apply_smoothing(value: float, smoothing: Optional[Dict[str, Any]], state: Dict[str, Any]) -> float:
    if not smoothing:
        return value
    stype = smoothing.get("type", "ema")
    if stype == "ema":
        alpha = float(smoothing.get("alpha", 0.2))
        prev = state.get("ema")
        if prev is None:
            state["ema"] = value
            return value
        out = prev + alpha * (value - prev)
        state["ema"] = out
        return out
    if stype == "attack_release":
        attack = float(smoothing.get("attack", 0.2))
        release = float(smoothing.get("release", 0.2))
        prev = state.get("ar")
        if prev is None:
            state["ar"] = value
            return value
        if value >= prev:
            out = prev + attack * (value - prev)
        else:
            out = prev + release * (value - prev)
        state["ar"] = out
        return out
    return value


class MidiSink:
    def __init__(self, dry_run: bool, port_name: Optional[str]) -> None:
        self.dry_run = dry_run
        self.port_name = port_name
        self.mido = None
        self.port = None

        if dry_run:
            return

        try:
            import mido  # type: ignore
            self.mido = mido
        except Exception:
            self.mido = None
            return

        try:
            if self.port_name:
                self.port = self.mido.open_output(self.port_name)
            else:
                self.port = self.mido.open_output()
        except Exception as exc:
            eprint(f"Failed to open MIDI output: {exc}")
            self.port = None

    def send_cc(self, channel: int, cc: int, value: int, meta: Dict[str, Any]) -> None:
        if self.dry_run or self.mido is None or self.port is None:
            out = {"type": "cc", "channel": channel, "cc": cc, "value": value, **meta}
            print(json.dumps(out, ensure_ascii=True))
            return
        msg = self.mido.Message("control_change", channel=channel - 1, control=cc, value=value)
        self.port.send(msg)

    def send_note_on(self, channel: int, note: int, velocity: int, meta: Dict[str, Any]) -> None:
        if self.dry_run or self.mido is None or self.port is None:
            out = {"type": "note_on", "channel": channel, "note": note, "velocity": velocity, **meta}
            print(json.dumps(out, ensure_ascii=True))
            return
        msg = self.mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity)
        self.port.send(msg)

    def send_note_off(self, channel: int, note: int, velocity: int, meta: Dict[str, Any]) -> None:
        if self.dry_run or self.mido is None or self.port is None:
            out = {"type": "note_off", "channel": channel, "note": note, "velocity": velocity, **meta}
            print(json.dumps(out, ensure_ascii=True))
            return
        msg = self.mido.Message("note_off", channel=channel - 1, note=note, velocity=velocity)
        self.port.send(msg)


def to_cc_value(norm: float) -> int:
    return int(round(clamp(norm, 0.0, 1.0) * 127))


def to_velocity(norm: float) -> int:
    value = int(round(clamp(norm, 0.0, 1.0) * 127))
    return max(1, value)


def process_event(event: Dict[str, Any], config: Dict[str, Any], states: Dict[int, Dict[str, Any]], sink: MidiSink) -> None:
    mappings = config.get("mappings", [])
    for idx, mapping in enumerate(mappings):
        inp = mapping.get("input")
        if inp not in event:
            continue

        try:
            raw = float(event[inp])
        except Exception:
            eprint(f"Non-numeric input for '{inp}': {event.get(inp)}")
            continue

        vmin = float(mapping.get("min", 0.0))
        vmax = float(mapping.get("max", 1.0))
        norm = normalize(raw, vmin, vmax)

        state = states.setdefault(idx, {})
        smooth = apply_smoothing(norm, mapping.get("smoothing"), state)

        meta = {
            "source": inp,
            "raw": raw,
            "normalized": norm,
            "smoothed": smooth,
        }

        mode = mapping.get("mode", "cc")
        channel = int(mapping.get("channel", 1))

        if mode == "cc":
            cc = int(mapping.get("cc", 1))
            sink.send_cc(channel, cc, to_cc_value(smooth), meta)
            continue

        if mode == "note":
            note = int(mapping.get("note", 36))
            threshold = float(mapping.get("trigger_threshold", 0.7))
            hysteresis = float(mapping.get("hysteresis", 0.1))
            active = bool(state.get("note_active", False))

            if not active and smooth >= threshold:
                sink.send_note_on(channel, note, to_velocity(smooth), meta)
                state["note_active"] = True
            elif active and smooth <= (threshold - hysteresis):
                sink.send_note_off(channel, note, 0, meta)
                state["note_active"] = False
            continue

        eprint(f"Unknown mode: {mode}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H10 JSONL to MIDI bridge")
    parser.add_argument(
        "--config",
        default="mapping_config.json",
        help="Path to mapping_config.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not open MIDI ports; print MIDI-intent JSON instead",
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Optional MIDI output port name (if mido is available)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    sink = MidiSink(dry_run=args.dry_run, port_name=args.port)

    if not args.dry_run and sink.mido is None:
        eprint("mido not available; falling back to MIDI-intent JSON output")

    states: Dict[int, Dict[str, Any]] = {}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            eprint(f"Invalid JSON line: {exc}")
            continue
        if not isinstance(event, dict):
            eprint("JSON line must be an object")
            continue
        process_event(event, config, states, sink)

    return 0


if __name__ == "__main__":
    sys.exit(main())
