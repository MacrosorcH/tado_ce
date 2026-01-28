"""Tado CE Sensors."""
import json
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorEntityDescription
from homeassistant.const import UnitOfTemperature, PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, ZONES_FILE, ZONES_INFO_FILE, RATELIMIT_FILE, WEATHER_FILE, MOBILE_DEVICES_FILE, API_CALL_HISTORY_FILE, DEFAULT_ZONE_NAMES, CONFIG_FILE, DATA_DIR, TADO_AUTH_URL, CLIENT_ID
from .device_manager import get_hub_device_info, get_zone_device_info
from .auth_manager import get_auth_manager
from .data_loader import (
    load_zones_file, load_zones_info_file, load_weather_file,
    load_config_file, load_ratelimit_file, load_api_call_history_file,
    get_zone_names as dl_get_zone_names
)

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
        # Only zones with TRVs should have Smart Heating sensors
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
                    ])
                    # v1.9.0: Smart Heating sensors (opt-in)
                    if config_manager.get_smart_heating_enabled():
                        # Heating/Cooling Rate - useful for all zones with temperature sensor
                        sensors.extend([
                            TadoHeatingRateSensor(zone_id, zone_name, zone_type),
                            TadoCoolingRateSensor(zone_id, zone_name, zone_type),
                            TadoComfortLevelSensor(zone_id, zone_name, zone_type),
                            TadoHeatingEfficiencySensor(zone_id, zone_name, zone_type),
                        ])
                        # Time to Target - only for zones with TRV (heating control)
                        if zone_id in zones_with_trv:
                            sensors.append(TadoTimeToTargetSensor(zone_id, zone_name, zone_type))
                elif zone_type == 'AIR_CONDITIONING':
                    sensors.extend([
                        TadoTemperatureSensor(zone_id, zone_name, zone_type),
                        TadoHumiditySensor(zone_id, zone_name, zone_type),
                        TadoACPowerSensor(zone_id, zone_name, zone_type),
                        TadoTargetTempSensor(zone_id, zone_name, zone_type),
                        TadoOverlaySensor(zone_id, zone_name, zone_type),
                    ])
                    # v1.9.0: Smart Heating sensors for AC (opt-in, always create for AC zones)
                    if config_manager.get_smart_heating_enabled():
                        sensors.extend([
                            TadoHeatingRateSensor(zone_id, zone_name, zone_type),
                            TadoCoolingRateSensor(zone_id, zone_name, zone_type),
                            TadoTimeToTargetSensor(zone_id, zone_name, zone_type),
                            TadoComfortLevelSensor(zone_id, zone_name, zone_type),
                            TadoHeatingEfficiencySensor(zone_id, zone_name, zone_type),
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
        _LOGGER.debug(f"Failed to load device info: {e}")
    
    async_add_entities(sensors, True)
    _LOGGER.info(f"Tado CE sensors loaded: {len(sensors)}")


def _has_boiler_flow_temperature_data():
    """Check if any zone has boiler flow temperature data (requires OpenTherm).
    
    This is used during setup to determine if the boiler flow temperature
    sensor should be created. Only systems with OpenTherm connection between
    Tado and the boiler will have this data.
    """
    try:
        with open(ZONES_FILE) as f:
            data = json.load(f)
        
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
        self._attr_name = "Tado CE Home ID"
        self._attr_unique_id = "tado_ce_home_id"
        self._attr_icon = "mdi:home"
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
    
    def update(self):
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
                self._attr_native_value = config.get("home_id")
                self._attr_available = self._attr_native_value is not None
        except Exception:
            self._attr_available = False


class TadoApiUsageSensor(SensorEntity):
    """Sensor for Tado API usage tracking."""
    
    def __init__(self):
        self._attr_name = "Tado CE API Usage"
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
            with open(RATELIMIT_FILE) as f:
                self._data = json.load(f)
                used = self._data.get("used")
                if used is not None:
                    self._attr_native_value = int(used)
                    self._attr_available = True
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
                
                tracker = APICallTracker(DATA_DIR, retention_days=retention_days)
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
            except Exception as e:
                _LOGGER.debug(f"Failed to load call history: {e}")
                self._call_history = []
                
        except Exception:
            self._attr_available = False

class TadoApiResetSensor(SensorEntity):
    """Sensor showing API rate limit reset time."""
    
    def __init__(self):
        self._attr_name = "Tado CE API Reset"
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
            
            with open(RATELIMIT_FILE) as f:
                data = json.load(f)
                
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
        self._attr_name = "Tado CE API Limit"
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
            with open(RATELIMIT_FILE) as f:
                data = json.load(f)
                self._attr_native_value = data.get("limit")
                self._attr_available = self._attr_native_value is not None
            
            # Load recent API calls from history (last 100 calls only to avoid DB size issues)
            try:
                from datetime import datetime, timedelta
                from homeassistant.util import dt as dt_util
                
                with open(API_CALL_HISTORY_FILE) as f:
                    history = json.load(f)
                    
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
        self._attr_name = "Tado CE API Status"
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
            with open(RATELIMIT_FILE) as f:
                data = json.load(f)
                self._attr_native_value = data.get("status", "unknown")
                self._attr_available = True
        except Exception:
            self._attr_native_value = "error"
            self._attr_available = True

class TadoTokenStatusSensor(SensorEntity):
    """Sensor showing Tado token status."""
    
    def __init__(self):
        self._attr_name = "Tado CE Token Status"
        self._attr_unique_id = "tado_ce_token_status"
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
    
    @property
    def icon(self):
        if self._attr_native_value == "valid":
            return "mdi:key-check"
        return "mdi:key-alert"
    
    def update(self):
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
                if config.get("refresh_token"):
                    self._attr_native_value = "valid"
                else:
                    self._attr_native_value = "missing"
                self._attr_available = True
        except Exception:
            self._attr_native_value = "error"
            self._attr_available = True

class TadoZoneCountSensor(SensorEntity):
    """Sensor showing number of Tado zones."""
    
    def __init__(self):
        self._attr_name = "Tado CE Zone Count"
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
            with open(ZONES_INFO_FILE) as f:
                zones = json.load(f)
                self._attr_native_value = len(zones)
                self._heating_zones = len([z for z in zones if z.get('type') == 'HEATING'])
                self._hot_water_zones = len([z for z in zones if z.get('type') == 'HOT_WATER'])
                self._ac_zones = len([z for z in zones if z.get('type') == 'AIR_CONDITIONING'])
                self._attr_available = True
        except Exception:
            self._attr_available = False

class TadoLastSyncSensor(SensorEntity):
    """Sensor showing last sync time."""
    
    def __init__(self):
        self._attr_name = "Tado CE Last Sync"
        self._attr_unique_id = "tado_ce_last_sync"
        self._attr_icon = "mdi:sync"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = False
        self._attr_native_value = None
    
    def update(self):
        try:
            with open(RATELIMIT_FILE) as f:
                data = json.load(f)
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
        except Exception:
            self._attr_available = False

# ============ Weather Sensors ============

class TadoOutsideTemperatureSensor(SensorEntity):
    """Outside temperature from Tado weather data."""
    
    def __init__(self):
        self._attr_name = "Tado CE Outside Temperature"
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
            with open(WEATHER_FILE) as f:
                data = json.load(f)
                # Use 'or {}' pattern for null safety
                temp_data = data.get('outsideTemperature') or {}
                self._attr_native_value = temp_data.get('celsius')
                self._timestamp = temp_data.get('timestamp')
                self._attr_available = self._attr_native_value is not None
        except Exception:
            self._attr_available = False

class TadoSolarIntensitySensor(SensorEntity):
    """Solar intensity from Tado weather data."""
    
    def __init__(self):
        self._attr_name = "Tado CE Solar Intensity"
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
            with open(WEATHER_FILE) as f:
                data = json.load(f)
                # Use 'or {}' pattern for null safety
                solar_data = data.get('solarIntensity') or {}
                self._attr_native_value = solar_data.get('percentage')
                self._timestamp = solar_data.get('timestamp')
                self._attr_available = self._attr_native_value is not None
        except Exception:
            self._attr_available = False

class TadoWeatherStateSensor(SensorEntity):
    """Weather state from Tado weather data."""
    
    def __init__(self):
        self._attr_name = "Tado CE Weather"
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
            with open(WEATHER_FILE) as f:
                data = json.load(f)
                # Use 'or {}' pattern for null safety
                weather_data = data.get('weatherState') or {}
                self._raw_state = weather_data.get('value')
                self._timestamp = weather_data.get('timestamp')
                self._attr_native_value = WEATHER_STATE_MAP.get(self._raw_state, self._raw_state)
                self._attr_available = self._attr_native_value is not None
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
    
    def _get_zone_data(self):
        """Get zone data from file."""
        try:
            with open(ZONES_FILE) as f:
                data = json.load(f)
                # Use 'or {}' pattern for null safety
                zone_states = data.get('zoneStates') or {}
                return zone_states.get(self._zone_id)
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
        self._attr_name = f"{zone_name} Heating"
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
        self._attr_name = "Tado CE Boiler Flow Temperature"
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
            with open(ZONES_FILE) as f:
                data = json.load(f)
            
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
            with open(ZONES_INFO_FILE) as f:
                zones_info = json.load(f)
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
            with open(ZONES_INFO_FILE) as f:
                zones_info = json.load(f)
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


# ============ Smart Heating Sensors (v1.9.0) ============

class TadoHeatingRateSensor(TadoBaseSensor):
    """Heating rate sensor - shows °C/hour when HVAC is active.
    
    For HEATING zones: Rate of temperature increase when heating.
    For AC zones: Rate of temperature change when AC is running.
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Heating Rate"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_heating_rate"
        self._attr_native_unit_of_measurement = "°C/h"
        self._attr_icon = "mdi:thermometer-chevron-up"
        self._attr_state_class = "measurement"
        self._data_points = 0
    
    @property
    def extra_state_attributes(self):
        return {
            "data_points": self._data_points,
            "zone_type": self._zone_type,
        }
    
    def update(self):
        """Update heating rate from SmartHeatingManager."""
        try:
            # v1.9.0: Use hass.data instead of global singleton for multi-home support
            manager = self.hass.data.get(DOMAIN, {}).get('smart_heating_manager') if self.hass else None
            
            if not manager or not manager.is_enabled:
                self._attr_available = False
                return
            
            rate = manager.get_heating_rate(self._zone_id)
            if rate is not None:
                self._attr_native_value = rate
                self._attr_available = True
                # Get data points count
                zone = manager.get_zone(self._zone_id)
                heating_readings = [r for r in zone.readings if r.is_heating]
                self._data_points = len(heating_readings)
            else:
                self._attr_native_value = None
                self._attr_available = False
                self._data_points = 0
        except Exception as e:
            _LOGGER.debug(f"Failed to update heating rate for zone {self._zone_id}: {e}")
            self._attr_available = False


class TadoCoolingRateSensor(TadoBaseSensor):
    """Cooling rate sensor - shows °C/hour when HVAC is off.
    
    For HEATING zones: Rate of temperature decrease when heating is off (heat loss).
    For AC zones: Rate of temperature change when AC is off.
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Cooling Rate"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_cooling_rate"
        self._attr_native_unit_of_measurement = "°C/h"
        self._attr_icon = "mdi:thermometer-chevron-down"
        self._attr_state_class = "measurement"
        self._data_points = 0
    
    @property
    def extra_state_attributes(self):
        return {
            "data_points": self._data_points,
            "zone_type": self._zone_type,
        }
    
    def update(self):
        """Update cooling rate from SmartHeatingManager."""
        try:
            # v1.9.0: Use hass.data instead of global singleton for multi-home support
            manager = self.hass.data.get(DOMAIN, {}).get('smart_heating_manager') if self.hass else None
            
            if not manager or not manager.is_enabled:
                self._attr_available = False
                return
            
            rate = manager.get_cooling_rate(self._zone_id)
            if rate is not None:
                self._attr_native_value = rate
                self._attr_available = True
                # Get data points count
                zone = manager.get_zone(self._zone_id)
                cooling_readings = [r for r in zone.readings if not r.is_heating]
                self._data_points = len(cooling_readings)
            else:
                self._attr_native_value = None
                self._attr_available = False
                self._data_points = 0
        except Exception as e:
            _LOGGER.debug(f"Failed to update cooling rate for zone {self._zone_id}: {e}")
            self._attr_available = False


class TadoHeatingEfficiencySensor(TadoBaseSensor):
    """Heating efficiency sensor - compares current rate vs baseline.
    
    Shows percentage of baseline heating rate, helping identify:
    - Slow heating (possible issues like open windows, poor insulation)
    - Fast heating (external heat sources like sun, cooking)
    
    State: Percentage (100% = normal, <75% = slow, >125% = fast)
    """
    
    # Thresholds for status determination
    SLOW_THRESHOLD = 75   # Below 75% = slow
    FAST_THRESHOLD = 125  # Above 125% = fast
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Heating Efficiency"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_heating_efficiency"
        self._attr_native_unit_of_measurement = "%"
        self._attr_icon = "mdi:gauge"
        self._attr_state_class = "measurement"
        
        # Attributes
        self._current_rate: float | None = None
        self._baseline_rate: float | None = None
        self._status: str = "unknown"
    
    @property
    def extra_state_attributes(self):
        return {
            "current_rate": self._current_rate,
            "baseline_rate": self._baseline_rate,
            "status": self._status,
            "zone_type": self._zone_type,
        }
    
    @property
    def icon(self):
        """Dynamic icon based on status."""
        if self._status == "slow":
            return "mdi:gauge-low"
        elif self._status == "fast":
            return "mdi:gauge-full"
        elif self._status == "normal":
            return "mdi:gauge"
        return "mdi:gauge-empty"
    
    def update(self):
        """Update heating efficiency from SmartHeatingManager."""
        try:
            manager = self.hass.data.get(DOMAIN, {}).get('smart_heating_manager') if self.hass else None
            
            if not manager or not manager.is_enabled:
                self._attr_available = False
                return
            
            self._current_rate = manager.get_heating_rate(self._zone_id)
            self._baseline_rate = manager.get_baseline_heating_rate(self._zone_id)
            
            # Need both rates to calculate efficiency
            if self._current_rate is None or self._baseline_rate is None:
                self._attr_native_value = None
                self._attr_available = False
                self._status = "unknown"
                return
            
            # Avoid division by zero
            if self._baseline_rate == 0:
                # If baseline is 0 but current is positive, that's unusual
                if self._current_rate > 0:
                    self._attr_native_value = 999  # Cap at 999%
                    self._status = "fast"
                else:
                    self._attr_native_value = 100  # Both zero = normal
                    self._status = "normal"
            else:
                # Calculate efficiency percentage
                efficiency = (self._current_rate / self._baseline_rate) * 100
                self._attr_native_value = round(efficiency, 0)
                
                # Determine status
                if efficiency < self.SLOW_THRESHOLD:
                    self._status = "slow"
                elif efficiency > self.FAST_THRESHOLD:
                    self._status = "fast"
                else:
                    self._status = "normal"
            
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update heating efficiency for zone {self._zone_id}: {e}")
            self._attr_available = False
            self._status = "unknown"


class TadoTimeToTargetSensor(TadoBaseSensor):
    """Time to target sensor - estimated minutes to reach target temperature."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Time to Target"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_time_to_target"
        self._attr_native_unit_of_measurement = "min"
        self._attr_icon = "mdi:timer-outline"
        self._current_temp = None
        self._target_temp = None
        self._outdoor_temp = None
        self._weather_compensation = "none"
    
    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "target_temperature": self._target_temp,
            "outdoor_temperature": self._outdoor_temp,
            "weather_compensation": self._weather_compensation,
            "zone_type": self._zone_type,
        }
    
    def update(self):
        """Update time to target from SmartHeatingManager."""
        try:
            # v1.9.0: Use hass.data instead of global singleton for multi-home support
            manager = self.hass.data.get(DOMAIN, {}).get('smart_heating_manager') if self.hass else None
            
            if not manager or not manager.is_enabled:
                self._attr_available = False
                return
            
            # Get weather compensation info
            self._outdoor_temp = manager.get_outdoor_temperature()
            self._weather_compensation = manager._weather_compensation
            
            # Get current and target temperature from zone data
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return
            
            # Current temperature
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')
            
            # Target temperature
            setting = zone_data.get('setting') or {}
            if setting.get('power') == 'ON':
                self._target_temp = (setting.get('temperature') or {}).get('celsius')
            else:
                self._target_temp = None
            
            # Calculate time to target
            if self._current_temp is not None and self._target_temp is not None:
                # Use weather-compensated time if available
                minutes = manager.get_compensated_time_to_target(
                    self._zone_id,
                    self._current_temp,
                    self._target_temp,
                    self._zone_type
                )
                # Fallback to non-compensated if compensation not configured
                if minutes is None:
                    minutes = manager.get_time_to_target(
                        self._zone_id,
                        self._current_temp,
                        self._target_temp,
                        self._zone_type
                    )
                if minutes is not None:
                    self._attr_native_value = minutes
                    self._attr_available = True
                else:
                    self._attr_native_value = None
                    self._attr_available = False
            else:
                self._attr_native_value = None
                self._attr_available = False
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update time to target for zone {self._zone_id}: {e}")
            self._attr_available = False


# ============ Comfort Level Sensor (v1.9.0) ============

class TadoComfortLevelSensor(TadoBaseSensor):
    """Sensor showing comfort level as readable text.
    
    Displays:
    - "Comfortable" when temperature is within comfort range
    - "Too Cold" when HEATING zone is below threshold
    - "Too Hot" when AC zone is above threshold
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(zone_id, zone_name, zone_type)
        self._attr_name = f"{zone_name} Comfort Level"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_comfort_level"
        self._attr_icon = "mdi:thermometer-check"
        self._current_temp = None
        self._threshold = None
        self._using_config_threshold = False
    
    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "threshold": self._threshold,
            "zone_type": self._zone_type,
            "using_config_threshold": self._using_config_threshold,
        }
    
    def update(self):
        """Update comfort status based on temperature vs threshold."""
        try:
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return
            
            # Get current temperature
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')
            
            if self._current_temp is None:
                self._attr_available = False
                return
            
            # Determine threshold: use active target if available, else config threshold
            setting = zone_data.get('setting') or {}
            self._using_config_threshold = False
            self._threshold = None
            
            if setting.get('power') == 'ON':
                self._threshold = (setting.get('temperature') or {}).get('celsius')
            
            if self._threshold is None:
                self._using_config_threshold = True
                self._threshold = self._get_config_threshold()
            
            # Determine comfort status
            if self._zone_type == 'HEATING':
                if self._current_temp < self._threshold:
                    self._attr_native_value = "Too Cold"
                    self._attr_icon = "mdi:snowflake-alert"
                else:
                    self._attr_native_value = "Comfortable"
                    self._attr_icon = "mdi:thermometer-check"
            else:  # AC
                if self._current_temp > self._threshold:
                    self._attr_native_value = "Too Hot"
                    self._attr_icon = "mdi:fire-alert"
                else:
                    self._attr_native_value = "Comfortable"
                    self._attr_icon = "mdi:thermometer-check"
            
            self._attr_available = True
            
        except Exception as e:
            _LOGGER.debug(f"Failed to update comfort status for zone {self._zone_id}: {e}")
            self._attr_available = False
    
    def _get_config_threshold(self) -> float:
        """Get comfort threshold from config, with fallback defaults."""
        try:
            if self.hass:
                from .config_manager import ConfigurationManager
                entries = self.hass.config_entries.async_entries(DOMAIN)
                if entries:
                    config_manager = ConfigurationManager(entries[0])
                    if self._zone_type == 'HEATING':
                        return config_manager.get_comfort_threshold_heating()
                    else:
                        return config_manager.get_comfort_threshold_cooling()
        except Exception as e:
            _LOGGER.debug(f"Could not get comfort threshold from config, using default: {e}")
        
        # Fallback defaults
        return 18.0 if self._zone_type == 'HEATING' else 26.0
