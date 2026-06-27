"""El-detektiv sensors."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity, SensorDeviceClass, SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ElDetektivCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coord: ElDetektivCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        UnexplainedPowerSensor(coord, entry),
        SignaturesSensor(coord, entry),
        PendingEventsSensor(coord, entry),
    ])


class _Base(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: ElDetektivCoordinator, entry: ConfigEntry, key: str):
        super().__init__(coord)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "El-detektiv",
            "manufacturer": "El-detektiv",
            "model": "NILM load identifier",
        }


class UnexplainedPowerSensor(_Base, SensorEntity):
    _attr_translation_key = "uforklaret_effekt"
    _attr_name = "Uforklaret effekt"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:help-circle-outline"

    def __init__(self, coord, entry):
        super().__init__(coord, entry, "uforklaret_effekt")

    @property
    def native_value(self):
        v = (self.coordinator.data or {}).get("residual")
        return round(v) if v is not None else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "baseline": data.get("baseline"),
            "total_power": self.coordinator.total_power,
            "measured_plugs": self.coordinator.measured_plugs,
            "tracked": self.coordinator.tracked,
            "test_meter": self.coordinator.test_meter,
            "test_label": data.get("test_label"),
            "test_started": data.get("test_started"),
        }


class SignaturesSensor(_Base, SensorEntity):
    _attr_name = "Signaturer"
    _attr_icon = "mdi:fingerprint"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord, entry, "signaturer")

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("signatures", []))

    @property
    def extra_state_attributes(self):
        return {"library": (self.coordinator.data or {}).get("signatures", [])}


class PendingEventsSensor(_Base, SensorEntity):
    _attr_name = "Ulabelede hændelser"
    _attr_icon = "mdi:clipboard-text-search-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry):
        super().__init__(coord, entry, "ulabelede_haendelser")

    @property
    def native_value(self):
        return len((self.coordinator.data or {}).get("pending", []))

    @property
    def extra_state_attributes(self):
        return {"events": (self.coordinator.data or {}).get("pending", [])}
