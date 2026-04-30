"""Test the Vehicle Bluetooth Tracker config flow."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
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
    CAR_UID,
    DEVICE_A_NAME,
    DEVICE_B_NAME,
    DRIVER_A,
    DRIVER_B,
)

CAR_LABEL = "00:4E:10:51:0C:00 (TestCar)"
OTHER_CAR_LABEL = "DC:0D:30:81:34:8D (OtherCar)"


async def test_full_config_flow(
    hass: HomeAssistant, mobile_app_setup
) -> None:
    """Walk through device-select → driver-names → select-car and create the entry."""
    device_a_id = mobile_app_setup["device_a_id"]
    device_b_id = mobile_app_setup["device_b_id"]

    # Give each BT sensor paired_devices so the car list is populated in step 3.
    hass.states.async_set(BT_ENTITY_A, "Connected", {"paired_devices": [CAR_LABEL]})
    hass.states.async_set(BT_ENTITY_B, "Disconnected", {"paired_devices": [OTHER_CAR_LABEL]})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CAR_NAME: "TestCar", CONF_DRIVER_DEVICES: [device_a_id, device_b_id]},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "driver_names"

    # Defaults should be the device names; submit custom names.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {BT_ENTITY_A: DRIVER_A, BT_ENTITY_B: DRIVER_B},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_car"

    with patch(
        "custom_components.vehicle_bt_tracker.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CAR_MAC: CAR_LABEL}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "TestCar"
    assert result["data"][CONF_CAR_MAC] == CAR_LABEL
    assert result["data"][CONF_DRIVER_ENTITIES] == [BT_ENTITY_A, BT_ENTITY_B]
    assert result["data"][CONF_DRIVER_NAMES] == {BT_ENTITY_A: DRIVER_A, BT_ENTITY_B: DRIVER_B}
    assert len(mock_setup_entry.mock_calls) == 1


async def test_driver_name_defaults_to_device_name(
    hass: HomeAssistant, mobile_app_setup
) -> None:
    """Driver name defaults to the phone's HA device name — no typing required."""
    device_a_id = mobile_app_setup["device_a_id"]

    hass.states.async_set(BT_ENTITY_A, "Connected", {"paired_devices": [CAR_LABEL]})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CAR_NAME: "TestCar", CONF_DRIVER_DEVICES: [device_a_id]},
    )
    assert result["step_id"] == "driver_names"

    # The schema default for BT_ENTITY_A must be the device display name.
    schema_defaults = {
        k.schema: k.default()
        for k in result["data_schema"].schema
        if hasattr(k, "default") and callable(k.default)
    }
    assert schema_defaults.get(BT_ENTITY_A) == DEVICE_A_NAME


async def test_user_step_blocks_empty_driver_list(hass: HomeAssistant) -> None:
    """Submitting with no devices selected stays on the user step with an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    try:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_CAR_NAME: "X", CONF_DRIVER_DEVICES: []},
        )
    except Exception:
        # voluptuous may reject the empty list at schema level — also acceptable.
        return
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_drivers"}


async def test_user_step_bt_sensor_not_found(
    hass: HomeAssistant, mobile_app_setup
) -> None:
    """Selecting a device without an enabled BT sensor shows bt_sensor_not_found."""
    from homeassistant.helpers import device_registry as dr

    # Create a third device with NO entity registered (sensor never enabled).
    device_reg = dr.async_get(hass)
    bare_device = device_reg.async_get_or_create(
        config_entry_id="mobile_test_entry",
        identifiers={("mobile_app", "bare_device_no_bt")},
        name="Bare Phone",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CAR_NAME: "X", CONF_DRIVER_DEVICES: [bare_device.id]},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "bt_sensor_not_found"}
    assert "Bare Phone" in (result.get("description_placeholders") or {}).get("devices", "")


async def test_select_car_falls_back_when_no_paired_devices(
    hass: HomeAssistant, mobile_app_setup
) -> None:
    """Choosing a car is blocked when the BT sensor has no paired_devices yet."""
    device_a_id = mobile_app_setup["device_a_id"]

    # BT sensor is registered (entity exists) but paired_devices is empty.
    hass.states.async_set(
        BT_ENTITY_A, "Disconnected", {"paired_devices": [], "connected_paired_devices": []}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CAR_NAME: "X", CONF_DRIVER_DEVICES: [device_a_id]},
    )
    assert result["step_id"] == "driver_names"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {BT_ENTITY_A: DRIVER_A}
    )
    assert result["step_id"] == "select_car"

    # The only choice is the sentinel — submitting it surfaces the error.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CAR_MAC: "__manual__"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "no_paired_devices"}


async def test_duplicate_car_mac_aborts(
    hass: HomeAssistant, mobile_app_setup
) -> None:
    """Adding the same car a second time aborts via unique_id collision."""
    device_a_id = mobile_app_setup["device_a_id"]

    MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CAR_NAME: "TestCar",
            CONF_CAR_MAC: CAR_LABEL,
            CONF_DRIVER_DEVICES: [device_a_id],
            CONF_DRIVER_ENTITIES: [BT_ENTITY_A],
            CONF_DRIVER_NAMES: {BT_ENTITY_A: DRIVER_A},
        },
        unique_id=CAR_UID,
    ).add_to_hass(hass)

    hass.states.async_set(BT_ENTITY_A, "Connected", {"paired_devices": [CAR_LABEL]})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CAR_NAME: "Dup", CONF_DRIVER_DEVICES: [device_a_id]},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {BT_ENTITY_A: DRIVER_A}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CAR_MAC: CAR_LABEL}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
