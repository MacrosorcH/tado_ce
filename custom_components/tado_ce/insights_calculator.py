"""Actionable insights calculator for Tado CE sensors.

v2.2.0: Provides SMART recommendation calculations for environment,
thermal analytics, device status sensors, and window predicted detection.

SMART = Specific, Measurable, Achievable, Relevant, Time-bound

Issue Reference: Discussion #112 - @tigro7
"""
import math
from typing import Optional
from dataclasses import dataclass
from enum import IntEnum
from datetime import datetime, timedelta
from collections import deque


class InsightPriority(IntEnum):
    """Priority levels for insights (higher = more urgent)."""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Insight:
    """Represents an actionable insight."""
    priority: InsightPriority
    recommendation: str
    insight_type: str  # e.g., "mold_risk", "comfort", "battery", "window_predicted"
    zone_name: Optional[str] = None


@dataclass
class TemperatureReading:
    """A temperature reading with timestamp."""
    temperature: float
    humidity: Optional[float]
    timestamp: datetime


@dataclass
class WindowPredictedResult:
    """Result of window predicted detection."""
    detected: bool
    confidence: str  # "none", "low", "medium", "high"
    temp_drop: float
    time_window_minutes: int
    recommendation: str
    anomaly_readings: int = 0


# ============ Window Predicted Detection ============

def detect_window_predicted(
    readings: list[TemperatureReading],
    hvac_active: bool,
    zone_name: str = "Room",
    temp_threshold: float = 1.5,
    time_window_minutes: int = 5,
    humidity_check: bool = True,
    hvac_mode: str = "heating",
    consecutive_drops: int = 2,
) -> WindowPredictedResult:
    """Detect possible open window via heating/cooling anomaly detection.

    When HVAC is active but temperature moves in the wrong direction across
    consecutive polling readings, an open window is the most likely cause.

    Args:
        readings: List of temperature readings (oldest first)
        hvac_active: Whether HVAC is currently heating/cooling
        zone_name: Name of the zone for specific recommendations
        temp_threshold: Unused, kept for backward compatibility
        time_window_minutes: Kept for backward compat in result
        humidity_check: Unused, kept for backward compatibility
        hvac_mode: "heating" or "cooling" — determines anomaly direction
        consecutive_drops: Min consecutive anomalous readings to trigger (default 2)

    Returns:
        WindowPredictedResult with detection status and SMART recommendation
    """
    _not_detected = WindowPredictedResult(
        detected=False,
        confidence="none",
        temp_drop=0.0,
        time_window_minutes=time_window_minutes,
        recommendation="",
        anomaly_readings=0,
    )

    # Detection REQUIRES active HVAC — temperature drops without heating are natural
    if not hvac_active:
        return _not_detected

    # Need at least 2 readings to compare consecutive pairs
    if len(readings) < 2:
        return _not_detected

    # Count consecutive anomalous readings from most recent backward
    # For heating: anomaly = temperature dropped (newer < older)
    # For cooling: anomaly = temperature rose (newer > older)
    anomaly_count = 0
    for i in range(len(readings) - 1, 0, -1):
        newer = readings[i].temperature
        older = readings[i - 1].temperature
        if hvac_mode == "heating":
            is_anomaly = newer < older
        else:  # cooling
            is_anomaly = newer > older
        if is_anomaly:
            anomaly_count += 1
        else:
            break  # streak broken

    if anomaly_count < consecutive_drops:
        return _not_detected

    # Calculate total temperature change across anomalous readings
    start_idx = len(readings) - 1 - anomaly_count
    total_change = abs(readings[start_idx].temperature - readings[-1].temperature)

    # Determine confidence based on count and magnitude
    if anomaly_count >= 3 and total_change >= 1.5:
        confidence = "high"
    elif anomaly_count >= 3 or total_change >= 1.0:
        confidence = "medium"
    else:
        confidence = "low"

    # Context-aware recommendation
    if hvac_mode == "heating":
        action = "heating active but temperature dropping"
    else:
        action = "cooling active but temperature rising"

    if confidence == "high":
        recommendation = (
            f"{zone_name}: Close window now — {action}, "
            f"{total_change:.1f}°C change over {anomaly_count} readings"
        )
    elif confidence == "medium":
        recommendation = (
            f"{zone_name}: Check windows — {action}, "
            f"{total_change:.1f}°C change detected"
        )
    else:
        recommendation = (
            f"{zone_name}: Verify windows are closed — {action}"
        )

    return WindowPredictedResult(
        detected=True,
        confidence=confidence,
        temp_drop=round(total_change, 2),
        time_window_minutes=time_window_minutes,
        recommendation=recommendation,
        anomaly_readings=anomaly_count,
    )


# ============ Mold Risk Recommendations ============

def calculate_mold_risk_recommendation(
    risk_level: str,
    zone_name: str,
    humidity: Optional[float] = None,
    surface_temp: Optional[float] = None,
    dew_point: Optional[float] = None,
    current_temp: Optional[float] = None,
    target_temp: Optional[float] = None
) -> str:
    """Calculate SMART recommendation for mold risk with delta format.

    v2.2.0: Uses delta-first format showing changes needed before absolute
    targets. Includes level transition guidance (e.g. Critical->High).

    Args:
        risk_level: Current risk level (Critical, High, Medium, Low)
        zone_name: Name of the zone
        humidity: Current humidity percentage
        surface_temp: Calculated surface temperature
        dew_point: Calculated dew point
        current_temp: Current room temperature
        target_temp: Current heating target temperature

    Returns:
        SMART recommendation string (empty if no action needed)
    """
    if risk_level in ("Minimal", "Low"):
        return ""

    # Calculate margin for specific recommendations
    margin = None
    if surface_temp is not None and dew_point is not None:
        margin = round(surface_temp - dew_point, 1)

    # Level transition targets (margin thresholds)
    # Critical (<3) -> High needs margin >= 3
    # High (3-5) -> Medium needs margin >= 5
    # Medium (5-7) -> Low needs margin >= 7

    if risk_level == "Critical":
        # Target: move to High (margin >= 3)
        transition = "Critical\u2192High"
        actions = []
        if humidity and humidity > 70:
            delta_h = round(humidity - 60)
            actions.append(f"reduce humidity by {delta_h}% (from {humidity:.0f}% to <60%)")
        if current_temp and target_temp and current_temp < target_temp:
            delta_t = round(target_temp - current_temp, 1)
            actions.append(f"increase heating by {delta_t}\u00b0C (to {target_temp:.0f}\u00b0C)")
        elif current_temp:
            actions.append(f"increase heating by +2\u00b0C (to {min(current_temp + 2, 23):.0f}\u00b0C)")

        if actions:
            return f"{zone_name} [{transition}]: URGENT - {' and '.join(actions)}. Ventilate 10 min."
        return f"{zone_name} [{transition}]: URGENT - Ventilate 10 min and increase heating by +2\u00b0C"

    if risk_level == "High":
        # Target: move to Medium (margin >= 5)
        transition = "High\u2192Medium"
        if humidity and humidity > 70:
            delta_h = round(humidity - 55)
            return (
                f"{zone_name} [{transition}]: Humidity {humidity:.0f}% "
                f"(reduce by {delta_h}% to 55%) - dehumidifier or ventilate 15 min"
            )
        if margin is not None and margin < 5:
            needed = round(5 - margin, 1)
            if current_temp:
                suggested = min(current_temp + 1.5, 22)
                return (
                    f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                    f"(need +{needed}\u00b0C margin) - increase heating by +1.5\u00b0C (to {suggested:.0f}\u00b0C)"
                )
        return f"{zone_name} [{transition}]: Ventilate 15 min or increase heating by +1.5\u00b0C"

    if risk_level == "Medium":
        # Target: move to Low (margin >= 7)
        transition = "Medium\u2192Low"
        if humidity and humidity > 65:
            delta_h = round(humidity - 55)
            return (
                f"{zone_name} [{transition}]: Humidity {humidity:.0f}% "
                f"(reduce by {delta_h}% to 55%) - ventilate 10 min after cooking/showering"
            )
        if margin is not None and margin < 7:
            needed = round(7 - margin, 1)
            return (
                f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                f"(need +{needed}\u00b0C margin) - ensure adequate ventilation"
            )
        return f"{zone_name} [{transition}]: Moderate risk - ventilate daily 10 min"

    return ""

# ============ Comfort Level Recommendations ============

def calculate_comfort_recommendation(
    comfort_state: str,
    zone_name: str,
    current_temp: Optional[float] = None,
    target_temp: Optional[float] = None,
    humidity: Optional[float] = None,
    hvac_mode: Optional[str] = None,
    hvac_action: Optional[str] = None
) -> str:
    """Calculate SMART recommendation for comfort level with time frame.

    v2.2.0: Added hvac_action parameter to differentiate between
    "heating in progress" vs "heating not reaching target".

    Args:
        comfort_state: Current comfort state (Comfortable, Cold, Cool, etc.)
        zone_name: Name of the zone
        current_temp: Current room temperature
        target_temp: Target/setpoint temperature
        humidity: Current humidity percentage
        hvac_mode: Current HVAC mode (heat, cool, off, auto)
        hvac_action: Current HVAC action (heating, idle, off)

    Returns:
        SMART recommendation string (empty if comfortable)
    """
    if comfort_state == "Comfortable":
        return ""

    # Cold/Cool states
    if comfort_state in ("Too Cold", "Cold", "Cool", "Freezing"):
        if current_temp is not None and target_temp is not None:
            diff = round(target_temp - current_temp, 1)
            if diff > 0:
                if hvac_mode == "off":
                    return (
                        f"{zone_name}: {current_temp:.1f}\u00b0C, "
                        f"target {target_temp:.0f}\u00b0C - turn on heating"
                    )
                # Differentiate based on hvac_action
                if hvac_action == "heating":
                    return (
                        f"{zone_name}: Heating in progress - "
                        f"{current_temp:.1f}\u00b0C, {diff:.1f}\u00b0C below target. "
                        f"Allow 15-30 min to reach {target_temp:.0f}\u00b0C"
                    )
                elif hvac_action in ("idle", "off"):
                    suggested = min(target_temp + 1, 25)
                    return (
                        f"{zone_name}: {current_temp:.1f}\u00b0C, "
                        f"{diff:.1f}\u00b0C below target but heating idle - "
                        f"increase setpoint to {suggested:.0f}\u00b0C"
                    )
                # Unknown hvac_action - generic
                suggested = min(target_temp + 1, 25)
                return (
                    f"{zone_name}: {current_temp:.1f}\u00b0C, "
                    f"{diff:.1f}\u00b0C below target - "
                    f"increase setpoint to {suggested:.0f}\u00b0C if not warming up"
                )
            else:
                suggested = min(current_temp + 2, 22)
                return (
                    f"{zone_name}: {current_temp:.1f}\u00b0C feels cold - "
                    f"set heating to {suggested:.0f}\u00b0C"
                )
        return f"{zone_name}: Room too cold - increase heating setpoint by 2\u00b0C"

    # Hot states
    if comfort_state in ("Too Hot", "Hot", "Warm", "Sweltering"):
        if current_temp is not None:
            if target_temp is not None and current_temp > target_temp:
                over = round(current_temp - target_temp, 1)
                return (
                    f"{zone_name}: {current_temp:.1f}\u00b0C, "
                    f"{over:.1f}\u00b0C above target - open window or reduce heating"
                )
            suggested = max(current_temp - 2, 18)
            return (
                f"{zone_name}: {current_temp:.1f}\u00b0C too warm - "
                f"reduce setpoint to {suggested:.0f}\u00b0C or open window"
            )
        return f"{zone_name}: Room too hot - reduce heating setpoint by 2\u00b0C or open window"

    if comfort_state == "Too Humid":
        if humidity is not None:
            return (
                f"{zone_name}: Humidity {humidity:.0f}% too high - "
                f"run dehumidifier or ventilate to reach 55%"
            )
        return f"{zone_name}: High humidity - run dehumidifier or open window for 15 minutes"

    if comfort_state == "Too Dry":
        if humidity is not None:
            return (
                f"{zone_name}: Humidity {humidity:.0f}% too low - "
                f"use humidifier to reach 45%"
            )
        return f"{zone_name}: Low humidity - use humidifier or place water bowl near radiator"

    return ""

# ============ Condensation Risk Recommendations ============

def calculate_condensation_recommendation(
    risk_level: str,
    zone_name: str,
    margin: Optional[float] = None,
    ac_setpoint: Optional[float] = None,
    current_temp: Optional[float] = None
) -> str:
    """Calculate SMART recommendation for condensation risk (AC zones).
    
    Args:
        risk_level: Current risk level (Critical, High, Medium, Low, Minimal)
        zone_name: Name of the zone
        margin: Temperature margin above dew point
        ac_setpoint: Current AC setpoint temperature
        current_temp: Current room temperature
    
    Returns:
        SMART recommendation string (empty if no action needed)
    """
    if risk_level in ("Minimal", "Low"):
        return ""
    
    if risk_level == "Critical":
        if ac_setpoint is not None:
            suggested = ac_setpoint + 2
            return f"{zone_name}: URGENT condensation risk - increase AC setpoint from {ac_setpoint:.0f}°C to {suggested:.0f}°C immediately"
        return f"{zone_name}: URGENT condensation risk - increase AC setpoint by 2°C and improve ventilation"
    
    if risk_level == "High":
        if ac_setpoint is not None and margin is not None:
            suggested = ac_setpoint + 1
            return f"{zone_name}: Only {margin:.1f}°C above dew point - increase AC setpoint to {suggested:.0f}°C"
        return f"{zone_name}: High condensation risk - increase AC setpoint by 1°C"
    
    if risk_level == "Medium":
        if margin is not None:
            return f"{zone_name}: {margin:.1f}°C above dew point - monitor conditions, consider raising AC setpoint"
        return f"{zone_name}: Moderate condensation risk - ensure adequate ventilation"
    
    return ""


# ============ Battery Recommendations ============

def calculate_battery_recommendation(
    battery_state: str,
    zone_name: str,
    device_type: Optional[str] = None
) -> str:
    """Calculate SMART recommendation for battery status.
    
    Args:
        battery_state: Current battery state (Normal, Low, Critical)
        zone_name: Name of the zone
        device_type: Type of device (TRV, Thermostat, etc.)
    
    Returns:
        SMART recommendation string (empty if battery is normal)
    """
    if battery_state.upper() == "NORMAL":
        return ""
    
    # Determine battery type based on device
    battery_type = "AA batteries"
    if device_type:
        device_lower = device_type.lower()
        if "trv" in device_lower or "va0" in device_lower or "ru0" in device_lower:
            battery_type = "2x AA batteries"
        elif "thermostat" in device_lower or "su0" in device_lower:
            battery_type = "3x AAA batteries"
    
    if battery_state.upper() == "CRITICAL":
        return f"{zone_name}: Replace {battery_type} TODAY - device may stop working"
    
    if battery_state.upper() == "LOW":
        return f"{zone_name}: Replace {battery_type} within 1-2 weeks"
    
    return ""


# ============ Connection Recommendations ============

def calculate_connection_recommendation(
    connection_state: str,
    zone_name: str,
    last_seen: Optional[str] = None,
    offline_minutes: Optional[int] = None
) -> str:
    """Calculate SMART recommendation for device connection status.
    
    Args:
        connection_state: Current connection state (Online, Offline)
        zone_name: Name of the zone
        last_seen: Last seen timestamp string
        offline_minutes: Minutes since device was last seen
    
    Returns:
        SMART recommendation string (empty if connected)
    """
    if connection_state.upper() == "ONLINE":
        return ""
    
    if connection_state.upper() == "OFFLINE":
        # Provide time-specific recommendations
        if offline_minutes is not None:
            if offline_minutes < 30:
                return f"{zone_name}: Device offline {offline_minutes} min - may be temporary, wait 30 minutes"
            elif offline_minutes < 120:
                return f"{zone_name}: Device offline {offline_minutes} min - check if device is within 10m of bridge"
            elif offline_minutes < 1440:  # 24 hours
                hours = offline_minutes // 60
                return f"{zone_name}: Device offline {hours}h - check batteries and bridge connection"
            else:
                days = offline_minutes // 1440
                return f"{zone_name}: Device offline {days} days - replace batteries and re-pair if needed"
        
        if last_seen:
            return f"{zone_name}: Device offline since {last_seen} - check batteries and bridge connection"
        
        return f"{zone_name}: Device offline - 1) Check batteries 2) Verify bridge is online 3) Move device closer to bridge"
    
    return ""


# ============ API Status Recommendations ============

def calculate_api_status_recommendation(
    remaining_calls: Optional[int],
    total_calls: Optional[int],
    reset_time_human: Optional[str] = None,
    current_interval_minutes: Optional[int] = None
) -> str:
    """Calculate SMART recommendation for API status.
    
    Args:
        remaining_calls: Remaining API calls
        total_calls: Total API calls allowed
        reset_time_human: Human-readable reset time (e.g., "3h 20m")
        current_interval_minutes: Current polling interval in minutes
    
    Returns:
        SMART recommendation string (empty if API usage is healthy)
    """
    if remaining_calls is None or total_calls is None:
        return ""
    
    usage_percent = ((total_calls - remaining_calls) / total_calls) * 100
    
    if usage_percent < 70:
        return ""
    
    # Calculate suggested interval based on remaining calls and time
    suggested_interval = None
    if current_interval_minutes:
        if usage_percent >= 90:
            suggested_interval = max(current_interval_minutes * 2, 60)
        elif usage_percent >= 80:
            suggested_interval = max(current_interval_minutes + 15, 30)
    
    reset_info = f" (resets in {reset_time_human})" if reset_time_human else ""
    
    if usage_percent >= 95:
        return f"API CRITICAL: Only {remaining_calls} calls remaining{reset_info} - pause automations until reset"
    
    if usage_percent >= 90:
        if suggested_interval:
            return f"API WARNING: {remaining_calls} calls remaining{reset_info} - increase polling to {suggested_interval} min in Settings → Tado CE → Configure"
        return f"API WARNING: {remaining_calls} calls remaining{reset_info} - reduce polling frequency"
    
    if usage_percent >= 80:
        if suggested_interval:
            return f"API usage at {usage_percent:.0f}%{reset_info} - consider increasing polling to {suggested_interval} min"
        return f"API usage at {usage_percent:.0f}%{reset_info} - monitor usage"
    
    if usage_percent >= 70:
        return f"API usage at {usage_percent:.0f}%{reset_info}"
    
    return ""




# ============ Historical Deviation Recommendations ============

def calculate_historical_deviation_recommendation(
    deviation: Optional[float],
    zone_name: str,
    current_temp: Optional[float] = None,
    historical_avg: Optional[float] = None,
    sample_count: int = 0
) -> str:
    """Calculate SMART recommendation for historical temperature deviation.

    Args:
        deviation: Temperature difference from historical average (degrees C)
        zone_name: Name of the zone
        current_temp: Current room temperature
        historical_avg: 7-day average temperature at this time
        sample_count: Number of historical samples used

    Returns:
        SMART recommendation string (empty if deviation is normal)
    """
    if deviation is None or sample_count < 3:
        return ""

    abs_deviation = abs(deviation)

    # Normal range: within 1.5 degrees C of historical average
    if abs_deviation <= 1.5:
        return ""

    if deviation > 3.0:
        if current_temp is not None and historical_avg is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C warmer than usual "
                f"({current_temp:.1f}°C vs avg {historical_avg:.1f}°C) "
                f"- check if heating schedule needs adjustment"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C warmer than usual - review heating schedule"

    if deviation > 1.5:
        if current_temp is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C above average "
                f"({current_temp:.1f}°C) - monitor for pattern"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C above average - monitor for pattern"

    if deviation < -3.0:
        if current_temp is not None and historical_avg is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C colder than usual "
                f"({current_temp:.1f}°C vs avg {historical_avg:.1f}°C) "
                f"- check windows and heating system"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C colder than usual - check windows and heating"

    if deviation < -1.5:
        if current_temp is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C below average "
                f"({current_temp:.1f}°C) - check for drafts or open windows"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C below average - check for drafts"

    return ""


# ============ Analysis Confidence Recommendations ============

def calculate_confidence_recommendation(
    confidence_percent: Optional[float],
    zone_name: str,
    cycle_count: int = 0,
    completed_count: int = 0
) -> str:
    """Calculate SMART recommendation for thermal analysis confidence.

    Args:
        confidence_percent: Confidence score as percentage (0-100)
        zone_name: Name of the zone
        cycle_count: Total heating cycles detected
        completed_count: Completed heating cycles analyzed

    Returns:
        SMART recommendation string (empty if confidence is adequate)
    """
    if confidence_percent is None:
        return ""

    if confidence_percent >= 70:
        return ""

    if confidence_percent < 30:
        needed = max(5 - completed_count, 1)
        return (
            f"{zone_name}: Low analysis confidence ({confidence_percent:.0f}%) "
            f"- need {needed} more complete heating cycles for reliable estimates"
        )

    if confidence_percent < 50:
        needed = max(3 - completed_count, 1)
        return (
            f"{zone_name}: Moderate confidence ({confidence_percent:.0f}%) "
            f"- {needed} more heating cycles will improve preheat accuracy"
        )

    # 50-70%
    return (
        f"{zone_name}: Building confidence ({confidence_percent:.0f}%) "
        f"- estimates improving with each heating cycle"
    )

# ============ Home Insights Aggregation ============

def get_insight_priority(insight_type: str, severity: str) -> InsightPriority:
    """Get priority level for an insight based on type and severity.
    
    Args:
        insight_type: Type of insight (window_predicted, mold_risk, etc.)
        severity: Severity level (critical, high, medium, low)
    
    Returns:
        InsightPriority enum value
    """
    priority_map = {
        ("window_predicted", "high"): InsightPriority.HIGH,
        ("window_predicted", "medium"): InsightPriority.MEDIUM,
        ("window_predicted", "low"): InsightPriority.LOW,
        ("mold_risk", "critical"): InsightPriority.CRITICAL,
        ("mold_risk", "high"): InsightPriority.HIGH,
        ("mold_risk", "medium"): InsightPriority.MEDIUM,
        ("condensation", "critical"): InsightPriority.CRITICAL,
        ("condensation", "high"): InsightPriority.HIGH,
        ("condensation", "medium"): InsightPriority.MEDIUM,
        ("connection", "offline"): InsightPriority.HIGH,
        ("connection", "offline_long"): InsightPriority.CRITICAL,
        ("battery", "critical"): InsightPriority.CRITICAL,
        ("battery", "low"): InsightPriority.HIGH,
        ("comfort", "too_cold"): InsightPriority.MEDIUM,
        ("comfort", "too_hot"): InsightPriority.MEDIUM,
        ("api", "critical"): InsightPriority.CRITICAL,
        ("api", "warning"): InsightPriority.HIGH,
        ("api", "high"): InsightPriority.MEDIUM,
    }
    return priority_map.get((insight_type, severity.lower()), InsightPriority.NONE)


def aggregate_home_insights(zone_insights: dict[str, list[Insight]]) -> dict:
    """Aggregate insights from all zones into home-level summary.
    
    Args:
        zone_insights: Dict mapping zone names to lists of Insight objects
    
    Returns:
        Dict with aggregated insights summary
    """
    if not zone_insights:
        return {
            "total_insights": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "top_priority": "none",
            "top_recommendation": "",
            "zones_with_issues": [],
        }
    
    all_insights = []
    zones_with_issues = []
    
    for zone_name, insights in zone_insights.items():
        if insights:
            zones_with_issues.append(zone_name)
            all_insights.extend(insights)
    
    # Count by priority
    critical_count = sum(1 for i in all_insights if i.priority == InsightPriority.CRITICAL)
    high_count = sum(1 for i in all_insights if i.priority == InsightPriority.HIGH)
    medium_count = sum(1 for i in all_insights if i.priority == InsightPriority.MEDIUM)
    low_count = sum(1 for i in all_insights if i.priority == InsightPriority.LOW)
    
    # Find top priority insight
    top_insight = max(all_insights, key=lambda i: i.priority, default=None)
    
    if top_insight:
        top_priority = top_insight.priority.name.lower()
        top_recommendation = top_insight.recommendation
    else:
        top_priority = "none"
        top_recommendation = ""
    
    return {
        "total_insights": len(all_insights),
        "critical_count": critical_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "top_priority": top_priority,
        "top_recommendation": top_recommendation,
        "zones_with_issues": zones_with_issues,
    }


# ============ Preheat Timing Insight (US-14) ============

def calculate_preheat_timing_insight(
    preheat_time_minutes: Optional[float] = None,
    next_schedule_time: Optional[str] = None,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Calculate preheat timing insight.

    Combines Thermal Analytics preheat_time with Smart Comfort
    next_schedule_time to advise when preheating should start.

    Args:
        preheat_time_minutes: Estimated preheat time in minutes
        next_schedule_time: Next schedule change time (ISO format or HH:MM)
        zone_name: Name of the zone

    Returns:
        Insight if preheat timing is relevant, None otherwise
    """
    if preheat_time_minutes is None or next_schedule_time is None:
        return None

    if preheat_time_minutes <= 0:
        return None

    # Parse time string
    time_str = str(next_schedule_time)
    rec = (
        f"{zone_name}: Preheat takes ~{preheat_time_minutes:.0f} min. "
        f"Next schedule change at {time_str} - "
        f"start heating {preheat_time_minutes:.0f} min before."
    )

    priority = InsightPriority.LOW
    if preheat_time_minutes > 30:
        priority = InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="preheat_timing",
        zone_name=zone_name,
    )


# ============ Schedule Deviation Insight (US-15) ============

def calculate_schedule_deviation_insight(
    historical_temp: Optional[float] = None,
    target_temp: Optional[float] = None,
    deviation_days: int = 0,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Detect consistent schedule deviation over multiple days.

    Triggers when actual temperature consistently deviates from target
    for 3+ days, suggesting the schedule may need adjustment.

    Args:
        historical_temp: Average actual temperature over recent days
        target_temp: Scheduled target temperature
        deviation_days: Number of consecutive days with deviation
        zone_name: Name of the zone

    Returns:
        Insight if deviation is consistent, None otherwise
    """
    if historical_temp is None or target_temp is None:
        return None
    if deviation_days < 3:
        return None

    diff = round(historical_temp - target_temp, 1)
    if abs(diff) < 1.0:
        return None

    if diff > 0:
        rec = (
            f"{zone_name}: Actual temp {historical_temp:.1f}\u00b0C has been "
            f"+{diff:.1f}\u00b0C above schedule target ({target_temp:.0f}\u00b0C) "
            f"for {deviation_days} days - consider lowering schedule by {abs(diff):.0f}\u00b0C"
        )
    else:
        rec = (
            f"{zone_name}: Actual temp {historical_temp:.1f}\u00b0C has been "
            f"{diff:.1f}\u00b0C below schedule target ({target_temp:.0f}\u00b0C) "
            f"for {deviation_days} days - consider raising schedule by {abs(diff):.0f}\u00b0C"
        )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="schedule_deviation",
        zone_name=zone_name,
    )


# ============ Heating Power Anomaly Detection (US-16) ============

def calculate_heating_anomaly_insight(
    heating_power_pct: Optional[float] = None,
    temp_delta: Optional[float] = None,
    duration_minutes: int = 0,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Detect heating power anomaly.

    Triggers when heating_power >= 80% AND temp_delta < 0.5C for 60+ min,
    indicating the heating system may not be working effectively.

    Args:
        heating_power_pct: Current heating power percentage (0-100)
        temp_delta: Temperature change over the monitoring period
        duration_minutes: How long the condition has persisted
        zone_name: Name of the zone

    Returns:
        Insight with HIGH priority if anomaly detected, None otherwise
    """
    if heating_power_pct is None or temp_delta is None:
        return None
    if duration_minutes < 60:
        return None
    if heating_power_pct < 80 or temp_delta >= 0.5:
        return None

    hours = duration_minutes / 60
    rec = (
        f"{zone_name}: Heating at {heating_power_pct:.0f}% for {hours:.1f}h "
        f"but temp only changed {temp_delta:.1f}\u00b0C - "
        f"check TRV/radiator for blockage or air lock"
    )

    return Insight(
        priority=InsightPriority.HIGH,
        recommendation=rec,
        insight_type="heating_anomaly",
        zone_name=zone_name,
    )


# ============ Cross-Zone Mold Risk Aggregation (US-17) ============

def aggregate_cross_zone_mold_risk(
    zone_mold_risks: dict[str, str],
) -> Optional["Insight"]:
    """Aggregate mold risk across zones.

    Triggers when 3+ zones have Medium/High/Critical mold risk,
    suggesting a whole-house humidity problem.

    Args:
        zone_mold_risks: Dict mapping zone names to risk levels

    Returns:
        Insight if whole-house issue detected, None otherwise
    """
    if not zone_mold_risks:
        return None

    affected = [
        name for name, level in zone_mold_risks.items()
        if level in ("Medium", "High", "Critical")
    ]

    if len(affected) < 3:
        return None

    zones_str = ", ".join(affected[:5])
    rec = (
        f"Whole-house mold risk: {len(affected)} zones affected "
        f"({zones_str}) - consider whole-house dehumidifier or "
        f"check ventilation system"
    )

    # Priority based on worst zone
    has_critical = any(
        zone_mold_risks[z] == "Critical" for z in affected
    )
    priority = InsightPriority.CRITICAL if has_critical else InsightPriority.HIGH

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="cross_zone_mold",
        zone_name=None,
    )


# ============ Cross-Zone Window Detection (US-18) ============

def aggregate_cross_zone_window_predicted(
    zone_window_states: dict[str, bool],
) -> Optional["Insight"]:
    """Aggregate window predicted across zones.

    Triggers when 2+ zones have window_predicted=on,
    suggesting multiple windows are open simultaneously.

    Args:
        zone_window_states: Dict mapping zone names to window predicted state

    Returns:
        Insight if multiple windows detected, None otherwise
    """
    if not zone_window_states:
        return None

    open_zones = [name for name, is_open in zone_window_states.items() if is_open]

    if len(open_zones) < 2:
        return None

    zones_str = ", ".join(open_zones)
    rec = (
        f"Multiple windows detected open: {zones_str} - "
        f"close windows to prevent energy waste"
    )

    return Insight(
        priority=InsightPriority.HIGH,
        recommendation=rec,
        insight_type="cross_zone_window",
        zone_name=None,
    )


# ============ API Quota Planning Insight (US-19) ============

def calculate_api_quota_planning_insight(
    remaining_calls: Optional[int] = None,
    total_calls: Optional[int] = None,
    calls_per_hour: Optional[float] = None,
    hours_until_reset: Optional[float] = None,
    current_interval_minutes: Optional[float] = None,
) -> Optional["Insight"]:
    """Calculate API quota planning insight.

    Triggers when projected exhaustion is < 6 hours before reset,
    suggesting polling interval adjustment.

    Args:
        remaining_calls: Remaining API calls
        total_calls: Total daily API call limit
        calls_per_hour: Current average calls per hour
        hours_until_reset: Hours until quota resets
        current_interval_minutes: Current polling interval in minutes

    Returns:
        Insight if quota exhaustion projected, None otherwise
    """
    if remaining_calls is None or calls_per_hour is None or hours_until_reset is None:
        return None
    if calls_per_hour <= 0:
        return None

    hours_remaining = remaining_calls / calls_per_hour
    buffer_hours = hours_until_reset - hours_remaining

    # Only trigger if projected to run out > 6 hours before reset
    if buffer_hours < 6:
        return None

    # Suggest new interval
    if hours_until_reset > 0 and remaining_calls > 0:
        safe_calls_per_hour = remaining_calls / hours_until_reset * 0.8  # 20% safety margin
        if safe_calls_per_hour > 0:
            suggested_interval = max(60 / safe_calls_per_hour, 5)  # min 5 minutes
        else:
            suggested_interval = 30
    else:
        suggested_interval = 30

    rec = (
        f"API quota: {remaining_calls} calls left, "
        f"projected to run out {buffer_hours:.0f}h before reset. "
        f"Consider increasing polling interval to {suggested_interval:.0f} min"
    )

    priority = InsightPriority.HIGH if buffer_hours > 12 else InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="api_quota_planning",
        zone_name=None,
    )


# ============ Weather Impact Insight (US-20) ============

def calculate_weather_impact_insight(
    current_outdoor_temp: Optional[float] = None,
    avg_outdoor_temp_7d: Optional[float] = None,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Calculate weather impact insight.

    Triggers when current outdoor temp is > 5C colder than 7-day average,
    estimating increased heating demand.

    Args:
        current_outdoor_temp: Current outdoor temperature
        avg_outdoor_temp_7d: 7-day average outdoor temperature
        zone_name: Name of the zone (or empty for home-level)

    Returns:
        Insight if significant weather impact, None otherwise
    """
    if current_outdoor_temp is None or avg_outdoor_temp_7d is None:
        return None

    diff = round(avg_outdoor_temp_7d - current_outdoor_temp, 1)
    if diff <= 5.0:
        return None

    # Rough estimate: each 1C drop increases heating by ~3-5%
    impact_pct = round(diff * 4)  # ~4% per degree

    rec = (
        f"Cold snap: {current_outdoor_temp:.0f}\u00b0C outdoor, "
        f"{diff:.0f}\u00b0C below 7-day average. "
        f"Estimated {impact_pct}% increase in heating demand"
    )

    priority = InsightPriority.LOW
    if diff > 10:
        priority = InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="weather_impact",
        zone_name=zone_name if zone_name else None,
    )

# ============ Dew Point Calculation (moved from sensor.py) ============

def calculate_dew_point(temperature: float, humidity: float) -> float:
    """Calculate dew point using Magnus-Tetens formula.

    Formula: Td = (b × α) / (a - α)
    where α = (a × T) / (b + T) + ln(RH/100)

    Constants (for -40°C to 50°C range):
    a = 17.27, b = 237.7°C

    Args:
        temperature: Indoor temperature in °C
        humidity: Relative humidity in %

    Returns:
        Dew point temperature in °C
    """
    a = 17.27
    b = 237.7
    # Clamp humidity to valid range (avoid log(0))
    humidity = max(1, min(100, humidity))
    alpha = (a * temperature) / (b + temperature) + math.log(humidity / 100)
    return round((b * alpha) / (a - alpha), 1)


# ============ Mold Risk Level Classification ============

def classify_mold_risk_level(inside_temp: float, humidity: float) -> str:
    """Classify mold risk level from temperature and humidity.

    Uses dew point margin thresholds:
    - Critical: margin < 3°C
    - High:     margin < 5°C
    - Medium:   margin < 7°C
    - Low:      margin >= 7°C

    Args:
        inside_temp: Indoor temperature in °C
        humidity: Relative humidity in %

    Returns:
        Risk level string: "Critical", "High", "Medium", or "Low"
    """
    dew_point = calculate_dew_point(inside_temp, humidity)
    margin = round(inside_temp - dew_point, 1)
    if margin < 3:
        return "Critical"
    if margin < 5:
        return "High"
    if margin < 7:
        return "Medium"
    return "Low"


# ============ Comfort Level Classification ============

def classify_comfort_level(inside_temp: float) -> str:
    """Classify comfort level from indoor temperature.

    Thresholds:
    - Cold:        < 16°C
    - Cool:        < 18°C
    - Comfortable: <= 24°C
    - Warm:        <= 26°C
    - Hot:         > 26°C

    Args:
        inside_temp: Indoor temperature in °C

    Returns:
        Comfort level string: "Cold", "Cool", "Comfortable", "Warm", or "Hot"
    """
    if inside_temp < 16:
        return "Cold"
    if inside_temp < 18:
        return "Cool"
    if inside_temp <= 24:
        return "Comfortable"
    if inside_temp <= 26:
        return "Warm"
    return "Hot"


# ============ API Call Rate Calculation ============

def calculate_calls_per_hour(history: list) -> Optional[float]:
    """Calculate average API calls per hour from call history.

    Args:
        history: List of call history dicts with "timestamp" key (ISO format)

    Returns:
        Calls per hour as float, or None if insufficient data
    """
    if not history or len(history) < 2:
        return None
    try:
        first_ts = history[0].get("timestamp", "")
        last_ts = history[-1].get("timestamp", "")
        first_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        hours_span = (last_dt - first_dt).total_seconds() / 3600
        if hours_span <= 0:
            return None
        return len(history) / hours_span
    except (ValueError, TypeError, AttributeError):
        return None
