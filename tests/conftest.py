"""Test fixtures for the Vehicle Bluetooth Tracker integration."""
from __future__ import annotations

from typing import Any

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vehicle_bt_tracker.const import (
    CONF_CAR_MAC,
    CONF_CAR_NAME,
    CONF_DRIVER_DEVICES,
    CONF_DRIVER_ENTITIES,
    CONF_DRIVER_NAMES,
)


# ---------------------------------------------------------------------------
# Runtime test constants (entity-ID based, used by test_sensor / test_init / etc.)
# ---------------------------------------------------------------------------
PHONE_A = "sensor.phone_a_bluetooth"
PHONE_B = "sensor.phone_b_bluetooth"
DRIVER_A = "Alice"
DRIVER_B = "Bob"
CAR_MAC = "00:4E:10:51:0C:00"
CAR_MAC_LABEL = f"{CAR_MAC} (TestCar)"
CAR_UID = "004E10510C00"  # normalized unique_id set by config flow (_mac_uid)

# ---------------------------------------------------------------------------
# Config-flow test constants (device-ID based, used by test_config_flow / test_options_flow)
# The entity IDs below match the suggested_object_id used in mobile_app_setup.
# ---------------------------------------------------------------------------
DEVICE_A_IDENT = "phone_a_test_device"   # mobile_app identifier tuple value
DEVICE_B_IDENT = "phone_b_test_device"
DEVICE_A_NAME = "Alice's Phone"
DEVICE_B_NAME = "Bob's Phone"
# Entity IDs created by mobile_app_setup (sensor.<suggested_object_id>):
BT_ENTITY_A = "sensor.phone_a_bluetooth_connection"
BT_ENTITY_B = "sensor.phone_b_bluetooth_connection"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/ during tests."""
    yield


@pytest.fixture
def base_entry_data() -> dict[str, Any]:
    """Standard config-entry data for one car + two drivers (runtime tests)."""
    return {
        CONF_CAR_NAME: "TestCar",
        CONF_CAR_MAC: CAR_MAC_LABEL,
        CONF_DRIVER_ENTITIES: [PHONE_A, PHONE_B],
        CONF_DRIVER_NAMES: {PHONE_A: DRIVER_A, PHONE_B: DRIVER_B},
    }


def set_paired(hass, entity_id: str, devices: list[str] | str | None) -> None:
    """Helper: set the connected_paired_devices attribute on a phone sensor.

    Also sets paired_devices to the same value so both the runtime (which reads
    connected_paired_devices) and the config flow (which reads paired_devices for
    the car-MAC pool) see consistent data in tests.
    """
    if devices is None:
        hass.states.async_set(entity_id, "Disconnected", {})
        return
    paired_list = [devices] if isinstance(devices, str) else list(devices)
    attrs = {
        "paired_devices": paired_list,
        "connected_paired_devices": devices,  # keep original str/list; runtime handles both
    }
    hass.states.async_set(
        entity_id, "Connected" if devices else "Disconnected", attrs
    )


@pytest.fixture
def mobile_app_setup(hass):
    """Register two Companion App devices + their BT Connection sensor entities.

    The entity unique_ids contain 'bluetooth_connection' so _find_bt_sensor's
    first pass resolves them without needing live state.  suggested_object_id
    pins the entity_ids to BT_ENTITY_A / BT_ENTITY_B.

    Returns a dict with 'device_a_id' and 'device_b_id' (HA device UUIDs).
    """
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    mobile_entry = MockConfigEntry(domain="mobile_app", entry_id="mobile_test_entry")
    mobile_entry.add_to_hass(hass)

    device_a = device_reg.async_get_or_create(
        config_entry_id=mobile_entry.entry_id,
        identifiers={("mobile_app", DEVICE_A_IDENT)},
        name=DEVICE_A_NAME,
    )
    device_b = device_reg.async_get_or_create(
        config_entry_id=mobile_entry.entry_id,
        identifiers={("mobile_app", DEVICE_B_IDENT)},
        name=DEVICE_B_NAME,
    )

    # unique_id contains 'bluetooth_connection' → matched by _find_bt_sensor first pass
    entity_reg.async_get_or_create(
        "sensor",
        "mobile_app",
        f"{DEVICE_A_IDENT}_bluetooth_connection",
        config_entry=mobile_entry,
        device_id=device_a.id,
        suggested_object_id="phone_a_bluetooth_connection",  # → BT_ENTITY_A
    )
    entity_reg.async_get_or_create(
        "sensor",
        "mobile_app",
        f"{DEVICE_B_IDENT}_bluetooth_connection",
        config_entry=mobile_entry,
        device_id=device_b.id,
        suggested_object_id="phone_b_bluetooth_connection",  # → BT_ENTITY_B
    )

    return {"device_a_id": device_a.id, "device_b_id": device_b.id}
