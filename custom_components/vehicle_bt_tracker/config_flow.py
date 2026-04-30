"""Config and options flow for Vehicle Bluetooth Tracker."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .const import (
    CONF_CAR_MAC,
    CONF_CAR_NAME,
    CONF_DRIVER_DEVICES,
    CONF_DRIVER_ENTITIES,
    CONF_DRIVER_NAMES,
    DEFAULT_CAR_NAME,
    DOMAIN,
)

_NO_DEVICES_FOUND = "__manual__"

_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}[:\-]){5}([0-9A-Fa-f]{2})")


def _mac_uid(label: str) -> str:
    """Extract a stable 12-char uppercase hex MAC from a paired-device label.

    Used as the config-entry unique_id so entries with ':' and '-' separators
    (or with a friendly-name suffix like '(CarName)') all map to the same key.
    """
    m = _MAC_RE.search(label or "")
    if m:
        return re.sub(r"[:\-]", "", m.group(0)).upper()
    return (label or "").upper()

# Hints used to identify the Bluetooth Connection sensor in the entity registry.
# The Companion App sets the unique_id to something like
# "<device_id>_bluetooth_connection" on both iOS and Android.
_BT_UNIQUE_ID_HINTS = ("bluetooth_connection",)
# Fallback: accept any entity on the device that exposes either BT attribute.
_BT_SENSOR_ATTRS = ("paired_devices", "connected_paired_devices")


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def _find_bt_sensor(hass: HomeAssistant, device_id: str) -> str | None:
    """Return the Bluetooth Connection sensor entity_id for a mobile_app device.

    First pass: match by unique_id containing 'bluetooth_connection'.
    Second pass: any entity on this device whose current state has BT attributes.
    Returns None if nothing is found (sensor not enabled / not yet registered).
    """
    entity_reg = er.async_get(hass)
    entries = er.async_entries_for_device(entity_reg, device_id)

    for entry in entries:
        uid = (entry.unique_id or "").lower()
        eid = (entry.entity_id or "").lower()
        if any(hint in uid or hint in eid for hint in _BT_UNIQUE_ID_HINTS):
            return entry.entity_id

    for entry in entries:
        state = hass.states.get(entry.entity_id)
        if state and any(attr in state.attributes for attr in _BT_SENSOR_ATTRS):
            return entry.entity_id

    return None


def _device_name(hass: HomeAssistant, device_id: str) -> str:
    """Return the human-readable name of a device registry entry."""
    device_reg = dr.async_get(hass)
    device = device_reg.async_get(device_id)
    if device is None:
        return device_id
    return device.name_by_user or device.name or device_id


def _resolve_devices(
    hass: HomeAssistant, device_ids: list[str]
) -> tuple[dict[str, str], list[str]]:
    """Map each device_id to its BT sensor entity_id.

    Returns (resolved, failed_names) where *resolved* is the device→entity
    mapping and *failed_names* is a list of human-readable device names for
    which no BT sensor could be found (sensor not yet enabled on the phone).
    """
    resolved: dict[str, str] = {}
    failed: list[str] = []
    for device_id in device_ids:
        entity_id = _find_bt_sensor(hass, device_id)
        if entity_id:
            resolved[device_id] = entity_id
        else:
            failed.append(_device_name(hass, device_id))
    return resolved, failed


def _gather_paired_devices(
    hass: HomeAssistant, entity_ids: list[str]
) -> set[str]:
    """Pool paired_devices attributes from each resolved BT sensor."""
    devices: set[str] = set()
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state is None:
            continue
        raw = state.attributes.get("paired_devices")
        if isinstance(raw, list):
            devices.update(str(item) for item in raw)
        elif isinstance(raw, str):
            devices.add(raw)
    return devices


def _driver_names_schema(
    hass: HomeAssistant,
    device_to_entity: dict[str, str],
    existing_names: dict[str, str] | None = None,
) -> vol.Schema:
    """Build a schema with one name field per driver.

    Field key = entity_id (used as the config key); default = existing name or
    the phone's device name, so the user only has to confirm rather than type.
    """
    existing = existing_names or {}
    fields: dict = {}
    for device_id, entity_id in device_to_entity.items():
        default = existing.get(entity_id) or _device_name(hass, device_id)
        fields[vol.Required(entity_id, default=default)] = str
    return vol.Schema(fields)


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class VehicleTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Three-step config flow: device pick → driver names → car MAC."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        # device_id → resolved entity_id, populated after step 1
        self._device_to_entity: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: vehicle name + Companion App device multi-select."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            chosen = user_input.get(CONF_DRIVER_DEVICES) or []
            if not chosen:
                errors["base"] = "no_drivers"
            else:
                resolved, failed = _resolve_devices(self.hass, chosen)
                if failed:
                    errors["base"] = "bt_sensor_not_found"
                    placeholders["devices"] = ", ".join(failed)
                else:
                    self._device_to_entity = resolved
                    self._data.update(user_input)
                    self._data[CONF_DRIVER_ENTITIES] = list(resolved.values())
                    return await self.async_step_driver_names()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CAR_NAME, default=DEFAULT_CAR_NAME): str,
                    vol.Required(CONF_DRIVER_DEVICES): selector.DeviceSelector(
                        selector.DeviceSelectorConfig(
                            integration="mobile_app",
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_driver_names(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: confirm or override the display name for each driver.

        Defaults to the phone's device name so users rarely need to type.
        """
        if user_input is not None:
            self._data[CONF_DRIVER_NAMES] = {
                eid: name.strip()
                for eid, name in user_input.items()
                if name.strip()
            }
            return await self.async_step_select_car()

        return self.async_show_form(
            step_id="driver_names",
            data_schema=_driver_names_schema(self.hass, self._device_to_entity),
        )

    async def async_step_select_car(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3: pick the vehicle's MAC from the pooled paired-device list."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input[CONF_CAR_MAC]
            if mac == _NO_DEVICES_FOUND:
                errors["base"] = "no_paired_devices"
            else:
                self._data[CONF_CAR_MAC] = mac
                await self.async_set_unique_id(_mac_uid(mac))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self._data[CONF_CAR_NAME], data=self._data
                )

        pool = _gather_paired_devices(self.hass, self._data[CONF_DRIVER_ENTITIES])
        choices = (
            {d: d for d in sorted(pool)}
            if pool
            else {_NO_DEVICES_FOUND: "No paired devices found — pair the phone with the car first"}
        )

        return self.async_show_form(
            step_id="select_car",
            data_schema=vol.Schema({vol.Required(CONF_CAR_MAC): vol.In(choices)}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return VehicleTrackerOptionsFlow(entry)


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

class VehicleTrackerOptionsFlow(OptionsFlow):
    """Re-pick driver devices, names, and the car MAC without deleting the entry."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._working: dict[str, Any] = {}
        self._device_to_entity: dict[str, str] = {}

    def _current(self, key: str, fallback: Any = None) -> Any:
        """Read from options first, fall back to original data."""
        return self._entry.options.get(key, self._entry.data.get(key, fallback))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: re-select Companion App devices."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            chosen = user_input.get(CONF_DRIVER_DEVICES) or []
            if not chosen:
                errors["base"] = "no_drivers"
            else:
                resolved, failed = _resolve_devices(self.hass, chosen)
                if failed:
                    errors["base"] = "bt_sensor_not_found"
                    placeholders["devices"] = ", ".join(failed)
                else:
                    self._device_to_entity = resolved
                    self._working[CONF_DRIVER_DEVICES] = chosen
                    self._working[CONF_DRIVER_ENTITIES] = list(resolved.values())
                    return await self.async_step_driver_names()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DRIVER_DEVICES,
                        default=self._current(CONF_DRIVER_DEVICES, []),
                    ): selector.DeviceSelector(
                        selector.DeviceSelectorConfig(
                            integration="mobile_app",
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_driver_names(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: confirm or override driver display names."""
        existing_names: dict[str, str] = self._current(CONF_DRIVER_NAMES, {}) or {}

        if user_input is not None:
            self._working[CONF_DRIVER_NAMES] = {
                eid: name.strip()
                for eid, name in user_input.items()
                if name.strip()
            }
            return await self.async_step_select_car()

        return self.async_show_form(
            step_id="driver_names",
            data_schema=_driver_names_schema(
                self.hass, self._device_to_entity, existing_names=existing_names
            ),
        )

    async def async_step_select_car(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3: re-pick or confirm the vehicle MAC."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input[CONF_CAR_MAC]
            if mac == _NO_DEVICES_FOUND:
                errors["base"] = "no_paired_devices"
            else:
                self._working[CONF_CAR_MAC] = mac
                return self.async_create_entry(title="", data=self._working)

        pool = _gather_paired_devices(
            self.hass, self._working[CONF_DRIVER_ENTITIES]
        )
        current_mac = self._current(CONF_CAR_MAC)
        if current_mac:
            pool.add(current_mac)

        choices = (
            {d: d for d in sorted(pool)}
            if pool
            else {_NO_DEVICES_FOUND: "No paired devices found on selected phones"}
        )

        return self.async_show_form(
            step_id="select_car",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CAR_MAC,
                        default=current_mac if current_mac in choices else vol.UNDEFINED,
                    ): vol.In(choices)
                }
            ),
            errors=errors,
        )
