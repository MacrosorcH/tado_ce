"""Centralized Data Loader for Tado CE Integration.

This module provides thread-safe file loading helpers for all Tado CE components.
All file I/O is blocking and should be called via hass.async_add_executor_job().

v1.8.0: Added multi-home support with per-home data files.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from .const import DATA_DIR, get_data_file, get_legacy_file

_LOGGER = logging.getLogger(__name__)

# Global home_id cache (set during setup)
_current_home_id: Optional[str] = None


def set_current_home_id(home_id: str) -> None:
    """Set the current home_id for data file lookups.
    
    Called during integration setup.
    """
    global _current_home_id
    _current_home_id = home_id
    _LOGGER.debug(f"Data loader home_id set to: {home_id}")


def get_current_home_id() -> Optional[str]:
    """Get the current home_id."""
    return _current_home_id


def cleanup_data_loader() -> bool:
    """Clean up data loader state.
    
    MUST be called in async_unload_entry() to reset home_id on reload.
    
    Returns:
        True if state was cleaned up
    """
    global _current_home_id
    _current_home_id = None
    _LOGGER.debug("Cleaned up data loader home_id")
    return True


def _get_file_path(base_name: str) -> Path:
    """Get file path with home_id support and fallback.
    
    Tries per-home file first, falls back to legacy file.
    Also auto-detects per-home files if _current_home_id not set yet.
    
    v2.0.1: Fixed glob pattern to only match {base_name}_{digits}.json
    to avoid collision with similar prefixes (e.g., zones_info.json
    being matched when looking for zones_*.json). Issue #100.
    """
    # If home_id is set, use it directly
    if _current_home_id:
        per_home_path = get_data_file(base_name, _current_home_id)
        if per_home_path.exists():
            return per_home_path
    
    # Auto-detect per-home files (for when home_id not set yet)
    # Use regex to only match {base_name}_{digits}.json pattern
    # This avoids collision like zones_info.json matching zones_*.json
    import re
    try:
        pattern = re.compile(rf"^{re.escape(base_name)}_(\d+)\.json$")
        for file in DATA_DIR.iterdir():
            if pattern.match(file.name):
                _LOGGER.debug(f"Auto-detected per-home file: {file.name}")
                return file
    except (OSError, FileNotFoundError):
        pass  # DATA_DIR doesn't exist yet
    
    # Fallback to legacy path
    return get_legacy_file(base_name)


def load_zones_file() -> Optional[dict]:
    """Load zones.json (zone states).
    
    Returns:
        Zone states dict, or None if file doesn't exist or is invalid.
    """
    try:
        file_path = _get_file_path("zones")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("zones.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in zones.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load zones.json: {e}")
        return None


def load_zones_info_file() -> Optional[list]:
    """Load zones_info.json (zone metadata).
    
    Returns:
        List of zone info dicts, or None if file doesn't exist or is invalid.
    """
    try:
        file_path = _get_file_path("zones_info")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("zones_info.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in zones_info.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load zones_info.json: {e}")
        return None


def load_weather_file() -> Optional[dict]:
    """Load weather.json.
    
    Returns:
        Weather data dict, or None if file doesn't exist or is invalid.
    """
    try:
        file_path = _get_file_path("weather")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("weather.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in weather.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load weather.json: {e}")
        return None


def load_mobile_devices_file() -> Optional[list]:
    """Load mobile_devices.json.
    
    Returns:
        List of mobile device dicts, or None if file doesn't exist or is invalid.
    """
    try:
        file_path = _get_file_path("mobile_devices")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("mobile_devices.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in mobile_devices.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load mobile_devices.json: {e}")
        return None


def load_config_file() -> Optional[dict]:
    """Load config.json.
    
    Returns:
        Config dict, or None if file doesn't exist or is invalid.
    """
    try:
        file_path = _get_file_path("config")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("config.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in config.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load config.json: {e}")
        return None


def load_home_state_file() -> Optional[dict]:
    """Load home_state.json.
    
    Returns:
        Home state dict, or None if file doesn't exist or is invalid.
    """
    try:
        file_path = _get_file_path("home_state")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("home_state.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in home_state.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load home_state.json: {e}")
        return None


def load_ratelimit_file() -> Optional[dict]:
    """Load ratelimit.json.
    
    Returns:
        Rate limit data dict, or None if file doesn't exist or is invalid.
    """
    try:
        file_path = _get_file_path("ratelimit")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("ratelimit.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in ratelimit.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load ratelimit.json: {e}")
        return None


def load_offsets_file() -> Optional[dict]:
    """Load offsets.json.
    
    Returns:
        Offsets dict (zone_id -> offset_celsius), or None if file doesn't exist.
    """
    try:
        file_path = _get_file_path("offsets")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("offsets.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in offsets.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load offsets.json: {e}")
        return None


def load_ac_capabilities_file() -> Optional[dict]:
    """Load ac_capabilities.json.
    
    Returns:
        AC capabilities dict (zone_id -> capabilities), or None if file doesn't exist.
    """
    try:
        file_path = _get_file_path("ac_capabilities")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("ac_capabilities.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in ac_capabilities.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load ac_capabilities.json: {e}")
        return None


def load_api_call_history_file() -> Optional[dict]:
    """Load api_call_history.json.
    
    Returns:
        API call history dict, or None if file doesn't exist.
    """
    try:
        file_path = _get_file_path("api_call_history")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("api_call_history.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in api_call_history.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load api_call_history.json: {e}")
        return None


# Convenience functions for common data access patterns

def get_zone_names() -> dict:
    """Get zone ID to name mapping.
    
    Returns:
        Dict mapping zone_id (str) to zone_name (str).
    """
    from .const import DEFAULT_ZONE_NAMES
    
    zones_info = load_zones_info_file()
    if zones_info:
        return {str(z.get('id')): z.get('name', f"Zone {z.get('id')}") for z in zones_info}
    return DEFAULT_ZONE_NAMES


def get_zone_types() -> dict:
    """Get zone ID to type mapping.
    
    Returns:
        Dict mapping zone_id (str) to zone_type (str).
    """
    zones_info = load_zones_info_file()
    if zones_info:
        return {str(z.get('id')): z.get('type', 'HEATING') for z in zones_info}
    return {}


def get_zone_data(zone_id: str) -> Optional[dict]:
    """Get state data for a specific zone.
    
    Args:
        zone_id: Zone ID to look up.
        
    Returns:
        Zone state dict, or None if not found.
    """
    zones_data = load_zones_file()
    if zones_data:
        # Use 'or {}' pattern for null safety
        zone_states = zones_data.get('zoneStates') or {}
        return zone_states.get(zone_id)
    return None


def load_schedules_file() -> Optional[dict]:
    """Load schedules.json (zone heating schedules).
    
    Returns:
        Schedules dict (zone_id -> schedule data), or None if file doesn't exist.
    """
    try:
        file_path = _get_file_path("schedules")
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        _LOGGER.debug("schedules.json not found")
        return None
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in schedules.json: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Failed to load schedules.json: {e}")
        return None


def get_zone_schedule(zone_id: str) -> Optional[dict]:
    """Get schedule data for a specific zone.
    
    Args:
        zone_id: Zone ID to look up.
        
    Returns:
        Zone schedule dict with 'blocks', or None if not found.
    """
    schedules = load_schedules_file()
    if schedules:
        return schedules.get(zone_id)
    return None


# ============================================================
# v2.0.2: Overlay Mode Storage (Issue #101 - @leoogermenia)
# ============================================================

OVERLAY_MODE_FILE = "overlay_mode.json"


def load_overlay_mode() -> str:
    """Load overlay mode from storage.
    
    v2.0.2: Issue #101 - Configurable overlay mode.
    v2.1.0: Added TIMER mode support.
    
    IMPORTANT: This is a SYNC function. Callers in async context
    MUST use `await hass.async_add_executor_job(load_overlay_mode)`.
    Lesson from v2.0.0: Blocking I/O in async context causes warnings.
    
    Returns:
        "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL"
        Defaults to "TADO_MODE" if file doesn't exist.
    """
    file_path = DATA_DIR / OVERLAY_MODE_FILE
    
    if not file_path.exists():
        return "TADO_MODE"
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            mode = data.get("overlay_mode", "TADO_MODE")
            # Validate mode
            if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
                _LOGGER.warning(f"Invalid overlay mode '{mode}', defaulting to TADO_MODE")
                return "TADO_MODE"
            return mode
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in {OVERLAY_MODE_FILE}: {e}")
        return "TADO_MODE"
    except Exception as e:
        _LOGGER.warning(f"Failed to load overlay mode: {e}")
        return "TADO_MODE"


def save_overlay_mode(mode: str) -> bool:
    """Save overlay mode to storage.
    
    v2.0.2: Issue #101 - Configurable overlay mode.
    v2.1.0: Added TIMER mode support.
    
    IMPORTANT: This is a SYNC function. Callers in async context
    MUST use `await hass.async_add_executor_job(save_overlay_mode, mode)`.
    Lesson from v2.0.0: Blocking I/O in async context causes warnings.
    
    Args:
        mode: "TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", or "MANUAL"
        
    Returns:
        True if saved successfully, False otherwise.
    """
    # Validate mode
    if mode not in ("TADO_MODE", "NEXT_TIME_BLOCK", "TIMER", "MANUAL"):
        _LOGGER.error(f"Invalid overlay mode: {mode}")
        return False
    
    file_path = DATA_DIR / OVERLAY_MODE_FILE
    
    try:
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w') as f:
            json.dump({"overlay_mode": mode}, f)
        
        _LOGGER.debug(f"Saved overlay mode: {mode}")
        return True
    except Exception as e:
        _LOGGER.error(f"Failed to save overlay mode: {e}")
        return False


def save_timer_duration(duration: int) -> bool:
    """Save timer duration to storage.
    
    v2.1.0: Timer duration for Timer overlay mode.
    
    IMPORTANT: This is a SYNC function. Callers in async context
    MUST use `await hass.async_add_executor_job(save_timer_duration, duration)`.
    
    Args:
        duration: Duration in minutes (15-180)
        
    Returns:
        True if saved successfully, False otherwise.
    """
    # Validate duration
    if not isinstance(duration, int) or duration < 15 or duration > 180:
        _LOGGER.error(f"Invalid timer duration: {duration}")
        return False
    
    file_path = DATA_DIR / "timer_duration.json"
    
    try:
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w') as f:
            json.dump({"timer_duration": duration}, f)
        
        _LOGGER.debug(f"Saved timer duration: {duration} minutes")
        return True
    except Exception as e:
        _LOGGER.error(f"Failed to save timer duration: {e}")
        return False


def load_timer_duration() -> int:
    """Load timer duration from storage.
    
    v2.1.0: Timer duration for Timer overlay mode.
    
    Returns:
        Duration in minutes (default 60 if not set or error).
    """
    file_path = DATA_DIR / "timer_duration.json"
    
    try:
        if file_path.exists():
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get("timer_duration", 60)
    except Exception as e:
        _LOGGER.debug(f"Failed to load timer duration: {e}")
    
    return 60  # Default


# ============================================================
# v2.2.0: Outdoor Temperature History (Weather Impact Insight)
# ============================================================

MAX_OUTDOOR_TEMP_READINGS = 336  # 7 days at 30s poll interval (2 readings/min × 60 × 24 × 7)


def load_outdoor_temp_history() -> list:
    """Load outdoor temperature history from storage.

    v2.2.0: Persists rolling outdoor temp readings across HA restarts
    for weather impact insight (US-20). Survives restarts unlike in-memory deque.

    IMPORTANT: This is a SYNC function. Callers in async context
    MUST use `await hass.async_add_executor_job(load_outdoor_temp_history)`.

    Returns:
        List of float temperature readings (most recent last), max 336 entries.
    """
    try:
        file_path = _get_file_path("outdoor_temp_history")
        with open(file_path) as f:
            data = json.load(f)
            readings = data.get("readings", [])
            # Validate and trim to max size
            readings = [float(r) for r in readings if isinstance(r, (int, float))]
            return readings[-MAX_OUTDOOR_TEMP_READINGS:]
    except FileNotFoundError:
        _LOGGER.debug("outdoor_temp_history.json not found - starting fresh")
        return []
    except json.JSONDecodeError as e:
        _LOGGER.warning(f"Invalid JSON in outdoor_temp_history.json: {e}")
        return []
    except Exception as e:
        _LOGGER.debug(f"Failed to load outdoor_temp_history.json: {e}")
        return []


def save_outdoor_temp_history(readings: list) -> bool:
    """Save outdoor temperature history to storage.

    v2.2.0: Persists rolling outdoor temp readings across HA restarts.

    IMPORTANT: This is a SYNC function. Callers in async context
    MUST use `await hass.async_add_executor_job(save_outdoor_temp_history, readings)`.

    Args:
        readings: List of float temperature readings (most recent last).

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        file_path = _get_file_path("outdoor_temp_history")
        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Trim to max size before saving
        trimmed = readings[-MAX_OUTDOOR_TEMP_READINGS:]
        with open(file_path, 'w') as f:
            json.dump({"readings": trimmed}, f)
        return True
    except Exception as e:
        _LOGGER.debug(f"Failed to save outdoor_temp_history.json: {e}")
        return False
