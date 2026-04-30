"""Binary sensor platform for Vehicle Bluetooth Tracker."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .vehicle_state import VehicleStateRuntime, signal_update


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the in-use binary sensor."""
    runtime: VehicleStateRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VehicleInUseBinarySensor(runtime)])


class VehicleInUseBinarySensor(BinarySensorEntity):
    """On while any configured driver is connected to the car's Bluetooth."""

    _attr_has_entity_name = True
    _attr_translation_key = "in_use"
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, runtime: VehicleStateRuntime) -> None:
        self._runtime = runtime
        self._attr_unique_id = f"{runtime.entry_id}_in_use"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry_id)},
            name=runtime.car_name,
            manufacturer="Vehicle Bluetooth Tracker",
            model="Bluetooth-derived vehicle",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self._runtime.hass,
                signal_update(self._runtime.entry_id),
                self._handle_runtime_update,
            )
        )

    @callback
    def _handle_runtime_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._runtime.is_driving
