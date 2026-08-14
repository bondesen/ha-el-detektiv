"""Guard-rails for the silent (no unlabeled-event queue) coordinator.

Home Assistant is not installed in this test environment, so the few HA
symbols coordinator.py imports are stubbed. The point of these tests is the
El-detektiv logic itself: a whole-home step must either be counted against a
known device or be dropped — it must never be queued, notified, or persisted.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(ROOT, "custom_components", "el_detektiv")


# --------------------------------------------------------------------------
# Minimal Home Assistant stubs (only what coordinator.py imports).
# --------------------------------------------------------------------------
def _install_ha_stubs():
    if "homeassistant" in sys.modules:
        return

    def _mod(name):
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    ha = _mod("homeassistant")
    core = _mod("homeassistant.core")
    core.HomeAssistant = object
    core.Event = object
    core.callback = lambda f: f
    ce = _mod("homeassistant.config_entries")
    ce.ConfigEntry = object
    helpers = _mod("homeassistant.helpers")
    uc = _mod("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        def __init__(self, hass, logger, name=None, update_interval=None):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval

    uc.DataUpdateCoordinator = DataUpdateCoordinator
    ev = _mod("homeassistant.helpers.event")
    ev.async_track_state_change_event = lambda *a, **k: (lambda: None)
    st = _mod("homeassistant.helpers.storage")

    class Store:
        payloads: list = []
        preload: dict = {}

        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return dict(Store.preload)

        async def async_save(self, data):
            Store.payloads.append(data)

    st.Store = Store
    ha.core, ha.config_entries, ha.helpers = core, ce, helpers
    helpers.update_coordinator, helpers.event, helpers.storage = uc, ev, st
    return Store


STORE = _install_ha_stubs() or sys.modules["homeassistant.helpers.storage"].Store


# --------------------------------------------------------------------------
# Import the integration modules without executing __init__.py (which pulls in
# voluptuous and more HA internals we do not need here).
# --------------------------------------------------------------------------
def _load(name):
    full = f"eld_test_pkg.{name}"
    if full in sys.modules:
        return sys.modules[full]
    if "eld_test_pkg" not in sys.modules:
        pkg = types.ModuleType("eld_test_pkg")
        pkg.__path__ = [PKG_DIR]
        sys.modules["eld_test_pkg"] = pkg
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(PKG_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


const = _load("const")
_load("nilm_core")
coordinator = _load("coordinator")


class FakeStates:
    def __init__(self, values=None):
        self._v = values or {}

    def get(self, eid):
        return self._v.get(eid)


class FakeHass:
    def __init__(self):
        self.states = FakeStates()
        self.service_calls = []
        self._tasks = []

    def async_create_task(self, coro):
        self._tasks.append(coro)
        coro.close()

    class _Services:
        def __init__(self, outer):
            self.outer = outer

        async def async_call(self, domain, service, data, blocking=False):
            self.outer.service_calls.append((domain, service, data))

    @property
    def services(self):
        return FakeHass._Services(self)


class FakeEntry:
    def __init__(self, **data):
        self.data = {const.CONF_TOTAL_POWER: "sensor.total", **data}
        self.options = {}
        self.entry_id = "test"


def _coord(**data):
    return coordinator.ElDetektivCoordinator(FakeHass(), FakeEntry(**data))


def _event(delta, dur=300.0, t=1_700_000_000.0):
    return {"t_start": t, "t_end": t + dur, "delta_w": delta, "duration_s": dur}


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_no_pending_queue_attribute():
    c = _coord()
    assert not hasattr(c, "pending")
    for gone in ("label_event", "confirm_suggestion", "dismiss_event",
                 "_pop_pending", "_notify_event", "_send_telegram_event"):
        assert not hasattr(c, gone), f"{gone} should be gone"


def test_removed_constants():
    for gone in ("MAX_PENDING", "EVENT_DETECTED", "SERVICE_LABEL_EVENT",
                 "SERVICE_CONFIRM_SUGGESTION", "SERVICE_DISMISS_EVENT",
                 "ATTR_EVENT_ID"):
        assert not hasattr(const, gone), f"const.{gone} should be gone"


def test_unknown_step_is_dropped_silently():
    c = _coord(telegram_chat_id="123")
    assert c._attribute_event(_event(1850)) is None
    assert c.store_engine.sigs == {}          # nothing learned
    assert c.hass.service_calls == []         # nothing sent
    assert c._dirty is False                  # nothing to persist


def test_trusted_signature_still_counts_the_run():
    c = _coord()
    for _ in range(6):                        # -> confidence "hoej"
        c.store_engine.add_sample("Elkedel", 2000.0, 300.0, 12, 1.0)
    assert c.store_engine.sigs["Elkedel"].confidence == const.CONFIDENCE_TRUSTED
    assert c._attribute_event(_event(2000)) == "Elkedel"
    assert c.store_engine.sigs["Elkedel"].n == 7
    assert c._dirty is True


def test_low_confidence_signature_is_not_auto_counted():
    c = _coord()
    c.store_engine.add_sample("Elkedel", 2000.0, 300.0, 12, 1.0)
    assert c._attribute_event(_event(2000)) is None
    assert c.store_engine.sigs["Elkedel"].n == 1


def test_saved_payload_has_no_pending_key():
    STORE.payloads.clear()
    c = _coord()
    c.store_engine.add_sample("Elkedel", 2000.0)
    asyncio.run(c.async_save())
    assert STORE.payloads[-1].keys() == {"signatures"}


def test_legacy_pending_in_storage_is_discarded():
    STORE.payloads.clear()
    STORE.preload = {
        "signatures": [{"label": "Elkedel", "n": 2, "mean": 2000.0}],
        "pending": [{"id": "abc", "delta_w": 1850}],
    }
    try:
        c = _coord()
        asyncio.run(c.async_load())
        assert "Elkedel" in c.store_engine.sigs
        assert c._dirty is True               # forces a clean rewrite
        asyncio.run(c.async_save())
        assert "pending" not in STORE.payloads[-1]
    finally:
        STORE.preload = {}


def test_snapshot_has_no_pending_field():
    c = _coord()
    data = asyncio.run(c._async_update_data())
    assert set(data) == {"residual", "baseline", "signatures",
                         "test_label", "test_started"}
