"""Sensor platform for Vehicle Bluetooth Tracker.

Two sensors share one device:
* `VehicleActiveDriverSensor` - current driver name (or `idle`); history-graph
  timeline reads `idle … Alice … Bob …` over time.  Carries drive-state
  attributes so automations have a single entity to query.
* `VehicleLastDriveDurationSensor` - duration in minutes of the most recent drive.
"""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_DRIVE_START_TIME,
    ATTR_LAST_DRIVE_DURATION,
    ATTR_LAST_DRIVER,
    ATTR_MONITORED_MAC,
    DOMAIN,
    STATE_IDLE,
)
from .vehicle_state import VehicleStateRuntime, signal_update

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the two sensor entities for this config entry."""
    runtime: VehicleStateRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            VehicleActiveDriverSensor(runtime),
            VehicleLastDriveDurationSensor(runtime),
        ]
    )


def _device_info(runtime: VehicleStateRuntime) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, runtime.entry_id)},
        name=runtime.car_name,
        manufacturer="Vehicle Bluetooth Tracker",
        model="Bluetooth-derived vehicle",
    )


class _VehicleEntityBase:
    """Mixin: shared device_info + dispatcher subscription wiring."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: VehicleStateRuntime) -> None:
        self._runtime = runtime
        self._attr_device_info = _device_info(runtime)

    async def async_added_to_hass(self) -> None:  # type: ignore[override]
        await super().async_added_to_hass()  # type: ignore[misc]
        self.async_on_remove(  # type: ignore[attr-defined]
            async_dispatcher_connect(
                self._runtime.hass,
                signal_update(self._runtime.entry_id),
                self._handle_runtime_update,
            )
        )

    @callback
    def _handle_runtime_update(self) -> None:
        self.async_write_ha_state()  # type: ignore[attr-defined]


class VehicleActiveDriverSensor(_VehicleEntityBase, RestoreEntity, SensorEntity):
    """Current driver display name, or `idle` when the car is not in use.

    The history graph renders this as a categorical timeline ribbon:
    `idle … Alice … Bob … idle …`

    Carries extra attributes so automations have a single entity to query:
    last_driver, drive_start_time, last_drive_duration_minutes, monitored_mac.
    """

    _attr_translation_key = "active_driver"
    _attr_icon = "mdi:account"

    def __init__(self, runtime: VehicleStateRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry_id}_active_driver"

    @property
    def native_value(self) -> str:
        if not self._runtime.is_driving or self._runtime.active_driver_entity is None:
            return STATE_IDLE
        return self._runtime.driver_display_name(self._runtime.active_driver_entity)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_LAST_DRIVER: self._runtime.last_driver,
            ATTR_DRIVE_START_TIME: (
                self._runtime.drive_start_time.isoformat()
                if self._runtime.drive_start_time
                else None
            ),
            ATTR_LAST_DRIVE_DURATION: self._runtime.last_drive_duration_minutes,
            ATTR_MONITORED_MAC: self._runtime.car_mac,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None:
            return

        attrs = last_state.attributes or {}
        start_time_raw = attrs.get(ATTR_DRIVE_START_TIME)
        start_time: datetime | None = None
        if isinstance(start_time_raw, str):
            start_time = dt_util.parse_datetime(start_time_raw)

        last_driver = attrs.get(ATTR_LAST_DRIVER) or "Unknown"
        try:
            last_duration = float(attrs.get(ATTR_LAST_DRIVE_DURATION, 0.0))
        except (TypeError, ValueError):
            last_duration = 0.0

        # Restore historical attributes only; current is_driving / active driver
        # come from the runtime's silent eval against live phone-sensor state.
        self._runtime.apply_restored_state(
            is_driving=self._runtime.is_driving,
            active_driver_entity=self._runtime.active_driver_entity,
            drive_start_time=start_time,
            last_driver=last_driver,
            last_drive_duration_minutes=last_duration,
        )
        self.async_write_ha_state()


class VehicleLastDriveDurationSensor(_VehicleEntityBase, SensorEntity):
    """Duration in minutes of the most recently completed drive."""

    _attr_translation_key = "last_drive_duration"
    _attr_icon = "mdi:timer-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, runtime: VehicleStateRuntime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.entry_id}_last_drive_duration"

    @property
    def native_value(self) -> float:
        return self._runtime.last_drive_duration_minutes
