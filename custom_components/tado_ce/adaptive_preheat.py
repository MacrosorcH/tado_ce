"""Adaptive Preheat Manager for Tado CE.

v2.0.0: Automatically triggers heating when preheat_now binary sensor turns ON.
Replaces Tado's cloud-based Early Start with local, user-controlled automation.

Features:
- Monitors preheat_now binary sensors for enabled zones
- Automatically sets heating overlay when preheat time is reached
- Clears overlay when target temperature is reached or schedule starts
- Tracks which overlays were set by this manager (won't clear user-set overlays)
"""
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event

if TYPE_CHECKING:
    from .config_manager import ConfigurationManager

_LOGGER = logging.getLogger(__name__)


class AdaptivePreheatManager:
    """Manages adaptive preheat automation for heating zones."""
    
    def __init__(self, hass: HomeAssistant, config_manager: "ConfigurationManager"):
        """Initialize the Adaptive Preheat Manager.
        
        Args:
            hass: Home Assistant instance
            config_manager: Configuration manager with settings
        """
        self._hass = hass
        self._config_manager = config_manager
        self._enabled = False
        self._enabled_zones: list[str] = []  # Zone IDs enabled for adaptive preheat
        self._active_overlays: dict[str, dict] = {}  # zone_id -> overlay info
        self._state_listeners: list = []  # Track state change listeners
        self._zone_info: dict[str, dict] = {}  # zone_id -> {name, entity_id}
    
    async def async_setup(self) -> None:
        """Set up the Adaptive Preheat Manager.
        
        Called during integration setup. Loads zone info and starts monitoring
        if adaptive preheat is enabled.
        """
        # Check if adaptive preheat is enabled
        self._enabled = self._config_manager.get_adaptive_preheat_enabled()
        if not self._enabled:
            _LOGGER.debug("Adaptive Preheat: Disabled in config")
            return
        
        # Check if Smart Comfort is enabled (required for preheat_now sensors)
        if not self._config_manager.get_smart_comfort_enabled():
            _LOGGER.warning(
                "Adaptive Preheat: Requires Smart Comfort to be enabled. "
                "Please enable Smart Comfort in integration options."
            )
            self._enabled = False
            return
        
        # Load zone info
        from .data_loader import load_zones_info_file
        zones_info = await self._hass.async_add_executor_job(load_zones_info_file)
        
        if not zones_info:
            _LOGGER.warning("Adaptive Preheat: No zones found")
            return
        
        # Get configured zones (empty = all heating zones)
        configured_zones = self._config_manager.get_adaptive_preheat_zones()
        
        # Build zone info mapping
        for zone in zones_info:
            if zone.get('type') != 'HEATING':
                continue
            
            zone_id = str(zone.get('id'))
            zone_name = zone.get('name', f"Zone {zone_id}")
            
            # Check if this zone is enabled
            if configured_zones and zone_id not in configured_zones:
                continue
            
            # Build entity IDs
            zone_slug = zone_name.lower().replace(' ', '_')
            self._zone_info[zone_id] = {
                'name': zone_name,
                'slug': zone_slug,
                'preheat_now_entity': f"binary_sensor.{zone_slug}_preheat_now",
                'preheat_advisor_entity': f"sensor.{zone_slug}_preheat_advisor",
                'climate_entity': f"climate.{zone_slug}",
            }
            self._enabled_zones.append(zone_id)
        
        if not self._enabled_zones:
            _LOGGER.info("Adaptive Preheat: No zones configured")
            return
        
        _LOGGER.info(
            f"Adaptive Preheat: Enabled for {len(self._enabled_zones)} zones: "
            f"{[self._zone_info[z]['name'] for z in self._enabled_zones]}"
        )
        
        # Start monitoring preheat_now sensors
        await self._start_monitoring()
    
    async def _start_monitoring(self) -> None:
        """Start monitoring preheat_now binary sensors."""
        # Build list of entities to monitor
        entities_to_monitor = [
            self._zone_info[zone_id]['preheat_now_entity']
            for zone_id in self._enabled_zones
        ]
        
        # Register state change listener
        @callback
        def _state_change_handler(event: Event) -> None:
            """Handle state changes for preheat_now sensors."""
            entity_id = event.data.get('entity_id')
            new_state = event.data.get('new_state')
            old_state = event.data.get('old_state')
            
            if not new_state:
                return
            
            # Find zone_id for this entity
            zone_id = None
            for zid, info in self._zone_info.items():
                if info['preheat_now_entity'] == entity_id:
                    zone_id = zid
                    break
            
            if not zone_id:
                return
            
            # Check state transition
            old_is_on = old_state and old_state.state == 'on'
            new_is_on = new_state.state == 'on'
            
            if new_is_on and not old_is_on:
                # Preheat time reached - trigger heating
                self._hass.async_create_task(
                    self._trigger_preheat(zone_id)
                )
            elif not new_is_on and old_is_on:
                # Preheat ended - check if we should clear overlay
                self._hass.async_create_task(
                    self._check_clear_overlay(zone_id)
                )
        
        # Register listener
        cancel = async_track_state_change_event(
            self._hass,
            entities_to_monitor,
            _state_change_handler
        )
        self._state_listeners.append(cancel)
        
        _LOGGER.debug(f"Adaptive Preheat: Monitoring {len(entities_to_monitor)} sensors")
        
        # Check current state of all sensors (in case they're already ON)
        for zone_id in self._enabled_zones:
            entity_id = self._zone_info[zone_id]['preheat_now_entity']
            state = self._hass.states.get(entity_id)
            if state and state.state == 'on':
                _LOGGER.info(
                    f"Adaptive Preheat: {self._zone_info[zone_id]['name']} "
                    f"preheat_now already ON, triggering preheat"
                )
                await self._trigger_preheat(zone_id)
    
    async def _trigger_preheat(self, zone_id: str) -> None:
        """Trigger heating for a zone.
        
        Sets a heating overlay with the target temperature from the next schedule.
        Uses NEXT_TIME_BLOCK termination so it auto-clears when schedule starts.
        
        Args:
            zone_id: Zone ID to trigger heating for
        """
        zone_info = self._zone_info.get(zone_id)
        if not zone_info:
            return
        
        zone_name = zone_info['name']
        
        # Check if we already have an active overlay for this zone
        if zone_id in self._active_overlays:
            _LOGGER.debug(f"Adaptive Preheat: {zone_name} already has active overlay")
            return
        
        # Get target temperature from preheat advisor
        preheat_advisor_id = zone_info['preheat_advisor_entity']
        preheat_state = self._hass.states.get(preheat_advisor_id)
        
        if not preheat_state:
            _LOGGER.warning(f"Adaptive Preheat: {zone_name} preheat advisor not found")
            return
        
        target_temp = preheat_state.attributes.get('target_temperature')
        if not target_temp:
            _LOGGER.warning(f"Adaptive Preheat: {zone_name} no target temperature")
            return
        
        try:
            target_temp = float(target_temp)
        except (ValueError, TypeError):
            _LOGGER.warning(f"Adaptive Preheat: {zone_name} invalid target temp: {target_temp}")
            return
        
        # Check current temperature - don't trigger if already at target
        climate_entity_id = zone_info['climate_entity']
        climate_state = self._hass.states.get(climate_entity_id)
        
        if climate_state:
            current_temp = climate_state.attributes.get('current_temperature')
            if current_temp and float(current_temp) >= target_temp - 0.5:
                _LOGGER.info(
                    f"Adaptive Preheat: {zone_name} already at target "
                    f"({current_temp}°C >= {target_temp}°C), skipping"
                )
                return
        
        # Set heating overlay via API
        _LOGGER.info(
            f"Adaptive Preheat: Triggering {zone_name} to {target_temp}°C "
            f"(NEXT_TIME_BLOCK termination)"
        )
        
        try:
            from .async_api import get_async_client
            client = get_async_client(self._hass)
            
            setting = {
                "type": "HEATING",
                "power": "ON",
                "temperature": {"celsius": target_temp}
            }
            termination = {"type": "NEXT_TIME_BLOCK"}
            
            success = await client.set_zone_overlay(zone_id, setting, termination)
            
            if success:
                self._active_overlays[zone_id] = {
                    'target_temp': target_temp,
                    'triggered_at': datetime.now(),
                    'termination': 'NEXT_TIME_BLOCK'
                }
                _LOGGER.info(f"Adaptive Preheat: {zone_name} overlay set successfully")
            else:
                _LOGGER.warning(f"Adaptive Preheat: {zone_name} failed to set overlay")
                
        except Exception as e:
            _LOGGER.error(f"Adaptive Preheat: {zone_name} error setting overlay: {e}")
    
    async def _check_clear_overlay(self, zone_id: str) -> None:
        """Check if we should clear the overlay for a zone.
        
        Only clears overlays that were set by this manager.
        Called when preheat_now turns OFF.
        
        Args:
            zone_id: Zone ID to check
        """
        zone_info = self._zone_info.get(zone_id)
        if not zone_info:
            return
        
        zone_name = zone_info['name']
        
        # Check if we have an active overlay for this zone
        if zone_id not in self._active_overlays:
            _LOGGER.debug(f"Adaptive Preheat: {zone_name} no active overlay to clear")
            return
        
        # The overlay should auto-clear with NEXT_TIME_BLOCK termination
        # Just remove from our tracking
        del self._active_overlays[zone_id]
        _LOGGER.info(
            f"Adaptive Preheat: {zone_name} preheat ended, "
            f"overlay will auto-clear at schedule start"
        )
    
    async def async_unload(self) -> None:
        """Unload the Adaptive Preheat Manager.
        
        Called during integration unload. Cancels all listeners.
        """
        for cancel in self._state_listeners:
            cancel()
        self._state_listeners.clear()
        
        _LOGGER.debug("Adaptive Preheat: Unloaded")


# Singleton instance
_manager: AdaptivePreheatManager | None = None


def get_adaptive_preheat_manager(
    hass: HomeAssistant | None = None,
    config_manager: "ConfigurationManager | None" = None
) -> AdaptivePreheatManager | None:
    """Get or create the Adaptive Preheat Manager singleton.
    
    Args:
        hass: Home Assistant instance (required for creation)
        config_manager: Configuration manager (required for creation)
        
    Returns:
        AdaptivePreheatManager instance, or None if not created yet
    """
    global _manager
    
    if _manager is None and hass is not None and config_manager is not None:
        _manager = AdaptivePreheatManager(hass, config_manager)
    
    return _manager


async def async_setup_adaptive_preheat(
    hass: HomeAssistant,
    config_manager: "ConfigurationManager"
) -> None:
    """Set up Adaptive Preheat Manager.
    
    Called from __init__.py during integration setup.
    
    Args:
        hass: Home Assistant instance
        config_manager: Configuration manager
    """
    manager = get_adaptive_preheat_manager(hass, config_manager)
    if manager:
        await manager.async_setup()


async def async_unload_adaptive_preheat() -> None:
    """Unload Adaptive Preheat Manager.
    
    Called from __init__.py during integration unload.
    """
    global _manager
    
    if _manager:
        await _manager.async_unload()
        _manager = None
