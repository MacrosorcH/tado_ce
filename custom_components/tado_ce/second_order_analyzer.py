"""Second-order thermal dynamics analyzer.

Analyzes heating acceleration and approach behavior for improved preheat estimation.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .heating_cycle_models import HeatingCycle, TemperatureReading

_LOGGER = logging.getLogger(__name__)


class SecondOrderAnalyzer:
    """Analyze second-order thermal dynamics from heating cycles.
    
    Second-order analysis provides:
    - Heating acceleration: How quickly the heating rate increases after heating starts
    - Approach factor: How much the heating rate decreases near the setpoint
    
    These metrics improve preheat estimation by accounting for:
    - System response time (acceleration)
    - Overshoot prediction (approach factor)
    """
    
    def __init__(self, min_cycles: int = 3):
        """Initialize analyzer.
        
        Args:
            min_cycles: Minimum completed cycles required for analysis
        """
        self._min_cycles = min_cycles
    
    def calculate_acceleration(
        self,
        cycles: List["HeatingCycle"]
    ) -> Optional[float]:
        """Calculate average heating acceleration.
        
        Acceleration = d(rate)/dt = (rate_end - rate_start) / duration
        
        Measures how quickly the heating rate increases after heating starts.
        Higher acceleration = faster response system.
        
        Args:
            cycles: List of completed heating cycles
            
        Returns:
            Average acceleration in °C/h², or None if insufficient data
        """
        if len(cycles) < self._min_cycles:
            return None
        
        accelerations = []
        
        for cycle in cycles:
            accel = self._calculate_cycle_acceleration(cycle)
            if accel is not None:
                accelerations.append(accel)
        
        if not accelerations:
            return None
        
        avg_acceleration = sum(accelerations) / len(accelerations)
        
        _LOGGER.debug(
            "Calculated acceleration from %d cycles: %.2f °C/h²",
            len(accelerations),
            avg_acceleration
        )
        
        return round(avg_acceleration, 2)
    
    def _calculate_cycle_acceleration(
        self,
        cycle: "HeatingCycle"
    ) -> Optional[float]:
        """Calculate acceleration for a single cycle.
        
        We measure acceleration by comparing:
        - Initial heating rate (first 1/3 of cycle)
        - Final heating rate (last 1/3 of cycle, before reaching setpoint)
        
        Returns:
            Acceleration in °C/h², or None if cannot calculate
        """
        readings = cycle.temperature_readings
        
        if len(readings) < 6:
            return None
        
        # Split readings into thirds
        third = len(readings) // 3
        
        # Calculate initial rate (first third)
        initial_readings = readings[:third]
        initial_rate = self._calculate_rate_from_readings(initial_readings)
        
        # Calculate final rate (last third, but before setpoint)
        # Filter out readings that are at or above target
        final_readings = [
            r for r in readings[2*third:]
            if r.temp < cycle.target_temp - 0.1
        ]
        
        if len(final_readings) < 2:
            # Use all readings from last third if filtering removed too many
            final_readings = readings[2*third:]
        
        final_rate = self._calculate_rate_from_readings(final_readings)
        
        if initial_rate is None or final_rate is None:
            return None
        
        # Calculate time span
        if not readings:
            return None
        
        duration_hours = (readings[-1].time - readings[0].time).total_seconds() / 3600
        
        if duration_hours < 0.1:  # Less than 6 minutes
            return None
        
        # Acceleration = (final_rate - initial_rate) / duration
        # Convert rates from °C/min to °C/h for consistency
        initial_rate_h = initial_rate * 60
        final_rate_h = final_rate * 60
        
        acceleration = (final_rate_h - initial_rate_h) / duration_hours
        
        return acceleration
    
    def _calculate_rate_from_readings(
        self,
        readings: List["TemperatureReading"]
    ) -> Optional[float]:
        """Calculate heating rate from a list of readings.
        
        Returns:
            Rate in °C/min, or None if cannot calculate
        """
        if len(readings) < 2:
            return None
        
        # Use linear regression for more stable rate calculation
        times = [(r.time - readings[0].time).total_seconds() / 60 for r in readings]
        temps = [r.temp for r in readings]
        
        n = len(readings)
        sum_t = sum(times)
        sum_temp = sum(temps)
        sum_t_temp = sum(t * temp for t, temp in zip(times, temps))
        sum_t2 = sum(t * t for t in times)
        
        denominator = n * sum_t2 - sum_t * sum_t
        
        if abs(denominator) < 0.001:
            return None
        
        # Slope = rate in °C/min
        rate = (n * sum_t_temp - sum_t * sum_temp) / denominator
        
        return rate
    
    def calculate_approach_factor(
        self,
        cycles: List["HeatingCycle"]
    ) -> Optional[float]:
        """Calculate approach deceleration factor.
        
        Measures how much the heating rate decreases as temperature
        approaches the setpoint. Used to predict overshoot.
        
        Factor interpretation:
        - 1.0 (100%): No deceleration, will likely overshoot
        - 0.5 (50%): 50% deceleration, controlled approach
        - 0.0 (0%): Complete stop before setpoint (rare)
        
        Args:
            cycles: List of completed heating cycles
            
        Returns:
            Approach factor as percentage (0-100), or None if insufficient data
        """
        if len(cycles) < self._min_cycles:
            return None
        
        factors = []
        
        for cycle in cycles:
            factor = self._calculate_cycle_approach_factor(cycle)
            if factor is not None:
                factors.append(factor)
        
        if not factors:
            return None
        
        avg_factor = sum(factors) / len(factors)
        
        _LOGGER.debug(
            "Calculated approach factor from %d cycles: %.1f%%",
            len(factors),
            avg_factor * 100
        )
        
        return round(avg_factor * 100, 1)
    
    def _calculate_cycle_approach_factor(
        self,
        cycle: "HeatingCycle"
    ) -> Optional[float]:
        """Calculate approach factor for a single cycle.
        
        Compare heating rate at 50% of temperature delta vs 90% of delta.
        
        Returns:
            Factor between 0.0 and 1.0+, or None if cannot calculate
        """
        readings = cycle.temperature_readings
        
        if len(readings) < 6 or cycle.start_temp is None:
            return None
        
        temp_delta = cycle.target_temp - cycle.start_temp
        
        if temp_delta < 0.5:  # Less than 0.5°C change
            return None
        
        # Find readings at ~50% and ~90% of temperature delta
        temp_50 = cycle.start_temp + temp_delta * 0.5
        temp_90 = cycle.start_temp + temp_delta * 0.9
        
        # Get readings around these temperatures
        readings_50 = self._get_readings_near_temp(readings, temp_50, tolerance=0.3)
        readings_90 = self._get_readings_near_temp(readings, temp_90, tolerance=0.3)
        
        if len(readings_50) < 2 or len(readings_90) < 2:
            return None
        
        rate_50 = self._calculate_rate_from_readings(readings_50)
        rate_90 = self._calculate_rate_from_readings(readings_90)
        
        if rate_50 is None or rate_90 is None or rate_50 <= 0:
            return None
        
        # Factor = rate_90 / rate_50
        # If rate_90 < rate_50, factor < 1.0 (deceleration)
        # If rate_90 > rate_50, factor > 1.0 (acceleration near setpoint, unusual)
        factor = rate_90 / rate_50
        
        # Clamp to reasonable range
        factor = max(0.0, min(2.0, factor))
        
        return factor
    
    def _get_readings_near_temp(
        self,
        readings: List["TemperatureReading"],
        target_temp: float,
        tolerance: float = 0.3
    ) -> List["TemperatureReading"]:
        """Get readings near a target temperature."""
        return [
            r for r in readings
            if abs(r.temp - target_temp) <= tolerance
        ]
    
    def estimate_overshoot(
        self,
        current_temp: float,
        target_temp: float,
        heating_rate: float,
        approach_factor: float
    ) -> float:
        """Estimate temperature overshoot based on approach dynamics.
        
        Args:
            current_temp: Current temperature
            target_temp: Target temperature
            heating_rate: Current heating rate in °C/h
            approach_factor: Approach factor (0-100%)
            
        Returns:
            Estimated overshoot in °C
        """
        if heating_rate <= 0 or current_temp >= target_temp:
            return 0.0
        
        # Convert approach factor from percentage
        factor = approach_factor / 100.0
        
        # Higher factor = more overshoot
        # Base overshoot estimate: rate * thermal_lag_time
        # Thermal lag is typically 5-15 minutes for residential heating
        thermal_lag_hours = 0.15  # ~9 minutes
        
        base_overshoot = heating_rate * thermal_lag_hours
        
        # Adjust by approach factor
        # Factor 1.0 = full overshoot
        # Factor 0.5 = half overshoot
        adjusted_overshoot = base_overshoot * factor
        
        # Clamp to reasonable range
        return round(max(0.0, min(2.0, adjusted_overshoot)), 1)
    
    def get_improved_preheat_estimate(
        self,
        current_temp: float,
        target_temp: float,
        avg_heating_rate: float,
        inertia_time: float,
        acceleration: Optional[float] = None,
        approach_factor: Optional[float] = None
    ) -> Optional[float]:
        """Get improved preheat time estimate using second-order analysis.
        
        Args:
            current_temp: Current temperature
            target_temp: Target temperature
            avg_heating_rate: Average heating rate in °C/h
            inertia_time: Thermal inertia time in minutes
            acceleration: Heating acceleration in °C/h² (optional)
            approach_factor: Approach factor in % (optional)
            
        Returns:
            Estimated preheat time in minutes, or None if cannot calculate
        """
        if avg_heating_rate <= 0 or target_temp <= current_temp:
            return 0.0
        
        temp_delta = target_temp - current_temp
        
        # Base estimate: inertia + (delta / rate)
        # Convert rate from °C/h to °C/min
        rate_per_min = avg_heating_rate / 60
        heating_time = temp_delta / rate_per_min
        base_estimate = inertia_time + heating_time
        
        # Adjust for acceleration (if available)
        # Higher acceleration = faster warmup = less time needed
        if acceleration is not None and acceleration != 0:
            # Acceleration adjustment factor
            # Positive acceleration reduces time, negative increases it
            accel_adjustment = 1.0 - (acceleration / 100)  # Normalize
            accel_adjustment = max(0.8, min(1.2, accel_adjustment))
            base_estimate *= accel_adjustment
        
        # Adjust for approach factor (if available)
        # Lower approach factor = more deceleration = need to start earlier
        if approach_factor is not None:
            # Factor 100% = no adjustment
            # Factor 50% = add 10% more time
            factor_adjustment = 1.0 + (100 - approach_factor) / 500
            factor_adjustment = max(1.0, min(1.2, factor_adjustment))
            base_estimate *= factor_adjustment
        
        return round(base_estimate, 1)
