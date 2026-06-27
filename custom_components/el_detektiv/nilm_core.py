"""NILM core engine — pure-Python, no Home Assistant dependencies.

Event detection over a residual-power stream, plus an online signature
store (Welford running mean/variance) with tolerant matching that copes
with appliances whose draw varies from run to run (kettle, iron, vacuum).

This module is unit-tested standalone, then imported by the Home Assistant
custom integration's coordinator.
"""
from __future__ import annotations
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


class Signature:
    """Running statistics for one labelled appliance, via Welford."""

    def __init__(self, label: str):
        self.label = label
        self.n = 0
        self.mean = 0.0
        self._m2 = 0.0
        self.dur_n = 0
        self.dur_mean = 0.0
        self.hours = [0] * 24
        self.last_ts: Optional[float] = None
        self.runs: list = []

    MAX_RUNS = 1500

    def add(self, watt: float, dur: Optional[float] = None,
            hour: Optional[int] = None, ts: Optional[float] = None) -> None:
        self.n += 1
        d = watt - self.mean
        self.mean += d / self.n
        self._m2 += d * (watt - self.mean)
        if dur is not None:
            self.dur_n += 1
            self.dur_mean += (dur - self.dur_mean) / self.dur_n
        if hour is not None:
            self.hours[hour % 24] += 1
        if ts is not None:
            self.last_ts = ts
        if ts is not None and dur:
            self.runs.append([int(ts), round(watt * dur / 3600.0, 1)])
            if len(self.runs) > self.MAX_RUNS:
                self.runs = self.runs[-self.MAX_RUNS:]

    @property
    def std(self) -> float:
        if self.n < 2:
            return max(self.mean * 0.20, 50.0)
        return math.sqrt(self._m2 / (self.n - 1))

    @property
    def confidence(self) -> str:
        cv = (self.std / self.mean) if self.mean else 1.0
        if self.n >= 6 and cv < 0.25:
            return "hoej"
        if self.n >= 3:
            return "middel"
        return "lav"

    def to_dict(self) -> dict:
        return {
            "label": self.label, "n": self.n, "mean": round(self.mean, 1),
            "std": round(self.std, 1), "dur_mean": round(self.dur_mean, 1),
            "hours": self.hours, "last_ts": self.last_ts,
            "confidence": self.confidence, "_m2": self._m2, "dur_n": self.dur_n,
            "runs": self.runs,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Signature":
        s = cls(d["label"])
        s.n = d.get("n", 0)
        s.mean = d.get("mean", 0.0)
        s._m2 = d.get("_m2", 0.0)
        s.dur_n = d.get("dur_n", 0)
        s.dur_mean = d.get("dur_mean", 0.0)
        s.hours = d.get("hours", [0] * 24)
        s.last_ts = d.get("last_ts")
        s.runs = d.get("runs", [])
        return s


class SignatureStore:
    def __init__(self):
        self.sigs: dict[str, Signature] = {}

    def add_sample(self, label: str, watt: float, dur=None, hour=None, ts=None):
        sig = self.sigs.get(label)
        if sig is None:
            sig = self.sigs[label] = Signature(label)
        sig.add(watt, dur, hour, ts)
        return sig

    def match(self, watt: float, dur=None, hour=None, k: float = 3.0,
              min_tol: float = 80.0) -> Optional[tuple[str, float]]:
        best = None
        for sig in self.sigs.values():
            if sig.n < 1:
                continue
            band = max(sig.std * k, min_tol)
            dw = abs(watt - sig.mean)
            if dw > band:
                continue
            score = 1.0 - dw / band
            if dur is not None and sig.dur_mean > 0:
                dr = abs(dur - sig.dur_mean) / max(sig.dur_mean, 1.0)
                score -= min(0.25, dr * 0.25)
            if hour is not None and sum(sig.hours) > 0:
                frac = sig.hours[hour % 24] / sum(sig.hours)
                score += min(0.15, frac)
            if best is None or score > best[1]:
                best = (sig.label, round(max(0.0, min(1.0, score)), 3))
        return best


@dataclass
class DetectorConfig:
    step_threshold: float = 120.0
    confirm: int = 2
    baseline_window: int = 12
    min_duration: float = 20.0
    max_duration: float = 6 * 3600
    # An event still open after this many seconds is treated as a mis-seeded
    # baseline (the steady floor reads as a permanent "on") and is abandoned so
    # the detector re-syncs instead of staying blind forever.
    rebaseline_after: float = 1800.0


@dataclass
class _Open:
    t_start: float
    level_before: float
    plateau: list = field(default_factory=list)


class EventDetector:
    """Feed (timestamp, residual_power); get back completed ON-run events.

    Baseline robustness: the idle baseline is seeded from a *median of the
    first ``baseline_window`` samples* (never a single reading), and an event
    that stays open longer than ``rebaseline_after`` is abandoned and the
    baseline re-synced to the current level. Together these guarantee that a
    bad startup reading can never pin the baseline below the real floor and
    leave the detector permanently "in an event" (blind to new steps).
    """

    def __init__(self, cfg: DetectorConfig = DetectorConfig()):
        self.cfg = cfg
        self._base = deque(maxlen=cfg.baseline_window)
        self._baseline = None
        self._open: Optional[_Open] = None
        self._above = 0
        self._below = 0

    @property
    def baseline(self):
        return self._baseline

    def _median(self, seq):
        s = sorted(seq)
        n = len(s)
        if n == 0:
            return 0.0
        m = n // 2
        return s[m] if n % 2 else (s[m - 1] + s[m]) / 2

    def feed(self, t: float, residual: float) -> Optional[dict]:
        cfg = self.cfg

        # Warm-up: establish the baseline from a median of the first N samples,
        # never a single reading. A lone low/high sample at startup (e.g. just
        # after a reload) must not lock the baseline far from the real floor —
        # that used to leave the detector permanently "in an event" and blind.
        if self._baseline is None:
            self._base.append(residual)
            if len(self._base) >= cfg.baseline_window:
                self._baseline = self._median(self._base)
            return None

        if self._open is None:
            if residual > self._baseline + cfg.step_threshold:
                self._above += 1
                if self._above >= cfg.confirm:
                    self._open = _Open(t_start=t, level_before=self._baseline)
                    self._open.plateau.append(residual)
                    self._above = 0
            else:
                self._above = 0
                self._base.append(residual)
                self._baseline = self._median(self._base)
            return None

        op = self._open
        op.plateau.append(residual)
        if residual < op.level_before + cfg.step_threshold * 0.5:
            self._below += 1
        else:
            self._below = 0
        ended = self._below >= cfg.confirm
        runaway = (t - op.t_start) >= cfg.max_duration

        # Self-heal: an event open far longer than any real transient
        # (kettle/iron/vacuum are minutes) almost always means the baseline was
        # seeded too low, so the steady floor reads as a permanent "on".
        # Abandon it without emitting and re-baseline to the current level, so
        # the detector never stays blind. A genuinely long load simply becomes
        # the new baseline and is picked up again on its next change.
        if not ended and (t - op.t_start) >= cfg.rebaseline_after:
            level_now = self._median(op.plateau[-cfg.baseline_window:])
            self._open = None
            self._below = 0
            self._base.clear()
            self._base.append(level_now)
            self._baseline = level_now
            return None

        if ended or runaway:
            dur = t - op.t_start
            body = op.plateau[:-cfg.confirm] if ended else op.plateau
            level_high = self._median(body) if body else self._median(op.plateau)
            delta = level_high - op.level_before
            self._open = None
            self._below = 0
            self._base.clear()
            # Clean end -> the floor returns to the prior level. Runaway (still
            # on after max_duration) -> re-baseline to the current level so a
            # never-closing load can't re-lock the detector.
            seed = (op.level_before if ended
                    else self._median(op.plateau[-cfg.baseline_window:]))
            self._base.append(seed)
            self._baseline = seed
            if dur >= cfg.min_duration and delta >= cfg.step_threshold:
                return {
                    "t_start": op.t_start, "t_end": t,
                    "delta_w": round(delta, 1), "duration_s": round(dur, 1),
                }
        return None
