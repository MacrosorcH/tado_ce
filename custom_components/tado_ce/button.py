"""Tado CE Button Platform."""
import asyncio
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .device_manager import get_zone_device_info, get_hub_device_info
from .config_manager import ConfigurationManager
from .data_loader import load_zones_info_file

_LOGGER = logging.getLogger(__name__)

# Default timer preset durations (in minutes)
DEFAULT_TIMER_PRESETS = [30, 60, 90]


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up Tado CE buttons from a config entry."""
    _LOGGER.debug("Tado CE button: Setting up...")
    zones_info = await hass.async_add_executor_job(load_zones_info_file)
    
    # Get config manager to check if schedule calendar is enabled
    config_manager = hass.data.get(DOMAIN, {}).get('config_manager')
    schedule_calendar_enabled = config_manager.get_schedule_calendar_enabled() if config_manager else False
    
    buttons = []
    
    # Add Resume All Schedules button (hub-level)
    buttons.append(TadoResumeAllSchedulesButton(hass))
    
    # Add Refresh AC Capabilities button (hub-level) - only if there are AC zones
    has_ac_zones = any(z.get('type') == 'AIR_CONDITIONING' for z in (zones_info or []))
    if has_ac_zones:
        buttons.append(TadoRefreshACCapabilitiesButton(hass))
    
    if zones_info:
        for zone in zones_info:
            zone_id = str(zone.get('id'))
            zone_name = zone.get('name', f"Zone {zone_id}")
            zone_type = zone.get('type')
            
            # Create timer preset buttons for hot water zones
            if zone_type == 'HOT_WATER':
                for duration in DEFAULT_TIMER_PRESETS:
                    buttons.append(
                        TadoWaterHeaterTimerButton(hass, zone_id, zone_name, duration)
                    )
            
            # Create boost buttons for heating zones
            if zone_type == 'HEATING':
                # Boost button (official Tado-style: max temp for 30 min)
                buttons.append(
                    TadoBoostButton(hass, zone_id, zone_name)
                )
                # Smart Boost button (calculated duration based on heating rate)
                buttons.append(
                    TadoSmartBoostButton(hass, zone_id, zone_name)
                )
            
            # Create refresh schedule button for heating zones (only if calendar enabled)
            if zone_type == 'HEATING' and schedule_calendar_enabled:
                buttons.append(
                    TadoRefreshScheduleButton(hass, zone_id, zone_name)
                )
    
    if buttons:
        async_add_entities(buttons, True)
        _LOGGER.info(f"Tado CE buttons loaded: {len(buttons)}")
    else:
        _LOGGER.info("Tado CE: No buttons to create")


class TadoResumeAllSchedulesButton(ButtonEntity):
    """Button to resume schedules for all zones (delete all overlays)."""
    
    def __init__(self, hass: HomeAssistant):
        """Initialize the button."""
        self.hass = hass
        
        self._attr_name = "Resume All Schedules"
        self._attr_unique_id = "tado_ce_resume_all_schedules"
        self._attr_device_info = get_hub_device_info()
        self._attr_icon = "mdi:calendar-refresh"
    
    async def async_press(self) -> None:
        """Handle button press - resume schedules for all zones."""
        from .async_api import get_async_client
        from .data_loader import load_zones_info_file
        from .immediate_refresh_handler import get_handler
        
        _LOGGER.info("Resume All Schedules button pressed")
        
        client = get_async_client(self.hass)
        zones_info = await self.hass.async_add_executor_job(load_zones_info_file)
        
        if not zones_info:
            _LOGGER.warning("No zones found to resume schedules")
            return
        
        success_count = 0
        fail_count = 0
        
        for zone in zones_info:
            zone_id = str(zone.get('id'))
            zone_name = zone.get('name', f"Zone {zone_id}")
            
            try:
                if await client.delete_zone_overlay(zone_id):
                    _LOGGER.debug(f"Resumed schedule for {zone_name} (zone {zone_id})")
                    success_count += 1
                else:
                    # API returned False - might mean no overlay existed
                    _LOGGER.debug(f"No overlay to delete for {zone_name} (zone {zone_id})")
                    success_count += 1  # Still count as success
            except Exception as e:
                _LOGGER.error(f"Failed to resume schedule for {zone_name}: {e}")
                fail_count += 1
        
        if fail_count == 0:
            _LOGGER.info(f"Resume All Schedules complete: {success_count} zones processed")
        else:
            _LOGGER.warning(f"Resume All Schedules: {success_count} succeeded, {fail_count} failed")
        
        # Trigger immediate refresh to update all entities
        try:
            handler = get_handler(self.hass)
            await handler.trigger_refresh(self.entity_id, "resume_all_schedules", force=True, skip_debounce=True)
        except Exception as e:
            _LOGGER.warning(f"Failed to trigger immediate refresh: {e}")


class TadoRefreshACCapabilitiesButton(ButtonEntity):
    """Button to refresh AC capabilities cache."""
    
    def __init__(self, hass: HomeAssistant):
        """Initialize the button."""
        self.hass = hass
        
        self._attr_name = "Refresh AC Capabilities"
        self._attr_unique_id = "tado_ce_refresh_ac_capabilities"
        self._attr_device_info = get_hub_device_info()
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:air-conditioner"
    
    async def async_press(self) -> None:
        """Handle button press - refresh AC capabilities from API."""
        from .async_api import get_async_client
        from .const import AC_CAPABILITIES_FILE
        
        _LOGGER.info("Refresh AC Capabilities button pressed")
        
        # Delete existing cache to force re-fetch
        def _delete_cache():
            if AC_CAPABILITIES_FILE.exists():
                AC_CAPABILITIES_FILE.unlink()
                _LOGGER.debug("Deleted AC capabilities cache")
        
        await self.hass.async_add_executor_job(_delete_cache)
        
        # Fetch fresh capabilities
        client = get_async_client(self.hass)
        zones_info = await self.hass.async_add_executor_job(load_zones_info_file)
        
        if not zones_info:
            _LOGGER.warning("No zones found")
            return
        
        # Call the sync method to re-fetch AC capabilities
        try:
            await client._sync_ac_capabilities(zones_info)
            _LOGGER.info("AC capabilities refreshed successfully")
        except Exception as e:
            _LOGGER.error(f"Failed to refresh AC capabilities: {e}")


class TadoWaterHeaterTimerButton(ButtonEntity):
    """Button to set water heater timer with preset duration."""
    
    def __init__(self, hass: HomeAssistant, zone_id: str, zone_name: str, duration: int):
        """Initialize the button.
        
        Args:
            hass: Home Assistant instance
            zone_id: Zone ID
            zone_name: Zone name
            duration: Timer duration in minutes
        """
        self.hass = hass
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._duration = duration
        
        self._attr_name = f"{zone_name} {duration}min Timer"
        self._attr_unique_id = f"tado_ce_{zone_name.lower().replace(' ', '_')}_timer_{duration}min"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HOT_WATER")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:timer"
    
    async def async_press(self) -> None:
        """Handle button press - set water heater timer with preset duration."""
        from homeassistant.exceptions import HomeAssistantError
        from homeassistant.helpers import entity_registry as er
        
        _LOGGER.info(f"Timer button pressed - {self._zone_name} for {self._duration} minutes")
        
        # Find water heater entity by unique_id (more reliable than constructing from name)
        # This handles cases where HA adds suffix like _2 due to entity_id conflicts
        registry = er.async_get(self.hass)
        unique_id = f"tado_ce_zone_{self._zone_id}_water_heater"
        entry = registry.async_get_entity_id("water_heater", DOMAIN, unique_id)
        
        if entry:
            water_heater_entity_id = entry
        else:
            # Fallback to name-based construction for backwards compatibility
            water_heater_entity_id = f"water_heater.{self._zone_name.lower().replace(' ', '_')}"
        
        # Verify entity exists before calling service
        if not self.hass.states.get(water_heater_entity_id):
            error_msg = f"Water heater entity not found: {water_heater_entity_id}"
            _LOGGER.error(f"Timer button failed - {error_msg}")
            raise HomeAssistantError(error_msg)
        
        # Convert duration (minutes) to HH:MM:SS format
        hours = self._duration // 60
        minutes = self._duration % 60
        time_period = f"{hours:02d}:{minutes:02d}:00"
        
        _LOGGER.info(f"Calling set_water_heater_timer for {water_heater_entity_id} with {time_period}")
        
        try:
            # Call the set_water_heater_timer service
            await self.hass.services.async_call(
                "tado_ce",
                "set_water_heater_timer",
                {
                    "entity_id": water_heater_entity_id,
                    "time_period": time_period,
                },
                blocking=True,
            )
            
            _LOGGER.info(f"Timer set successfully - {self._zone_name} for {self._duration} minutes")
            
        except HomeAssistantError:
            # Re-raise HomeAssistantError as-is (already has good error message)
            raise
        except Exception as e:
            # Catch any other unexpected errors and provide detailed message
            error_type = type(e).__name__
            error_msg = f"Failed to set {self._duration}min timer for {self._zone_name}: {error_type}: {str(e)}"
            _LOGGER.error(f"Timer button failed - {error_msg}")
            raise HomeAssistantError(error_msg) from e


class TadoRefreshScheduleButton(ButtonEntity):
    """Button to refresh schedule for a specific zone."""
    
    def __init__(self, hass: HomeAssistant, zone_id: str, zone_name: str):
        """Initialize the button.
        
        Args:
            hass: Home Assistant instance
            zone_id: Zone ID
            zone_name: Zone name
        """
        self.hass = hass
        self._zone_id = zone_id
        self._zone_name = zone_name
        
        self._attr_name = f"{zone_name} Refresh Schedule"
        self._attr_unique_id = f"tado_ce_{zone_id}_refresh_schedule"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING")
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:calendar-refresh"
    
    async def async_press(self) -> None:
        """Handle button press - refresh schedule for this zone."""
        from .async_api import get_async_client
        from .calendar import _get_schedules_file
        from .const import DATA_DIR
        import json
        
        _LOGGER.info(f"Refresh Schedule button pressed for {self._zone_name} (zone {self._zone_id})")
        
        client = get_async_client(self.hass)
        
        try:
            # Fetch fresh schedule from API
            schedule_data = await client.get_zone_schedule(self._zone_id)
            
            if not schedule_data:
                _LOGGER.warning(f"No schedule data returned for {self._zone_name}")
                return
            
            # Get per-home schedules file path
            schedules_file = _get_schedules_file()
            
            # Load existing schedules
            def _load_schedules():
                if schedules_file.exists():
                    with open(schedules_file) as f:
                        return json.load(f)
                return {}
            
            schedules = await self.hass.async_add_executor_job(_load_schedules)
            
            # Update this zone's schedule
            schedules[self._zone_id] = {
                "name": self._zone_name,
                "type": schedule_data.get("type", "ONE_DAY"),
                "blocks": schedule_data.get("blocks", {}),
            }
            
            # Save back to file using atomic write
            def _save_schedules():
                import tempfile
                import shutil
                
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                # Atomic write: write to temp file then move
                with tempfile.NamedTemporaryFile(
                    mode='w', dir=DATA_DIR, delete=False, suffix='.tmp'
                ) as tmp:
                    json.dump(schedules, tmp, indent=2)
                    temp_path = tmp.name
                shutil.move(temp_path, schedules_file)
            
            await self.hass.async_add_executor_job(_save_schedules)
            
            _LOGGER.info(f"Schedule refreshed for {self._zone_name}")
            
            # Fire event to notify calendar entity to update
            self.hass.bus.async_fire(
                f"{DOMAIN}_schedule_updated",
                {"zone_id": self._zone_id, "zone_name": self._zone_name}
            )
            
        except Exception as e:
            _LOGGER.error(f"Failed to refresh schedule for {self._zone_name}: {e}")


# Boost button constants
BOOST_TEMPERATURE = 25.0  # Maximum temperature for boost
BOOST_DURATION_MINUTES = 30  # Default boost duration

# Smart Boost constants
SMART_BOOST_MIN_DURATION = 15  # Minimum duration in minutes
SMART_BOOST_MAX_DURATION = 180  # Maximum duration in minutes (3 hours)
SMART_BOOST_DEFAULT_RATE = 1.0  # Default heating rate if unknown (°C/h)


class TadoBoostButton(ButtonEntity):
    """Button to boost heating to maximum temperature for 30 minutes.
    
    Mimics official Tado app boost functionality:
    - Sets zone to maximum temperature (25°C)
    - Timer for 30 minutes
    - Automatically resumes schedule after timer expires
    """
    
    def __init__(self, hass: HomeAssistant, zone_id: str, zone_name: str):
        """Initialize the button."""
        self.hass = hass
        self._zone_id = zone_id
        self._zone_name = zone_name
        
        self._attr_name = f"{zone_name} Boost"
        self._attr_unique_id = f"tado_ce_{zone_id}_boost"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING")
        self._attr_icon = "mdi:fire"
    
    async def async_press(self) -> None:
        """Handle button press - boost heating to max for 30 minutes."""
        from .async_api import get_async_client
        from .immediate_refresh_handler import get_handler
        
        _LOGGER.info(f"Boost button pressed for {self._zone_name}")
        
        client = get_async_client(self.hass)
        
        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": BOOST_TEMPERATURE}
        }
        termination = {
            "type": "TIMER",
            "durationInSeconds": BOOST_DURATION_MINUTES * 60
        }
        
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Boost TIMEOUT: {self._zone_name} API call timed out")
        except Exception as e:
            _LOGGER.error(f"Boost ERROR: {self._zone_name} API call failed ({e})")
        
        if api_success:
            _LOGGER.info(f"Boost activated: {self._zone_name} set to {BOOST_TEMPERATURE}°C for {BOOST_DURATION_MINUTES} minutes")
            # Trigger immediate refresh
            try:
                handler = get_handler(self.hass)
                await handler.trigger_refresh(self.entity_id, "boost_activated")
            except Exception as e:
                _LOGGER.warning(f"Failed to trigger immediate refresh: {e}")
        else:
            _LOGGER.error(f"Boost failed for {self._zone_name}")


class TadoSmartBoostButton(ButtonEntity):
    """Button to smart boost heating with calculated duration.
    
    Uses heating rate sensor to calculate optimal boost duration:
    - Target: Schedule's next target temperature (or current + 3°C if unavailable)
    - Duration: (target - current) / heating_rate
    - Capped between 15 minutes and 3 hours
    """
    
    def __init__(self, hass: HomeAssistant, zone_id: str, zone_name: str):
        """Initialize the button."""
        self.hass = hass
        self._zone_id = zone_id
        self._zone_name = zone_name
        
        self._attr_name = f"{zone_name} Smart Boost"
        self._attr_unique_id = f"tado_ce_{zone_id}_smart_boost"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING")
        self._attr_icon = "mdi:fire-alert"
    
    def _get_climate_entity_id(self) -> str | None:
        """Get the climate entity ID for this zone.
        
        Uses entity registry lookup for reliability, with name-based fallback.
        This handles cases where HA adds suffix (e.g., _2) due to entity_id conflicts.
        
        Returns:
            Climate entity ID, or None if not found
        """
        from homeassistant.helpers import entity_registry as er
        
        # Strategy 1: Entity registry lookup by unique_id (most reliable)
        registry = er.async_get(self.hass)
        unique_id = f"tado_ce_zone_{self._zone_id}_climate"
        entry = registry.async_get_entity_id("climate", DOMAIN, unique_id)
        
        if entry:
            return entry
        
        # Strategy 2: Fallback to name-based construction for backwards compatibility
        return f"climate.{self._zone_name.lower().replace(' ', '_')}"
    
    def _get_heating_rate(self) -> float:
        """Get heating rate with fallback chain.
        
        Priority:
        1. HeatingCycleCoordinator (°C/min → convert to °C/h)
        2. SmartComfortManager (°C/h)
        3. Default rate
        
        Returns:
            Heating rate in °C/h
        """
        from .const import DOMAIN
        
        # Strategy 1: HeatingCycleCoordinator (most accurate)
        heating_cycle_coordinator = self.hass.data.get(DOMAIN, {}).get('heating_cycle_coordinator')
        if heating_cycle_coordinator:
            zone_data = heating_cycle_coordinator.get_zone_data(self._zone_id)
            if zone_data and zone_data.get("heating_rate") is not None:
                # HeatingCycleCoordinator rate is in °C/min, convert to °C/h
                rate = zone_data.get("heating_rate") * 60
                if rate > 0.1:
                    _LOGGER.debug(f"Smart Boost: Using HeatingCycleCoordinator rate {rate:.2f}°C/h")
                    return rate
        
        # Strategy 2: SmartComfortManager
        smart_comfort_manager = self.hass.data.get(DOMAIN, {}).get('smart_comfort_manager')
        if smart_comfort_manager:
            rate = smart_comfort_manager.get_heating_rate(self._zone_id)
            if rate is not None and rate > 0.1:
                _LOGGER.debug(f"Smart Boost: Using SmartComfort rate {rate:.2f}°C/h")
                return rate
        
        # Strategy 3: Default
        _LOGGER.debug(f"Smart Boost: Using default rate {SMART_BOOST_DEFAULT_RATE}°C/h")
        return SMART_BOOST_DEFAULT_RATE
    
    async def async_press(self) -> None:
        """Handle button press - smart boost with calculated duration."""
        from .async_api import get_async_client
        from .immediate_refresh_handler import get_handler
        
        _LOGGER.info(f"Smart Boost button pressed for {self._zone_name}")
        
        # Get current temperature from climate entity
        climate_entity_id = self._get_climate_entity_id()
        climate_state = self.hass.states.get(climate_entity_id)
        
        if not climate_state:
            _LOGGER.error(f"Smart Boost: Climate entity not found: {climate_entity_id}")
            return
        
        current_temp = climate_state.attributes.get('current_temperature')
        if current_temp is None:
            _LOGGER.error(f"Smart Boost: No current temperature for {self._zone_name}")
            return
        
        # Get target temperature (schedule target or current + 3°C)
        target_temp = climate_state.attributes.get('temperature')
        if target_temp is None or target_temp <= current_temp:
            # No schedule target or already at/above target, use current + 3°C
            target_temp = min(current_temp + 3.0, 25.0)
            _LOGGER.debug(f"Smart Boost: Using default target {target_temp}°C (current + 3)")
        
        # Get heating rate using fallback chain
        heating_rate = self._get_heating_rate()
        
        # Calculate duration: (target - current) / rate * 60 minutes
        temp_diff = target_temp - current_temp
        if temp_diff <= 0:
            _LOGGER.info(f"Smart Boost: Already at or above target ({current_temp}°C >= {target_temp}°C)")
            return
        
        duration_hours = temp_diff / heating_rate
        duration_minutes = int(duration_hours * 60)
        
        # Apply caps
        duration_minutes = max(SMART_BOOST_MIN_DURATION, min(duration_minutes, SMART_BOOST_MAX_DURATION))
        
        _LOGGER.info(
            f"Smart Boost calculation: {current_temp}°C → {target_temp}°C, "
            f"rate={heating_rate}°C/h, duration={duration_minutes}min"
        )
        
        # Set the overlay
        client = get_async_client(self.hass)
        
        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": target_temp}
        }
        termination = {
            "type": "TIMER",
            "durationInSeconds": duration_minutes * 60
        }
        
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Smart Boost TIMEOUT: {self._zone_name} API call timed out")
        except Exception as e:
            _LOGGER.error(f"Smart Boost ERROR: {self._zone_name} API call failed ({e})")
        
        if api_success:
            _LOGGER.info(
                f"Smart Boost activated: {self._zone_name} set to {target_temp}°C "
                f"for {duration_minutes} minutes (rate: {heating_rate}°C/h)"
            )
            # Trigger immediate refresh
            try:
                handler = get_handler(self.hass)
                await handler.trigger_refresh(self.entity_id, "smart_boost_activated")
            except Exception as e:
                _LOGGER.warning(f"Failed to trigger immediate refresh: {e}")
        else:
            _LOGGER.error(f"Smart Boost failed for {self._zone_name}")
