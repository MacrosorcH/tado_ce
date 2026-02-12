"""Tado CE Climate Platform - Supports Heating and AC zones."""
import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
    FAN_AUTO,
    FAN_HIGH,
    FAN_MEDIUM,
    FAN_LOW,
    SWING_ON,
    PRESET_HOME,
    PRESET_AWAY,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.components.climate import ATTR_HVAC_MODE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .device_manager import get_zone_device_info
from .async_api import get_async_client
from .data_loader import (
    load_zones_file, load_zones_info_file, load_config_file,
    load_home_state_file, load_offsets_file, load_ac_capabilities_file,
    get_zone_names as dl_get_zone_names, get_zone_types as dl_get_zone_types
)
from .immediate_refresh_handler import SIGNAL_ZONES_UPDATED

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


# Tado AC modes mapping
TADO_TO_HA_HVAC_MODE = {
    "COOL": HVACMode.COOL,
    "HEAT": HVACMode.HEAT,
    "DRY": HVACMode.DRY,
    "FAN": HVACMode.FAN_ONLY,
    "AUTO": HVACMode.HEAT_COOL,
}

HA_TO_TADO_HVAC_MODE = {v: k for k, v in TADO_TO_HA_HVAC_MODE.items()}

# Fan level mapping - Tado uses SILENT, LEVEL1-5, AUTO
# Map to HA's limited fan modes (auto, low, medium, high)
TADO_TO_HA_FAN = {
    "AUTO": FAN_AUTO,
    "SILENT": FAN_LOW,
    "LEVEL1": FAN_LOW,
    "LEVEL2": FAN_LOW,
    "LEVEL3": FAN_MEDIUM,
    "LEVEL4": FAN_HIGH,
    "LEVEL5": FAN_HIGH,
    # Legacy mappings
    "HIGH": FAN_HIGH,
    "MIDDLE": FAN_MEDIUM,
    "LOW": FAN_LOW,
}

HA_TO_TADO_FAN = {
    FAN_AUTO: "AUTO",
    FAN_LOW: "LEVEL1",
    FAN_MEDIUM: "LEVEL3",
    FAN_HIGH: "LEVEL5",
}

def get_zone_names():
    """Load zone names from API data."""
    return dl_get_zone_names()


def get_zone_types():
    """Load zone types from API data."""
    return dl_get_zone_types()


def get_zone_capabilities():
    """Load zone capabilities (for AC zones).
    
    First tries to load from ac_capabilities.json (fetched from dedicated API endpoint).
    Falls back to zones_info.json for basic capabilities.
    """
    ac_caps = load_ac_capabilities_file() or {}
    zones_info = load_zones_info_file()
    
    if not zones_info:
        return {}
    
    caps = {}
    for z in zones_info:
        zone_id = str(z.get('id'))
        zone_type = z.get('type')
        
        if zone_type == 'AIR_CONDITIONING' and zone_id in ac_caps:
            # Use detailed AC capabilities from dedicated API
            caps[zone_id] = {
                'type': zone_type,
                'ac_capabilities': ac_caps[zone_id],
            }
        else:
            # Fallback to basic capabilities from zones_info
            # Use 'or {}' pattern for null safety
            caps[zone_id] = {
                'type': zone_type,
                'capabilities': z.get('capabilities') or {},
            }
    return caps


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up Tado CE climate from a config entry."""
    zone_names = await hass.async_add_executor_job(get_zone_names)
    zone_types = await hass.async_add_executor_job(get_zone_types)
    zone_caps = await hass.async_add_executor_job(get_zone_capabilities)
    
    climates = []
    try:
        zones_data = await hass.async_add_executor_job(load_zones_file)
        if zones_data:
            # Use 'or {}' pattern for null safety
            zone_states = zones_data.get('zoneStates') or {}
            for zone_id, zone_data in zone_states.items():
                zone_type = zone_types.get(zone_id, 'HEATING')
                zone_name = zone_names.get(zone_id, f"Zone {zone_id}")
                caps = zone_caps.get(zone_id, {})
                
                if zone_type == 'HEATING':
                    climates.append(TadoClimate(hass, zone_id, zone_name))
                elif zone_type == 'AIR_CONDITIONING':
                    climates.append(TadoACClimate(hass, zone_id, zone_name, caps))
    except Exception as e:
        _LOGGER.error(f"Failed to load zones for climate: {e}")
    
    async_add_entities(climates, True)
    _LOGGER.info(f"Tado CE climates loaded: {len(climates)}")


class TadoClimate(ClimateEntity):
    """Tado CE Climate Entity."""
    
    def __init__(self, hass: HomeAssistant, zone_id: str, zone_name: str):
        self.hass = hass
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._home_id = None
        
        self._attr_name = zone_name
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_climate"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "HEATING")
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TURN_OFF |
            ClimateEntityFeature.TURN_ON |
            ClimateEntityFeature.PRESET_MODE
        )
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF, HVACMode.AUTO]
        self._attr_preset_modes = [PRESET_HOME, PRESET_AWAY]
        self._attr_min_temp = 5
        self._attr_max_temp = 25
        self._attr_target_temperature_step = 0.5
        
        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_hvac_mode = None
        self._attr_hvac_action = None
        self._attr_available = False
        self._attr_current_humidity = None
        
        # Extra attributes
        self._overlay_type = None
        self._heating_power = None
        self._offset_celsius = None  # Temperature offset (optional, enabled in config)
        self._attr_preset_mode = PRESET_HOME
        
        # v2.0.0: Track last target temp from API for heating cycle detection
        self._last_target_temp_from_api: float | None = None
        
        # v1.10.0: Optimistic state tracking with sequence numbers (Issue #44 fix)
        # Replaces v1.9.7's flawed state-based tracking with coordinator-aware approach
        self._optimistic_state: dict | None = None  # Current optimistic state
        self._optimistic_sequence: int | None = None  # Sequence number of optimistic state
        self._expected_hvac_mode: HVACMode | None = None  # Expected mode after API call
        self._expected_hvac_action: HVACAction | None = None  # Expected action after API call
        
        # v1.9.3: Unsubscribe callback for zones_updated signal
        self._unsub_zones_updated = None

    # ========== v1.10.0: Helper Methods (Updated for Issue #44 fix) ==========
    
    def _clear_optimistic_state(self):
        """Clear all optimistic state tracking.
        
        v1.10.0: Updated for sequence-based tracking (Issue #44 fix).
        Called when:
        - API confirms the expected state
        - Optimistic window expires
        - API call fails (rollback)
        """
        self._optimistic_state = None
        self._optimistic_sequence = None
        self._expected_hvac_mode = None
        self._expected_hvac_action = None
    
    async def _set_optimistic_state(self, hvac_mode: HVACMode, hvac_action: HVACAction, target_temp: float = None):
        """Set optimistic state with sequence number tracking.
        
        v1.10.0: Updated for coordinator-aware optimistic updates (Issue #44 fix).
        Instead of time-based tracking, we now use sequence numbers and mark
        the entity as fresh in the coordinator to prevent stale data overwrites.
        
        v2.0.0: Changed to async to ensure mark_entity_fresh completes before
        async_write_ha_state() triggers update().
        
        Args:
            hvac_mode: The HVAC mode we expect API to confirm
            hvac_action: The HVAC action we expect API to confirm
            target_temp: Optional target temperature for optimistic state
        """
        # Get sequence number from coordinator
        get_next_sequence = self.hass.data.get(DOMAIN, {}).get('get_next_sequence')
        if get_next_sequence:
            self._optimistic_sequence = get_next_sequence()
        else:
            _LOGGER.warning(f"{self._zone_name}: get_next_sequence not available, using fallback")
            self._optimistic_sequence = int(time.time())
        
        # Set optimistic state
        self._optimistic_state = {
            "target_temperature": target_temp,
            "hvac_mode": hvac_mode,
            "hvac_action": hvac_action,
            "timestamp": time.time(),
        }
        self._expected_hvac_mode = hvac_mode
        self._expected_hvac_action = hvac_action
        
        # Mark entity as fresh in coordinator - MUST await to ensure freshness is set
        # before async_write_ha_state() triggers update()
        mark_entity_fresh = self.hass.data.get(DOMAIN, {}).get('mark_entity_fresh')
        if mark_entity_fresh:
            await mark_entity_fresh(self.entity_id)
        
        _LOGGER.debug(
            f"{self._zone_name}: Set optimistic state: mode={hvac_mode}, action={hvac_action}, seq={self._optimistic_sequence}"
        )
    
    def _calculate_hvac_action(self, target_temp: float = None) -> HVACAction:
        """Calculate hvac_action for heating zone.
        
        v1.10.0: Updated for optimistic update fix (Issue #44).
        
        Priority:
        1. If hvac_mode == OFF → OFF
        2. If target_temp provided (optimistic call) → HEATING
        3. If in optimistic window with expected action → return expected action
        4. If heating_power > 0 → HEATING (API confirms active heating)
        5. If hvac_mode == HEAT and target > current + 0.5 → HEATING (temperature fallback)
        6. Otherwise → IDLE
        
        Args:
            target_temp: Optional target temperature for optimistic updates.
                        If None, uses self._attr_target_temperature.
        
        Returns:
            HVACAction.HEATING, HVACAction.IDLE, or HVACAction.OFF
        """
        # OFF mode always returns OFF
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        
        # v2.0.0: If target_temp is provided (optimistic call), assume HEATING
        # This MUST be checked before _expected_hvac_action to ensure new
        # optimistic updates override stale expected actions
        if target_temp is not None and self._attr_hvac_mode == HVACMode.HEAT:
            return HVACAction.HEATING
        
        # v1.10.0: If we have optimistic state with expected action, use it
        # This ensures optimistic updates work even when current temp >= target
        if self._expected_hvac_action is not None:
            return self._expected_hvac_action
        
        # API confirms heating (highest priority when available)
        if self._heating_power and self._heating_power > 0:
            return HVACAction.HEATING
        
        # Temperature-aware fallback for HEAT mode
        # This handles the case where API hasn't updated heating_power yet
        if self._attr_hvac_mode == HVACMode.HEAT:
            target = self._attr_target_temperature
            current = self._attr_current_temperature
            if target is not None and current is not None:
                # 0.5°C buffer for hysteresis to prevent flip-flopping
                if target > current + 0.5:
                    return HVACAction.HEATING
        
        return HVACAction.IDLE

    # ========== End Helper Methods ==========

    async def async_added_to_hass(self):
        """Register signal listener when entity is added to hass.
        
        v1.9.3: Listen for SIGNAL_ZONES_UPDATED to force immediate update
        after zones.json is refreshed. This fixes the grey loading state
        issue (#44) where entities wait for SCAN_INTERVAL (30s).
        
        v1.9.6: Don't clear _optimistic_set_at here - let update() preserve
        optimistic hvac_action if API hasn't caught up yet (#44).
        """
        await super().async_added_to_hass()
        
        @callback
        def _handle_zones_updated():
            """Handle zones.json update signal."""
            # v1.9.6: Don't clear _optimistic_set_at - update() will preserve
            # optimistic hvac_action if heating_power hasn't updated yet (#44)
            # Schedule immediate update
            self.async_schedule_update_ha_state(True)
            _LOGGER.debug(f"{self._zone_name}: Received zones_updated signal, scheduling update")
        
        self._unsub_zones_updated = async_dispatcher_connect(
            self.hass, SIGNAL_ZONES_UPDATED, _handle_zones_updated
        )

    async def async_will_remove_from_hass(self):
        """Unregister signal listener when entity is removed.
        
        v1.9.3: Clean up signal listener to prevent memory leaks.
        """
        if self._unsub_zones_updated:
            self._unsub_zones_updated()
            self._unsub_zones_updated = None
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        attrs = {
            "overlay_type": self._overlay_type,
            "heating_power": self._heating_power,
            "zone_id": self._zone_id,
        }
        # Only include offset_celsius if enabled and available
        if self._offset_celsius is not None:
            attrs["offset_celsius"] = self._offset_celsius
        return attrs

    def update(self):
        """Update climate state from JSON file."""
        # v1.10.0: Layer 1 - Skip update if entity is fresh (coordinator-level protection)
        # This prevents unnecessary file I/O and processing when entity has recent API call
        is_entity_fresh = self.hass.data.get(DOMAIN, {}).get('is_entity_fresh')
        if is_entity_fresh and is_entity_fresh(self.entity_id):
            _LOGGER.debug(f"{self._zone_name}: Skipping update (entity is fresh)")
            return
        
        try:
            # Load home_id from config (uses data_loader for per-home file support)
            config = load_config_file()
            if config:
                self._home_id = config.get("home_id")
            
            # Load zones data (uses data_loader for per-home file support)
            data = load_zones_file()
            if data:
                # Use 'or {}' pattern for null safety
                zone_states = data.get('zoneStates') or {}
                zone_data = zone_states.get(self._zone_id)
            else:
                zone_data = None
            
            if not zone_data:
                self._attr_available = False
                return
            
            # Current temperature (use 'or {}' pattern for null safety)
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._attr_current_temperature = (
                (sensor_data.get('insideTemperature') or {}).get('celsius')
            )
            
            # Current humidity
            self._attr_current_humidity = (
                (sensor_data.get('humidity') or {}).get('percentage')
            )
            
            # Heating power
            activity_data = zone_data.get('activityDataPoints') or {}
            self._heating_power = (
                (activity_data.get('heatingPower') or {}).get('percentage', 0)
            )
            
            # Setting (target temp and mode)
            setting = zone_data.get('setting') or {}
            power = setting.get('power')
            self._overlay_type = zone_data.get('overlayType')
            
            # v1.9.7: Determine API-reported state first
            if power == 'ON':
                temp = (setting.get('temperature') or {}).get('celsius')
                self._attr_target_temperature = temp
                
                # v2.0.0 fix: Use SINGLE atomic call to heating cycle coordinator
                # This eliminates race conditions between setpoint and temperature updates
                if temp is not None and self._attr_current_temperature is not None:
                    heating_cycle_coordinator = self.hass.data.get(DOMAIN, {}).get('heating_cycle_coordinator')
                    if heating_cycle_coordinator:
                        # Use on_zone_update for atomic operation
                        self.hass.loop.call_soon_threadsafe(
                            self.hass.async_create_task,
                            heating_cycle_coordinator.on_zone_update(
                                self._zone_id, temp, self._attr_current_temperature
                            )
                        )
                
                # Determine HVAC mode - match official Tado integration behavior
                if self._overlay_type == 'MANUAL':
                    api_hvac_mode = HVACMode.HEAT
                else:
                    api_hvac_mode = HVACMode.AUTO
            else:
                # Power is OFF
                if self._overlay_type == 'MANUAL':
                    api_hvac_mode = HVACMode.OFF
                else:
                    api_hvac_mode = HVACMode.AUTO
            
            # v1.9.7: Calculate hvac_action based on API state
            # Temporarily set hvac_mode to calculate action correctly
            old_hvac_mode = self._attr_hvac_mode
            self._attr_hvac_mode = api_hvac_mode
            api_hvac_action = self._calculate_hvac_action()
            self._attr_hvac_mode = old_hvac_mode  # Restore for comparison
            
            # v1.10.0: Sequence-based optimistic state handling (Issue #44 fix)
            # Preserve optimistic state if we have an active optimistic sequence
            # and API hasn't confirmed our expected state yet
            should_preserve = False
            
            if self._optimistic_sequence is not None:
                # Check if API has confirmed our expected mode
                if api_hvac_mode == self._expected_hvac_mode and api_hvac_action == self._expected_hvac_action:
                    # API confirmed our expected state - clear optimistic state
                    _LOGGER.debug(f"{self._zone_name}: API confirmed optimistic state (mode={api_hvac_mode}, action={api_hvac_action}), clearing")
                    self._clear_optimistic_state()
                else:
                    # API hasn't caught up yet - PRESERVE optimistic state
                    should_preserve = True
                    _LOGGER.debug(
                        f"{self._zone_name}: Preserving optimistic state "
                        f"(expected mode={self._expected_hvac_mode}, action={self._expected_hvac_action}; "
                        f"API shows mode={api_hvac_mode}, action={api_hvac_action})"
                    )
            
            # v1.10.0: Apply state based on preservation decision
            if should_preserve:
                # Keep optimistic mode and action until API confirms
                self._attr_hvac_mode = self._expected_hvac_mode
                self._attr_hvac_action = self._expected_hvac_action
                _LOGGER.debug(f"{self._zone_name}: Using optimistic state: mode={self._attr_hvac_mode}, action={self._attr_hvac_action}")
            else:
                # Use API state
                self._attr_hvac_mode = api_hvac_mode
                self._attr_hvac_action = api_hvac_action
                
                # Handle OFF mode specifics
                if power != 'ON' and api_hvac_mode in (HVACMode.OFF, HVACMode.AUTO):
                    self._attr_target_temperature = None
                    if api_hvac_mode == HVACMode.OFF:
                        self._attr_hvac_action = HVACAction.OFF
            
            self._attr_available = True
            
            # v1.9.0: Record temperature for Smart Comfort analytics
            self._record_smart_comfort_data()
            
            # Update preset mode from home state
            self._update_preset_mode()
            
            # Update offset if enabled
            self._update_offset()
                
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self.name}: {e}")
            self._attr_available = False
    
    def _update_offset(self):
        """Update temperature offset from cached offsets file.
        
        Offset is synced during full sync if offset_enabled is True in config.
        Only reads offset if offset_enabled is True in config.
        """
        try:
            # Check if offset is enabled in config
            config_manager = self.hass.data.get(DOMAIN, {}).get('config_manager')
            if not config_manager or not config_manager.get_offset_enabled():
                self._offset_celsius = None
                return
            
            # Use data_loader for per-home file support
            offsets = load_offsets_file()
            if offsets:
                self._offset_celsius = offsets.get(self._zone_id)
            else:
                self._offset_celsius = None
        except Exception:
            # Keep existing offset value on error
            pass
    
    def _update_preset_mode(self):
        """Update preset mode based on home state (not mobile devices).
        
        Uses home_state.json which reflects the actual Tado home/away state,
        regardless of whether mobile device tracking is enabled.
        """
        try:
            # Use data_loader for per-home file support
            home_state = load_home_state_file()
            if home_state:
                presence = home_state.get('presence', 'HOME')
                self._attr_preset_mode = PRESET_HOME if presence == 'HOME' else PRESET_AWAY
        except Exception:
            # Keep last known preset mode
            pass

    async def async_set_preset_mode(self, preset_mode: str):
        """Set preset mode (Home/Away).
        
        Uses 1 API call to set presence lock.
        
        v1.9.2: Added timeout protection for consistency with other methods.
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        client = get_async_client(self.hass)
        state = "AWAY" if preset_mode == PRESET_AWAY else "HOME"
        
        # Optimistic update BEFORE API call
        old_preset = self._attr_preset_mode
        self._attr_preset_mode = preset_mode
        self._optimistic_set_at = time.time()
        self.async_write_ha_state()
        
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_presence_lock(state)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"TIMEOUT: {self._zone_name} preset mode API call timed out")
        except Exception as e:
            _LOGGER.warning(f"ERROR: {self._zone_name} preset mode API call failed ({e})")
        
        if api_success:
            _LOGGER.info(f"Set {self._zone_name} preset mode to {preset_mode}")
            await self._async_trigger_immediate_refresh("preset_mode_change")
        else:
            _LOGGER.warning(f"ROLLBACK: {self._zone_name} preset mode failed")
            self._attr_preset_mode = old_preset
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature.
        
        Optimized to use single API call when both temperature and hvac_mode are provided.
        This saves 1 API call (1% of 100-call limit) compared to calling set_hvac_mode first.
        
        v1.9.2: Changed from fire-and-forget to await pattern to fix grey loading state issue (#44).
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        temperature = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        
        # Handle hvac_mode without temperature (delegate to set_hvac_mode)
        if hvac_mode is not None and temperature is None:
            await self.async_set_hvac_mode(hvac_mode)
            return
        
        # Handle OFF mode specially (no temperature needed)
        if hvac_mode == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
            return
        
        # Handle AUTO mode specially (delete overlay, no temperature)
        if hvac_mode == HVACMode.AUTO:
            await self.async_set_hvac_mode(HVACMode.AUTO)
            return
        
        if temperature is None:
            return
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        # v1.10.0: Optimistic update BEFORE API call (Issue #44 fix)
        old_temp = self._attr_target_temperature
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action
        self._attr_target_temperature = temperature
        self._attr_hvac_mode = HVACMode.HEAT
        self._overlay_type = "MANUAL"
        # Calculate hvac_action
        new_hvac_action = self._calculate_hvac_action(target_temp=temperature)
        self._attr_hvac_action = new_hvac_action
        # Set optimistic state with sequence number and mark entity fresh
        await self._set_optimistic_state(HVACMode.HEAT, new_hvac_action, target_temp=temperature)
        _LOGGER.debug(f"Optimistic update: {self._zone_name} target_temp={temperature}, hvac_action={self._attr_hvac_action}")
        self.async_write_ha_state()
        
        # v1.9.2: Await API call with timeout (fixes #44 grey loading state)
        client = get_async_client(self.hass)
        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": temperature}
        }
        # v2.0.2: Use TADO_MODE to respect per-device "Manual Control" settings in Tado app
        # Issue #101 (@leoogermenia)
        termination = {"type": "TADO_MODE"}
        
        api_success = False
        try:
            async with asyncio.timeout(10):  # 10 second timeout
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"TIMEOUT: {self._zone_name} API call timed out, reverting to {old_temp}")
        except Exception as e:
            _LOGGER.warning(f"ERROR: {self._zone_name} API call failed ({e}), reverting to {old_temp}")
        
        if api_success:
            _LOGGER.info(f"Set {self._zone_name} to {temperature}°C")
            # v2.0.0: Notify heating cycle coordinator of setpoint change
            heating_cycle_coordinator = self.hass.data.get(DOMAIN, {}).get('heating_cycle_coordinator')
            if heating_cycle_coordinator:
                await heating_cycle_coordinator.on_setpoint_change(
                    self._zone_id, temperature, self._attr_current_temperature
                )
            # Refresh is best-effort, don't rollback if it fails
            await self._async_trigger_immediate_refresh("temperature_change")
        else:
            # v1.10.0: Rollback on API failure (Issue #44 fix)
            self._attr_target_temperature = old_temp
            self._attr_hvac_mode = old_mode
            self._attr_hvac_action = old_action
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        """Set new HVAC mode.
        
        v1.9.2: Changed from fire-and-forget to await pattern to fix grey loading state issue (#44).
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        client = get_async_client(self.hass)
        
        if hvac_mode == HVACMode.HEAT:
            temp = self._attr_target_temperature or 20
            setting = {
                "type": "HEATING",
                "power": "ON",
                "temperature": {"celsius": temp}
            }
            # v2.0.2: Use TADO_MODE to respect per-device settings (Issue #101)
            termination = {"type": "TADO_MODE"}
            
            # Optimistic update BEFORE API call
            old_mode = self._attr_hvac_mode
            old_action = self._attr_hvac_action
            self._attr_hvac_mode = HVACMode.HEAT
            self._overlay_type = "MANUAL"
            # v1.9.7: Use helper method for hvac_action calculation
            new_hvac_action = self._calculate_hvac_action(target_temp=temp)
            self._attr_hvac_action = new_hvac_action
            # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
            await self._set_optimistic_state(HVACMode.HEAT, new_hvac_action, target_temp=temp)
            self.async_write_ha_state()
            
            # v1.9.2: Await API call with timeout (fixes #44)
            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
            except asyncio.TimeoutError:
                _LOGGER.warning(f"TIMEOUT: {self._zone_name} HEAT mode API call timed out")
            except Exception as e:
                _LOGGER.warning(f"ERROR: {self._zone_name} HEAT mode API call failed ({e})")
            
            if api_success:
                _LOGGER.info(f"Set {self._zone_name} to HEAT mode at {temp}°C")
                await self._async_trigger_immediate_refresh("hvac_mode_change")
            else:
                _LOGGER.warning(f"ROLLBACK: {self._zone_name} HEAT mode failed")
                self._attr_hvac_mode = old_mode
                self._attr_hvac_action = old_action
                self._clear_optimistic_state()
                self.async_write_ha_state()
                
        elif hvac_mode == HVACMode.OFF:
            setting = {
                "type": "HEATING",
                "power": "OFF"
            }
            # v2.0.2: Use TADO_MODE to respect per-device settings (Issue #101)
            termination = {"type": "TADO_MODE"}
            
            # Optimistic update BEFORE API call
            old_mode = self._attr_hvac_mode
            old_action = self._attr_hvac_action
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_hvac_action = HVACAction.OFF
            self._overlay_type = "MANUAL"
            # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
            # For OFF mode, we expect API to confirm quickly
            await self._set_optimistic_state(HVACMode.OFF, HVACAction.OFF)
            self.async_write_ha_state()
            
            # v1.9.2: Await API call with timeout (fixes #44)
            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
            except asyncio.TimeoutError:
                _LOGGER.warning(f"TIMEOUT: {self._zone_name} OFF mode API call timed out")
            except Exception as e:
                _LOGGER.warning(f"ERROR: {self._zone_name} OFF mode API call failed ({e})")
            
            if api_success:
                _LOGGER.info(f"Set {self._zone_name} to OFF mode")
                await self._async_trigger_immediate_refresh("hvac_mode_change")
            else:
                _LOGGER.warning(f"ROLLBACK: {self._zone_name} OFF mode failed")
                self._attr_hvac_mode = old_mode
                self._attr_hvac_action = old_action
                self._clear_optimistic_state()
                self.async_write_ha_state()
                
        elif hvac_mode == HVACMode.AUTO:
            # Optimistic update BEFORE API call
            old_mode = self._attr_hvac_mode
            old_overlay = self._overlay_type
            old_action = self._attr_hvac_action
            self._attr_hvac_mode = HVACMode.AUTO
            self._overlay_type = None
            # v1.9.7: Set hvac_action to IDLE when switching to AUTO
            # The actual heating state will be updated when zones.json is refreshed
            self._attr_hvac_action = HVACAction.IDLE
            # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
            # For AUTO mode, we expect API to confirm quickly
            await self._set_optimistic_state(HVACMode.AUTO, HVACAction.IDLE)
            self.async_write_ha_state()
            
            # v1.9.2: Await API call with timeout (fixes #44)
            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await client.delete_zone_overlay(self._zone_id)
            except asyncio.TimeoutError:
                _LOGGER.warning(f"TIMEOUT: {self._zone_name} AUTO mode API call timed out")
            except Exception as e:
                _LOGGER.warning(f"ERROR: {self._zone_name} AUTO mode API call failed ({e})")
            
            if api_success:
                _LOGGER.info(f"Set {self._zone_name} to AUTO mode (deleted overlay)")
                await self._async_trigger_immediate_refresh("hvac_mode_change")
            else:
                _LOGGER.warning(f"ROLLBACK: {self._zone_name} AUTO mode failed")
                self._attr_hvac_mode = old_mode
                self._overlay_type = old_overlay
                self._attr_hvac_action = old_action
                self._clear_optimistic_state()
                self.async_write_ha_state()
    
    async def _async_trigger_immediate_refresh(self, reason: str):
        """Trigger immediate refresh after state change.
        
        v2.0.1: DRY refactor - delegates to shared async_trigger_immediate_refresh().
        """
        from . import async_trigger_immediate_refresh
        await async_trigger_immediate_refresh(self.hass, self.entity_id, reason)

    async def async_set_timer(self, temperature: float, duration_minutes: int = None, overlay: str = None) -> bool:
        """Set temperature with timer or overlay type.
        
        Args:
            temperature: Target temperature in Celsius
            duration_minutes: Duration in minutes (for TIMER termination)
            overlay: Overlay type - 'next_time_block' for TADO_MODE, None for MANUAL
            
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        client = get_async_client(self.hass)
        
        setting = {
            "type": "HEATING",
            "power": "ON",
            "temperature": {"celsius": temperature}
        }
        
        # Determine termination type
        if duration_minutes:
            termination = {
                "type": "TIMER",
                "durationInSeconds": duration_minutes * 60
            }
            term_desc = f"for {duration_minutes} minutes"
        elif overlay == "next_time_block":
            termination = {"type": "TADO_MODE"}
            term_desc = "until next schedule block"
        else:
            termination = {"type": "MANUAL"}
            term_desc = "manually"
        
        # v1.9.2: Added timeout protection for consistency
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"TIMEOUT: {self._zone_name} set_timer API call timed out")
        except Exception as e:
            _LOGGER.warning(f"ERROR: {self._zone_name} set_timer API call failed ({e})")
        
        if api_success:
            _LOGGER.info(f"Set {self._zone_name} to {temperature}°C {term_desc}")
            return True
        return False
    
    def _record_smart_comfort_data(self):
        """Record temperature data for Smart Comfort analytics.
        
        v1.9.0: Records current temperature and heating state to the
        SmartComfortManager for rate calculation and predictions.
        """
        try:
            smart_comfort_manager = self.hass.data.get(DOMAIN, {}).get('smart_comfort_manager')
            if not smart_comfort_manager or not smart_comfort_manager.is_enabled:
                return
            
            # Only record if we have valid temperature data
            if self._attr_current_temperature is None:
                return
            
            # Determine if actively heating
            is_heating = (
                self._heating_power is not None and 
                self._heating_power > 0
            )
            
            smart_comfort_manager.record_temperature(
                zone_id=self._zone_id,
                zone_name=self._zone_name,
                temperature=self._attr_current_temperature,
                is_heating=is_heating,
                target_temperature=self._attr_target_temperature
            )
        except Exception as e:
            _LOGGER.debug(f"Failed to record smart comfort data for {self._zone_name}: {e}")

    async def _check_bootstrap_reserve(self) -> None:
        """Check bootstrap reserve and raise error if quota critically low.
        
        v2.0.1: Bootstrap Reserve - blocks ALL actions (including manual) when quota
        falls to the absolute minimum needed for auto-recovery after API reset.
        
        v2.0.1: DRY refactor - delegates to shared async_check_bootstrap_reserve_or_raise().
        
        Raises:
            HomeAssistantError: If quota is at bootstrap reserve level
        """
        from . import async_check_bootstrap_reserve_or_raise
        await async_check_bootstrap_reserve_or_raise(self.hass, self._zone_name)


class TadoACClimate(ClimateEntity):
    """Tado CE Air Conditioning Climate Entity."""
    
    def __init__(self, hass: HomeAssistant, zone_id: str, zone_name: str, capabilities: dict):
        self.hass = hass
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._home_id = None
        self._capabilities = capabilities
        
        self._attr_name = zone_name
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_zone_{zone_id}_ac_climate"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, "AIR_CONDITIONING")
        
        # Get AC capabilities from dedicated API endpoint
        # Format: {"COOL": {...}, "HEAT": {...}, "DRY": {...}, "FAN": {...}, "AUTO": {...}}
        # Use 'or {}' pattern for null safety
        ac_caps = capabilities.get('ac_capabilities') or {}
        
        # Build supported features based on capabilities
        features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        
        # Check if any mode has fan levels
        has_fan = any((ac_caps.get(mode) or {}).get('fanLevel') for mode in ['COOL', 'HEAT', 'DRY', 'FAN', 'AUTO'])
        if has_fan:
            features |= ClimateEntityFeature.FAN_MODE
        
        # Check if any mode has swing options
        has_swing = any(
            (ac_caps.get(mode) or {}).get('verticalSwing') or (ac_caps.get(mode) or {}).get('horizontalSwing')
            for mode in ['COOL', 'HEAT', 'DRY', 'FAN', 'AUTO']
        )
        if has_swing:
            features |= ClimateEntityFeature.SWING_MODE
        
        self._attr_supported_features = features
        
        # Build HVAC modes based on capabilities
        # v1.5.5: Removed HVACMode.AUTO from AC to avoid confusion
        # - HVACMode.AUTO in HA means "follow schedule" (delete overlay)
        # - Users confused it with Tado's AUTO mode (heat/cool as needed)
        # - Tado's AUTO = HA's HEAT_COOL
        # - AC users can still delete overlay via Resume Schedule button
        self._attr_hvac_modes = [HVACMode.OFF]
        
        # Add modes that exist in capabilities
        for tado_mode in ['COOL', 'HEAT', 'DRY', 'FAN']:
            if tado_mode in ac_caps:
                ha_mode = TADO_TO_HA_HVAC_MODE.get(tado_mode)
                if ha_mode and ha_mode not in self._attr_hvac_modes:
                    self._attr_hvac_modes.append(ha_mode)
        
        # If AUTO mode exists in capabilities, add HEAT_COOL
        # Tado's AUTO = HA's HEAT_COOL (heat or cool as needed)
        if 'AUTO' in ac_caps:
            if HVACMode.HEAT_COOL not in self._attr_hvac_modes:
                self._attr_hvac_modes.append(HVACMode.HEAT_COOL)
        
        _LOGGER.debug(f"AC zone {zone_id} HVAC modes: {self._attr_hvac_modes}")
        
        # Fan modes - collect from all modes that have fanLevel
        fan_levels = set()
        for mode_caps in ac_caps.values():
            if isinstance(mode_caps, dict) and 'fanLevel' in mode_caps:
                fan_levels.update(mode_caps['fanLevel'])
        
        if fan_levels:
            # Map Tado fan levels to HA fan modes
            self._attr_fan_modes = []
            if 'AUTO' in fan_levels:
                self._attr_fan_modes.append(FAN_AUTO)
            if any(f in fan_levels for f in ['SILENT', 'LEVEL1', 'LEVEL2', 'LOW']):
                self._attr_fan_modes.append(FAN_LOW)
            if any(f in fan_levels for f in ['LEVEL3', 'MIDDLE']):
                self._attr_fan_modes.append(FAN_MEDIUM)
            if any(f in fan_levels for f in ['LEVEL4', 'LEVEL5', 'HIGH']):
                self._attr_fan_modes.append(FAN_HIGH)
            _LOGGER.debug(f"AC zone {zone_id} fan modes: {self._attr_fan_modes} (from {fan_levels})")
        else:
            self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        
        # Swing modes - unified dropdown like official Tado integration
        # Options: off, vertical, horizontal, both
        if has_swing:
            self._attr_swing_modes = ["off", "vertical", "horizontal", "both"]
        else:
            self._attr_swing_modes = None
        
        # Temperature range from capabilities
        # Get from any mode that has temperatures (COOL is most common)
        temp_caps = None
        for mode in ['COOL', 'HEAT', 'AUTO', 'DRY']:
            if mode in ac_caps and 'temperatures' in ac_caps[mode]:
                # Use 'or {}' pattern for null safety
                temp_caps = (ac_caps[mode]['temperatures'].get('celsius') or {})
                break
        
        if temp_caps:
            self._attr_min_temp = temp_caps.get('min', 16)
            self._attr_max_temp = temp_caps.get('max', 30)
            self._attr_target_temperature_step = temp_caps.get('step', 1)
        else:
            self._attr_min_temp = 16
            self._attr_max_temp = 30
            self._attr_target_temperature_step = 1
        
        self._attr_current_temperature = None
        self._attr_target_temperature = None
        self._attr_hvac_mode = None
        self._attr_hvac_action = None
        # v1.9.3: Set default fan/swing modes to suppress HA startup validation warnings (#44)
        # HA validates that current mode is in the modes list, so we set valid defaults
        self._attr_fan_mode = self._attr_fan_modes[0] if self._attr_fan_modes else None
        self._attr_swing_mode = self._attr_swing_modes[0] if self._attr_swing_modes else None
        self._attr_available = False
        self._attr_current_humidity = None
        
        self._overlay_type = None
        self._ac_power_percentage = None
        
        # v1.10.0: Optimistic state tracking with sequence numbers (Issue #44 fix)
        # Replaces v1.9.7's flawed state-based tracking with coordinator-aware approach
        self._optimistic_state: dict | None = None  # Current optimistic state
        self._optimistic_sequence: int | None = None  # Sequence number of optimistic state
        self._expected_hvac_mode: HVACMode | None = None  # Expected mode after API call
        self._expected_hvac_action: HVACAction | None = None  # Expected action after API call
        
        # v1.9.3: Unsubscribe callback for zones_updated signal
        self._unsub_zones_updated = None

    # ========== v1.10.0: Helper Methods (Updated for Issue #44 fix) ==========
    
    def _clear_optimistic_state(self):
        """Clear all optimistic state tracking.
        
        v1.10.0: Updated for sequence-based tracking (Issue #44 fix).
        Called when:
        - API confirms the expected state
        - Optimistic window expires
        - API call fails (rollback)
        """
        self._optimistic_state = None
        self._optimistic_sequence = None
        self._expected_hvac_mode = None
        self._expected_hvac_action = None
    
    async def _set_optimistic_state(self, hvac_mode: HVACMode, hvac_action: HVACAction, target_temp: float = None):
        """Set optimistic state with sequence number tracking.
        
        v1.10.0: Updated for coordinator-aware optimistic updates (Issue #44 fix).
        Instead of time-based tracking, we now use sequence numbers and mark
        the entity as fresh in the coordinator to prevent stale data overwrites.
        
        v2.0.0: Changed to async to ensure mark_entity_fresh completes before
        async_write_ha_state() triggers update().
        
        Args:
            hvac_mode: The HVAC mode we expect API to confirm
            hvac_action: The HVAC action we expect API to confirm
            target_temp: Optional target temperature for optimistic state
        """
        # Get sequence number from coordinator
        get_next_sequence = self.hass.data.get(DOMAIN, {}).get('get_next_sequence')
        if get_next_sequence:
            self._optimistic_sequence = get_next_sequence()
        else:
            _LOGGER.warning(f"AC {self._zone_name}: get_next_sequence not available, using fallback")
            self._optimistic_sequence = int(time.time())
        
        # Set optimistic state
        self._optimistic_state = {
            "target_temperature": target_temp,
            "hvac_mode": hvac_mode,
            "hvac_action": hvac_action,
            "timestamp": time.time(),
        }
        self._expected_hvac_mode = hvac_mode
        self._expected_hvac_action = hvac_action
        
        # Mark entity as fresh in coordinator - MUST await to ensure freshness is set
        # before async_write_ha_state() triggers update()
        mark_entity_fresh = self.hass.data.get(DOMAIN, {}).get('mark_entity_fresh')
        if mark_entity_fresh:
            await mark_entity_fresh(self.entity_id)
        
        _LOGGER.debug(
            f"AC {self._zone_name}: Set optimistic state: mode={hvac_mode}, action={hvac_action}, seq={self._optimistic_sequence}"
        )
    
    def _calculate_hvac_action(self, hvac_mode: HVACMode = None, ac_power_on: bool = None) -> HVACAction:
        """Calculate hvac_action for AC zone.
        
        v1.10.0: Updated for optimistic update fix (Issue #44).
        
        Priority:
        1. If hvac_mode == OFF → OFF
        2. If in optimistic window with expected action → return expected action
        3. If API confirms AC is off → IDLE
        4. Mode-based action (COOL→COOLING, HEAT→HEATING, etc.)
        
        Args:
            hvac_mode: Optional mode for optimistic updates.
                      If None, uses self._attr_hvac_mode.
            ac_power_on: Optional AC power state from API.
                        If None, assumes AC is ON (for optimistic updates).
                        If False, returns IDLE (API confirms AC is off).
        
        Returns:
            HVACAction based on mode (COOLING, HEATING, DRYING, FAN, IDLE, or OFF)
        """
        mode = hvac_mode if hvac_mode is not None else self._attr_hvac_mode
        
        # OFF mode always returns OFF
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        
        # v1.10.0: If we have optimistic state with expected action, use it
        # This ensures optimistic updates work immediately
        if self._expected_hvac_action is not None:
            return self._expected_hvac_action
        
        # If API confirms AC is off, return IDLE
        if ac_power_on is False:
            return HVACAction.IDLE
        
        # Mode-based action (AC is ON or assumed ON for optimistic)
        if mode == HVACMode.COOL:
            return HVACAction.COOLING
        elif mode == HVACMode.HEAT:
            return HVACAction.HEATING
        elif mode == HVACMode.DRY:
            return HVACAction.DRYING
        elif mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN
        elif mode == HVACMode.HEAT_COOL:
            # Tado AUTO mode - AC decides to heat or cool as needed
            return HVACAction.IDLE
        
        return HVACAction.IDLE

    # ========== End Helper Methods ==========

    async def async_added_to_hass(self):
        """Register signal listener when entity is added to hass.
        
        v1.9.3: Listen for SIGNAL_ZONES_UPDATED to force immediate update
        after zones.json is refreshed. This fixes the grey loading state
        issue (#44) where entities wait for SCAN_INTERVAL (30s).
        
        v1.9.6: Don't clear _optimistic_set_at here - let update() preserve
        optimistic hvac_action if API hasn't caught up yet (#44).
        """
        await super().async_added_to_hass()
        
        @callback
        def _handle_zones_updated():
            """Handle zones.json update signal."""
            # v1.9.6: Don't clear _optimistic_set_at - update() will preserve
            # optimistic hvac_action if ac_power hasn't updated yet (#44)
            # Schedule immediate update
            self.async_schedule_update_ha_state(True)
            _LOGGER.debug(f"AC {self._zone_name}: Received zones_updated signal, scheduling update")
        
        self._unsub_zones_updated = async_dispatcher_connect(
            self.hass, SIGNAL_ZONES_UPDATED, _handle_zones_updated
        )

    async def async_will_remove_from_hass(self):
        """Unregister signal listener when entity is removed.
        
        v1.9.3: Clean up signal listener to prevent memory leaks.
        """
        if self._unsub_zones_updated:
            self._unsub_zones_updated()
            self._unsub_zones_updated = None
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "overlay_type": self._overlay_type,
            "ac_power_percentage": self._ac_power_percentage,
            "zone_id": self._zone_id,
            "zone_type": "AIR_CONDITIONING",
        }

    def update(self):
        """Update AC climate state from JSON file."""
        # v1.10.0: Layer 1 - Skip update if entity is fresh (coordinator-level protection)
        # This prevents unnecessary file I/O and processing when entity has recent API call
        is_entity_fresh = self.hass.data.get(DOMAIN, {}).get('is_entity_fresh')
        if is_entity_fresh and is_entity_fresh(self.entity_id):
            _LOGGER.debug(f"AC {self._zone_name}: Skipping update (entity is fresh)")
            return
        
        try:
            # Load home_id from config (uses data_loader for per-home file support)
            config = load_config_file()
            if config:
                self._home_id = config.get("home_id")
            
            # Load zones data (uses data_loader for per-home file support)
            data = load_zones_file()
            if data:
                # Use 'or {}' pattern for null safety
                zone_states = data.get('zoneStates') or {}
                zone_data = zone_states.get(self._zone_id)
            else:
                zone_data = None
                
            if not zone_data:
                self._attr_available = False
                return
            
            # Current temperature (use 'or {}' pattern for null safety)
            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._attr_current_temperature = (
                (sensor_data.get('insideTemperature') or {}).get('celsius')
            )
            
            # Current humidity
            self._attr_current_humidity = (
                (sensor_data.get('humidity') or {}).get('percentage')
            )
            
            # AC power state - API returns {'value': 'ON'/'OFF'} not percentage
            activity_data = zone_data.get('activityDataPoints') or {}
            ac_power = activity_data.get('acPower') or {}
            ac_power_value = ac_power.get('value')  # 'ON' or 'OFF'
            # Keep percentage for backwards compatibility attribute
            self._ac_power_percentage = ac_power.get('percentage')
            
            # Setting
            setting = zone_data.get('setting') or {}
            power = setting.get('power')
            self._overlay_type = zone_data.get('overlayType')
            
            if power == 'ON':
                # Temperature
                temp = (setting.get('temperature') or {}).get('celsius')
                self._attr_target_temperature = temp
                
                # Mode
                tado_mode = setting.get('mode')
                self._attr_hvac_mode = TADO_TO_HA_HVAC_MODE.get(tado_mode, HVACMode.AUTO)
                
                # Fan - API returns fanLevel (newer firmware) or fanSpeed (older firmware)
                fan_level = setting.get('fanLevel') or setting.get('fanSpeed')
                self._attr_fan_mode = TADO_TO_HA_FAN.get(fan_level, FAN_AUTO)
                
                # Swing - API returns verticalSwing/horizontalSwing (not swing)
                # Map to unified swing mode: off/vertical/horizontal/both
                vertical_swing = setting.get('verticalSwing', 'OFF')
                horizontal_swing = setting.get('horizontalSwing', 'OFF')
                v_on = vertical_swing != 'OFF'
                h_on = horizontal_swing != 'OFF'
                if v_on and h_on:
                    self._attr_swing_mode = "both"
                elif v_on:
                    self._attr_swing_mode = "vertical"
                elif h_on:
                    self._attr_swing_mode = "horizontal"
                else:
                    self._attr_swing_mode = "off"
                
                # HVAC action - based on acPower.value ('ON'/'OFF')
                # v1.10.0: Use helper method for hvac_action calculation
                ac_power_on = (ac_power_value == 'ON')
                api_hvac_action = self._calculate_hvac_action(hvac_mode=self._attr_hvac_mode, ac_power_on=ac_power_on)
                
                # v1.10.0: Sequence-based optimistic state handling (Issue #44 fix)
                # Preserve optimistic state if we have an active optimistic sequence
                # and API hasn't confirmed our expected state yet
                should_preserve = False
                
                if self._optimistic_sequence is not None:
                    # Check if API has confirmed our expected mode and action
                    if self._attr_hvac_mode == self._expected_hvac_mode and api_hvac_action == self._expected_hvac_action:
                        # API confirmed our expected state - clear optimistic state
                        _LOGGER.debug(f"AC {self._zone_name}: API confirmed optimistic state (mode={self._attr_hvac_mode}, action={api_hvac_action}), clearing")
                        self._clear_optimistic_state()
                    else:
                        # API hasn't caught up yet - PRESERVE optimistic state
                        should_preserve = True
                        _LOGGER.debug(
                            f"AC {self._zone_name}: Preserving optimistic state "
                            f"(expected mode={self._expected_hvac_mode}, action={self._expected_hvac_action}; "
                            f"API shows mode={self._attr_hvac_mode}, action={api_hvac_action})"
                        )
                
                # Apply state based on preservation decision
                if should_preserve:
                    # Keep optimistic mode and action until API confirms
                    self._attr_hvac_mode = self._expected_hvac_mode
                    self._attr_hvac_action = self._expected_hvac_action
                    _LOGGER.debug(f"AC {self._zone_name}: Using optimistic state: mode={self._attr_hvac_mode}, action={self._attr_hvac_action}")
                else:
                    self._attr_hvac_action = api_hvac_action
            else:
                # Power is OFF - keep last temperature for reference
                # v1.10.0: Sequence-based optimistic state handling for AC OFF (Issue #44 fix)
                if self._optimistic_sequence is not None:
                    if self._expected_hvac_mode == HVACMode.OFF:
                        # We expected OFF and API confirms OFF - clear optimistic state
                        _LOGGER.debug(f"AC {self._zone_name}: API confirmed OFF mode, clearing optimistic state")
                        self._clear_optimistic_state()
                        self._attr_hvac_mode = HVACMode.OFF
                        self._attr_hvac_action = HVACAction.OFF
                    else:
                        # We expected a different mode but API shows OFF
                        # PRESERVE optimistic state - API hasn't caught up yet
                        _LOGGER.debug(f"AC {self._zone_name}: Preserving optimistic state (expected={self._expected_hvac_mode}, API shows OFF)")
                        self._attr_hvac_mode = self._expected_hvac_mode
                        self._attr_hvac_action = self._expected_hvac_action
                else:
                    # No optimistic state - trust API
                    self._attr_hvac_mode = HVACMode.OFF
                    self._attr_hvac_action = HVACAction.OFF
            
            self._attr_available = True
            
            # v1.9.0: Record temperature for Smart Comfort analytics
            self._record_smart_comfort_data(ac_power_value)
                
        except Exception as e:
            _LOGGER.warning(f"Failed to update {self.name}: {e}")
            self._attr_available = False

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature.
        
        Optimized to use single API call when both temperature and hvac_mode are provided.
        This saves 1 API call (1% of 100-call limit) compared to calling set_hvac_mode first.
        
        v1.9.2: Changed from fire-and-forget to await pattern to fix grey loading state issue (#44).
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        temperature = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        
        # Handle hvac_mode without temperature (delegate to set_hvac_mode)
        if hvac_mode is not None and temperature is None:
            await self.async_set_hvac_mode(hvac_mode)
            return
        
        # Handle OFF mode specially (no temperature needed)
        if hvac_mode == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
            return
        
        # Handle AUTO mode specially (delete overlay, no temperature)
        # Note: For AC, HVACMode.AUTO means "follow schedule" (delete overlay)
        if hvac_mode == HVACMode.AUTO:
            await self.async_set_hvac_mode(HVACMode.AUTO)
            return
        
        if temperature is None:
            return
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        # Convert hvac_mode to Tado mode for the overlay
        tado_mode = HA_TO_TADO_HVAC_MODE.get(hvac_mode) if hvac_mode else None
        
        # Optimistic update BEFORE API call
        old_temp = self._attr_target_temperature
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action
        
        self._attr_target_temperature = temperature
        if hvac_mode is not None:
            self._attr_hvac_mode = hvac_mode
        
        # If AC is OFF, setting temperature will turn it ON
        if old_mode == HVACMode.OFF:
            self._attr_hvac_mode = hvac_mode if hvac_mode else HVACMode.COOL
        
        # v1.10.0: Use helper method for hvac_action calculation
        new_hvac_action = self._calculate_hvac_action()
        self._attr_hvac_action = new_hvac_action
        
        self._overlay_type = "MANUAL"
        # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
        await self._set_optimistic_state(self._attr_hvac_mode, new_hvac_action, target_temp=temperature)
        _LOGGER.debug(f"AC Optimistic update: {self._zone_name} target_temp={temperature}, hvac_action={new_hvac_action}")
        self.async_write_ha_state()
        
        # v1.9.2: Await API call with timeout (fixes #44)
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await self._async_set_ac_overlay(temperature=temperature, mode=tado_mode)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"AC TIMEOUT: {self._zone_name} temperature change timed out")
        except Exception as e:
            _LOGGER.warning(f"AC ERROR: {self._zone_name} temperature change failed ({e})")
        
        if api_success:
            _LOGGER.info(f"AC Set {self._zone_name} to {temperature}°C")
            await self._async_trigger_immediate_refresh("temperature_change")
        else:
            _LOGGER.warning(f"AC ROLLBACK: {self._zone_name} temperature change failed")
            self._attr_target_temperature = old_temp
            self._attr_hvac_mode = old_mode
            self._attr_hvac_action = old_action
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        """Set new HVAC mode.
        
        v1.9.2: Changed from fire-and-forget to await pattern to fix grey loading state issue (#44).
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        client = get_async_client(self.hass)
        
        if hvac_mode == HVACMode.OFF:
            # Optimistic update BEFORE API call
            old_mode = self._attr_hvac_mode
            old_action = self._attr_hvac_action
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_hvac_action = HVACAction.OFF
            self._overlay_type = "MANUAL"
            # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
            await self._set_optimistic_state(HVACMode.OFF, HVACAction.OFF)
            self.async_write_ha_state()
            
            setting = {
                "type": "AIR_CONDITIONING",
                "power": "OFF"
            }
            # v2.0.2: Use TADO_MODE to respect per-device settings (Issue #101)
            termination = {"type": "TADO_MODE"}
            
            # v1.9.2: Await API call with timeout (fixes #44)
            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await client.set_zone_overlay(self._zone_id, setting, termination)
            except asyncio.TimeoutError:
                _LOGGER.warning(f"AC TIMEOUT: {self._zone_name} OFF mode API call timed out")
            except Exception as e:
                _LOGGER.warning(f"AC ERROR: {self._zone_name} OFF mode API call failed ({e})")
            
            if api_success:
                _LOGGER.info(f"AC Set {self._zone_name} to OFF mode")
                await self._async_trigger_immediate_refresh("hvac_mode_change")
            else:
                _LOGGER.warning(f"AC ROLLBACK: {self._zone_name} OFF mode failed")
                self._attr_hvac_mode = old_mode
                self._attr_hvac_action = old_action
                self._clear_optimistic_state()
                self.async_write_ha_state()
                
        elif hvac_mode == HVACMode.AUTO:
            # Optimistic update BEFORE API call
            old_mode = self._attr_hvac_mode
            old_overlay = self._overlay_type
            old_action = self._attr_hvac_action
            self._attr_hvac_mode = HVACMode.AUTO
            self._overlay_type = None
            # v1.9.7: Set hvac_action to IDLE when switching to AUTO
            # The actual state will be updated when zones.json is refreshed.
            self._attr_hvac_action = HVACAction.IDLE
            # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
            await self._set_optimistic_state(HVACMode.AUTO, HVACAction.IDLE)
            self.async_write_ha_state()
            
            # v1.9.2: Await API call with timeout (fixes #44)
            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await client.delete_zone_overlay(self._zone_id)
            except asyncio.TimeoutError:
                _LOGGER.warning(f"AC TIMEOUT: {self._zone_name} AUTO mode API call timed out")
            except Exception as e:
                _LOGGER.warning(f"AC ERROR: {self._zone_name} AUTO mode API call failed ({e})")
            
            if api_success:
                _LOGGER.info(f"AC Set {self._zone_name} to AUTO mode (deleted overlay)")
                await self._async_trigger_immediate_refresh("hvac_mode_change")
            else:
                _LOGGER.warning(f"AC ROLLBACK: {self._zone_name} AUTO mode failed")
                self._attr_hvac_mode = old_mode
                self._overlay_type = old_overlay
                self._attr_hvac_action = old_action
                self._clear_optimistic_state()
                self.async_write_ha_state()
        else:
            # Optimistic update BEFORE API call
            # Include all attributes that will be set by _async_set_ac_overlay
            old_mode = self._attr_hvac_mode
            old_temp = self._attr_target_temperature
            old_fan = self._attr_fan_mode
            old_action = self._attr_hvac_action
            
            self._attr_hvac_mode = hvac_mode
            self._overlay_type = "MANUAL"
            
            # Set default temperature if not already set (matches _async_set_ac_overlay logic)
            # v1.9.3: Clear temperature for FAN/DRY modes that don't support it (#44)
            tado_mode = HA_TO_TADO_HVAC_MODE.get(hvac_mode, 'COOL')
            
            # Check if this mode supports temperature (from capabilities)
            ac_caps = self._capabilities.get('ac_capabilities') or {}
            mode_caps = ac_caps.get(tado_mode) or {}
            mode_has_temp = 'temperatures' in mode_caps
            
            if tado_mode == "FAN" or not mode_has_temp:
                # FAN mode and modes without temperature support: clear temperature display
                self._attr_target_temperature = None
            elif not self._attr_target_temperature:
                self._attr_target_temperature = 24.0
            
            # Set default fan mode if not already set
            if not self._attr_fan_mode:
                self._attr_fan_mode = "auto"
            
            # v1.10.0: Use helper method for hvac_action calculation
            new_hvac_action = self._calculate_hvac_action()
            self._attr_hvac_action = new_hvac_action
            
            # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
            await self._set_optimistic_state(hvac_mode, new_hvac_action)
            self.async_write_ha_state()
            
            # v1.9.2: Await API call with timeout (fixes #44)
            api_success = False
            try:
                async with asyncio.timeout(10):
                    api_success = await self._async_set_ac_overlay(mode=tado_mode)
            except asyncio.TimeoutError:
                _LOGGER.warning(f"AC TIMEOUT: {self._zone_name} {hvac_mode} mode API call timed out")
            except Exception as e:
                _LOGGER.warning(f"AC ERROR: {self._zone_name} {hvac_mode} mode API call failed ({e})")
            
            if api_success:
                _LOGGER.info(f"AC Set {self._zone_name} to {hvac_mode} mode")
                await self._async_trigger_immediate_refresh("hvac_mode_change")
            else:
                _LOGGER.warning(f"AC ROLLBACK: {self._zone_name} {hvac_mode} mode failed")
                self._attr_hvac_mode = old_mode
                self._attr_target_temperature = old_temp
                self._attr_fan_mode = old_fan
                self._attr_hvac_action = old_action
                self._clear_optimistic_state()
                self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str):
        """Set new fan mode.
        
        v1.9.2: Changed from fire-and-forget to await pattern to fix grey loading state issue (#44).
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        # Optimistic update BEFORE API call
        old_fan = self._attr_fan_mode
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action
        
        self._attr_fan_mode = fan_mode
        
        # If AC is OFF, setting fan mode will turn it ON
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.COOL  # Default mode when turning on via fan
            self._overlay_type = "MANUAL"
        
        # v1.10.0: Use helper method for hvac_action calculation
        new_hvac_action = self._calculate_hvac_action()
        self._attr_hvac_action = new_hvac_action
        
        # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
        await self._set_optimistic_state(self._attr_hvac_mode, new_hvac_action)
        self.async_write_ha_state()
        
        tado_fan = HA_TO_TADO_FAN.get(fan_mode, 'AUTO')
        
        # v1.9.2: Await API call with timeout (fixes #44)
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await self._async_set_ac_overlay(fan_level=tado_fan)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"AC TIMEOUT: {self._zone_name} fan mode change timed out")
        except Exception as e:
            _LOGGER.warning(f"AC ERROR: {self._zone_name} fan mode change failed ({e})")
        
        if api_success:
            _LOGGER.info(f"AC Set {self._zone_name} fan mode to {fan_mode}")
            await self._async_trigger_immediate_refresh("fan_mode_change")
        else:
            _LOGGER.warning(f"AC ROLLBACK: {self._zone_name} fan mode change failed")
            self._attr_fan_mode = old_fan
            self._attr_hvac_mode = old_mode
            self._attr_hvac_action = old_action
            self._clear_optimistic_state()
            self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str):
        """Set new swing mode.
        
        Unified swing dropdown like official Tado integration:
        - off: verticalSwing=OFF, horizontalSwing=OFF
        - vertical: verticalSwing=ON, horizontalSwing=OFF
        - horizontal: verticalSwing=OFF, horizontalSwing=ON
        - both: verticalSwing=ON, horizontalSwing=ON
        
        v1.9.2: Changed from fire-and-forget to await pattern to fix grey loading state issue (#44).
        Service call now awaits API completion (with timeout) for proper HA Frontend state sync.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        await self._check_bootstrap_reserve()
        
        if swing_mode == "off":
            v_swing, h_swing = "OFF", "OFF"
        elif swing_mode == "vertical":
            v_swing, h_swing = "ON", "OFF"
        elif swing_mode == "horizontal":
            v_swing, h_swing = "OFF", "ON"
        elif swing_mode == "both":
            v_swing, h_swing = "ON", "ON"
        else:
            # Fallback for legacy SWING_ON/SWING_OFF
            v_swing = "ON" if swing_mode == SWING_ON else "OFF"
            h_swing = "OFF"
        
        # Optimistic update BEFORE API call
        old_swing = self._attr_swing_mode
        old_mode = self._attr_hvac_mode
        old_action = self._attr_hvac_action
        
        self._attr_swing_mode = swing_mode
        
        # If AC is OFF, setting swing mode will turn it ON
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_mode = HVACMode.COOL  # Default mode when turning on via swing
            self._overlay_type = "MANUAL"
        
        # v1.10.0: Use helper method for hvac_action calculation
        new_hvac_action = self._calculate_hvac_action()
        self._attr_hvac_action = new_hvac_action
        
        # v1.10.0: Use new optimistic state tracking with sequence numbers (Issue #44 fix)
        await self._set_optimistic_state(self._attr_hvac_mode, new_hvac_action)
        self.async_write_ha_state()
        
        # v1.9.2: Await API call with timeout (fixes #44)
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await self._async_set_ac_overlay(vertical_swing=v_swing, horizontal_swing=h_swing)
        except asyncio.TimeoutError:
            _LOGGER.warning(f"AC TIMEOUT: {self._zone_name} swing mode change timed out")
        except Exception as e:
            _LOGGER.warning(f"AC ERROR: {self._zone_name} swing mode change failed ({e})")
        
        if api_success:
            _LOGGER.info(f"AC Set {self._zone_name} swing mode to {swing_mode}")
            await self._async_trigger_immediate_refresh("swing_mode_change")
        else:
            _LOGGER.warning(f"AC ROLLBACK: {self._zone_name} swing mode change failed")
            self._attr_swing_mode = old_swing
            self._attr_hvac_mode = old_mode
            self._attr_hvac_action = old_action
            self._clear_optimistic_state()
            self.async_write_ha_state()
    
    async def _async_trigger_immediate_refresh(self, reason: str):
        """Trigger immediate refresh after state change.
        
        v2.0.1: DRY refactor - delegates to shared async_trigger_immediate_refresh().
        """
        from . import async_trigger_immediate_refresh
        await async_trigger_immediate_refresh(self.hass, self.entity_id, reason)

    async def _async_set_ac_overlay(self, temperature: float = None, mode: str = None, 
                                    fan_level: str = None, vertical_swing: str = None,
                                    horizontal_swing: str = None,
                                    duration_minutes: int = None) -> bool:
        """Set AC overlay with optional parameters.
        
        Uses Tado API v2 format with fanLevel, verticalSwing, horizontalSwing.
        Only sends fields that are supported by the current mode (per capabilities).
        """
        client = get_async_client(self.hass)
        
        # Build setting from current state + changes
        setting = {
            "type": "AIR_CONDITIONING",
            "power": "ON",
        }
        
        # Mode
        if mode:
            setting["mode"] = mode
        elif self._attr_hvac_mode and self._attr_hvac_mode not in (HVACMode.OFF, HVACMode.AUTO):
            setting["mode"] = HA_TO_TADO_HVAC_MODE.get(self._attr_hvac_mode, 'COOL')
        else:
            setting["mode"] = "COOL"
        
        current_mode = setting["mode"]
        
        # Get capabilities for current mode to check what fields are supported
        ac_caps = self._capabilities.get('ac_capabilities') or {}
        mode_caps = ac_caps.get(current_mode) or {}
        
        # Temperature - only send if mode supports it (check capabilities)
        # Some AC units require temperature for DRY mode, others don't
        mode_has_temp = 'temperatures' in mode_caps
        if current_mode != "FAN" and mode_has_temp:
            if temperature:
                setting["temperature"] = {"celsius": temperature}
            elif self._attr_target_temperature:
                setting["temperature"] = {"celsius": self._attr_target_temperature}
            else:
                setting["temperature"] = {"celsius": 24}
        
        # Fan level - only send if mode supports it (DRY mode doesn't have fanLevel)
        if 'fanLevel' in mode_caps:
            if fan_level:
                setting["fanLevel"] = fan_level
            elif self._attr_fan_mode:
                setting["fanLevel"] = HA_TO_TADO_FAN.get(self._attr_fan_mode, 'AUTO')
            else:
                setting["fanLevel"] = "AUTO"
        
        # Swing - only send if mode supports it
        # Use unified swing mode: off/vertical/horizontal/both
        if 'verticalSwing' in mode_caps:
            if vertical_swing is not None:
                setting["verticalSwing"] = vertical_swing
            elif self._attr_swing_mode in ("vertical", "both"):
                setting["verticalSwing"] = "ON"
            else:
                setting["verticalSwing"] = "OFF"
        
        if 'horizontalSwing' in mode_caps:
            if horizontal_swing is not None:
                setting["horizontalSwing"] = horizontal_swing
            elif self._attr_swing_mode in ("horizontal", "both"):
                setting["horizontalSwing"] = "ON"
            else:
                setting["horizontalSwing"] = "OFF"
        
        # Termination
        # v2.0.2: Use TADO_MODE by default to respect per-device settings (Issue #101)
        # Timer-based calls still use TIMER termination
        if duration_minutes:
            termination = {"type": "TIMER", "durationInSeconds": duration_minutes * 60}
        else:
            termination = {"type": "TADO_MODE"}
        
        _LOGGER.debug(f"AC overlay payload: setting={setting}, termination={termination}")
        
        if await client.set_zone_overlay(self._zone_id, setting, termination):
            _LOGGER.info(f"Set AC {self._zone_name}: {setting}")
            return True
        return False

    async def async_set_timer(self, temperature: float, duration_minutes: int, mode: str = None) -> bool:
        """Set AC with timer.
        
        v1.9.2: Added timeout protection for consistency.
        """
        api_success = False
        try:
            async with asyncio.timeout(10):
                api_success = await self._async_set_ac_overlay(
                    temperature=temperature,
                    mode=mode,
                    duration_minutes=duration_minutes
                )
        except asyncio.TimeoutError:
            _LOGGER.warning(f"AC TIMEOUT: {self._zone_name} set_timer API call timed out")
        except Exception as e:
            _LOGGER.warning(f"AC ERROR: {self._zone_name} set_timer API call failed ({e})")
        
        return api_success
    
    def _record_smart_comfort_data(self, ac_power_value: str):
        """Record temperature data for Smart Comfort analytics.
        
        v1.9.0: Records current temperature and AC state to the
        SmartComfortManager for rate calculation and predictions.
        
        For AC zones, "is_heating" means AC is actively running (cooling/heating/etc).
        """
        try:
            smart_comfort_manager = self.hass.data.get(DOMAIN, {}).get('smart_comfort_manager')
            if not smart_comfort_manager or not smart_comfort_manager.is_enabled:
                return
            
            # Only record if we have valid temperature data
            if self._attr_current_temperature is None:
                return
            
            # For AC, "is_heating" means AC is actively running
            is_active = ac_power_value == 'ON'
            
            smart_comfort_manager.record_temperature(
                zone_id=self._zone_id,
                zone_name=self._zone_name,
                temperature=self._attr_current_temperature,
                is_heating=is_active,
                target_temperature=self._attr_target_temperature
            )
        except Exception as e:
            _LOGGER.debug(f"Failed to record smart comfort data for AC {self._zone_name}: {e}")

    async def _check_bootstrap_reserve(self) -> None:
        """Check bootstrap reserve and raise error if quota critically low.
        
        v2.0.1: Bootstrap Reserve - blocks ALL actions (including manual) when quota
        falls to the absolute minimum needed for auto-recovery after API reset.
        
        v2.0.1: DRY refactor - delegates to shared async_check_bootstrap_reserve_or_raise().
        
        Raises:
            HomeAssistantError: If quota is at bootstrap reserve level
        """
        from . import async_check_bootstrap_reserve_or_raise
        await async_check_bootstrap_reserve_or_raise(self.hass, f"AC {self._zone_name}")
