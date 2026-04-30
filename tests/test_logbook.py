"""Tests for the logbook event describer."""
from __future__ import annotations

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant

from custom_components.vehicle_bt_tracker.const import (
    DOMAIN,
    EVENT_DRIVE_ENDED,
    EVENT_DRIVE_STARTED,
)
from custom_components.vehicle_bt_tracker.logbook import async_describe_events

from .conftest import DRIVER_A, DRIVER_B, PHONE_A


def _collect_describers(hass: HomeAssistant) -> dict:
    """Run async_describe_events and capture (event_type → callback) pairs."""
    captured: dict = {}

    def capture(domain: str, event_type: str, fn) -> None:
        assert domain == DOMAIN
        captured[event_type] = fn

    async_describe_events(hass, capture)
    return captured


async def test_drive_started_describer(hass: HomeAssistant) -> None:
    describers = _collect_describers(hass)
    event = Event(
        EVENT_DRIVE_STARTED,
        {
            "entry_id": "e1",
            "car_name": "Honda Civic",
            "driver": DRIVER_A,
            "driver_entity": PHONE_A,
        },
    )
    msg = describers[EVENT_DRIVE_STARTED](event)
    assert msg[LOGBOOK_ENTRY_NAME] == "Honda Civic"
    assert DRIVER_A in msg[LOGBOOK_ENTRY_MESSAGE]
    assert "started" in msg[LOGBOOK_ENTRY_MESSAGE].lower()


async def test_drive_ended_describer_includes_duration(
    hass: HomeAssistant,
) -> None:
    describers = _collect_describers(hass)
    event = Event(
        EVENT_DRIVE_ENDED,
        {
            "entry_id": "e1",
            "car_name": "Honda Civic",
            "driver": DRIVER_B,
            "duration_minutes": 23.4,
        },
    )
    msg = describers[EVENT_DRIVE_ENDED](event)
    assert msg[LOGBOOK_ENTRY_NAME] == "Honda Civic"
    body = msg[LOGBOOK_ENTRY_MESSAGE]
    assert DRIVER_B in body
    assert "23.4" in body
