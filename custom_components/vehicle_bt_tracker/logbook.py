"""Logbook describer for Vehicle Bluetooth Tracker drive events."""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_DRIVE_ENDED, EVENT_DRIVE_STARTED


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict]], None],
) -> None:
    """Register human-readable summaries for the integration's drive events."""

    @callback
    def describe_started(event: Event) -> dict:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: data.get("car_name", "Vehicle"),
            LOGBOOK_ENTRY_MESSAGE: f"started driving with {data.get('driver', 'unknown driver')}",
        }

    @callback
    def describe_ended(event: Event) -> dict:
        data = event.data
        duration = data.get("duration_minutes", 0.0)
        driver = data.get("driver", "unknown driver")
        return {
            LOGBOOK_ENTRY_NAME: data.get("car_name", "Vehicle"),
            LOGBOOK_ENTRY_MESSAGE: f"finished a drive with {driver} ({duration:.1f} min)",
        }

    async_describe_event(DOMAIN, EVENT_DRIVE_STARTED, describe_started)
    async_describe_event(DOMAIN, EVENT_DRIVE_ENDED, describe_ended)
