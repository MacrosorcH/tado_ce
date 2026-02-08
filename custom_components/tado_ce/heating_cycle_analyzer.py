"""Analysis of heating cycle data to extract metrics."""
import logging
from typing import Optional

from .heating_cycle_models import HeatingCycle

_LOGGER = logging.getLogger(__name__)


class HeatingCycleAnalyzer:
    """Analyze heating cycles to extract performance metrics."""
    
    def __init__(self, min_cycles: int = 3):
        """Initialize analyzer with minimum cycle requirement."""
        self._min_cycles = min_cycles
    
    def analyze_cycles(self, cycles: list[HeatingCycle]) -> Optional[dict]:
        """Analyze completed cycles and return metrics.
        
        Args:
            cycles: List of completed, non-interrupted cycles
            
        Returns:
            Dictionary with metrics, or None if insufficient data
        """
        if len(cycles) < self._min_cycles:
            _LOGGER.debug(
                "Insufficient cycles for analysis: %d < %d",
                len(cycles),
                self._min_cycles
            )
            return None
        
        # Calculate metrics
        inertia_times = []
        heating_rates = []
        
        for cycle in cycles:
            # Inertia time (minutes)
            if cycle.first_rise_time and cycle.start_time:
                inertia_minutes = (cycle.first_rise_time - cycle.start_time).total_seconds() / 60
                inertia_times.append(inertia_minutes)
            
            # Heating rate (°C/min)
            if cycle.end_time and cycle.start_temp is not None:
                duration_minutes = (cycle.end_time - cycle.start_time).total_seconds() / 60
                temp_delta = cycle.target_temp - cycle.start_temp
                if duration_minutes > 0:
                    rate = temp_delta / duration_minutes
                    heating_rates.append(rate)
        
        if not inertia_times or not heating_rates:
            _LOGGER.debug("No valid metrics extracted from cycles")
            return None
        
        # Calculate averages
        avg_inertia = sum(inertia_times) / len(inertia_times)
        avg_heating_rate = sum(heating_rates) / len(heating_rates)
        
        # Confidence score (0.0-1.0) based on cycle count and consistency
        confidence = self._calculate_confidence(
            len(cycles),
            inertia_times,
            heating_rates
        )
        
        return {
            "inertia_time": round(avg_inertia, 1),  # minutes
            "heating_rate": round(avg_heating_rate, 3),  # °C/min
            "confidence_score": round(confidence, 2),  # 0.0-1.0
            "cycle_count": len(cycles),
            "completed_count": len(cycles),
        }
    
    def estimate_preheat_time(
        self,
        current_temp: float,
        target_temp: float,
        metrics: dict,
    ) -> Optional[float]:
        """Estimate preheat time to reach target temperature.
        
        Args:
            current_temp: Current zone temperature
            target_temp: Target temperature
            metrics: Analysis metrics from analyze_cycles()
            
        Returns:
            Estimated preheat time in minutes, or None if insufficient data
        """
        if not metrics:
            return None
        
        if target_temp <= current_temp:
            return 0.0
        
        inertia_time = metrics["inertia_time"]
        heating_rate = metrics["heating_rate"]
        
        if heating_rate <= 0:
            _LOGGER.warning("Invalid heating rate: %.3f", heating_rate)
            return None
        
        # Preheat time = Inertia time + (ΔT / heating rate)
        temp_delta = target_temp - current_temp
        heating_time = temp_delta / heating_rate
        total_time = inertia_time + heating_time
        
        return round(total_time, 1)
    
    def _calculate_confidence(
        self,
        cycle_count: int,
        inertia_times: list[float],
        heating_rates: list[float],
    ) -> float:
        """Calculate confidence score based on data quality.
        
        Confidence factors:
        - Cycle count (more cycles = higher confidence)
        - Consistency (lower variance = higher confidence)
        
        Returns:
            Confidence score 0.0-1.0
        """
        # Base confidence from cycle count (0.0-0.6)
        # 3 cycles = 0.3, 5 cycles = 0.5, 10+ cycles = 0.6
        count_confidence = min(0.6, cycle_count * 0.1)
        
        # Consistency confidence from coefficient of variation (0.0-0.4)
        consistency_confidence = 0.0
        
        if len(inertia_times) >= 2:
            # Calculate coefficient of variation for inertia times
            mean_inertia = sum(inertia_times) / len(inertia_times)
            if mean_inertia > 0:
                variance = sum((x - mean_inertia) ** 2 for x in inertia_times) / len(inertia_times)
                std_dev = variance ** 0.5
                cv_inertia = std_dev / mean_inertia
                
                # Lower CV = higher confidence (CV < 0.2 = good, CV > 0.5 = poor)
                consistency_confidence += max(0.0, 0.2 - cv_inertia * 0.4)
        
        if len(heating_rates) >= 2:
            # Calculate coefficient of variation for heating rates
            mean_rate = sum(heating_rates) / len(heating_rates)
            if mean_rate > 0:
                variance = sum((x - mean_rate) ** 2 for x in heating_rates) / len(heating_rates)
                std_dev = variance ** 0.5
                cv_rate = std_dev / mean_rate
                
                # Lower CV = higher confidence
                consistency_confidence += max(0.0, 0.2 - cv_rate * 0.4)
        
        total_confidence = count_confidence + consistency_confidence
        return min(1.0, max(0.0, total_confidence))

