"""The Vehicle Bluetooth Tracker integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .vehicle_state import VehicleStateRuntime

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vehicle Bluetooth Tracker from a config entry."""
    merged = {**entry.data, **entry.options}
    runtime = VehicleStateRuntime.from_config(hass, entry.entry_id, merged)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listener subscription happens here; the primary status sensor may seed
    # restored state shortly after via runtime.apply_restored_state().
    runtime.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime: VehicleStateRuntime = hass.data[DOMAIN].pop(entry.entry_id)
        runtime.async_stop()
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change so new driver list/MAC takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
