"""Tado CE Sensors."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DATA_DIR
from .device_manager import get_hub_device_info, get_zone_device_info
from .data_loader import (
    load_zones_file, load_zones_info_file, load_weather_file,
    load_config_file, load_ratelimit_file, load_api_call_history_file,
    get_zone_names as dl_get_zone_names
)
from .immediate_refresh_handler import SIGNAL_ZONES_UPDATED

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

# Weather state mapping
WEATHER_STATE_MAP = {
    "CLOUDY_MOSTLY": "Mostly Cloudy",
    "CLOUDY_PARTLY": "Partly Cloudy",
    "CLOUDY": "Cloudy",
    "DRIZZLE": "Drizzle",
    "FOGGY": "Foggy",
    "NIGHT_CLEAR": "Clear Night",
    "NIGHT_CLOUDY": "Cloudy Night",
    "RAIN": "Rain",
    "SCATTERED_RAIN": "Scattered Rain",
    "SNOW": "Snow",
    "SUN": "Sunny",
    "THUNDERSTORMS": "Thunderstorms",
    "WINDY": "Windy",
}

# Cached home_id to avoid blocking calls in event loop
_CACHED_HOME_ID = None

def _load_home_id():
    """Load home ID from config file (blocking, run in executor)."""
    config = load_config_file()
    return config.get('home_id', 'unknown') if config else 'unknown'

def get_zone_names():
    """Load zone names from API data."""
    return dl_get_zone_names()

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up Tado CE sensors from a config entry."""
    # Load home_id in executor to avoid blocking event loop
    global _CACHED_HOME_ID
    _CACHED_HOME_ID = await hass.async_add_executor_job(_load_home_id)
    
    # Get configuration manager from hass data
    from .config_manager import ConfigurationManager
    config_manager = ConfigurationManager(entry)
    
    zone_names = await hass.async_add_executor_job(get_zone_names)
    
    sensors = []
    
    # Hub sensors (API status, home info)
    sensors.append(TadoHomeIdSensor())
    sensors.append(TadoApiUsageSensor())
    sensors.append(TadoApiLimitSensor())
    sensors.append(TadoApiResetSensor())
    sensors.append(TadoApiStatusSensor())
    sensors.append(TadoTokenStatusSensor())
    sensors.append(TadoZoneCountSensor())
    sensors.append(TadoLastSyncSensor())
    
    # API Monitoring Sensors (Discussion #86, Issue #65)
    sensors.append(TadoNextSyncSensor())
    sensors.append(TadoPollingIntervalSensor())
    sensors.append(TadoCallHistorySensor())
    sensors.append(TadoApiCallBreakdownSensor())
    
    # Boiler Flow Temperature sensor (Hub device - only if data available)
    # This requires OpenTherm connection between Tado and boiler
    if await hass.async_add_executor_job(_has_boiler_flow_temperature_data):
        _LOGGER.info("Boiler flow temperature data detected - creating sensor")
        sensors.append(TadoBoilerFlowTemperatureSensor())
    else:
        _LOGGER.debug("No boiler flow temperature data found - sensor not created (requires OpenTherm)")
    
    # Weather sensors (optional based on configuration)
    if config_manager.get_weather_enabled():
        sensors.append(TadoOutsideTemperatureSensor())
        sensors.append(TadoSolarIntensitySensor())
        sensors.append(TadoWeatherStateSensor())
    
    # Zone sensors
    try:
        zones_data = await hass.async_add_executor_job(load_zones_file)
        zones_info = await hass.async_add_executor_job(load_zones_info_file)
        
        # Build zone type map
        zone_types = {}
        if zones_info:
            zone_types = {str(z.get('id')): z.get('type', 'HEATING') for z in zones_info}
        
        # Build zone TRV map - check if zone has TRV device (VA02, RU01, VA01)
        # Only zones with TRVs should have Smart Comfort sensors
        zones_with_trv = set()
        TRV_DEVICE_TYPES = {'VA02', 'VA01', 'RU01', 'RU02'}  # V3+ and V2 TRVs
        if zones_info:
            for zone in zones_info:
                zone_id = str(zone.get('id'))
                devices = zone.get('devices', [])
                for device in devices:
                    if device.get('deviceType') in TRV_DEVICE_TYPES:
                        zones_with_trv.add(zone_id)
                        break
        
        if zones_with_trv:
            _LOGGER.debug(f"Zones with TRV devices: {zones_with_trv}")
        
        if zones_data:
            # Use 'or {}' pattern for null safety
            zone_states = zones_data.get('zoneStates') or {}
            for zone_id, zone_data in zone_states.items():
                zone_type = zone_types.get(zone_id, 'HEATING')
                zone_name = zone_names.get(zone_id, f"Zone {zone_id}")
                
                # Check if zone has temperature sensor data
                # Use 'or {}' pattern for null safety
                sensor_data = zone_data.get('sensorDataPoints') or {}
                inside_temp = sensor_data.get('insideTemperature') or {}
                has_temperature = inside_temp.get('celsius') is not None
                
                if zone_type == 'HEATING':
                    sensors.extend([
                        TadoTemperatureSensor(zone_id, zone_name, zone_type),
                        TadoHumiditySensor(zone_id, zone_name, zone_type),
                        TadoHeatingPowerSensor(zone_id, zone_name, zone_type),
                        TadoTargetTempSensor(zone_id, zone_name, zone_type),
                        TadoOverlaySensor(zone_id, zone_name, zone_type),
                        # v1.9.0: Environment sensors (always enabled)
                        TadoMoldRiskSensor(zone_id, zone_name, zone_type),
                        TadoComfortLevelSensor(zone_id, zone_name, zone_type),
                    ])
                    # v1.11.0: Thermal Analytics sensors (only for zones with TRV devices)
                    # SU02 (Smart Thermostat) doesn't have TRV, so no thermal analytics
                    heating_cycle_coordinator = hass.data.get(DOMAIN, {}).get('heating_cycle_coordinator')
                    if zone_id in zones_with_trv:
                        if heating_cycle_coordinator:
                            sensors.extend([
                                TadoThermalInertiaSensor(heating_cycle_coordinator, zone_id, zone_name, zone_type),
                                TadoAvgHeatingRateSensor(heating_cycle_coordinator, zone_id, zone_name, zone_type),
                                TadoPreheatTimeSensor(heating_cycle_coordinator, zone_id, zone_name, zone_type),
                                TadoAnalysisConfidenceSensor(heating_cycle_coordinator, zone_id, zone_name, zone_type),
                                TadoHeatingAccelerationSensor(heating_cycle_coordinator, zone_id, zone_name, zone_type),
                                TadoApproachFactorSensor(heating_cycle_coordinator, zone_id, zone_name, zone_type),
                            ])
                        else:
                            _LOGGER.warning(f"Zone {zone_name} has TRV but HeatingCycleCoordinator not available - thermal analytics sensors not created")
                    # v1.9.0: Smart Comfort sensors (opt-in)
                    # v1.11.0: Removed TadoThermalRateSensor, TadoTimeToTargetSensor (replaced by heating cycle analysis)
                    if config_manager.get_smart_comfort_enabled():
                        sensors.extend([
                            TadoHistoricalDeviationSensor(zone_id, zone_name, zone_type),
                            TadoNextScheduleTimeSensor(zone_id, zone_name, zone_type),
                            TadoNextScheduleTempSensor(zone_id, zone_name, zone_type),
                            TadoPreheatAdvisorSensor(zone_id, zone_name, zone_type),
                            TadoSmartComfortTargetSensor(zone_id, zone_name, zone_type),
                        ])
                    
                elif zone_type == 'AIR_CONDITIONING':
                    sensors.extend([
                        TadoTemperatureSensor(zone_id, zone_name, zone_type),
                        TadoHumiditySensor(zone_id, zone_name, zone_type),
                        TadoACPowerSensor(zone_id, zone_name, zone_type),
                        TadoTargetTempSensor(zone_id, zone_name, zone_type),
                        TadoOverlaySensor(zone_id, zone_name, zone_type),
                        # v1.9.0: Environment sensors (always enabled)
                        TadoMoldRiskSensor(zone_id, zone_name, zone_type),
                        TadoComfortLevelSensor(zone_id, zone_name, zone_type),
                    ])
                    # v1.9.0: Smart Comfort sensors for AC (opt-in)
                    # v1.11.0: Removed TadoThermalRateSensor, TadoTimeToTargetSensor (replaced by heating cycle analysis)
                    if config_manager.get_smart_comfort_enabled():
                        sensors.extend([
                            TadoHistoricalDeviationSensor(zone_id, zone_name, zone_type),
                            TadoNextScheduleTimeSensor(zone_id, zone_name, zone_type),
                            TadoNextScheduleTempSensor(zone_id, zone_name, zone_type),
                            TadoPreheatAdvisorSensor(zone_id, zone_name, zone_type),
                            TadoSmartComfortTargetSensor(zone_id, zone_name, zone_type),
                        ])
                elif zone_type == 'HOT_WATER':
                    # Only create temperature sensor if zone has temperature data
                    # Many hot water zones (combi boilers) don't have temperature sensors
                    if has_temperature:
                        sensors.append(TadoTemperatureSensor(zone_id, zone_name, zone_type))
                    sensors.append(TadoOverlaySensor(zone_id, zone_name, zone_type))
                    sensors.append(TadoHotWaterPowerSensor(zone_id, zone_name, zone_type))
    except Exception as e:
        _LOGGER.error(f"Failed to load zones: {e}")
    
    # Device sensors (battery + connection) - track seen serials to avoid duplicates
    # Prioritize HEATING zones over HOT_WATER/AIR_CONDITIONING for device assignment (#56)
    try:
        zones_info = await hass.async_add_executor_job(load_zones_info_file)
        if zones_info:
            # Build mapping: serial -> list of (zone_id, zone_name, zone_type, device)
            device_zones: dict[str, list[tuple]] = {}
            for zone in zones_info:
                zone_id = str(zone.get('id'))
                zone_name = zone.get('name', f"Zone {zone_id}")
                zone_type = zone.get('type', 'HEATING')
                for device in zone.get('devices', []):
                    serial = device.get('shortSerialNo')
                    if serial:
                        if serial not in device_zones:
                            device_zones[serial] = []
                        device_zones[serial].append((zone_id, zone_name, zone_type, device))
            
            # For each device, pick the best zone (HEATING > HOT_WATER > AIR_CONDITIONING)
            for serial, zone_list in device_zones.items():
                # Sort by zone type priority: HEATING first
                def zone_priority(item):
                    zone_type = item[2]
                    if zone_type == 'HEATING':
                        return 0
                    elif zone_type == 'AIR_CONDITIONING':
                        return 1
                    else:  # HOT_WATER
                        return 2
                
                zone_list.sort(key=zone_priority)
                zone_id, zone_name, zone_type, device = zone_list[0]
                
                # Battery sensor (if device has battery)
                if 'batteryState' in device:
                    sensors.append(TadoBatterySensor(zone_id, zone_name, zone_type, device, zones_info))
                # Connection sensor (all devices)
                if 'connectionState' in device:
                    sensors.append(TadoDeviceConnectionSensor(zone_id, zone_name, zone_type, device, zones_info))
    except Exception as e:
        _LOGGER.warning(f"Failed to load device info: {e}")
    
    async_add_entities(sensors, True)
    _LOGGER.info(f"Tado CE sensors loaded: {len(sensors)}")


def _has_boiler_flow_temperature_data():
    """Check if any zone has boiler flow temperature data (requires OpenTherm).
    
    This is used during setup to determine if the boiler flow temperature
    sensor should be created. Only systems with OpenTherm connection between
    Tado and the boiler will have this data.
    """
    try:
        # Use data_loader for per-home file support
        data = load_zones_file()
        if not data:
            return False
        
        # Use 'or {}' pattern for null safety
        zone_states = data.get('zoneStates') or {}
        for zone_id, zone_data in zone_states.items():
            # Use 'or {}' pattern for null safety
            activity_data = zone_data.get('activityDataPoints') or {}
            flow_temp = (activity_data.get('boilerFlowTemperature') or {}).get('celsius')
            if flow_temp is not None:
                _LOGGER.debug(f"Found boilerFlowTemperature in zone {zone_id}: {flow_temp}°C")
                return True
        
        return False
    except Exception as e:
        _LOGGER.debug(f"Error checking boiler flow temperature data: {e}")
        return False

# ============ Hub Sensors (Tado CE Hub Device) ============

class TadoHomeIdSensor(SensorEntity):
    """Sensor showing Tado Home ID."""
    
    def __init__(self):
        self._attr_name = "Home ID"
        self._attr_unique_id = "tado_ce_home_id"
        self._attr_icon = "mdi:home"
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            config = load_config_file()
            if config:
                self._attr_native_value = config.get("home_id")
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoApiUsageSensor(SensorEntity):
    """Sensor for Tado API usage tracking."""
    
    def __init__(self):
        self._attr_name = "API Usage"
        self._attr_unique_id = "tado_ce_api_usage"
        self._attr_native_unit_of_measurement = "calls"
        self._attr_state_class = "measurement"
        self._attr_device_info = get_hub_device_info()
        self._attr_available = False
        self._attr_native_value = None
        self._data = {}
        self._call_history = []
    
    @property
    def icon(self):
        status = self._data.get("status")
        if status == "rate_limited":
            return "mdi:api-off"
        elif status == "error":
            return "mdi:alert-circle"
        return "mdi:api"
    
    @property
    def extra_state_attributes(self):
        attrs = {
            "limit": self._data.get("limit"),
            "remaining": self._data.get("remaining"),
            "percentage_used": self._data.get("percentage_used"),
            "last_updated": self._data.get("last_updated"),
            "status": self._data.get("status"),
        }
        
        # Add Test Mode indicator if enabled
        try:
            from .config_manager import ConfigurationManager
            from homeassistant.config_entries import ConfigEntry
            
            # Try to get config entry (this is a bit hacky but works)
            hass = self.hass
            if hass:
                entries = hass.config_entries.async_entries(DOMAIN)
                if entries:
                    config_manager = ConfigurationManager(entries[0])
                    if config_manager.get_test_mode_enabled():
                        attrs["test_mode"] = "Test Mode: 100 call limit"
        except Exception as e:
            _LOGGER.debug(f"Failed to check Test Mode status: {e}")
        
        # Add call history if available
        if self._call_history:
            attrs["call_history"] = self._call_history
        
        return attrs
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            self._data = load_ratelimit_file()
            if self._data:
                used = self._data.get("used")
                if used is not None:
                    self._attr_native_value = int(used)
                    self._attr_available = True
                else:
                    self._attr_available = False
            else:
                self._attr_available = False
            
            # Load call history from tracker and convert to local timezone
            try:
                from .api_call_tracker import APICallTracker
                from .config_manager import ConfigurationManager
                from homeassistant.util import dt as dt_util
                from datetime import datetime
                
                # Get retention days from config
                retention_days = 14  # default
                try:
                    config_manager = ConfigurationManager(None)
                    retention_days = config_manager.get_api_history_retention_days()
                except (AttributeError, TypeError):
                    pass
                
                # Get home_id for per-home file path
                from .data_loader import get_current_home_id
                home_id = get_current_home_id()
                
                tracker = APICallTracker(DATA_DIR, retention_days=retention_days, home_id=home_id)
                raw_history = tracker.get_recent_calls(limit=50)
                
                # Convert timestamps to local timezone for display
                self._call_history = []
                for call in raw_history:
                    call_copy = call.copy()
                    try:
                        # Parse ISO timestamp and convert to local
                        ts = datetime.fromisoformat(call["timestamp"])
                        if ts.tzinfo is None:
                            # Assume UTC if no timezone
                            ts = ts.replace(tzinfo=dt_util.UTC)
                        local_ts = dt_util.as_local(ts)
                        call_copy["timestamp"] = local_ts.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass  # Keep original timestamp if conversion fails
                    self._call_history.append(call_copy)
            except FileNotFoundError:
                _LOGGER.debug("API call history file not found - first run or migration pending")
                self._call_history = []
            except PermissionError:
                _LOGGER.warning("Permission denied reading API call history file")
                self._call_history = []
            except json.JSONDecodeError as e:
                _LOGGER.error(f"Invalid JSON in API call history file: {e}")
                self._call_history = []
            except Exception as e:
                _LOGGER.debug(f"Failed to load call history: {e}")
                self._call_history = []
                
        except FileNotFoundError:
            _LOGGER.debug("Ratelimit file not found - first run or migration pending")
            self._attr_available = False
        except PermissionError:
            _LOGGER.error("Permission denied reading ratelimit file")
            self._attr_available = False
        except json.JSONDecodeError as e:
            _LOGGER.error(f"Invalid JSON in ratelimit file: {e}")
            self._attr_available = False
        except Exception as e:
            _LOGGER.error(f"Unexpected error loading ratelimit data: {e}", exc_info=True)
            self._attr_available = False

class TadoApiResetSensor(SensorEntity):
    """Sensor showing API rate limit reset time."""
    
    def __init__(self):
        self._attr_name = "API Reset"
        self._attr_unique_id = "tado_ce_api_reset"
        self._attr_icon = "mdi:timer-refresh"
        self._attr_device_class = "timestamp"
        self._attr_device_info = get_hub_device_info()
        self._attr_available = False
        self._attr_native_value = None
        self._reset_human = None
        self._reset_seconds = None
        self._reset_at = None  # v1.8.0: Actual reset time string
        self._last_reset = None  # v1.8.0: Last reset time string
        self._status = None
        self._next_poll = None
        self._current_interval = None
    
    @property
    def extra_state_attributes(self):
        return {
            "time_until_reset": self._reset_human,
            "reset_seconds": self._reset_seconds,
            "reset_at": self._reset_at,  # v1.8.0: When next reset will happen
            "last_reset": self._last_reset,  # v1.8.0: When last reset happened
            "status": self._status,
            "next_poll": self._next_poll,
            "current_interval_minutes": self._current_interval,
        }
    
    def update(self):
        try:
            from datetime import datetime, timezone, timedelta
            from homeassistant.util import dt as dt_util
            
            # Use data_loader for per-home file support
            data = load_ratelimit_file()
            if not data:
                self._attr_available = False
                return
                
            self._reset_human = data.get("reset_human")
            self._reset_seconds = data.get("reset_seconds")
            self._status = data.get("status", "unknown")
            
            # v1.8.0: Format reset_at as local time string for attribute
            reset_at = data.get("reset_at")
            if reset_at and reset_at != "unknown":
                try:
                    reset_time = datetime.fromisoformat(reset_at.replace('Z', '+00:00'))
                    self._attr_native_value = reset_time
                    self._attr_available = True
                    # Format as local time for attribute
                    reset_local = dt_util.as_local(reset_time)
                    self._reset_at = reset_local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    _LOGGER.debug(f"Failed to parse reset_at: {e}")
                    self._attr_native_value = None
                    self._attr_available = False
                    self._reset_at = None
            else:
                self._attr_native_value = None
                self._attr_available = False
                self._reset_at = None
            
            # v1.8.0: Format last_reset_utc as local time string for attribute
            last_reset_utc = data.get("last_reset_utc")
            if last_reset_utc:
                try:
                    last_reset_time = datetime.fromisoformat(last_reset_utc.replace('Z', '+00:00'))
                    last_reset_local = dt_util.as_local(last_reset_time)
                    self._last_reset = last_reset_local.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    _LOGGER.debug(f"Failed to parse last_reset_utc: {e}")
                    self._last_reset = None
            else:
                self._last_reset = None
            
            # Calculate next poll time
            try:
                from homeassistant.util import dt as dt_util
                
                last_updated = data.get("last_updated")
                if last_updated:
                    # v1.6.1: Robust timestamp parsing for different formats
                    # - "2026-01-25T12:00:00Z" (legacy tado_api.py)
                    # - "2026-01-25T12:00:00+00:00" (async_api.py v1.6.1+)
                    # - "2026-01-25T12:00:00" (naive, assume UTC)
                    if last_updated.endswith('Z'):
                        last_sync = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    elif '+' in last_updated or last_updated.endswith('00:00'):
                        last_sync = datetime.fromisoformat(last_updated)
                    else:
                        # Naive datetime - assume UTC for backwards compatibility
                        last_sync = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)
                    
                    # Get current polling interval from config
                    from homeassistant.config_entries import ConfigEntry
                    entries = self.hass.config_entries.async_entries(DOMAIN) if self.hass else []
                    if entries:
                        from .config_manager import ConfigurationManager
                        from . import get_polling_interval
                        config_manager = ConfigurationManager(entries[0])
                        self._current_interval = get_polling_interval(config_manager)
                        
                        # Calculate next poll time and convert to local timezone
                        next_poll_time = last_sync + timedelta(minutes=self._current_interval)
                        next_poll_local = dt_util.as_local(next_poll_time)
                        self._next_poll = next_poll_local.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        self._next_poll = None
                        self._current_interval = None
                else:
                    self._next_poll = None
                    self._current_interval = None
            except Exception as e:
                _LOGGER.debug(f"Failed to calculate next poll time: {e}")
                self._next_poll = None
                self._current_interval = None
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update API reset sensor: {e}")
            self._attr_available = False
            self._attr_native_value = None

class TadoApiLimitSensor(SensorEntity):
    """Sensor showing Tado API daily limit."""
    
    def __init__(self):
        self._attr_name = "API Limit"
        self._attr_unique_id = "tado_ce_api_limit"
        self._attr_icon = "mdi:speedometer"
        self._attr_native_unit_of_measurement = "calls"
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            data = load_ratelimit_file()
            if data:
                self._attr_native_value = data.get("limit")
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
            
            # Load recent API calls from history (last 100 calls only to avoid DB size issues)
            try:
                from datetime import datetime, timedelta
                from homeassistant.util import dt as dt_util
                
                history = load_api_call_history_file()
                if history:
                    # Flatten all calls from all dates
                    all_calls = []
                    for date_key, calls in history.items():
                        all_calls.extend(calls)
                    
                    # Sort by timestamp (newest first) and take last 100
                    all_calls.sort(key=lambda x: x["timestamp"], reverse=True)
                    raw_recent_calls = all_calls[:100]
                    
                    # Convert timestamps to local timezone for display
                    recent_calls = []
                    for call in raw_recent_calls:
                        call_copy = call.copy()
                        try:
                            ts = datetime.fromisoformat(call["timestamp"])
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=dt_util.UTC)
                            local_ts = dt_util.as_local(ts)
                            call_copy["timestamp"] = local_ts.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                        recent_calls.append(call_copy)
                    
                    # Count calls from last 24 hours for statistics
                    now = datetime.now(dt_util.UTC)
                    cutoff = now - timedelta(hours=24)
                    last_24h_count = sum(
                        1 for call in all_calls
                        if datetime.fromisoformat(call["timestamp"]).replace(tzinfo=dt_util.UTC) > cutoff
                    )
                    
                    self._attr_extra_state_attributes = {
                        "recent_calls": recent_calls,
                        "recent_calls_count": len(recent_calls),
                        "last_24h_count": last_24h_count,
                        "total_calls_tracked": len(all_calls)
                    }
            except Exception as e:
                _LOGGER.debug(f"Failed to load API call history: {e}")
                self._attr_extra_state_attributes = {
                    "recent_calls": [],
                    "recent_calls_count": 0,
                    "last_24h_count": 0,
                    "total_calls_tracked": 0
                }
        except Exception:
            self._attr_available = False

class TadoApiStatusSensor(SensorEntity):
    """Sensor showing Tado API status."""
    
    def __init__(self):
        self._attr_name = "API Status"
        self._attr_unique_id = "tado_ce_api_status"
        self._attr_device_info = get_hub_device_info()
        self._attr_available = False
        self._attr_native_value = None
    
    @property
    def icon(self):
        if self._attr_native_value == "ok":
            return "mdi:check-circle"
        elif self._attr_native_value == "rate_limited":
            return "mdi:alert-circle"
        return "mdi:help-circle"
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            data = load_ratelimit_file()
            if data:
                self._attr_native_value = data.get("status", "unknown")
                self._attr_available = True
            else:
                self._attr_native_value = "unknown"
                self._attr_available = True
        except Exception:
            self._attr_native_value = "error"
            self._attr_available = True

class TadoTokenStatusSensor(SensorEntity):
    """Sensor showing Tado token status."""
    
    def __init__(self):
        self._attr_name = "Token Status"
        self._attr_unique_id = "tado_ce_token_status"
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
    
    @property
    def icon(self):
        if self._attr_native_value == "valid":
            return "mdi:key"
        return "mdi:key-alert"
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            config = load_config_file()
            if config:
                if config.get("refresh_token"):
                    self._attr_native_value = "valid"
                else:
                    self._attr_native_value = "missing"
                self._attr_available = True
            else:
                self._attr_native_value = "missing"
                self._attr_available = True
        except Exception:
            self._attr_native_value = "error"
            self._attr_available = True

class TadoZoneCountSensor(SensorEntity):
    """Sensor showing number of Tado zones."""
    
    def __init__(self):
        self._attr_name = "Zone Count"
        self._attr_unique_id = "tado_ce_zone_count"
        self._attr_icon = "mdi:home-thermometer"
        self._attr_native_unit_of_measurement = "zones"
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
        self._heating_zones = 0
        self._hot_water_zones = 0
        self._ac_zones = 0
    
    @property
    def extra_state_attributes(self):
        return {
            "heating_zones": self._heating_zones,
            "hot_water_zones": self._hot_water_zones,
            "ac_zones": self._ac_zones,
        }
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            zones = load_zones_info_file()
            if zones:
                self._attr_native_value = len(zones)
                self._heating_zones = len([z for z in zones if z.get('type') == 'HEATING'])
                self._hot_water_zones = len([z for z in zones if z.get('type') == 'HOT_WATER'])
                self._ac_zones = len([z for z in zones if z.get('type') == 'AIR_CONDITIONING'])
                self._attr_available = True
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False

class TadoLastSyncSensor(SensorEntity):
    """Sensor showing last sync time."""
    
    def __init__(self):
        self._attr_name = "Last Sync"
        self._attr_unique_id = "tado_ce_last_sync"
        self._attr_icon = "mdi:sync"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            data = load_ratelimit_file()
            if data:
                last_updated = data.get("last_updated")
                if last_updated:
                    from datetime import datetime, timezone
                    # v1.6.1: Robust timestamp parsing for different formats
                    if last_updated.endswith('Z'):
                        self._attr_native_value = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    elif '+' in last_updated or last_updated.endswith('00:00'):
                        self._attr_native_value = datetime.fromisoformat(last_updated)
                    else:
                        # Naive datetime - assume UTC for backwards compatibility
                        self._attr_native_value = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)
                    self._attr_available = True
                else:
                    self._attr_available = False
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False

# ============ API Monitoring Sensors (Discussion #86, Issue #65) ============

class TadoNextSyncSensor(SensorEntity):
    """Sensor showing next API sync time."""
    
    def __init__(self):
        self._attr_name = "Next Sync"
        self._attr_unique_id = "tado_ce_next_sync"
        self._attr_icon = "mdi:clock-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
        self._countdown = None
        self._current_interval = None
    
    @property
    def extra_state_attributes(self):
        return {
            "countdown": self._countdown,
            "current_interval_minutes": self._current_interval,
        }
    
    def update(self):
        try:
            from datetime import datetime, timezone, timedelta
            from homeassistant.util import dt as dt_util
            
            # Use data_loader for per-home file support
            data = load_ratelimit_file()
            if not data:
                self._attr_available = False
                return
            
            last_updated = data.get("last_updated")
            if not last_updated:
                self._attr_available = False
                return
            
            # Parse last sync time
            if last_updated.endswith('Z'):
                last_sync = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
            elif '+' in last_updated or last_updated.endswith('00:00'):
                last_sync = datetime.fromisoformat(last_updated)
            else:
                last_sync = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)
            
            # Get current polling interval from config
            from homeassistant.config_entries import ConfigEntry
            entries = self.hass.config_entries.async_entries(DOMAIN) if self.hass else []
            if entries:
                from .config_manager import ConfigurationManager
                from . import get_polling_interval
                config_manager = ConfigurationManager(entries[0])
                self._current_interval = get_polling_interval(config_manager)
                
                # Calculate next sync time
                next_sync_time = last_sync + timedelta(minutes=self._current_interval)
                self._attr_native_value = next_sync_time
                self._attr_available = True
                
                # Calculate countdown
                now = datetime.now(timezone.utc)
                time_until = next_sync_time - now
                if time_until.total_seconds() > 0:
                    minutes = int(time_until.total_seconds() // 60)
                    seconds = int(time_until.total_seconds() % 60)
                    self._countdown = f"{minutes}m {seconds}s"
                else:
                    self._countdown = "Overdue"
            else:
                self._attr_available = False
                self._current_interval = None
                self._countdown = None
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update Next Sync sensor: {e}")
            self._attr_available = False
            self._attr_native_value = None


class TadoPollingIntervalSensor(SensorEntity):
    """Sensor showing current polling interval."""
    
    def __init__(self):
        self._attr_name = "Polling Interval"
        self._attr_unique_id = "tado_ce_polling_interval"
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
        self._source = None
        self._day_interval = None
        self._night_interval = None
        self._is_night_mode = None
    
    @property
    def extra_state_attributes(self):
        return {
            "source": self._source,
            "day_interval": self._day_interval,
            "night_interval": self._night_interval,
            "is_night_mode": self._is_night_mode,
        }
    
    def update(self):
        try:
            from homeassistant.config_entries import ConfigEntry
            from datetime import datetime
            
            entries = self.hass.config_entries.async_entries(DOMAIN) if self.hass else []
            if not entries:
                self._attr_available = False
                return
            
            from .config_manager import ConfigurationManager
            from . import get_polling_interval
            
            config_manager = ConfigurationManager(entries[0])
            
            # Get current interval
            self._attr_native_value = get_polling_interval(config_manager)
            self._attr_available = True
            
            # Get day/night intervals
            self._day_interval = config_manager.get_custom_day_interval()
            self._night_interval = config_manager.get_custom_night_interval()
            
            # Check if currently in night mode based on config hours
            current_hour = datetime.now().hour
            day_start = config_manager.get_day_start_hour()
            night_start = config_manager.get_night_start_hour()
            self._is_night_mode = not (day_start <= current_hour < night_start)
            
            # Determine source
            if self._day_interval and self._night_interval:
                self._source = "Custom (Day/Night)"
            elif self._day_interval:
                self._source = "Custom (Day only)"
            elif self._night_interval:
                self._source = "Custom (Night only)"
            else:
                self._source = "Adaptive (Smart Polling)"
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update Polling Interval sensor: {e}")
            self._attr_available = False
            self._attr_native_value = None


class TadoCallHistorySensor(SensorEntity):
    """Sensor showing API call history."""
    
    def __init__(self):
        self._attr_name = "Call History"
        self._attr_unique_id = "tado_ce_call_history"
        self._attr_icon = "mdi:history"
        self._attr_native_unit_of_measurement = "calls"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_hub_device_info()
        self._attr_available = False
        self._attr_native_value = None
        self._history = []
        self._history_period_days = 14
        self._oldest_call = None
        self._newest_call = None
        self._calls_per_hour = None
        self._calls_today = None
        self._most_called_endpoint = None
    
    @property
    def extra_state_attributes(self):
        return {
            "history": self._history,
            "history_period_days": self._history_period_days,
            "oldest_call": self._oldest_call,
            "newest_call": self._newest_call,
            "calls_per_hour": self._calls_per_hour,
            "calls_today": self._calls_today,
            "most_called_endpoint": self._most_called_endpoint,
        }
    
    def update(self):
        try:
            from datetime import datetime, timezone, timedelta
            from homeassistant.util import dt as dt_util
            
            # Get retention days from config
            try:
                from .config_manager import ConfigurationManager
                config_manager = ConfigurationManager(None)
                self._history_period_days = config_manager.get_api_history_retention_days()
            except (AttributeError, TypeError):
                self._history_period_days = 14
            
            # Load call history
            history_data = load_api_call_history_file()
            if not history_data:
                self._attr_available = True
                self._attr_native_value = 0
                self._history = []
                return
            
            # Flatten all calls from all dates
            all_calls = []
            for date_key, calls in history_data.items():
                all_calls.extend(calls)
            
            if not all_calls:
                self._attr_available = True
                self._attr_native_value = 0
                self._history = []
                return
            
            # Sort by timestamp (newest first)
            all_calls.sort(key=lambda x: x["timestamp"], reverse=True)
            
            # Set state to total call count
            self._attr_native_value = len(all_calls)
            self._attr_available = True
            
            # Store recent calls (last 100) with local timezone conversion
            recent_calls = []
            for call in all_calls[:100]:
                call_copy = call.copy()
                try:
                    ts = datetime.fromisoformat(call["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=dt_util.UTC)
                    local_ts = dt_util.as_local(ts)
                    call_copy["timestamp"] = local_ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
                recent_calls.append(call_copy)
            self._history = recent_calls
            
            # Calculate oldest/newest call timestamps
            try:
                oldest_ts = datetime.fromisoformat(all_calls[-1]["timestamp"])
                if oldest_ts.tzinfo is None:
                    oldest_ts = oldest_ts.replace(tzinfo=dt_util.UTC)
                self._oldest_call = dt_util.as_local(oldest_ts).strftime("%Y-%m-%d %H:%M:%S")
                
                newest_ts = datetime.fromisoformat(all_calls[0]["timestamp"])
                if newest_ts.tzinfo is None:
                    newest_ts = newest_ts.replace(tzinfo=dt_util.UTC)
                self._newest_call = dt_util.as_local(newest_ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                _LOGGER.debug(f"Failed to parse oldest/newest timestamps: {e}")
                self._oldest_call = None
                self._newest_call = None
            
            # Calculate calls per hour (last 24h)
            try:
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=24)
                last_24h_calls = [
                    c for c in all_calls
                    if datetime.fromisoformat(c["timestamp"]).replace(tzinfo=timezone.utc) > cutoff
                ]
                if last_24h_calls:
                    self._calls_per_hour = round(len(last_24h_calls) / 24, 1)
                else:
                    self._calls_per_hour = 0
            except Exception as e:
                _LOGGER.debug(f"Failed to calculate calls per hour: {e}")
                self._calls_per_hour = None
            
            # Calculate calls today (UTC day)
            try:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self._calls_today = len(history_data.get(today_str, []))
            except Exception as e:
                _LOGGER.debug(f"Failed to calculate calls today: {e}")
                self._calls_today = None
            
            # Find most called endpoint
            try:
                endpoint_counts = {}
                for call in all_calls:
                    endpoint = call.get("type_name", "unknown")
                    endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1
                
                if endpoint_counts:
                    most_called = max(endpoint_counts.items(), key=lambda x: x[1])
                    self._most_called_endpoint = f"{most_called[0]} ({most_called[1]} calls)"
                else:
                    self._most_called_endpoint = None
            except Exception as e:
                _LOGGER.debug(f"Failed to find most called endpoint: {e}")
                self._most_called_endpoint = None
            
        except Exception as e:
            _LOGGER.error(f"Failed to update Call History sensor: {e}")
            self._attr_available = False
            self._attr_native_value = None


class TadoApiCallBreakdownSensor(SensorEntity):
    """Sensor showing API call breakdown by type."""
    
    def __init__(self):
        self._attr_name = "API Call Breakdown"
        self._attr_unique_id = "tado_ce_api_call_breakdown"
        self._attr_icon = "mdi:chart-bar"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = get_hub_device_info()
        self._attr_available = False
        self._attr_native_value = None
        self._breakdown_24h = {}
        self._breakdown_today = {}
        self._breakdown_total = {}
        self._top_3_types = []
        self._chart_data = []
    
    @property
    def extra_state_attributes(self):
        return {
            "breakdown_24h": self._breakdown_24h,
            "breakdown_today": self._breakdown_today,
            "breakdown_total": self._breakdown_total,
            "top_3_types": self._top_3_types,
            "chart_data": self._chart_data,
        }
    
    def update(self):
        try:
            from datetime import datetime, timezone, timedelta
            
            # Load call history
            history_data = load_api_call_history_file()
            if not history_data:
                self._attr_available = True
                self._attr_native_value = "No data"
                self._breakdown_24h = {}
                self._breakdown_today = {}
                self._breakdown_total = {}
                self._top_3_types = []
                self._chart_data = []
                return
            
            # Flatten all calls from all dates
            all_calls = []
            for date_key, calls in history_data.items():
                all_calls.extend(calls)
            
            if not all_calls:
                self._attr_available = True
                self._attr_native_value = "No data"
                self._breakdown_24h = {}
                self._breakdown_today = {}
                self._breakdown_total = {}
                self._top_3_types = []
                self._chart_data = []
                return
            
            # Calculate breakdown for last 24 hours
            now = datetime.now(timezone.utc)
            cutoff_24h = now - timedelta(hours=24)
            breakdown_24h = {}
            
            for call in all_calls:
                try:
                    ts = datetime.fromisoformat(call["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    
                    if ts > cutoff_24h:
                        type_name = call.get("type_name", "unknown")
                        breakdown_24h[type_name] = breakdown_24h.get(type_name, 0) + 1
                except Exception:
                    continue
            
            self._breakdown_24h = breakdown_24h
            
            # Calculate breakdown for today (UTC day)
            today_str = now.strftime("%Y-%m-%d")
            breakdown_today = {}
            today_calls = history_data.get(today_str, [])
            
            for call in today_calls:
                type_name = call.get("type_name", "unknown")
                breakdown_today[type_name] = breakdown_today.get(type_name, 0) + 1
            
            self._breakdown_today = breakdown_today
            
            # Calculate total breakdown (all history)
            breakdown_total = {}
            for call in all_calls:
                type_name = call.get("type_name", "unknown")
                breakdown_total[type_name] = breakdown_total.get(type_name, 0) + 1
            
            self._breakdown_total = breakdown_total
            
            # Find top 3 types (based on 24h data)
            if breakdown_24h:
                sorted_types = sorted(breakdown_24h.items(), key=lambda x: x[1], reverse=True)
                self._top_3_types = [
                    {"type": type_name, "count": count}
                    for type_name, count in sorted_types[:3]
                ]
                
                # Set state to most called type
                self._attr_native_value = sorted_types[0][0]
            else:
                self._top_3_types = []
                self._attr_native_value = "No data"
            
            # Format chart data for visualization (24h data)
            self._chart_data = [
                {"type": type_name, "count": count}
                for type_name, count in sorted(breakdown_24h.items(), key=lambda x: x[1], reverse=True)
            ]
            
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.error(f"Failed to update API Call Breakdown sensor: {e}")
            self._attr_available = False
            self._attr_native_value = None

# ============ Weather Sensors ============

class TadoOutsideTemperatureSensor(SensorEntity):
    """Outside temperature from Tado weather data."""
    
    def __init__(self):
        self._attr_name = "Outside Temperature"
        self._attr_unique_id = "tado_ce_outside_temperature"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = "measurement"
        self._attr_available = False
        self._attr_native_value = None
        self._timestamp = None
    
    @property
    def extra_state_attributes(self):
        return {"timestamp": self._timestamp}
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            data = load_weather_file()
            if data:
                # Use 'or {}' pattern for null safety
                temp_data = data.get('outsideTemperature') or {}
                self._attr_native_value = temp_data.get('celsius')
                self._timestamp = temp_data.get('timestamp')
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False

class TadoSolarIntensitySensor(SensorEntity):
    """Solar intensity from Tado weather data."""
    
    def __init__(self):
        self._attr_name = "Solar Intensity"
        self._attr_unique_id = "tado_ce_solar_intensity"
        self._attr_icon = "mdi:white-balance-sunny"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = "measurement"
        self._attr_available = False
        self._attr_native_value = None
        self._timestamp = None
    
    @property
    def extra_state_attributes(self):
        return {"timestamp": self._timestamp}
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            data = load_weather_file()
            if data:
                # Use 'or {}' pattern for null safety
                solar_data = data.get('solarIntensity') or {}
                self._attr_native_value = solar_data.get('percentage')
                self._timestamp = solar_data.get('timestamp')
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False

class TadoWeatherStateSensor(SensorEntity):
    """Weather state from Tado weather data."""
    
    def __init__(self):
        self._attr_name = "Weather"
        self._attr_unique_id = "tado_ce_weather_state"
        self._attr_icon = "mdi:weather-partly-cloudy"
        self._attr_available = False
        self._attr_native_value = None
        self._raw_state = None
        self._timestamp = None
    
    @property
    def icon(self):
        icons = {
            "SUN": "mdi:weather-sunny",
            "CLOUDY": "mdi:weather-cloudy",
            "CLOUDY_MOSTLY": "mdi:weather-cloudy",
            "CLOUDY_PARTLY": "mdi:weather-partly-cloudy",
            "RAIN": "mdi:weather-rainy",
            "SCATTERED_RAIN": "mdi:weather-partly-rainy",
            "DRIZZLE": "mdi:weather-rainy",
            "SNOW": "mdi:weather-snowy",
            "FOGGY": "mdi:weather-fog",
            "NIGHT_CLEAR": "mdi:weather-night",
            "NIGHT_CLOUDY": "mdi:weather-night-partly-cloudy",
            "THUNDERSTORMS": "mdi:weather-lightning",
            "WINDY": "mdi:weather-windy",
        }
        return icons.get(self._raw_state, "mdi:weather-partly-cloudy")
    
    @property
    def extra_state_attributes(self):
        return {
            "raw_state": self._raw_state,
            "timestamp": self._timestamp,
        }
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            data = load_weather_file()
            if data:
                # Use 'or {}' pattern for null safety
                weather_data = data.get('weatherState') or {}
                self._raw_state = weather_data.get('value')
                self._timestamp = weather_data.get('timestamp')
                self._attr_native_value = WEATHER_STATE_MAP.get(self._raw_state, self._raw_state)
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False

# ============ Zone Sensors ============

class TadoBaseSensor(SensorEntity):
    """Base class for Tado zone sensors."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_available = False
        self._attr_native_value = None
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        # v1.9.4: Unsubscribe callback for zones_updated signal
        self._unsub_zones_updated = None

    async def async_added_to_hass(self):
        """Register signal listener when entity is added to hass.
        
        v1.9.4: Listen for SIGNAL_ZONES_UPDATED to force immediate update
        after zones.json is refreshed. This fixes slow sensor updates (#44).
        """
        await super().async_added_to_hass()
        
        @callback
        def _handle_zones_updated():
            """Handle zones.json update signal."""
            self.async_schedule_update_ha_state(True)
        
        self._unsub_zones_updated = async_dispatcher_connect(
            self.hass, SIGNAL_ZONES_UPDATED, _handle_zones_updated
        )

    async def async_will_remove_from_hass(self):
        """Unregister signal listener when entity is removed."""
        if self._unsub_zones_updated:
            self._unsub_zones_updated()
            self._unsub_zones_updated = None
        await super().async_will_remove_from_hass()
    
    def _get_zone_data(self):
        """Get zone data from file."""
        try:
            # Use data_loader for per-home file support
            data = load_zones_file()
            if data:
                # Use 'or {}' pattern for null safety
                zone_states = data.get('zoneStates') or {}
                return zone_states.get(self._zone_id)
            return None
        except Exception:
            return None
    
    def update(self):
        zone_data = self._get_zone_data()
        if zone_data:
            self._update_from_zone_data(zone_data)
            self._attr_available = True
        else:
            self._attr_available = False
    
    def _update_from_zone_data(self, zone_data):
        pass

class TadoTemperatureSensor(TadoBaseSensor):
    """Current temperature sensor."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Temperature"
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_temperature"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = "measurement"
    
    def update(self):
        """Update temperature sensor - mark unavailable if no temperature data."""
        zone_data = self._get_zone_data()
        if zone_data:
            self._update_from_zone_data(zone_data)
            # Only mark available if we actually have temperature data
            # HOT_WATER zones (combi boilers) often don't have temperature sensors
            self._attr_available = self._attr_native_value is not None
        else:
            self._attr_available = False
    
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        sensor_data = zone_data.get('sensorDataPoints') or {}
        self._attr_native_value = (
            (sensor_data.get('insideTemperature') or {}).get('celsius')
        )

class TadoHumiditySensor(TadoBaseSensor):
    """Humidity sensor."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Humidity"
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_humidity"
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = "measurement"
    
    def update(self):
        """Update humidity sensor - mark unavailable if no humidity data."""
        zone_data = self._get_zone_data()
        if zone_data:
            self._update_from_zone_data(zone_data)
            # Only mark available if we actually have humidity data
            # Some zones may not have humidity sensors
            self._attr_available = self._attr_native_value is not None
        else:
            self._attr_available = False
    
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        sensor_data = zone_data.get('sensorDataPoints') or {}
        self._attr_native_value = (
            (sensor_data.get('humidity') or {}).get('percentage')
        )

class TadoHeatingPowerSensor(TadoBaseSensor):
    """Heating power sensor."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Heating Power"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_heating"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:radiator"
        self._attr_state_class = "measurement"
    
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        activity_data = zone_data.get('activityDataPoints') or {}
        power = (activity_data.get('heatingPower') or {}).get('percentage')
        self._attr_native_value = power if power is not None else 0

class TadoACPowerSensor(TadoBaseSensor):
    """AC power sensor."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "AIR_CONDITIONING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} AC Power"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_ac_power"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:air-conditioner"
        self._attr_state_class = "measurement"
    
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        activity_data = zone_data.get('activityDataPoints') or {}
        ac_power = activity_data.get('acPower') or {}
        # Try percentage first (older API), then value (newer API returns 'ON'/'OFF')
        power = ac_power.get('percentage')
        if power is None:
            value = ac_power.get('value')
            power = 100 if value == 'ON' else 0
        self._attr_native_value = power if power is not None else 0

class TadoBoilerFlowTemperatureSensor(SensorEntity):
    """Boiler flow temperature sensor - reads from HEATING zones.
    
    This is a Hub-level sensor that reads boilerFlowTemperature from
    any HEATING zone that has this data available.
    """
    
    def __init__(self):
        self._attr_name = "Boiler Flow Temperature"
        self._attr_unique_id = "tado_ce_boiler_flow_temperature"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = "measurement"
        self._attr_icon = "mdi:water-boiler"
        self._attr_device_info = get_hub_device_info()
        self._attr_available = False
        self._attr_native_value = None
        self._source_zone = None
    
    @property
    def extra_state_attributes(self):
        return {
            "source_zone": self._source_zone,
        }
    
    def update(self):
        """Update boiler flow temperature from HEATING zones."""
        try:
            # Use data_loader for per-home file support
            data = load_zones_file()
            if not data:
                self._attr_available = False
                return
            
            # Look for boilerFlowTemperature in any zone
            # Use 'or {}' pattern for null safety
            zone_states = data.get('zoneStates') or {}
            for zone_id, zone_data in zone_states.items():
                # Use 'or {}' pattern for null safety
                activity_data = zone_data.get('activityDataPoints') or {}
                flow_temp = (activity_data.get('boilerFlowTemperature') or {}).get('celsius')
                if flow_temp is not None:
                    self._attr_native_value = flow_temp
                    self._source_zone = zone_id
                    self._attr_available = True
                    return
            
            # No boiler flow data found
            self._attr_native_value = None
            self._source_zone = None
            self._attr_available = False
            
        except Exception:
            self._attr_available = False

class TadoTargetTempSensor(TadoBaseSensor):
    """Target temperature sensor."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Target"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_target"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:thermometer-check"
    
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for setting)
        setting = zone_data.get('setting') or {}
        if setting.get('power') == 'ON':
            self._attr_native_value = (setting.get('temperature') or {}).get('celsius')
        else:
            self._attr_native_value = None

class TadoOverlaySensor(TadoBaseSensor):
    """Overlay status sensor (Manual/Schedule)."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Mode"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_mode"
        self._attr_icon = "mdi:calendar-clock"
        self._next_change = None
        self._next_temp = None
    
    @property
    def extra_state_attributes(self):
        return {
            "next_change": self._next_change,
            "next_temperature": self._next_temp,
        }
    
    def _update_from_zone_data(self, zone_data):
        overlay_type = zone_data.get('overlayType')
        # Use 'or {}' pattern for null safety
        setting = zone_data.get('setting') or {}
        power = setting.get('power')
        
        if power == 'OFF':
            self._attr_native_value = "Off"
        elif overlay_type == 'MANUAL':
            self._attr_native_value = "Manual"
        else:
            self._attr_native_value = "Schedule"
        
        # Next schedule change
        next_change = zone_data.get('nextScheduleChange')
        if next_change:
            self._next_change = next_change.get('start')
            next_setting = next_change.get('setting')
            if next_setting:
                temp = next_setting.get('temperature')
                self._next_temp = temp.get('celsius') if temp else None
            else:
                self._next_temp = None
        else:
            self._next_change = None
            self._next_temp = None


class TadoHotWaterPowerSensor(TadoBaseSensor):
    """Hot water power sensor (ON/OFF)."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HOT_WATER"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Power"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_power"
        self._attr_icon = "mdi:power"
    
    def _update_from_zone_data(self, zone_data):
        setting = zone_data.get('setting') or {}
        power = setting.get('power')
        self._attr_native_value = power if power else "Unknown"


# ============ Device Sensors ============

class TadoBatterySensor(SensorEntity):
    """Battery status sensor."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str, device: dict, zones_info: list):
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._device_serial = device.get('shortSerialNo', 'unknown')
        self._device_type = device.get('deviceType', 'unknown')
        
        # Import here to avoid circular dependency
        from .device_manager import get_device_name_suffix
        suffix = get_device_name_suffix(zone_id, self._device_serial, self._device_type, zones_info)
        
        self._attr_name = f"{zone_name}{suffix} Battery"
        self._attr_unique_id = f"tado_ce_{self._device_serial}_battery"
        self._attr_icon = "mdi:battery"
        self._attr_available = True
        self._attr_native_value = device.get('batteryState', 'unknown')
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        
        # Extra attributes
        self._firmware = device.get('currentFwVersion')
        self._connection_state = (device.get('connectionState') or {}).get('value')
        self._connection_timestamp = (device.get('connectionState') or {}).get('timestamp')
    
    @property
    def icon(self):
        if self._attr_native_value == 'LOW':
            return "mdi:battery-low"
        return "mdi:battery"
    
    @property
    def extra_state_attributes(self):
        return {
            "device_serial": self._device_serial,
            "device_type": self._device_type,
            "firmware_version": self._firmware,
            "connection_state": "online" if self._connection_state else "offline",
            "connection_timestamp": self._connection_timestamp,
        }
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            zones_info = load_zones_info_file()
            if zones_info:
                for zone in zones_info:
                    for device in zone.get('devices', []):
                        if device.get('shortSerialNo') == self._device_serial:
                            self._attr_native_value = device.get('batteryState', 'unknown')
                            self._firmware = device.get('currentFwVersion')
                            # Use 'or {}' pattern for null safety
                            conn = device.get('connectionState') or {}
                            self._connection_state = conn.get('value')
                            self._connection_timestamp = conn.get('timestamp')
                            self._attr_available = True
                            return
            self._attr_available = False
        except Exception:
            self._attr_available = False

class TadoDeviceConnectionSensor(SensorEntity):
    """Device connection state sensor."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str, device: dict, zones_info: list):
        self._zone_id = zone_id
        self._device_serial = device.get('shortSerialNo', 'unknown')
        self._device_type = device.get('deviceType', 'unknown')
        self._zone_name = zone_name
        self._zone_type = zone_type
        
        # Import here to avoid circular dependency
        from .device_manager import get_device_name_suffix
        suffix = get_device_name_suffix(zone_id, self._device_serial, self._device_type, zones_info)
        
        self._attr_name = f"{zone_name}{suffix} Connection"
        self._attr_unique_id = f"tado_ce_{self._device_serial}_connection"
        self._attr_icon = "mdi:wifi"
        self._attr_available = True
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        
        # Use 'or {}' pattern for null safety
        conn = device.get('connectionState') or {}
        self._attr_native_value = "Online" if conn.get('value') else "Offline"
        self._connection_timestamp = conn.get('timestamp')
        self._firmware = device.get('currentFwVersion')
    
    @property
    def icon(self):
        if self._attr_native_value == "Online":
            return "mdi:wifi"
        return "mdi:wifi-off"
    
    @property
    def extra_state_attributes(self):
        return {
            "device_serial": self._device_serial,
            "device_type": self._device_type,
            "firmware_version": self._firmware,
            "last_seen": self._connection_timestamp,
        }
    
    def update(self):
        try:
            # Use data_loader for per-home file support
            zones_info = load_zones_info_file()
            if zones_info:
                for zone in zones_info:
                    for device in zone.get('devices', []):
                        if device.get('shortSerialNo') == self._device_serial:
                            # Use 'or {}' pattern for null safety
                            conn = device.get('connectionState') or {}
                            self._attr_native_value = "Online" if conn.get('value') else "Offline"
                            self._connection_timestamp = conn.get('timestamp')
                            self._firmware = device.get('currentFwVersion')
                            self._attr_available = True
                            return
            self._attr_available = False
        except Exception:
            self._attr_available = False


# ============ Smart Comfort Sensors (v1.9.0) ============
# v1.11.0: Removed TadoThermalRateSensor, TadoCoolingRateSensor, TadoHeatingEfficiencySensor, TadoTimeToTargetSensor
# These instantaneous sensors have been replaced by the more accurate heating cycle analysis sensors:
# - TadoAvgHeatingRateSensor (replaces TadoThermalRateSensor)
# - TadoPreheatTimeSensor (replaces TadoTimeToTargetSensor)
# See migration code in __init__.py for entity cleanup.

# ============ Smart Comfort Insights Sensors (v1.9.0 Phase 3) ============

class TadoHistoricalDeviationSensor(TadoBaseSensor):
    """Historical temperature comparison sensor.
    
    Compares current temperature to the 7-day average at the same time of day.
    Helps identify unusual temperature patterns.
    
    State: Difference from historical average (e.g., "+1.2" or "-0.8")
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Historical Deviation"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_historical_deviation"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_icon = "mdi:chart-timeline-variant"
        self._attr_state_class = "measurement"
        
        # Attributes
        self._current_temp: float | None = None
        self._historical_avg: float | None = None
        self._sample_count: int = 0
        self._summary: str = ""
    
    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "historical_average": self._historical_avg,
            "sample_count": self._sample_count,
            "summary": self._summary,
            "zone_type": self._zone_type,
        }
    
    @property
    def icon(self):
        """Dynamic icon based on comparison."""
        if self._attr_native_value is None:
            return "mdi:chart-timeline-variant"
        elif self._attr_native_value > 0.5:
            return "mdi:thermometer-chevron-up"
        elif self._attr_native_value < -0.5:
            return "mdi:thermometer-chevron-down"
        return "mdi:thermometer-check"
    
    def update(self):
        """Update historical comparison from SmartComfortManager."""
        try:
            manager = self.hass.data.get(DOMAIN, {}).get('smart_comfort_manager') if self.hass else None
            
            if not manager or not manager.is_enabled:
                self._attr_available = False
                return
            
            # Get current temperature from zone data
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return
            
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')
            
            if self._current_temp is None:
                self._attr_available = False
                return
            
            # Get historical comparison
            comparison = manager.get_historical_comparison(
                self._zone_id,
                self._current_temp
            )
            
            if comparison is None:
                self._attr_native_value = None
                self._attr_available = False
                self._historical_avg = None
                self._sample_count = 0
                self._summary = "Insufficient data"
                return
            
            self._attr_native_value = comparison.difference
            self._historical_avg = comparison.historical_avg
            self._sample_count = comparison.sample_count
            self._summary = comparison.to_summary()
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update historical comparison for zone {self._zone_id}: {e}")
            self._attr_available = False


class TadoNextScheduleTimeSensor(TadoBaseSensor):
    """Next schedule time sensor.
    
    Shows when the next scheduled temperature change will occur.
    
    State: Next schedule time (e.g., "17:00" or "Tomorrow 07:00")
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Next Schedule"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_next_schedule_time"
        self._attr_icon = "mdi:calendar-clock"
        
        # Attributes
        self._next_temp: float | None = None
        self._is_heating_on: bool = False
        self._is_tomorrow: bool = False
        self._minutes_until: int | None = None
    
    @property
    def extra_state_attributes(self):
        return {
            "next_temperature": self._next_temp,
            "is_heating_on": self._is_heating_on,
            "is_tomorrow": self._is_tomorrow,
            "minutes_until": self._minutes_until,
            "zone_type": self._zone_type,
        }
    
    def update(self):
        """Update next schedule time from schedule data."""
        try:
            from .smart_comfort import get_next_schedule_change
            from datetime import datetime
            
            next_block = get_next_schedule_change(self._zone_id)
            
            if next_block is None:
                self._attr_native_value = "No schedule"
                self._attr_available = True
                self._next_temp = None
                self._is_heating_on = False
                self._is_tomorrow = False
                self._minutes_until = None
                return
            
            now = datetime.now()
            self._is_tomorrow = next_block.start_time.date() > now.date()
            self._is_heating_on = next_block.is_heating_on
            self._next_temp = next_block.target_temp
            
            # Calculate minutes until
            time_diff = next_block.start_time - now
            self._minutes_until = int(time_diff.total_seconds() / 60)
            
            # Format display value
            time_str = next_block.start_time.strftime("%H:%M")
            if self._is_tomorrow:
                self._attr_native_value = f"Tomorrow {time_str}"
            else:
                self._attr_native_value = time_str
            
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update next schedule for zone {self._zone_id}: {e}")
            self._attr_available = False


class TadoNextScheduleTempSensor(TadoBaseSensor):
    """Next schedule target temperature sensor.
    
    Shows the target temperature of the next scheduled block.
    
    State: Target temperature (°C) or "OFF"
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Next Schedule Temp"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_next_schedule_temp"
        # No unit_of_measurement so we can show "OFF" as state
        self._attr_icon = "mdi:thermometer-chevron-up"
        
        # Attributes
        self._schedule_time: str | None = None
        self._is_heating_on: bool = False
        self._current_temp: float | None = None
        self._temp_diff: float | None = None
    
    @property
    def extra_state_attributes(self):
        attrs = {
            "schedule_time": self._schedule_time,
            "is_heating_on": self._is_heating_on,
            "current_temperature": self._current_temp,
            "temperature_difference": self._temp_diff,
            "zone_type": self._zone_type,
        }
        # Add unit only when showing temperature
        if self._is_heating_on and isinstance(self._attr_native_value, (int, float)):
            attrs["unit_of_measurement"] = "°C"
        return attrs
    
    @property
    def icon(self):
        """Dynamic icon based on heating direction."""
        if self._temp_diff is not None:
            if self._temp_diff > 0:
                return "mdi:thermometer-chevron-up"
            elif self._temp_diff < 0:
                return "mdi:thermometer-chevron-down"
        if not self._is_heating_on:
            return "mdi:thermometer-off"
        return "mdi:thermometer"
    
    def update(self):
        """Update next schedule temperature from schedule data."""
        try:
            from .smart_comfort import get_next_schedule_change
            from datetime import datetime
            
            next_block = get_next_schedule_change(self._zone_id)
            
            if next_block is None:
                self._attr_native_value = "No schedule"
                self._attr_available = True
                self._schedule_time = None
                self._is_heating_on = False
                self._current_temp = None
                self._temp_diff = None
                return
            
            self._is_heating_on = next_block.is_heating_on
            self._schedule_time = next_block.start_time.strftime("%H:%M")
            
            # Get current temperature
            zone_data = self._get_zone_data()
            if zone_data:
                sensor_data = zone_data.get('sensorDataPoints') or {}
                self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')
            
            if not next_block.is_heating_on or next_block.target_temp is None:
                # Heating OFF block - show "OFF" instead of unknown
                self._attr_native_value = "OFF"
                self._attr_available = True
                self._temp_diff = None
                return
            
            self._attr_native_value = next_block.target_temp
            
            # Calculate temperature difference
            if self._current_temp is not None:
                self._temp_diff = round(next_block.target_temp - self._current_temp, 1)
            else:
                self._temp_diff = None
            
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update next schedule temp for zone {self._zone_id}: {e}")
            self._attr_available = False


class TadoPreheatAdvisorSensor(TadoBaseSensor):
    """Preheat timing advisor sensor.
    
    Suggests optimal preheat start time based on historical heating rates.
    Uses the next scheduled target temperature from Tado schedule.
    
    State: Recommended start time (e.g., "06:15")
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Preheat Advisor"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_preheat_advisor"
        self._attr_icon = "mdi:clock-start"
        
        # Attributes
        self._current_temp: float | None = None
        self._target_temp: float | None = None
        self._target_time: str | None = None
        self._duration_minutes: int | None = None
        self._heating_rate: float | None = None
        self._confidence: str = "unknown"
        self._summary: str = ""
    
    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "target_temperature": self._target_temp,
            "target_time": self._target_time,
            "duration_minutes": self._duration_minutes,
            "heating_rate": self._heating_rate,
            "confidence": self._confidence,
            "summary": self._summary,
            "zone_type": self._zone_type,
        }
    
    @property
    def icon(self):
        """Dynamic icon based on confidence."""
        if self._confidence == "high":
            return "mdi:clock-check"
        elif self._confidence == "medium":
            return "mdi:clock-alert"
        elif self._confidence == "low":
            return "mdi:clock-outline"
        elif self._confidence == "no_schedule":
            return "mdi:calendar-remove"
        elif self._confidence == "insufficient_data":
            return "mdi:database-off"
        return "mdi:clock-start"
    
    def update(self):
        """Update preheat advice based on schedule and heating rate.
        
        Logic:
        1. Get next schedule block from schedules.json
        2. If next block has heating ON with target temp > current temp, calculate preheat time
        3. If already at or above target, show "Ready"
        4. If no schedule or heating OFF, show appropriate status
        """
        try:
            from .smart_comfort import get_next_schedule_change
            from datetime import datetime
            
            manager = self.hass.data.get(DOMAIN, {}).get('smart_comfort_manager') if self.hass else None
            
            if not manager or not manager.is_enabled:
                self._attr_available = False
                return
            
            # Get current temperature from zone data
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return
            
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')
            
            if self._current_temp is None:
                self._attr_available = False
                return
            
            # Get next schedule change from schedules.json
            next_block = get_next_schedule_change(self._zone_id)
            
            if next_block is None:
                # No schedule data or no more blocks today
                self._attr_native_value = "No schedule"
                self._attr_available = True
                self._target_temp = None
                self._target_time = None
                self._duration_minutes = None
                self._heating_rate = None
                self._confidence = "no_schedule"
                self._summary = "No upcoming schedule changes today"
                return
            
            # Check if next block has heating ON
            if not next_block.is_heating_on or next_block.target_temp is None:
                # Next block is heating OFF
                self._attr_native_value = "Heating OFF"
                self._attr_available = True
                self._target_temp = None
                self._target_time = next_block.start_time.strftime("%H:%M")
                self._duration_minutes = 0
                self._heating_rate = None
                self._confidence = "high"
                self._summary = f"Heating turns OFF at {self._target_time}"
                return
            
            self._target_temp = next_block.target_temp
            self._target_time = next_block.start_time.strftime("%H:%M")
            
            # Check if already at or above target
            if self._current_temp >= self._target_temp:
                self._attr_native_value = "Ready"
                self._attr_available = True
                self._duration_minutes = 0
                self._heating_rate = None
                self._confidence = "high"
                self._summary = f"Already at {self._target_temp:.1f}°C (no preheat needed)"
                return
            
            # Need to preheat - calculate timing
            # v1.11.0: Prioritize HeatingCycleCoordinator rate over SmartComfort rate
            # HeatingCycleCoordinator uses complete heating cycles for more accurate rate
            heating_cycle_coordinator = self.hass.data.get(DOMAIN, {}).get('heating_cycle_coordinator')
            cycle_heating_rate = None
            cycle_confidence = None
            
            # v2.0.0: Get UFH buffer from options (only for selected zones)
            ufh_buffer = 0
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                ufh_buffer_global = entry.options.get('ufh_buffer_minutes', 0)
                ufh_zones = entry.options.get('ufh_zones', [])
                # Apply buffer only if: buffer > 0 AND (no zones selected OR this zone is selected)
                if ufh_buffer_global > 0:
                    if not ufh_zones or self._zone_id in ufh_zones:
                        ufh_buffer = ufh_buffer_global
                break
            
            if heating_cycle_coordinator:
                zone_data_cycle = heating_cycle_coordinator.get_zone_data(self._zone_id)
                if zone_data_cycle and zone_data_cycle.get("heating_rate") is not None:
                    # HeatingCycleCoordinator rate is in °C/min, convert to °C/h for consistency
                    cycle_heating_rate = zone_data_cycle.get("heating_rate") * 60
                    cycle_count = zone_data_cycle.get("cycle_count", 0)
                    # Determine confidence based on cycle count
                    if cycle_count >= 5:
                        cycle_confidence = "high"
                    elif cycle_count >= 3:
                        cycle_confidence = "medium"
                    else:
                        cycle_confidence = "low"
            
            # If we have HeatingCycleCoordinator data, use it directly
            if cycle_heating_rate is not None and cycle_heating_rate > 0.1:
                from datetime import timedelta
                temp_diff = self._target_temp - self._current_temp
                hours_needed = temp_diff / cycle_heating_rate
                minutes_needed = int(hours_needed * 60)
                
                # v2.0.0: Add UFH buffer for underfloor heating systems
                minutes_needed += ufh_buffer
                
                minutes_needed = min(minutes_needed, 240)  # Cap at 4 hours
                
                recommended_start = next_block.start_time - timedelta(minutes=minutes_needed)
                
                self._attr_native_value = recommended_start.strftime("%H:%M")
                self._duration_minutes = minutes_needed
                self._heating_rate = cycle_heating_rate
                self._confidence = cycle_confidence
                self._summary = f"Start at {self._attr_native_value} ({minutes_needed} min to reach {self._target_temp:.1f}°C)"
                if ufh_buffer > 0:
                    self._summary += f" (includes {ufh_buffer} min UFH buffer)"
                self._attr_available = True
                return
            
            # Fallback to SmartComfortManager
            advice = manager.get_preheat_advice(
                self._zone_id,
                self._target_temp,
                next_block.start_time,
                self._current_temp
            )
            
            if advice is None:
                # Not enough data to calculate heating rate
                self._attr_native_value = "Insufficient data"
                self._attr_available = True
                self._duration_minutes = None
                self._heating_rate = None
                self._confidence = "insufficient_data"
                temp_diff = self._target_temp - self._current_temp
                self._summary = f"Need +{temp_diff:.1f}°C by {self._target_time} (no heating history)"
                return
            
            # We have a valid preheat recommendation
            # v2.0.0: Apply UFH buffer to SmartComfortManager advice
            from datetime import timedelta
            adjusted_duration = advice.estimated_duration_minutes + ufh_buffer
            adjusted_duration = min(adjusted_duration, 240)  # Cap at 4 hours
            adjusted_start = next_block.start_time - timedelta(minutes=adjusted_duration)
            
            self._attr_native_value = adjusted_start.strftime("%H:%M")
            self._duration_minutes = adjusted_duration
            self._heating_rate = advice.heating_rate
            self._confidence = advice.confidence
            self._summary = advice.to_summary()
            if ufh_buffer > 0:
                self._summary += f" (includes {ufh_buffer} min UFH buffer)"
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update preheat advice for zone {self._zone_id}: {e}")
            self._attr_available = False


class TadoSmartComfortTargetSensor(TadoBaseSensor):
    """Smart Comfort Target Temperature sensor.
    
    Calculates the ideal target temperature using ASHRAE 55 Adaptive Comfort Model.
    This is the temperature at which the zone would be "Comfortable" according to
    the Comfort Level sensor.
    
    Formula: Comfort Temp = 0.31 × Outdoor_Temp + 17.8°C
    
    This provides a scientifically-validated, location-aware target that adapts
    to outdoor conditions. When outdoor temp is not available, falls back to
    seasonal thresholds based on latitude.
    
    State: Recommended target temperature (°C)
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Smart Comfort Target"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_smart_comfort_target"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_icon = "mdi:thermometer-auto"
        self._attr_state_class = "measurement"
        
        # Attributes
        self._current_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._humidity: float | None = None
        self._comfort_model: str = "unknown"
        self._deviation: float | None = None
    
    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "outdoor_temperature": self._outdoor_temp,
            "humidity": self._humidity,
            "comfort_model": self._comfort_model,
            "deviation_from_comfort": self._deviation,
            "zone_type": self._zone_type,
        }
    
    @property
    def icon(self):
        """Dynamic icon based on deviation from comfort."""
        if self._deviation is None:
            return "mdi:thermometer-auto"
        if self._deviation < -2:
            return "mdi:thermometer-low"  # Too cold
        if self._deviation > 2:
            return "mdi:thermometer-high"  # Too hot
        return "mdi:thermometer-check"  # Comfortable
    
    def update(self):
        """Update Smart Comfort target using ASHRAE 55 Adaptive Comfort Model."""
        try:
            from .config_manager import ConfigurationManager
            
            if not self.hass:
                self._attr_available = False
                return
            
            # Get config
            entries = self.hass.config_entries.async_entries(DOMAIN)
            if not entries:
                self._attr_available = False
                return
            
            config_manager = ConfigurationManager(entries[0])
            
            # Get zone data
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return
            
            # Get current temperature
            sensor_data = zone_data.get('sensorDataPoints') or {}
            inside_temp = sensor_data.get('insideTemperature') or {}
            self._current_temp = inside_temp.get('celsius')
            
            # Get humidity
            humidity_data = sensor_data.get('humidity') or {}
            self._humidity = humidity_data.get('percentage')
            
            # Get outdoor temperature
            outdoor_entity = config_manager.get_outdoor_temp_entity()
            self._outdoor_temp = self._get_outdoor_temperature(outdoor_entity, config_manager.get_use_feels_like())
            
            # Calculate comfort target using ASHRAE 55 or seasonal fallback
            comfort_target = self._calculate_comfort_target()
            
            if comfort_target is None:
                self._attr_available = False
                return
            
            # Round to 0.5°C (Tado's precision)
            comfort_target = round(comfort_target * 2) / 2
            
            # Calculate deviation from comfort
            if self._current_temp is not None:
                self._deviation = round(self._current_temp - comfort_target, 1)
            else:
                self._deviation = None
            
            self._attr_native_value = comfort_target
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update Smart Comfort target for zone {self._zone_id}: {e}")
            self._attr_available = False
    
    def _calculate_comfort_target(self) -> float | None:
        """Calculate comfort target using ASHRAE 55 or seasonal fallback."""
        # Method 1: ASHRAE 55 Adaptive Comfort Model (if outdoor temp available)
        if self._outdoor_temp is not None:
            self._comfort_model = "adaptive"
            # Formula: Comfort Temp = 0.31 × Outdoor_Temp + 17.8°C
            return 0.31 * self._outdoor_temp + 17.8
        
        # Method 2: Seasonal fallback based on latitude
        self._comfort_model = "seasonal"
        return self._get_seasonal_comfort_target()
    
    def _get_seasonal_comfort_target(self) -> float:
        """Get comfort target based on season and latitude."""
        from datetime import datetime
        
        # Get latitude from HA config
        latitude = 51.5  # Default to London
        if self.hass and hasattr(self.hass.config, 'latitude'):
            latitude = self.hass.config.latitude or 51.5
        
        # Determine season (reverse for Southern Hemisphere)
        month = datetime.now().month
        is_southern = latitude < 0
        
        if is_southern:
            # Southern Hemisphere: reverse seasons
            if month in [12, 1, 2]:
                season = "summer"
            elif month in [6, 7, 8]:
                season = "winter"
            else:
                season = "transition"
        else:
            # Northern Hemisphere
            if month in [6, 7, 8]:
                season = "summer"
            elif month in [11, 12, 1, 2]:
                season = "winter"
            else:
                season = "transition"
        
        # Base comfort targets by season
        base_targets = {
            "summer": 24.0,
            "winter": 20.0,
            "transition": 22.0,
        }
        
        # Latitude adjustment
        abs_lat = abs(latitude)
        if abs_lat > 55:
            lat_offset = -1.0  # Nordic - prefer cooler
        elif abs_lat > 45:
            lat_offset = -0.5  # Northern Europe
        elif abs_lat < 30:
            lat_offset = 1.0   # Subtropical - prefer warmer
        elif abs_lat < 40:
            lat_offset = 0.5   # Mediterranean
        else:
            lat_offset = 0.0   # Temperate
        
        return base_targets[season] + lat_offset
    
    def _get_outdoor_temperature(self, entity_id: str, use_feels_like: bool) -> float | None:
        """Get outdoor temperature from configured entity."""
        if not entity_id or not self.hass:
            return None
        
        try:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ('unknown', 'unavailable'):
                return None
            
            # Check if it's a weather entity
            if entity_id.startswith('weather.'):
                if use_feels_like:
                    # Try apparent_temperature first
                    apparent = state.attributes.get('apparent_temperature')
                    if apparent is not None:
                        return float(apparent)
                # Fall back to temperature
                temp = state.attributes.get('temperature')
                if temp is not None:
                    return float(temp)
            else:
                # Regular sensor entity
                return float(state.state)
        except (ValueError, TypeError):
            pass
        
        return None


# ============ Environment Sensors (v1.9.0) ============

def _calculate_dew_point(temperature: float, humidity: float) -> float:
    """Calculate dew point using Magnus-Tetens formula (more accurate).
    
    Formula: Td = (b × α) / (a - α)
    where α = (a × T) / (b + T) + ln(RH/100)
    
    Constants (for -40°C to 50°C range):
    a = 17.27
    b = 237.7°C
    
    Args:
        temperature: Indoor temperature in °C
        humidity: Relative humidity in %
        
    Returns:
        Dew point temperature in °C
    """
    import math
    a = 17.27
    b = 237.7
    
    # Clamp humidity to valid range (avoid log(0))
    humidity = max(1, min(100, humidity))
    
    alpha = (a * temperature) / (b + temperature) + math.log(humidity / 100)
    dew_point = (b * alpha) / (a - alpha)
    
    return round(dew_point, 1)


def _calculate_surface_temperature(indoor_temp: float, outdoor_temp: float, u_value: float) -> float:
    """Calculate window surface temperature using heat transfer physics.
    
    v1.11.0: Used for mold risk assessment with U-value estimation.
    
    Formula: T_surface = T_indoor - (T_indoor - T_outdoor) × U / (U + h)
    where:
        U = window U-value (thermal transmittance, W/m²K)
        h = interior surface heat transfer coefficient = 8 W/m²K
    
    This formula accounts for:
    - Window insulation properties (U-value)
    - Indoor/outdoor temperature difference
    - Interior surface heat transfer
    
    Args:
        indoor_temp: Indoor temperature in °C
        outdoor_temp: Outdoor temperature in °C
        u_value: Window U-value in W/m²K
        
    Returns:
        Estimated surface temperature in °C
        
    References:
        - ASHRAE 160 standard for surface temperature assessment
        - Window condensation risk calculators
    """
    from .const import INTERIOR_SURFACE_HEAT_TRANSFER_COEFFICIENT
    
    h = INTERIOR_SURFACE_HEAT_TRANSFER_COEFFICIENT
    
    # Calculate surface temperature
    temp_diff = indoor_temp - outdoor_temp
    surface_temp = indoor_temp - (temp_diff * u_value / (u_value + h))
    
    return round(surface_temp, 1)


class TadoMoldRiskSensor(TadoBaseSensor):
    """Mold risk indicator sensor.
    
    v1.11.0: Enhanced with 2-tier temperature source strategy:
    - Tier 1: U-value surface temperature estimation (if outdoor temp available)
    - Tier 2: Room average temperature (fallback)
    
    Calculates dew point from temperature and humidity using Magnus-Tetens formula,
    then assesses mold risk based on the margin between temperature and dew point.
    
    Risk Levels (based on condensation margin):
    - Critical: <3°C margin (high mold risk, condensation likely)
    - High: 3-5°C margin (elevated risk, monitor closely)
    - Medium: 5-7°C margin (moderate risk, improve ventilation)
    - Low: >7°C margin (safe, good conditions)
    
    State: Risk level text (Critical/High/Medium/Low)
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Mold Risk"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_mold_risk"
        self._attr_icon = "mdi:mushroom"
        self._attr_translation_key = "mold_risk"  # v1.11.0: Enable translations
        
        # Attributes
        self._room_temp: float | None = None  # v1.11.0: Room temp from Tado sensor
        self._effective_temp: float | None = None  # v1.11.0: Effective temp used for calculation
        self._humidity: float | None = None
        self._dew_point: float | None = None
        self._margin: float | None = None
        self._temperature_source: str = "unknown"  # v1.11.0: Track which tier is active
        self._outdoor_temp: float | None = None  # v1.11.0: For surface temp calculation
        self._surface_temp: float | None = None  # v1.11.0: Calculated surface temp
    
    @property
    def extra_state_attributes(self):
        return {
            "room_temperature": self._room_temp,  # v1.11.0: Always show room temp
            "effective_temperature": self._effective_temp,  # v1.11.0: Temp used for calculation
            "humidity": self._humidity,
            "dew_point": self._dew_point,
            "margin": self._margin,
            "mold_risk_percentage": self._calculate_surface_rh(),  # v1.11.0: RH at surface (mold risk %)
            "temperature_source": self._temperature_source,  # v1.11.0
            "outdoor_temperature": self._outdoor_temp,  # v1.11.0
            "surface_temperature": self._surface_temp,  # v1.11.0
            "zone_type": self._zone_type,
        }
    
    @property
    def icon(self):
        """Dynamic icon based on risk level."""
        if self._attr_native_value == "Critical":
            return "mdi:mushroom-outline"
        elif self._attr_native_value == "High":
            return "mdi:alert-circle"
        elif self._attr_native_value == "Medium":
            return "mdi:alert"
        return "mdi:check-circle"
    
    def update(self):
        """Update mold risk based on temperature and humidity.
        
        v1.11.0: Uses 2-tier temperature source strategy for more accurate assessment.
        """
        try:
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return
            
            # Get humidity from zone data
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._humidity = (sensor_data.get('humidity') or {}).get('percentage')
            
            if self._humidity is None:
                self._attr_available = False
                return
            
            # Get room temperature (always needed as fallback)
            room_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')
            if room_temp is None:
                self._attr_available = False
                return
            
            # v1.11.0: Store room temp and determine effective temp (Tier 1 or Tier 2)
            self._room_temp = room_temp
            self._effective_temp = self._get_effective_temperature(room_temp)
            
            # Calculate dew point using Magnus-Tetens formula (using effective temp)
            self._dew_point = _calculate_dew_point(self._effective_temp, self._humidity)
            
            # Calculate margin (difference between effective temperature and dew point)
            self._margin = round(self._effective_temp - self._dew_point, 1)
            
            # Determine risk level
            if self._margin < 3:
                self._attr_native_value = "Critical"
            elif self._margin < 5:
                self._attr_native_value = "High"
            elif self._margin < 7:
                self._attr_native_value = "Medium"
            else:
                self._attr_native_value = "Low"
            
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update mold risk for zone {self._zone_id}: {e}")
            self._attr_available = False
    
    def _get_effective_temperature(self, room_temp: float) -> float:
        """Get effective temperature for mold risk calculation.
        
        v1.11.0: 2-tier strategy:
        - Tier 1: Surface temperature estimation (if outdoor temp + window type available)
        - Tier 2: Room average temperature (fallback)
        
        Args:
            room_temp: Room average temperature from Tado sensor
            
        Returns:
            Effective temperature for mold risk calculation
        """
        from .config_manager import ConfigurationManager
        from .const import WINDOW_U_VALUES, DEFAULT_WINDOW_TYPE
        
        try:
            # Get config manager
            entries = self.hass.config_entries.async_entries(DOMAIN)
            if not entries:
                self._temperature_source = "room_average"
                return room_temp
            
            config_manager = ConfigurationManager(entries[0])
            
            # Try Tier 1: Surface temperature estimation
            outdoor_entity = config_manager.get_outdoor_temp_entity()
            
            if outdoor_entity:
                # Get outdoor temperature
                self._outdoor_temp = self._get_outdoor_temperature(outdoor_entity, config_manager.get_use_feels_like())
                
                if self._outdoor_temp is not None:
                    # Get window type and U-value
                    window_type = config_manager.get_mold_risk_window_type()
                    u_value = WINDOW_U_VALUES.get(window_type, WINDOW_U_VALUES[DEFAULT_WINDOW_TYPE])
                    
                    # Calculate surface temperature
                    self._surface_temp = _calculate_surface_temperature(room_temp, self._outdoor_temp, u_value)
                    self._temperature_source = "surface_estimation"
                    
                    _LOGGER.debug(
                        f"Mold Risk (Zone {self._zone_id}): Using surface estimation - "
                        f"Room: {room_temp}°C, Outdoor: {self._outdoor_temp}°C, "
                        f"Window: {window_type} (U={u_value}), Surface: {self._surface_temp}°C"
                    )
                    
                    return self._surface_temp
            
            # Tier 2: Fallback to room temperature
            self._temperature_source = "room_average"
            self._outdoor_temp = None
            self._surface_temp = None
            
            _LOGGER.debug(
                f"Mold Risk (Zone {self._zone_id}): Using room average - "
                f"Room: {room_temp}°C (no outdoor temp configured)"
            )
            
            return room_temp
            
        except Exception as e:
            _LOGGER.debug(f"Error determining temperature source for zone {self._zone_id}: {e}")
            self._temperature_source = "room_average"
            self._outdoor_temp = None
            self._surface_temp = None
            return room_temp
    
    def _get_outdoor_temperature(self, entity_id: str, use_feels_like: bool = False) -> float | None:
        """Get outdoor temperature from configured entity.
        
        v1.11.0: Reused from Smart Comfort implementation.
        
        Args:
            entity_id: Entity ID of outdoor temperature sensor or weather entity
            use_feels_like: Whether to use feels-like temperature
            
        Returns:
            Outdoor temperature in °C, or None if not available
        """
        if not self.hass or not entity_id:
            return None
        
        try:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ('unknown', 'unavailable'):
                return None
            
            # Check if it's a weather entity
            if entity_id.startswith('weather.'):
                if use_feels_like:
                    # Try feels-like attributes
                    temp = state.attributes.get('apparent_temperature')
                    if temp is None:
                        temp = state.attributes.get('feels_like')
                    if temp is None:
                        temp = state.attributes.get('temperature')
                else:
                    temp = state.attributes.get('temperature')
                
                if temp is not None:
                    return float(temp)
            else:
                # Regular sensor entity
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    return None
                    
        except Exception as e:
            _LOGGER.debug(f"Error getting outdoor temperature from {entity_id}: {e}")
            return None
        
        return None
    
    def _calculate_surface_rh(self) -> int | None:
        """Calculate relative humidity at surface (mold risk percentage).
        
        v1.11.0: Provides mold risk as percentage for easier comparison with other sensors.
        
        Uses Magnus-Tetens formula to calculate saturation vapor pressure at both
        dew point and surface temperature, then derives relative humidity at surface.
        
        Mold typically grows when surface RH exceeds ~70-80%.
        
        Returns:
            Surface relative humidity as percentage (0-100), or None if data unavailable
        """
        if self._effective_temp is None or self._dew_point is None:
            return None
        
        try:
            import math
            
            # Magnus-Tetens formula for saturation vapor pressure
            # SVP = 6.112 * exp((17.67 * T) / (T + 243.5))
            def svp(temp: float) -> float:
                return 6.112 * math.exp((17.67 * temp) / (temp + 243.5))
            
            # Relative humidity at surface = (SVP at dew point / SVP at surface temp) * 100
            # When surface temp = dew point, RH = 100% (condensation occurs)
            # When surface temp > dew point, RH < 100% (safer)
            surface_rh = (svp(self._dew_point) / svp(self._effective_temp)) * 100
            
            # Clamp to 0-100 range and round to integer
            return round(min(100, max(0, surface_rh)))
            
        except Exception as e:
            _LOGGER.debug(f"Error calculating surface RH for zone {self._zone_id}: {e}")
            return None


class TadoComfortLevelSensor(TadoBaseSensor):
    """Comfort level sensor using Adaptive Comfort model.
    
    Based on ASHRAE 55 adaptive comfort standard, which adjusts comfort
    expectations based on outdoor temperature. Also considers humidity.
    
    Comfort Calculation:
    1. If outdoor temp available: Use adaptive comfort model
       - Comfort temp = 0.31 × outdoor_temp + 17.8°C
       - Acceptable range = ±3°C (90% acceptability)
    2. If no outdoor temp: Use latitude-based seasonal thresholds
       - Adjusts for hemisphere and climate zone
    
    Temperature States: Freezing, Cold, Cool, Comfortable, Warm, Hot, Sweltering
    Humidity Suffix: Dry (<35%), Humid (>70%)
    
    State: Combined comfort text (e.g., "Comfortable", "Cool Dry")
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Comfort Level"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_comfort_level"
        self._attr_icon = "mdi:air-filter"
        
        # Attributes
        self._temperature: float | None = None
        self._humidity: float | None = None
        self._outdoor_temp: float | None = None
        self._comfort_temp: float | None = None
        self._comfort_model: str = "unknown"
        self._dew_point: float | None = None
    
    @property
    def extra_state_attributes(self):
        return {
            "temperature": self._temperature,
            "humidity": self._humidity,
            "outdoor_temperature": self._outdoor_temp,
            "comfort_target": self._comfort_temp,
            "comfort_model": self._comfort_model,
            "dew_point": self._dew_point,
            "zone_type": self._zone_type,
        }
    
    @property
    def icon(self):
        """Dynamic icon based on comfort level."""
        state = self._attr_native_value or ""
        if "Freezing" in state or "Cold" in state:
            return "mdi:snowflake-alert"
        elif "Cool" in state:
            return "mdi:thermometer-low"
        elif "Comfortable" in state:
            return "mdi:emoticon-happy"
        elif "Warm" in state:
            return "mdi:thermometer-high"
        elif "Hot" in state or "Sweltering" in state:
            return "mdi:fire-alert"
        return "mdi:air-filter"
    
    def update(self):
        """Update air comfort using adaptive comfort model."""
        try:
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return
            
            # Get temperature and humidity
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._temperature = (sensor_data.get('insideTemperature') or {}).get('celsius')
            self._humidity = (sensor_data.get('humidity') or {}).get('percentage')
            
            if self._temperature is None:
                self._attr_available = False
                return
            
            # Calculate dew point if humidity available
            if self._humidity is not None:
                self._dew_point = _calculate_dew_point(self._temperature, self._humidity)
            
            # Get outdoor temperature from config
            self._outdoor_temp = self._get_outdoor_temperature()
            
            # Calculate comfort level
            if self._outdoor_temp is not None:
                # Use ASHRAE 55 Adaptive Comfort model
                comfort_level = self._calculate_adaptive_comfort()
                self._comfort_model = "adaptive"
            else:
                # Fallback to latitude-based seasonal thresholds
                comfort_level = self._calculate_seasonal_comfort()
                self._comfort_model = "seasonal"
            
            # Add humidity suffix
            humidity_suffix = self._get_humidity_suffix()
            
            self._attr_native_value = comfort_level + humidity_suffix
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update air comfort for zone {self._zone_id}: {e}")
            self._attr_available = False
    
    def _get_outdoor_temperature(self) -> float | None:
        """Get outdoor temperature from configured entity."""
        if not self.hass:
            return None
        
        try:
            from .config_manager import ConfigurationManager
            entries = self.hass.config_entries.async_entries(DOMAIN)
            if not entries:
                return None
            
            config_manager = ConfigurationManager(entries[0])
            entity_id = config_manager.get_outdoor_temp_entity()
            use_feels_like = config_manager.get_use_feels_like()
            
            if not entity_id:
                return None
            
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ('unknown', 'unavailable'):
                return None
            
            # Check if it's a weather entity
            if entity_id.startswith('weather.'):
                if use_feels_like:
                    apparent = state.attributes.get('apparent_temperature')
                    if apparent is not None:
                        return float(apparent)
                temp = state.attributes.get('temperature')
                if temp is not None:
                    return float(temp)
            else:
                return float(state.state)
        except (ValueError, TypeError, AttributeError):
            pass
        
        return None
    
    def _calculate_adaptive_comfort(self) -> str:
        """Calculate comfort using ASHRAE 55 Adaptive Comfort model.
        
        Formula: Comfort temp = 0.31 × outdoor_temp + 17.8°C
        Acceptable range: ±3°C for 90% acceptability
        
        Returns:
            Comfort level text
        """
        # Calculate neutral comfort temperature
        self._comfort_temp = round(0.31 * self._outdoor_temp + 17.8, 1)
        
        # Calculate deviation from comfort
        deviation = self._temperature - self._comfort_temp
        
        # Determine comfort level based on deviation
        if deviation < -6:
            return "Freezing"
        elif deviation < -4:
            return "Cold"
        elif deviation < -2:
            return "Cool"
        elif deviation <= 2:
            return "Comfortable"
        elif deviation <= 4:
            return "Warm"
        elif deviation <= 6:
            return "Hot"
        else:
            return "Sweltering"
    
    def _calculate_seasonal_comfort(self) -> str:
        """Calculate comfort using latitude-based seasonal thresholds.
        
        Adjusts thresholds based on:
        - Hemisphere (north/south) for season detection
        - Latitude for climate zone (higher latitude = lower thresholds)
        
        Returns:
            Comfort level text
        """
        from datetime import datetime
        
        # Get latitude from HA config
        latitude = 51.5  # Default to London if not available
        if self.hass:
            latitude = self.hass.config.latitude or 51.5
        
        # Determine season based on month and hemisphere
        month = datetime.now().month
        is_southern = latitude < 0
        
        # Adjust month for southern hemisphere
        if is_southern:
            month = (month + 6 - 1) % 12 + 1
        
        # Season detection: Summer (6-8), Winter (12-2), Transition (3-5, 9-11)
        is_summer = 6 <= month <= 8
        is_winter = month >= 11 or month <= 2
        
        # Adjust thresholds based on latitude (climate zone)
        # Higher latitude = people accustomed to lower temps
        lat_abs = abs(latitude)
        if lat_abs > 55:  # Nordic/Subarctic
            lat_offset = -2
        elif lat_abs > 45:  # Northern Europe/Canada
            lat_offset = -1
        elif lat_abs < 30:  # Subtropical
            lat_offset = 2
        elif lat_abs < 40:  # Mediterranean
            lat_offset = 1
        else:
            lat_offset = 0
        
        # Base thresholds for indoor comfort (adjusted for latitude)
        if is_summer:
            thresholds = [19, 21, 23, 25, 27, 29]
        elif is_winter:
            thresholds = [15, 17, 19, 21, 23, 25]
        else:  # Transition
            thresholds = [16, 18, 20, 22, 24, 26]
        
        # Apply latitude offset
        thresholds = [t + lat_offset for t in thresholds]
        
        # Store comfort target (middle of comfortable range)
        self._comfort_temp = (thresholds[2] + thresholds[3]) / 2
        
        # Determine comfort level
        if self._temperature <= thresholds[0]:
            return "Freezing"
        elif self._temperature <= thresholds[1]:
            return "Cold"
        elif self._temperature <= thresholds[2]:
            return "Cool"
        elif self._temperature <= thresholds[3]:
            return "Comfortable"
        elif self._temperature <= thresholds[4]:
            return "Warm"
        elif self._temperature <= thresholds[5]:
            return "Hot"
        else:
            return "Sweltering"
    
    def _get_humidity_suffix(self) -> str:
        """Get humidity suffix for comfort display.
        
        Returns:
            Humidity suffix: " Dry" (<35%), " Humid" (>70%), or "" (normal)
        """
        if self._humidity is None:
            return ""
        
        if self._humidity < 35:
            return " Dry"
        elif self._humidity > 70:
            return " Humid"
        return ""



# ========== v1.11.0: Heating Cycle Analysis Sensors ==========

class TadoThermalInertiaSensor(CoordinatorEntity, SensorEntity):
    """Sensor for thermal inertia time (delay before temperature rises)."""
    
    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Thermal Inertia"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_thermal_inertia"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:timer-sand"
    
    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("inertia_time")
    
    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("inertia_time") is not None
    
    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "confidence_score": zone_data.get("confidence_score", 0.0),
        }


class TadoAvgHeatingRateSensor(CoordinatorEntity, SensorEntity):
    """Sensor for heating rate (°C per minute)."""
    
    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Avg Heating Rate"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_avg_heating_rate"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        self._attr_native_unit_of_measurement = "°C/min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:trending-up"
    
    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("heating_rate")
    
    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("heating_rate") is not None
    
    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "confidence_score": zone_data.get("confidence_score", 0.0),
        }


class TadoPreheatTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for estimated preheat time to reach target temperature."""
    
    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Preheat Time"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_preheat_time"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:clock-fast"
        self._current_temp: Optional[float] = None
        self._target_temp: Optional[float] = None
    
    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        # Get current and target temps from zone data
        zone_data = self._get_zone_data()
        if not zone_data:
            return None
        
        current_temp = zone_data.get("sensorDataPoints", {}).get("insideTemperature", {}).get("celsius")
        target_temp = zone_data.get("setting", {}).get("temperature", {}).get("celsius")
        
        if current_temp is None or target_temp is None:
            return None
        
        # Store for attributes
        self._current_temp = current_temp
        self._target_temp = target_temp
        
        # Get estimate from coordinator
        estimate = self.coordinator.estimate_preheat_time(
            self._zone_id, current_temp, target_temp
        )
        return estimate
    
    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("heating_rate") is not None
    
    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "current_temp": self._current_temp,
            "target_temp": self._target_temp,
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "confidence_score": zone_data.get("confidence_score", 0.0),
        }
    
    def _get_zone_data(self):
        """Get zone data from file."""
        try:
            # Use data_loader for per-home file support
            data = load_zones_file()
            if data:
                zone_states = data.get('zoneStates') or {}
                return zone_states.get(self._zone_id)
            return None
        except Exception:
            return None


class TadoAnalysisConfidenceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for confidence score of preheat estimates (0-100%)."""
    
    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Analysis Confidence"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_analysis_confidence"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:chart-line"
    
    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        # Convert 0.0-1.0 to 0-100%
        confidence = zone_data.get("confidence_score")
        if confidence is not None:
            return round(confidence * 100, 1)
        return None
    
    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None
    
    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
        }


class TadoHeatingAccelerationSensor(CoordinatorEntity, SensorEntity):
    """Sensor for heating acceleration (second-order analysis).

    Measures how quickly the heating rate increases after heating starts.
    Higher acceleration = faster response system.
    """

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Heating Acceleration"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_heating_acceleration"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        self._attr_native_unit_of_measurement = "°C/h²"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:chart-bell-curve-cumulative"

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("acceleration")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("acceleration") is not None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
        }


class TadoApproachFactorSensor(CoordinatorEntity, SensorEntity):
    """Sensor for approach deceleration factor (second-order analysis).

    Measures how much the heating rate decreases as temperature
    approaches the setpoint. Used to predict overshoot.

    Factor interpretation:
    - 100%: No deceleration, will likely overshoot
    - 50%: 50% deceleration, controlled approach
    - 0%: Complete stop before setpoint (rare)
    """

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Approach Factor"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_approach_factor"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:target"

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("approach_factor")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("approach_factor") is not None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "overshoot_estimate": zone_data.get("overshoot_estimate"),
        }

