"""Smart Heating Manager for Tado CE.

Provides intelligent heating analytics including:
- Temperature rate calculation (heating/cooling rates)
- Time to target estimation
- Comfort risk prediction
- Weather compensation (Phase 3)
- Recorder integration for historical data (Phase 3)
- File persistence for data backup (Phase 3)

This module can bootstrap from HA recorder history on startup,
allowing immediate rate calculations without waiting for data collection.
Data is also persisted to file as backup for when recorder is unavailable.
"""
import json
import logging
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Configuration
HISTORY_WINDOW_HOURS = 2  # Keep 2 hours of history for real-time tracking
RECORDER_HISTORY_HOURS = 24  # Load 24 hours from recorder on startup
MIN_DATA_POINTS = 3  # Minimum points needed for rate calculation
MIN_TIME_SPAN_MINUTES = 15  # Minimum time span for meaningful rate
CACHE_SAVE_INTERVAL_MINUTES = 15  # Save cache every 15 minutes

# Weather compensation presets: (cold_threshold, cold_factor, warm_threshold, warm_factor)
WEATHER_COMPENSATION_PRESETS = {
    "none": (None, 1.0, None, 1.0),
    "light": (5, 1.1, 15, 0.95),
    "moderate": (5, 1.2, 10, 0.9),
    "aggressive": (0, 1.4, 10, 0.8),
}


@dataclass
class TemperatureReading:
    """A single temperature reading with context."""
    timestamp: datetime
    temperature: float
    is_heating: bool  # True if HVAC is actively heating/cooling
    target_temperature: Optional[float] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature": self.temperature,
            "is_heating": self.is_heating,
            "target_temperature": self.target_temperature
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TemperatureReading":
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            temperature=data["temperature"],
            is_heating=data["is_heating"],
            target_temperature=data.get("target_temperature")
        )


class ZoneHistory:
    """Temperature history for a single zone."""
    
    def __init__(self, zone_id: str, zone_name: str):
        self.zone_id = zone_id
        self.zone_name = zone_name
        self.readings: list[TemperatureReading] = []
        self._last_heating_rate: Optional[float] = None
        self._last_cooling_rate: Optional[float] = None
        self._rate_updated_at: Optional[datetime] = None
        # Baseline rates from long-term statistics (Tier 3)
        self._baseline_heating_rate: Optional[float] = None
        self._baseline_cooling_rate: Optional[float] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "readings": [r.to_dict() for r in self.readings]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ZoneHistory":
        """Create from dictionary."""
        zone = cls(data["zone_id"], data["zone_name"])
        zone.readings = [TemperatureReading.from_dict(r) for r in data.get("readings", [])]
        return zone
    
    def add_reading(self, reading: TemperatureReading) -> None:
        """Add a temperature reading and prune old data."""
        self.readings.append(reading)
        self._prune_old_readings()
    
    def _prune_old_readings(self) -> None:
        """Remove readings older than HISTORY_WINDOW_HOURS."""
        cutoff = datetime.now() - timedelta(hours=HISTORY_WINDOW_HOURS)
        self.readings = [r for r in self.readings if r.timestamp > cutoff]
    
    def get_heating_rate(self) -> Optional[float]:
        """Calculate heating rate (°C/hour) when HVAC is active.
        
        Uses linear regression on temperature readings where is_heating=True.
        Falls back to baseline rate from long-term statistics if not enough data.
        Returns positive value for heating, negative for cooling (AC).
        """
        heating_readings = [r for r in self.readings if r.is_heating]
        rate = self._calculate_rate(heating_readings)
        
        # Fallback to baseline if no real-time rate available
        if rate is None and self._baseline_heating_rate is not None:
            return self._baseline_heating_rate
        
        return rate
    
    def get_cooling_rate(self) -> Optional[float]:
        """Calculate cooling rate (°C/hour) when HVAC is off.
        
        Uses linear regression on temperature readings where is_heating=False.
        Falls back to baseline rate from long-term statistics if not enough data.
        Returns negative value (temperature dropping) typically.
        """
        cooling_readings = [r for r in self.readings if not r.is_heating]
        rate = self._calculate_rate(cooling_readings)
        
        # Fallback to baseline if no real-time rate available
        if rate is None and self._baseline_cooling_rate is not None:
            return self._baseline_cooling_rate
        
        return rate
    
    def _calculate_rate(self, readings: list[TemperatureReading]) -> Optional[float]:
        """Calculate temperature rate using linear regression.
        
        Args:
            readings: List of temperature readings to analyze
            
        Returns:
            Rate in °C/hour, or None if insufficient data
        """
        if len(readings) < MIN_DATA_POINTS:
            return None
        
        # Check time span
        time_span = (readings[-1].timestamp - readings[0].timestamp).total_seconds()
        if time_span < MIN_TIME_SPAN_MINUTES * 60:
            return None
        
        # Simple linear regression: y = mx + b
        # x = time in hours from first reading
        # y = temperature
        n = len(readings)
        base_time = readings[0].timestamp
        
        sum_x = 0.0
        sum_y = 0.0
        sum_xy = 0.0
        sum_x2 = 0.0
        
        for r in readings:
            x = (r.timestamp - base_time).total_seconds() / 3600  # Hours
            y = r.temperature
            sum_x += x
            sum_y += y
            sum_xy += x * y
            sum_x2 += x * x
        
        # Calculate slope (rate)
        denominator = n * sum_x2 - sum_x * sum_x
        if abs(denominator) < 0.0001:
            return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        
        # Round to 2 decimal places
        return round(slope, 2)
    
    def get_time_to_target(self, current_temp: float, target_temp: float, zone_type: str = "HEATING") -> Optional[int]:
        """Estimate time to reach target temperature in minutes.
        
        Args:
            current_temp: Current temperature
            target_temp: Target temperature
            zone_type: "HEATING" or "AIR_CONDITIONING"
            
        Returns:
            Estimated minutes to reach target, or None if cannot estimate
        """
        diff = target_temp - current_temp
        
        if abs(diff) < 0.1:
            return 0  # Already at target
        
        # For HEATING zones: only calculate if we need to heat up (current < target)
        # For AC zones: only calculate if we need to cool down (current > target)
        if zone_type == "HEATING":
            if diff <= 0:
                # Current >= target, no heating needed
                return 0
            rate = self.get_heating_rate()
        else:  # AIR_CONDITIONING
            if diff >= 0:
                # Current <= target, no cooling needed
                return 0
            rate = self.get_cooling_rate()
        
        if rate is None or abs(rate) < 0.01:
            return None
        
        # Time = distance / speed
        hours = abs(diff) / abs(rate)
        minutes = int(hours * 60)
        
        # Cap at reasonable maximum (8 hours)
        return min(minutes, 480)
    
    def predict_temperature(self, minutes_ahead: int, is_heating: bool) -> Optional[float]:
        """Predict temperature at a future time.
        
        Args:
            minutes_ahead: Minutes into the future
            is_heating: Whether HVAC will be active
            
        Returns:
            Predicted temperature, or None if cannot predict
        """
        if not self.readings:
            return None
        
        current_temp = self.readings[-1].temperature
        rate = self.get_heating_rate() if is_heating else self.get_cooling_rate()
        
        if rate is None:
            return None
        
        hours = minutes_ahead / 60
        predicted = current_temp + (rate * hours)
        
        return round(predicted, 1)


class SmartHeatingManager:
    """Manages smart heating analytics for all zones."""
    
    def __init__(self, hass: "HomeAssistant" = None, home_id: str = ""):
        self._zones: dict[str, ZoneHistory] = {}
        self._enabled = False
        self._hass = hass
        self._home_id = home_id
        self._last_save_time: Optional[datetime] = None
        # Weather compensation settings
        self._outdoor_temp_entity: str = ""
        self._weather_compensation: str = "none"
        self._use_feels_like: bool = False
    
    def _get_cache_file(self) -> Path:
        """Get the cache file path."""
        from .const import DATA_DIR
        if self._home_id:
            return DATA_DIR / f"smart_heating_cache_{self._home_id}.json"
        return DATA_DIR / "smart_heating_cache.json"
    
    def save_to_file(self) -> bool:
        """Save zone data to file for persistence.
        
        Returns:
            True if save was successful
        """
        if not self._zones:
            return True
        
        try:
            from .const import DATA_DIR
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            
            cache_file = self._get_cache_file()
            data = {
                "saved_at": datetime.now().isoformat(),
                "zones": {zone_id: zone.to_dict() for zone_id, zone in self._zones.items()}
            }
            
            # Atomic write using temp file
            import tempfile
            import shutil
            
            with tempfile.NamedTemporaryFile(
                mode='w', dir=DATA_DIR, delete=False, suffix='.tmp'
            ) as tmp:
                json.dump(data, tmp, indent=2)
                temp_path = tmp.name
            
            shutil.move(temp_path, cache_file)
            self._last_save_time = datetime.now()
            
            total_readings = sum(len(z.readings) for z in self._zones.values())
            _LOGGER.debug(
                f"Smart Heating: Saved {len(self._zones)} zones, "
                f"{total_readings} readings to {cache_file.name}"
            )
            return True
            
        except Exception as e:
            _LOGGER.warning(f"Smart Heating: Failed to save cache: {e}")
            return False
    
    def load_from_file(self) -> int:
        """Load zone data from file.
        
        Returns:
            Number of readings loaded
        """
        cache_file = self._get_cache_file()
        
        if not cache_file.exists():
            _LOGGER.debug(f"Smart Heating: No cache file found at {cache_file}")
            return 0
        
        try:
            with open(cache_file) as f:
                data = json.load(f)
            
            zones_data = data.get("zones", {})
            total_readings = 0
            
            for zone_id, zone_data in zones_data.items():
                zone = ZoneHistory.from_dict(zone_data)
                # Prune old readings
                zone._prune_old_readings()
                
                if zone.readings:
                    self._zones[zone_id] = zone
                    total_readings += len(zone.readings)
            
            saved_at = data.get("saved_at", "unknown")
            _LOGGER.info(
                f"Smart Heating: Loaded {len(self._zones)} zones, "
                f"{total_readings} readings from cache (saved at {saved_at})"
            )
            return total_readings
            
        except json.JSONDecodeError as e:
            _LOGGER.warning(f"Smart Heating: Invalid cache file: {e}")
            return 0
        except Exception as e:
            _LOGGER.warning(f"Smart Heating: Failed to load cache: {e}")
            return 0
    
    def maybe_save(self) -> None:
        """Save to file if enough time has passed since last save."""
        if self._last_save_time is None:
            self.save_to_file()
            return
        
        elapsed = datetime.now() - self._last_save_time
        if elapsed.total_seconds() >= CACHE_SAVE_INTERVAL_MINUTES * 60:
            self.save_to_file()
    
    def configure_weather(
        self,
        outdoor_temp_entity: str = "",
        weather_compensation: str = "none",
        use_feels_like: bool = False
    ) -> None:
        """Configure weather compensation settings.
        
        Args:
            outdoor_temp_entity: Entity ID for outdoor temperature
            weather_compensation: Preset name (none/light/moderate/aggressive)
            use_feels_like: Whether to use feels-like temperature
        """
        self._outdoor_temp_entity = outdoor_temp_entity
        self._weather_compensation = weather_compensation
        self._use_feels_like = use_feels_like
        _LOGGER.info(
            f"Smart Heating: Weather compensation configured - "
            f"entity={outdoor_temp_entity}, preset={weather_compensation}, "
            f"feels_like={use_feels_like}"
        )
    
    def enable(self) -> None:
        """Enable smart heating tracking."""
        self._enabled = True
        _LOGGER.info("Smart Heating Manager enabled")
    
    def disable(self) -> None:
        """Disable smart heating tracking."""
        self._enabled = False
        _LOGGER.info("Smart Heating Manager disabled")
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
    
    def get_zone(self, zone_id: str, zone_name: str = "") -> ZoneHistory:
        """Get or create zone history tracker."""
        if zone_id not in self._zones:
            self._zones[zone_id] = ZoneHistory(zone_id, zone_name or f"Zone {zone_id}")
        return self._zones[zone_id]
    
    def record_temperature(
        self,
        zone_id: str,
        zone_name: str,
        temperature: float,
        is_heating: bool,
        target_temperature: Optional[float] = None
    ) -> None:
        """Record a temperature reading for a zone.
        
        This should be called on each zone state update.
        
        Args:
            zone_id: Zone identifier
            zone_name: Human-readable zone name
            temperature: Current temperature
            is_heating: Whether HVAC is actively heating/cooling
            target_temperature: Current target temperature (optional)
        """
        if not self._enabled:
            return
        
        zone = self.get_zone(zone_id, zone_name)
        reading = TemperatureReading(
            timestamp=datetime.now(),
            temperature=temperature,
            is_heating=is_heating,
            target_temperature=target_temperature
        )
        zone.add_reading(reading)
        
        # Periodically save to file
        self.maybe_save()
        
        _LOGGER.debug(
            f"Smart Heating: Recorded {zone_name} temp={temperature}°C "
            f"heating={is_heating} target={target_temperature}"
        )
    
    def get_heating_rate(self, zone_id: str) -> Optional[float]:
        """Get heating rate for a zone in °C/hour."""
        if zone_id not in self._zones:
            return None
        return self._zones[zone_id].get_heating_rate()
    
    def get_cooling_rate(self, zone_id: str) -> Optional[float]:
        """Get cooling rate for a zone in °C/hour."""
        if zone_id not in self._zones:
            return None
        return self._zones[zone_id].get_cooling_rate()
    
    def get_time_to_target(
        self,
        zone_id: str,
        current_temp: float,
        target_temp: float,
        zone_type: str = "HEATING"
    ) -> Optional[int]:
        """Get estimated time to reach target in minutes."""
        if zone_id not in self._zones:
            return None
        return self._zones[zone_id].get_time_to_target(current_temp, target_temp, zone_type)
    
    def is_comfort_at_risk(
        self,
        zone_id: str,
        current_temp: float,
        target_temp: float,
        minutes_until_schedule: int,
        is_currently_heating: bool,
        zone_type: str = "HEATING"
    ) -> Optional[bool]:
        """Check if comfort target is at risk of being missed.
        
        Args:
            zone_id: Zone identifier
            current_temp: Current temperature
            target_temp: Target temperature at schedule time
            minutes_until_schedule: Minutes until next schedule change
            is_currently_heating: Whether HVAC is currently active
            zone_type: "HEATING" or "AIR_CONDITIONING"
            
        Returns:
            True if target will likely be missed, False if OK, None if unknown
        """
        if zone_id not in self._zones:
            return None
        
        diff = target_temp - current_temp
        
        # For HEATING zones: only at risk if we need to heat up (current < target)
        # For AC zones: only at risk if we need to cool down (current > target)
        if zone_type == "HEATING":
            if diff <= 0:
                # Current >= target, already comfortable, no risk
                return False
        else:  # AIR_CONDITIONING
            if diff >= 0:
                # Current <= target, already comfortable, no risk
                return False
        
        zone = self._zones[zone_id]
        predicted = zone.predict_temperature(minutes_until_schedule, is_currently_heating)
        
        if predicted is None:
            return None
        
        # For heating: at risk if predicted < target - 0.5°C
        # For cooling (AC): at risk if predicted > target + 0.5°C
        if zone_type == "HEATING":
            return predicted < (target_temp - 0.5)
        else:
            return predicted > (target_temp + 0.5)
    
    def get_stats(self) -> dict:
        """Get statistics about tracked zones."""
        return {
            "enabled": self._enabled,
            "zones_tracked": len(self._zones),
            "weather_compensation": self._weather_compensation,
            "outdoor_temp_entity": self._outdoor_temp_entity,
            "use_feels_like": self._use_feels_like,
            "zones": {
                zone_id: {
                    "name": zone.zone_name,
                    "readings": len(zone.readings),
                    "heating_rate": zone.get_heating_rate(),
                    "cooling_rate": zone.get_cooling_rate(),
                }
                for zone_id, zone in self._zones.items()
            }
        }
    
    def get_outdoor_temperature(self) -> Optional[float]:
        """Get current outdoor temperature from configured entity.
        
        Returns:
            Outdoor temperature in °C, or None if not available
        """
        if not self._hass or not self._outdoor_temp_entity:
            return None
        
        try:
            state = self._hass.states.get(self._outdoor_temp_entity)
            if state is None or state.state in ('unknown', 'unavailable'):
                return None
            
            # Check if it's a weather entity (has temperature attribute)
            if self._outdoor_temp_entity.startswith('weather.'):
                temp = state.attributes.get('temperature')
                if temp is not None:
                    if self._use_feels_like:
                        # Try to get feels-like from attributes
                        feels_like = self._get_feels_like_from_weather(state)
                        if feels_like is not None:
                            return feels_like
                    return float(temp)
            else:
                # Regular sensor entity
                return float(state.state)
        except (ValueError, TypeError) as e:
            _LOGGER.debug(f"Failed to get outdoor temperature: {e}")
            return None
        
        return None
    
    def _get_feels_like_from_weather(self, state) -> Optional[float]:
        """Extract feels-like temperature from weather entity.
        
        Different weather integrations use different attribute names:
        - AccuWeather: apparent_temperature
        - PirateWeather: apparent_temperature
        - OpenWeatherMap: feels_like
        - Tomorrow.io: (calculate from temp/humidity/wind)
        
        Args:
            state: Weather entity state object
            
        Returns:
            Feels-like temperature, or None if not available
        """
        attrs = state.attributes
        
        # Try common attribute names
        for attr_name in ['apparent_temperature', 'feels_like', 'feelslike']:
            if attr_name in attrs and attrs[attr_name] is not None:
                try:
                    return float(attrs[attr_name])
                except (ValueError, TypeError):
                    continue
        
        # Calculate feels-like if we have temp, humidity, and wind
        temp = attrs.get('temperature')
        humidity = attrs.get('humidity')
        wind_speed = attrs.get('wind_speed')
        
        if temp is not None and humidity is not None:
            return self._calculate_feels_like(
                float(temp),
                float(humidity),
                float(wind_speed) if wind_speed else 0
            )
        
        return None
    
    def _calculate_feels_like(
        self,
        temp: float,
        humidity: float,
        wind_speed: float = 0
    ) -> float:
        """Calculate feels-like temperature.
        
        Uses wind chill for cold weather (≤10°C) and heat index for warm weather.
        
        Args:
            temp: Temperature in °C
            humidity: Relative humidity (0-100)
            wind_speed: Wind speed in km/h (default 0)
            
        Returns:
            Feels-like temperature in °C
        """
        # Wind chill for cold weather (≤10°C and wind > 4.8 km/h)
        if temp <= 10 and wind_speed > 4.8:
            # Wind chill formula (Environment Canada)
            # T_wc = 13.12 + 0.6215*T - 11.37*V^0.16 + 0.3965*T*V^0.16
            v_pow = wind_speed ** 0.16
            feels_like = 13.12 + 0.6215 * temp - 11.37 * v_pow + 0.3965 * temp * v_pow
            return round(feels_like, 1)
        
        # Heat index for warm weather (≥27°C)
        if temp >= 27:
            # Simplified heat index formula
            # HI = -8.785 + 1.611*T + 2.339*RH - 0.146*T*RH - 0.012*T² - 0.016*RH² + 0.002*T²*RH + 0.001*T*RH² - 0.000002*T²*RH²
            t = temp
            rh = humidity
            hi = (-8.785 + 1.611 * t + 2.339 * rh - 0.146 * t * rh 
                  - 0.012 * t * t - 0.016 * rh * rh 
                  + 0.002 * t * t * rh + 0.001 * t * rh * rh 
                  - 0.000002 * t * t * rh * rh)
            return round(hi, 1)
        
        # For moderate temperatures, just return actual temp
        return temp
    
    def get_compensated_rate(self, base_rate: float, for_heating: bool = True) -> float:
        """Apply weather compensation to a heating/cooling rate.
        
        Args:
            base_rate: Base rate in °C/hour
            for_heating: True for heating rate, False for cooling rate
            
        Returns:
            Compensated rate in °C/hour
        """
        if self._weather_compensation == "none":
            return base_rate
        
        outdoor_temp = self.get_outdoor_temperature()
        if outdoor_temp is None:
            return base_rate
        
        preset = WEATHER_COMPENSATION_PRESETS.get(
            self._weather_compensation,
            WEATHER_COMPENSATION_PRESETS["none"]
        )
        cold_thresh, cold_factor, warm_thresh, warm_factor = preset
        
        # For heating: cold weather = slower heating (more heat loss)
        # For cooling: cold weather = faster cooling (more heat loss)
        factor = 1.0
        
        if cold_thresh is not None and outdoor_temp < cold_thresh:
            if for_heating:
                # Cold weather: heating takes longer (divide by factor)
                factor = 1.0 / cold_factor
            else:
                # Cold weather: cooling is faster (multiply by factor)
                factor = cold_factor
        elif warm_thresh is not None and outdoor_temp > warm_thresh:
            if for_heating:
                # Warm weather: heating is faster (multiply by factor)
                factor = 1.0 / warm_factor
            else:
                # Warm weather: cooling is slower (divide by factor)
                factor = warm_factor
        
        compensated = base_rate * factor
        
        _LOGGER.debug(
            f"Weather compensation: outdoor={outdoor_temp}°C, "
            f"preset={self._weather_compensation}, factor={factor:.2f}, "
            f"base_rate={base_rate:.2f}, compensated={compensated:.2f}"
        )
        
        return round(compensated, 2)
    
    def get_compensated_time_to_target(
        self,
        zone_id: str,
        current_temp: float,
        target_temp: float,
        zone_type: str = "HEATING"
    ) -> Optional[int]:
        """Get weather-compensated time to reach target in minutes.
        
        Args:
            zone_id: Zone identifier
            current_temp: Current temperature
            target_temp: Target temperature
            zone_type: "HEATING" or "AIR_CONDITIONING"
            
        Returns:
            Estimated minutes to reach target with weather compensation
        """
        if zone_id not in self._zones:
            return None
        
        zone = self._zones[zone_id]
        diff = target_temp - current_temp
        
        if abs(diff) < 0.1:
            return 0  # Already at target
        
        # For HEATING zones: only calculate if we need to heat up (current < target)
        # For AC zones: only calculate if we need to cool down (current > target)
        if zone_type == "HEATING":
            if diff <= 0:
                # Current >= target, no heating needed
                return 0
            base_rate = zone.get_heating_rate()
            for_heating = True
        else:  # AIR_CONDITIONING
            if diff >= 0:
                # Current <= target, no cooling needed
                return 0
            base_rate = zone.get_cooling_rate()
            for_heating = False
        
        if base_rate is None or abs(base_rate) < 0.01:
            return None
        
        # Apply weather compensation
        compensated_rate = self.get_compensated_rate(base_rate, for_heating)
        
        if abs(compensated_rate) < 0.01:
            return None
        
        # Time = distance / speed
        hours = abs(diff) / abs(compensated_rate)
        minutes = int(hours * 60)
        
        # Cap at reasonable maximum (8 hours)
        return min(minutes, 480)


# Global instance
_manager: Optional[SmartHeatingManager] = None


def get_smart_heating_manager() -> SmartHeatingManager:
    """Get the global SmartHeatingManager instance."""
    global _manager
    if _manager is None:
        _manager = SmartHeatingManager()
    return _manager


async def async_load_history_from_recorder(
    hass: "HomeAssistant",
    manager: SmartHeatingManager,
    climate_entity_ids: list[str],
    entity_to_zone_id: dict[str, str] = None
) -> int:
    """Load historical temperature data from HA recorder on startup.
    
    This allows immediate rate calculations without waiting for data collection.
    Queries the last RECORDER_HISTORY_HOURS of climate entity history.
    
    Args:
        hass: Home Assistant instance
        manager: SmartHeatingManager to populate
        climate_entity_ids: List of climate entity IDs to load history for
        entity_to_zone_id: Mapping from entity name to numeric zone_id
            e.g., {"master": "1", "dining": "2"}. Required for correct zone matching.
        
    Returns:
        Number of data points loaded
    """
    if not climate_entity_ids or not entity_to_zone_id:
        return 0
    
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
        from homeassistant.util import dt as dt_util
        
        end_time = dt_util.utcnow()
        start_time = end_time - timedelta(hours=RECORDER_HISTORY_HOURS)
        
        _LOGGER.info(
            f"Smart Heating: Loading {RECORDER_HISTORY_HOURS}h history for "
            f"{len(climate_entity_ids)} climate entities"
        )
        
        # Query history from recorder (runs in executor to avoid blocking)
        def _get_history():
            return get_significant_states(
                hass,
                start_time,
                end_time,
                climate_entity_ids,
                significant_changes_only=False
            )
        
        states = await get_instance(hass).async_add_executor_job(_get_history)
        
        if not states:
            _LOGGER.debug("Smart Heating: No history found in recorder")
            return 0
        
        total_points = 0
        
        for entity_id, history in states.items():
            if not history:
                continue
            
            # Extract entity name from entity_id (e.g., climate.master -> master)
            entity_name = entity_id.replace("climate.", "")
            
            # Get numeric zone_id from mapping
            zone_id = entity_to_zone_id.get(entity_name)
            if not zone_id:
                _LOGGER.debug(f"Smart Heating: No zone_id mapping for {entity_name}")
                continue
            
            zone_name = entity_name.replace("_", " ").title()
            zone = manager.get_zone(zone_id, zone_name)
            points_added = 0
            
            for state in history:
                try:
                    # Skip unavailable/unknown states
                    if state.state in ('unavailable', 'unknown'):
                        continue
                    
                    # Get current temperature from attributes
                    attrs = state.attributes
                    current_temp = attrs.get('current_temperature')
                    
                    if current_temp is None:
                        continue
                    
                    # Determine if heating was active from hvac_action
                    hvac_action = attrs.get('hvac_action', 'idle')
                    is_heating = hvac_action in ('heating', 'cooling')
                    
                    # Get target temperature
                    target_temp = attrs.get('temperature')
                    
                    # Get timestamp (ensure UTC)
                    timestamp = state.last_changed
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=dt_util.UTC)
                    
                    # Convert to local datetime for consistency with live readings
                    local_timestamp = dt_util.as_local(timestamp)
                    
                    reading = TemperatureReading(
                        timestamp=local_timestamp.replace(tzinfo=None),
                        temperature=float(current_temp),
                        is_heating=is_heating,
                        target_temperature=float(target_temp) if target_temp else None
                    )
                    
                    # Add directly to readings list (bypass add_reading to avoid pruning)
                    zone.readings.append(reading)
                    points_added += 1
                    
                except (ValueError, TypeError, AttributeError) as e:
                    _LOGGER.debug(f"Smart Heating: Skipping invalid history state: {e}")
                    continue
            
            # Sort readings by timestamp and prune old ones
            zone.readings.sort(key=lambda r: r.timestamp)
            zone._prune_old_readings()
            
            if points_added > 0:
                _LOGGER.info(
                    f"Smart Heating: Loaded {points_added} history points for {zone_name}, "
                    f"{len(zone.readings)} after pruning"
                )
                total_points += len(zone.readings)
        
        _LOGGER.info(f"Smart Heating: Total {total_points} data points loaded from recorder")
        return total_points
        
    except ImportError:
        _LOGGER.debug("Smart Heating: Recorder component not available")
        return 0
    except Exception as e:
        _LOGGER.warning(f"Smart Heating: Failed to load history from recorder: {e}")
        return 0


async def async_load_baseline_from_statistics(
    hass: "HomeAssistant",
    manager: SmartHeatingManager,
    zone_sensor_mapping: dict[str, str]
) -> dict[str, dict]:
    """Load baseline heating/cooling rates from long-term statistics.
    
    Long-term statistics provide hourly averages over weeks/months, which can
    be used to calculate more accurate baseline rates for each zone.
    
    This is Tier 3 of the 3-tier loading strategy:
    - Tier 1: Cache file (2h detailed data)
    - Tier 2: Recorder history (24h detailed states)
    - Tier 3: Long-term statistics (weeks of hourly averages)
    
    Args:
        hass: Home Assistant instance
        manager: SmartHeatingManager to update with baseline rates
        zone_sensor_mapping: Dict mapping zone_id to temperature sensor entity_id
            e.g., {"master": "sensor.master_temperature"}
            
    Returns:
        Dict of zone_id -> {"baseline_heating_rate": float, "baseline_cooling_rate": float}
    """
    if not zone_sensor_mapping:
        return {}
    
    try:
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
            get_last_statistics,
        )
        from homeassistant.components.recorder import get_instance
        from homeassistant.util import dt as dt_util
        
        # Get last 7 days of hourly statistics
        end_time = dt_util.utcnow()
        start_time = end_time - timedelta(days=7)
        
        statistic_ids = list(zone_sensor_mapping.values())
        
        _LOGGER.info(
            f"Smart Heating: Loading 7-day statistics for {len(statistic_ids)} sensors"
        )
        
        # Query statistics (runs in executor)
        def _get_statistics():
            return statistics_during_period(
                hass,
                start_time,
                end_time,
                statistic_ids=statistic_ids,
                period="hour",
                units={"temperature": "°C"},
                types={"mean", "min", "max"}
            )
        
        stats = await get_instance(hass).async_add_executor_job(_get_statistics)
        
        if not stats:
            _LOGGER.debug("Smart Heating: No long-term statistics found")
            return {}
        
        results = {}
        
        for zone_id, sensor_id in zone_sensor_mapping.items():
            if sensor_id not in stats:
                continue
            
            sensor_stats = stats[sensor_id]
            if len(sensor_stats) < 24:  # Need at least 24 hours
                _LOGGER.debug(
                    f"Smart Heating: Not enough statistics for {zone_id} "
                    f"({len(sensor_stats)} points)"
                )
                continue
            
            # Calculate hourly temperature changes
            temp_changes = []
            for i in range(1, len(sensor_stats)):
                prev = sensor_stats[i - 1]
                curr = sensor_stats[i]
                
                prev_mean = prev.get("mean")
                curr_mean = curr.get("mean")
                
                if prev_mean is not None and curr_mean is not None:
                    change = curr_mean - prev_mean
                    temp_changes.append(change)
            
            if not temp_changes:
                continue
            
            # Separate positive (heating) and negative (cooling) changes
            heating_changes = [c for c in temp_changes if c > 0.05]
            cooling_changes = [c for c in temp_changes if c < -0.05]
            
            baseline_heating = None
            baseline_cooling = None
            
            if heating_changes:
                # Use median to avoid outliers
                heating_changes.sort()
                mid = len(heating_changes) // 2
                baseline_heating = round(heating_changes[mid], 2)
            
            if cooling_changes:
                cooling_changes.sort()
                mid = len(cooling_changes) // 2
                baseline_cooling = round(cooling_changes[mid], 2)
            
            results[zone_id] = {
                "baseline_heating_rate": baseline_heating,
                "baseline_cooling_rate": baseline_cooling,
                "data_points": len(sensor_stats),
                "heating_samples": len(heating_changes),
                "cooling_samples": len(cooling_changes)
            }
            
            # Store baseline in zone history for fallback
            zone = manager.get_zone(zone_id)
            zone._baseline_heating_rate = baseline_heating
            zone._baseline_cooling_rate = baseline_cooling
            
            _LOGGER.info(
                f"Smart Heating: {zone_id} baseline rates from {len(sensor_stats)} hours: "
                f"heating={baseline_heating}°C/h, cooling={baseline_cooling}°C/h"
            )
        
        return results
        
    except ImportError as e:
        _LOGGER.debug(f"Smart Heating: Statistics API not available: {e}")
        return {}
    except Exception as e:
        _LOGGER.warning(f"Smart Heating: Failed to load statistics: {e}")
        return {}
