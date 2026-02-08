# Tado CE Entities Reference

Complete list of all entities created by Tado CE integration.

## 📋 v2.0.0 Changes

### Entity Descriptions (UX Enhancement)
All sensors and binary sensors now include helpful descriptions visible in Home Assistant's entity info panel:
- **What it measures**: Clear explanation of what each sensor tracks
- **How to interpret values**: Guidance on understanding sensor readings
- **Context and usage**: When and why you might use this sensor

**Implementation**: Descriptions appear automatically in the entity info panel (ℹ️ icon) for all ~30+ sensors and binary sensors. No configuration needed.

**Reference**: Addresses Issue #91 - Makes Smart Comfort and other sensors more discoverable and easier to understand for new users.

### Thermal Analytics (TRV Zones Only)
New sensors automatically created for all HEATING zones with TRV devices:
- **Thermal Inertia** (`sensor.{zone}_thermal_inertia`): Delay before temperature starts rising
- **Avg Heating Rate** (`sensor.{zone}_avg_heating_rate`): Temperature increase per minute
- **Preheat Time** (`sensor.{zone}_preheat_time`): Estimated minutes to reach target
- **Analysis Confidence** (`sensor.{zone}_analysis_confidence`): Reliability score (0-100%)
- **Heating Acceleration** (`sensor.{zone}_heating_acceleration`): Rate of change in heating speed
- **Approach Factor** (`sensor.{zone}_approach_factor`): Deceleration near target

### Smart Polling
- **Adaptive polling interval**: Automatically adjusts based on remaining API quota
- **Universal quota support**: Works with any API tier (100, 200, 500, 5000, 20000+)
- **Quota Reserve Protection**: Pauses polling when quota critically low (≤5% or ≤5 calls), reserves quota for manual operations

### Enhanced Mold Risk
- **Surface temperature calculation**: Uses outdoor temp + window U-value for accurate cold spot detection
- **Window type config**: Single Pane, Double Pane (default), Triple Pane, Passive House

---

## 📋 v1.9.0 Changes

### Environment Sensors (Always Enabled)
New sensors automatically created for all HEATING and AIR_CONDITIONING zones:
- **Mold Risk Sensor** (`sensor.{zone}_mold_risk`): Per-zone mold risk indicator based on temperature, humidity, and dew point calculation
  - **Attributes**: `temperature`, `humidity`, `dew_point`, `temperature_source` (room/surface), `outdoor_temperature`, `surface_temperature`
  - **v2.0.0**: Enhanced with 2-tier temperature calculation - uses outdoor temp + window U-value to estimate cold spot temperature at window edges (Tier 1), or falls back to room temperature (Tier 2)
- **Comfort Level Sensor** (`sensor.{zone}_comfort_level`): Adaptive comfort level (Freezing/Cold/Cool/Comfortable/Warm/Hot/Sweltering + Dry/Humid suffix)

### Smart Comfort Analytics (Opt-in)
Enable in Options → Features → "Enable Smart Comfort Analytics":
- **Heating Rate** (`sensor.{zone}_heating_rate`): °C/h when heating is active
- **Cooling Rate** (`sensor.{zone}_cooling_rate`): °C/h when heating is off (heat loss rate)
- **Time to Target** (`sensor.{zone}_time_to_target`): Estimated minutes to reach target (TRV zones only)
- **Heating Efficiency** (`sensor.{zone}_heating_efficiency`): Compare current vs baseline rate
- **Historical Temp** (`sensor.{zone}_historical_temp`): Compare current temp vs 7-day same-time average
- **Preheat Advisor** (`sensor.{zone}_preheat_advisor`): Suggested preheat start time
- **Smart Comfort Target** (`sensor.{zone}_smart_comfort_target`): Compensated target temperature

### Schedule Sensors (Opt-in, with Smart Comfort)
- **Next Schedule Time** (`sensor.{zone}_next_schedule_time`): When next scheduled change occurs
- **Next Schedule Temp** (`sensor.{zone}_next_schedule_temp`): Target temperature of next block

### UI/UX Improvements
- **Reorganized Options**: Now grouped into Features, Polling Schedule, Smart Comfort, and Experimental sections
- **Renamed "Advanced Settings" to "Experimental"**: Clearer naming
- **Renamed "Open Window" to "Window"**: Shorter display name for binary sensor
- **Renamed "Heating" to "Heating Power"**: Clearer sensor name for heating demand percentage (entity IDs unchanged)

---

## 📋 v1.8.0 Changes

### Schedule Calendar (Optional)
- **Per-zone calendar entities**: View heating schedules from Tado app as calendar events
- **Read-only**: Displays schedules, cannot modify from HA
- **Enable in Options**: Creates calendar entities for each heating zone
- **Refresh Schedule button**: Per-zone button to refresh schedule from Tado API

### API Reset Sensor Enhancements
- **New `reset_at` attribute**: Shows when next reset will happen (local time)
- **New `last_reset` attribute**: Shows when last reset happened (local time)

---

## 📋 v1.5.0 Changes

### Climate Entity Enhancements
- **Optional `offset_celsius` attribute**: Enable in options to show temperature offset on climate entities
- **Full AC support**: DRY/FAN modes, fan levels (Low/Medium/High/Auto), swing modes now properly supported

### Hot Water Temperature Control
- **Auto-detected**: If your hot water zone supports temperature (e.g., hot water tanks), you can now see and set target temperature
- **Works with V2 systems**: Verified working with Tado V2 thermostats

### New Sensors
- **Power sensor** (Hot water zones): Shows ON/OFF status

### New Service
- **`tado_ce.get_temperature_offset`**: Fetch current offset for use in automations

### Mobile Device Sync
- **Frequent sync option**: Enable to sync mobile devices every quick sync (for presence automations)

---

## 📋 v1.4.0 Changes

### Boiler Flow Temperature Sensor
- **Auto-detection**: Sensor only created if OpenTherm/eBUS data is available
- **Moved to Hub device**: Now a Hub-level sensor (was incorrectly zone-level)
- **New attribute**: `source_zone` shows which zone the data comes from
- **No more "unavailable"**: Users without OpenTherm won't see this sensor

### Climate Preset Mode Fix
- Preset mode now correctly reflects Tado's actual home/away state
- Works regardless of mobile device geo-tracking settings

---

## 📋 v1.2.0 Changes

### Device Organization
- **Zone-based devices**: Each zone now appears as a separate device
- **Zone entities**: Assigned to their respective zone devices
- **Hub entities**: Remain on the Tado CE Hub device
- **Entity IDs**: Preserved - automations continue to work

### Entity Naming
- **Zone entities**: No "Tado CE" prefix (e.g., "Living Room" instead of "Tado CE Living Room")
- **Hub entities**: Retain "Tado CE" prefix for clarity

---

## Hub Buttons (v1.5.3+)

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `button.tado_ce_resume_all_schedules` | Button | Delete all zone overlays and return to schedules | 1 per zone |
| `button.tado_ce_refresh_ac_capabilities` | Button | Refresh AC capabilities cache (v1.8.3, AC zones only) | 1 per AC zone |

**Note (v1.8.3):** The Refresh AC Capabilities button only appears if you have AC zones. Use it to refresh cached capabilities after AC firmware updates or for troubleshooting.

---

## Schedule Calendar (v1.8.0)

**Optional feature** - Enable in integration options.

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `calendar.{zone}` | Calendar | Heating schedule for zone | ~1 per zone on startup |
| `button.{zone}_refresh_schedule` | Button | Refresh schedule from Tado API | ~1 per press |

**Note:** Calendar entities only created for HEATING zones. Schedules are cached locally and only fetched on startup or when Refresh Schedule button is pressed.

---

## Hub Sensors

Global sensors for the Tado CE Hub device.

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.tado_ce_home_id` | Diagnostic | Your Tado home ID |
| `sensor.tado_ce_api_usage` | Sensor | API calls used (e.g. "142/5000") |
| `sensor.tado_ce_api_reset` | Sensor | Time until rate limit resets (e.g. "5h 30m") |
| `sensor.tado_ce_api_limit` | Diagnostic | Your daily API call limit |
| `sensor.tado_ce_api_status` | Diagnostic | API status (ok/warning/rate_limited) |
| `sensor.tado_ce_token_status` | Diagnostic | Token status (valid/expired) |
| `sensor.tado_ce_zones_count` | Diagnostic | Number of zones configured |
| `sensor.tado_ce_last_sync` | Diagnostic | Last successful sync timestamp |
| `sensor.tado_ce_next_sync` | Diagnostic | Next scheduled sync timestamp (v2.0.0) |
| `sensor.tado_ce_polling_interval` | Diagnostic | Current polling interval in minutes (v2.0.0) |
| `sensor.tado_ce_call_history` | Diagnostic | API call history with statistics (v2.0.0) |
| `sensor.tado_ce_api_call_breakdown` | Diagnostic | API call breakdown by endpoint type (v2.0.0) |

### API Reset Sensor Attributes (v1.8.0)

| Attribute | Example | Description |
|-----------|---------|-------------|
| `time_until_reset` | `5h 30m` | Human-readable countdown |
| `reset_seconds` | `19800` | Seconds until reset |
| `reset_at` | `2026-01-27 11:24:00` | When next reset will happen (local time) |
| `last_reset` | `2026-01-26 11:24:00` | When last reset happened (local time) |
| `status` | `ok` | API status |
| `next_poll` | `2026-01-26 15:30:00` | Next scheduled poll time |
| `current_interval_minutes` | `30` | Current polling interval |

### Last Sync Sensor Attributes (v2.0.0)

| Attribute | Example | Description |
|-----------|---------|-------------|
| `time_ago` | `5 minutes ago` | Human-readable time since last sync |
| `sync_status` | `active` | Sync status (active/stale/unknown) |

### Next Sync Sensor Attributes (v2.0.0)

| Attribute | Example | Description |
|-----------|---------|-------------|
| `countdown` | `in 5 minutes` | Human-readable countdown to next sync |
| `polling_interval_seconds` | `600` | Polling interval in seconds |
| `polling_interval_human` | `10 minutes` | Human-readable polling interval |

### Polling Interval Sensor Attributes (v2.0.0)

| Attribute | Example | Description |
|-----------|---------|-------------|
| `interval_source` | `custom` | Interval source (custom/adaptive/default) |

### Call History Sensor Attributes (v2.0.0)

| Attribute | Example | Description |
|-----------|---------|-------------|
| `history` | `[...]` | Array of recent API calls (last 100) |
| `history_period_days` | `14` | Number of days of history stored |
| `oldest_call` | `2026-01-25 10:00:00` | Timestamp of oldest call |
| `newest_call` | `2026-02-08 14:00:00` | Timestamp of newest call |
| `calls_per_hour` | `15.2` | Average calls per hour (last 24h) |
| `calls_today` | `245` | Total calls today (UTC day) |
| `most_called_endpoint` | `zoneStates (1234 calls)` | Most frequently called endpoint |

### API Call Breakdown Sensor Attributes (v2.0.0)

| Attribute | Example | Description |
|-----------|---------|-------------|
| `breakdown_24h` | `{"zoneStates": 50, "home": 10}` | API calls by type in last 24 hours |
| `breakdown_today` | `{"zoneStates": 30, "home": 5}` | API calls by type today (UTC day) |
| `breakdown_total` | `{"zoneStates": 500, "home": 100}` | Total API calls by type (all history) |
| `top_3_types` | `[{"type": "zoneStates", "count": 50}]` | Top 3 most called endpoint types |
| `chart_data` | `[{"type": "zoneStates", "count": 50}]` | Formatted data for visualization |

## Weather Sensors

**Note:** Weather sensors are **disabled by default** in v1.2.0 to save API calls. Enable in integration options if needed.

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `sensor.tado_ce_outside_temperature` | Temperature | Outside temperature at your location | 1 per sync (when enabled) |
| `sensor.tado_ce_solar_intensity` | Percentage | Solar intensity (0-100%) | Included in weather call |
| `sensor.tado_ce_weather_state` | State | Current weather condition | Included in weather call |

## Home/Away

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `binary_sensor.tado_ce_home` | Binary Sensor | Home/Away status (read-only, from geofencing) | 0 |
| `switch.tado_ce_away_mode` | Switch | Toggle Home/Away manually | 1 per toggle |

## Per Zone - Climate

**Device Organization (v1.2.0):** Each zone has its own device. Zone entities are assigned to their zone device.

For each heating zone (e.g. "Lounge"), you get:

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `climate.{zone}` | Climate | Full climate control | 1 per action |

**Note:** Entity naming changed in v1.2.0 - no "tado_ce_" prefix for zone entities.

### Climate Entity Attributes

| Attribute | Description |
|-----------|-------------|
| `current_temperature` | Current room temperature |
| `current_humidity` | Current room humidity |
| `target_temperature` | Target temperature |
| `hvac_mode` | Current mode (heat/off/auto) |
| `hvac_action` | Current action (heating/idle/off) |
| `preset_mode` | Home/Away preset |
| `overlay_type` | Manual/Schedule/Timer |
| `heating_power` | Heating demand (0-100%) |
| `zone_id` | Tado zone ID |
| `offset_celsius` | Temperature offset (v1.5.0, optional - enable in options) |

### Climate Preset Modes

| Preset | Description | API Calls |
|--------|-------------|-----------|
| `home` | Set presence to Home | 1 |
| `away` | Set presence to Away | 1 |

## Per Zone - Sensors

For each zone, you get these sensors:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.{zone}_temperature` | Temperature | Current temperature |
| `sensor.{zone}_humidity` | Percentage | Current humidity |
| `sensor.{zone}_heating` | Percentage | Heating Power (0-100%) |
| `sensor.{zone}_power` | State | Power state (ON/OFF) (v1.5.0) |
| `sensor.{zone}_target` | Temperature | Target temperature |
| `sensor.{zone}_mode` | State | Mode (Manual/Schedule/Off) |
| `sensor.{zone}_battery` | State | Battery status (NORMAL/LOW) |
| `sensor.{zone}_connection` | State | Connection (Online/Offline) |

### v2.0.0: Thermal Analytics Sensors (HEATING zones only)

Automatically created for all HEATING zones to provide improved preheat timing estimates with first-order and second-order thermal analysis:

#### First-Order Analysis (Basic Metrics)

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.{zone}_thermal_inertia` | Time (minutes) | Thermal inertia time - delay before temperature starts rising after heating starts |
| `sensor.{zone}_avg_heating_rate` | Rate (°C/min) | Average linear heating rate during active heating |
| `sensor.{zone}_preheat_time` | Time (minutes) | Estimated time to reach target temperature from current temperature |
| `sensor.{zone}_analysis_confidence` | Percentage | Confidence score (0-100%) indicating reliability of estimates |

#### Second-Order Analysis (Advanced Metrics)

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.{zone}_heating_acceleration` | Rate (°C/h²) | How quickly the heating rate increases after heating starts |
| `sensor.{zone}_approach_factor` | Percentage | How much the heating rate decreases near the setpoint (used to predict overshoot) |

**How it works:**
- Automatically tracks heating cycles (when setpoint increases and heating activates)
- First-order analysis: calculates thermal inertia and average heating rate
- Second-order analysis: calculates acceleration and approach behavior for improved predictions
- Provides preheat time estimates based on historical data
- Confidence score increases as more cycles are collected (minimum 3 cycles recommended)

**Note:** Entity naming changed in v1.2.0 - no "tado_ce_" prefix for zone entities.

## Per Zone - Binary Sensors

| Entity | Type | Description |
|--------|------|-------------|
| `binary_sensor.{zone}_open_window` | Binary Sensor | Open window detected |

**Note:** Entity naming changed in v1.2.0 - no "tado_ce_" prefix for zone entities.

## Per Zone - Switches

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `switch.{zone}_early_start` | Switch | Smart pre-heating | 1 per toggle |
| `switch.{zone}_child_lock` | Switch | Child lock on device | 1 per toggle |

**Note:** Entity naming changed in v1.2.0 - no "tado_ce_" prefix for zone entities.

## Hot Water

If you have hot water control:

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `water_heater.{zone}` | Water Heater | Hot water control (with temperature if supported) | 1 per action |
| `sensor.{zone}_mode` | Sensor | Mode (Manual/Schedule/Off) | 0 |
| `sensor.{zone}_power` | Sensor | Power state (ON/OFF) (v1.5.0) | 0 |

**Note:** Entity naming changed in v1.2.0 - no "tado_ce_" prefix for zone entities.

### Hot Water Temperature Control (v1.5.0)

If your hot water zone supports temperature (e.g., hot water tanks with V2 thermostats), the water heater entity will show and allow setting target temperature. This is auto-detected from the API response.

### Hot Water Operation Modes (v1.2.0)

| Mode | Description |
|------|-------------|
| `auto` | Follow Tado schedule |
| `heat` | Manual override (on until cancelled or timer expires) |
| `off` | Completely off |

### Hot Water Timer Buttons (v1.2.0)

Quick-access timer buttons for hot water boost:

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `button.{zone}_timer_30min` | Button | Turn on hot water for 30 minutes | 1 per press |
| `button.{zone}_timer_60min` | Button | Turn on hot water for 60 minutes | 1 per press |
| `button.{zone}_timer_90min` | Button | Turn on hot water for 90 minutes | 1 per press |

## Boiler Flow Temperature (v1.4.0)

**Auto-detected** - Only appears if your system has OpenTherm/eBUS connection between Tado and boiler.

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.tado_ce_boiler_flow_temperature` | Temperature | Real-time boiler flow temperature |

**Attributes:**
- `source_zone`: The zone providing the boiler data

**Note:** This is a Hub-level sensor. If you don't have OpenTherm, this sensor won't be created.

---

## Device Trackers

For each mobile device with geo tracking enabled:

| Entity | Type | Description |
|--------|------|-------------|
| `device_tracker.tado_ce_{device}` | Device Tracker | Presence (home/not_home) |

## AC Zones (v1.5.0 Enhanced)

For air conditioning zones, climate entities support additional features:

| Feature | Description |
|---------|-------------|
| `hvac_modes` | off/auto/cool/heat/dry/fan_only |
| `fan_mode` | auto/low/medium/high (mapped from Tado's SILENT/LEVEL1-5/AUTO) |
| `swing_mode` | on/off/vertical/horizontal (when supported by AC unit) |
| `min_temp` / `max_temp` | Read from AC capabilities API |
| `target_temp_step` | Read from AC capabilities API |

**Note (v1.5.0):** AC capabilities are now fetched from Tado API instead of hardcoded values.

---

## Smart Comfort Analytics (v1.9.0)

**Optional feature** - Enable in integration options under "Smart Comfort Settings".

Provides intelligent heating insights based on temperature history analysis.

### Per Zone Sensors

| Entity | Type | Unit | Description |
|--------|------|------|-------------|
| `sensor.{zone}_heating_rate` | Sensor | °C/h | Temperature rise rate when heating is active |
| `sensor.{zone}_cooling_rate` | Sensor | °C/h | Temperature drop rate when heating is off (heat loss) |
| `sensor.{zone}_heating_efficiency` | Sensor | % | Current rate vs baseline (detect anomalies) |
| `sensor.{zone}_time_to_target` | Sensor | min | Estimated time to reach target temperature |
| `sensor.{zone}_comfort_level` | Sensor | State | Too Cold / Comfortable / Too Warm |

### Heating Efficiency Sensor Details

The Heating Efficiency sensor compares current heating rate against the baseline (historical average).

| State | Meaning | Possible Causes |
|-------|---------|-----------------|
| `< 75%` | Slow heating | Open window, poor insulation, boiler issue |
| `75-125%` | Normal | Heating as expected |
| `> 125%` | Fast heating | External heat source (sun, cooking, guests) |

**Attributes:**
- `current_rate`: Current heating rate in °C/h
- `baseline_rate`: Historical average heating rate
- `status`: "slow" / "normal" / "fast"

### Data Requirements

- Sensors need ~15 minutes of data to calculate rates
- Baseline rates require HA Recorder long-term statistics (typically 1+ week)
- Cache stores up to 7-30 d of readings (configurable)

---

## API Usage Summary

**v1.2.0 Optimizations:**
- Normal polling: 1-2 calls (quick sync) instead of 4
- Full sync: Every 6 h only (4 calls)
- Weather: Optional (disabled by default, saves 1 call per sync)
- Immediate refresh: Quota-aware with exponential backoff
- **Estimated savings: 60-70% reduction in API calls**

| Action | API Calls |
|--------|-----------|
| Quick sync (normal) | 1-2 per sync |
| Full sync (every 6h) | 4 per sync |
| Weather (if enabled) | 1 per sync |
| Set temperature | 1 |
| Change HVAC mode | 1 |
| Toggle Away Mode | 1 |
| Change Preset | 1 |
| Toggle Early Start | 1 |
| Toggle Child Lock | 1 |
| Set Hot Water | 1 |
| Hot Water Timer Button | 1 |

All read operations use cached data from the last sync - no additional API calls.

---

## 🆕 v1.2.0 New Features

### Hot Water Timer Buttons

Quick-access timer buttons for hot water boost:

| Entity | Type | Description | API Calls |
|--------|------|-------------|-----------|
| `button.{zone}_timer_30min` | Button | Turn on hot water for 30 minutes | 1 per press |
| `button.{zone}_timer_60min` | Button | Turn on hot water for 60 minutes | 1 per press |
| `button.{zone}_timer_90min` | Button | Turn on hot water for 90 minutes | 1 per press |

### Enhanced API Monitoring

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.tado_ce_api_usage` | Sensor | Shows detailed call history (last 100 calls) |
| `sensor.tado_ce_api_reset` | Sensor | Exact reset timestamp in local timezone |

### Customizable Polling

Configure in integration options:
- Custom day/night hours (default: 7am-11pm day, 11pm-7am night)
- Custom polling intervals
- Quota warnings when intervals would exceed limits

### Optional Weather Sensors

Toggle weather sensors on/off in integration options:
- **Default: Disabled** for new installations
- Saves 1 API call per sync when disabled
- Enable if you need weather data

---

## 📝 Entity Naming Changes (v1.2.0)

### Zone Entities (No Prefix)
- Before: `climate.tado_ce_living_room`
- After: `climate.living_room`

### Hub Entities (Keep Prefix)
- `sensor.tado_ce_api_usage`
- `sensor.tado_ce_api_reset`
- `switch.tado_ce_away_mode`
- `sensor.tado_ce_outside_temperature` (if enabled)

**Note:** Entity IDs are preserved during upgrade - automations continue to work.
