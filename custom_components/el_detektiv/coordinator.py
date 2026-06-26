"""El-detektiv coordinator: samples power, detects events, learns signatures."""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from datetime import timedelta, datetime

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN, STORAGE_KEY, STORAGE_VERSION, EVENT_DETECTED, MAX_PENDING,
    CONF_TOTAL_POWER, CONF_MEASURED_PLUGS, CONF_TRACKED_ENTITIES,
    CONF_STEP_THRESHOLD, CONF_SAMPLE_INTERVAL, CONF_MIN_DURATION,
    CONF_MATCH_WINDOW, DEFAULT_STEP_THRESHOLD, DEFAULT_SAMPLE_INTERVAL,
    DEFAULT_MIN_DURATION, DEFAULT_MATCH_WINDOW, is_on_state,
)
from .nilm_core import EventDetector, DetectorConfig, SignatureStore, Signature

_LOGGER = logging.getLogger(__name__)


def _to_float(hass: HomeAssistant, entity_id: str):
    st = hass.states.get(entity_id)
    if st is None or st.state in ("unknown", "unavailable", "", None):
        return None
    try:
        return float(st.state)
    except (ValueError, TypeError):
        return None


class ElDetektivCoordinator(DataUpdateCoordinator):
    """Polls every sample_interval; feeds the NILM engine; exposes a snapshot."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        opts = {**entry.data, **entry.options}
        self.entry = entry
        self.total_power: str = opts[CONF_TOTAL_POWER]
        self.measured_plugs: list[str] = list(opts.get(CONF_MEASURED_PLUGS, []))
        self.tracked: list[str] = list(opts.get(CONF_TRACKED_ENTITIES, []))
        self.step_threshold = float(opts.get(CONF_STEP_THRESHOLD, DEFAULT_STEP_THRESHOLD))
        self.match_window = float(opts.get(CONF_MATCH_WINDOW, DEFAULT_MATCH_WINDOW))
        interval = int(opts.get(CONF_SAMPLE_INTERVAL, DEFAULT_SAMPLE_INTERVAL))

        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )

        self.detector = EventDetector(DetectorConfig(
            step_threshold=self.step_threshold,
            min_duration=float(opts.get(CONF_MIN_DURATION, DEFAULT_MIN_DURATION)),
        ))
        self.store_engine = SignatureStore()
        self.pending: list[dict] = []
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._dirty = False
        # recent on/off transitions of tracked entities: (ts, entity_id, is_on)
        self._transitions: deque = deque(maxlen=200)
        self._unsub_state = None
        self._residual = None

    # ---------- persistence ----------
    async def async_load(self):
        data = await self._store.async_load() or {}
        for d in data.get("signatures", []):
            self.store_engine.sigs[d["label"]] = Signature.from_dict(d)
        self.pending = data.get("pending", [])

    async def async_save(self):
        await self._store.async_save({
            "signatures": [s.to_dict() for s in self.store_engine.sigs.values()],
            "pending": self.pending,
        })
        self._dirty = False

    # ---------- lifecycle ----------
    async def async_start(self):
        await self.async_load()
        if self.tracked:
            self._unsub_state = async_track_state_change_event(
                self.hass, self.tracked, self._on_tracked_change
            )

    async def async_stop(self):
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        if self._dirty:
            await self.async_save()

    @callback
    def _on_tracked_change(self, event: Event):
        new = event.data.get("new_state")
        if new is None:
            return
        self._transitions.append((time.time(), event.data["entity_id"], is_on_state(new.state)))

    # ---------- helpers ----------
    def _active_tracked_signature_sum(self) -> float:
        total = 0.0
        for eid in self.tracked:
            st = self.hass.states.get(eid)
            if st and is_on_state(st.state):
                sig = self.store_engine.sigs.get(eid)
                if sig:
                    total += sig.mean
        return total

    def _attribute_event(self, ev: dict):
        """Decide if a completed event belongs to a tracked device or is unknown.

        Auto-attribution is intentionally conservative: a coincident device
        state-change is only trusted when that device ALREADY has a signature
        whose magnitude matches this event. A bare coincidence (e.g. a TV going
        to "playing" near a 2 kW kettle spike) must not silently mislabel — it
        is queued for the user with the device offered as a low-confidence
        suggestion instead.
        """
        t0 = ev["t_start"]
        delta = ev["delta_w"]
        hour = datetime.fromtimestamp(ev["t_start"]).hour

        # nearest coincident ON-transition of a tracked entity
        best = None
        for (ts, eid, is_on) in list(self._transitions):
            if is_on and abs(ts - t0) <= self.match_window:
                d = abs(ts - t0)
                if best is None or d < best[1]:
                    best = (eid, d)

        # confident auto-attribution: device already has a matching signature
        if best:
            eid = best[0]
            sig = self.store_engine.sigs.get(eid)
            if sig is not None and sig.n >= 1 and abs(delta - sig.mean) <= max(sig.std * 3, 80):
                self.store_engine.add_sample(eid, delta, ev["duration_s"], hour, ev["t_end"])
                self._dirty = True
                _LOGGER.debug("El-detektiv auto-labeled %.0fW -> %s", delta, eid)
                return

        # otherwise queue it; suggest the best learned match, else the
        # coincident device (low confidence) so the user can confirm/correct.
        suggestion, score = None, None
        m = self.store_engine.match(delta, ev["duration_s"], hour)
        if m:
            suggestion, score = m
        elif best:
            st = self.hass.states.get(best[0])
            suggestion = (st.attributes.get("friendly_name") if st else None) or best[0]
            score = None

        item = {
            "id": uuid.uuid4().hex[:8],
            "t_start": ev["t_start"], "t_end": ev["t_end"],
            "delta_w": delta, "duration_s": ev["duration_s"],
            "hour": hour,
            "suggestion": suggestion,
            "suggestion_score": score,
        }
        self.pending.insert(0, item)
        self.pending = self.pending[:MAX_PENDING]
        self._dirty = True
        self.hass.bus.async_fire(EVENT_DETECTED, item)

    # ---------- main loop ----------
    async def _async_update_data(self):
        total = _to_float(self.hass, self.total_power)
        if total is not None:
            plug_sum = sum(
                (_to_float(self.hass, p) or 0.0) for p in self.measured_plugs)
            residual_for_detector = total - plug_sum
            ev = self.detector.feed(time.time(), residual_for_detector)
            if ev:
                self._attribute_event(ev)
            self._residual = max(0.0, residual_for_detector
                                 - self._active_tracked_signature_sum())

        if self._dirty:
            self.hass.async_create_task(self.async_save())

        return {
            "residual": self._residual,
            "baseline": self.detector.baseline,
            "signatures": [s.to_dict() for s in self.store_engine.sigs.values()],
            "pending": list(self.pending),
        }

    # ---------- service handlers ----------
    def label_event(self, event_id: str, label: str):
        item = self._pop_pending(event_id)
        if not item:
            return
        self.store_engine.add_sample(
            label, item["delta_w"], item["duration_s"], item.get("hour"),
            item["t_end"])
        self._dirty = True

    def confirm_suggestion(self, event_id: str):
        item = next((p for p in self.pending if p["id"] == event_id), None)
        if item and item.get("suggestion"):
            self.label_event(event_id, item["suggestion"])

    def dismiss_event(self, event_id: str):
        self._pop_pending(event_id)
        self._dirty = True

    def delete_signature(self, label: str):
        self.store_engine.sigs.pop(label, None)
        self._dirty = True

    def rename_signature(self, label: str, new_label: str):
        sig = self.store_engine.sigs.pop(label, None)
        if sig:
            sig.label = new_label
            self.store_engine.sigs[new_label] = sig
            self._dirty = True

    def add_manual_signature(self, label: str, watt: float, duration=None):
        self.store_engine.add_sample(label, float(watt), duration)
        self._dirty = True

    def _pop_pending(self, event_id: str):
        for i, p in enumerate(self.pending):
            if p["id"] == event_id:
                return self.pending.pop(i)
        return None
