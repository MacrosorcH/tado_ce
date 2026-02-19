"""Zone configuration entities - per-zone settings as HA entities.

v2.1.0: Per-zone configuration entities for heating type, overlay mode,
temperature limits, etc.
"""
import logging
import re
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo  # Keep for type hints
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    HEATING_TYPE_OPTIONS,
    OVERLAY_MODE_OPTIONS, OVERLAY_MODE_MAP, OVERLAY_MODE_REVERSE_MAP,
    OVERLAY_MODE_DEFAULT, OVERLAY_MODE_DEFAULT_DISPLAY,
    SMART_COMFORT_MODE_OPTIONS,
    WINDOW_TYPE_OPTIONS, WINDOW_TYPE_MAP, WINDOW_TYPE_REVERSE_MAP,
    TIMER_DURATION_OPTIONS, TIMER_DURATION_DEFAULT,
    ZONE_UFH_BUFFER_MIN, ZONE_UFH_BUFFER_MAX, ZONE_UFH_BUFFER_STEP,
    ZONE_MIN_TEMP_MIN, ZONE_MIN_TEMP_MAX, ZONE_MAX_TEMP_MIN, ZONE_MAX_TEMP_MAX, ZONE_TEMP_STEP,
    TEMP_OFFSET_MIN, TEMP_OFFSET_MAX, TEMP_OFFSET_STEP,
    SURFACE_TEMP_OFFSET_MIN, SURFACE_TEMP_OFFSET_MAX, SURFACE_TEMP_OFFSET_STEP,
)
from .zone_config_manager import ZoneConfigManager

_LOGGER = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text to slug format for entity_id.
    
    Converts "Living Room" to "living_room".
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text


def _get_zone_device_info(zone_id: str, zone_name: str, zone_type: str) -> DeviceInfo:
    """Get device info for zone entity registration.
    
    Uses the same identifier format as device_manager.py to ensure
    zone config entities are registered to the existing zone device.
    """
    from .device_manager import get_zone_device_info
    return get_zone_device_info(zone_id, zone_name, zone_type)


# =============================================================================
# Heat Emitter Type Select (Heating only)
# =============================================================================

class TadoHeatingTypeSelect(SelectEntity):
    """Select entity for zone heat emitter type (Radiator/UFH).
    
    Only available for HEATING zones.
    """
    
    _attr_options = HEATING_TYPE_OPTIONS
    _attr_icon = "mdi:radiator"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize heat emitter type select."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_heating_type"
        self._attr_name = "Heat Emitter Type"
        self.entity_id = f"select.{slug}_heating_type"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, "HEATING")
    
    @property
    def current_option(self) -> str:
        """Return current heat emitter type."""
        config = self._config_manager.get_zone_config(self._zone_id)
        heating_type = config.get("heating_type", "radiator")
        return "UFH" if heating_type == "ufh" else "Radiator"
    
    async def async_select_option(self, option: str) -> None:
        """Set heat emitter type."""
        value = "ufh" if option == "UFH" else "radiator"
        await self._config_manager.async_set_zone_value(
            self._zone_id, "heating_type", value
        )
        self.async_write_ha_state()


# =============================================================================
# UFH Buffer Number (Heating only, when heating_type=UFH)
# =============================================================================

class TadoUFHBufferNumber(NumberEntity):
    """Number entity for UFH buffer minutes.
    
    Only visible when heating_type = "UFH".
    """
    
    _attr_native_min_value = ZONE_UFH_BUFFER_MIN
    _attr_native_max_value = ZONE_UFH_BUFFER_MAX
    _attr_native_step = ZONE_UFH_BUFFER_STEP
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize UFH buffer number."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_ufh_buffer"
        self._attr_name = "UFH Buffer"
        self.entity_id = f"number.{slug}_ufh_buffer"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, "HEATING")
    
    @property
    def native_value(self) -> float:
        """Return current UFH buffer."""
        config = self._config_manager.get_zone_config(self._zone_id)
        return config.get("ufh_buffer_minutes", 30)
    
    async def async_set_native_value(self, value: float) -> None:
        """Set UFH buffer."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "ufh_buffer_minutes", int(value)
        )
        self.async_write_ha_state()


# =============================================================================
# Adaptive Preheat Switch (Heating + AC)
# =============================================================================

class TadoAdaptivePreheatSwitch(SwitchEntity):
    """Switch entity for per-zone adaptive preheat."""
    
    _attr_icon = "mdi:home-thermometer"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize adaptive preheat switch."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_adaptive_preheat"
        self._attr_name = "Adaptive Preheat"
        self.entity_id = f"switch.{slug}_adaptive_preheat"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def is_on(self) -> bool:
        """Return if adaptive preheat is enabled."""
        config = self._config_manager.get_zone_config(self._zone_id)
        return config.get("adaptive_preheat", False)
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable adaptive preheat."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "adaptive_preheat", True
        )
        self.async_write_ha_state()
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable adaptive preheat."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "adaptive_preheat", False
        )
        self.async_write_ha_state()


# =============================================================================
# Smart Comfort Mode Select (Heating + AC)
# =============================================================================

class TadoSmartComfortModeSelect(SelectEntity):
    """Select entity for per-zone smart comfort mode."""
    
    _attr_options = SMART_COMFORT_MODE_OPTIONS
    _attr_icon = "mdi:home-thermometer-outline"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize smart comfort mode select."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_smart_comfort_mode"
        self._attr_name = "Smart Comfort"
        self.entity_id = f"select.{slug}_smart_comfort_mode"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def current_option(self) -> str:
        """Return current smart comfort mode."""
        config = self._config_manager.get_zone_config(self._zone_id)
        mode = config.get("smart_comfort_mode", "none")
        # Convert internal value to display name
        return mode.capitalize() if mode != "none" else "None"
    
    async def async_select_option(self, option: str) -> None:
        """Set smart comfort mode."""
        value = option.lower()
        await self._config_manager.async_set_zone_value(
            self._zone_id, "smart_comfort_mode", value
        )
        self.async_write_ha_state()


# =============================================================================
# Window Type Select (Heating + AC)
# =============================================================================

class TadoWindowTypeSelect(SelectEntity):
    """Select entity for per-zone window type.
    
    Used for mold risk (Heating) and condensation risk (AC) calculations.
    """
    
    _attr_options = WINDOW_TYPE_OPTIONS
    _attr_icon = "mdi:window-closed-variant"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize window type select."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_window_type"
        self._attr_name = "Window Type"
        self.entity_id = f"select.{slug}_window_type"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def current_option(self) -> str:
        """Return current window type."""
        config = self._config_manager.get_zone_config(self._zone_id)
        window_type = config.get("window_type", "double_pane")
        return WINDOW_TYPE_REVERSE_MAP.get(window_type, "Double Pane")
    
    async def async_select_option(self, option: str) -> None:
        """Set window type."""
        value = WINDOW_TYPE_MAP.get(option, "double_pane")
        await self._config_manager.async_set_zone_value(
            self._zone_id, "window_type", value
        )
        self.async_write_ha_state()


# =============================================================================
# Overlay Mode Select (Heating + AC)
# =============================================================================

class TadoZoneOverlayModeSelect(SelectEntity):
    """Select entity for per-zone overlay mode.
    
    Controls how long manual temperature changes last.
    """
    
    _attr_options = OVERLAY_MODE_OPTIONS
    _attr_icon = "mdi:timer-cog"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize overlay mode select."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_overlay_mode"
        self._attr_name = "Overlay Mode"
        self.entity_id = f"select.{slug}_overlay_mode"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def current_option(self) -> str:
        """Return current overlay mode."""
        config = self._config_manager.get_zone_config(self._zone_id)
        mode = config.get("overlay_mode", OVERLAY_MODE_DEFAULT)
        return OVERLAY_MODE_REVERSE_MAP.get(mode, OVERLAY_MODE_DEFAULT_DISPLAY)
    
    async def async_select_option(self, option: str) -> None:
        """Set overlay mode."""
        value = OVERLAY_MODE_MAP.get(option, OVERLAY_MODE_DEFAULT)
        await self._config_manager.async_set_zone_value(
            self._zone_id, "overlay_mode", value
        )
        self.async_write_ha_state()


# =============================================================================
# Timer Duration Select (Heating + AC, when overlay_mode=Timer)
# =============================================================================

class TadoTimerDurationSelect(SelectEntity):
    """Select entity for per-zone timer duration.
    
    Only used when overlay_mode = "Timer".
    Options: 15, 30, 45, 60, 90, 120, 180 minutes.
    """
    
    _attr_options = TIMER_DURATION_OPTIONS
    _attr_icon = "mdi:timer"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize timer duration select."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_timer_duration"
        self._attr_name = "Overlay Timer Duration"
        self.entity_id = f"select.{slug}_overlay_timer_duration"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def current_option(self) -> str:
        """Return current timer duration."""
        config = self._config_manager.get_zone_config(self._zone_id)
        duration = config.get("timer_duration", TIMER_DURATION_DEFAULT)
        return str(duration)
    
    async def async_select_option(self, option: str) -> None:
        """Set timer duration."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "timer_duration", int(option)
        )
        self.async_write_ha_state()


# =============================================================================
# Min/Max Temperature Numbers (Heating + AC)
# =============================================================================

class TadoMinTempNumber(NumberEntity):
    """Number entity for per-zone minimum temperature limit."""
    
    _attr_native_min_value = ZONE_MIN_TEMP_MIN
    _attr_native_max_value = ZONE_MIN_TEMP_MAX
    _attr_native_step = ZONE_TEMP_STEP
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:thermometer-low"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize min temp number."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_min_temp"
        self._attr_name = "Min Temp"
        self.entity_id = f"number.{slug}_min_temp"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def native_value(self) -> float:
        """Return current min temp."""
        config = self._config_manager.get_zone_config(self._zone_id)
        return config.get("min_temp", 5.0)
    
    async def async_set_native_value(self, value: float) -> None:
        """Set min temp."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "min_temp", float(value)
        )
        self.async_write_ha_state()


class TadoMaxTempNumber(NumberEntity):
    """Number entity for per-zone maximum temperature limit."""
    
    _attr_native_min_value = ZONE_MAX_TEMP_MIN
    _attr_native_max_value = ZONE_MAX_TEMP_MAX
    _attr_native_step = ZONE_TEMP_STEP
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:thermometer-high"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize max temp number."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_max_temp"
        self._attr_name = "Max Temp"
        self.entity_id = f"number.{slug}_max_temp"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def native_value(self) -> float:
        """Return current max temp."""
        config = self._config_manager.get_zone_config(self._zone_id)
        return config.get("max_temp", 25.0)
    
    async def async_set_native_value(self, value: float) -> None:
        """Set max temp."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "max_temp", float(value)
        )
        self.async_write_ha_state()


# =============================================================================
# Temperature Offset Number (Heating + AC)
# =============================================================================

class TadoTempOffsetNumber(NumberEntity):
    """Number entity for per-zone temperature offset.
    
    Adjusts target temperature for sensor placement or comfort preferences.
    """
    
    _attr_native_min_value = TEMP_OFFSET_MIN
    _attr_native_max_value = TEMP_OFFSET_MAX
    _attr_native_step = TEMP_OFFSET_STEP
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:thermometer-plus"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize temp offset number."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_temp_offset"
        self._attr_name = "Temp Offset"
        self.entity_id = f"number.{slug}_temp_offset"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def native_value(self) -> float:
        """Return current temp offset."""
        config = self._config_manager.get_zone_config(self._zone_id)
        return config.get("temp_offset", 0.0)
    
    async def async_set_native_value(self, value: float) -> None:
        """Set temp offset."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "temp_offset", float(value)
        )
        self.async_write_ha_state()


class TadoSurfaceTempOffsetNumber(NumberEntity):
    """Number entity for per-zone surface temperature offset.
    
    v2.1.0: Allows calibration of mold risk calculation based on
    laser thermometer measurements of actual cold spots.
    
    Negative values = colder surface (more conservative mold risk)
    Positive values = warmer surface (less conservative mold risk)
    """
    
    _attr_native_min_value = SURFACE_TEMP_OFFSET_MIN
    _attr_native_max_value = SURFACE_TEMP_OFFSET_MAX
    _attr_native_step = SURFACE_TEMP_OFFSET_STEP
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:thermometer-water"
    
    def __init__(
        self,
        zone_id: str,
        zone_name: str,
        zone_type: str,
        zone_config_manager: ZoneConfigManager,
    ):
        """Initialize surface temp offset number."""
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._config_manager = zone_config_manager
        
        slug = _slugify(zone_name)
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_surface_temp_offset"
        self._attr_name = "Surface Temp Offset"
        self.entity_id = f"number.{slug}_surface_temp_offset"
        
        self._attr_device_info = _get_zone_device_info(zone_id, zone_name, zone_type)
    
    @property
    def native_value(self) -> float:
        """Return current surface temp offset."""
        config = self._config_manager.get_zone_config(self._zone_id)
        return config.get("surface_temp_offset", 0.0)
    
    async def async_set_native_value(self, value: float) -> None:
        """Set surface temp offset."""
        await self._config_manager.async_set_zone_value(
            self._zone_id, "surface_temp_offset", float(value)
        )
        self.async_write_ha_state()


# =============================================================================
# Platform Setup
# =============================================================================

async def async_setup_zone_config_select(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone configuration select entities."""
    config_manager = hass.data[DOMAIN].get('config_manager')
    zone_config_manager = hass.data[DOMAIN].get('zone_config_manager')
    
    if not zone_config_manager:
        _LOGGER.warning("Zone config manager not available, skipping zone config entities")
        return
    
    # Check if zone configuration is enabled
    if not config_manager.get_zone_configuration_enabled():
        _LOGGER.debug("Zone configuration disabled, skipping zone config entities")
        return
    
    # Load zones info
    from .data_loader import load_zones_info_file
    zones_info = await hass.async_add_executor_job(load_zones_info_file)
    
    if not zones_info:
        _LOGGER.warning("No zones info available, skipping zone config entities")
        return
    
    entities = []
    
    for zone in zones_info:
        zone_id = str(zone.get("id"))
        zone_name = zone.get("name", f"Zone {zone_id}")
        zone_type = zone.get("type")
        
        # v2.1.1: Skip Hot Water zones - they don't need per-zone config (#115)
        if zone_type == "HOT_WATER":
            continue
        
        # Heating-only entities
        if zone_type == "HEATING":
            entities.append(TadoHeatingTypeSelect(zone_id, zone_name, zone_config_manager))
        
        # Heating + AC entities
        entities.extend([
            TadoSmartComfortModeSelect(zone_id, zone_name, zone_type, zone_config_manager),
            TadoWindowTypeSelect(zone_id, zone_name, zone_type, zone_config_manager),
            TadoZoneOverlayModeSelect(zone_id, zone_name, zone_type, zone_config_manager),
            TadoTimerDurationSelect(zone_id, zone_name, zone_type, zone_config_manager),
        ])
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} zone config select entities")


async def async_setup_zone_config_number(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone configuration number entities."""
    config_manager = hass.data[DOMAIN].get('config_manager')
    zone_config_manager = hass.data[DOMAIN].get('zone_config_manager')
    
    if not zone_config_manager:
        _LOGGER.warning("Zone config manager not available, skipping zone config entities")
        return
    
    # Check if zone configuration is enabled
    if not config_manager.get_zone_configuration_enabled():
        _LOGGER.debug("Zone configuration disabled, skipping zone config entities")
        return
    
    # Load zones info
    from .data_loader import load_zones_info_file
    zones_info = await hass.async_add_executor_job(load_zones_info_file)
    
    if not zones_info:
        _LOGGER.warning("No zones info available, skipping zone config entities")
        return
    
    entities = []
    
    for zone in zones_info:
        zone_id = str(zone.get("id"))
        zone_name = zone.get("name", f"Zone {zone_id}")
        zone_type = zone.get("type")
        
        # v2.1.1: Skip Hot Water zones - they don't need per-zone config (#115)
        if zone_type == "HOT_WATER":
            continue
        
        # Heating-only entities
        if zone_type == "HEATING":
            entities.append(TadoUFHBufferNumber(zone_id, zone_name, zone_config_manager))
        
        # Heating + AC entities
        entities.extend([
            TadoMinTempNumber(zone_id, zone_name, zone_type, zone_config_manager),
            TadoMaxTempNumber(zone_id, zone_name, zone_type, zone_config_manager),
            TadoTempOffsetNumber(zone_id, zone_name, zone_type, zone_config_manager),
            TadoSurfaceTempOffsetNumber(zone_id, zone_name, zone_type, zone_config_manager),
        ])
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} zone config number entities")


async def async_setup_zone_config_switch(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone configuration switch entities."""
    config_manager = hass.data[DOMAIN].get('config_manager')
    zone_config_manager = hass.data[DOMAIN].get('zone_config_manager')
    
    if not zone_config_manager:
        _LOGGER.warning("Zone config manager not available, skipping zone config entities")
        return
    
    # Check if zone configuration is enabled
    if not config_manager.get_zone_configuration_enabled():
        _LOGGER.debug("Zone configuration disabled, skipping zone config entities")
        return
    
    # Load zones info
    from .data_loader import load_zones_info_file
    zones_info = await hass.async_add_executor_job(load_zones_info_file)
    
    if not zones_info:
        _LOGGER.warning("No zones info available, skipping zone config entities")
        return
    
    entities = []
    
    for zone in zones_info:
        zone_id = str(zone.get("id"))
        zone_name = zone.get("name", f"Zone {zone_id}")
        zone_type = zone.get("type")
        
        # v2.1.1: Skip Hot Water zones - they don't need per-zone config (#115)
        if zone_type == "HOT_WATER":
            continue
        
        # Heating + AC entities
        entities.append(
            TadoAdaptivePreheatSwitch(zone_id, zone_name, zone_type, zone_config_manager)
        )
    
    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} zone config switch entities")
