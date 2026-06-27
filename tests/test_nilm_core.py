"""Standalone unit tests for the El-detektiv NILM core.

Focus: baseline robustness. These reproduce the regression where a baseline
seeded too low left the detector permanently "in an event" and blind to new
steps (kettles undetected until a manual reload).

Run: ``pytest tests/`` (no Home Assistant needed — nilm_core is pure Python).
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "el_detektiv"))

from nilm_core import EventDetector, DetectorConfig  # noqa: E402


def _run(detector, samples, step=10):
    """Feed values spaced ``step`` seconds apart; return the events fired."""
    fired = []
    t = 0.0
    for v in samples:
        ev = detector.feed(t, float(v))
        if ev:
            fired.append(ev)
        t += step
    return fired


def test_kettle_after_warmup_is_detected():
    """A clear ~2 kW excursion on a settled floor yields exactly one event."""
    d = EventDetector(DetectorConfig(step_threshold=120, min_duration=20))
    samples = ([520] * 15
               + [2700, 2705, 2695, 2710, 2700, 2698]  # ~60 s kettle
               + [521, 519, 520, 520])
    fired = _run(d, samples)
    assert len(fired) == 1
    assert fired[0]["delta_w"] > 2000
    assert fired[0]["duration_s"] >= 20


def test_low_init_sample_does_not_lock_baseline():
    """Regression: one low reading at startup must not pin the baseline.

    Previously this left the detector stuck open and blind; now warm-up
    (median of the first N samples) keeps the baseline on the real floor.
    """
    d = EventDetector(DetectorConfig(step_threshold=120, min_duration=20))
    _run(d, [78] + [520] * 20)
    assert d.baseline is not None
    assert abs(d.baseline - 520) < 120
    fired = _run(d, [2700] * 6 + [520, 520, 520])
    assert len(fired) == 1
    assert fired[0]["delta_w"] > 2000


def test_self_heal_unsticks_a_low_baseline():
    """A baseline forced far below the floor must self-heal and detect again."""
    d = EventDetector(DetectorConfig(
        step_threshold=120, min_duration=20, rebaseline_after=300))
    d._baseline = 78.0  # pathological: stuck far below the ~520 W floor
    _run(d, [520] * 60)  # 600 s > rebaseline_after -> must re-sync
    assert abs(d.baseline - 520) < 120
    fired = _run(d, [2700] * 6 + [520, 520, 520])
    assert len(fired) == 1


def test_steady_floor_produces_no_events():
    """A flat floor must not generate false positives."""
    d = EventDetector(DetectorConfig(step_threshold=120, min_duration=20))
    assert _run(d, [520] * 80) == []
