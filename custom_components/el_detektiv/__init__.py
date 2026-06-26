"""El-detektiv — non-intrusive load identification for Home Assistant."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN, SERVICE_LABEL_EVENT, SERVICE_CONFIRM_SUGGESTION,
    SERVICE_DISMISS_EVENT, SERVICE_DELETE_SIGNATURE, SERVICE_RENAME_SIGNATURE,
    SERVICE_ADD_MANUAL_SIGNATURE, ATTR_EVENT_ID, ATTR_LABEL, ATTR_NEW_LABEL,
    ATTR_WATT, ATTR_DURATION,
)
from .coordinator import ElDetektivCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ElDetektivCoordinator(hass, entry)
    await coordinator.async_start()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coord: ElDetektivCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coord.async_stop()
        if not hass.data[DOMAIN]:
            for svc in (
                SERVICE_LABEL_EVENT, SERVICE_CONFIRM_SUGGESTION,
                SERVICE_DISMISS_EVENT, SERVICE_DELETE_SIGNATURE,
                SERVICE_RENAME_SIGNATURE, SERVICE_ADD_MANUAL_SIGNATURE,
            ):
                hass.services.async_remove(DOMAIN, svc)
    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LABEL_EVENT):
        return

    def _all_coords():
        return list(hass.data.get(DOMAIN, {}).values())

    async def _refresh():
        for c in _all_coords():
            await c.async_save()
            c.async_set_updated_data(await c._async_update_data())

    async def label_event(call: ServiceCall):
        for c in _all_coords():
            c.label_event(call.data[ATTR_EVENT_ID], call.data[ATTR_LABEL])
        await _refresh()

    async def confirm_suggestion(call: ServiceCall):
        for c in _all_coords():
            c.confirm_suggestion(call.data[ATTR_EVENT_ID])
        await _refresh()

    async def dismiss_event(call: ServiceCall):
        for c in _all_coords():
            c.dismiss_event(call.data[ATTR_EVENT_ID])
        await _refresh()

    async def delete_signature(call: ServiceCall):
        for c in _all_coords():
            c.delete_signature(call.data[ATTR_LABEL])
        await _refresh()

    async def rename_signature(call: ServiceCall):
        for c in _all_coords():
            c.rename_signature(call.data[ATTR_LABEL], call.data[ATTR_NEW_LABEL])
        await _refresh()

    async def add_manual_signature(call: ServiceCall):
        for c in _all_coords():
            c.add_manual_signature(
                call.data[ATTR_LABEL], call.data[ATTR_WATT],
                call.data.get(ATTR_DURATION))
        await _refresh()

    hass.services.async_register(DOMAIN, SERVICE_LABEL_EVENT, label_event,
        schema=vol.Schema({vol.Required(ATTR_EVENT_ID): cv.string,
                           vol.Required(ATTR_LABEL): cv.string}))
    hass.services.async_register(DOMAIN, SERVICE_CONFIRM_SUGGESTION, confirm_suggestion,
        schema=vol.Schema({vol.Required(ATTR_EVENT_ID): cv.string}))
    hass.services.async_register(DOMAIN, SERVICE_DISMISS_EVENT, dismiss_event,
        schema=vol.Schema({vol.Required(ATTR_EVENT_ID): cv.string}))
    hass.services.async_register(DOMAIN, SERVICE_DELETE_SIGNATURE, delete_signature,
        schema=vol.Schema({vol.Required(ATTR_LABEL): cv.string}))
    hass.services.async_register(DOMAIN, SERVICE_RENAME_SIGNATURE, rename_signature,
        schema=vol.Schema({vol.Required(ATTR_LABEL): cv.string,
                           vol.Required(ATTR_NEW_LABEL): cv.string}))
    hass.services.async_register(DOMAIN, SERVICE_ADD_MANUAL_SIGNATURE, add_manual_signature,
        schema=vol.Schema({vol.Required(ATTR_LABEL): cv.string,
                           vol.Required(ATTR_WATT): vol.Coerce(float),
                           vol.Optional(ATTR_DURATION): vol.Coerce(float)}))
