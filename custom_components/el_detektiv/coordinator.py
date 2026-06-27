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

        # Notifications — optional (empty = dashboard only).
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
        self.pending: list[dict] = []
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._dirty = False
        # recent on/off transitions of tracked entities: (ts, entity_id, is_on)
        self._transitions: deque = deque(maxlen=200)
        self._unsub_state = None
        self._unsub_tg_cb = None
        self._unsub_tg_txt = None
        self._residual = None
        # test session
        self.test_label: str | None = None
        self.test_started: float | None = None
        # telegram: event_id we're awaiting a free-text name reply for
        self._awaiting: str | None = None

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
        # Interactive Telegram: listen for button taps and free-text replies.
        if self.telegram_chat_id:
            self._unsub_tg_cb = self.hass.bus.async_listen(
                "telegram_callback", self._on_tg_callback)
            self._unsub_tg_txt = self.hass.bus.async_listen(
                "telegram_text", self._on_tg_text)

    async def async_stop(self):
        for unsub in (self._unsub_state, self._unsub_tg_cb, self._unsub_tg_txt):
            if unsub:
                unsub()
        self._unsub_state = self._unsub_tg_cb = self._unsub_tg_txt = None
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

    def _attribute_event(self, ev: dict):
        """Decide a completed event: auto-attribute, auto-match, or queue."""
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
                return

        # 2) trusted-signature silent auto-match: once a device is well learned
        #    (high confidence), stop bothering the user — just count it.
        m = self.store_engine.match(delta, ev["duration_s"], hour)
        if m:
            sig = self.store_engine.sigs.get(m[0])
            if sig is not None and sig.confidence == CONFIDENCE_TRUSTED and m[1] >= 0.6:
                self.store_engine.add_sample(m[0], delta, ev["duration_s"], hour, ev["t_end"])
                self._dirty = True
                _LOGGER.debug("El-detektiv auto-matched %.0fW -> %s (trusted)", delta, m[0])
                return

        # 3) otherwise queue it; suggest the best learned match, else the
        #    coincident device (low confidence) so the user can confirm/correct.
        suggestion, score = None, None
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
        self._notify_event(item)

    # ---------- notifications ----------
    def _notify_event(self, item: dict):
        if self.telegram_chat_id:
            self.hass.async_create_task(self._send_telegram_event(item))
        elif self.notify_service:
            self.hass.async_create_task(self._send_simple(item))

    def _notify_text(self, message: str):
        if self.telegram_chat_id:
            self.hass.async_create_task(self._tg_send(message))
        elif self.notify_service:
            self.hass.async_create_task(self._simple_send(message))

    def _event_line(self, item: dict) -> str:
        t0 = datetime.fromtimestamp(item["t_start"]).strftime("%H:%M")
        t1 = datetime.fromtimestamp(item["t_end"]).strftime("%H:%M")
        mins = round(item["duration_s"] / 60.0, 1)
        line = f"⚡ Uforklaret forbrug: *{round(item['delta_w'])} W* · {t0}–{t1} · {mins} min"
        if item.get("suggestion"):
            pct = f" ({round((item['suggestion_score'] or 0) * 100)}%)" if item.get("suggestion_score") else ""
            line += f"\nForslag: *{item['suggestion']}*{pct}"
        return line

    async def _send_telegram_event(self, item: dict):
        try:
            row = []
            if item.get("suggestion"):
                row.append(f"✅ {item['suggestion']}:/eldc {item['id']}")
            row.append(f"✏️ Nyt navn:/eldn {item['id']}")
            row.append(f"\U0001f5d1 Ignorér:/eldx {item['id']}")
            await self.hass.services.async_call("telegram_bot", "send_message", {
                "message": self._event_line(item),
                "chat_id": int(self.telegram_chat_id),
                "inline_keyboard": [row],
            }, blocking=False)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.warning("El-detektiv: telegram notify failed (%s)", err)

    async def _tg_send(self, message: str):
        try:
            await self.hass.services.async_call("telegram_bot", "send_message", {
                "message": message, "chat_id": int(self.telegram_chat_id),
            }, blocking=False)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.warning("El-detektiv: telegram send failed (%s)", err)

    async def _send_simple(self, item: dict):
        await self._simple_send(self._event_line(item))

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

    # ---------- telegram interaction ----------
    @callback
    def _on_tg_callback(self, event: Event):
        data = str((event.data or {}).get("data", "")).strip()
        cqid = (event.data or {}).get("id")
        parts = data.split()
        if len(parts) < 2 or not parts[0].startswith("/eld"):
            return
        cmd, eid = parts[0], parts[1]
        reply = None
        if cmd == "/eldc":
            self.confirm_suggestion(eid)
            reply = "Bekræftet ✅"
        elif cmd == "/eldx":
            self.dismiss_event(eid)
            reply = "Ignoreret \U0001f5d1"
        elif cmd == "/eldn":
            self._awaiting = eid
            reply = "Skriv navnet i et svar ✏️"
            self.hass.async_create_task(self._tg_send(
                "✏️ Skriv navnet på enheden (som en almindelig besked):"))
        else:
            return
        self._dirty = True
        self.hass.async_create_task(self._after_tg_action(cqid, reply))

    @callback
    def _on_tg_text(self, event: Event):
        if not self._awaiting:
            return
        text = str((event.data or {}).get("text", "")).strip()
        if not text or text.startswith("/"):
            return
        eid, self._awaiting = self._awaiting, None
        self.label_event(eid, text)
        self._dirty = True
        self.hass.async_create_task(self._after_tg_action(None, f"Gemt som *{text}* ✅"))

    async def _after_tg_action(self, cqid, reply: str | None):
        if cqid is not None and reply:
            try:
                await self.hass.services.async_call(
                    "telegram_bot", "answer_callback_query",
                    {"callback_query_id": cqid, "message": reply}, blocking=False)
            except Exception:  # pragma: no cover - defensive
                pass
        elif reply:
            await self._tg_send(reply)
        await self.async_save()
        self.async_set_updated_data(await self._async_update_data())

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
            "pending": list(self.pending),
            "test_label": self.test_label,
            "test_started": self.test_started,
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
