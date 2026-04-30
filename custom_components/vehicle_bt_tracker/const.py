"""Constants for the Vehicle Bluetooth Tracker integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "vehicle_bt_tracker"

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

CONF_CAR_NAME = "car_name"
CONF_CAR_MAC = "car_mac"
CONF_DRIVER_DEVICES = "driver_devices"   # list of HA device IDs (from mobile_app)
CONF_DRIVER_ENTITIES = "driver_entities"  # list of resolved BT sensor entity IDs
CONF_DRIVER_NAMES = "driver_names"

DEFAULT_CAR_NAME = "Vehicle"

STATE_IDLE = "idle"

ATTR_LAST_DRIVER = "last_driver"
ATTR_DRIVE_START_TIME = "drive_start_time"
ATTR_LAST_DRIVE_DURATION = "last_drive_duration_minutes"
ATTR_MONITORED_MAC = "monitored_mac"
ATTR_ACTIVE_DRIVER_ENTITY = "active_driver_entity"

EVENT_DRIVE_STARTED = f"{DOMAIN}_drive_started"
EVENT_DRIVE_ENDED = f"{DOMAIN}_drive_ended"
