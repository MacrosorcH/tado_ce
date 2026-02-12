"""Tado CE Select Platform (Presence Mode).

v2.0.2: New select entity for presence mode control.
Discussion #102 (@wyx087) - Adds "Auto" option to resume geofencing.
"""
import logging
import time
from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .device_manager import get_hub_device_info

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up Tado CE select entities from a config entry."""
    _LOGGER.debug("Tado CE select: Setting up...")
    
    entities = []
    
    # Add Presence Mode select (global, 1 API call per change)
    entities.append(TadoPresenceModeSelect())
    
    if entities:
        async_add_entities(entities, True)
        _LOGGER.info(f"Tado CE select entities loaded: {len(entities)}")


class TadoPresenceModeSelect(SelectEntity):
    """Tado CE Presence Mode Select Entity.
    
    Allows control of presence mode: auto (geofencing), home, away.
    Replaces the old switch.tado_ce_away_mode (v2.0.2 breaking change).
    
    v2.0.2: Full 3-layer defense (lesson from v2.0.1 hot water fix)
    - Layer 1: _optimistic_set_at freshness tracking
    - Layer 2: Sequence numbers via get_next_sequence()
    - Layer 3: Expected state confirmation
    
    Uses 1 API call per change.
    """
    
    _attr_options = ["Auto", "Home", "Away"]
    _attr_translation_key = "presence_mode"
    _attr_has_entity_name = True
    
    def __init__(self):
        self._attr_unique_id = "tado_ce_presence_mode"
        self._attr_current_option = "Auto"
        self._attr_available = True
        self._attr_device_info = get_hub_device_info()
        
        # State tracking
        self._presence = "HOME"
        self._presence_locked = False
        
        # v2.0.2: 3-layer defense (parity with climate/water_heater)
        self._optimistic_set_at: float | None = None
        self._optimistic_sequence: int | None = None
        self._expected_mode: str | None = None

    # ========== v2.0.2: Helper Methods ==========
    
    def _is_within_optimistic_window(self) -> bool:
        """Check if we're within the optimistic update window.
        
        v2.0.2: Extracted to helper method for consistency with other entities.
        Uses shared get_optimistic_window() for DRY.
        
        Returns:
            True if _optimistic_set_at is set and elapsed time < optimistic window.
        """
        if self._optimistic_set_at is None:
            return False
        from . import get_optimistic_window
        elapsed = time.time() - self._optimistic_set_at
        return elapsed < get_optimistic_window(self.hass) if self.hass else elapsed < 17.0
    
    def _clear_optimistic_state(self):
        """Clear all optimistic state tracking."""
        self._optimistic_set_at = None
        self._optimistic_sequence = None
        self._expected_mode = None
    
    # ========== End Helper Methods ==========
    
    @property
    def icon(self):
        """Return icon based on current mode."""
        if self._attr_current_option == "Auto":
            return "mdi:home-account"
        elif self._attr_current_option == "Home":
            return "mdi:home"
        else:  # Away
            return "mdi:home-export-outline"
    
    @property
    def extra_state_attributes(self):
        return {
            "presence": self._presence,
            "presence_locked": self._presence_locked,
            "api_calls_per_change": 1,
        }
    
    def update(self):
        """Update state from home_state.json.
        
        v2.0.2: 3-layer defense - preserve optimistic state if within window
        or if API hasn't confirmed expected state yet.
        """
        # Layer 1: Skip if within optimistic window
        if self._is_within_optimistic_window():
            _LOGGER.debug("Presence Mode: Preserving optimistic state (within window)")
            return
        
        # Window expired, clear optimistic tracking
        if self._optimistic_set_at is not None:
            self._optimistic_set_at = None
        
        # Load from file
        try:
            from .data_loader import load_home_state_file
            home_state = load_home_state_file()
            if not home_state:
                return
            
            api_presence = home_state.get('presence', 'HOME')
            api_locked = home_state.get('presenceLocked', False)
            
            # Layer 3: Check if API confirmed expected state
            if self._optimistic_sequence is not None and self._expected_mode is not None:
                # Determine what mode API is showing
                if not api_locked:
                    api_mode = "Auto"
                elif api_presence == "HOME":
                    api_mode = "Home"
                else:
                    api_mode = "Away"
                
                if api_mode == self._expected_mode:
                    # API confirmed - clear optimistic state
                    self._clear_optimistic_state()
                else:
                    # Preserve optimistic state - API hasn't caught up yet
                    _LOGGER.debug(f"Presence Mode: Preserving optimistic state (expected={self._expected_mode}, api={api_mode})")
                    return
            
            # Update from API
            self._presence = api_presence
            self._presence_locked = api_locked
            
            # Determine mode from API state
            if not api_locked:
                self._attr_current_option = "Auto"
            elif api_presence == "HOME":
                self._attr_current_option = "Home"
            else:
                self._attr_current_option = "Away"
                
        except Exception as e:
            _LOGGER.warning(f"Failed to update presence mode: {e}")
            # Keep last known state
    
    async def async_select_option(self, option: str) -> None:
        """Select presence mode with 3-layer defense.
        
        v2.0.1: Bootstrap Reserve check
        v2.0.2: Full 3-layer optimistic update
        """
        from .async_api import get_async_client
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        # Store previous state for rollback
        old_mode = self._attr_current_option
        old_presence = self._presence
        old_locked = self._presence_locked
        
        # Layer 1 & 2: Optimistic update BEFORE API call
        self._attr_current_option = option
        self._optimistic_set_at = time.time()
        get_next_sequence = self.hass.data.get(DOMAIN, {}).get('get_next_sequence')
        if get_next_sequence:
            self._optimistic_sequence = get_next_sequence()
        
        # Layer 3: Set expected state
        self._expected_mode = option
        
        # Update internal state optimistically
        if option == "Auto":
            self._presence_locked = False
        else:
            self._presence_locked = True
            self._presence = option.upper()
        
        self.async_write_ha_state()
        
        # API call - normalize to lowercase for API
        option_lower = option.lower()
        client = get_async_client(self.hass)
        if option_lower == "auto":
            success = await client.delete_presence_lock()
        else:
            success = await client.set_presence_lock(option.upper())
        
        if success:
            _LOGGER.info(f"Set presence mode to {option}")
            await self._async_trigger_immediate_refresh(f"presence_mode_{option}")
        else:
            # Rollback on failure
            _LOGGER.warning(f"ROLLBACK: Presence mode {option} failed")
            self._attr_current_option = old_mode
            self._presence = old_presence
            self._presence_locked = old_locked
            self._clear_optimistic_state()
            self.async_write_ha_state()
    
    async def _async_trigger_immediate_refresh(self, reason: str):
        """Trigger immediate refresh after state change.
        
        v2.0.2: DRY refactor - delegates to shared async_trigger_immediate_refresh().
        Includes home_state refresh for presence mode changes.
        """
        from . import async_trigger_immediate_refresh
        await async_trigger_immediate_refresh(self.hass, self.entity_id, reason, include_home_state=True)
    
    async def _check_bootstrap_reserve(self) -> None:
        """Check if bootstrap reserve is depleted and block action if so.
        
        v2.0.1: Bootstrap Reserve - ensures 3 API calls are ALWAYS reserved
        for auto-recovery after API reset.
        
        v2.0.2: DRY refactor - delegates to shared async_check_bootstrap_reserve_or_raise().
        
        Raises:
            HomeAssistantError: If bootstrap reserve is depleted
        """
        from . import async_check_bootstrap_reserve_or_raise
        await async_check_bootstrap_reserve_or_raise(self.hass, "Presence Mode")
