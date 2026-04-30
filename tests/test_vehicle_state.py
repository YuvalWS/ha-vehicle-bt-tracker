"""Unit tests for the VehicleStateRuntime state machine."""
from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.vehicle_bt_tracker.const import (
    EVENT_DRIVE_ENDED,
    EVENT_DRIVE_STARTED,
)
from custom_components.vehicle_bt_tracker.vehicle_state import (
    VehicleStateRuntime,
    _normalize_mac,
    signal_update,
)

from .conftest import CAR_MAC, CAR_MAC_LABEL, DRIVER_A, DRIVER_B, PHONE_A, PHONE_B, set_paired


@pytest.fixture
def runtime(hass: HomeAssistant) -> VehicleStateRuntime:
    rt = VehicleStateRuntime(
        hass=hass,
        entry_id="entry1",
        car_name="Honda Civic",
        car_mac=CAR_MAC,
        driver_entities=[PHONE_A, PHONE_B],
        driver_names={PHONE_A: DRIVER_A, PHONE_B: DRIVER_B},
    )
    yield rt
    rt.async_stop()


def test_normalize_mac_extracts_canonical_form() -> None:
    assert _normalize_mac("00:4E:10:51:0C:00 (Honda)") == "00:4E:10:51:0C:00"
    assert _normalize_mac("dc:0d:30:81:34:8d") == "DC:0D:30:81:34:8D"
    assert _normalize_mac("DC-0D-30-81-34-8D") == "DC-0D-30-81-34-8D"
    assert _normalize_mac("garbage no mac here") == "GARBAGE NO MAC HERE"
    assert _normalize_mac("") == ""


def test_signal_update_includes_entry_id() -> None:
    assert signal_update("abc") == "vehicle_bt_tracker_update_abc"


def test_from_config_normalizes_mac_and_copies_data(hass: HomeAssistant) -> None:
    runtime = VehicleStateRuntime.from_config(
        hass,
        "e1",
        {
            "car_name": "X",
            "car_mac": "aa:bb:cc:dd:ee:ff (Tag)",
            "driver_entities": [PHONE_A],
            "driver_names": {PHONE_A: "A"},
        },
    )
    assert runtime.car_mac == "AA:BB:CC:DD:EE:FF"
    assert runtime.driver_entities == [PHONE_A]
    assert runtime.driver_names == {PHONE_A: "A"}


async def test_initial_eval_idle_when_no_phones_connected(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])

    runtime.async_start()
    await hass.async_block_till_done()

    assert not runtime.is_driving
    assert runtime.active_driver_entity is None


async def test_initial_eval_silent_even_if_already_driving(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    """Recovery on startup must not synthesize a phantom drive_started event."""
    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    started: list = []
    hass.bus.async_listen(EVENT_DRIVE_STARTED, lambda e: started.append(e))

    runtime.async_start()
    await hass.async_block_till_done()

    assert runtime.is_driving is True
    assert runtime.active_driver_entity == PHONE_A
    assert started == []


async def test_drive_started_event_on_connect(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])
    runtime.async_start()
    await hass.async_block_till_done()

    started: list = []
    hass.bus.async_listen(EVENT_DRIVE_STARTED, lambda e: started.append(e))

    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    await hass.async_block_till_done()

    assert len(started) == 1
    assert started[0].data["driver"] == DRIVER_A
    assert started[0].data["car_name"] == "Honda Civic"
    assert started[0].data["entry_id"] == "entry1"
    assert runtime.is_driving
    assert runtime.last_driver == DRIVER_A
    assert runtime.drive_start_time is not None


async def test_drive_ended_event_with_duration(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])
    runtime.async_start()
    await hass.async_block_till_done()

    # Pin a deterministic start time, then drive forward 5 minutes before the end.
    start = dt_util.utcnow()

    ended: list = []
    hass.bus.async_listen(EVENT_DRIVE_ENDED, lambda e: ended.append(e))

    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    await hass.async_block_till_done()
    assert runtime.is_driving

    # Force drive_start_time so duration math is predictable.
    runtime.drive_start_time = start - timedelta(minutes=5)
    set_paired(hass, PHONE_A, [])
    await hass.async_block_till_done()

    assert not runtime.is_driving
    assert len(ended) == 1
    assert ended[0].data["driver"] == DRIVER_A
    assert ended[0].data["duration_minutes"] >= 5.0
    assert runtime.last_drive_duration_minutes >= 5.0


async def test_smart_handoff_keeps_active_driver_when_both_connected(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])
    runtime.async_start()
    await hass.async_block_till_done()

    # A connects first.
    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    await hass.async_block_till_done()
    assert runtime.active_driver_entity == PHONE_A

    # B joins; A is still connected → A stays the active driver.
    set_paired(hass, PHONE_B, [CAR_MAC_LABEL])
    await hass.async_block_till_done()
    assert runtime.active_driver_entity == PHONE_A


async def test_handoff_when_active_driver_disconnects_but_passenger_stays(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    set_paired(hass, PHONE_A, [])
    set_paired(hass, PHONE_B, [])
    runtime.async_start()
    await hass.async_block_till_done()

    set_paired(hass, PHONE_A, [CAR_MAC_LABEL])
    set_paired(hass, PHONE_B, [CAR_MAC_LABEL])
    await hass.async_block_till_done()
    assert runtime.active_driver_entity == PHONE_A

    ended: list = []
    hass.bus.async_listen(EVENT_DRIVE_ENDED, lambda e: ended.append(e))

    # A leaves; B still connected → drive continues with B as active driver,
    # no drive_ended event fires.
    set_paired(hass, PHONE_A, [])
    await hass.async_block_till_done()

    assert runtime.is_driving
    assert runtime.active_driver_entity == PHONE_B
    assert runtime.last_driver == DRIVER_B
    assert ended == []


async def test_mac_match_is_case_insensitive(hass: HomeAssistant) -> None:
    runtime = VehicleStateRuntime(
        hass=hass,
        entry_id="entry1",
        car_name="X",
        car_mac="00:4E:10:51:0C:00",
        driver_entities=[PHONE_A],
        driver_names={},
    )
    # Phone advertises the MAC in lower case with extra label.
    set_paired(hass, PHONE_A, ["00:4e:10:51:0c:00 (honda)"])
    runtime.async_start()
    await hass.async_block_till_done()
    assert runtime.is_driving
    runtime.async_stop()


async def test_paired_devices_can_be_string_attribute(hass: HomeAssistant) -> None:
    runtime = VehicleStateRuntime(
        hass=hass,
        entry_id="entry1",
        car_name="X",
        car_mac=CAR_MAC,
        driver_entities=[PHONE_A],
        driver_names={},
    )
    set_paired(hass, PHONE_A, CAR_MAC_LABEL)  # str, not list
    runtime.async_start()
    await hass.async_block_till_done()
    assert runtime.is_driving
    runtime.async_stop()


async def test_missing_paired_devices_attribute_is_disconnected(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    set_paired(hass, PHONE_A, None)  # attribute missing entirely
    set_paired(hass, PHONE_B, None)
    runtime.async_start()
    await hass.async_block_till_done()
    assert not runtime.is_driving


async def test_driver_display_name_falls_back_to_friendly_name(
    hass: HomeAssistant,
) -> None:
    runtime = VehicleStateRuntime(
        hass=hass,
        entry_id="entry1",
        car_name="X",
        car_mac=CAR_MAC,
        driver_entities=[PHONE_A],
        driver_names={},  # nothing configured
    )
    hass.states.async_set(PHONE_A, "Connected", {"friendly_name": "Pixel 8 Pro"})
    assert runtime.driver_display_name(PHONE_A) == "Pixel 8 Pro"
    assert runtime.driver_display_name(None) == "Unknown"


async def test_apply_restored_state_seeds_runtime(
    hass: HomeAssistant, runtime: VehicleStateRuntime
) -> None:
    moment = dt_util.utcnow() - timedelta(minutes=12)
    runtime.apply_restored_state(
        is_driving=True,
        active_driver_entity=PHONE_A,
        drive_start_time=moment,
        last_driver=DRIVER_A,
        last_drive_duration_minutes=42.0,
    )
    assert runtime.is_driving is True
    assert runtime.active_driver_entity == PHONE_A
    assert runtime.drive_start_time == moment
    assert runtime.last_driver == DRIVER_A
    assert runtime.last_drive_duration_minutes == 42.0


async def test_async_start_warns_when_driver_entity_missing(
    hass: HomeAssistant, caplog
) -> None:
    """Setting up with a non-existent driver entity logs a warning, not a crash."""
    caplog.set_level("WARNING", logger="custom_components.vehicle_bt_tracker.vehicle_state")
    runtime = VehicleStateRuntime(
        hass=hass,
        entry_id="entry1",
        car_name="Honda Civic",
        car_mac=CAR_MAC,
        driver_entities=["sensor.does_not_exist"],
        driver_names={},
    )
    runtime.async_start()
    await hass.async_block_till_done()
    runtime.async_stop()

    assert any(
        "does not exist" in r.message and "sensor.does_not_exist" in r.message
        for r in caplog.records
    )


async def test_async_start_warns_when_driver_entity_lacks_attribute(
    hass: HomeAssistant, caplog
) -> None:
    """Selecting a non-Bluetooth sensor logs a clear warning at startup."""
    caplog.set_level("WARNING", logger="custom_components.vehicle_bt_tracker.vehicle_state")
    hass.states.async_set("sensor.outdoor_temperature", "21.4", {"unit": "°C"})

    runtime = VehicleStateRuntime(
        hass=hass,
        entry_id="entry1",
        car_name="Honda Civic",
        car_mac=CAR_MAC,
        driver_entities=["sensor.outdoor_temperature"],
        driver_names={},
    )
    runtime.async_start()
    await hass.async_block_till_done()
    runtime.async_stop()

    assert any(
        "connected_paired_devices" in r.message
        and "sensor.outdoor_temperature" in r.message
        for r in caplog.records
    )


