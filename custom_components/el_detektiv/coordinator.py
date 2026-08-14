"""El-detektiv coordinator: samples power, detects events, learns signatures.

Whole-home event detection is *silent*: a detected step is only used to count
usage on an already-known device (coincident tracked entity, or a trusted
signature match). Steps that cannot be attributed are discarded — the
integration never queues "unlabeled events" and never asks you to label them.
Learning happens through the dedicated test meter (supervised test sessions)
or `add_manual_signature`.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import timedelta, datetime

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN, STORAGE_KEY, STORAGE_VERSION,
    CONF_TOTAL_POWER, CONF_MEASURED_PLUGS, CONF_TRACKED_ENTITIES,
    CONF_STEP_THRESHOLD, CONF_SAMPLE_INTERVAL, CONF_MIN_DURATION,
    CONF_MATCH_WINDOW, CONF_TEST_METER, CONF_TEST_STEP_THRESHOLD,
    CONF_NOTIFY_SERVICE, CONF_TELEGRAM_CHAT_ID,
    DEFAULT_STEP_THRESHOLD, DEFAULT_SAMPLE_INTERVAL, DEFAULT_MIN_DURATION,
    DEFAULT_MATCH_WINDOW, DEFAULT_TEST_STEP_THRESHOLD, CONFIDENCE_TRUSTED,
    is_on_state,
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
        self.min_duration = float(opts.get(CONF_MIN_DURATION, DEFAULT_MIN_DURATION))
        interval = int(opts.get(CONF_SAMPLE_INTERVAL, DEFAULT_SAMPLE_INTERVAL))

        # Test meter (supervised learning) — optional.
        self.test_meter: str | None = opts.get(CONF_TEST_METER) or None
        self.test_step_threshold = float(
            opts.get(CONF_TEST_STEP_THRESHOLD, DEFAULT_TEST_STEP_THRESHOLD))

        # Notifications — optional (empty = dashboard only). Used only for
        # test-session status; unattributed events are never announced.
        self.notify_service: str = (opts.get(CONF_NOTIFY_SERVICE) or "").strip()
        self.telegram_chat_id: str = str(opts.get(CONF_TELEGRAM_CHAT_ID) or "").strip()

        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )

        self.detector = EventDetector(DetectorConfig(
            step_threshold=self.step_threshold,
            min_duration=self.min_duration,
        ))
        self.test_detector = EventDetector(DetectorConfig(
            step_threshold=self.test_step_threshold,
            min_duration=self.min_duration,
        ))
        self.store_engine = SignatureStore()
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._dirty = False
        # recent on/off transitions of tracked entities: (ts, entity_id, is_on)
        self._transitions: deque = deque(maxlen=200)
        self._unsub_state = None
        self._residual = None
        # test session
        self.test_label: str | None = None
        self.test_started: float | None = None

    # ---------- persistence ----------
    async def async_load(self):
        data = await self._store.async_load() or {}
        for d in data.get("signatures", []):
            self.store_engine.sigs[d["label"]] = Signature.from_dict(d)
        # Legacy stores (<= 0.7.x) also held a "pending" queue of unlabeled
        # events. That feature is gone; drop the leftovers on the next save.
        if data.get("pending"):
            _LOGGER.info(
                "El-detektiv: discarding %d legacy unlabeled events from storage",
                len(data["pending"]))
            self._dirty = True

    async def async_save(self):
        await self._store.async_save({
            "signatures": [s.to_dict() for s in self.store_engine.sigs.values()],
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

    # ---------- test session ----------
    def start_test_session(self, label: str):
        """Begin supervised learning of `label` from the dedicated test meter."""
        self.test_label = label
        self.test_started = time.time()
        # Fresh detector so a previous device's plateau can't bleed in.
        self.test_detector = EventDetector(DetectorConfig(
            step_threshold=self.test_step_threshold,
            min_duration=self.min_duration,
        ))
        self._dirty = True
        _LOGGER.info("El-detektiv test-session started for '%s'", label)

    def stop_test_session(self):
        if self.test_label:
            _LOGGER.info("El-detektiv test-session stopped ('%s')", self.test_label)
        self.test_label = None
        self.test_started = None

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

    def _attribute_event(self, ev: dict) -> str | None:
        """Silently attribute a completed whole-home event to a known device.

        Returns the label the event was counted against, or None when it could
        not be attributed — in which case the step is simply dropped. No queue,
        no notification, no labelling chore.
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

        # 1) confident auto-attribution to a coincident tracked device
        if best:
            eid = best[0]
            sig = self.store_engine.sigs.get(eid)
            if sig is not None and sig.n >= 1 and abs(delta - sig.mean) <= max(sig.std * 3, 80):
                self.store_engine.add_sample(eid, delta, ev["duration_s"], hour, ev["t_end"])
                self._dirty = True
                _LOGGER.debug("El-detektiv auto-labeled %.0fW -> %s", delta, eid)
                return eid

        # 2) trusted-signature auto-match: a well-learned device (typically
        #    taught through a test session) gets this run counted.
        m = self.store_engine.match(delta, ev["duration_s"], hour)
        if m:
            sig = self.store_engine.sigs.get(m[0])
            if sig is not None and sig.confidence == CONFIDENCE_TRUSTED and m[1] >= 0.6:
                self.store_engine.add_sample(m[0], delta, ev["duration_s"], hour, ev["t_end"])
                self._dirty = True
                _LOGGER.debug("El-detektiv auto-matched %.0fW -> %s (trusted)", delta, m[0])
                return m[0]

        # 3) unknown step — deliberately ignored.
        _LOGGER.debug("El-detektiv: unattributed %.0fW step (%.0fs) ignored",
                      delta, ev["duration_s"])
        return None

    # ---------- notifications ----------
    def _notify_text(self, message: str):
        """Send a status line (test session learned/finished). Optional."""
        if self.telegram_chat_id:
            self.hass.async_create_task(self._tg_send(message))
        elif self.notify_service:
            self.hass.async_create_task(self._simple_send(message))

    async def _tg_send(self, message: str):
        try:
            await self.hass.services.async_call("telegram_bot", "send_message", {
                "message": message, "chat_id": int(self.telegram_chat_id),
                "parse_mode": "markdown",
            }, blocking=True)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.warning("El-detektiv: telegram send failed (%s)", err)

    async def _simple_send(self, message: str):
        svc = self.notify_service
        if not svc:
            return
        domain, _, service = svc.partition(".")
        if not service:
            domain, service = "notify", svc
        try:
            await self.hass.services.async_call(
                domain, service, {"message": message}, blocking=False)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.warning("El-detektiv: notify '%s' failed (%s)", svc, err)

    # ---------- main loop ----------
    async def _async_update_data(self):
        total = _to_float(self.hass, self.total_power)
        if total is not None:
            plug_sum = sum(
                (_to_float(self.hass, p) or 0.0) for p in self.measured_plugs)
            # The test meter is an isolated, measured load — always subtract it
            # from the whole-home residual so whatever you're testing never also
            # shows up as an "unexplained" house event. No manual measured-plugs
            # entry needed.
            if self.test_meter and self.test_meter not in self.measured_plugs:
                plug_sum += (_to_float(self.hass, self.test_meter) or 0.0)
            residual_for_detector = total - plug_sum
            ev = self.detector.feed(time.time(), residual_for_detector)
            if ev:
                self._attribute_event(ev)
            self._residual = max(0.0, residual_for_detector
                                 - self._active_tracked_signature_sum())

        # Supervised learning from the dedicated test meter while a session runs.
        if self.test_meter and self.test_label:
            tp = _to_float(self.hass, self.test_meter)
            if tp is not None:
                tev = self.test_detector.feed(time.time(), tp)
                if tev:
                    hour = datetime.fromtimestamp(tev["t_start"]).hour
                    sig = self.store_engine.add_sample(
                        self.test_label, tev["delta_w"], tev["duration_s"],
                        hour, tev["t_end"])
                    self._dirty = True
                    _LOGGER.info(
                        "El-detektiv test-session '%s': +%.0fW sample (n=%d, %s)",
                        self.test_label, tev["delta_w"], sig.n, sig.confidence)
                    if sig.confidence == CONFIDENCE_TRUSTED:
                        done = self.test_label
                        self.stop_test_session()
                        self._notify_text(
                            f"✅ El-detektiv har lært *{done}* (høj tillid) "
                            f"— test-session afsluttet.")

        if self._dirty:
            self.hass.async_create_task(self.async_save())

        return {
            "residual": self._residual,
            "baseline": self.detector.baseline,
            "signatures": [s.to_dict() for s in self.store_engine.sigs.values()],
            "test_label": self.test_label,
            "test_started": self.test_started,
        }

    # ---------- service handlers ----------
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
