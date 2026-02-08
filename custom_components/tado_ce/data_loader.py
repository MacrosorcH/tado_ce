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
    """
    # If home_id is set, use it directly
    if _current_home_id:
        per_home_path = get_data_file(base_name, _current_home_id)
        if per_home_path.exists():
            return per_home_path
    
    # Auto-detect per-home files (for when home_id not set yet)
    # Look for files matching pattern: {base_name}_*.json
    import glob
    pattern = str(DATA_DIR / f"{base_name}_*.json")
    matches = glob.glob(pattern)
    if matches:
        # Return first match (should only be one per-home file)
        return Path(matches[0])
    
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
