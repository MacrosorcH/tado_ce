"""Tado CE Binary Sensors."""
import json
import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ZONES_FILE, ZONES_INFO_FILE
from .device_manager import get_hub_device_info, get_zone_device_info
from .data_loader import load_zones_file, load_zones_info_file, get_zone_names

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up Tado CE binary sensors from a config entry."""
    _LOGGER.debug("Tado CE binary_sensor: Setting up...")
    zone_names = await hass.async_add_executor_job(get_zone_names)
    zones_info = await hass.async_add_executor_job(load_zones_info_file)
    
    # Get configuration manager from hass data
    from .config_manager import ConfigurationManager
    config_manager = ConfigurationManager(entry)
    
    sensors = []
    
    # Home/Away sensor (global)
    sensors.append(TadoHomeSensor())
    
    # Open Window sensors (per zone that supports it)
    if zones_info:
        for zone in zones_info:
            zone_id = str(zone.get('id'))
            zone_name = zone.get('name', f"Zone {zone_id}")
            zone_type = zone.get('type')
            
            # Only add open window for heating zones that support it
            if zone_type == 'HEATING':
                owd = zone.get('openWindowDetection') or {}
                if owd.get('supported', False):
                    sensors.append(TadoOpenWindowSensor(zone_id, zone_name, zone_type))
            
            # v1.9.0: Smart Heating - Comfort at Risk sensor (opt-in)
            if config_manager.get_smart_heating_enabled():
                if zone_type in ('HEATING', 'AIR_CONDITIONING'):
                    sensors.append(TadoComfortAtRiskSensor(zone_id, zone_name, zone_type))
    
    async_add_entities(sensors, True)
    _LOGGER.info(f"Tado CE binary sensors loaded: {len(sensors)}")


class TadoHomeSensor(BinarySensorEntity):
    """Binary sensor for Tado Home/Away status."""
    
    def __init__(self):
        self._attr_name = "Tado CE Home"
        self._attr_unique_id = "tado_ce_home"
        self._attr_device_class = BinarySensorDeviceClass.PRESENCE
        self._attr_available = False
        self._attr_is_on = None
        # Use hub device info for global entities
        self._attr_device_info = get_hub_device_info()
        self._tado_mode = None
    
    @property
    def extra_state_attributes(self):
        return {
            "tado_mode": self._tado_mode,
        }
    
    def update(self):
        try:
            with open(ZONES_FILE) as f:
                data = json.load(f)
                # Get tado mode from first zone
                # Use 'or {}' pattern for null safety
                zone_states = data.get('zoneStates') or {}
                for zone_id, zone_data in zone_states.items():
                    self._tado_mode = zone_data.get('tadoMode')
                    if self._tado_mode:
                        self._attr_is_on = self._tado_mode == 'HOME'
                        self._attr_available = True
                        return
            self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoOpenWindowSensor(BinarySensorEntity):
    """Binary sensor for Tado Open Window detection."""
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Open Window"
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_open_window"
        self._attr_device_class = BinarySensorDeviceClass.WINDOW
        self._attr_available = False
        self._attr_is_on = None
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        self._detected_time = None
        self._expiry_time = None
    
    @property
    def extra_state_attributes(self):
        return {
            "detected_time": self._detected_time,
            "expiry_time": self._expiry_time,
        }
    
    def update(self):
        try:
            with open(ZONES_FILE) as f:
                data = json.load(f)
                # Use 'or {}' pattern for null safety
                zone_states = data.get('zoneStates') or {}
                zone_data = zone_states.get(self._zone_id)
                
                if not zone_data:
                    self._attr_available = False
                    return
                
                open_window = zone_data.get('openWindow')
                if open_window:
                    self._attr_is_on = True
                    self._detected_time = open_window.get('detectedTime')
                    self._expiry_time = open_window.get('expiryTime')
                else:
                    self._attr_is_on = False
                    self._detected_time = None
                    self._expiry_time = None
                
                self._attr_available = True
        except Exception:
            self._attr_available = False


# ============ Smart Heating Binary Sensors (v1.9.0) ============

class TadoComfortAtRiskSensor(BinarySensorEntity):
    """Binary sensor indicating if comfort target is at risk of being missed.
    
    Uses SmartHeatingManager to predict if the zone will reach target temperature
    before the next schedule change. Useful for early warning when heating/cooling
    may not be sufficient.
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Comfort at Risk"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_comfort_at_risk"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_available = False
        self._attr_is_on = None
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        
        # Extra attributes
        self._current_temp = None
        self._target_temp = None
        self._predicted_temp = None
        self._minutes_until_schedule = None
        self._is_heating = None
    
    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "target_temperature": self._target_temp,
            "predicted_temperature": self._predicted_temp,
            "minutes_until_schedule": self._minutes_until_schedule,
            "is_heating": self._is_heating,
            "zone_type": self._zone_type,
        }
    
    def update(self):
        """Update comfort at risk status from SmartHeatingManager."""
        try:
            from .smart_heating import get_smart_heating_manager
            from datetime import datetime
            
            manager = get_smart_heating_manager()
            
            if not manager.is_enabled:
                self._attr_available = False
                return
            
            # Get zone data
            with open(ZONES_FILE) as f:
                data = json.load(f)
                zone_states = data.get('zoneStates') or {}
                zone_data = zone_states.get(self._zone_id)
            
            if not zone_data:
                self._attr_available = False
                return
            
            # Current temperature
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')
            
            # Current target temperature (what we're trying to reach NOW)
            setting = zone_data.get('setting') or {}
            current_target = None
            if setting.get('power') == 'ON':
                current_target = (setting.get('temperature') or {}).get('celsius')
            
            # Is heating/cooling active?
            activity_data = zone_data.get('activityDataPoints') or {}
            if self._zone_type == 'HEATING':
                heating_power = (activity_data.get('heatingPower') or {}).get('percentage', 0)
                self._is_heating = heating_power > 0
            else:
                # AC zone
                ac_power = (activity_data.get('acPower') or {}).get('value')
                self._is_heating = ac_power == 'ON'
            
            # For HEATING zones: if current >= current_target, we're comfortable, no risk
            # For AC zones: if current <= current_target, we're comfortable, no risk
            if current_target is not None and self._current_temp is not None:
                if self._zone_type == 'HEATING':
                    if self._current_temp >= current_target:
                        # Already at or above target, no risk
                        self._target_temp = current_target
                        self._minutes_until_schedule = None
                        self._attr_is_on = False
                        self._attr_available = True
                        return
                else:  # AC
                    if self._current_temp <= current_target:
                        # Already at or below target, no risk
                        self._target_temp = current_target
                        self._minutes_until_schedule = None
                        self._attr_is_on = False
                        self._attr_available = True
                        return
            
            # We need to reach current_target - check if we can make it
            self._target_temp = current_target
            
            # Next schedule change (for informational purposes only)
            next_change = zone_data.get('nextScheduleChange')
            if next_change and next_change.get('start'):
                try:
                    next_time = datetime.fromisoformat(next_change['start'].replace('Z', '+00:00'))
                    now = datetime.now(next_time.tzinfo)
                    self._minutes_until_schedule = int((next_time - now).total_seconds() / 60)
                except Exception:
                    self._minutes_until_schedule = None
            else:
                self._minutes_until_schedule = None
            
            # If no current target or already comfortable, no risk assessment needed
            if self._target_temp is None:
                self._attr_is_on = None
                self._attr_available = False
                return
            
            # Check if we have enough data to predict
            # Note: minutes_until_schedule may be None if no schedule change pending
            # In that case, we use a default prediction window (e.g., 60 minutes)
            prediction_minutes = self._minutes_until_schedule if self._minutes_until_schedule and self._minutes_until_schedule > 0 else 60
            
            # Get prediction
            zone = manager.get_zone(self._zone_id)
            self._predicted_temp = zone.predict_temperature(
                prediction_minutes, 
                self._is_heating
            )
            
            # Check if comfort is at risk
            at_risk = manager.is_comfort_at_risk(
                self._zone_id,
                self._current_temp,
                self._target_temp,
                prediction_minutes,
                self._is_heating,
                self._zone_type
            )
            
            if at_risk is not None:
                self._attr_is_on = at_risk
                self._attr_available = True
            else:
                self._attr_is_on = None
                self._attr_available = False
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update comfort at risk for zone {self._zone_id}: {e}")
            self._attr_available = False
