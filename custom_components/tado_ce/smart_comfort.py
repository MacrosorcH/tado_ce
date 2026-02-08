"""Smart Comfort Manager for Tado CE.

Provides intelligent heating analytics including:
- Temperature rate calculation (heating/cooling rates)
- Time to target estimation
- Weather compensation (Phase 3)
- Recorder integration for historical data (Phase 3)
- File persistence for data backup (Phase 3)

This module can bootstrap from HA recorder history on startup,
allowing immediate rate calculations without waiting for data collection.
Data is also persisted to file as backup for when recorder is unavailable.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .const import (
    WIND_SPEED_CONVERSIONS,
    FAHRENHEIT_TO_CELSIUS_OFFSET,
    FAHRENHEIT_TO_CELSIUS_RATIO,
    WIND_CHILL_CONST_A,
    WIND_CHILL_CONST_B,
    WIND_CHILL_CONST_C,
    WIND_CHILL_CONST_D,
    WIND_CHILL_EXPONENT,
    WIND_CHILL_TEMP_THRESHOLD,
    WIND_CHILL_WIND_THRESHOLD,
    HEAT_INDEX_CONST_A,
    HEAT_INDEX_CONST_B,
    HEAT_INDEX_CONST_C,
    HEAT_INDEX_CONST_D,
    HEAT_INDEX_CONST_E,
    HEAT_INDEX_CONST_F,
    HEAT_INDEX_CONST_G,
    HEAT_INDEX_CONST_H,
    HEAT_INDEX_CONST_I,
    HEAT_INDEX_TEMP_THRESHOLD,
    WEATHER_COMPENSATION_PRESETS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Configuration
DEFAULT_HISTORY_DAYS = 7  # Default: keep 7 days of history
RECORDER_HISTORY_HOURS = 24  # Load 24 hours from recorder on startup
MIN_DATA_POINTS = 3  # Minimum points needed for rate calculation
MIN_TIME_SPAN_MINUTES = 15  # Minimum time span for meaningful rate
CACHE_SAVE_INTERVAL_MINUTES = 15  # Save cache every 15 minutes

# WEATHER_COMPENSATION_PRESETS imported from const.py

# Day type mapping for schedule parsing
DAY_TYPE_MAP = {
    0: "MONDAY",
    1: "TUESDAY", 
    2: "WEDNESDAY",
    3: "THURSDAY",
    4: "FRIDAY",
    5: "SATURDAY",
    6: "SUNDAY",
}


@dataclass
class NextScheduleBlock:
    """Next scheduled temperature change."""
    start_time: datetime  # When this block starts
    target_temp: Optional[float]  # Target temperature (None if OFF)
    is_heating_on: bool  # Whether heating will be ON
    block_end_time: datetime  # When this block ends
    
    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time.isoformat(),
            "target_temp": self.target_temp,
            "is_heating_on": self.is_heating_on,
            "block_end_time": self.block_end_time.isoformat(),
        }


def _get_day_blocks(blocks: dict, schedule_type: str, weekday: int) -> list:
    """Get schedule blocks for a specific weekday.
    
    Args:
        blocks: Schedule blocks dict from schedule data
        schedule_type: ONE_DAY, THREE_DAY, or SEVEN_DAY
        weekday: 0=Monday, 6=Sunday
        
    Returns:
        List of blocks for that day
    """
    if schedule_type == "ONE_DAY":
        return blocks.get("MONDAY_TO_SUNDAY", [])
    elif schedule_type == "THREE_DAY":
        if weekday < 5:
            return blocks.get("MONDAY_TO_FRIDAY", [])
        elif weekday == 5:
            return blocks.get("SATURDAY", [])
        else:
            return blocks.get("SUNDAY", [])
    else:
        # SEVEN_DAY
        day_name = DAY_TYPE_MAP.get(weekday, "MONDAY")
        return blocks.get(day_name, [])


def get_next_schedule_change(zone_id: str, current_time: Optional[datetime] = None, look_ahead_days: int = 2) -> Optional[NextScheduleBlock]:
    """Find the next schedule block that requires temperature change.
    
    Parses the zone's schedule and finds the next block where:
    1. Heating turns ON with a target temperature, OR
    2. Target temperature increases (needs preheat)
    
    Now supports looking ahead to tomorrow if no blocks remain today.
    
    Args:
        zone_id: Zone ID to look up schedule for
        current_time: Current time (defaults to now)
        look_ahead_days: How many days to look ahead (default 2 = today + tomorrow)
        
    Returns:
        NextScheduleBlock with next change info, or None if no schedule/no upcoming change
    """
    from .data_loader import get_zone_schedule
    
    if current_time is None:
        current_time = datetime.now()
    
    schedule = get_zone_schedule(zone_id)
    if not schedule:
        _LOGGER.debug(f"No schedule found for zone {zone_id}")
        return None
    
    blocks = schedule.get("blocks", {})
    schedule_type = schedule.get("type", "ONE_DAY")
    
    # Look through today and upcoming days
    for day_offset in range(look_ahead_days):
        check_date = current_time + timedelta(days=day_offset)
        check_weekday = check_date.weekday()
        
        day_blocks = _get_day_blocks(blocks, schedule_type, check_weekday)
        
        if not day_blocks:
            continue
        
        # For today, skip blocks that have already started
        # For future days, consider all blocks
        if day_offset == 0:
            current_time_str = current_time.strftime("%H:%M")
        else:
            current_time_str = "00:00"  # Consider all blocks for future days
        
        for block in day_blocks:
            block_start = block.get("start", "00:00")
            block_end = block.get("end", "00:00")
            setting = block.get("setting", {})
            power = setting.get("power", "OFF")
            temp_data = setting.get("temperature")
            
            # Skip if block has already started (only for today)
            if block_start <= current_time_str:
                continue
            
            # Parse start time into datetime
            start_hour, start_min = map(int, block_start.split(":"))
            start_datetime = check_date.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
            
            # Parse end time
            end_hour, end_min = map(int, block_end.split(":"))
            if block_end == "00:00":
                # Midnight means end of day
                end_datetime = (check_date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                end_datetime = check_date.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)
            
            # Get target temperature
            target_temp = None
            if power == "ON" and temp_data:
                target_temp = temp_data.get("celsius")
            
            return NextScheduleBlock(
                start_time=start_datetime,
                target_temp=target_temp,
                is_heating_on=(power == "ON"),
                block_end_time=end_datetime,
            )
    
    _LOGGER.debug(f"No schedule blocks found for zone {zone_id} in next {look_ahead_days} days")
    return None


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


@dataclass
class HistoricalComparison:
    """Result of historical temperature comparison."""
    current_temp: float
    historical_avg: float
    difference: float  # current - historical (positive = warmer than usual)
    sample_count: int  # Number of historical data points used
    comparison_window_minutes: int  # Time window used for comparison (e.g., 30 min)
    
    def to_summary(self) -> str:
        """Generate human-readable summary."""
        if abs(self.difference) < 0.3:
            return f"Normal (avg {self.historical_avg:.1f}°C)"
        elif self.difference > 0:
            return f"{self.difference:+.1f}°C warmer than usual"
        else:
            return f"{self.difference:.1f}°C cooler than usual"


@dataclass
class PreheatAdvice:
    """Preheat timing recommendation."""
    recommended_start_time: datetime  # When to start heating
    target_time: datetime  # When target should be reached
    target_temp: float
    current_temp: float
    estimated_duration_minutes: int  # How long heating will take
    heating_rate: float  # °C/hour used for calculation
    confidence: str  # "high", "medium", "low" based on data quality
    
    def to_summary(self) -> str:
        """Generate human-readable summary."""
        if self.estimated_duration_minutes == 0:
            return f"Already at {self.target_temp:.1f}°C (no preheat needed)"
        start_str = self.recommended_start_time.strftime("%H:%M")
        return f"Start at {start_str} ({self.estimated_duration_minutes} min to reach {self.target_temp:.1f}°C)"


class ZoneHistory:
    """Temperature history for a single zone."""
    
    def __init__(self, zone_id: str, zone_name: str, history_days: int = DEFAULT_HISTORY_DAYS):
        self.zone_id = zone_id
        self.zone_name = zone_name
        self.readings: list[TemperatureReading] = []
        self._history_days = history_days
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
            "readings": [r.to_dict() for r in self.readings],
            "history_days": self._history_days
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ZoneHistory":
        """Create from dictionary.
        
        v1.9.2: Deduplicates readings on load to clean up cache files
        from v1.9.0/v1.9.1 that may have duplicate entries.
        """
        history_days = data.get("history_days", DEFAULT_HISTORY_DAYS)
        zone = cls(data["zone_id"], data["zone_name"], history_days)
        
        # Load and deduplicate readings
        raw_readings = [TemperatureReading.from_dict(r) for r in data.get("readings", [])]
        
        # Sort by timestamp to ensure proper deduplication order
        raw_readings.sort(key=lambda r: r.timestamp)
        
        # Deduplicate: skip if same temp/heating and < 5 min apart
        deduplicated = []
        for reading in raw_readings:
            if deduplicated:
                last = deduplicated[-1]
                time_diff = (reading.timestamp - last.timestamp).total_seconds()
                # Skip duplicate: same temp, same heating state, < 5 min
                if (abs(reading.temperature - last.temperature) < 0.05 and
                    reading.is_heating == last.is_heating and
                    time_diff < 300):
                    continue
            deduplicated.append(reading)
        
        zone.readings = deduplicated
        return zone
    
    def set_history_days(self, days: int) -> None:
        """Update history retention period and prune old readings."""
        self._history_days = days
        self._prune_old_readings()
    
    def add_reading(self, reading: TemperatureReading) -> None:
        """Add a temperature reading and prune old data.
        
        Deduplication: Only adds if temperature or is_heating changed,
        or if more than 5 minutes have passed since last reading.
        This prevents cache bloat from frequent polling.
        """
        # Deduplication check
        if self.readings:
            last = self.readings[-1]
            time_diff = (reading.timestamp - last.timestamp).total_seconds()
            
            # Skip if same temp and heating state, and less than 5 minutes
            if (abs(reading.temperature - last.temperature) < 0.05 and
                reading.is_heating == last.is_heating and
                time_diff < 300):  # 5 minutes
                return
        
        self.readings.append(reading)
        self._prune_old_readings()
    
    def _prune_old_readings(self) -> None:
        """Remove readings older than configured history_days."""
        cutoff = datetime.now() - timedelta(days=self._history_days)
        self.readings = [r for r in self.readings if r.timestamp > cutoff]
    
    def get_heating_rate(self) -> Optional[float]:
        """Calculate heating rate (°C/hour) from actual temperature rise.
        
        Uses segment-based analysis to find periods of actual temperature rise.
        This works regardless of is_heating flag - we look at actual temp changes.
        
        Strategy:
        1. First try readings where is_heating=True (traditional HVAC control)
        2. If no heating readings, use ALL readings to find rising segments
           (supports Automation-controlled setups where is_heating may be False)
        3. Falls back to baseline rate from long-term statistics if not enough data
        
        Returns:
            Positive value for heating rate, or None if insufficient data.
        """
        # Strategy 1: Try readings where is_heating=True first
        heating_readings = [r for r in self.readings if r.is_heating]
        rate = self._calculate_heating_rate_segments(heating_readings)
        
        if rate is not None and rate > 0.01:
            self._last_heating_rate = rate
            self._rate_updated_at = datetime.now()
            return rate
        
        # Strategy 2: No heating readings - use ALL readings to find rising segments
        # This supports setups where heating is controlled by HA Automation
        # and is_heating flag may always be False
        if len(heating_readings) == 0 and len(self.readings) >= MIN_DATA_POINTS:
            rate = self._calculate_heating_rate_segments(self.readings)
            if rate is not None and rate > 0.01:
                self._last_heating_rate = rate
                self._rate_updated_at = datetime.now()
                return rate
        
        # Strategy 3: Fallback to baseline if no valid rate from segments
        if self._baseline_heating_rate is not None:
            return self._baseline_heating_rate
        
        # No data available - return None (don't use magic numbers)
        return None
    
    def get_cooling_rate(self) -> Optional[float]:
        """Calculate cooling rate (°C/hour) when HVAC is off (heat loss).
        
        Uses linear regression on temperature readings where is_heating=False.
        Falls back to baseline rate from long-term statistics if not enough data.
        
        Returns:
            Negative value for cooling/heat loss rate, 0 if no change detected.
            Positive rates are clamped to 0 (sensor lag or external heat source).
        """
        cooling_readings = [r for r in self.readings if not r.is_heating]
        rate = self._calculate_rate(cooling_readings)
        
        # Clamp positive rates to 0 - cooling/heat loss cannot cause temperature rise
        # Positive values indicate sensor lag or external heat source (sun, etc.)
        if rate is not None and rate > 0:
            rate = 0.0
        
        # Fallback to baseline if no real-time rate available
        if rate is None and self._baseline_cooling_rate is not None:
            return self._baseline_cooling_rate
        
        return rate
    
    def _calculate_heating_rate_segments(self, readings: list[TemperatureReading]) -> Optional[float]:
        """Calculate heating rate by finding segments of temperature rise.
        
        Instead of using all readings, this method:
        1. Finds consecutive readings where temperature is rising
        2. Calculates rate for each rising segment
        3. Returns the average of valid segments
        
        This is more accurate than linear regression over all heating readings,
        because it ignores periods where temperature is stable or falling
        (which happens when target is reached).
        
        Args:
            readings: List of heating readings (is_heating=True)
            
        Returns:
            Average heating rate in °C/hour, or None if insufficient data
        """
        if len(readings) < MIN_DATA_POINTS:
            return None
        
        # Sort by timestamp and deduplicate
        sorted_readings = sorted(readings, key=lambda r: r.timestamp)
        
        # Deduplicate readings with same timestamp
        deduped = []
        last_ts = None
        for r in sorted_readings:
            if last_ts is None or r.timestamp != last_ts:
                deduped.append(r)
                last_ts = r.timestamp
        
        if len(deduped) < MIN_DATA_POINTS:
            return None
        
        # Find rising segments
        segment_rates = []
        segment_start = 0
        
        for i in range(1, len(deduped)):
            prev = deduped[i - 1]
            curr = deduped[i]
            
            time_diff_hours = (curr.timestamp - prev.timestamp).total_seconds() / 3600
            temp_diff = curr.temperature - prev.temperature
            
            # Skip if time gap is too large (> 2 hours) - not continuous
            if time_diff_hours > 2:
                segment_start = i
                continue
            
            # Check if temperature is rising
            if temp_diff > 0.05 and time_diff_hours > 0.01:  # At least 0.05°C rise
                rate = temp_diff / time_diff_hours
                # Sanity check: rate should be between 0.1 and 10.0 °C/hour
                # TRV heating can be quite fast (5-8°C/h) when starting from cold
                if 0.1 <= rate <= 10.0:
                    segment_rates.append(rate)
        
        if not segment_rates:
            return None
        
        # Return average of segment rates
        avg_rate = sum(segment_rates) / len(segment_rates)
        return round(avg_rate, 2)
    
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
    
    def get_historical_comparison(
        self,
        current_temp: float,
        comparison_window_minutes: int = 30
    ) -> Optional[HistoricalComparison]:
        """Compare current temperature to historical average at same time of day.
        
        Looks at readings from the past 7 days at the same time (±window) and
        calculates the average temperature for comparison.
        
        Args:
            current_temp: Current temperature to compare
            comparison_window_minutes: Time window in minutes (default ±30 min)
            
        Returns:
            HistoricalComparison with analysis, or None if insufficient data
        """
        if len(self.readings) < MIN_DATA_POINTS:
            return None
        
        now = datetime.now()
        current_time_minutes = now.hour * 60 + now.minute
        
        # Collect readings from past days at similar time
        historical_temps = []
        cutoff = now - timedelta(days=self._history_days)
        
        for reading in self.readings:
            # Skip today's readings
            if reading.timestamp.date() == now.date():
                continue
            
            # Skip readings older than history window
            if reading.timestamp < cutoff:
                continue
            
            # Check if reading is within time window
            reading_time_minutes = reading.timestamp.hour * 60 + reading.timestamp.minute
            time_diff = abs(reading_time_minutes - current_time_minutes)
            
            # Handle midnight wraparound
            if time_diff > 720:  # More than 12 hours
                time_diff = 1440 - time_diff
            
            if time_diff <= comparison_window_minutes:
                historical_temps.append(reading.temperature)
        
        if len(historical_temps) < 2:
            return None
        
        historical_avg = sum(historical_temps) / len(historical_temps)
        difference = current_temp - historical_avg
        
        return HistoricalComparison(
            current_temp=round(current_temp, 1),
            historical_avg=round(historical_avg, 1),
            difference=round(difference, 1),
            sample_count=len(historical_temps),
            comparison_window_minutes=comparison_window_minutes
        )
    
    def get_preheat_advice(
        self,
        target_temp: float,
        target_time: datetime,
        current_temp: Optional[float] = None
    ) -> Optional[PreheatAdvice]:
        """Calculate recommended preheat start time.
        
        Based on historical heating rate, calculates when heating should start
        to reach target temperature by the specified time.
        
        Args:
            target_temp: Desired temperature
            target_time: When target should be reached
            current_temp: Current temperature (uses latest reading if not provided)
            
        Returns:
            PreheatAdvice with recommendation, or None if cannot calculate
        """
        # Get current temperature
        if current_temp is None:
            if not self.readings:
                return None
            current_temp = self.readings[-1].temperature
        
        # No preheating needed if already at or above target
        if current_temp >= target_temp:
            return PreheatAdvice(
                recommended_start_time=datetime.now(),
                target_time=target_time,
                target_temp=target_temp,
                current_temp=current_temp,
                estimated_duration_minutes=0,
                heating_rate=0,
                confidence="high"
            )
        
        # Get heating rate
        heating_rate = self.get_heating_rate()
        
        # Determine confidence based on data quality
        heating_readings = [r for r in self.readings if r.is_heating]
        if heating_rate is None:
            # Try baseline rate
            if self._baseline_heating_rate is not None:
                heating_rate = self._baseline_heating_rate
                confidence = "low"
            else:
                return None
        elif len(heating_readings) >= 10:
            confidence = "high"
        elif len(heating_readings) >= 5:
            confidence = "medium"
        else:
            confidence = "low"
        
        # Avoid division by zero
        if heating_rate <= 0.01:
            return None
        
        # Calculate duration needed
        temp_diff = target_temp - current_temp
        hours_needed = temp_diff / heating_rate
        minutes_needed = int(hours_needed * 60)
        
        # Cap at reasonable maximum (4 hours)
        minutes_needed = min(minutes_needed, 240)
        
        # Calculate start time
        recommended_start = target_time - timedelta(minutes=minutes_needed)
        
        return PreheatAdvice(
            recommended_start_time=recommended_start,
            target_time=target_time,
            target_temp=target_temp,
            current_temp=current_temp,
            estimated_duration_minutes=minutes_needed,
            heating_rate=heating_rate,
            confidence=confidence
        )


class SmartComfortManager:
    """Manages smart comfort analytics for all zones."""
    
    def __init__(self, hass: "HomeAssistant" = None, home_id: str = "", history_days: int = DEFAULT_HISTORY_DAYS):
        self._zones: dict[str, ZoneHistory] = {}
        self._enabled = False
        self._hass = hass
        self._home_id = home_id
        self._history_days = history_days
        self._last_save_time: Optional[datetime] = None
        # Weather compensation settings
        self._outdoor_temp_entity: str = ""
        self._weather_compensation: str = "none"
        self._use_feels_like: bool = False
    
    def set_history_days(self, days: int) -> None:
        """Update history retention period for all zones."""
        self._history_days = days
        for zone in self._zones.values():
            zone.set_history_days(days)
        _LOGGER.info(f"Smart Comfort: History retention set to {days} days")
    
    def _get_cache_file(self) -> Path:
        """Get the cache file path."""
        from .const import DATA_DIR
        if self._home_id:
            return DATA_DIR / f"smart_comfort_cache_{self._home_id}.json"
        return DATA_DIR / "smart_comfort_cache.json"
    
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
                "history_days": self._history_days,
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
                f"Smart Comfort: Saved {len(self._zones)} zones, "
                f"{total_readings} readings to {cache_file.name}"
            )
            return True
            
        except Exception as e:
            _LOGGER.warning(f"Smart Comfort: Failed to save cache: {e}")
            return False
    
    def load_from_file(self) -> int:
        """Load zone data from file.
        
        Returns:
            Number of readings loaded
        """
        cache_file = self._get_cache_file()
        
        if not cache_file.exists():
            _LOGGER.debug(f"Smart Comfort: No cache file found at {cache_file}")
            return 0
        
        try:
            with open(cache_file) as f:
                data = json.load(f)
            
            zones_data = data.get("zones", {})
            total_readings = 0
            
            for zone_id, zone_data in zones_data.items():
                zone = ZoneHistory.from_dict(zone_data)
                # Update history_days from current config
                zone.set_history_days(self._history_days)
                
                if zone.readings:
                    self._zones[zone_id] = zone
                    total_readings += len(zone.readings)
            
            saved_at = data.get("saved_at", "unknown")
            _LOGGER.info(
                f"Smart Comfort: Loaded {len(self._zones)} zones, "
                f"{total_readings} readings from cache (saved at {saved_at})"
            )
            return total_readings
            
        except json.JSONDecodeError as e:
            _LOGGER.warning(f"Smart Comfort: Invalid cache file: {e}")
            return 0
        except Exception as e:
            _LOGGER.warning(f"Smart Comfort: Failed to load cache: {e}")
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
            f"Smart Comfort: Weather compensation configured - "
            f"entity={outdoor_temp_entity}, preset={weather_compensation}, "
            f"feels_like={use_feels_like}"
        )
    
    def enable(self) -> None:
        """Enable smart comfort tracking."""
        self._enabled = True
        _LOGGER.info("Smart Comfort Manager enabled")
    
    def disable(self) -> None:
        """Disable smart comfort tracking."""
        self._enabled = False
        _LOGGER.info("Smart Comfort Manager disabled")
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
    
    def get_zone(self, zone_id: str, zone_name: str = "") -> ZoneHistory:
        """Get or create zone history tracker."""
        if zone_id not in self._zones:
            self._zones[zone_id] = ZoneHistory(zone_id, zone_name or f"Zone {zone_id}", self._history_days)
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
            f"Smart Comfort: Recorded {zone_name} temp={temperature}°C "
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
    
    def get_baseline_heating_rate(self, zone_id: str) -> Optional[float]:
        """Get baseline heating rate for a zone (from long-term statistics)."""
        if zone_id not in self._zones:
            return None
        return self._zones[zone_id]._baseline_heating_rate
    
    def get_baseline_cooling_rate(self, zone_id: str) -> Optional[float]:
        """Get baseline cooling rate for a zone (from long-term statistics)."""
        if zone_id not in self._zones:
            return None
        return self._zones[zone_id]._baseline_cooling_rate
    
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
    
    def get_historical_comparison(
        self,
        zone_id: str,
        current_temp: float,
        comparison_window_minutes: int = 30
    ) -> Optional[HistoricalComparison]:
        """Get historical temperature comparison for a zone.
        
        Args:
            zone_id: Zone identifier
            current_temp: Current temperature to compare
            comparison_window_minutes: Time window in minutes (default ±30 min)
            
        Returns:
            HistoricalComparison with analysis, or None if insufficient data
        """
        if zone_id not in self._zones:
            return None
        return self._zones[zone_id].get_historical_comparison(
            current_temp, comparison_window_minutes
        )
    
    def get_preheat_advice(
        self,
        zone_id: str,
        target_temp: float,
        target_time: datetime,
        current_temp: Optional[float] = None
    ) -> Optional[PreheatAdvice]:
        """Get preheat timing recommendation for a zone.
        
        Args:
            zone_id: Zone identifier
            target_temp: Desired temperature
            target_time: When target should be reached
            current_temp: Current temperature (uses latest reading if not provided)
            
        Returns:
            PreheatAdvice with recommendation, or None if cannot calculate
        """
        if zone_id not in self._zones:
            return None
        return self._zones[zone_id].get_preheat_advice(
            target_temp, target_time, current_temp
        )
    
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
                temp_unit = state.attributes.get('temperature_unit', '°C')
                if temp is not None:
                    if self._use_feels_like:
                        # Try to get feels-like from attributes
                        feels_like = self._get_feels_like_from_weather(state)
                        if feels_like is not None:
                            return self._convert_temp_to_celsius(feels_like, temp_unit)
                    return self._convert_temp_to_celsius(float(temp), temp_unit)
            else:
                # Regular sensor entity - check unit_of_measurement
                temp_unit = state.attributes.get('unit_of_measurement', '°C')
                return self._convert_temp_to_celsius(float(state.state), temp_unit)
        except (ValueError, TypeError) as e:
            _LOGGER.debug(f"Failed to get outdoor temperature: {e}")
            return None
        
        return None
    
    def _convert_temp_to_celsius(self, temp: float, unit: str) -> float:
        """Convert temperature to Celsius.
        
        Args:
            temp: Temperature value
            unit: Unit string (°C, °F, C, F, etc.)
            
        Returns:
            Temperature in Celsius
        """
        unit_upper = unit.upper().replace('°', '').strip()
        
        if unit_upper in ('C', 'CELSIUS'):
            return temp
        elif unit_upper in ('F', 'FAHRENHEIT'):
            return round(
                (temp - FAHRENHEIT_TO_CELSIUS_OFFSET) * FAHRENHEIT_TO_CELSIUS_RATIO, 
                1
            )
        else:
            # Unknown unit, assume Celsius
            _LOGGER.debug(f"Unknown temperature unit '{unit}', assuming Celsius")
            return temp
    
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
        wind_speed_unit = attrs.get('wind_speed_unit', 'km/h')
        
        if temp is not None and humidity is not None:
            # Convert wind speed to km/h for calculation
            wind_speed_kmh = self._convert_wind_speed_to_kmh(
                float(wind_speed) if wind_speed else 0,
                wind_speed_unit
            )
            return self._calculate_feels_like(
                float(temp),
                float(humidity),
                wind_speed_kmh
            )
        
        return None
    
    def _convert_wind_speed_to_kmh(self, speed: float, unit: str) -> float:
        """Convert wind speed to km/h.
        
        Args:
            speed: Wind speed value
            unit: Unit string (km/h, m/s, mph, etc.)
            
        Returns:
            Wind speed in km/h
        """
        # Normalize unit string for lookup
        unit_normalized = unit.lower().replace(' ', '').replace('/', '')
        
        # Look up conversion factor from constants
        factor = WIND_SPEED_CONVERSIONS.get(unit_normalized)
        if factor is not None:
            return speed * factor
        
        # Also try with slash for common formats
        unit_with_slash = unit.lower().replace(' ', '')
        factor = WIND_SPEED_CONVERSIONS.get(unit_with_slash)
        if factor is not None:
            return speed * factor
        
        # Unknown unit, assume km/h
        _LOGGER.debug(f"Unknown wind speed unit '{unit}', assuming km/h")
        return speed
    
    def _calculate_feels_like(
        self,
        temp: float,
        humidity: float,
        wind_speed_kmh: float = 0
    ) -> float:
        """Calculate feels-like temperature.
        
        Uses wind chill for cold weather and heat index for warm weather.
        
        Args:
            temp: Temperature in °C
            humidity: Relative humidity (0-100)
            wind_speed_kmh: Wind speed in km/h (default 0)
            
        Returns:
            Feels-like temperature in °C
        """
        # Wind chill for cold weather
        if temp <= WIND_CHILL_TEMP_THRESHOLD and wind_speed_kmh > WIND_CHILL_WIND_THRESHOLD:
            # Wind chill formula (Environment Canada)
            v_pow = wind_speed_kmh ** WIND_CHILL_EXPONENT
            feels_like = (
                WIND_CHILL_CONST_A 
                + WIND_CHILL_CONST_B * temp 
                - WIND_CHILL_CONST_C * v_pow 
                + WIND_CHILL_CONST_D * temp * v_pow
            )
            return round(feels_like, 1)
        
        # Heat index for warm weather
        if temp >= HEAT_INDEX_TEMP_THRESHOLD:
            t = temp
            rh = humidity
            hi = (
                HEAT_INDEX_CONST_A 
                + HEAT_INDEX_CONST_B * t 
                + HEAT_INDEX_CONST_C * rh 
                + HEAT_INDEX_CONST_D * t * rh 
                + HEAT_INDEX_CONST_E * t * t 
                + HEAT_INDEX_CONST_F * rh * rh 
                + HEAT_INDEX_CONST_G * t * t * rh 
                + HEAT_INDEX_CONST_H * t * rh * rh 
                + HEAT_INDEX_CONST_I * t * t * rh * rh
            )
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
_manager: Optional[SmartComfortManager] = None


def cleanup_smart_comfort_manager() -> bool:
    """Clean up the global SmartComfortManager (sync version for executor).
    
    NOTE: This performs blocking I/O (save_to_file). 
    Use async_cleanup_smart_comfort_manager() from async context.
    
    Returns:
        True if manager was cleaned up, False if no manager existed
    """
    global _manager
    if _manager is not None:
        # Save data before cleanup
        _manager.save_to_file()
        _manager = None
        _LOGGER.debug("Cleaned up SmartComfortManager")
        return True
    return False


async def async_cleanup_smart_comfort_manager(hass: "HomeAssistant") -> bool:
    """Clean up the global SmartComfortManager (async version).
    
    MUST be called in async_unload_entry() to prevent memory leaks
    when integration is reloaded or removed.
    
    This wraps the blocking save_to_file() in executor to avoid
    blocking I/O warning in async context.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        True if manager was cleaned up, False if no manager existed
    """
    global _manager
    if _manager is not None:
        # Save data before cleanup - run in executor to avoid blocking I/O
        await hass.async_add_executor_job(_manager.save_to_file)
        _manager = None
        _LOGGER.debug("Cleaned up SmartComfortManager (async)")
        return True
    return False


def get_smart_comfort_manager(history_days: int = DEFAULT_HISTORY_DAYS) -> SmartComfortManager:
    """Get the global SmartComfortManager instance."""
    global _manager
    if _manager is None:
        _manager = SmartComfortManager(history_days=history_days)
    else:
        # Update history_days if changed
        if _manager._history_days != history_days:
            _manager.set_history_days(history_days)
    return _manager


async def async_load_history_from_recorder(
    hass: "HomeAssistant",
    manager: SmartComfortManager,
    climate_entity_ids: list[str],
    entity_to_zone_id: dict[str, str] = None
) -> int:
    """Load historical temperature data from HA recorder on startup.
    
    This allows immediate rate calculations without waiting for data collection.
    Queries the last RECORDER_HISTORY_HOURS of climate entity history.
    
    Args:
        hass: Home Assistant instance
        manager: SmartComfortManager to populate
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
            f"Smart Comfort: Loading {RECORDER_HISTORY_HOURS}h history for "
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
            _LOGGER.debug("Smart Comfort: No history found in recorder")
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
                _LOGGER.debug(f"Smart Comfort: No zone_id mapping for {entity_name}")
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
                    _LOGGER.debug(f"Smart Comfort: Skipping invalid history state: {e}")
                    continue
            
            # Sort readings by timestamp and prune old ones
            zone.readings.sort(key=lambda r: r.timestamp)
            zone._prune_old_readings()
            
            if points_added > 0:
                _LOGGER.info(
                    f"Smart Comfort: Loaded {points_added} history points for {zone_name}, "
                    f"{len(zone.readings)} after pruning"
                )
                total_points += len(zone.readings)
        
        _LOGGER.info(f"Smart Comfort: Total {total_points} data points loaded from recorder")
        return total_points
        
    except ImportError:
        _LOGGER.debug("Smart Comfort: Recorder component not available")
        return 0
    except Exception as e:
        _LOGGER.warning(f"Smart Comfort: Failed to load history from recorder: {e}")
        return 0


async def async_load_baseline_from_statistics(
    hass: "HomeAssistant",
    manager: SmartComfortManager,
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
        manager: SmartComfortManager to update with baseline rates
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
            f"Smart Comfort: Loading 7-day statistics for {len(statistic_ids)} sensors"
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
            _LOGGER.debug("Smart Comfort: No long-term statistics found")
            return {}
        
        results = {}
        
        for zone_id, sensor_id in zone_sensor_mapping.items():
            if sensor_id not in stats:
                continue
            
            sensor_stats = stats[sensor_id]
            if len(sensor_stats) < 24:  # Need at least 24 hours
                _LOGGER.debug(
                    f"Smart Comfort: Not enough statistics for {zone_id} "
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
                f"Smart Comfort: {zone_id} baseline rates from {len(sensor_stats)} hours: "
                f"heating={baseline_heating}°C/h, cooling={baseline_cooling}°C/h"
            )
        
        return results
        
    except ImportError as e:
        _LOGGER.debug(f"Smart Comfort: Statistics API not available: {e}")
        return {}
    except Exception as e:
        _LOGGER.warning(f"Smart Comfort: Failed to load statistics: {e}")
        return {}
