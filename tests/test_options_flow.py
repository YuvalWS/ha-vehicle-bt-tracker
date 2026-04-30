"""Test the Vehicle Bluetooth Tracker options flow."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vehicle_bt_tracker.const import (
    CONF_CAR_MAC,
    CONF_CAR_NAME,
    CONF_DRIVER_DEVICES,
    CONF_DRIVER_ENTITIES,
    CONF_DRIVER_NAMES,
    DOMAIN,
)

from .conftest import (
    BT_ENTITY_A,
    BT_ENTITY_B,
    CAR_MAC_LABEL,
    DRIVER_A,
    DRIVER_B,
    set_paired,
)


def _make_entry(hass, device_a_id: str, device_b_id: str) -> MockConfigEntry:
    """Create and load a pre-existing config entry (device-selector style)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CAR_NAME: "TestCar",
            CONF_CAR_MAC: CAR_MAC_LABEL,
            CONF_DRIVER_DEVICES: [device_a_id, device_b_id],
            CONF_DRIVER_ENTITIES: [BT_ENTITY_A, BT_ENTITY_B],
            CONF_DRIVER_NAMES: {BT_ENTITY_A: DRIVER_A, BT_ENTITY_B: DRIVER_B},
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_flow_updates_driver_names(
    hass: HomeAssistant, mobile_app_setup
) -> None:
    """Renaming a driver via the options flow updates entry.options end-to-end."""
    device_a_id = mobile_app_setup["device_a_id"]
    device_b_id = mobile_app_setup["device_b_id"]

    set_paired(hass, BT_ENTITY_A, [])
    set_paired(hass, BT_ENTITY_B, [])

    entry = _make_entry(hass, device_a_id, device_b_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DRIVER_DEVICES: [device_a_id, device_b_id]}
    )
    assert result["step_id"] == "driver_names"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {BT_ENTITY_A: f"{DRIVER_A} Renamed", BT_ENTITY_B: DRIVER_B}
    )
    assert result["step_id"] == "select_car"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CAR_MAC: CAR_MAC_LABEL}
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DRIVER_NAMES][BT_ENTITY_A] == f"{DRIVER_A} Renamed"
    assert entry.options[CONF_CAR_MAC] == CAR_MAC_LABEL


async def test_options_flow_can_drop_a_driver(
    hass: HomeAssistant, mobile_app_setup
) -> None:
    """Removing a driver from the options flow updates the stored entity list."""
    device_a_id = mobile_app_setup["device_a_id"]
    device_b_id = mobile_app_setup["device_b_id"]

    set_paired(hass, BT_ENTITY_A, [])
    set_paired(hass, BT_ENTITY_B, [])

    entry = _make_entry(hass, device_a_id, device_b_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DRIVER_DEVICES: [device_a_id]}  # B dropped
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {BT_ENTITY_A: DRIVER_A}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CAR_MAC: CAR_MAC_LABEL}
    )
    await hass.async_block_till_done()

    assert entry.options[CONF_DRIVER_ENTITIES] == [BT_ENTITY_A]
    assert BT_ENTITY_B not in entry.options[CONF_DRIVER_NAMES]
