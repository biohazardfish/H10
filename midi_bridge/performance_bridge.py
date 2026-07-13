#!/usr/bin/env python3
"""H10 V4 body-narrative JSONL -> MIDI performance bridge.

The validated V3 bridge remains untouched.  This module adds personalised
calibration, RR artifact rejection, ACC-derived movement features, an ordered
five-scene state machine, and optional MiniLab 3 safety controls.
"""

from __future__ import annotations

import argparse
import collections
import enum
import json
import math
import queue
import selectors
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Deque, Iterable

import bridge as core


DEFAULT_CONFIG = Path(__file__).with_name("performance_mapping.json")


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def finite(value: Any) -> float | None:
    return core.finite_float(value)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def normalize(value: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return clamp((value - lo) / (hi - lo))


def smoothstep(value: float) -> float:
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


def log_normalize(value: float, lo: float, hi: float) -> float:
    linear = normalize(value, lo, hi)
    return math.log1p(linear * 9.0) / math.log(10.0)


def vector_unit(values: Iterable[Any]) -> tuple[float, float, float] | None:
    converted = [finite(value) for value in values]
    if len(converted) != 3 or any(value is None for value in converted):
        return None
    vector = tuple(float(value) for value in converted if value is not None)
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 1e-9:
        return None
    return tuple(value / magnitude for value in vector)  # type: ignore[return-value]


def angle_degrees(a: Iterable[Any], b: Iterable[Any]) -> float | None:
    left = vector_unit(a)
    right = vector_unit(b)
    if left is None or right is None:
        return None
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(left, right))))
    return math.degrees(math.acos(dot))


def calculate_rmssd(values: Iterable[float]) -> float | None:
    values = tuple(values)
    if len(values) < 2:
        return None
    return math.sqrt(
        sum((values[index] - values[index - 1]) ** 2 for index in range(1, len(values)))
        / (len(values) - 1)
    )


def calculate_sdnn(values: Iterable[float]) -> float | None:
    values = tuple(values)
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def event_time(event: dict[str, Any], fallback: float | None = None) -> float:
    value = finite(event.get("t_monotonic_s"))
    if value is not None:
        return value
    return time.monotonic() if fallback is None else fallback


class Scene(enum.IntEnum):
    LYING_OPEN = 0
    RISING = 1
    DANCE = 2
    SITTING_RETURN = 3
    LYING_FINAL = 4


SCENE_NAMES = {
    Scene.LYING_OPEN: "lying_open",
    Scene.RISING: "rising",
    Scene.DANCE: "dance",
    Scene.SITTING_RETURN: "sitting_return",
    Scene.LYING_FINAL: "lying_final",
}


class RRArtifactFilter:
    """Reject impossible, BPM-inconsistent, and rolling-median RR artifacts."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.min_ms = float(config.get("min_ms", 270.0))
        self.max_ms = float(config.get("max_ms", 2000.0))
        self.bpm_fraction = float(config.get("bpm_tolerance_fraction", 0.15))
        self.bpm_min_ms = float(config.get("bpm_tolerance_min_ms", 40.0))
        self.median_fraction = float(config.get("rolling_median_fraction", 0.30))
        history_size = int(config.get("history_size", 20))
        self.history: Deque[float] = collections.deque(maxlen=max(5, history_size))
        self.rejected = 0

    def accept(self, rr_value: Any, bpm_value: Any) -> float | None:
        rr = finite(rr_value)
        bpm = finite(bpm_value)
        if rr is None or rr < self.min_ms or rr > self.max_ms:
            self.rejected += 1
            return None
        if bpm is not None and 30.0 <= bpm <= 240.0:
            expected = 60000.0 / bpm
            tolerance = max(self.bpm_min_ms, expected * self.bpm_fraction)
            if abs(rr - expected) > tolerance:
                self.rejected += 1
                return None
        if len(self.history) >= 5:
            median = statistics.median(self.history)
            if abs(rr - median) > median * self.median_fraction:
                self.rejected += 1
                return None
        self.history.append(rr)
        return rr


class AsymmetricSmoother:
    def __init__(self, attack_seconds: float, release_seconds: float, initial: float = 0.0) -> None:
        self.attack_seconds = max(0.001, float(attack_seconds))
        self.release_seconds = max(0.001, float(release_seconds))
        self.value = float(initial)

    def update(
        self,
        target: float,
        dt_seconds: float,
        release_seconds_override: float | None = None,
    ) -> float:
        target = clamp(target)
        dt_seconds = clamp(float(dt_seconds), 0.0, 1.0)
        release_seconds = (
            self.release_seconds
            if release_seconds_override is None
            else max(0.001, float(release_seconds_override))
        )
        tau = self.attack_seconds if target >= self.value else release_seconds
        coefficient = 1.0 - math.exp(-dt_seconds / tau)
        self.value += coefficient * (target - self.value)
        return self.value


class PerformanceMidiSink(core.MidiSink):
    """V3's reliable sink plus a persistent gate and non-closing panic."""

    def __init__(self, dry_run: bool, port_name: str | None, virtual: bool = False) -> None:
        super().__init__(dry_run=dry_run, port_name=port_name, virtual=virtual)
        self.gate_value: int | None = None

    def send_gate(self, active: bool, force: bool = False) -> None:
        value = 127 if active else 0
        if not force and self.gate_value == value:
            return
        self.gate_value = value
        self.send_cc(1, 119, value, {"source": "performance_gate"})

    def panic(self) -> None:
        self.send_gate(False, force=True)
        meta = {"source": "panic"}
        for channel, note in sorted(self.active_notes):
            self.send_note_off(channel, note, 0, meta)
        self.active_notes.clear()
        for channel in sorted(self.used_channels | {1, 10}):
            self.send_cc(channel, core.CC_ALL_NOTES_OFF, 0, meta)

    def close(self) -> None:
        if self._closed:
            return
        self.send_gate(False)
        super().close()


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        config = json.load(stream)
    required = {
        "calibration", "rr_filter", "ranges", "state_machine", "dropout", "midi", "smoothing"
    }
    missing = required - set(config)
    if config.get("version") != 4 or missing:
        raise ValueError(f"invalid V4 performance config; missing={sorted(missing)}")
    signals = config["midi"].get("signals", {})
    expected_signals = {
        "arousal", "regulation", "motion", "uprightness", "pulse_gap",
        "fluidity", "rotation", "stillness",
    }
    if set(signals) != expected_signals:
        raise ValueError("performance config MIDI signal contract is incomplete")
    for cc in signals.values():
        if not isinstance(cc, int) or not 0 <= cc <= 127:
            raise ValueError(f"invalid MIDI CC: {cc!r}")
    return config


class PerformanceEngine:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.calibration_config = config["calibration"]
        self.ranges = config["ranges"]
        self.state_config = config["state_machine"]
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

        self.scene = Scene.LYING_OPEN
        self.scene_entered_at = 0.0
        self.condition_started: dict[str, float] = {}
        self.manual_mode = False
        self.panic_latched = False
        self.recalibrate_pressed_at: float | None = None

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
            "scene": 0.0,
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

    def reset_calibration(self, now: float) -> None:
        self.calibrated = False
        self.baseline_gravity = None
        self.stable_started_at = None
        self.calibration_gravity.clear()
        self.calibration_bpms.clear()
        self.calibration_rrs.clear()
        self.scene = Scene.LYING_OPEN
        self.scene_entered_at = now
        self.condition_started.clear()
        self.manual_mode = False
        self.targets["uprightness"] = 0.0
        self.targets["scene"] = 0.0
        eprint("V4 calibration reset; lie still for 10 seconds.")

    def _set_scene(self, scene: Scene, now: float, source: str) -> None:
        if scene == self.scene:
            return
        self.scene = scene
        self.scene_entered_at = now
        self.condition_started.clear()
        scene_values = self.midi_config.get("scene_values", [0, 32, 64, 96, 127])
        self.targets["scene"] = float(scene_values[int(scene)]) / 127.0
        eprint(f"V4 scene -> {SCENE_NAMES[scene]} ({source})")

    def _condition_held(self, key: str, condition: bool, hold_seconds: float, now: float) -> bool:
        if not condition:
            self.condition_started.pop(key, None)
            return False
        started = self.condition_started.setdefault(key, now)
        return now - started >= hold_seconds

    def _advance_scene(self, now: float) -> None:
        if self.manual_mode or not self.calibrated or not self.motion_available:
            return
        motion = self.targets["motion"]
        upright = self.targets["uprightness"]
        cfg = self.state_config

        if self.scene == Scene.LYING_OPEN:
            if self._condition_held(
                "rise",
                upright > float(cfg["rise_uprightness"]),
                float(cfg["rise_hold_seconds"]),
                now,
            ):
                self._set_scene(Scene.RISING, now, "auto")
        elif self.scene == Scene.RISING:
            eligible = now - self.scene_entered_at >= float(cfg["minimum_rise_seconds"])
            if self._condition_held(
                "dance",
                eligible and motion > float(cfg["dance_motion"]),
                float(cfg["dance_hold_seconds"]),
                now,
            ):
                self._set_scene(Scene.DANCE, now, "auto")
        elif self.scene == Scene.DANCE:
            if self._condition_held(
                "settle",
                motion < float(cfg["settle_motion"])
                and upright > float(cfg["settle_uprightness"]),
                float(cfg["settle_hold_seconds"]),
                now,
            ):
                self._set_scene(Scene.SITTING_RETURN, now, "auto")
        elif self.scene == Scene.SITTING_RETURN:
            if self._condition_held(
                "final",
                motion < float(cfg["settle_motion"])
                and upright < float(cfg["final_uprightness"]),
                float(cfg["final_hold_seconds"]),
                now,
            ):
                self._set_scene(Scene.LYING_FINAL, now, "auto")

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
                    eprint("V4 calibration started; remain lying still.")
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
                    self.scene = Scene.LYING_OPEN
                    self.scene_entered_at = now
                    self.targets["scene"] = 0.0
                    eprint(
                        "V4 calibration complete: "
                        f"baseline_bpm={self.baseline_bpm:.1f} "
                        f"baseline_rr={self.baseline_rr:.1f}"
                    )
            else:
                if self.stable_started_at is not None:
                    eprint("V4 calibration paused: movement exceeded stillness threshold.")
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
            self._advance_scene(now)

    def handle_status(self, event: dict[str, Any]) -> None:
        if "motion_available" in event:
            self.motion_available = bool(event["motion_available"])
        if "heart_available" in event:
            self.heart_available = bool(event["heart_available"])

    def handle_control(self, message: Any, sink: PerformanceMidiSink, now: float) -> None:
        if getattr(message, "channel", -1) + 1 != 3:
            return
        message_type = getattr(message, "type", "")
        note = int(getattr(message, "note", -1))
        velocity = int(getattr(message, "velocity", 0))
        is_on = message_type == "note_on" and velocity > 0
        is_off = message_type == "note_off" or (message_type == "note_on" and velocity == 0)

        if is_on and 36 <= note <= 40:
            self.panic_latched = False
            sink.send_gate(True, force=True)
            self.manual_mode = True
            self._set_scene(Scene(note - 36), now, "MiniLab manual")
        elif is_on and note == 41:
            self.panic_latched = False
            sink.send_gate(True, force=True)
            self.manual_mode = False
            self.condition_started.clear()
            eprint(f"V4 AUTO resumed from {SCENE_NAMES[self.scene]}")
        elif is_on and note == 42:
            self.recalibrate_pressed_at = now
        elif is_off and note == 42:
            if self.recalibrate_pressed_at is not None and now - self.recalibrate_pressed_at >= 2.0:
                self.reset_calibration(now)
            self.recalibrate_pressed_at = None
        elif is_on and note == 43:
            self.panic_latched = True
            sink.panic()
            eprint("V4 PANIC latched; press Pad 6/AUTO or a scene pad to resume.")

    def _schedule_heartbeat(self, sink: PerformanceMidiSink, velocity: int, now: float) -> None:
        if self.panic_latched:
            return
        channel = int(self.midi_config["heartbeat_channel"])
        note = int(self.midi_config["heartbeat_note"])
        meta = {"source": "heartbeat", "scene": SCENE_NAMES[self.scene]}
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
        for name, smoother in self.smoothers.items():
            dropout_release = None
            if name == "arousal" and not self.heart_available:
                dropout_release = float(
                    self.dropout_config["heart_arousal_release_seconds"]
                )
            values[name] = smoother.update(
                self.targets.get(name, 0.0),
                dt_seconds,
                release_seconds_override=dropout_release,
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
                eprint("V4 heartbeat and motion unavailable; performance gate faded out.")
            return

        self.all_signals_lost_at = None
        if self.outage_gate_closed:
            self.outage_gate_closed = False
            self.last_snapshot_at = None
            if not self.panic_latched:
                sink.send_gate(True, force=True)
                eprint("V4 signal recovered; performance gate restored.")

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
                sink.send_cc(
                    channel,
                    int(cc),
                    midi_value,
                    {"source": name, "scene": SCENE_NAMES[self.scene]},
                )
        scene_cc = int(self.midi_config["scene_cc"])
        scene_value = int(round(clamp(values.get("scene", 0.0)) * 127.0))
        if force or refresh_snapshot or self.last_midi_values.get(scene_cc) != scene_value:
            self.last_midi_values[scene_cc] = scene_value
            sink.send_cc(
                channel,
                scene_cc,
                scene_value,
                {"source": "scene", "scene": SCENE_NAMES[self.scene]},
            )

    def _diagnostics(self, now: float, values: dict[str, float]) -> None:
        if now - self.last_diag_at < 1.0:
            return
        self.last_diag_at = now
        calibration = "ready" if self.calibrated else "waiting"
        eprint(
            "V4 diag "
            f"scene={SCENE_NAMES[self.scene]} mode={'manual' if self.manual_mode else 'auto'} "
            f"cal={calibration} bpm={self.latest_bpm if self.latest_bpm is not None else '-'} "
            f"arousal={values.get('arousal', 0):.2f} motion={values.get('motion', 0):.2f} "
            f"upright={values.get('uprightness', 0):.2f} "
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
        eprint(f"Invalid V4 JSONL event: {exc}")
        return None
    if not isinstance(event, dict):
        eprint("V4 JSONL event must be an object")
        return None
    return event


def run_stream(
    config: dict[str, Any],
    sink: PerformanceMidiSink,
    stream: Any,
    control_queue: queue.Queue | None = None,
) -> int:
    engine = PerformanceEngine(config)

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
        eprint("V4 interrupted; fading performance gate and releasing MIDI.")
        return 0
    finally:
        engine.shutdown(sink)
        sink.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H10 V4 body-narrative MIDI bridge")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--virtual", action="store_true")
    parser.add_argument("--port", default="H10 Performance V4")
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
            eprint(f"MiniLab control unavailable ({exc}); body-auto mode remains active.")
            control_messages = None

    try:
        return run_stream(config, sink, sys.stdin, control_messages)
    finally:
        if control_port is not None:
            control_port.close()


if __name__ == "__main__":
    raise SystemExit(main())
