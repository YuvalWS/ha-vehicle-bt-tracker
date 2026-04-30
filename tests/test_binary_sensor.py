"""Tests for the in-use binary sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vehicle_bt_tracker.const import DOMAIN

from .conftest import CAR_MAC_LABEL, PHONE_A, PHONE_B, set_paired


async def _setup_entry(hass: HomeAssistant, base_entry_data) -> MockConfigEntry:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])
    entry = MockConfigEntry(domain=DOMAIN, data=base_entry_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _in_use_id(hass: HomeAssistant) -> str:
    reg = er.async_get(hass)
    for entry in reg.entities.values():
        if entry.platform == DOMAIN and entry.unique_id.endswith("_in_use"):
            return entry.entity_id
    raise AssertionError("in_use binary sensor not registered")


async def test_initial_state_is_off(
    hass: HomeAssistant, base_entry_data
) -> None:
    await _setup_entry(hass, base_entry_data)
    assert hass.states.get(_in_use_id(hass)).state == "off"


async def test_turns_on_when_phone_connects(
    hass: HomeAssistant, base_entry_data
) -> None:
    await _setup_entry(hass, base_entry_data)
    in_use_id = _in_use_id(hass)

    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    await hass.async_block_till_done()
    assert hass.states.get(in_use_id).state == "on"

    set_paired(hass, PHONE_A, [])
    await hass.async_block_till_done()
    assert hass.states.get(in_use_id).state == "off"


async def test_device_class_is_occupancy(
    hass: HomeAssistant, base_entry_data
) -> None:
    await _setup_entry(hass, base_entry_data)
    state = hass.states.get(_in_use_id(hass))
    assert state.attributes["device_class"] == BinarySensorDeviceClass.OCCUPANCY
