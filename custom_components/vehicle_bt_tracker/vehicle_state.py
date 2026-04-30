"""Shared runtime state machine for a single configured vehicle.

One instance per config entry. All platform entities (sensor, binary_sensor)
read from this object and re-render whenever it dispatches its update signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
import re

from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CAR_MAC,
    CONF_CAR_NAME,
    CONF_DRIVER_ENTITIES,
    CONF_DRIVER_NAMES,
    DOMAIN,
    EVENT_DRIVE_ENDED,
    EVENT_DRIVE_STARTED,
)

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})")
_PAIRED_ATTR = "connected_paired_devices"


def _normalize_mac(value: str) -> str:
    """Extract a MAC from arbitrary text, strip separators, and uppercase.

    Produces a 12-char hex string (e.g. "AA4E10510C00") so that MACs using ":"
    separators and those using "-" separators compare equal.
    """
    match = _MAC_RE.search(value or "")
    if match:
        return re.sub(r"[:\-]", "", match.group(0)).upper()
    return re.sub(r"[:\-]", "", value or "").upper()


def signal_update(entry_id: str) -> str:
    """Dispatcher signal for entity refresh."""
    return f"{DOMAIN}_update_{entry_id}"


@dataclass
class VehicleStateRuntime:
    """State machine + listener wiring for one vehicle config entry."""

    hass: HomeAssistant
    entry_id: str
    car_name: str
    car_mac: str
    driver_entities: list[str]
    driver_names: dict[str, str]

    is_driving: bool = False
    active_driver_entity: str | None = None
    drive_start_time: datetime | None = None
    last_driver: str = "Unknown"
    last_drive_duration_minutes: float = 0.0

    _unsub: callable | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_config(
        cls, hass: HomeAssistant, entry_id: str, data: dict
    ) -> "VehicleStateRuntime":
        """Build a runtime from a merged config-entry data dict."""
        return cls(
            hass=hass,
            entry_id=entry_id,
            car_name=data[CONF_CAR_NAME],
            car_mac=_normalize_mac(data[CONF_CAR_MAC]),
            driver_entities=list(data[CONF_DRIVER_ENTITIES]),
            driver_names=dict(data.get(CONF_DRIVER_NAMES) or {}),
        )

    @callback
    def async_start(self) -> None:
        """Subscribe to driver-sensor state changes and run a silent initial eval.

        The initial evaluation never fires logbook events: at startup we are
        recovering ground truth, not transitioning. Real transitions are only
        emitted on subsequent listener-driven evaluations.
        """
        self._warn_about_misconfigured_drivers()
        self._unsub = async_track_state_change_event(
            self.hass, self.driver_entities, self._async_state_changed
        )
        self._evaluate(fire_events=False)

    def _warn_about_misconfigured_drivers(self) -> None:
        """Log a one-shot warning if any configured driver entity isn't a BT sensor."""
        for entity_id in self.driver_entities:
            state = self.hass.states.get(entity_id)
            if state is None:
                _LOGGER.warning(
                    "%s: configured driver entity %s does not exist; "
                    "the car will never appear driven through this entity",
                    self.car_name,
                    entity_id,
                )
            elif "connected_paired_devices" not in state.attributes:
                _LOGGER.warning(
                    "%s: configured driver entity %s has no "
                    "`connected_paired_devices` attribute. Pick the Companion "
                    "App's Bluetooth Connection sensor, not %s",
                    self.car_name,
                    entity_id,
                    entity_id,
                )

    @callback
    def async_stop(self) -> None:
        """Tear down listeners (called on config entry unload)."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def apply_restored_state(
        self,
        *,
        is_driving: bool,
        active_driver_entity: str | None,
        drive_start_time: datetime | None,
        last_driver: str,
        last_drive_duration_minutes: float,
    ) -> None:
        """Seed runtime from RestoreEntity so a restart mid-drive continues cleanly."""
        self.is_driving = is_driving
        self.active_driver_entity = active_driver_entity
        self.drive_start_time = drive_start_time
        self.last_driver = last_driver
        self.last_drive_duration_minutes = last_drive_duration_minutes

    def driver_display_name(self, entity_id: str | None) -> str:
        """Resolve a driver entity to its configured display name."""
        if entity_id is None:
            return "Unknown"
        if entity_id in self.driver_names:
            return self.driver_names[entity_id]
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    @callback
    def _async_state_changed(self, _event: Event) -> None:
        self._evaluate(fire_events=True)

    @callback
    def _evaluate(self, *, fire_events: bool) -> None:
        """Recompute is_driving / active_driver and emit events on transitions."""
        connected = [
            entity_id
            for entity_id in self.driver_entities
            if self._is_connected(self.hass.states.get(entity_id))
        ]

        was_driving = self.is_driving
        prev_driver = self.active_driver_entity

        if connected:
            # Smart handoff: keep current driver if still connected, else pick first.
            if self.active_driver_entity in connected:
                new_driver = self.active_driver_entity
            else:
                new_driver = connected[0]
            new_is_driving = True
        else:
            new_driver = None
            new_is_driving = False

        if fire_events:
            if not was_driving and new_is_driving:
                self._on_drive_started(new_driver)
            elif was_driving and not new_is_driving:
                self._on_drive_ended(prev_driver)
            elif was_driving and new_is_driving and new_driver != prev_driver:
                # Driver swap mid-drive: log the handoff but keep the drive going.
                self.last_driver = self.driver_display_name(new_driver)
                _LOGGER.debug(
                    "%s: driver swap mid-drive %s -> %s",
                    self.car_name,
                    prev_driver,
                    new_driver,
                )

        self.is_driving = new_is_driving
        self.active_driver_entity = new_driver

        async_dispatcher_send(self.hass, signal_update(self.entry_id))

    def _on_drive_started(self, driver_entity: str | None) -> None:
        self.drive_start_time = dt_util.utcnow()
        self.last_driver = self.driver_display_name(driver_entity)
        self.hass.bus.async_fire(
            EVENT_DRIVE_STARTED,
            {
                "entry_id": self.entry_id,
                "car_name": self.car_name,
                "driver": self.last_driver,
                "driver_entity": driver_entity,
            },
        )
        _LOGGER.debug("%s: drive started by %s", self.car_name, self.last_driver)

    def _on_drive_ended(self, driver_entity: str | None) -> None:
        duration_min = 0.0
        if self.drive_start_time is not None:
            duration_min = round(
                (dt_util.utcnow() - self.drive_start_time).total_seconds() / 60.0, 1
            )
        self.last_drive_duration_minutes = duration_min
        ended_by = self.driver_display_name(driver_entity) if driver_entity else self.last_driver
        self.hass.bus.async_fire(
            EVENT_DRIVE_ENDED,
            {
                "entry_id": self.entry_id,
                "car_name": self.car_name,
                "driver": ended_by,
                "duration_minutes": duration_min,
            },
        )
        self.drive_start_time = None
        _LOGGER.debug(
            "%s: drive ended after %.1f min (driver=%s)",
            self.car_name,
            duration_min,
            ended_by,
        )

    def _is_connected(self, state: State | None) -> bool:
        if state is None:
            return False
        raw = state.attributes.get(_PAIRED_ATTR)
        if raw is None:
            return False
        if isinstance(raw, list):
            return any(self.car_mac in _normalize_mac(str(item)) for item in raw)
        if isinstance(raw, str):
            return self.car_mac in _normalize_mac(raw)
        return False
