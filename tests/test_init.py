"""Test setup, unload, and reload of the integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vehicle_bt_tracker.const import DOMAIN
from custom_components.vehicle_bt_tracker.vehicle_state import VehicleStateRuntime

from .conftest import DRIVER_A, DRIVER_B, PHONE_A, PHONE_B, set_paired


async def test_setup_creates_runtime_and_forwards_platforms(
    hass: HomeAssistant, base_entry_data
) -> None:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])

    entry = MockConfigEntry(domain=DOMAIN, data=base_entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    runtime = hass.data[DOMAIN][entry.entry_id]
    assert isinstance(runtime, VehicleStateRuntime)
    assert runtime.car_name == "TestCar"
    assert runtime.driver_names == {PHONE_A: DRIVER_A, PHONE_B: DRIVER_B}


async def test_unload_cleans_up_runtime(
    hass: HomeAssistant, base_entry_data
) -> None:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])

    entry = MockConfigEntry(domain=DOMAIN, data=base_entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_options_update_triggers_reload(
    hass: HomeAssistant, base_entry_data
) -> None:
    """Updating options should reload the entry so new config takes effect."""
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])

    entry = MockConfigEntry(domain=DOMAIN, data=base_entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    runtime_v1 = hass.data[DOMAIN][entry.entry_id]
    assert runtime_v1.driver_names[PHONE_A] == DRIVER_A

    # Persist new options dict — the listener installed by async_setup_entry
    # should call async_reload, replacing the runtime.
    hass.config_entries.async_update_entry(
        entry,
        options={
            **base_entry_data,
            "driver_names": {PHONE_A: f"{DRIVER_A} Updated", PHONE_B: DRIVER_B},
        },
    )
    await hass.async_block_till_done()

    runtime_v2 = hass.data[DOMAIN][entry.entry_id]
    assert runtime_v2 is not runtime_v1
    assert runtime_v2.driver_names[PHONE_A] == f"{DRIVER_A} Updated"
