"""End-to-end tests for the sensor platform."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vehicle_bt_tracker.const import (
    ATTR_DRIVE_START_TIME,
    ATTR_LAST_DRIVE_DURATION,
    ATTR_LAST_DRIVER,
    ATTR_MONITORED_MAC,
    DOMAIN,
)

from .conftest import (
    CAR_MAC,
    CAR_MAC_LABEL,
    DRIVER_A,
    DRIVER_B,
    PHONE_A,
    PHONE_B,
    set_paired,
)


async def _setup_entry(hass: HomeAssistant, base_entry_data) -> MockConfigEntry:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])
    entry = MockConfigEntry(domain=DOMAIN, data=base_entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _eid(hass: HomeAssistant, suffix: str) -> str:
    """Resolve a registered entity_id by its unique_id suffix."""
    reg = er.async_get(hass)
    for entry in reg.entities.values():
        if entry.platform == DOMAIN and entry.unique_id.endswith(suffix):
            return entry.entity_id
    raise AssertionError(f"entity with unique_id ending in {suffix!r} not found")


async def test_initial_state_is_idle(
    hass: HomeAssistant, base_entry_data
) -> None:
    await _setup_entry(hass, base_entry_data)

    assert hass.states.get(_eid(hass, "_active_driver")).state == "idle"
    assert hass.states.get(_eid(hass, "_last_drive_duration")).state == "0.0"


async def test_active_driver_sensor_shows_driver_when_driving(
    hass: HomeAssistant, base_entry_data
) -> None:
    await _setup_entry(hass, base_entry_data)

    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    await hass.async_block_till_done()

    active = hass.states.get(_eid(hass, "_active_driver"))
    assert active.state == DRIVER_A
    assert active.attributes[ATTR_LAST_DRIVER] == DRIVER_A
    assert active.attributes[ATTR_MONITORED_MAC] == CAR_MAC
    assert active.attributes[ATTR_DRIVE_START_TIME] is not None


async def test_full_drive_cycle_updates_duration(
    hass: HomeAssistant, base_entry_data
) -> None:
    entry = await _setup_entry(hass, base_entry_data)

    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    await hass.async_block_till_done()

    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime.drive_start_time = dt_util.utcnow() - timedelta(minutes=7)

    set_paired(hass, PHONE_A, [])
    await hass.async_block_till_done()

    active = hass.states.get(_eid(hass, "_active_driver"))
    duration = hass.states.get(_eid(hass, "_last_drive_duration"))
    assert active.state == "idle"
    assert float(duration.state) >= 7.0
    assert active.attributes[ATTR_LAST_DRIVE_DURATION] >= 7.0


async def test_driver_swap_updates_active_driver_without_ending_drive(
    hass: HomeAssistant, base_entry_data
) -> None:
    await _setup_entry(hass, base_entry_data)

    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    set_paired(hass, PHONE_B, [CAR_MAC_LABEL])
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, "_active_driver")).state == DRIVER_A

    set_paired(hass, PHONE_A, [])
    await hass.async_block_till_done()

    assert hass.states.get(_eid(hass, "_active_driver")).state == DRIVER_B
    assert hass.states.get(_eid(hass, "_in_use")).state == "on"


async def test_duration_sensor_metadata_uses_modern_patterns(
    hass: HomeAssistant, base_entry_data
) -> None:
    await _setup_entry(hass, base_entry_data)

    state = hass.states.get(_eid(hass, "_last_drive_duration"))
    assert state.attributes["device_class"] == SensorDeviceClass.DURATION
    assert state.attributes["state_class"] == SensorStateClass.MEASUREMENT
    assert state.attributes["unit_of_measurement"] == UnitOfTime.MINUTES


async def test_all_entities_share_one_device(
    hass: HomeAssistant, base_entry_data
) -> None:
    entry = await _setup_entry(hass, base_entry_data)
    reg = er.async_get(hass)
    related = [
        e for e in reg.entities.values() if e.config_entry_id == entry.entry_id
    ]
    assert len(related) == 3
    assert len({e.device_id for e in related}) == 1


async def test_active_driver_sensor_restores_drive_start_time(
    hass: HomeAssistant, base_entry_data
) -> None:
    """A drive in progress when HA went down should resume cleanly on startup."""
    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])  # still connected at startup
    set_paired(hass, PHONE_B, [])

    earlier = dt_util.utcnow() - timedelta(minutes=15)
    entry = MockConfigEntry(domain=DOMAIN, data=base_entry_data)
    entry.add_to_hass(hass)

    fake_state = State(
        "sensor.placeholder",
        DRIVER_A,
        {
            ATTR_LAST_DRIVER: DRIVER_A,
            ATTR_DRIVE_START_TIME: earlier.isoformat(),
            ATTR_LAST_DRIVE_DURATION: 0.0,
            ATTR_MONITORED_MAC: CAR_MAC,
        },
    )
    with patch(
        "custom_components.vehicle_bt_tracker.sensor.RestoreEntity.async_get_last_state",
        new=AsyncMock(return_value=fake_state),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime.is_driving
    assert runtime.drive_start_time is not None
    assert abs((runtime.drive_start_time - earlier).total_seconds()) < 1.0
    assert runtime.last_driver == DRIVER_A
