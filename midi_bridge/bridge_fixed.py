#!/usr/bin/env python3
"""H10 JSONL -> MIDI bridge (V3 validated baseline + reliability hardening).

Reliability fixes on top of the validated V3 pipeline (architecture unchanged):
  1. Clean MIDI shutdown: track active notes; on stdin EOF / KeyboardInterrupt /
     unexpected exit, send Note Off for every active note and CC123 (All Notes
     Off) on every used channel before closing the port -> the sustained drone
     can no longer stay stuck.
  2. Invalid-RR handling: RR values that are missing / zero / negative /
     physiologically implausible are ignored by every mapping and by the HRV
     maths (never treated as a real interval).
  3. rr_delta is now a SIGNED delta (rr - prev_rr), so the -80..80 pitch-bend
     mapping bends both directions instead of only upward from centre.
  4. Program Change re-triggers on zone re-entry (edge-detected) instead of
     firing once and never again.
  5. No silent JSON fallback: outside --dry-run, if MIDI init or port opening
     fails the bridge prints a clear error and exits non-zero.
"""

import argparse
import collections
import json
import math
import sys
from typing import Any, Deque, Dict, List, Optional, Set, Tuple


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


VALID_MODES = {"cc", "note", "pulse", "pitchbend", "program_change"}
VALID_CURVES = {"linear", "log", "exp", "scurve"}
VALID_SMOOTHING_TYPES = {"ema", "attack_release", "moving_average", "median", "rate_limit"}
VALID_CONDITION_OPS = {"<", "<=", ">", ">=", "==", "!="}

BUILTIN_INPUTS = {"bpm", "rr_ms", "beat"}
DERIVED_INPUTS = {"hrv_rmssd", "hrv_sdnn", "rr_delta", "bpm_accel"}
ALL_KNOWN_INPUTS = BUILTIN_INPUTS | DERIVED_INPUTS

# Fix 2: physiologically plausible RR interval window in milliseconds.
# 270 ms ~= 222 bpm ceiling; 2000 ms = 30 bpm floor. Anything outside
# (including 0, negative, or None) is treated as "no RR this packet".
RR_MIN_MS = 270.0
RR_MAX_MS = 2000.0


def is_valid_rr(rr: Any) -> bool:
    """True only for a finite RR interval inside the physiological window."""
    if rr is None:
        return False
    try:
        rr = float(rr)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(rr):
        return False
    return RR_MIN_MS <= rr <= RR_MAX_MS


# ---------------------------------------------------------------------------
# Config validation (unchanged from V3)
# ---------------------------------------------------------------------------

def validate_mapping(idx: int, m: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    inp = m.get("input")
    if inp is None:
        errors.append(f"mapping[{idx}]: missing required field 'input'")
    mode = m.get("mode", "cc")
    if mode not in VALID_MODES:
        errors.append(f"mapping[{idx}]: unknown mode '{mode}'")
    for key in ("min", "max"):
        v = m.get(key)
        if v is not None:
            try:
                float(v)
            except (TypeError, ValueError):
                errors.append(f"mapping[{idx}]: '{key}' must be a number, got {v!r}")
    curve = m.get("curve", "linear")
    if curve not in VALID_CURVES:
        errors.append(f"mapping[{idx}]: unknown curve '{curve}'")
    ch = m.get("channel", 1)
    try:
        ch = int(ch)
        if ch < 1 or ch > 16:
            errors.append(f"mapping[{idx}]: channel must be 1-16, got {ch}")
    except (TypeError, ValueError):
        errors.append(f"mapping[{idx}]: channel must be an integer, got {ch!r}")
    if mode == "cc":
        cc = m.get("cc", 1)
        try:
            cc = int(cc)
            if cc < 0 or cc > 127:
                errors.append(f"mapping[{idx}]: cc must be 0-127, got {cc}")
        except (TypeError, ValueError):
            errors.append(f"mapping[{idx}]: cc must be an integer, got {cc!r}")
    if mode in ("note", "pulse"):
        note = m.get("note", 36)
        try:
            note = int(note)
            if note < 0 or note > 127:
                errors.append(f"mapping[{idx}]: note must be 0-127, got {note}")
        except (TypeError, ValueError):
            errors.append(f"mapping[{idx}]: note must be an integer, got {note!r}")
    if mode == "program_change":
        prog = m.get("program")
        if prog is None:
            errors.append(f"mapping[{idx}]: mode 'program_change' requires 'program'")
        else:
            try:
                prog = int(prog)
                if prog < 0 or prog > 127:
                    errors.append(f"mapping[{idx}]: program must be 0-127, got {prog}")
            except (TypeError, ValueError):
                errors.append(f"mapping[{idx}]: program must be an integer, got {prog!r}")
    sm = m.get("smoothing")
    if sm is not None:
        st = sm.get("type", "ema")
        if st not in VALID_SMOOTHING_TYPES:
            errors.append(f"mapping[{idx}].smoothing: unknown type '{st}'")
    cond = m.get("condition")
    if cond is not None:
        if not isinstance(cond, dict):
            errors.append(f"mapping[{idx}]: 'condition' must be an object")
        else:
            if "field" not in cond:
                errors.append(f"mapping[{idx}].condition: missing 'field'")
            op = cond.get("op")
            if op not in VALID_CONDITION_OPS:
                errors.append(f"mapping[{idx}].condition: unknown op '{op}'")
            if "value" not in cond:
                errors.append(f"mapping[{idx}].condition: missing 'value'")
    zone = m.get("zone")
    if zone is not None:
        if not isinstance(zone, list) or len(zone) != 2:
            errors.append(f"mapping[{idx}]: 'zone' must be a [lo, hi] array")
    return errors


def validate_config(config: Dict[str, Any]) -> None:
    mappings = config.get("mappings")
    if mappings is None:
        eprint("Config error: missing 'mappings' array")
        sys.exit(2)
    if not isinstance(mappings, list):
        eprint("Config error: 'mappings' must be an array")
        sys.exit(2)
    all_errors: List[str] = []
    for idx, m in enumerate(mappings):
        all_errors.extend(validate_mapping(idx, m))
    if all_errors:
        eprint("Config validation failed:")
        for e in all_errors:
            eprint(f"  - {e}")
        sys.exit(2)


def load_config(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        eprint(f"Config not found: {path}")
        sys.exit(2)
    except json.JSONDecodeError as exc:
        eprint(f"Invalid JSON in config: {path}: {exc}")
        sys.exit(2)
    validate_config(config)
    return config


# ---------------------------------------------------------------------------
# Math / curves / smoothing (unchanged from V3)
# ---------------------------------------------------------------------------

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


def apply_curve(norm: float, curve: str) -> float:
    if curve == "linear":
        return norm
    if curve == "log":
        return math.log1p(norm * 9) / math.log(10)
    if curve == "exp":
        return (math.pow(10, norm) - 1) / 9.0
    if curve == "scurve":
        return norm * norm * (3.0 - 2.0 * norm)
    return norm


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
        out = prev + (attack if value >= prev else release) * (value - prev)
        state["ar"] = out
        return out
    if stype == "moving_average":
        window = int(smoothing.get("window", 5))
        buf: Deque[float] = state.setdefault("ma_buf", collections.deque(maxlen=window))
        buf.append(value)
        return sum(buf) / len(buf)
    if stype == "median":
        window = int(smoothing.get("window", 5))
        buf = state.setdefault("med_buf", collections.deque(maxlen=window))
        buf.append(value)
        sorted_buf = sorted(buf)
        n = len(sorted_buf)
        if n % 2 == 1:
            return sorted_buf[n // 2]
        return (sorted_buf[n // 2 - 1] + sorted_buf[n // 2]) / 2.0
    if stype == "rate_limit":
        max_delta = float(smoothing.get("max_delta", 0.05))
        prev = state.get("rl")
        if prev is None:
            state["rl"] = value
            return value
        delta = value - prev
        if abs(delta) > max_delta:
            delta = max_delta if delta > 0 else -max_delta
        out = prev + delta
        state["rl"] = out
        return out
    return value


# ---------------------------------------------------------------------------
# Derived inputs (HRV) — Fix 2 (RR validation) + Fix 3 (signed rr_delta)
# ---------------------------------------------------------------------------

class DerivedInputs:
    def __init__(self, rr_window: int = 20) -> None:
        self.rr_window = rr_window
        self.rr_history: Deque[float] = collections.deque(maxlen=rr_window)
        self.prev_rr: Optional[float] = None
        self.prev_bpm: Optional[float] = None

    def update(self, event: Dict[str, Any]) -> Dict[str, Any]:
        augmented = dict(event)

        rr_raw = event.get("rr_ms")
        if is_valid_rr(rr_raw):                       # Fix 2
            rr = float(rr_raw)
            augmented["rr_ms"] = rr

            # Fix 3: SIGNED delta (was abs()). Positive = RR lengthened
            # (heart slowing) -> bend up; negative = RR shortened -> bend down.
            if self.prev_rr is not None:
                augmented["rr_delta"] = rr - self.prev_rr

            self.rr_history.append(rr)
            self.prev_rr = rr

            if len(self.rr_history) >= 2:
                rr_list = list(self.rr_history)
                n = len(rr_list)
                mean_rr = sum(rr_list) / n
                variance = sum((x - mean_rr) ** 2 for x in rr_list) / n
                augmented["hrv_sdnn"] = math.sqrt(variance)
                diffs_sq = [(rr_list[i] - rr_list[i - 1]) ** 2 for i in range(1, n)]
                augmented["hrv_rmssd"] = math.sqrt(sum(diffs_sq) / len(diffs_sq))
        else:
            # Fix 2: strip an invalid/absent rr_ms so no mapping consumes it
            # and no HRV value is derived from a bogus interval.
            augmented.pop("rr_ms", None)

        bpm = event.get("bpm")
        if bpm is not None:
            bpm = float(bpm)
            if self.prev_bpm is not None:
                augmented["bpm_accel"] = abs(bpm - self.prev_bpm)
            self.prev_bpm = bpm
        return augmented


# ---------------------------------------------------------------------------
# MIDI sink — Fix 1 (active-note tracking + clean shutdown) + Fix 5 (hard fail)
# ---------------------------------------------------------------------------

CC_ALL_NOTES_OFF = 123


class MidiInitError(RuntimeError):
    """Raised when real MIDI cannot be initialised outside --dry-run."""


class MidiSink:
    def __init__(self, dry_run: bool, port_name: Optional[str], virtual: bool = False) -> None:
        self.dry_run = dry_run
        self.port_name = port_name
        self.virtual = virtual
        self.mido = None
        self.port = None
        self._closed = False
        # Fix 1: shutdown bookkeeping.
        self.active_notes: Set[Tuple[int, int]] = set()   # (channel, note)
        self.used_channels: Set[int] = set()

        if dry_run:
            return

        try:
            import mido  # type: ignore
            self.mido = mido
        except Exception as exc:                          # Fix 5
            raise MidiInitError(
                f"python-mido is required for MIDI output but could not be imported: {exc}. "
                f"Install it (pip install 'mido[rtmidi]') or run with --dry-run."
            )

        try:
            if self.virtual:
                name = self.port_name or "H10 Bridge"
                self.port = self.mido.open_output(name, virtual=True)
                eprint(f"Opened virtual MIDI output: {name}")
            elif self.port_name:
                self.port = self.mido.open_output(self.port_name)
            else:
                self.port = self.mido.open_output()
        except Exception as exc:                          # Fix 5
            raise MidiInitError(
                f"Failed to open MIDI output "
                f"({'virtual ' if self.virtual else ''}port={self.port_name!r}): {exc}"
            )

    # -- emit helpers -------------------------------------------------------
    def _emit_json(self, payload: Dict[str, Any]) -> None:
        print(json.dumps(payload, ensure_ascii=True))

    def _use_channel(self, channel: int) -> None:
        self.used_channels.add(channel)

    def send_cc(self, channel, cc, value, meta):
        self._use_channel(channel)
        if self.dry_run or self.port is None:
            self._emit_json({"type": "cc", "channel": channel, "cc": cc, "value": value, **meta})
            return
        self.port.send(self.mido.Message("control_change", channel=channel - 1, control=cc, value=value))

    def send_note_on(self, channel, note, velocity, meta):
        self._use_channel(channel)
        self.active_notes.add((channel, note))            # Fix 1
        if self.dry_run or self.port is None:
            self._emit_json({"type": "note_on", "channel": channel, "note": note, "velocity": velocity, **meta})
            return
        self.port.send(self.mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity))

    def send_note_off(self, channel, note, velocity, meta):
        self._use_channel(channel)
        self.active_notes.discard((channel, note))        # Fix 1
        if self.dry_run or self.port is None:
            self._emit_json({"type": "note_off", "channel": channel, "note": note, "velocity": velocity, **meta})
            return
        self.port.send(self.mido.Message("note_off", channel=channel - 1, note=note, velocity=velocity))

    def send_pitchbend(self, channel, value, meta):
        self._use_channel(channel)
        if self.dry_run or self.port is None:
            self._emit_json({"type": "pitchbend", "channel": channel, "value": value, **meta})
            return
        self.port.send(self.mido.Message("pitchwheel", channel=channel - 1, pitch=value))

    def send_program_change(self, channel, program, meta):
        self._use_channel(channel)
        if self.dry_run or self.port is None:
            self._emit_json({"type": "program_change", "channel": channel, "program": program, **meta})
            return
        self.port.send(self.mido.Message("program_change", channel=channel - 1, program=program))

    # -- Fix 1: clean shutdown ---------------------------------------------
    def close(self) -> None:
        """Release every active note, blanket All-Notes-Off each used channel,
        then close the port. Idempotent; safe to call from a finally block."""
        if self._closed:
            return
        self._closed = True

        meta = {"source": "shutdown"}
        # 1) explicit Note Off for each note we believe is still on
        for channel, note in sorted(self.active_notes):
            self.send_note_off(channel, note, 0, meta)
        self.active_notes.clear()
        # 2) CC123 All-Notes-Off on every channel we ever touched (kills the
        #    sustained drone even if our bookkeeping missed anything)
        for channel in sorted(self.used_channels):
            if self.dry_run or self.port is None:
                self._emit_json({"type": "cc", "channel": channel, "cc": CC_ALL_NOTES_OFF, "value": 0, **meta})
            else:
                self.port.send(self.mido.Message(
                    "control_change", channel=channel - 1, control=CC_ALL_NOTES_OFF, value=0))

        if self.port is not None:
            try:
                self.port.close()
            except Exception as exc:
                eprint(f"Error closing MIDI port: {exc}")


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def to_cc_value(norm: float) -> int:
    return int(round(clamp(norm, 0.0, 1.0) * 127))


def to_velocity(norm: float) -> int:
    return max(1, int(round(clamp(norm, 0.0, 1.0) * 127)))


def to_pitchbend(norm: float) -> int:
    return int(round(clamp(norm, 0.0, 1.0) * 16383 - 8192))


# ---------------------------------------------------------------------------
# Condition & zone
# ---------------------------------------------------------------------------

def eval_condition(cond: Dict[str, Any], event: Dict[str, Any]) -> bool:
    field = cond.get("field", "")
    if field not in event:
        return False
    try:
        actual = float(event[field])
    except (TypeError, ValueError):
        return False
    op = cond.get("op", ">=")
    target = float(cond.get("value", 0))
    return {
        "<": actual < target, "<=": actual <= target,
        ">": actual > target, ">=": actual >= target,
        "==": actual == target, "!=": actual != target,
    }.get(op, True)


def eval_zone(zone: List[float], raw: float) -> bool:
    return zone[0] <= raw <= zone[1]


# ---------------------------------------------------------------------------
# Core event processing — Fix 4 (program-change zone edge detection)
# ---------------------------------------------------------------------------

def process_event(event, config, states, sink):
    for idx, mapping in enumerate(config.get("mappings", [])):
        inp = mapping.get("input")
        if inp not in event:
            continue
        try:
            raw = float(event[inp])
        except Exception:
            eprint(f"Non-numeric input for '{inp}': {event.get(inp)}")
            continue

        mode = mapping.get("mode", "cc")
        state = states.setdefault(idx, {})   # available to both skip + handler

        cond = mapping.get("condition")
        if cond is not None and not eval_condition(cond, event):
            if mode == "program_change":
                state["pc_in_zone"] = False   # condition unmet counts as "outside"
            continue

        zone = mapping.get("zone")
        if zone is not None and not eval_zone(zone, raw):
            if mode == "program_change":      # Fix 4: record that we left the zone
                state["pc_in_zone"] = False
            continue

        vmin = float(mapping.get("min", 0.0))
        vmax = float(mapping.get("max", 1.0))
        norm = normalize(raw, vmin, vmax)
        norm = apply_curve(norm, mapping.get("curve", "linear"))
        smooth = apply_smoothing(norm, mapping.get("smoothing"), state)
        meta = {"source": inp, "raw": raw, "normalized": norm, "smoothed": smooth}
        channel = int(mapping.get("channel", 1))

        if mode == "cc":
            cc = int(mapping.get("cc", 1))
            cc_val = to_cc_value(smooth)
            min_change = int(mapping.get("min_change", 0))
            if min_change > 0:
                last_sent = state.get("last_cc")
                if last_sent is not None and abs(cc_val - last_sent) < min_change:
                    continue
                state["last_cc"] = cc_val
            sink.send_cc(channel, cc, cc_val, meta)
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

        if mode == "pulse":
            note = int(mapping.get("note", 36))
            velocity = int(mapping.get("velocity", 100))
            if mapping.get("velocity_from_input"):
                velocity = to_velocity(smooth)
            prev = state.get("pulse_note_on")
            if prev is not None:
                sink.send_note_off(channel, prev, 0, meta)
            sink.send_note_on(channel, note, velocity, meta)
            state["pulse_note_on"] = note
            continue

        if mode == "pitchbend":
            sink.send_pitchbend(channel, to_pitchbend(smooth), meta)
            continue

        if mode == "program_change":
            # Fix 4: fire on the rising edge of zone/condition entry only,
            # but allow re-fire after we have left and come back.
            program = int(mapping.get("program", 0))
            if not state.get("pc_in_zone", False):
                sink.send_program_change(channel, program, meta)
            state["pc_in_zone"] = True
            continue

        eprint(f"Unknown mode: {mode}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="H10 JSONL to MIDI bridge")
    p.add_argument("--config", default="mapping_config.json")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--port", default=None)
    p.add_argument("--virtual", action="store_true")
    return p.parse_args()


def run(config: Dict[str, Any], sink: MidiSink, stream) -> int:
    """Process a JSONL stream. Always closes the sink (Fix 1)."""
    derived = DerivedInputs(rr_window=int(config.get("derived_rr_window", 20)))
    states: Dict[int, Dict[str, Any]] = {}
    try:
        for line in stream:
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
            event = derived.update(event)
            process_event(event, config, states, sink)
    except KeyboardInterrupt:                 # Fix 1
        eprint("Interrupted; sending All-Notes-Off and closing MIDI.")
    finally:
        sink.close()                          # Fix 1
    return 0


def main():
    args = parse_args()
    config = load_config(args.config)
    try:                                      # Fix 5
        sink = MidiSink(dry_run=args.dry_run, port_name=args.port, virtual=args.virtual)
    except MidiInitError as exc:
        eprint(f"FATAL: {exc}")
        return 3
    return run(config, sink, sys.stdin)


if __name__ == "__main__":
    sys.exit(main())
