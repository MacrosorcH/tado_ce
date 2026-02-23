"""Tado CE Integration."""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import aiofiles
import aiofiles.os
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, DATA_DIR, CONFIG_FILE, RATELIMIT_FILE,
    MIN_POLLING_INTERVAL, MAX_POLLING_INTERVAL, POLLING_SAFETY_BUFFER,
    QUOTA_RESERVE_CALLS, QUOTA_RESERVE_PERCENT, WINDOW_TYPE_U_VALUES
)
from .config_manager import ConfigurationManager
from .zone_config_manager import ZoneConfigManager
from .async_api import get_async_client

_LOGGER = logging.getLogger(__name__)

# Platform.BUTTON was added in Home Assistant 2021.12
# Platform.SELECT was added in Home Assistant 2021.7
# For backward compatibility, check if it exists
try:
    BASE_PLATFORMS = [Platform.SENSOR, Platform.CLIMATE, Platform.BINARY_SENSOR, Platform.WATER_HEATER, Platform.DEVICE_TRACKER, Platform.SWITCH, Platform.BUTTON, Platform.SELECT, Platform.NUMBER]
    CALENDAR_PLATFORM = Platform.CALENDAR
except AttributeError:
    # Older Home Assistant version without Platform.BUTTON or Platform.SELECT
    BASE_PLATFORMS = [Platform.SENSOR, Platform.CLIMATE, Platform.BINARY_SENSOR, Platform.WATER_HEATER, Platform.DEVICE_TRACKER, Platform.SWITCH]
    CALENDAR_PLATFORM = None
    _LOGGER.debug("Platform.BUTTON/SELECT/NUMBER not available - some entities will not be loaded")

# v1.6.0: Removed SCRIPT_PATH - no longer using subprocess for sync
# Legacy tado_api.py is deprecated but kept for reference

# Service names
SERVICE_SET_CLIMATE_TIMER = "set_climate_timer"
SERVICE_SET_WATER_HEATER_TIMER = "set_water_heater_timer"
SERVICE_RESUME_SCHEDULE = "resume_schedule"
SERVICE_SET_TEMP_OFFSET = "set_climate_temperature_offset"  # Match official Tado integration
SERVICE_GET_TEMP_OFFSET = "get_temperature_offset"  # New: on-demand offset fetch
SERVICE_ADD_METER_READING = "add_meter_reading"
SERVICE_IDENTIFY_DEVICE = "identify_device"
SERVICE_SET_AWAY_CONFIG = "set_away_configuration"

# v1.11.0: Adaptive Smart Polling (removed hardcoded POLLING_INTERVALS table)
# Now uses pure adaptive calculation based on remaining quota and time until reset


def _get_calls_per_sync(config_manager: ConfigurationManager) -> int:
    """Calculate API calls per sync based on enabled features.
    
    v1.11.0: Helper for adaptive polling calculation.
    
    Args:
        config_manager: Configuration manager with feature settings
        
    Returns:
        Number of API calls per sync cycle
    """
    calls = 1  # Base: zoneStates API call
    
    if config_manager.get_weather_enabled():
        calls += 1  # weather API call
    
    if (config_manager.get_mobile_devices_enabled() and 
        config_manager.get_mobile_devices_frequent_sync()):
        calls += 1  # mobileDevices API call
    
    return calls


def _calculate_adaptive_interval(ratelimit_data: dict, config_manager: ConfigurationManager) -> int:
    """Calculate adaptive polling interval based on remaining quota, Day/Night period, and Reset Time.
    
    v1.11.0: Pure adaptive polling - distributes remaining calls over remaining time.
    Works universally for ANY quota tier (100, 5000, 20000, etc.)
    
    v2.0.1: Simplified - reads directly from ratelimit_data which already contains
    simulated values when Test Mode is ON (Single Source of Truth in ratelimit.json).
    
    v2.0.1: Day/Night aware adaptive polling:
    - Night period: Fixed MAX_POLLING_INTERVAL (120 min) to conserve quota
    - Day period: Adaptive based on remaining quota after reserving Night calls
    - Respects existing quota protection (SAFETY_BUFFER, RESERVE_CALLS)
    - Considers Reset Time: if reset is soon, use quota more aggressively
    
    Args:
        ratelimit_data: Rate limit data with 'remaining', 'reset_seconds', 'last_reset_utc'
                        (already simulated when Test Mode is ON)
        config_manager: Configuration manager for feature settings
        
    Returns:
        Polling interval in minutes (constrained by MIN/MAX)
    """
    from homeassistant.util import dt as dt_util
    
    # v2.0.1: Read directly from ratelimit_data (already simulated when Test Mode ON)
    remaining = ratelimit_data.get("remaining", 100)
    test_mode = ratelimit_data.get("test_mode", False)
    
    # v2.0.1: Get reset time info
    reset_seconds = ratelimit_data.get("reset_seconds", 86400)
    last_reset_utc = ratelimit_data.get("last_reset_utc")
    
    # v2.1.1 FIX: Only recalculate reset_seconds from last_reset_utc in LIVE mode
    # In Test Mode, reset_seconds is already correctly calculated from test_mode_start_time
    # Recalculating from last_reset_utc (which is Live mode's reset) causes wrong intervals
    # Issue #120: Test Mode polling stuck because of this mismatch
    if not test_mode and last_reset_utc:
        try:
            last_reset = datetime.fromisoformat(last_reset_utc.replace('Z', '+00:00'))
            if last_reset.tzinfo is None:
                last_reset = last_reset.replace(tzinfo=timezone.utc)
            
            next_reset = last_reset + timedelta(hours=24)
            now_utc = datetime.now(timezone.utc)
            
            # If next_reset is in the past, add 24h until it's in the future
            while next_reset <= now_utc:
                next_reset += timedelta(hours=24)
            
            calculated_reset_seconds = int((next_reset - now_utc).total_seconds())
            if calculated_reset_seconds > 0:
                reset_seconds = calculated_reset_seconds
        except Exception as e:
            _LOGGER.debug(f"Failed to calculate dynamic reset_seconds: {e}")
    
    reset_hours = reset_seconds / 3600
    
    if test_mode:
        _LOGGER.debug(
            f"Tado CE: Test Mode - using simulated remaining={remaining} from ratelimit.json"
        )
    
    # Account for optional features (weather, mobile devices)
    calls_per_sync = _get_calls_per_sync(config_manager)
    effective_remaining = remaining / calls_per_sync
    
    # Safety check: if no remaining quota, use max interval
    if effective_remaining <= 0:
        _LOGGER.debug(
            f"Tado CE: No remaining quota (effective_remaining={effective_remaining}). "
            f"Using max interval: {MAX_POLLING_INTERVAL} min"
        )
        return MAX_POLLING_INTERVAL
    
    # v2.0.1: Day/Night aware adaptive polling with Reset Time consideration
    # Get current time and Day/Night settings
    now = dt_util.now()
    current_hour = now.hour
    day_start = config_manager.get_day_start_hour()
    night_start = config_manager.get_night_start_hour()
    
    # Check if currently in Day or Night period
    is_day = is_daytime(config_manager)
    
    # Calculate usable quota after safety buffer and reserve
    usable_quota = effective_remaining * POLLING_SAFETY_BUFFER - QUOTA_RESERVE_CALLS
    
    # v2.0.3 FIX: Handle Uniform Mode (day_start == night_start) - Issue #99
    # In Uniform Mode, there's no Day/Night distinction, so use full reset_hours
    # and don't reserve any quota for Night period
    if day_start == night_start:
        # Uniform Mode - no Day/Night distinction
        effective_hours = reset_hours
        night_calls_needed = 0
        time_boundary = f"Reset ({reset_hours:.1f}h)"
        
        day_quota = max(0, usable_quota - night_calls_needed)
        
        if day_quota <= 0 or effective_hours <= 0:
            _LOGGER.debug(
                f"Tado CE: No quota available (day_quota={day_quota:.1f}, "
                f"effective_hours={effective_hours:.1f}). Using max interval."
            )
            return MAX_POLLING_INTERVAL
        
        # Calculate interval for Uniform Mode
        effective_minutes = effective_hours * 60
        interval_minutes = effective_minutes / day_quota
        
        # Apply constraints (min 5, max 120)
        interval_minutes = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, interval_minutes)))
        
        _LOGGER.debug(
            f"Tado CE Adaptive Polling (Uniform Mode):\n"
            f"  Period: Uniform (Day Start = Night Start = {day_start})\n"
            f"  Effective hours: {effective_hours:.1f}h (until {time_boundary})\n"
            f"  Remaining: {remaining} calls (effective: {effective_remaining:.0f})\n"
            f"  Usable quota: {usable_quota:.0f}\n"
            f"  Calculated: {effective_minutes / day_quota:.1f} min → Adaptive: {interval_minutes} min\n"
            f"  Reset in: {reset_hours:.1f}h | Test Mode: {test_mode}"
        )
        
        return interval_minutes
    
    # Normal Day/Night Mode calculation
    # Calculate hours until Night Start (for Day period)
    if is_day:
        if current_hour < night_start:
            hours_until_night = night_start - current_hour
        else:
            # current_hour >= night_start means we're past night_start today
            # This shouldn't happen if is_day is True, but handle edge case
            hours_until_night = 24 - current_hour + night_start
    else:
        hours_until_night = 0
    
    # Calculate Night duration (for quota reservation)
    if night_start > day_start:
        night_duration = 24 - night_start + day_start
    else:
        night_duration = day_start - night_start
    
    # v2.0.1: Key insight - if Reset Time is before Night Start, we don't need to reserve Night quota!
    # Because quota will reset and we'll have fresh quota for Night.
    
    # v2.2.0 FIX: Night period returns None to signal "use default/custom night interval" (#126)
    # Previously returned MAX_POLLING_INTERVAL which incorrectly overrode user's custom night interval
    if not is_day:
        _LOGGER.debug(
            f"Tado CE Adaptive Polling (Night):\n"
            f"  Period: Night (until {day_start:02d}:00)\n"
            f"  Reset in: {reset_hours:.1f}h\n"
            f"  Remaining: {remaining} calls\n"
            f"  Returning None (use default/custom night interval)\n"
            f"  Test Mode: {test_mode}"
        )
        return None  # Signal to use default/custom night interval
    
    # Day period: calculate adaptive interval
    # Determine effective time window (until Reset or Night Start, whichever is sooner)
    if reset_hours < hours_until_night:
        # Reset is before Night Start - use all quota until reset, no need to reserve for Night
        effective_hours = reset_hours
        night_calls_needed = 0
        time_boundary = f"Reset ({reset_hours:.1f}h)"
    else:
        # Night Start is before Reset - need to reserve quota for Night
        effective_hours = hours_until_night
        night_calls_needed = (night_duration * 60) / MAX_POLLING_INTERVAL
        time_boundary = f"Night Start ({hours_until_night}h)"
    
    day_quota = max(0, usable_quota - night_calls_needed)
    
    if day_quota <= 0 or effective_hours <= 0:
        _LOGGER.debug(
            f"Tado CE: No Day quota available (day_quota={day_quota:.1f}, "
            f"effective_hours={effective_hours:.1f}). Using max interval."
        )
        return MAX_POLLING_INTERVAL
    
    # Calculate Day interval
    effective_minutes = effective_hours * 60
    interval_minutes = effective_minutes / day_quota
    
    # Apply constraints (min 5, max 120)
    interval_minutes = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, interval_minutes)))
    
    # Log adaptive calculation
    _LOGGER.debug(
        f"Tado CE Adaptive Polling (Day):\n"
        f"  Period: Day (until {time_boundary})\n"
        f"  Effective hours: {effective_hours:.1f}h\n"
        f"  Night reserved: {night_calls_needed:.1f} calls\n"
        f"  Remaining: {remaining} calls (effective: {effective_remaining:.0f})\n"
        f"  Usable quota: {usable_quota:.0f} → Day quota: {day_quota:.0f}\n"
        f"  Calculated: {effective_minutes / day_quota:.1f} min → Adaptive: {interval_minutes} min\n"
        f"  Reset in: {reset_hours:.1f}h | Test Mode: {test_mode}"
    )
    
    # Log at DEBUG level if quota is very low
    if remaining < 10:
        _LOGGER.debug(
            f"Tado CE: Low quota ({remaining} remaining). "
            f"Using interval: {interval_minutes} min"
        )
    
    return interval_minutes


def should_pause_polling(ratelimit_data: dict, config_manager: ConfigurationManager) -> tuple[bool, str]:
    """Check if polling should be paused to reserve quota for manual operations.
    
    v2.0.0: Quota Reserve Protection - pauses polling when quota is critically low
    to ensure users can still perform manual operations (set temperature, etc.)
    
    v2.0.1: Added reset time check - if reset time has passed, resume polling
    to detect the actual reset from API headers.
    
    v2.0.1: Simplified - reads directly from ratelimit_data which already contains
    simulated values when Test Mode is ON (Single Source of Truth in ratelimit.json).
    
    v2.0.1: Added quota_reserve_enabled check - allows users to disable protection.
    
    Args:
        ratelimit_data: Rate limit data with 'remaining', 'used', 'reset_seconds'
                        (already simulated when Test Mode is ON)
        config_manager: Configuration manager for feature settings
        
    Returns:
        Tuple of (should_pause: bool, reason: str)
        - should_pause: True if polling should be paused
        - reason: Human-readable explanation (empty if not pausing)
    """
    # v2.0.1: Check if Quota Reserve Protection is enabled
    if not config_manager.get_quota_reserve_enabled():
        _LOGGER.debug("Tado CE: Quota Reserve Protection disabled, not pausing polling")
        return False, ""
    
    test_mode = ratelimit_data.get("test_mode", False)
    _LOGGER.debug(
        f"Tado CE: should_pause_polling called with "
        f"used={ratelimit_data.get('used')}, remaining={ratelimit_data.get('remaining')}, "
        f"test_mode={test_mode}"
    )
    
    # v2.0.1: Check if reset time has passed - if so, resume polling to detect reset
    last_reset_utc = ratelimit_data.get("last_reset_utc")
    if last_reset_utc:
        try:
            last_reset = datetime.fromisoformat(last_reset_utc.replace('Z', '+00:00'))
            next_reset = last_reset + timedelta(hours=24)
            now_utc = datetime.now(timezone.utc)
            
            # If next reset time has passed, resume polling to detect actual reset
            if now_utc >= next_reset:
                _LOGGER.info(
                    f"Tado CE: Reset time has passed (expected {next_reset.strftime('%H:%M')} UTC). "
                    f"Resuming polling to detect actual reset."
                )
                return False, ""
        except Exception as e:
            _LOGGER.debug(f"Failed to check reset time: {e}")
    
    # v2.0.1: Read directly from ratelimit_data (already simulated when Test Mode ON)
    # No need to recalculate - save_ratelimit() stores the correct values
    remaining = ratelimit_data.get("remaining", 100)
    daily_limit = ratelimit_data.get("limit", 100)
    
    # Calculate reserve threshold: max of absolute minimum or percentage
    reserve_threshold = max(QUOTA_RESERVE_CALLS, int(daily_limit * QUOTA_RESERVE_PERCENT))
    
    _LOGGER.debug(
        f"Tado CE: should_pause_polling check - "
        f"remaining={remaining}, limit={daily_limit}, threshold={reserve_threshold}, "
        f"should_pause={remaining <= reserve_threshold}"
    )
    
    # Check if we should pause
    if remaining <= reserve_threshold:
        reset_seconds = ratelimit_data.get("reset_seconds", 0)
        hours = reset_seconds // 3600
        minutes = (reset_seconds % 3600) // 60
        
        reason = (
            f"Quota critically low ({remaining} remaining, reserve threshold={reserve_threshold}). "
            f"Polling paused until reset in {hours}h {minutes}m. "
            f"Manual operations (set temperature, etc.) still available."
        )
        return True, reason
    
    return False, ""


def should_block_manual_action(ratelimit_data: dict, config_manager: ConfigurationManager) -> tuple[bool, str]:
    """Check if manual actions should be blocked due to bootstrap reserve.
    
    v2.0.1: Bootstrap Reserve - blocks ALL actions (including manual) when quota
    falls to the absolute minimum needed for auto-recovery after API reset.
    
    v2.0.1: Simplified - reads directly from ratelimit_data which already contains
    simulated values when Test Mode is ON (Single Source of Truth in ratelimit.json).
    
    v2.0.1: Added quota_reserve_enabled check - allows users to disable protection.
    
    Args:
        ratelimit_data: Rate limit data with 'remaining', 'used', 'reset_seconds'
                        (already simulated when Test Mode is ON)
        config_manager: Configuration manager for feature settings
        
    Returns:
        Tuple of (should_block: bool, reason: str)
        - should_block: True if manual actions should be blocked
        - reason: Human-readable explanation (empty if not blocking)
    """
    from .const import QUOTA_BOOTSTRAP_CALLS
    
    # v2.0.1: Check if Quota Reserve Protection is enabled
    if not config_manager.get_quota_reserve_enabled():
        _LOGGER.debug("Tado CE: Quota Reserve Protection disabled, not blocking manual actions")
        return False, ""
    
    # v2.0.1: Check if reset time has passed - if so, allow actions to detect reset
    last_reset_utc = ratelimit_data.get("last_reset_utc")
    if last_reset_utc:
        try:
            last_reset = datetime.fromisoformat(last_reset_utc.replace('Z', '+00:00'))
            next_reset = last_reset + timedelta(hours=24)
            now_utc = datetime.now(timezone.utc)
            
            # If next reset time has passed, allow actions to detect actual reset
            if now_utc >= next_reset:
                return False, ""
        except Exception as e:
            _LOGGER.debug(f"Failed to check reset time: {e}")
    
    # v2.0.1: Read directly from ratelimit_data (already simulated when Test Mode ON)
    # No need to recalculate - save_ratelimit() stores the correct values
    remaining = ratelimit_data.get("remaining", 100)
    test_mode = ratelimit_data.get("test_mode", False)
    
    _LOGGER.debug(
        f"Tado CE: should_block_manual_action check - "
        f"remaining={remaining}, bootstrap_threshold={QUOTA_BOOTSTRAP_CALLS}, "
        f"test_mode={test_mode}"
    )
    
    # Check if we've hit the bootstrap reserve (hard limit)
    if remaining <= QUOTA_BOOTSTRAP_CALLS:
        reset_seconds = ratelimit_data.get("reset_seconds", 0)
        hours = reset_seconds // 3600
        minutes = (reset_seconds % 3600) // 60
        
        reason = (
            f"API limit reached ({remaining} calls remaining). "
            f"All actions blocked to preserve auto-recovery capability. "
            f"Use the Tado app for emergency changes. "
            f"Integration will auto-recover at reset in {hours}h {minutes}m."
        )
        return True, reason
    
    return False, ""


async def async_check_bootstrap_reserve(hass: HomeAssistant) -> tuple[bool, str]:
    """Async helper to check bootstrap reserve for service handlers.
    
    v2.0.1: Convenience wrapper that loads ratelimit data and config manager.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        Tuple of (should_block: bool, reason: str)
    """
    from .data_loader import load_ratelimit_file
    
    try:
        config_manager = hass.data.get(DOMAIN, {}).get('config_manager')
        if not config_manager:
            return False, ""
        
        ratelimit_data = await hass.async_add_executor_job(load_ratelimit_file)
        if not ratelimit_data:
            return False, ""
        
        return should_block_manual_action(ratelimit_data, config_manager)
    except Exception as e:
        _LOGGER.debug(f"Failed to check bootstrap reserve: {e}")
        return False, ""


async def async_show_api_limit_notification(hass: HomeAssistant, message: str) -> None:
    """Show a persistent notification when API limit is reached.
    
    v2.0.1: Persistent notification to inform user about API limit.
    
    Args:
        hass: Home Assistant instance
        message: Notification message
    """
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "Tado CE: API Limit Reached",
            "message": message + "\n\n**Tip:** Use the official Tado app for emergency temperature changes.",
            "notification_id": "tado_ce_api_limit",
        },
    )


async def async_check_bootstrap_reserve_or_raise(hass: HomeAssistant, entity_name: str = "") -> None:
    """Check bootstrap reserve and raise HomeAssistantError if quota critically low.
    
    v2.0.1: DRY refactor - single shared function for all entities to check bootstrap reserve.
    Consolidates duplicate _check_bootstrap_reserve() methods across climate, water_heater,
    button, and switch entities.
    
    Args:
        hass: Home Assistant instance
        entity_name: Optional entity name for logging (e.g., "Living Room", "Hot Water")
        
    Raises:
        HomeAssistantError: If quota is at bootstrap reserve level
    """
    from homeassistant.exceptions import HomeAssistantError
    
    should_block, reason = await async_check_bootstrap_reserve(hass)
    if should_block:
        log_name = f" for {entity_name}" if entity_name else ""
        _LOGGER.warning(f"Tado CE: Blocking manual action{log_name} - {reason}")
        await async_show_api_limit_notification(hass, reason)
        raise HomeAssistantError(reason)


async def async_trigger_immediate_refresh(
    hass: HomeAssistant, 
    entity_id: str, 
    reason: str,
    force: bool = False,
    skip_debounce: bool = False,
    include_home_state: bool = False
) -> None:
    """Trigger immediate refresh after state change.
    
    v2.0.1: DRY refactor - single shared function for all entities to trigger refresh.
    Consolidates duplicate _async_trigger_immediate_refresh() methods across climate,
    water_heater, switch, and button entities.
    
    v2.0.2: Added include_home_state parameter for presence mode changes.
    
    Args:
        hass: Home Assistant instance
        entity_id: Entity ID that triggered the refresh
        reason: Reason for the refresh (for logging)
        force: If True, force refresh even if recently refreshed (for buttons)
        skip_debounce: If True, skip debounce delay (for buttons)
        include_home_state: If True, also fetch home state (for presence mode changes)
    """
    try:
        from .immediate_refresh_handler import get_handler
        handler = get_handler(hass)
        await handler.trigger_refresh(entity_id, reason, force=force, skip_debounce=skip_debounce, include_home_state=include_home_state)
    except Exception as e:
        _LOGGER.warning(f"Failed to trigger immediate refresh: {e}")


def get_optimistic_window(hass: HomeAssistant) -> float:
    """Get the optimistic update window duration in seconds.
    
    v2.0.1: DRY refactor - single shared function for all entities to get optimistic window.
    Consolidates duplicate _get_optimistic_window() methods across climate, water_heater,
    and switch entities.
    
    The optimistic window = debounce_seconds + 2.0 seconds buffer.
    During this window, entities ignore API updates to preserve optimistic state.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        Optimistic window duration in seconds (default: 17.0 = 15 + 2)
    """
    try:
        config_manager = hass.data.get(DOMAIN, {}).get('config_manager')
        if config_manager:
            return float(config_manager.get_refresh_debounce_seconds()) + 2.0
    except Exception:
        pass
    return 17.0  # Default: 15s debounce + 2s buffer


def get_overlay_termination(hass: HomeAssistant) -> dict:
    """Get the termination dict for overlay API calls.
    
    v2.0.2: Issue #101 - Configurable overlay mode (@leoogermenia).
    
    Reads from hass.data cache (no file I/O) to avoid blocking.
    Cache is populated during async_setup_entry.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        {"type": "TADO_MODE"} or {"type": "MANUAL"} or {"type": "TIMER", "durationInSeconds": ...}
        Note: Tado API only accepts MANUAL, TADO_MODE, TIMER (not NEXT_TIME_BLOCK)
    """
    mode = hass.data.get(DOMAIN, {}).get('overlay_mode', 'TADO_MODE')
    # Map internal storage values to API-accepted values
    # Tado API only accepts: MANUAL, TADO_MODE, TIMER
    if mode == "NEXT_TIME_BLOCK":
        mode = "TADO_MODE"
    
    # v2.1.0: Handle TIMER mode with global timer_duration
    if mode == "TIMER":
        duration = hass.data.get(DOMAIN, {}).get('timer_duration', 60)
        return {"type": "TIMER", "durationInSeconds": duration * 60}
    
    return {"type": mode}


def get_zone_overlay_termination(hass: HomeAssistant, zone_id: str) -> dict:
    """Get the termination dict for overlay API calls with per-zone support.
    
    v2.1.0: Per-zone overlay mode support.
    
    Priority:
    1. Per-zone overlay_mode (if zone_config_manager available and zone has override)
    2. Global overlay_mode (from hass.data cache)
    
    Args:
        hass: Home Assistant instance
        zone_id: Zone ID to get overlay mode for
        
    Returns:
        {"type": "..."} or {"type": "...", "durationInSeconds": ...} for Timer mode
    """
    zone_config_manager = hass.data.get(DOMAIN, {}).get('zone_config_manager')
    
    if zone_config_manager:
        # Get per-zone overlay mode (UPPERCASE values)
        zone_mode = zone_config_manager.get_zone_value(zone_id, "overlay_mode", None)
        
        if zone_mode and zone_mode != "TADO_MODE":
            # Map to API values
            # Note: Tado API only accepts MANUAL, TADO_MODE, TIMER
            # NEXT_TIME_BLOCK maps to TADO_MODE which follows device settings
            mode_map = {
                "NEXT_TIME_BLOCK": "TADO_MODE",  # API doesn't accept NEXT_TIME_BLOCK
                "TIMER": "TIMER",
                "MANUAL": "MANUAL",
            }
            api_mode = mode_map.get(zone_mode, "TADO_MODE")
            
            # Handle Timer mode with duration
            if api_mode == "TIMER":
                duration = zone_config_manager.get_zone_value(zone_id, "timer_duration", 60)
                return {"type": "TIMER", "durationInSeconds": duration * 60}
            
            return {"type": api_mode}
    
    # Fallback to global overlay mode (handles TADO_MODE and when no per-zone config)
    return get_overlay_termination(hass)


async def async_dismiss_api_limit_notification(hass: HomeAssistant) -> None:
    """Dismiss the API limit notification when quota is restored.
    
    v2.0.1: Called when API reset is detected.
    
    Args:
        hass: Home Assistant instance
    """
    try:
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {
                "notification_id": "tado_ce_api_limit",
            },
        )
    except Exception:
        pass  # Notification may not exist


async def async_detect_reset_from_history(hass: HomeAssistant) -> datetime | None:
    """Detect API reset time from Home Assistant sensor history.
    
    Queries the recorder for sensor.tado_ce_api_usage history and finds
    the time when the value dropped to its minimum (reset point).
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        Estimated reset time (datetime in UTC), or None if not enough data
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
        from homeassistant.util import dt as dt_util
        
        # Query last 36 hours of history (to catch reset even if it was yesterday)
        end_time = dt_util.utcnow()
        start_time = end_time - timedelta(hours=36)
        
        entity_id = "sensor.tado_ce_api_usage"
        
        # Get history from recorder
        def _get_history():
            return get_significant_states(
                hass,
                start_time,
                end_time,
                [entity_id],
                significant_changes_only=False
            )
        
        states = await get_instance(hass).async_add_executor_job(_get_history)
        
        if not states or entity_id not in states:
            _LOGGER.debug("HA History Detection: No history found for sensor.tado_ce_api_usage")
            return None
        
        history = states[entity_id]
        if len(history) < 10:
            _LOGGER.debug(f"HA History Detection: Not enough history points ({len(history)})")
            return None
        
        # Parse states and find minimum value (reset point)
        # The reset is when value drops from high to low
        min_value = float('inf')
        min_time = None
        prev_value = None
        
        for state in history:
            try:
                value = int(state.state)
                state_time = state.last_changed
                
                # Detect reset: value dropped significantly (>50% drop or to <10)
                if prev_value is not None and prev_value > 50:
                    if value < prev_value * 0.2 or value < 10:
                        # This is likely the reset point
                        _LOGGER.debug(
                            f"HA History Detection: Reset detected! {prev_value} -> {value} at {state_time}"
                        )
                        return state_time.replace(tzinfo=timezone.utc) if state_time.tzinfo is None else state_time
                
                # Track minimum as fallback
                if value < min_value:
                    min_value = value
                    min_time = state_time
                
                prev_value = value
                
            except (ValueError, TypeError):
                continue
        
        # If no clear reset detected, use minimum value time
        if min_time and min_value < 20:
            _LOGGER.debug(f"HA History Detection: Using minimum value as reset: {min_value} at {min_time}")
            return min_time.replace(tzinfo=timezone.utc) if min_time.tzinfo is None else min_time
        
        _LOGGER.debug(f"HA History Detection: Could not detect reset (min_value={min_value})")
        return None
        
    except ImportError:
        _LOGGER.debug("Recorder component not available")
        return None
    except Exception as e:
        _LOGGER.debug(f"Failed to detect reset from history: {e}")
        return None


async def _update_ratelimit_reset_time(hass: HomeAssistant, detected_reset: datetime) -> None:
    """Update ratelimit.json with detected reset time from HA history.
    
    This is called after sync when we detect the actual reset time from
    sensor.tado_ce_api_usage history. It's more accurate than extrapolation.
    
    Args:
        hass: Home Assistant instance
        detected_reset: Detected reset time (datetime in UTC)
    """
    try:
        if not await aiofiles.os.path.exists(RATELIMIT_FILE):
            return
        
        async with aiofiles.open(RATELIMIT_FILE, 'r') as f:
            content = await f.read()
            data = json.loads(content)
        
        # Only update if detected time is different from stored time
        current_reset = data.get("last_reset_utc")
        new_reset = detected_reset.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        if current_reset != new_reset:
            data["last_reset_utc"] = new_reset
            
            # Recalculate reset_seconds, reset_at, reset_human
            now_utc = datetime.now(timezone.utc)
            next_reset = detected_reset + timedelta(hours=24)
            
            # If next_reset is in the past, add another 24h
            while next_reset <= now_utc:
                next_reset += timedelta(hours=24)
            
            seconds_until_reset = int((next_reset - now_utc).total_seconds())
            
            if seconds_until_reset > 0:
                hours = seconds_until_reset // 3600
                minutes = (seconds_until_reset % 3600) // 60
                data["reset_seconds"] = seconds_until_reset
                data["reset_at"] = next_reset.isoformat()
                data["reset_human"] = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            
            # Write back with atomic write
            temp_path = RATELIMIT_FILE.with_suffix('.tmp')
            async with aiofiles.open(temp_path, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            
            await aiofiles.os.replace(temp_path, RATELIMIT_FILE)
            _LOGGER.info(
                f"Updated reset time from HA history: {detected_reset.strftime('%H:%M')} UTC"
            )
        
    except Exception as e:
        _LOGGER.debug(f"Failed to update ratelimit reset time: {e}")


DEFAULT_DAY_INTERVAL = 30
DEFAULT_NIGHT_INTERVAL = 120
FULL_SYNC_INTERVAL_HOURS = 6


def is_daytime(config_manager: ConfigurationManager) -> bool:
    """Check if current time is daytime based on configured hours.
    
    Args:
        config_manager: Configuration manager with day/night hour settings
        
    Returns:
        True if current time is within day hours, False otherwise
        
    Note:
        If day_start == night_start, returns True (uniform mode - always day polling)
        
    v1.6.1: Uses Home Assistant's timezone instead of system timezone
    v2.2.0: Fixed wrap-around case when night_start < day_start (#126)
    """
    from homeassistant.util import dt as dt_util
    
    # Use HA's timezone-aware current time
    now = dt_util.now()
    hour = now.hour
    
    day_start = config_manager.get_day_start_hour()
    night_start = config_manager.get_night_start_hour()
    
    # Uniform mode: if day_start == night_start, always use day interval
    if day_start == night_start:
        return True
    
    # v2.2.0 FIX: Handle wrap-around case (#126)
    # Normal case: day_start < night_start (e.g., day=6, night=22)
    if day_start < night_start:
        return day_start <= hour < night_start
    
    # Wrap-around case: night_start < day_start (e.g., night=1, day=6)
    # Day is from day_start to 24 OR from 0 to night_start
    return hour >= day_start or hour < night_start


def get_polling_interval(config_manager: ConfigurationManager, cached_ratelimit: dict | None = None) -> int:
    """Get polling interval based on configuration and API rate limit.
    
    v1.11.0: Uses adaptive polling based on remaining quota and time until reset.
    Custom intervals are treated as targets, but adaptive polling can override if quota is low.
    
    v2.0.1: Day/Night aware adaptive polling - always use adaptive interval when available.
    Custom intervals are only used as override when explicitly set by user.
    
    Args:
        config_manager: Configuration manager with polling settings
        cached_ratelimit: Pre-loaded ratelimit data (to avoid blocking I/O in async context)
        
    Returns:
        Polling interval in minutes
    """
    daytime = is_daytime(config_manager)
    
    # v2.0.1: Check if user has explicitly set custom intervals
    # Only use custom interval if user explicitly configured it (not default)
    custom_day_interval = config_manager.get_custom_day_interval()
    custom_night_interval = config_manager.get_custom_night_interval()
    
    user_set_custom = False
    custom_interval = None
    if daytime and custom_day_interval is not None:
        custom_interval = custom_day_interval
        user_set_custom = True
    elif not daytime and custom_night_interval is not None:
        custom_interval = custom_night_interval
        user_set_custom = True
    
    # Calculate adaptive interval based on remaining quota
    adaptive_interval = None
    try:
        ratelimit_data = None
        
        if cached_ratelimit is not None:
            # Use pre-loaded data (async-safe)
            ratelimit_data = cached_ratelimit
        else:
            # Use data_loader for per-home file support
            from .data_loader import load_ratelimit_file
            ratelimit_data = load_ratelimit_file()
        
        if ratelimit_data:
            adaptive_interval = _calculate_adaptive_interval(ratelimit_data, config_manager)
            
    except Exception as e:
        _LOGGER.debug(f"Could not calculate adaptive polling interval, using default: {e}")
    
    # v2.1.0: Decision logic - respect user custom override for high-quota users
    # Issue #107: Custom intervals below 5 min were being ignored because adaptive
    # interval is clamped to MIN_POLLING_INTERVAL (5 min) by default.
    # Fix: When user explicitly sets custom interval, use it directly unless
    # quota is actually insufficient (not just because of MIN_POLLING_INTERVAL clamp).
    if user_set_custom and custom_interval is not None:
        # User explicitly set custom interval - check if quota is actually sufficient
        if adaptive_interval is not None:
            # Calculate what the "raw" adaptive interval would be without MIN_POLLING_INTERVAL clamp
            # If adaptive > custom AND adaptive > MIN_POLLING_INTERVAL, quota is truly insufficient
            if adaptive_interval > custom_interval and adaptive_interval > MIN_POLLING_INTERVAL:
                _LOGGER.warning(
                    f"Tado CE: Custom interval ({custom_interval} min) would exceed quota. "
                    f"Using adaptive interval ({adaptive_interval} min) to protect remaining calls."
                )
                return adaptive_interval
        # Custom interval is safe (or no ratelimit data), use it
        _LOGGER.info(
            f"Tado CE: Using custom {'day' if daytime else 'night'} interval: {custom_interval} min"
        )
        return custom_interval
    elif adaptive_interval is not None:
        # No custom interval set - use pure adaptive (Day/Night aware)
        return adaptive_interval
    else:
        # Fallback to default intervals
        return DEFAULT_DAY_INTERVAL if daytime else DEFAULT_NIGHT_INTERVAL


def _log_quota_warning_if_needed(interval: int, daytime: bool, config_manager: ConfigurationManager):
    """Log warning if custom interval would exceed API quota.
    
    Args:
        interval: Custom polling interval in minutes
        daytime: Whether it's currently daytime
        config_manager: Configuration manager
    """
    # Calculate calls per day with this interval
    # Assuming 2-3 API calls per sync (zoneStates + weather if enabled)
    weather_enabled = config_manager.get_weather_enabled()
    calls_per_sync = 2 if weather_enabled else 1
    
    # Get both intervals to calculate total daily calls
    day_interval = config_manager.get_custom_day_interval() or DEFAULT_DAY_INTERVAL
    night_interval = config_manager.get_custom_night_interval() or DEFAULT_NIGHT_INTERVAL
    
    # Assume 16 hours day, 8 hours night (based on default 7am-11pm)
    day_hours = 16
    night_hours = 8
    
    day_syncs = (day_hours * 60) / day_interval
    night_syncs = (night_hours * 60) / night_interval
    total_calls = (day_syncs + night_syncs) * calls_per_sync
    
    # Warn if exceeding low-tier quota (100 calls/day)
    low_tier_quota = 100
    if total_calls > low_tier_quota:
        _LOGGER.warning(
            f"Tado CE: Custom polling intervals may exceed API quota for 100-call tier. "
            f"Estimated {total_calls:.0f} calls/day with day={day_interval}m, night={night_interval}m. "
            f"Consider increasing intervals or check if you have a higher quota tier (5000/20000)."
        )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tado CE component."""
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new version.
    
    v1.5.3: Added comprehensive debug logging for upgrade troubleshooting.
    If upgrade fails, users can share logs to help diagnose issues.
    
    v1.6.0: Fixed cumulative migration - uses `< X` pattern instead of `== X`
    to ensure users jumping multiple versions (e.g., v1 -> v5) run ALL
    intermediate migrations correctly.
    """
    # Store initial version for logging (version may change during migration)
    # Handle None version (can happen if previous migration failed mid-way)
    initial_version = config_entry.version
    if initial_version is None:
        _LOGGER.warning(
            "Config entry version is None (possibly from failed migration). "
            "Treating as version 1 to run all migrations."
        )
        initial_version = 1
    
    _LOGGER.info(
        "=== Tado CE Migration Start ===\n"
        f"  Current version: {initial_version}\n"
        f"  Target version: 9\n"
        f"  Entry ID: {config_entry.entry_id}\n"
        f"  Entry data: {config_entry.data}"
    )
    
    # Log file system state for debugging
    from .const import LEGACY_DATA_DIR, ZONES_INFO_FILE
    _LOGGER.info(
        "=== File System State ===\n"
        f"  DATA_DIR exists: {DATA_DIR.exists()}\n"
        f"  DATA_DIR path: {DATA_DIR}\n"
        f"  LEGACY_DATA_DIR exists: {LEGACY_DATA_DIR.exists()}\n"
        f"  LEGACY_DATA_DIR path: {LEGACY_DATA_DIR}\n"
        f"  CONFIG_FILE exists: {CONFIG_FILE.exists()}\n"
        f"  CONFIG_FILE path: {CONFIG_FILE}"
    )
    
    # List files in both directories for debugging
    if DATA_DIR.exists():
        try:
            files = list(DATA_DIR.glob("*.json"))
            _LOGGER.info(f"  DATA_DIR files: {[f.name for f in files]}")
        except Exception as e:
            _LOGGER.warning(f"  Could not list DATA_DIR files: {e}")
    
    if LEGACY_DATA_DIR.exists():
        try:
            files = list(LEGACY_DATA_DIR.glob("*.json"))
            _LOGGER.info(f"  LEGACY_DATA_DIR files: {[f.name for f in files]}")
        except Exception as e:
            _LOGGER.warning(f"  Could not list LEGACY_DATA_DIR files: {e}")
    
    # v1.5.2: Migrate data directory from custom_components/tado_ce/data/ to .storage/tado_ce/
    if LEGACY_DATA_DIR.exists() and not DATA_DIR.exists():
        _LOGGER.info("=== Data Directory Migration ===")
        _LOGGER.info("Migrating data directory from legacy location to .storage/tado_ce/")
        import shutil
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _LOGGER.info(f"  Created DATA_DIR: {DATA_DIR}")
        except Exception as e:
            _LOGGER.error(f"  Failed to create DATA_DIR: {e}")
            return False
        
        migrated_files = []
        failed_files = []
        for file in LEGACY_DATA_DIR.glob("*.json"):
            try:
                shutil.copy2(file, DATA_DIR / file.name)
                migrated_files.append(file.name)
                _LOGGER.info(f"  Migrated {file.name}")
            except Exception as e:
                failed_files.append((file.name, str(e)))
                _LOGGER.error(f"  Failed to migrate {file.name}: {e}")
        
        _LOGGER.info(f"  Migrated files: {migrated_files}")
        if failed_files:
            _LOGGER.error(f"  Failed files: {failed_files}")
        
        # Copy log file too if exists
        legacy_log = LEGACY_DATA_DIR / "api.log"
        if legacy_log.exists():
            try:
                shutil.copy2(legacy_log, DATA_DIR / "api.log")
                _LOGGER.info("  Migrated api.log")
            except Exception:
                pass  # Log file is not critical
        _LOGGER.info("Data directory migration complete")

    # v1.6.0: Cumulative migration using `< X` pattern
    # This ensures users jumping multiple versions (e.g., v1 -> v5) run ALL migrations
    # Previous `== X` pattern could miss migrations if config_entry.version wasn't
    # updated in-place after async_update_entry()
    
    if initial_version < 2:
        # Version 1 (v1.1.0) -> 2 (v1.2.0): Handle zone-based device migration
        _LOGGER.info("=== Migration: v1 -> v2 ===")
        _LOGGER.info("Migrating from v1.1.0 to v1.2.0 format")
        
        # Ensure data directory exists
        try:
            DATA_DIR.mkdir(exist_ok=True)
            _LOGGER.info(f"  DATA_DIR ensured: {DATA_DIR}")
        except Exception as e:
            _LOGGER.error(f"  Failed to create DATA_DIR: {e}")
        
        # Check if zones_info.json exists, if not, trigger a full sync
        if not ZONES_INFO_FILE.exists():
            _LOGGER.warning("  zones_info.json missing - will be created on first sync")
            # Don't fail migration - let the sync create it
        else:
            _LOGGER.info("  zones_info.json exists")
        
        _LOGGER.info("Migration step v1 -> v2 complete")

    if initial_version < 4:
        # Version 2/3 -> 4 (v1.4.0): New device authorization flow
        _LOGGER.info(f"=== Migration: v{initial_version} -> v4 ===")
        _LOGGER.info("Migrating to v1.4.0 format (device authorization)")
        
        # Ensure data directory exists
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _LOGGER.info(f"  DATA_DIR ensured: {DATA_DIR}")
        except Exception as e:
            _LOGGER.error(f"  Failed to create DATA_DIR: {e}")
        
        # Check if config.json exists with valid refresh_token
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
                
                _LOGGER.info(f"  config.json keys: {list(config.keys())}")
                _LOGGER.info(f"  home_id present: {'home_id' in config}")
                _LOGGER.info(f"  refresh_token present: {'refresh_token' in config and bool(config.get('refresh_token'))}")
                
                if config.get("refresh_token"):
                    _LOGGER.info("  Existing refresh_token found - authentication should work")
                else:
                    _LOGGER.warning(
                        "  No refresh_token in config.json - re-authentication may be required. "
                        "If entities are unavailable, use Reconfigure option or delete and re-add the integration."
                    )
            except json.JSONDecodeError as e:
                _LOGGER.error(f"  config.json is invalid JSON: {e}")
            except Exception as e:
                _LOGGER.warning(f"  Could not read config.json: {e}")
        else:
            _LOGGER.warning(
                "  config.json not found - re-authentication required. "
                "Delete and re-add the integration to authenticate."
            )
        
        _LOGGER.info("Migration step -> v4 complete")

    if initial_version < 5:
        # Version 4 -> 5 (v1.5.2): Data directory moved to .storage/tado_ce/
        _LOGGER.info("=== Migration: -> v5 ===")
        _LOGGER.info("Migrating to v1.5.2 format (new data directory)")
        
        # Data migration already handled at the top of this function
        _LOGGER.info("Migration step -> v5 complete")

    if initial_version < 6:
        # Version 5 -> 6 (v1.7.0): Change unique_id from tado_ce_integration to tado_ce_{home_id}
        _LOGGER.info("=== Migration: -> v6 ===")
        _LOGGER.info("Migrating to v1.7.0 format (unique_id change for multi-home support)")
        
        # Get home_id from config entry data or config.json
        home_id = config_entry.data.get("home_id")
        
        if not home_id and CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
                    home_id = config.get("home_id")
                    _LOGGER.info(f"  Got home_id from config.json: {home_id}")
            except Exception as e:
                _LOGGER.warning(f"  Could not read home_id from config.json: {e}")
        
        if home_id:
            new_unique_id = f"tado_ce_{home_id}"
            _LOGGER.info(f"  Updating unique_id: tado_ce_integration -> {new_unique_id}")
            
            # Update the config entry's unique_id
            # Note: This is done via async_update_entry with the new unique_id
            hass.config_entries.async_update_entry(
                config_entry,
                unique_id=new_unique_id
            )
            _LOGGER.info(f"  unique_id updated to: {new_unique_id}")
        else:
            _LOGGER.warning(
                "  Could not determine home_id for unique_id migration. "
                "unique_id will remain as tado_ce_integration until re-authentication."
            )
        
        _LOGGER.info("Migration step -> v6 complete")

    if initial_version < 7:
        # Version 6 -> 7 (v1.8.0): Per-home data files for multi-home support
        _LOGGER.info("=== Migration: -> v7 ===")
        _LOGGER.info("Migrating to v1.8.0 format (per-home data files)")
        
        # Get home_id from config entry data or config.json
        home_id = config_entry.data.get("home_id")
        
        if not home_id and CONFIG_FILE.exists():
            try:
                def _read_home_id():
                    with open(CONFIG_FILE) as f:
                        return json.load(f).get("home_id")
                home_id = await hass.async_add_executor_job(_read_home_id)
                _LOGGER.info(f"  Got home_id from config.json: {home_id}")
            except Exception as e:
                _LOGGER.warning(f"  Could not read home_id from config.json: {e}")
        
        if home_id:
            from .const import PER_HOME_FILES, get_data_file, get_legacy_file
            import shutil
            
            def _migrate_files():
                """Migrate files in executor to avoid blocking I/O."""
                migrated = []
                for base_name in PER_HOME_FILES:
                    legacy_path = get_legacy_file(base_name)
                    new_path = get_data_file(base_name, home_id)
                    
                    # Only migrate if legacy exists and new doesn't
                    if legacy_path.exists() and not new_path.exists():
                        try:
                            shutil.copy2(legacy_path, new_path)
                            migrated.append(f"{base_name}.json -> {base_name}_{home_id}.json")
                        except Exception as e:
                            _LOGGER.error(f"  Failed to migrate {base_name}.json: {e}")
                return migrated
            
            migrated_files = await hass.async_add_executor_job(_migrate_files)
            
            for f in migrated_files:
                _LOGGER.info(f"  Migrated {f}")
            
            if migrated_files:
                _LOGGER.info(f"  Migrated {len(migrated_files)} files for home_id {home_id}")
            else:
                _LOGGER.info("  No files needed migration (already migrated or new install)")
        else:
            _LOGGER.warning(
                "  Could not determine home_id for data file migration. "
                "Files will remain with legacy names until re-authentication."
            )
        
        _LOGGER.info("Migration step -> v7 complete")

    if initial_version < 8:
        # Version 7 -> 8 (v1.9.0): Hub device identifier migration for multi-home support
        _LOGGER.info("=== Migration: -> v8 ===")
        _LOGGER.info("Migrating to v1.9.0 format (hub device identifier)")
        
        # Get home_id from config entry data or config.json
        home_id = config_entry.data.get("home_id")
        
        if not home_id and CONFIG_FILE.exists():
            try:
                def _read_home_id():
                    with open(CONFIG_FILE) as f:
                        return json.load(f).get("home_id")
                home_id = await hass.async_add_executor_job(_read_home_id)
                _LOGGER.info(f"  Got home_id from config.json: {home_id}")
            except Exception as e:
                _LOGGER.warning(f"  Could not read home_id from config.json: {e}")
        
        if home_id:
            # Set home_id for data_loader so load_zones_info_file() works correctly
            from .data_loader import set_current_home_id
            set_current_home_id(home_id)
            
            # Import device registry
            from homeassistant.helpers import device_registry as dr
            
            device_registry = dr.async_get(hass)
            
            # Find old hub device with identifier "tado_ce_hub"
            old_device = device_registry.async_get_device(
                identifiers={(DOMAIN, "tado_ce_hub")}
            )
            
            if old_device:
                new_identifier = f"tado_ce_hub_{home_id}"
                _LOGGER.info(f"  Found old hub device: {old_device.id}")
                _LOGGER.info(f"  Updating identifier: tado_ce_hub -> {new_identifier}")
                
                # Update device identifier (preserves user customizations!)
                device_registry.async_update_device(
                    old_device.id,
                    new_identifiers={(DOMAIN, new_identifier)}
                )
                _LOGGER.info(f"  Hub device identifier updated successfully")
            else:
                _LOGGER.info("  No old hub device found (new install or already migrated)")
            
            # Also migrate zone devices: tado_ce_zone_{zone_id} -> tado_ce_{home_id}_zone_{zone_id}
            # Strategy: Try zones_info first, fallback to scanning device registry
            from .data_loader import load_zones_info_file
            zones_info = await hass.async_add_executor_job(load_zones_info_file)
            
            migrated_zones = 0
            
            if zones_info:
                # Use zones_info to find zone IDs
                for zone in zones_info:
                    zone_id = str(zone.get('id'))
                    old_zone_identifier = f"tado_ce_zone_{zone_id}"
                    new_zone_identifier = f"tado_ce_{home_id}_zone_{zone_id}"
                    
                    old_zone_device = device_registry.async_get_device(
                        identifiers={(DOMAIN, old_zone_identifier)}
                    )
                    
                    if old_zone_device:
                        _LOGGER.info(f"  Migrating zone device: {old_zone_identifier} -> {new_zone_identifier}")
                        device_registry.async_update_device(
                            old_zone_device.id,
                            new_identifiers={(DOMAIN, new_zone_identifier)},
                            via_device_id=None  # Will be re-linked when entities load
                        )
                        migrated_zones += 1
            else:
                # Fallback: Scan device registry for any tado_ce_zone_* devices
                # This handles edge case where zones_info.json doesn't exist
                _LOGGER.info("  zones_info not available, scanning device registry for zone devices")
                
                import re
                zone_pattern = re.compile(r"tado_ce_zone_(\d+)")
                
                for device in device_registry.devices.values():
                    for id_tuple in device.identifiers:
                        if len(id_tuple) != 2:
                            continue
                        domain, identifier = id_tuple
                        if domain == DOMAIN:
                            match = zone_pattern.match(identifier)
                            if match:
                                zone_id = match.group(1)
                                new_zone_identifier = f"tado_ce_{home_id}_zone_{zone_id}"
                                
                                _LOGGER.info(f"  Migrating zone device: {identifier} -> {new_zone_identifier}")
                                device_registry.async_update_device(
                                    device.id,
                                    new_identifiers={(DOMAIN, new_zone_identifier)},
                                    via_device_id=None
                                )
                                migrated_zones += 1
            
            if migrated_zones > 0:
                _LOGGER.info(f"  Migrated {migrated_zones} zone devices")
        else:
            _LOGGER.warning(
                "  Could not determine home_id for hub device migration. "
                "Hub device will remain with old identifier until re-authentication."
            )
        
        _LOGGER.info("Migration step -> v8 complete")

    # v1.11.0 Migration (continued)
    if initial_version < 9:
        # Version 8 -> 9 (v1.11.0): Remove deprecated instantaneous sensors
        # These have been replaced by heating cycle analysis sensors
        _LOGGER.info("=== Migration: -> v9 ===")
        _LOGGER.info("Removing deprecated sensors and cleaning up non-TRV zone thermal analytics")
        
        from homeassistant.helpers import entity_registry as er
        from .data_loader import load_zones_info_file
        
        entity_registry = er.async_get(hass)
        
        # Part 1: Remove deprecated sensor suffixes (all zones)
        deprecated_suffixes = [
            # Original v1.9.0 instantaneous sensors
            "_thermal_rate",
            "_cooling_rate", 
            "_heating_efficiency",
            "_time_to_target",
            # Additional deprecated sensors from earlier iterations
            "_heating_rate",           # replaced by _avg_heating_rate
            "_historical_comparison",  # replaced by _historical_deviation
            "_inertia_time",           # replaced by _thermal_inertia
            "_heating_rate_analysis",  # replaced by _avg_heating_rate
            "_preheat_estimate",       # replaced by _preheat_time
            "_confidence_score",       # replaced by _analysis_confidence
        ]
        
        # Part 2: REMOVED in v2.0.1 (#91)
        # Previously removed thermal analytics from non-TRV zones, but SU02 also has heatingPower
        # Thermal analytics sensors are now created for ALL zones with heatingPower data
        # Users who upgraded from v1.11.0-v2.0.0 may need to reload the integration
        # to recreate thermal analytics sensors for SU02 zones
        _LOGGER.info("  v2.0.1: Thermal analytics now available for all zones with heatingPower (including SU02)")
        
        removed_count = 0
        for entity_id, entity_entry in list(entity_registry.entities.items()):
            if entity_entry.platform != DOMAIN:
                continue
            
            should_remove = False
            
            # Check deprecated suffixes (all zones)
            for suffix in deprecated_suffixes:
                if entity_id.endswith(suffix):
                    should_remove = True
                    _LOGGER.info(f"  Removing deprecated entity: {entity_id}")
                    break
            
            # v2.0.1: Removed non-TRV zone cleanup - SU02 also has heatingPower (#91)
            
            if should_remove:
                entity_registry.async_remove(entity_id)
                removed_count += 1
        
        _LOGGER.info(f"  Removed {removed_count} entities")
        
        # Migrate legacy data files to per-home format
        # v1.8.0 introduced per-home files WITH _HOMEID suffix
        # Legacy files (no suffix) need to be RENAMED to per-home format
        # Exception: config.json stays as-is (bootstrap file, needed before we know home_id)
        home_id = config_entry.data.get("home_id")
        if home_id:
            # Legacy files (no suffix) -> New files (with _HOMEID suffix)
            # Note: config.json is NOT migrated - it's the bootstrap file
            legacy_to_new_mapping = {
                "api_call_history.json": f"api_call_history_{home_id}.json",
                "heating_cycle_history.json": f"heating_cycle_history_{home_id}.json",
                "home_state.json": f"home_state_{home_id}.json",
                "ratelimit.json": f"ratelimit_{home_id}.json",
                "schedules.json": f"schedules_{home_id}.json",
                "smart_comfort_cache.json": f"smart_comfort_cache_{home_id}.json",
                "smart_heating_cache.json": f"smart_heating_cache_{home_id}.json",
                "zones.json": f"zones_{home_id}.json",
                "zones_info.json": f"zones_info_{home_id}.json",
                "weather.json": f"weather_{home_id}.json",
                "mobile_devices.json": f"mobile_devices_{home_id}.json",
                "offsets.json": f"offsets_{home_id}.json",
                "ac_capabilities.json": f"ac_capabilities_{home_id}.json",
            }
            
            def _migrate_legacy_files():
                """Migrate legacy files to per-home format in executor."""
                migrated = []
                deleted = []
                
                for legacy_name, new_name in legacy_to_new_mapping.items():
                    legacy_path = DATA_DIR / legacy_name
                    new_path = DATA_DIR / new_name
                    
                    if not legacy_path.exists():
                        continue
                    
                    if new_path.exists():
                        # Per-home file already exists, delete legacy
                        try:
                            legacy_path.unlink()
                            deleted.append(legacy_name)
                            _LOGGER.debug(f"  Deleted legacy file: {legacy_name} (per-home exists)")
                        except Exception as e:
                            _LOGGER.warning(f"  Failed to delete {legacy_name}: {e}")
                    else:
                        # RENAME legacy -> per-home
                        try:
                            legacy_path.rename(new_path)
                            migrated.append(f"{legacy_name} -> {new_name}")
                            _LOGGER.info(f"  Migrated: {legacy_name} -> {new_name}")
                        except Exception as e:
                            _LOGGER.warning(f"  Failed to migrate {legacy_name}: {e}")
                
                return {"migrated": migrated, "deleted": deleted}
            
            result = await hass.async_add_executor_job(_migrate_legacy_files)
            if result["migrated"]:
                _LOGGER.info(f"  Migrated {len(result['migrated'])} files to per-home format")
            if result["deleted"]:
                _LOGGER.info(f"  Deleted {len(result['deleted'])} legacy files")
        
        # Clean up deprecated code files (tado_api.py, error_handler.py)
        # These were replaced by async_api.py in v1.6.0 but kept for compatibility
        # Now safe to remove as all functionality is in async_api.py
        from pathlib import Path
        integration_dir = Path(__file__).parent
        deprecated_code_files = ["tado_api.py", "error_handler.py", "test_schedule_api.py"]
        
        def _cleanup_deprecated_code():
            """Remove deprecated code files."""
            removed = []
            for filename in deprecated_code_files:
                file_path = integration_dir / filename
                if file_path.exists():
                    try:
                        file_path.unlink()
                        removed.append(filename)
                        _LOGGER.info(f"  Removed deprecated file: {filename}")
                    except Exception as e:
                        _LOGGER.warning(f"  Failed to remove {filename}: {e}")
            return removed
        
        removed_files = await hass.async_add_executor_job(_cleanup_deprecated_code)
        if removed_files:
            _LOGGER.info(f"  Cleaned up {len(removed_files)} deprecated code files")
        
        _LOGGER.info("Migration step -> v9 complete")

    # Update to final version (only once, at the end)
    if initial_version < 10:
        hass.config_entries.async_update_entry(config_entry, version=10)
        _LOGGER.info(
            "=== Migration Complete ===\n"
            f"  Initial version: {initial_version}\n"
            f"  Final version: 10\n"
            f"  CONFIG_FILE exists: {CONFIG_FILE.exists()}\n"
            f"  DATA_DIR exists: {DATA_DIR.exists()}"
        )
    else:
        _LOGGER.info("Config entry already at version 10, no migration needed")
    
    return True


async def _migrate_to_per_zone_config(
    hass: HomeAssistant,
    entry: ConfigEntry,
    zone_config_manager: ZoneConfigManager
) -> None:
    """Migrate global settings to per-zone configuration.
    
    v2.1.0: Called on first startup after upgrade.
    Migrates:
    - ufh_zones → per-zone heating_type = "ufh"
    - ufh_buffer_minutes → per-zone ufh_buffer_minutes
    - adaptive_preheat_zones → per-zone adaptive_preheat = True
    - smart_comfort_mode → per-zone (inherit global)
    - mold_risk_window_type → per-zone window_type
    - overlay_mode → per-zone (inherit global)
    """
    options = entry.options
    
    # Check if already migrated
    if options.get("_per_zone_migrated"):
        _LOGGER.debug("Per-zone migration already completed, skipping")
        return
    
    # Check if there are any global settings to migrate
    has_settings_to_migrate = any([
        options.get("ufh_zones"),
        options.get("adaptive_preheat_zones"),
        options.get("smart_comfort_mode"),
        options.get("mold_risk_window_type"),
    ])
    
    if not has_settings_to_migrate:
        _LOGGER.debug("No global settings to migrate to per-zone config")
        # Mark as migrated anyway to prevent future checks
        new_options = {**options, "_per_zone_migrated": True}
        hass.config_entries.async_update_entry(entry, options=new_options)
        return
    
    _LOGGER.info("=== Per-Zone Configuration Migration ===")
    
    # Load zones info
    from .data_loader import load_zones_info_file
    zones_info = await hass.async_add_executor_job(load_zones_info_file)
    
    if not zones_info:
        _LOGGER.warning("No zones info available, skipping per-zone migration")
        return
    
    # Get global settings
    ufh_zones = options.get("ufh_zones", [])
    ufh_buffer = options.get("ufh_buffer_minutes", 30)
    adaptive_preheat_zones = options.get("adaptive_preheat_zones", [])
    smart_comfort_mode = options.get("smart_comfort_mode", "none")
    window_type = options.get("mold_risk_window_type", "double_pane")
    
    # Get overlay mode from cache or file (already UPPERCASE)
    from .data_loader import load_overlay_mode
    overlay_mode = await hass.async_add_executor_job(load_overlay_mode)
    
    # v2.1.0: overlay_mode is already UPPERCASE from data_loader
    # No mapping needed - use directly
    overlay_mode_internal = overlay_mode  # Already UPPERCASE
    
    migrated_count = 0
    
    # Apply to each zone
    for zone in zones_info:
        zone_id = str(zone.get("id"))
        zone_type = zone.get("type")
        zone_name = zone.get("name", f"Zone {zone_id}")
        
        config_updates = {}
        
        # Heating type (Heating only)
        if zone_type == "HEATING":
            if zone_id in ufh_zones:
                config_updates["heating_type"] = "ufh"
                config_updates["ufh_buffer_minutes"] = ufh_buffer
                _LOGGER.debug(f"  Zone {zone_name}: UFH with {ufh_buffer}min buffer")
            else:
                config_updates["heating_type"] = "radiator"
        
        # Adaptive preheat (Heating + AC)
        if zone_id in adaptive_preheat_zones:
            config_updates["adaptive_preheat"] = True
            _LOGGER.debug(f"  Zone {zone_name}: Adaptive preheat enabled")
        
        # Smart comfort mode (inherit global)
        if smart_comfort_mode != "none":
            config_updates["smart_comfort_mode"] = smart_comfort_mode
        
        # Window type (inherit global)
        config_updates["window_type"] = window_type
        
        # Overlay mode (inherit global)
        config_updates["overlay_mode"] = overlay_mode_internal
        
        # Save zone config
        for key, value in config_updates.items():
            await zone_config_manager.async_set_zone_value(zone_id, key, value)
        
        if config_updates:
            migrated_count += 1
    
    # Mark as migrated
    new_options = {**options, "_per_zone_migrated": True}
    hass.config_entries.async_update_entry(entry, options=new_options)
    
    _LOGGER.info(f"Per-zone migration complete: {migrated_count} zones configured")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tado CE from a config entry."""
    _LOGGER.info(
        "=== Tado CE Setup Start ===\n"
        f"  Entry ID: {entry.entry_id}\n"
        f"  Entry version: {entry.version}\n"
        f"  Entry data: {entry.data}"
    )
    
    # Log file system state for debugging (run in executor to avoid blocking I/O)
    from .const import LEGACY_DATA_DIR, ZONES_INFO_FILE, ZONES_FILE
    
    def _check_file_system_state():
        """Check file system state (blocking I/O)."""
        return {
            "data_dir_exists": DATA_DIR.exists(),
            "config_file_exists": CONFIG_FILE.exists(),
            "zones_file_exists": ZONES_FILE.exists(),
            "zones_info_file_exists": ZONES_INFO_FILE.exists(),
            "legacy_data_dir_exists": LEGACY_DATA_DIR.exists(),
        }
    
    fs_state = await hass.async_add_executor_job(_check_file_system_state)
    _LOGGER.info(
        "=== Setup File System State ===\n"
        f"  DATA_DIR: {DATA_DIR} (exists: {fs_state['data_dir_exists']})\n"
        f"  CONFIG_FILE: {CONFIG_FILE} (exists: {fs_state['config_file_exists']})\n"
        f"  ZONES_FILE: {ZONES_FILE} (exists: {fs_state['zones_file_exists']})\n"
        f"  ZONES_INFO_FILE: {ZONES_INFO_FILE} (exists: {fs_state['zones_info_file_exists']})\n"
        f"  LEGACY_DATA_DIR: {LEGACY_DATA_DIR} (exists: {fs_state['legacy_data_dir_exists']})"
    )
    
    # CRITICAL: Check for duplicate entries and remove old ones (v1.1.0 leftovers)
    # This must be done BEFORE any setup to avoid race conditions
    all_entries = hass.config_entries.async_entries(DOMAIN)
    if len(all_entries) > 1:
        _LOGGER.warning(f"Found {len(all_entries)} Tado CE entries - checking for duplicates")
        _LOGGER.info(f"  All entries: {[(e.entry_id, e.version) for e in all_entries]}")
        
        # Initialize domain data if needed
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        
        # Sort by version (descending), then by entry_id for deterministic ordering
        entries_by_version = sorted(
            all_entries, 
            key=lambda e: (getattr(e, 'version', 0), e.entry_id), 
            reverse=True
        )
        
        keeper_entry_id = entries_by_version[0].entry_id
        _LOGGER.info(f"  Keeper entry: {keeper_entry_id}")
        
        # If current entry is NOT the one to keep, abort this setup
        if entry.entry_id != keeper_entry_id:
            _LOGGER.warning(
                f"Current entry {entry.entry_id} (version {entry.version}) is duplicate. "
                f"Aborting setup - will be removed by keeper entry."
            )
            return False
        
        # Current entry IS the keeper - remove all others
        # Use a flag specific to THIS cleanup session to prevent duplicate work
        cleanup_key = f'duplicate_cleanup_{keeper_entry_id}'
        if cleanup_key not in hass.data[DOMAIN]:
            hass.data[DOMAIN][cleanup_key] = True
            
            _LOGGER.info(f"Entry {keeper_entry_id} is keeper - removing {len(entries_by_version) - 1} duplicates")
            
            for old_entry in entries_by_version[1:]:
                _LOGGER.warning(
                    f"Removing duplicate entry {old_entry.entry_id} "
                    f"(version {getattr(old_entry, 'version', 'unknown')})"
                )
                # CRITICAL: Use await to ensure removal completes before continuing
                # This prevents race condition where old entries continue setup
                try:
                    await hass.config_entries.async_remove(old_entry.entry_id)
                    _LOGGER.info(f"Successfully removed duplicate entry {old_entry.entry_id}")
                except Exception as e:
                    _LOGGER.error(f"Failed to remove duplicate entry {old_entry.entry_id}: {e}")
            
            # Verify cleanup
            _LOGGER.info(f"Duplicate cleanup complete. Keeper: {keeper_entry_id}")
    
    # v1.5.2: Migrate data from legacy location if needed
    # This handles cases where migration didn't run (e.g., fresh install with old data)
    # Run in executor to avoid blocking I/O
    def _migrate_legacy_data():
        """Migrate data from legacy location (blocking I/O)."""
        import shutil
        if not LEGACY_DATA_DIR.exists() or DATA_DIR.exists():
            return []
        
        _LOGGER.info("=== Setup-time Data Migration ===")
        _LOGGER.info("Migrating data directory from legacy location to .storage/tado_ce/")
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _LOGGER.info(f"  Created DATA_DIR: {DATA_DIR}")
        except Exception as e:
            _LOGGER.error(f"  Failed to create DATA_DIR: {e}")
            return []
        
        migrated_files = []
        for file in LEGACY_DATA_DIR.glob("*.json"):
            try:
                shutil.copy2(file, DATA_DIR / file.name)
                migrated_files.append(file.name)
            except Exception as e:
                _LOGGER.error(f"  Failed to migrate {file.name}: {e}")
        return migrated_files
    
    migrated = await hass.async_add_executor_job(_migrate_legacy_data)
    if migrated:
        _LOGGER.info(f"  Migrated files: {migrated}")
    
    # Ensure data directory exists (run in executor to avoid blocking I/O)
    def _ensure_data_dir():
        """Ensure data directory exists (blocking I/O)."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            _LOGGER.error(f"Failed to create DATA_DIR: {e}")
    
    await hass.async_add_executor_job(_ensure_data_dir)
    
    # Initialize configuration manager
    config_manager = ConfigurationManager(entry, hass)
    _LOGGER.info(f"Configuration loaded: {config_manager.get_all_config()}")
    
    # v1.8.0: Set current home_id for data_loader multi-home support
    home_id = entry.data.get("home_id")
    if home_id:
        from .data_loader import set_current_home_id
        set_current_home_id(home_id)
        _LOGGER.info(f"Data loader home_id set to: {home_id}")
    
    # Store config_manager in hass.data for access by other components
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    
    # CRITICAL: Check if already setup to prevent multiple polling timers
    if 'polling_cancel' in hass.data[DOMAIN]:
        _LOGGER.warning("Tado CE: Already setup, cancelling old polling timer")
        old_cancel = hass.data[DOMAIN]['polling_cancel']
        if old_cancel:
            old_cancel()
    
    hass.data[DOMAIN]['config_manager'] = config_manager
    
    # v2.1.0: Initialize ZoneConfigManager for per-zone settings
    zone_config_manager = ZoneConfigManager(hass, home_id or "default")
    await zone_config_manager.async_load()
    hass.data[DOMAIN]['zone_config_manager'] = zone_config_manager
    _LOGGER.info(f"Zone config manager initialized with {len(zone_config_manager.zones)} zones")
    
    # v2.1.0: Migrate global settings to per-zone configuration
    await _migrate_to_per_zone_config(hass, entry, zone_config_manager)
    
    # v2.0.2: Load overlay mode into cache (Issue #101 - @leoogermenia)
    # Lesson from v2.0.0: Use async_add_executor_job for file I/O
    from .data_loader import load_overlay_mode, load_timer_duration
    overlay_mode = await hass.async_add_executor_job(load_overlay_mode)
    hass.data[DOMAIN]['overlay_mode'] = overlay_mode
    _LOGGER.debug(f"Tado CE: Overlay mode loaded: {overlay_mode}")
    
    # v2.1.0: Load timer duration into cache
    timer_duration = await hass.async_add_executor_job(load_timer_duration)
    hass.data[DOMAIN]['timer_duration'] = timer_duration
    _LOGGER.debug(f"Tado CE: Timer duration loaded: {timer_duration} minutes")
    
    # v2.0.1: Set Test Mode flag on async client for save_ratelimit() to use
    client = get_async_client(hass)
    client._test_mode_enabled = config_manager.get_test_mode_enabled()
    _LOGGER.debug(f"Tado CE: Test Mode enabled = {client._test_mode_enabled}")
    
    # v1.10.0: Store freshness tracking functions in hass.data for entity access
    async def mark_entity_fresh(entity_id: str) -> None:
        """Mark entity as having a recent API call in progress."""
        async with freshness_lock:
            entity_freshness[entity_id] = time.time()
            _LOGGER.debug(f"Marked entity fresh: {entity_id}")
    
    def is_entity_fresh(entity_id: str, debounce_seconds: int = None) -> bool:
        """Check if entity has a recent API call (within debounce window).
        
        Args:
            entity_id: Entity ID to check
            debounce_seconds: Override debounce window (uses config if None)
        """
        if entity_id not in entity_freshness:
            return False
        
        # Use config value if not overridden
        if debounce_seconds is None:
            debounce_seconds = config_manager.get_refresh_debounce_seconds() + 2
        
        elapsed = time.time() - entity_freshness[entity_id]
        if elapsed > debounce_seconds:
            # Auto-cleanup expired entries
            del entity_freshness[entity_id]
            return False
        
        return True
    
    async def cleanup_entity_freshness() -> None:
        """Periodic cleanup of expired entity freshness entries.
        
        Prevents memory leak from entities that are always fresh or removed.
        Called every 5 minutes by async_track_time_interval.
        """
        async with freshness_lock:
            now = time.time()
            expired = [
                entity_id for entity_id, timestamp in entity_freshness.items()
                if now - timestamp > 60  # Remove entries older than 1 minute
            ]
            for entity_id in expired:
                del entity_freshness[entity_id]
            if expired:
                _LOGGER.debug(f"Cleaned up {len(expired)} expired entity freshness entries")
    
    def get_next_sequence() -> int:
        """Get next sequence number for tracking data freshness.
        
        Includes overflow protection - resets at sys.maxsize to prevent
        memory issues in long-running instances.
        """
        import sys
        global_sequence[0] += 1
        # Overflow protection: reset at sys.maxsize
        if global_sequence[0] >= sys.maxsize:
            _LOGGER.info("Sequence number reached max, resetting to 0")
            global_sequence[0] = 0
        return global_sequence[0]
    
    hass.data[DOMAIN]['mark_entity_fresh'] = mark_entity_fresh
    hass.data[DOMAIN]['is_entity_fresh'] = is_entity_fresh
    hass.data[DOMAIN]['get_next_sequence'] = get_next_sequence
    
    # Start periodic cleanup for entity freshness dict (every 5 minutes)
    from homeassistant.helpers.event import async_track_time_interval
    from datetime import timedelta
    
    def _schedule_cleanup(now):
        """Schedule cleanup in event loop from time interval callback."""
        hass.loop.call_soon_threadsafe(
            lambda: hass.async_create_task(cleanup_entity_freshness())
        )
    
    cleanup_cancel = async_track_time_interval(
        hass,
        _schedule_cleanup,
        timedelta(minutes=5)
    )
    hass.data[DOMAIN]['freshness_cleanup_cancel'] = cleanup_cancel
    
    # Sync configuration to config.json for tado_api.py
    await config_manager.async_sync_all_to_config_json()
    
    # Initialize immediate refresh handler
    from .immediate_refresh_handler import get_handler
    refresh_handler = get_handler(hass)
    _LOGGER.info("Immediate refresh handler initialized")
    
    # Load home_id and version early to avoid race conditions in device_manager
    # These perform blocking I/O so must be run in executor
    from .device_manager import load_home_id, load_version
    await hass.async_add_executor_job(load_home_id)
    await hass.async_add_executor_job(load_version)
    
    # v1.9.0: Cleanup duplicate hub devices (migration safety net)
    # If migration failed or was interrupted, we might have both old and new hub devices
    if home_id:
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er
        
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        
        def count_device_entities(device_id: str) -> int:
            """Count entities linked to a device."""
            return len([e for e in entity_registry.entities.values() if e.device_id == device_id])
        
        old_hub_identifier = "tado_ce_hub"
        new_hub_identifier = f"tado_ce_hub_{home_id}"
        
        old_hub = device_registry.async_get_device(identifiers={(DOMAIN, old_hub_identifier)})
        new_hub = device_registry.async_get_device(identifiers={(DOMAIN, new_hub_identifier)})
        
        if old_hub and new_hub:
            # Both exist - need to merge safely to preserve entity links
            # Strategy: Keep the device with MORE entities, migrate entities from the other, then remove it
            old_entity_count = count_device_entities(old_hub.id)
            new_entity_count = count_device_entities(new_hub.id)
            
            _LOGGER.warning(
                f"Found duplicate hub devices: {old_hub_identifier} ({old_entity_count} entities) "
                f"and {new_hub_identifier} ({new_entity_count} entities). Merging..."
            )
            
            if old_entity_count >= new_entity_count:
                # Keep old (has more or equal entities)
                # First, migrate any entities from new to old
                for entity in list(entity_registry.entities.values()):
                    if entity.device_id == new_hub.id:
                        _LOGGER.info(f"Moving entity {entity.entity_id} from new hub to old hub")
                        entity_registry.async_update_entity(
                            entity.entity_id,
                            device_id=old_hub.id
                        )
                
                # Now remove the empty new device
                try:
                    device_registry.async_remove_device(new_hub.id)
                    _LOGGER.info(f"Removed empty new hub device: {new_hub_identifier}")
                except Exception as e:
                    _LOGGER.warning(f"Could not remove new hub device: {e}")
                
                # Update old device's identifier to new format
                device_registry.async_update_device(
                    old_hub.id,
                    new_identifiers={(DOMAIN, new_hub_identifier)}
                )
                _LOGGER.info(f"Kept old hub ({old_entity_count} entities), updated identifier to {new_hub_identifier}")
            else:
                # Keep new (has more entities)
                # First, migrate any entities from old to new
                for entity in list(entity_registry.entities.values()):
                    if entity.device_id == old_hub.id:
                        _LOGGER.info(f"Moving entity {entity.entity_id} from old hub to new hub")
                        entity_registry.async_update_entity(
                            entity.entity_id,
                            device_id=new_hub.id
                        )
                
                # Now remove the empty old device
                try:
                    device_registry.async_remove_device(old_hub.id)
                    _LOGGER.info(f"Removed empty old hub device: {old_hub_identifier}")
                except Exception as e:
                    _LOGGER.warning(f"Could not remove old hub device: {e}")
                
                _LOGGER.info(f"Kept new hub ({new_entity_count} entities)")
        elif old_hub and not new_hub:
            # Only old exists - migration didn't run, update it now
            _LOGGER.info(f"Found old hub device without new one. Migrating: {old_hub_identifier} -> {new_hub_identifier}")
            device_registry.async_update_device(
                old_hub.id,
                new_identifiers={(DOMAIN, new_hub_identifier)}
            )
        
        # Also cleanup duplicate zone devices
        import re
        zone_pattern = re.compile(r"tado_ce_zone_(\d+)")
        
        for device in list(device_registry.devices.values()):
            for id_tuple in device.identifiers:
                if len(id_tuple) != 2:
                    continue
                domain, identifier = id_tuple
                if domain == DOMAIN:
                    match = zone_pattern.match(identifier)
                    if match:
                        zone_id = match.group(1)
                        new_zone_identifier = f"tado_ce_{home_id}_zone_{zone_id}"
                        
                        # Check if new zone device exists
                        new_zone = device_registry.async_get_device(
                            identifiers={(DOMAIN, new_zone_identifier)}
                        )
                        
                        if new_zone:
                            # Both exist - keep the one with more entities
                            old_count = count_device_entities(device.id)
                            new_count = count_device_entities(new_zone.id)
                            
                            _LOGGER.warning(
                                f"Found duplicate zone devices: {identifier} ({old_count} entities) "
                                f"and {new_zone_identifier} ({new_count} entities). Merging..."
                            )
                            
                            if old_count >= new_count:
                                # Keep old, migrate entities from new, remove new, update old's identifier
                                for entity in list(entity_registry.entities.values()):
                                    if entity.device_id == new_zone.id:
                                        entity_registry.async_update_entity(
                                            entity.entity_id,
                                            device_id=device.id
                                        )
                                try:
                                    device_registry.async_remove_device(new_zone.id)
                                except Exception as e:
                                    _LOGGER.warning(f"Could not remove new zone device: {e}")
                                device_registry.async_update_device(
                                    device.id,
                                    new_identifiers={(DOMAIN, new_zone_identifier)}
                                )
                                _LOGGER.info(f"Kept old zone ({old_count} entities), updated to {new_zone_identifier}")
                            else:
                                # Keep new, migrate entities from old, remove old
                                for entity in list(entity_registry.entities.values()):
                                    if entity.device_id == device.id:
                                        entity_registry.async_update_entity(
                                            entity.entity_id,
                                            device_id=new_zone.id
                                        )
                                try:
                                    device_registry.async_remove_device(device.id)
                                except Exception as e:
                                    _LOGGER.warning(f"Could not remove old zone device: {e}")
                                _LOGGER.info(f"Kept new zone ({new_count} entities)")
                        else:
                            # Only old exists - migrate it
                            _LOGGER.info(f"Migrating zone device: {identifier} -> {new_zone_identifier}")
                            device_registry.async_update_device(
                                device.id,
                                new_identifiers={(DOMAIN, new_zone_identifier)}
                            )
    
    # Check if config file exists (run in executor to avoid blocking I/O)
    config_exists = await hass.async_add_executor_job(CONFIG_FILE.exists)
    if not config_exists:
        _LOGGER.warning(
            "Tado CE config file not found. "
            "Use Settings > Devices & Services > Add Integration > Tado CE to authenticate."
        )
    
    # Track current interval and last full sync time
    current_interval = [0]
    cancel_interval = [None]
    last_full_sync = [None]
    
    # Cache for ratelimit data (loaded async to avoid blocking I/O)
    cached_ratelimit = [None]
    
    # v1.10.0: Coordinator freshness tracking for race condition fix (Issue #44)
    # Track which entities have recent API calls to prevent stale data overwrites
    entity_freshness = {}  # entity_id -> timestamp
    global_sequence = [0]  # Monotonically increasing sequence number
    freshness_lock = asyncio.Lock()  # Protect concurrent access
    
    async def async_load_ratelimit():
        """Load ratelimit data asynchronously using native async I/O."""
        try:
            # Use per-home file path
            from .data_loader import get_current_home_id
            from .const import get_data_file
            home_id = get_current_home_id()
            ratelimit_path = get_data_file("ratelimit", home_id)
            
            _LOGGER.debug(f"Tado CE: async_load_ratelimit - home_id={home_id}, path={ratelimit_path}")
            
            if await aiofiles.os.path.exists(ratelimit_path):
                async with aiofiles.open(ratelimit_path, 'r') as f:
                    content = await f.read()
                    cached_ratelimit[0] = json.loads(content)
                    _LOGGER.debug(f"Tado CE: async_load_ratelimit - loaded used={cached_ratelimit[0].get('used')}")
            else:
                cached_ratelimit[0] = None
                _LOGGER.debug(f"Tado CE: async_load_ratelimit - file not found")
        except Exception as e:
            cached_ratelimit[0] = None
            _LOGGER.debug(f"Tado CE: async_load_ratelimit - exception: {e}")
    
    async def async_schedule_next_sync():
        """Schedule next sync with dynamic interval (async-safe)."""
        # Load ratelimit data asynchronously
        await async_load_ratelimit()
        
        new_interval = get_polling_interval(config_manager, cached_ratelimit[0])
        
        if new_interval != current_interval[0]:
            time_period = "day" if is_daytime(config_manager) else "night"
            _LOGGER.info(f"Tado CE: Polling interval set to {new_interval}m ({time_period})")
            current_interval[0] = new_interval
        
        # Cancel old interval
        if cancel_interval[0]:
            cancel_interval[0]()
        
        # Schedule new interval
        async def async_sync_wrapper(now):
            """Async wrapper for sync."""
            await async_sync_tado()
        
        cancel_interval[0] = async_track_time_interval(
            hass,
            async_sync_wrapper,
            timedelta(minutes=new_interval)
        )
        
        # Store cancel function in hass.data so we can cancel on reload
        hass.data[DOMAIN]['polling_cancel'] = cancel_interval[0]
    
    async def async_sync_tado():
        """Run Tado sync using async API (v1.6.0+).
        
        Replaces subprocess-based sync with native async calls.
        """
        # v2.0.0: Universal Quota Reserve Protection
        # Replaces the old Test Mode-only check with a universal solution
        try:
            # Use cached ratelimit data to avoid extra file I/O
            ratelimit_data = cached_ratelimit[0]
            if ratelimit_data is None:
                await async_load_ratelimit()
                ratelimit_data = cached_ratelimit[0]
            
            if ratelimit_data:
                should_pause, reason = should_pause_polling(ratelimit_data, config_manager)
                if should_pause:
                    _LOGGER.warning(f"Tado CE: {reason}")
                    # Re-schedule to check again later
                    await async_schedule_next_sync()
                    return
        except Exception as e:
            _LOGGER.debug(f"Could not check quota reserve: {e}")
        
        # Determine if this should be a full sync
        do_full_sync = False
        if last_full_sync[0] is None:
            do_full_sync = True
        else:
            hours_since_full = (datetime.now() - last_full_sync[0]).total_seconds() / 3600
            if hours_since_full >= FULL_SYNC_INTERVAL_HOURS:
                do_full_sync = True
        
        sync_type = "full" if do_full_sync else "quick"
        _LOGGER.debug(f"Tado CE: Executing {sync_type} sync")
        
        try:
            # Get async client and perform sync
            client = get_async_client(hass)
            
            # Get config options
            weather_enabled = config_manager.get_weather_enabled()
            mobile_devices_enabled = config_manager.get_mobile_devices_enabled()
            mobile_devices_frequent_sync = config_manager.get_mobile_devices_frequent_sync()
            offset_enabled = config_manager.get_offset_enabled()
            home_state_sync_enabled = config_manager.get_home_state_sync_enabled()
            
            success = await client.async_sync(
                quick=not do_full_sync,
                weather_enabled=weather_enabled,
                mobile_devices_enabled=mobile_devices_enabled,
                mobile_devices_frequent_sync=mobile_devices_frequent_sync,
                offset_enabled=offset_enabled,
                home_state_sync_enabled=home_state_sync_enabled
            )
            
            if success:
                if do_full_sync:
                    last_full_sync[0] = datetime.now()
                
                # v1.7.0: Detect API reset time from HA sensor history
                # This is more accurate than extrapolation because it uses actual recorded data
                detected_reset = await async_detect_reset_from_history(hass)
                if detected_reset:
                    _LOGGER.debug(f"Tado CE: HA history detected reset at {detected_reset.strftime('%H:%M')} UTC")
                    await _update_ratelimit_reset_time(hass, detected_reset)
            else:
                _LOGGER.warning("Tado CE sync returned failure status")
                
        except Exception as e:
            _LOGGER.error(f"Tado CE sync ERROR: {e}")
        
        # Re-schedule with potentially new interval (day/night change)
        await async_schedule_next_sync()
    
    # Initial sync (only if config exists)
    # Reuse config_exists from earlier check to avoid blocking I/O
    _LOGGER.info(f"Tado CE: Checking config file at {CONFIG_FILE}, exists={config_exists}")
    if config_exists:
        _LOGGER.info("Tado CE: Starting initial sync...")
        await async_sync_tado()
        _LOGGER.info("Tado CE: Initial sync completed")
    else:
        # Still schedule polling even without config
        _LOGGER.warning(f"Tado CE: Config file not found at {CONFIG_FILE}, scheduling polling only")
        await async_schedule_next_sync()
        _LOGGER.info("Tado CE: Polling scheduled")
    
    # Forward setup to platforms
    # Build platform list based on config
    platforms_to_load = list(BASE_PLATFORMS)
    
    # v1.8.0: Add Calendar platform if enabled (opt-in)
    if CALENDAR_PLATFORM and config_manager.get_schedule_calendar_enabled():
        platforms_to_load.append(CALENDAR_PLATFORM)
        _LOGGER.info("Tado CE: Schedule Calendar enabled")
    

    # v1.9.0: Initialize Smart Comfort Manager if enabled (opt-in)
    if config_manager.get_smart_comfort_enabled():
        from .smart_comfort import (
            get_smart_comfort_manager,
            async_load_history_from_recorder,
            async_load_baseline_from_statistics
        )
        history_days = config_manager.get_smart_comfort_history_days()
        smart_comfort_manager = get_smart_comfort_manager(history_days=history_days)
        smart_comfort_manager._hass = hass  # Set hass reference for weather entity access
        smart_comfort_manager._home_id = home_id  # Set home_id for per-home cache files
        smart_comfort_manager.enable()
        
        # Configure weather compensation (Phase 3)
        outdoor_temp_entity = config_manager.get_outdoor_temp_entity()
        weather_compensation = config_manager.get_weather_compensation()
        use_feels_like = config_manager.get_use_feels_like()
        
        if outdoor_temp_entity:
            smart_comfort_manager.configure_weather(
                outdoor_temp_entity=outdoor_temp_entity,
                weather_compensation=weather_compensation,
                use_feels_like=use_feels_like
            )
        
        hass.data[DOMAIN]['smart_comfort_manager'] = smart_comfort_manager
        
        # 3-Tier Loading Strategy:
        # Tier 1: Load from cache file (fastest, 2h detailed data)
        cache_readings = await hass.async_add_executor_job(smart_comfort_manager.load_from_file)
        
        # Get zones_info for entity ID mapping
        from .data_loader import load_zones_info_file
        zones_info = await hass.async_add_executor_job(load_zones_info_file)
        
        if zones_info:
            # Build mapping: entity_name -> zone_id (numeric)
            # e.g., "master" -> "1", "dining" -> "2"
            entity_to_zone_id = {
                zone.get('name', '').lower().replace(' ', '_'): str(zone.get('id'))
                for zone in zones_info
                if zone.get('name') and zone.get('id')
            }
            
            climate_entity_ids = [
                f"climate.{entity_name}"
                for entity_name in entity_to_zone_id.keys()
            ]
            
            # Tier 2: Load from recorder history (24h detailed states)
            recorder_readings = 0
            if climate_entity_ids:
                recorder_readings = await async_load_history_from_recorder(
                    hass, smart_comfort_manager, climate_entity_ids, entity_to_zone_id
                )
            
            # Tier 3: Load baseline rates from long-term statistics (7 days hourly)
            zone_sensor_mapping = {
                str(zone.get('id')): 
                f"sensor.{zone.get('name', '').lower().replace(' ', '_')}_temperature"
                for zone in zones_info
                if zone.get('name') and zone.get('id')
            }
            baseline_stats = await async_load_baseline_from_statistics(
                hass, smart_comfort_manager, zone_sensor_mapping
            )
            
            _LOGGER.info(
                f"Tado CE: Smart Comfort 3-tier loading complete - "
                f"cache={cache_readings}, recorder={recorder_readings}, "
                f"baseline_zones={len(baseline_stats)}"
            )
        
        _LOGGER.info("Tado CE: Smart Comfort Analytics enabled")
    
    # v1.11.0: Initialize Heating Cycle Coordinator (always enabled for HEATING zones)
    if home_id:
        try:
            from .heating_cycle_coordinator import HeatingCycleCoordinator
            from .heating_cycle_models import HeatingCycleConfig
            
            # Create config from user settings
            heating_cycle_config = HeatingCycleConfig(
                enabled=True,
                rolling_window_days=config_manager.get_heating_cycle_history_days(),
                inertia_threshold_celsius=config_manager.get_heating_cycle_inertia_threshold(),
                min_cycles=config_manager.get_heating_cycle_min_cycles(),
            )
            
            _LOGGER.info(
                "Tado CE: Heating Cycle Config - min_cycles=%d, history_days=%d, inertia_threshold=%.2f",
                heating_cycle_config.min_cycles,
                heating_cycle_config.rolling_window_days,
                heating_cycle_config.inertia_threshold_celsius
            )
            
            # Initialize coordinator
            heating_cycle_coordinator = HeatingCycleCoordinator(
                hass, home_id, heating_cycle_config
            )
            
            # Setup coordinator (load storage, resume active cycles)
            await heating_cycle_coordinator.async_setup()
            
            # Store in hass.data for sensor access
            hass.data[DOMAIN]['heating_cycle_coordinator'] = heating_cycle_coordinator
            
            # Schedule periodic timeout check (every 60 seconds)
            async def async_check_cycle_timeouts(_now):
                """Periodic task to check for cycle timeouts."""
                await heating_cycle_coordinator.check_timeouts()
            
            # Use track_time_interval for periodic execution
            cancel_timeout_check = async_track_time_interval(
                hass, 
                async_check_cycle_timeouts,
                timedelta(seconds=60)
            )
            hass.data[DOMAIN]['heating_cycle_timeout_cancel'] = cancel_timeout_check
            
            _LOGGER.info("Tado CE: Heating Cycle Analysis initialized")
        except Exception as e:
            _LOGGER.error("Tado CE: Failed to initialize Heating Cycle Analysis: %s", e)
            # Continue without heating cycle analysis - non-critical feature
    
    # v2.0.0: Initialize Adaptive Preheat Manager if enabled
    if config_manager.get_adaptive_preheat_enabled():
        try:
            from .adaptive_preheat import async_setup_adaptive_preheat
            await async_setup_adaptive_preheat(hass, config_manager)
            _LOGGER.info("Tado CE: Adaptive Preheat enabled")
        except Exception as e:
            _LOGGER.error("Tado CE: Failed to initialize Adaptive Preheat: %s", e)
            # Continue without adaptive preheat - non-critical feature
    
    await hass.config_entries.async_forward_entry_setups(entry, platforms_to_load)
    
    # Auto-assign areas to zone devices (v2.0.0)
    # This runs after platforms are loaded so devices are already created
    try:
        from .area_manager import async_assign_zone_areas
        from .data_loader import load_zones_info_file
        
        _LOGGER.info("Tado CE: Starting auto-assign areas")
        zones_info = await hass.async_add_executor_job(load_zones_info_file)
        if zones_info:
            await async_assign_zone_areas(hass, home_id or "unknown", zones_info)
        else:
            _LOGGER.debug("No zones_info available for area assignment")
    except Exception as e:
        _LOGGER.warning(f"Failed to auto-assign areas: {e}")
        # Non-critical feature - continue setup
    
    # Register services
    await _async_register_services(hass)
    
    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    _LOGGER.info("Tado CE: Integration loaded successfully")
    return True


def _cleanup_entities_by_suffix(entity_registry, domain: str, prefix: str, suffixes: list) -> int:
    """Remove entities matching prefix and any of the suffixes.
    
    Args:
        entity_registry: HA entity registry
        domain: Integration domain (e.g., "tado_ce")
        prefix: unique_id prefix to match (e.g., "tado_ce_zone_")
        suffixes: List of suffixes to match (e.g., ["_battery", "_connection"])
    
    Returns:
        Number of entities removed
    """
    removed = 0
    for entity_id, entity_entry in list(entity_registry.entities.items()):
        if entity_entry.platform != domain:
            continue
        unique_id = entity_entry.unique_id or ""
        if unique_id.startswith(prefix) and any(unique_id.endswith(suffix) for suffix in suffixes):
            _LOGGER.debug(f"  Removing entity: {entity_id} (unique_id: {unique_id})")
            entity_registry.async_remove(entity_id)
            removed += 1
    return removed


def _cleanup_entities_by_pattern(entity_registry, domain: str, suffixes: list) -> int:
    """Remove entities matching any of the suffixes (regardless of prefix).
    
    Args:
        entity_registry: HA entity registry
        domain: Integration domain (e.g., "tado_ce")
        suffixes: List of suffixes to match (e.g., ["_child_lock", "_early_start"])
    
    Returns:
        Number of entities removed
    """
    removed = 0
    for entity_id, entity_entry in list(entity_registry.entities.items()):
        if entity_entry.platform != domain:
            continue
        unique_id = entity_entry.unique_id or ""
        if unique_id.startswith("tado_ce_") and any(unique_id.endswith(suffix) for suffix in suffixes):
            _LOGGER.debug(f"  Removing entity: {entity_id} (unique_id: {unique_id})")
            entity_registry.async_remove(entity_id)
            removed += 1
    return removed


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change.
    
    v2.0.1: When Test Mode is disabled, trigger an API call to refresh
    rate limit data with real values instead of relying on backup.
    v2.0.3: Auto-cleanup entities when Zone Features are disabled.
    """
    _LOGGER.info("Tado CE: Options changed, reloading integration...")
    
    # v2.0.3: Cleanup entities when Zone Features are disabled
    # Check for cleanup flags set by config_flow before async_create_entry
    try:
        from homeassistant.helpers import entity_registry as er
        entity_registry = er.async_get(hass)
        
        domain_data = hass.data.get(DOMAIN, {})
        total_removed = 0
        
        # Zone Configuration cleanup
        if domain_data.pop("_cleanup_zone_config", False):
            _LOGGER.info("Tado CE: Zone Configuration disabled - removing zone config entities")
            zone_config_suffixes = [
                "_heating_type", "_ufh_buffer", "_adaptive_preheat",
                "_smart_comfort_mode", "_window_type", "_overlay_mode",
                "_timer_duration", "_min_temp", "_max_temp", "_temp_offset",
            ]
            removed = _cleanup_entities_by_suffix(entity_registry, DOMAIN, "tado_ce_zone_", zone_config_suffixes)
            total_removed += removed
            _LOGGER.info(f"  Removed {removed} zone config entities")
        
        # Zone Diagnostics cleanup (battery, connection, heating power)
        if domain_data.pop("_cleanup_zone_diagnostics", False):
            _LOGGER.info("Tado CE: Zone Diagnostics disabled - removing diagnostic entities")
            # Device-level entities use serial number pattern: tado_ce_{serial}_*
            diagnostic_suffixes = ["_battery", "_connection", "_heating", "_ac_power"]
            removed = _cleanup_entities_by_suffix(entity_registry, DOMAIN, "tado_ce_zone_", diagnostic_suffixes)
            # Also cleanup device-level battery/connection (tado_ce_{serial}_*)
            removed += _cleanup_entities_by_pattern(entity_registry, DOMAIN, ["_battery", "_connection"])
            total_removed += removed
            _LOGGER.info(f"  Removed {removed} diagnostic entities")
        
        # Device Controls cleanup (child lock, early start)
        if domain_data.pop("_cleanup_device_controls", False):
            _LOGGER.info("Tado CE: Device Controls disabled - removing device control entities")
            device_control_suffixes = ["_child_lock", "_early_start"]
            removed = _cleanup_entities_by_pattern(entity_registry, DOMAIN, device_control_suffixes)
            total_removed += removed
            _LOGGER.info(f"  Removed {removed} device control entities")
        
        # Boost Buttons cleanup
        if domain_data.pop("_cleanup_boost_buttons", False):
            _LOGGER.info("Tado CE: Boost Buttons disabled - removing boost button entities")
            boost_suffixes = ["_boost", "_smart_boost"]
            removed = _cleanup_entities_by_pattern(entity_registry, DOMAIN, boost_suffixes)
            total_removed += removed
            _LOGGER.info(f"  Removed {removed} boost button entities")
        
        # Environment Sensors cleanup (mold risk, comfort level, condensation)
        if domain_data.pop("_cleanup_environment_sensors", False):
            _LOGGER.info("Tado CE: Environment Sensors disabled - removing environment sensor entities")
            env_suffixes = [
                "_mold_risk", "_comfort_level", "_condensation_risk",
                "_surface_temperature", "_dew_point", "_insights",  # v2.2.0
            ]
            removed = _cleanup_entities_by_suffix(entity_registry, DOMAIN, "tado_ce_zone_", env_suffixes)
            # v2.2.0: Also cleanup window_predicted binary sensors (different platform)
            removed += _cleanup_entities_by_suffix(entity_registry, DOMAIN, "tado_ce_zone_", ["_window_predicted"])
            total_removed += removed
            _LOGGER.info(f"  Removed {removed} environment sensor entities")
        
        # Thermal Analytics cleanup
        if domain_data.pop("_cleanup_thermal_analytics", False):
            _LOGGER.info("Tado CE: Thermal Analytics disabled - removing thermal analytics entities")
            thermal_suffixes = [
                "_thermal_inertia", "_heating_rate", "_efficiency",
                "_approach_factor", "_historical_deviation", "_heating_cycles",
            ]
            removed = _cleanup_entities_by_suffix(entity_registry, DOMAIN, "tado_ce_zone_", thermal_suffixes)
            total_removed += removed
            _LOGGER.info(f"  Removed {removed} thermal analytics entities")
        
        if total_removed > 0:
            _LOGGER.info(f"Tado CE: Total entities removed: {total_removed}")
            
    except Exception as e:
        _LOGGER.warning(f"Tado CE: Could not cleanup entities: {e}")
    
    # v2.0.1: Check if Test Mode was just disabled
    # If so, trigger an API call to get fresh rate limit data
    try:
        # Get previous Test Mode state from ratelimit.json
        from .const import get_data_file
        from .data_loader import get_current_home_id
        import aiofiles
        import json
        
        home_id = get_current_home_id()
        ratelimit_path = get_data_file("ratelimit", home_id)
        
        prev_test_mode = False
        if await aiofiles.os.path.exists(ratelimit_path):
            async with aiofiles.open(ratelimit_path, 'r') as f:
                content = await f.read()
                ratelimit_data = json.loads(content)
                prev_test_mode = ratelimit_data.get("test_mode", False)
        
        # Get new Test Mode state from options
        new_test_mode = entry.options.get("test_mode_enabled", False)
        
        _LOGGER.debug(f"Test Mode transition check: prev={prev_test_mode}, new={new_test_mode}")
        
        # If Test Mode was just disabled, trigger API refresh
        if prev_test_mode and not new_test_mode:
            _LOGGER.info("Tado CE: Test Mode disabled - triggering API refresh for real rate limit data")
            
            # Get async client and make a lightweight API call
            client = get_async_client(hass)
            
            # Use get_me() as a lightweight API call to refresh rate limit
            # This will trigger save_ratelimit() with real API values
            try:
                await client.get_me()
                _LOGGER.info("Tado CE: API refresh completed - rate limit data updated with real values")
            except Exception as e:
                _LOGGER.warning(f"Tado CE: API refresh failed (will use backup): {e}")
    except Exception as e:
        _LOGGER.debug(f"Tado CE: Could not check Test Mode transition: {e}")
    
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_services(hass: HomeAssistant):
    """Register Tado CE services."""
    
    # Check if services are already registered (avoid duplicate registration)
    if hass.services.has_service(DOMAIN, SERVICE_SET_CLIMATE_TIMER):
        _LOGGER.debug("Tado CE services already registered, skipping")
        return
    
    async def handle_set_climate_timer(call: ServiceCall):
        """Handle set_climate_timer service call.
        
        Compatible with official Tado integration format:
        - entity_id (required)
        - temperature (required)
        - time_period (required) - Time Period format (e.g., "01:30:00")
        - overlay (optional)
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        should_block, reason = await async_check_bootstrap_reserve(hass)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )
        
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        
        temperature = call.data.get("temperature")
        time_period = call.data.get("time_period")
        overlay = call.data.get("overlay")
        
        # CRITICAL FIX: Validate time_period (same as water heater)
        if not time_period:
            error_msg = "time_period is required for set_climate_timer service"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)
        
        # Convert time_period to minutes with validation
        try:
            from datetime import timedelta
            
            # Home Assistant cv.time_period returns timedelta
            if isinstance(time_period, timedelta):
                duration_minutes = int(time_period.total_seconds() / 60)
            else:
                # Fallback: parse string format HH:MM:SS
                time_parts = str(time_period).split(":")
                if len(time_parts) != 3:
                    raise ValueError(f"Invalid time_period format: {time_period}. Expected HH:MM:SS")
                
                hours = int(time_parts[0])
                minutes = int(time_parts[1])
                seconds = int(time_parts[2])
                
                # Validate ranges
                if not (0 <= hours <= 24):
                    raise ValueError(f"Hours must be 0-24, got {hours}")
                if not (0 <= minutes <= 59):
                    raise ValueError(f"Minutes must be 0-59, got {minutes}")
                if not (0 <= seconds <= 59):
                    raise ValueError(f"Seconds must be 0-59, got {seconds}")
                
                duration_minutes = hours * 60 + minutes + (seconds // 60)
            
            # Validate final duration (5-1440 minutes)
            if duration_minutes < 5:
                raise ValueError(f"Duration must be at least 5 minutes, got {duration_minutes}")
            if duration_minutes > 1440:
                raise ValueError(f"Duration must be at most 1440 minutes (24 hours), got {duration_minutes}")
            
            _LOGGER.info(f"Parsed time_period {time_period} to {duration_minutes} minutes")
            
        except (ValueError, AttributeError, TypeError) as e:
            error_msg = f"Failed to parse time_period: {e}"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)
        
        # Validate temperature if provided
        if temperature is None:
            error_msg = "temperature is required for set_climate_timer service"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)
        
        for entity_id in entity_ids:
            entity = hass.states.get(entity_id)
            if entity:
                # Get the climate entity and call async_set_timer
                climate_entity = hass.data.get("entity_components", {}).get("climate")
                if climate_entity:
                    for ent in climate_entity.entities:
                        if ent.entity_id == entity_id and hasattr(ent, 'async_set_timer'):
                            try:
                                await ent.async_set_timer(temperature, duration_minutes, overlay)
                                _LOGGER.info(f"Set timer for {entity_id}: {temperature}°C for {duration_minutes}min")
                            except Exception as e:
                                error_msg = f"Failed to set timer for {entity_id}: {e}"
                                _LOGGER.error(error_msg)
                                # Continue to next entity instead of failing completely
                            break
    
    async def handle_set_water_heater_timer(call: ServiceCall):
        """Handle set_water_heater_timer service call.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        should_block, reason = await async_check_bootstrap_reserve(hass)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )
        
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        
        time_period = call.data.get("time_period")
        temperature = call.data.get("temperature")
        
        # CRITICAL FIX: Validate time_period
        if not time_period:
            error_msg = "time_period is required for set_water_heater_timer service"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)
        
        # Convert time_period to minutes with validation
        try:
            from datetime import timedelta
            
            # Home Assistant cv.time_period returns timedelta
            if isinstance(time_period, timedelta):
                duration_minutes = int(time_period.total_seconds() / 60)
            else:
                # Fallback: parse string format HH:MM:SS
                time_parts = str(time_period).split(":")
                if len(time_parts) != 3:
                    raise ValueError(f"Invalid time_period format: {time_period}. Expected HH:MM:SS")
                
                hours = int(time_parts[0])
                minutes = int(time_parts[1])
                seconds = int(time_parts[2])
                
                # Validate ranges
                if not (0 <= hours <= 24):
                    raise ValueError(f"Hours must be 0-24, got {hours}")
                if not (0 <= minutes <= 59):
                    raise ValueError(f"Minutes must be 0-59, got {minutes}")
                if not (0 <= seconds <= 59):
                    raise ValueError(f"Seconds must be 0-59, got {seconds}")
                
                duration_minutes = hours * 60 + minutes + (seconds // 60)
            
            # Validate final duration (5-1440 minutes)
            if duration_minutes < 5:
                raise ValueError(f"Duration must be at least 5 minutes, got {duration_minutes}")
            if duration_minutes > 1440:
                raise ValueError(f"Duration must be at most 1440 minutes (24 hours), got {duration_minutes}")
            
            _LOGGER.info(f"Parsed time_period {time_period} to {duration_minutes} minutes")
            
        except (ValueError, AttributeError, TypeError) as e:
            error_msg = f"Failed to parse time_period: {e}"
            _LOGGER.error(error_msg)
            raise vol.Invalid(error_msg)
        
        # Validate temperature if provided
        if temperature is not None:
            if not (30 <= temperature <= 80):
                error_msg = f"Temperature must be 30-80°C, got {temperature}"
                _LOGGER.error(error_msg)
                raise vol.Invalid(error_msg)
        
        # Call water heater entities
        for entity_id in entity_ids:
            water_heater_component = hass.data.get("entity_components", {}).get("water_heater")
            if water_heater_component:
                for ent in water_heater_component.entities:
                    if ent.entity_id == entity_id and hasattr(ent, 'async_set_timer'):
                        try:
                            await ent.async_set_timer(duration_minutes, temperature)
                            _LOGGER.info(f"Set timer for {entity_id}: {duration_minutes}min")
                        except Exception as e:
                            error_msg = f"Failed to set timer for {entity_id}: {e}"
                            _LOGGER.error(error_msg)
                            # Continue to next entity instead of failing completely
                        break
    
    async def handle_resume_schedule(call: ServiceCall):
        """Handle resume_schedule service call.
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        from .async_api import get_async_client
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        should_block, reason = await async_check_bootstrap_reserve(hass)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )
        
        entity_ids = call.data.get("entity_id", [])
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        
        client = get_async_client(hass)
        
        for entity_id in entity_ids:
            domain = entity_id.split(".")[0]
            component = hass.data.get("entity_components", {}).get(domain)
            if component:
                for ent in component.entities:
                    if ent.entity_id == entity_id:
                        zone_id = getattr(ent, '_zone_id', None)
                        if zone_id:
                            await client.delete_zone_overlay(zone_id)
                            _LOGGER.info(f"Resumed schedule for {entity_id}")
                        break
    
    async def handle_set_temp_offset(call: ServiceCall):
        """Handle set_temperature_offset service call.
        
        Sets temperature offset for ALL devices in a zone (supports multi-TRV rooms).
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        from .async_api import get_async_client
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        should_block, reason = await async_check_bootstrap_reserve(hass)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )
        
        entity_id = call.data.get("entity_id")
        offset = call.data.get("offset")
        
        client = get_async_client(hass)
        
        # Get zone_id from entity and find ALL device serials
        climate_component = hass.data.get("entity_components", {}).get("climate")
        if climate_component:
            for ent in climate_component.entities:
                if ent.entity_id == entity_id:
                    zone_id = getattr(ent, '_zone_id', None)
                    if zone_id:
                        # Find ALL device serials for this zone (multi-TRV support)
                        serials = await hass.async_add_executor_job(
                            _get_device_serials_for_zone, zone_id
                        )
                        if serials:
                            for serial in serials:
                                await client.set_device_offset(serial, offset)
                            _LOGGER.info(f"Set offset {offset}°C for {entity_id} ({len(serials)} device(s))")
                        else:
                            _LOGGER.warning(f"No devices found for {entity_id}")
                    break
    
    async def handle_add_meter_reading(call: ServiceCall):
        """Handle add_meter_reading service call (fully async).
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        from .async_api import get_async_client
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        should_block, reason = await async_check_bootstrap_reserve(hass)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )
        
        reading = call.data.get("reading")
        date = call.data.get("date")
        
        client = get_async_client(hass)
        success = await client.add_meter_reading(reading, date)
        
        if not success:
            _LOGGER.error(f"Failed to add meter reading: {reading}")
    
    # Register services
    hass.services.async_register(
        DOMAIN, SERVICE_SET_CLIMATE_TIMER, handle_set_climate_timer,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
            vol.Required("temperature"): vol.Coerce(float),
            vol.Required("time_period"): cv.time_period,
            vol.Optional("overlay"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_SET_WATER_HEATER_TIMER, handle_set_water_heater_timer,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
            vol.Required("time_period"): cv.time_period,
            vol.Optional("temperature"): vol.Coerce(float),
        })
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_RESUME_SCHEDULE, handle_resume_schedule,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_ids,
        })
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_SET_TEMP_OFFSET, handle_set_temp_offset,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("offset"): vol.Coerce(float),
        })
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_METER_READING, handle_add_meter_reading,
        schema=vol.Schema({
            vol.Required("reading"): vol.Coerce(int),
            vol.Optional("date"): cv.string,
        })
    )
    
    async def handle_identify_device(call: ServiceCall):
        """Handle identify_device service call (fully async).
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        from .async_api import get_async_client
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        should_block, reason = await async_check_bootstrap_reserve(hass)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )
        
        device_serial = call.data.get("device_serial")
        
        client = get_async_client(hass)
        success = await client.identify_device(device_serial)
        
        if not success:
            _LOGGER.error(f"Failed to identify device: {device_serial}")
    
    async def handle_set_away_config(call: ServiceCall):
        """Handle set_away_configuration service call (fully async).
        
        v2.0.1: Added bootstrap reserve check - blocks action when quota critically low.
        """
        from .async_api import get_async_client
        
        # v2.0.1: Bootstrap Reserve - block action when quota critically low
        should_block, reason = await async_check_bootstrap_reserve(hass)
        if should_block:
            await async_show_api_limit_notification(hass, reason)
            raise HomeAssistantError(
                "API quota critically low - action blocked to preserve bootstrap reserve. "
                "Please wait for API reset."
            )
        
        entity_id = call.data.get("entity_id")
        mode = call.data.get("mode")
        temperature = call.data.get("temperature")
        comfort_level = call.data.get("comfort_level", 50)
        
        client = get_async_client(hass)
        
        # Get zone_id from entity
        climate_component = hass.data.get("entity_components", {}).get("climate")
        if climate_component:
            for ent in climate_component.entities:
                if ent.entity_id == entity_id:
                    zone_id = getattr(ent, '_zone_id', None)
                    if zone_id:
                        success = await client.set_away_configuration(
                            zone_id, mode, temperature, comfort_level
                        )
                        if not success:
                            _LOGGER.error(f"Failed to set away config for {entity_id}")
                    break
    
    hass.services.async_register(
        DOMAIN, SERVICE_IDENTIFY_DEVICE, handle_identify_device,
        schema=vol.Schema({
            vol.Required("device_serial"): cv.string,
        })
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_SET_AWAY_CONFIG, handle_set_away_config,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("mode"): cv.string,
            vol.Optional("temperature"): vol.Coerce(float),
            vol.Optional("comfort_level"): vol.Coerce(int),
        })
    )
    
    async def handle_get_temp_offset(call: ServiceCall):
        """Handle get_temperature_offset service call.
        
        Fetches the current temperature offset for a climate entity on-demand.
        Returns the offset value via service response for use in automations.
        """
        from .async_api import get_async_client
        
        entity_id = call.data.get("entity_id")
        client = get_async_client(hass)
        
        # Get zone_id from entity
        climate_component = hass.data.get("entity_components", {}).get("climate")
        if climate_component:
            for ent in climate_component.entities:
                if ent.entity_id == entity_id:
                    zone_id = getattr(ent, '_zone_id', None)
                    if zone_id:
                        # Find device serial for this zone
                        serial = await hass.async_add_executor_job(
                            _get_device_serial_for_zone, zone_id
                        )
                        if serial:
                            result = await client.get_device_offset(serial)
                            if result is not None:
                                return {"offset_celsius": result}
                    
                    _LOGGER.error(f"Failed to get offset for {entity_id}")
                    return {"offset_celsius": None, "error": "Failed to fetch offset"}
        
        _LOGGER.error(f"Entity not found: {entity_id}")
        return {"offset_celsius": None, "error": "Entity not found"}
    
    hass.services.async_register(
        DOMAIN, SERVICE_GET_TEMP_OFFSET, handle_get_temp_offset,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
        }),
        supports_response=True,
    )
    
    _LOGGER.info("Tado CE: Services registered")


def _get_device_serial_for_zone(zone_id: str) -> str | None:
    """Get the first device serial for a zone.
    
    Args:
        zone_id: Zone ID to look up
        
    Returns:
        Device serial number, or None if not found
    """
    from .data_loader import load_zones_info_file
    
    try:
        zones_info = load_zones_info_file()
        if not zones_info:
            return None
        
        for zone in zones_info:
            if str(zone.get('id')) == zone_id:
                for device in zone.get('devices', []):
                    serial = device.get('shortSerialNo')
                    if serial:
                        return serial
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to get device serial for zone {zone_id}: {e}")
        return None


def _get_device_serials_for_zone(zone_id: str) -> list[str]:
    """Get ALL device serials for a zone.
    
    Used for operations that need to apply to all devices in a zone
    (e.g., setting temperature offset on multiple TRVs).
    
    Args:
        zone_id: Zone ID to look up
        
    Returns:
        List of device serial numbers (may be empty)
    """
    from .data_loader import load_zones_info_file
    
    serials = []
    try:
        zones_info = load_zones_info_file()
        if not zones_info:
            return []
        
        for zone in zones_info:
            if str(zone.get('id')) == zone_id:
                for device in zone.get('devices', []):
                    serial = device.get('shortSerialNo')
                    if serial:
                        serials.append(serial)
                break
        return serials
    except Exception as e:
        _LOGGER.error(f"Failed to get device serials for zone {zone_id}: {e}")
        return []


# NOTE: The following blocking functions have been replaced by async methods
# in async_api.py (v1.5.0+) and removed to enforce proper async architecture:
# - _get_access_token -> Use async_api.get_async_client().get_access_token()
# - _get_temperature_offset -> client.get_device_offset()
# - _set_temperature_offset -> client.set_device_offset()
# - _add_meter_reading -> client.add_meter_reading()
# - _identify_device -> client.identify_device()
# - _set_away_configuration -> client.set_away_configuration()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.
    
    CRITICAL: Must clean up all resources to prevent memory leaks on reload.
    """
    _LOGGER.info("Tado CE: Unloading integration...")
    
    # Cancel polling timer if active
    if DOMAIN in hass.data and 'polling_cancel' in hass.data[DOMAIN]:
        cancel_func = hass.data[DOMAIN]['polling_cancel']
        if cancel_func:
            cancel_func()
            _LOGGER.debug("Cancelled polling timer")
    
    # Cancel freshness cleanup timer if active
    if DOMAIN in hass.data and 'freshness_cleanup_cancel' in hass.data[DOMAIN]:
        cleanup_cancel = hass.data[DOMAIN]['freshness_cleanup_cancel']
        if cleanup_cancel:
            cleanup_cancel()
            _LOGGER.debug("Cancelled freshness cleanup timer")
    
    # Clean up async client to prevent memory leak
    from .async_api import cleanup_async_client, cleanup_tracker
    cleanup_async_client(hass)
    cleanup_tracker()
    
    # Clean up immediate refresh handler
    from .immediate_refresh_handler import cleanup_handler
    cleanup_handler()
    
    # Clean up API call tracker executor to prevent thread leaks
    from .api_call_tracker import cleanup_executor
    cleanup_executor()
    
    # Clean up Smart Comfort manager (saves data before cleanup)
    from .smart_comfort import async_cleanup_smart_comfort_manager
    await async_cleanup_smart_comfort_manager(hass)
    
    # v2.0.0: Clean up Adaptive Preheat manager
    from .adaptive_preheat import async_unload_adaptive_preheat
    await async_unload_adaptive_preheat()
    
    # v1.11.0: Cancel heating cycle timeout check timer
    if DOMAIN in hass.data and 'heating_cycle_timeout_cancel' in hass.data[DOMAIN]:
        cancel_func = hass.data[DOMAIN]['heating_cycle_timeout_cancel']
        if cancel_func:
            cancel_func()
            _LOGGER.debug("Cancelled heating cycle timeout check timer")
    
    # Clean up data loader home_id
    from .data_loader import cleanup_data_loader
    cleanup_data_loader()
    
    # Clean up auth manager
    from .auth_manager import cleanup_auth_manager
    cleanup_auth_manager()
    
    # Build platform list to unload (same logic as setup)
    config_manager = hass.data.get(DOMAIN, {}).get('config_manager')
    platforms_to_unload = list(BASE_PLATFORMS)
    
    # v1.8.0: Add Calendar platform if it was loaded
    if CALENDAR_PLATFORM and config_manager and config_manager.get_schedule_calendar_enabled():
        platforms_to_unload.append(CALENDAR_PLATFORM)
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms_to_unload)
    
    # Clean up hass.data
    if unload_ok and DOMAIN in hass.data:
        hass.data.pop(DOMAIN, None)
        _LOGGER.debug("Cleaned up hass.data")
    
    _LOGGER.info("Tado CE: Integration unloaded successfully")
    return unload_ok
