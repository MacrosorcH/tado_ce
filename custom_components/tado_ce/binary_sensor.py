"""Tado CE Binary Sensors."""
import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.core import HomeAssistant

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
    
    # Check if Smart Comfort is enabled (required for Preheat Now sensor)
    smart_comfort_enabled = entry.options.get('smart_comfort_enabled', False)
    
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
                
                # Add Preheat Now sensor if Smart Comfort is enabled
                if smart_comfort_enabled:
                    sensors.append(TadoPreheatNowSensor(zone_id, zone_name, zone_type))
            

    
    async_add_entities(sensors, False)  # Don't update before add - self.hass not set yet
    _LOGGER.debug(f"Tado CE binary sensors loaded: {len(sensors)}")


class TadoHomeSensor(BinarySensorEntity):
    """Binary sensor for Tado Home/Away status."""
    
    def __init__(self):
        self._attr_name = "Home"
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
            # Use data_loader for per-home file support
            data = load_zones_file()
            if data:
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
        self._attr_name = f"{zone_name} Window"
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
            # Use data_loader for per-home file support
            data = load_zones_file()
            if data:
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
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoPreheatNowSensor(BinarySensorEntity):
    """Binary sensor indicating when to start preheating.
    
    Turns ON when current time >= recommended preheat start time.
    Uses data from TadoPreheatAdvisorSensor to determine timing.
    
    v2.0.0: UFH buffer is already applied in TadoPreheatAdvisorSensor,
    so this sensor just reads the adjusted time directly.
    """
    
    def __init__(self, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = f"{zone_name} Preheat Now"
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_preheat_now"
        self._attr_device_class = BinarySensorDeviceClass.HEAT
        self._attr_available = False
        self._attr_is_on = None
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type)
        
        # Attributes for debugging/display
        self._recommended_start = None
        self._target_time = None
        self._target_temp = None
        self._current_temp = None
        self._duration_minutes = None
        self._confidence = "unknown"
    
    @property
    def extra_state_attributes(self):
        return {
            "recommended_start": self._recommended_start,
            "target_time": self._target_time,
            "target_temperature": self._target_temp,
            "current_temperature": self._current_temp,
            "duration_minutes": self._duration_minutes,
            "confidence": self._confidence,
            "zone_type": self._zone_type,
        }
    
    @property
    def icon(self):
        """Dynamic icon based on state."""
        if self._attr_is_on:
            return "mdi:radiator"
        return "mdi:radiator-off"
    
    def update(self):
        """Update preheat now status.
        
        Logic:
        1. Get preheat advisor data for this zone (already includes UFH buffer)
        2. If recommended start time exists and is valid
        3. Turn ON if current time >= recommended start time
        """
        try:
            from datetime import datetime
            
            if not self.hass:
                self._attr_available = False
                return
            
            # Find the preheat advisor sensor for this zone
            # Try different entity_id formats
            zone_slug = self._zone_name.lower().replace(' ', '_')
            preheat_advisor_id = f"sensor.{zone_slug}_preheat_advisor"
            preheat_state = self.hass.states.get(preheat_advisor_id)
            
            if not preheat_state:
                # Try with zone name as-is
                preheat_advisor_id = f"sensor.{self._zone_name}_preheat_advisor"
                preheat_state = self.hass.states.get(preheat_advisor_id)
            
            # Copy attributes from preheat advisor
            if preheat_state:
                self._target_time = preheat_state.attributes.get('target_time')
                self._target_temp = preheat_state.attributes.get('target_temperature')
                self._current_temp = preheat_state.attributes.get('current_temperature')
                self._duration_minutes = preheat_state.attributes.get('duration_minutes')
                self._confidence = preheat_state.attributes.get('confidence', 'unknown')
            
            # Check for non-actionable states
            non_actionable_states = ('unavailable', 'unknown', 'No schedule', 'Heating OFF', 'Ready', 'Insufficient data')
            if not preheat_state or preheat_state.state in non_actionable_states:
                self._attr_is_on = False
                self._attr_available = True
                self._recommended_start = None
                return
            
            # Parse recommended start time (format: "HH:MM")
            # Note: UFH buffer is already applied in TadoPreheatAdvisorSensor
            try:
                recommended_str = preheat_state.state
                now = datetime.now()
                recommended_time = datetime.strptime(recommended_str, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                
                self._recommended_start = recommended_str
                
                # Check if it's time to preheat
                self._attr_is_on = now >= recommended_time
                self._attr_available = True
                
            except ValueError:
                # Invalid time format
                self._attr_is_on = False
                self._attr_available = True
                self._recommended_start = None
                
        except Exception as e:
            _LOGGER.debug(f"Failed to update preheat now for zone {self._zone_id}: {e}")
            self._attr_available = False



