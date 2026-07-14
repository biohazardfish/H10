#!/usr/bin/env python3
"""H10 Continuous Body Field JSONL -> MIDI bridge.

Parallel to the validated V4 five-scene bridge (``performance_bridge.py``,
untouched).  This module removes scene classification entirely: body state
maps continuously to sound-control axes with no discrete states, thresholds,
transitions, or forcing.  Calibration, RR artifact filtering, asymmetric
smoothing, dropout handling, and the MIDI gate/panic sink are scene-agnostic
in the V4 bridge already, so they are reused here unmodified rather than
duplicated.
"""

from __future__ import annotations

import argparse
import collections
import json
import queue
import selectors
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Deque

import bridge as core
from performance_bridge import (
    AsymmetricSmoother,
    PerformanceMidiSink,
    RRArtifactFilter,
    angle_degrees,
    calculate_rmssd,
    clamp,
    eprint,
    event_time,
    finite,
    log_normalize,
    normalize,
    smoothstep,
    vector_unit,
)


DEFAULT_CONFIG = Path(__file__).with_name("continuous_mapping.json")

CORE_SIGNALS = (
    "arousal", "regulation", "motion", "uprightness",
    "pulse_gap", "fluidity", "rotation", "stillness",
)


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        config = json.load(stream)
    required = {"calibration", "rr_filter", "ranges", "dropout", "midi", "smoothing"}
    missing = required - set(config)
    if config.get("schema") != "h10_continuous_v1" or missing:
        raise ValueError(f"invalid continuous performance config; missing={sorted(missing)}")
    midi_config = config["midi"]
    if "scene_cc" in midi_config or "scene_values" in midi_config or "state_machine" in config:
        raise ValueError("continuous config must not define scene_cc, scene_values, or state_machine")
    signals = midi_config.get("signals", {})
    if set(signals) != set(CORE_SIGNALS):
        raise ValueError("continuous config MIDI signal contract is incomplete")
    for cc in signals.values():
        if not isinstance(cc, int) or not 0 <= cc <= 127:
            raise ValueError(f"invalid MIDI CC: {cc!r}")
    if "recovery" not in config["smoothing"]:
        raise ValueError("continuous config missing recovery smoothing parameters")
    return config


class ContinuousEngine:
    """Body state -> continuous physiological/movement features -> continuous targets.

    No scene enum, no scene ordering, no scene thresholds or hold timers, and
    no manual scene forcing exist anywhere in this class.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.calibration_config = config["calibration"]
        self.ranges = config["ranges"]
        self.dropout_config = config["dropout"]
        self.midi_config = config["midi"]
        self.rr_filter = RRArtifactFilter(config["rr_filter"])
        self.rr_history: Deque[float] = collections.deque(
            maxlen=int(config["rr_filter"].get("history_size", 20))
        )

        self.baseline_bpm = float(self.calibration_config.get("default_baseline_bpm", 109.0))
        self.baseline_rr = float(self.calibration_config.get("default_baseline_rr_ms", 553.0))
        self.baseline_gravity: tuple[float, float, float] | None = None
        self.calibrated = False
        self.stable_started_at: float | None = None
        self.calibration_gravity: list[tuple[float, float, float]] = []
        self.calibration_bpms: list[float] = []
        self.calibration_rrs: list[float] = []

        self.panic_latched = False

        self.latest_bpm: float | None = None
        self.bpm_ema: float | None = None
        self.last_heart_at: float | None = None
        self.last_motion_at: float | None = None
        self.motion_available = True
        self.heart_available = True
        self.all_signals_lost_at: float | None = None
        self.outage_gate_closed = False
        self.last_clock: float | None = None
        self.last_emit_at: float | None = None
        self.last_snapshot_at: float | None = None
        self.note_off_due: float | None = None
        self.last_midi_values: dict[int, int] = {}
        self.gate_started = False
        self.last_diag_at = 0.0

        self.targets: dict[str, float] = {
            "arousal": 0.0,
            "regulation": 0.5,
            "motion": 0.0,
            "uprightness": 0.0,
            "pulse_gap": normalize(
                self.baseline_rr,
                float(self.ranges["rr_min_ms"]),
                float(self.ranges["rr_max_ms"]),
            ),
            "fluidity": 0.5,
            "rotation": 0.0,
            "stillness": 1.0,
            # Fully "recovered" is the sensible default before any heartbeat
            # has been observed.
            "recovery": 1.0,
        }
        self.smoothers: dict[str, AsymmetricSmoother] = {}
        for name, smoothing in config["smoothing"].items():
            self.smoothers[name] = AsymmetricSmoother(
                smoothing.get("attack_seconds", 1.0),
                smoothing.get("release_seconds", 1.0),
                initial=self.targets.get(name, 0.0),
            )

    def _clock(self, now: float) -> tuple[float, float]:
        now = float(now)
        if self.last_clock is None:
            self.last_clock = now
            return now, 0.1
        now = max(now, self.last_clock)
        dt_seconds = max(0.001, min(1.0, now - self.last_clock))
        self.last_clock = now
        return now, dt_seconds

    def update_heartbeat(self, event: dict[str, Any], now: float) -> int:
        bpm = finite(event.get("bpm"))
        self.last_heart_at = now
        self.heart_available = True
        if bpm is not None:
            self.latest_bpm = bpm
            if self.bpm_ema is None:
                self.bpm_ema = bpm
            else:
                alpha = 0.25 if bpm >= self.bpm_ema else 0.08
                self.bpm_ema += alpha * (bpm - self.bpm_ema)
            if not self.calibrated and self.stable_started_at is not None:
                self.calibration_bpms.append(bpm)

            delta = (self.bpm_ema - self.baseline_bpm) / float(
                self.ranges["arousal_delta_bpm"]
            )
            self.targets["arousal"] = smoothstep(delta)

        rr = self.rr_filter.accept(event.get("rr_ms"), bpm)
        if rr is not None:
            self.rr_history.append(rr)
            if not self.calibrated and self.stable_started_at is not None:
                self.calibration_rrs.append(rr)
            self.targets["pulse_gap"] = normalize(
                rr, float(self.ranges["rr_min_ms"]), float(self.ranges["rr_max_ms"])
            )
            rmssd = calculate_rmssd(self.rr_history)
            if rmssd is not None:
                self.targets["regulation"] = log_normalize(
                    rmssd,
                    float(self.ranges["rmssd_min_ms"]),
                    float(self.ranges["rmssd_max_ms"]),
                )

        velocity = round(
            42.0 + 18.0 * self.targets["arousal"] + 12.0 * self.targets["motion"]
        )
        return int(clamp(float(velocity), 42.0, 72.0))

    def update_motion(self, event: dict[str, Any], now: float) -> None:
        motion_rms = finite(event.get("motion_rms_mg"))
        jerk_rms = finite(event.get("jerk_rms_mg_s"))
        rotation_rms = finite(event.get("rotation_rms_deg_s"))
        gravity = vector_unit(event.get("gravity_unit", ()))
        if motion_rms is None or gravity is None:
            return

        self.last_motion_at = now
        self.motion_available = True
        motion = log_normalize(
            motion_rms,
            float(self.ranges["motion_min_mg"]),
            float(self.ranges["motion_max_mg"]),
        )
        self.targets["motion"] = motion
        self.targets["stillness"] = 1.0 - motion

        if jerk_rms is not None and motion_rms > float(self.ranges["motion_min_mg"]):
            ratio = jerk_rms / max(1.0, motion_rms)
            self.targets["fluidity"] = 1.0 - normalize(
                ratio,
                float(self.ranges["fluidity_ratio_min"]),
                float(self.ranges["fluidity_ratio_max"]),
            )
        if rotation_rms is not None:
            self.targets["rotation"] = log_normalize(
                rotation_rms,
                float(self.ranges["rotation_min_deg_s"]),
                float(self.ranges["rotation_max_deg_s"]),
            )

        if not self.calibrated:
            stable_limit = float(self.calibration_config["max_motion_rms_mg"])
            if motion_rms <= stable_limit:
                if self.stable_started_at is None:
                    self.stable_started_at = now
                    self.calibration_gravity.clear()
                    self.calibration_bpms.clear()
                    self.calibration_rrs.clear()
                    eprint("Continuous calibration started; remain lying still.")
                self.calibration_gravity.append(gravity)
                if now - self.stable_started_at >= float(
                    self.calibration_config["stable_seconds"]
                ):
                    mean_gravity = tuple(
                        statistics.fmean(vector[index] for vector in self.calibration_gravity)
                        for index in range(3)
                    )
                    self.baseline_gravity = vector_unit(mean_gravity)
                    if self.calibration_bpms:
                        self.baseline_bpm = statistics.median(self.calibration_bpms)
                    if self.calibration_rrs:
                        self.baseline_rr = statistics.median(self.calibration_rrs)
                    self.calibrated = self.baseline_gravity is not None
                    eprint(
                        "Continuous calibration complete: "
                        f"baseline_bpm={self.baseline_bpm:.1f} "
                        f"baseline_rr={self.baseline_rr:.1f}"
                    )
            else:
                if self.stable_started_at is not None:
                    eprint("Continuous calibration paused: movement exceeded stillness threshold.")
                self.stable_started_at = None
                self.calibration_gravity.clear()
                self.calibration_bpms.clear()
                self.calibration_rrs.clear()

        if self.calibrated and self.baseline_gravity is not None:
            angle = angle_degrees(self.baseline_gravity, gravity)
            if angle is not None:
                self.targets["uprightness"] = smoothstep(
                    normalize(
                        angle,
                        float(self.ranges["upright_min_deg"]),
                        float(self.ranges["upright_max_deg"]),
                    )
                )

    def handle_status(self, event: dict[str, Any]) -> None:
        if "motion_available" in event:
            self.motion_available = bool(event["motion_available"])
        if "heart_available" in event:
            self.heart_available = bool(event["heart_available"])

    def handle_control(self, message: Any, sink: PerformanceMidiSink, now: float) -> None:
        # Only the pad channel (3) is interpreted. The MiniLab keyboard
        # (channel 2) deliberately has NO function here: unlike V4 there is
        # no root-pitch selection -- keyboard notes flow directly to the
        # MELODY VOICE track in REAPER and are played manually.
        if getattr(message, "channel", -1) + 1 != 3:
            return
        message_type = getattr(message, "type", "")
        note = int(getattr(message, "note", -1))
        velocity = int(getattr(message, "velocity", 0))
        is_on = message_type == "note_on" and velocity > 0

        # Pads 1-7 (notes 36-42) are intentionally ignored: no scene forcing,
        # no AUTO resume, no recalibration, no freeze, no hidden debug
        # function. Only Pad 8 (note 43) does anything, and panic is a
        # one-way latch -- restart the bridge to resume sound.
        if is_on and note == 43:
            self.panic_latched = True
            sink.panic()
            eprint("Continuous PANIC latched; restart the bridge to resume sound.")

    def _schedule_heartbeat(self, sink: PerformanceMidiSink, velocity: int, now: float) -> None:
        if self.panic_latched:
            return
        channel = int(self.midi_config["heartbeat_channel"])
        note = int(self.midi_config["heartbeat_note"])
        meta = {"source": "heartbeat"}
        if (channel, note) in sink.active_notes:
            sink.send_note_off(channel, note, 0, meta)
        sink.send_note_on(channel, note, velocity, meta)
        self.note_off_due = now + float(self.midi_config["heartbeat_gate_ms"]) / 1000.0

    def _update_smoothing(self, now: float, dt_seconds: float) -> dict[str, float]:
        if (
            self.last_heart_at is not None
            and now - self.last_heart_at > float(self.dropout_config["heart_stale_seconds"])
        ):
            self.heart_available = False
            self.targets["arousal"] = 0.0
        if (
            self.last_motion_at is not None
            and now - self.last_motion_at > float(self.dropout_config["motion_stale_seconds"])
        ):
            self.motion_available = False
            self.targets["motion"] = 0.0
            self.targets["rotation"] = 0.0
            self.targets["stillness"] = 1.0

        values: dict[str, float] = {}
        for name in CORE_SIGNALS:
            smoother = self.smoothers[name]
            dropout_release = None
            if name == "arousal" and not self.heart_available:
                dropout_release = float(self.dropout_config["heart_arousal_release_seconds"])
            values[name] = smoother.update(
                self.targets.get(name, 0.0),
                dt_seconds,
                release_seconds_override=dropout_release,
            )

        # Recovery targets the inverse of the already-smoothed arousal, then
        # applies its own, even slower attack. That asymmetry is what makes
        # "body settled, heart not yet recovered" audible: stillness/
        # uprightness release back to baseline quickly (their own smoothers),
        # while recovery keeps lagging behind for tens of seconds. If arousal
        # spikes again, recovery's fast release lets it drop right away.
        self.targets["recovery"] = clamp(1.0 - values["arousal"])
        values["recovery"] = self.smoothers["recovery"].update(
            self.targets["recovery"], dt_seconds
        )
        return values

    def _update_signal_gate(self, now: float, sink: PerformanceMidiSink) -> None:
        if not self.heart_available and not self.motion_available:
            if self.all_signals_lost_at is None:
                self.all_signals_lost_at = now
            lost_seconds = now - self.all_signals_lost_at
            if (
                not self.outage_gate_closed
                and lost_seconds >= float(self.dropout_config["all_lost_gate_seconds"])
            ):
                sink.send_gate(False, force=True)
                self.outage_gate_closed = True
                eprint("Continuous heartbeat and motion unavailable; performance gate faded out.")
            return

        self.all_signals_lost_at = None
        if self.outage_gate_closed:
            self.outage_gate_closed = False
            self.last_snapshot_at = None
            if not self.panic_latched:
                sink.send_gate(True, force=True)
                eprint("Continuous signal recovered; performance gate restored.")

    def _emit_controls(
        self,
        sink: PerformanceMidiSink,
        now: float,
        values: dict[str, float],
        force: bool = False,
    ) -> None:
        max_hz = float(self.midi_config.get("max_cc_hz", 10.0))
        if not force and self.last_emit_at is not None and now - self.last_emit_at < 1.0 / max_hz:
            return
        self.last_emit_at = now
        snapshot_seconds = float(self.midi_config.get("snapshot_keepalive_seconds", 1.0))
        refresh_snapshot = (
            self.last_snapshot_at is None
            or now - self.last_snapshot_at >= snapshot_seconds
        )
        if (
            not self.panic_latched
            and not self.outage_gate_closed
            and (not self.gate_started or refresh_snapshot)
        ):
            sink.send_gate(True, force=True)
            self.gate_started = True
            self.last_snapshot_at = now
        if self.panic_latched or self.outage_gate_closed:
            return

        channel = int(self.midi_config["channel"])
        signals: dict[str, int] = self.midi_config["signals"]
        for name, cc in signals.items():
            midi_value = int(round(clamp(values.get(name, 0.0)) * 127.0))
            if force or refresh_snapshot or self.last_midi_values.get(cc) != midi_value:
                self.last_midi_values[cc] = midi_value
                sink.send_cc(channel, int(cc), midi_value, {"source": name})

    def _diagnostics(self, now: float, values: dict[str, float]) -> None:
        if now - self.last_diag_at < 1.0:
            return
        self.last_diag_at = now
        calibration = "ready" if self.calibrated else "waiting"
        eprint(
            "Continuous diag "
            f"cal={calibration} bpm={self.latest_bpm if self.latest_bpm is not None else '-'} "
            f"arousal={values.get('arousal', 0):.2f} motion={values.get('motion', 0):.2f} "
            f"upright={values.get('uprightness', 0):.2f} "
            f"recovery={values.get('recovery', 0):.2f} "
            f"rr_rejected={self.rr_filter.rejected}"
        )

    def process_event(self, event: dict[str, Any], sink: PerformanceMidiSink) -> None:
        now = event_time(event)
        kind = event.get("kind")
        if kind == "heartbeat":
            velocity = self.update_heartbeat(event, now)
            if event.get("beat"):
                self._schedule_heartbeat(sink, velocity, now)
        elif kind == "motion":
            self.update_motion(event, now)
        elif kind == "status":
            self.handle_status(event)
        else:
            return
        self.tick(now, sink)

    def tick(self, now: float, sink: PerformanceMidiSink) -> None:
        now, dt_seconds = self._clock(now)
        if self.note_off_due is not None and now >= self.note_off_due:
            channel = int(self.midi_config["heartbeat_channel"])
            note = int(self.midi_config["heartbeat_note"])
            sink.send_note_off(channel, note, 0, {"source": "heartbeat_gate"})
            self.note_off_due = None
        values = self._update_smoothing(now, dt_seconds)
        self._update_signal_gate(now, sink)
        self._emit_controls(sink, now, values)
        self._diagnostics(now, values)

    def shutdown(self, sink: PerformanceMidiSink) -> None:
        if self.note_off_due is not None:
            channel = int(self.midi_config["heartbeat_channel"])
            note = int(self.midi_config["heartbeat_note"])
            sink.send_note_off(channel, note, 0, {"source": "shutdown"})
            self.note_off_due = None
        sink.send_gate(False, force=True)


def parse_json_line(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        eprint(f"Invalid continuous JSONL event: {exc}")
        return None
    if not isinstance(event, dict):
        eprint("Continuous JSONL event must be an object")
        return None
    return event


def run_stream(
    config: dict[str, Any],
    sink: PerformanceMidiSink,
    stream: Any,
    control_queue: queue.Queue | None = None,
) -> int:
    engine = ContinuousEngine(config)

    def drain_controls() -> None:
        if control_queue is None:
            return
        while True:
            try:
                message = control_queue.get_nowait()
            except queue.Empty:
                return
            engine.handle_control(message, sink, time.monotonic())

    try:
        try:
            stream.fileno()
            can_select = True
        except (AttributeError, OSError):
            can_select = False

        if not can_select:
            for line in stream:
                drain_controls()
                event = parse_json_line(line.strip())
                if event is not None:
                    engine.process_event(event, sink)
            return 0

        selector = selectors.DefaultSelector()
        selector.register(stream, selectors.EVENT_READ)
        try:
            while True:
                drain_controls()
                ready = selector.select(timeout=0.05)
                engine.tick(time.monotonic(), sink)
                if not ready:
                    continue
                line = stream.readline()
                if line == "":
                    break
                line = line.strip()
                if not line:
                    continue
                event = parse_json_line(line)
                if event is not None:
                    engine.process_event(event, sink)
        finally:
            selector.close()
        return 0
    except KeyboardInterrupt:
        eprint("Continuous bridge interrupted; fading performance gate and releasing MIDI.")
        return 0
    finally:
        engine.shutdown(sink)
        sink.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H10 Continuous Body Field MIDI bridge")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--virtual", action="store_true")
    parser.add_argument("--port", default="H10 Continuous Body Field")
    parser.add_argument("--control-port", default="Minilab3 MIDI")
    parser.add_argument("--no-controller", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
        sink = PerformanceMidiSink(
            dry_run=args.dry_run,
            port_name=args.port,
            virtual=args.virtual,
        )
    except (OSError, ValueError, json.JSONDecodeError, core.MidiInitError) as exc:
        eprint(f"FATAL: {exc}")
        return 3

    control_messages: queue.Queue | None = None
    control_port = None
    if not args.no_controller:
        try:
            import mido

            control_messages = queue.Queue()
            control_port = mido.open_input(
                args.control_port, callback=lambda message: control_messages.put(message)
            )
            eprint(f"Opened MiniLab control input: {args.control_port}")
        except Exception as exc:
            eprint(f"MiniLab control unavailable ({exc}); continuous mode remains active.")
            control_messages = None

    try:
        return run_stream(config, sink, sys.stdin, control_messages)
    finally:
        if control_port is not None:
            control_port.close()


if __name__ == "__main__":
    raise SystemExit(main())
