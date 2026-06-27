"""Config & options flow for El-detektiv."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow, ConfigEntry, OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector, EntitySelectorConfig, NumberSelector, NumberSelectorConfig,
    TextSelector, TextSelectorConfig,
)

from .const import (
    DOMAIN, CONF_TOTAL_POWER, CONF_MEASURED_PLUGS, CONF_TRACKED_ENTITIES,
    CONF_STEP_THRESHOLD, CONF_SAMPLE_INTERVAL, CONF_MIN_DURATION,
    CONF_MATCH_WINDOW, CONF_TEST_METER, CONF_TEST_STEP_THRESHOLD,
    CONF_NOTIFY_SERVICE, CONF_TELEGRAM_CHAT_ID,
    DEFAULT_STEP_THRESHOLD, DEFAULT_SAMPLE_INTERVAL,
    DEFAULT_MIN_DURATION, DEFAULT_MATCH_WINDOW, DEFAULT_TEST_STEP_THRESHOLD,
)


def _schema(defaults: dict) -> vol.Schema:
    d = defaults
    return vol.Schema({
        vol.Required(CONF_TOTAL_POWER, default=d.get(CONF_TOTAL_POWER)):
            EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
        vol.Optional(CONF_MEASURED_PLUGS, default=d.get(CONF_MEASURED_PLUGS, [])):
            EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)),
        vol.Optional(CONF_TRACKED_ENTITIES, default=d.get(CONF_TRACKED_ENTITIES, [])):
            EntitySelector(EntitySelectorConfig(
                domain=["switch", "media_player", "climate", "binary_sensor",
                        "light", "device_tracker", "vacuum", "fan"],
                multiple=True)),
        vol.Optional(CONF_STEP_THRESHOLD, default=d.get(CONF_STEP_THRESHOLD, DEFAULT_STEP_THRESHOLD)):
            NumberSelector(NumberSelectorConfig(min=20, max=1000, step=10, unit_of_measurement="W", mode="box")),
        vol.Optional(CONF_SAMPLE_INTERVAL, default=d.get(CONF_SAMPLE_INTERVAL, DEFAULT_SAMPLE_INTERVAL)):
            NumberSelector(NumberSelectorConfig(min=5, max=60, step=1, unit_of_measurement="s", mode="box")),
        vol.Optional(CONF_MIN_DURATION, default=d.get(CONF_MIN_DURATION, DEFAULT_MIN_DURATION)):
            NumberSelector(NumberSelectorConfig(min=10, max=600, step=5, unit_of_measurement="s", mode="box")),
        vol.Optional(CONF_MATCH_WINDOW, default=d.get(CONF_MATCH_WINDOW, DEFAULT_MATCH_WINDOW)):
            NumberSelector(NumberSelectorConfig(min=15, max=300, step=5, unit_of_measurement="s", mode="box")),
        # --- Test meter (supervised learning) ---
        vol.Optional(CONF_TEST_METER, default=d.get(CONF_TEST_METER)):
            EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power")),
        vol.Optional(CONF_TEST_STEP_THRESHOLD, default=d.get(CONF_TEST_STEP_THRESHOLD, DEFAULT_TEST_STEP_THRESHOLD)):
            NumberSelector(NumberSelectorConfig(min=5, max=500, step=5, unit_of_measurement="W", mode="box")),
        # --- Notifications (optional; leave blank for dashboard-only) ---
        vol.Optional(CONF_NOTIFY_SERVICE, default=d.get(CONF_NOTIFY_SERVICE, "")):
            TextSelector(TextSelectorConfig()),
        vol.Optional(CONF_TELEGRAM_CHAT_ID, default=d.get(CONF_TELEGRAM_CHAT_ID, "")):
            TextSelector(TextSelectorConfig()),
    })


class ElDetektivConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="El-detektiv", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return ElDetektivOptionsFlow(entry)


class ElDetektivOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = {**self._entry.data, **self._entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(current))
