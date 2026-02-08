"""Constants for Tado CE integration."""
from pathlib import Path
import os
from typing import Optional

DOMAIN = "tado_ce"
MANUFACTURER = "Joe Yiu (@hiall-fyi)"

# Data directory (persistent storage)
# v1.5.2: Moved from custom_components/tado_ce/data/ to .storage/tado_ce/
# This prevents HACS upgrades from overwriting credentials and data files
# Use environment variable if set (for testing), otherwise use standard HA path
_BASE_CONFIG_DIR = os.environ.get("TADO_CE_CONFIG_DIR", "/config")
DATA_DIR = Path(_BASE_CONFIG_DIR) / ".storage" / "tado_ce"

# Legacy data directory (for migration from v1.5.1 and earlier)
LEGACY_DATA_DIR = Path(_BASE_CONFIG_DIR) / "custom_components" / "tado_ce" / "data"

# v1.8.0: Multi-home support - per-home data files
# Files that are per-home (need home_id suffix)
PER_HOME_FILES = [
    "config", "zones", "zones_info", "ratelimit", "weather",
    "mobile_devices", "home_state", "api_call_history", "offsets",
    "ac_capabilities", "schedules"
]


def get_data_file(base_name: str, home_id: Optional[str] = None) -> Path:
    """Get data file path, with optional home_id suffix for multi-home support.
    
    v1.8.0: Supports per-home data files for multi-home setups.
    
    Args:
        base_name: Base filename without extension (e.g., "zones", "config")
        home_id: Optional home ID for per-home files
        
    Returns:
        Path to the data file
        
    Examples:
        get_data_file("zones") -> /config/.storage/tado_ce/zones.json
        get_data_file("zones", "12345") -> /config/.storage/tado_ce/zones_12345.json
    """
    if home_id and base_name in PER_HOME_FILES:
        return DATA_DIR / f"{base_name}_{home_id}.json"
    return DATA_DIR / f"{base_name}.json"


def get_legacy_file(base_name: str) -> Path:
    """Get legacy file path (without home_id suffix).
    
    Used for backwards compatibility and migration.
    
    Args:
        base_name: Base filename without extension
        
    Returns:
        Path to the legacy data file
    """
    return DATA_DIR / f"{base_name}.json"


# Legacy file paths (for backwards compatibility)
# These are kept for existing code that imports them directly
# New code should use get_data_file() with home_id
CONFIG_FILE = DATA_DIR / "config.json"
ZONES_FILE = DATA_DIR / "zones.json"
ZONES_INFO_FILE = DATA_DIR / "zones_info.json"
RATELIMIT_FILE = DATA_DIR / "ratelimit.json"
WEATHER_FILE = DATA_DIR / "weather.json"
MOBILE_DEVICES_FILE = DATA_DIR / "mobile_devices.json"
HOME_STATE_FILE = DATA_DIR / "home_state.json"
API_CALL_HISTORY_FILE = DATA_DIR / "api_call_history.json"
OFFSETS_FILE = DATA_DIR / "offsets.json"
AC_CAPABILITIES_FILE = DATA_DIR / "ac_capabilities.json"

# API Base URLs
TADO_API_BASE = "https://my.tado.com/api/v2"
TADO_AUTH_URL = "https://login.tado.com/oauth2"
CLIENT_ID = "1bb50063-6b0c-4d11-bd99-387f4a91cc46"

# API Endpoints (relative to TADO_API_BASE)
API_ENDPOINT_ME = f"{TADO_API_BASE}/me"
API_ENDPOINT_HOMES = f"{TADO_API_BASE}/homes"  # + /{home_id}
API_ENDPOINT_DEVICES = f"{TADO_API_BASE}/devices"  # + /{serial}

# Auth Endpoints
AUTH_ENDPOINT_DEVICE = f"{TADO_AUTH_URL}/device_authorize"
AUTH_ENDPOINT_TOKEN = f"{TADO_AUTH_URL}/token"

# Default zone names (fallback)
DEFAULT_ZONE_NAMES = {
    "0": "Hot Water", "1": "Dining", "4": "Guest", "5": "Study",
    "6": "Dressing", "9": "Lounge", "11": "Hallway", "13": "Bathroom",
    "16": "Ensuite", "18": "Master"
}

# =============================================================================
# Unit Conversion Constants (v1.9.0)
# =============================================================================

# Wind Speed Conversion Factors (to km/h)
WIND_SPEED_CONVERSIONS = {
    # km/h variants (no conversion needed)
    'kmh': 1.0,
    'km/h': 1.0,
    'kph': 1.0,
    # m/s to km/h
    'ms': 3.6,
    'm/s': 3.6,
    # mph to km/h
    'mph': 1.60934,
    'mi/h': 1.60934,
    # knots to km/h
    'kn': 1.852,
    'kt': 1.852,
    'knots': 1.852,
    # ft/s to km/h
    'fts': 1.09728,
    'ft/s': 1.09728,
}

# Temperature Conversion Constants
FAHRENHEIT_TO_CELSIUS_OFFSET = 32
FAHRENHEIT_TO_CELSIUS_RATIO = 5 / 9

# Wind Chill Formula Constants (Environment Canada)
# T_wc = 13.12 + 0.6215*T - 11.37*V^0.16 + 0.3965*T*V^0.16
WIND_CHILL_CONST_A = 13.12
WIND_CHILL_CONST_B = 0.6215
WIND_CHILL_CONST_C = 11.37
WIND_CHILL_CONST_D = 0.3965
WIND_CHILL_EXPONENT = 0.16
WIND_CHILL_TEMP_THRESHOLD = 10  # °C - only apply wind chill at or below this
WIND_CHILL_WIND_THRESHOLD = 4.8  # km/h - minimum wind speed for wind chill

# Heat Index Formula Constants
# HI = -8.785 + 1.611*T + 2.339*RH - 0.146*T*RH - 0.012*T² - 0.016*RH² 
#      + 0.002*T²*RH + 0.001*T*RH² - 0.000002*T²*RH²
HEAT_INDEX_CONST_A = -8.785
HEAT_INDEX_CONST_B = 1.611
HEAT_INDEX_CONST_C = 2.339
HEAT_INDEX_CONST_D = -0.146
HEAT_INDEX_CONST_E = -0.012
HEAT_INDEX_CONST_F = -0.016
HEAT_INDEX_CONST_G = 0.002
HEAT_INDEX_CONST_H = 0.001
HEAT_INDEX_CONST_I = -0.000002
HEAT_INDEX_TEMP_THRESHOLD = 27  # °C - only apply heat index at or above this

# Weather compensation presets: (cold_threshold, cold_factor, warm_threshold, warm_factor)
# - cold_threshold: Apply cold factor when outdoor temp is below this (°C)
# - cold_factor: Multiplier for heating rate in cold weather (>1 = slower heating)
# - warm_threshold: Apply warm factor when outdoor temp is above this (°C)
# - warm_factor: Multiplier for heating rate in warm weather (<1 = faster heating)
WEATHER_COMPENSATION_PRESETS = {
    "none": (None, 1.0, None, 1.0),
    "light": (5, 1.1, 15, 0.95),
    "moderate": (5, 1.2, 10, 0.9),
    "aggressive": (0, 1.4, 10, 0.8),
}

# Smart Comfort Presets - comprehensive comfort optimization
# Combines outdoor temp compensation, humidity adjustment, and preheat factors
SMART_COMFORT_PRESETS = {
    "none": {
        # Outdoor temperature compensation
        "outdoor_cold_threshold": None,  # °C - apply cold offset below this
        "outdoor_cold_offset": 0.0,      # °C - add to target when cold
        "outdoor_warm_threshold": None,  # °C - apply warm offset above this
        "outdoor_warm_offset": 0.0,      # °C - subtract from target when warm
        "outdoor_shutoff_threshold": None,  # °C - turn off heating above this
        # Humidity compensation
        "humidity_high_threshold": 70,   # % - apply high humidity offset above this
        "humidity_high_offset": 0.0,     # °C - subtract when humid
        "humidity_low_threshold": 35,    # % - apply low humidity offset below this
        "humidity_low_offset": 0.0,      # °C - add when dry
        # Preheat duration factors
        "preheat_cold_factor": 1.0,      # Multiply preheat time when cold
        "preheat_warm_factor": 1.0,      # Multiply preheat time when warm
    },
    "light": {
        "outdoor_cold_threshold": 5,
        "outdoor_cold_offset": 0.5,
        "outdoor_warm_threshold": 15,
        "outdoor_warm_offset": 0.5,
        "outdoor_shutoff_threshold": None,
        "humidity_high_threshold": 70,
        "humidity_high_offset": 0.3,
        "humidity_low_threshold": 35,
        "humidity_low_offset": 0.3,
        "preheat_cold_factor": 1.1,
        "preheat_warm_factor": 0.95,
    },
    "moderate": {
        "outdoor_cold_threshold": 5,
        "outdoor_cold_offset": 1.0,
        "outdoor_warm_threshold": 15,
        "outdoor_warm_offset": 1.0,
        "outdoor_shutoff_threshold": None,
        "humidity_high_threshold": 70,
        "humidity_high_offset": 0.5,
        "humidity_low_threshold": 35,
        "humidity_low_offset": 0.5,
        "preheat_cold_factor": 1.2,
        "preheat_warm_factor": 0.9,
    },
    "aggressive": {
        "outdoor_cold_threshold": 5,
        "outdoor_cold_offset": 1.5,
        "outdoor_warm_threshold": 15,
        "outdoor_warm_offset": 1.5,
        "outdoor_shutoff_threshold": 18,  # Turn off heating when outdoor > 18°C
        "humidity_high_threshold": 70,
        "humidity_high_offset": 0.5,
        "humidity_low_threshold": 35,
        "humidity_low_offset": 0.5,
        "preheat_cold_factor": 1.4,
        "preheat_warm_factor": 0.8,
    },
}

# v1.11.0: Adaptive Smart Polling Constants
MIN_POLLING_INTERVAL = 5        # minutes (prevent excessive polling for high quotas)
MAX_POLLING_INTERVAL = 120      # minutes (ensure reasonable updates even with low quota)
POLLING_SAFETY_BUFFER = 0.90    # Reserve 10% quota for manual calls and unexpected usage

# v2.0.0: Quota Reserve Protection Constants
# When remaining quota falls below threshold, pause polling to reserve for manual operations
QUOTA_RESERVE_CALLS = 5         # Minimum reserved calls (absolute floor)
QUOTA_RESERVE_PERCENT = 0.05    # Reserve 5% of daily limit (whichever is larger)

# v1.11.0: Mold Risk Enhancement - Window U-values (W/m²K)
# Standard thermal transmittance values for different window types
WINDOW_U_VALUES = {
    "single_pane": 5.0,      # Single glazing (old buildings)
    "double_pane": 2.7,      # Double glazing (most common, default)
    "triple_pane": 1.0,      # Triple glazing (modern buildings)
    "passive_house": 0.8,    # Passive house standard (high performance)
}
DEFAULT_WINDOW_TYPE = "double_pane"
INTERIOR_SURFACE_HEAT_TRANSFER_COEFFICIENT = 8.0  # W/m²K (standard value for indoor surfaces)
