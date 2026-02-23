# Changelog

All notable changes to Tado CE will be documented in this file.

## [2.2.2] - 2026-02-23

**Options Flow Validation & Persistence Fixes**

### Bug Fixes
- **Fix API Options validation and persistence** ([#134](https://github.com/hiall-fyi/tado_ce/issues/134) - @Xavinooo)
  - Validation bug: Cannot save if only one of day/night interval is filled (other empty)
  - Persistence bug: Clearing a custom interval field does not persist (old value remains)

### Improvements
- **Clarified debug log message** - Changed "Applied:" to "Adaptive:" in polling interval debug logs for clarity

---

## [2.2.1] - 2026-02-23

**Hot Water Detection & API Options Fixes**

### Bug Fixes
- **Fixed Hot Water per-zone config detection for tank-based systems** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @jeverley)
  - v2.2.0 detection used `overlayType` and `temperature` which are null when hot water is in scheduled mode
  - Now uses `nextScheduleChange` as primary indicator (tank-based systems have schedules, combi boilers don't)
  - Tank-based hot water users will now correctly see Overlay Mode + Timer Duration entities

- **Fixed API Options not saving** ([#134](https://github.com/hiall-fyi/tado_ce/issues/134) - @ChrisMarriott38, @Xavinooo)
  - HA's NumberSelector returns float (e.g., `10.0`) but validation expected int
  - Custom day/night polling intervals now correctly saved after Options flow changes
  - Also handles legacy TextSelector string data from older configs

---
## [2.2.0] - 2026-02-23

**Calibration Sensors & Actionable Insights**

### Features
- **Surface Temperature Sensor** ([#118](https://github.com/hiall-fyi/tado_ce/issues/118))
  - New standalone sensor exposing calculated cold spot temperature
  - Real-time feedback for mold risk calibration with laser thermometer
  - Uses same 2-tier calculation as Mold Risk sensor
  - Entity: `sensor.{zone}_surface_temperature`

- **Dew Point Sensor** ([#118](https://github.com/hiall-fyi/tado_ce/issues/118))
  - New standalone sensor exposing calculated dew point temperature
  - Enables automation for dehumidifier control and condensation prevention
  - Uses Magnus-Tetens formula (same as Mold Risk sensor)
  - Entity: `sensor.{zone}_dew_point`

- **Window Predicted Binary Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7)
  - Early open window detection using heating/cooling anomaly detection
  - Provides warning before Tado's cloud detection (which takes 15-17 minutes)
  - ONLY triggers when HVAC is active but temperature moves wrong direction (heating but dropping, cooling but rising)
  - Requires 2+ consecutive anomalous readings to trigger (reduces false positives)
  - Entity: `binary_sensor.{zone}_window_predicted`
  - Attributes: `confidence`, `temp_drop`, `time_window_minutes`, `recommendation`

Both calibration sensors are controlled by the existing `environment_sensors_enabled` toggle.

- **Actionable Recommendation Attributes** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7)
  - New `recommendation` attribute on environment, device, and hub sensors
  - Mold risk: Delta format with specific humidity/temperature targets to reduce risk level
  - Comfort level: Context-aware recommendations considering HVAC action state
  - Battery, connection, API status: Actionable troubleshooting guidance
  - Empty string when no action needed, actionable text when issues detected

- **Home Insights Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7)
  - Hub-level aggregation of insights from all zones with priority ranking
  - Entity: `sensor.tado_ce_home_insights`
  - State: Total number of active insights
  - Attributes: `critical_count`, `high_count`, `medium_count`, `low_count`, `top_priority`, `top_recommendation`, `zones_with_issues`, `cross_zone_insights`
  - Insight types: mold risk, comfort, window predicted, battery, connection, preheat timing, heating anomaly, API quota planning, weather impact
  - Cross-zone aggregation: whole-house mold risk (3+ zones), multiple open windows (2+ zones)

- **Zone Insights Sensor** ([Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112) - @tigro7)
  - Per-zone insights sensor for each HEATING and AIR_CONDITIONING zone
  - Entity: `sensor.{zone}_insights`
  - State: Number of active insights for this zone (integer)
  - Attributes: `top_priority`, `top_recommendation`, `insight_types`, `recommendations`
  - Insight types: mold risk, comfort, window predicted, battery, connection, preheat timing, heating anomaly
  - Dynamic icon changes based on highest priority insight

### Improvements
- **User-Friendly Attribute Values**
  - `zone_type`: Now displays `"Heating"`, `"Air Conditioning"`, `"Hot Water"` instead of `"HEATING"`, `"AIR_CONDITIONING"`, `"HOT_WATER"`
  - `window_type`: Now displays `"Single Pane"`, `"Double Pane"`, `"Triple Pane"` instead of snake_case
  - `comfort_model`: Now displays `"Adaptive"`, `"Seasonal"` instead of lowercase

### Bug Fixes
- **Fixed heating cycle never completing after ~50 minutes** ([#125](https://github.com/hiall-fyi/tado_ce/issues/125) - @BruceRobertson)
  - `on_temperature_update()` stopped appending readings at 100 (memory limit)
  - `check_cycle_complete()` used `readings[-1].temp` which was frozen after limit
  - Now updates last reading in-place when limit reached, ensuring cycle completion detection works for long heating cycles

- **Fixed API call history save error on first run** ([#127](https://github.com/hiall-fyi/tado_ce/issues/127) - @slflowfoon, [PR #132](https://github.com/hiall-fyi/tado_ce/pull/132) - @hacker4257)
  - `_save_history_sync()` failed with `[Errno 2] No such file or directory` when `.storage/tado_ce/` didn't exist
  - Original fix: Added `self.data_dir.mkdir(parents=True, exist_ok=True)`
  - Improved fix (PR #132): Changed to `self.history_file.parent.mkdir()` for better future-proofing

- **Fixed Hot Water per-zone config for tank-based systems** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @jeverley)
  - v2.1.1 blanket-skipped ALL per-zone config entities for Hot Water zones
  - Tank-based hot water systems DO support overlay mode and schedules
  - Now detects at runtime: if zone has `overlayType` or temperature setting → create Overlay Mode + Timer Duration entities

- **Fixed polling override issues** ([#126](https://github.com/hiall-fyi/tado_ce/issues/126) - @Xavinooo)
  - Bug 1: Custom night interval was always overridden by hardcoded 120 min from adaptive polling
  - Bug 2: `is_daytime()` failed when `night_start < day_start` (e.g., night=1, day=6)
  - Bug 3: Config persistence issue when clearing custom interval
  - Improvement: Changed custom interval fields from TextSelector to NumberSelector

- **Fixed heating anomaly insight firing false positives on every poll cycle**
  - `TadoHomeInsightsSensor` and `TadoZoneInsightsSensor` were passing `duration_minutes=60` hardcoded to `calculate_heating_anomaly_insight()`
  - Insight fired immediately on first poll even if condition just started
  - Now tracks real elapsed time per zone using `_anomaly_start_times` dict; resets timer when condition clears

- **Fixed environment sensor cleanup missing v2.2.0 entities on reload**
  - `async_reload_entry` cleanup block only removed `_mold_risk`, `_comfort_level`, `_condensation_risk`
  - Missing: `_surface_temperature`, `_dew_point`, `_insights` (sensors), `_window_predicted` (binary sensor)
  - All v2.2.0 environment entities now correctly removed when feature is toggled off

- **Fixed `NameError: datetime` in Home Insights heating anomaly tracking**
  - `_collect_zone_insights()` used `datetime.now()` but `datetime` class was not imported at module level
  - Only `timedelta` was imported; `datetime` was inline-imported in other methods
  - Fixed by adding `datetime` to top-level `from datetime import datetime, timedelta`

- **Implemented weather impact insight rolling history**
  - Weather impact insight (US-20) was always passing `avg_outdoor_temp_7d=None`, making it dead code
  - Now persists rolling outdoor temperature history to `outdoor_temp_history_{home_id}.json` (survives HA restarts)
  - Insight activates after ~24 minutes of readings (48 samples at 30s poll interval)
  - Triggers when current outdoor temp is >5°C below rolling average, estimating increased heating demand

- **Fixed KeyError in hub insights calculation**
  - `load_api_call_history_file()` returns dict `{date: [call_dicts]}` but `calculate_calls_per_hour()` expects flat list
  - Caused `KeyError: 0` when accessing `history[0]` on dict, logged as `"Failed to collect hub insights: 0"`
  - Added flattening logic to convert dict to flat list before passing to `calculate_calls_per_hour()`
  - API quota planning insight now calculates correctly

- **Fixed AC swing mode validation for Mitsubishi units** ([#128](https://github.com/hiall-fyi/tado_ce/issues/128) - @BirbByte)
  - Some AC units (e.g., Mitsubishi MSZ-AP series) don't support "OFF" as a swing value
  - API rejected overlay with error: `"vertical swing not in supported vertical swings [MID_UP, AUTO, UP, MID, DOWN, ON, MID_DOWN]"`
  - Now validates swing values against capabilities before sending to API
  - If "OFF" not supported, omits swing field entirely (lets AC use its default)

---

## [2.1.1] - 2026-02-19

**Bug Fixes**

### Bug Fixes
- **Fixed Test Mode Adaptive Polling using wrong reset time** ([#120](https://github.com/hiall-fyi/tado_ce/issues/120), [#119](https://github.com/hiall-fyi/tado_ce/issues/119) - @ChrisMarriott38)
  - `_calculate_adaptive_interval()` was recalculating reset time from `last_reset_utc` (Live mode's reset)
  - In Test Mode, this caused polling to get stuck at 120min or use incorrect intervals
  - Now respects Test Mode's already-calculated `reset_seconds` from `test_mode_start_time`

- **Fixed Hot Water zones showing heating-only entities** ([#115](https://github.com/hiall-fyi/tado_ce/issues/115) - @ChrisMarriott38)
  - Per-Zone Configuration entities (Surface Temp Offset, Min/Max Temp, etc.) were incorrectly created for Hot Water zones
  - Hot Water zones now correctly skip these heating/AC-only entities

## [2.1.0] - 2026-02-18

**Per-Zone Configuration**

### Features
- **Per-Zone Overlay Mode** - Configure overlay termination per zone (Tado Mode, Timer, Manual)
- **Per-Zone Timer Duration** - Set custom timer duration per zone (15-180 minutes via select entity)
- **Per-Zone Thermal Analytics** - Select which zones have Thermal Analytics sensors ([#91](https://github.com/hiall-fyi/tado_ce/issues/91))
  - Zones that never call for heat (passive heating) always show `unavailable`
  - Now users can deselect these zones in Options to keep UI clean
  - Multi-select in Tado CE Exclusive section, defaults to all zones with heatingPower
- **Per-Zone Surface Temp Offset** - Calibrate mold risk calculation per zone ([#90](https://github.com/hiall-fyi/tado_ce/issues/90))
  - New `number.{zone}_surface_temp_offset` entity (-5°C to +5°C)
  - Use laser thermometer to measure actual cold spots, then set offset to match
  - Negative offset = colder surface (more conservative mold risk)
  - Shows `surface_temp_offset` attribute in mold risk sensors

### Bug Fixes
- **Fixed Preheat Time sensors showing `unknown` after HA restart**
  - `TadoPreheatTimeSensor` depends on both `_zone_data` (historical analysis) and `_zone_states` (current/target temps)
  - `_zone_states` was only populated when `on_zone_update()` was called, but sensors weren't notified
  - Added `async_set_updated_data()` call to notify sensors when zone state is cached
  - Updated `available` property to check both `_zone_data` and `_zone_states` exist

- **Fixed NEXT_TIME_BLOCK API error** - Tado API only accepts `MANUAL`, `TADO_MODE`, `TIMER` as termination types
  - `adaptive_preheat.py` was sending `NEXT_TIME_BLOCK` directly to API
  - `get_overlay_termination()` was returning `NEXT_TIME_BLOCK` without mapping
  - `get_zone_overlay_termination()` was mapping `next_change` to `NEXT_TIME_BLOCK`
  - All now correctly map to `TADO_MODE` which follows device settings (typically "until next schedule block")

- **Fixed custom polling interval below 5 minutes still not working** ([#107](https://github.com/hiall-fyi/tado_ce/issues/107) - @jakeycrx)
  - v2.0.2 fix was incomplete: adaptive interval was still being clamped to 5 min minimum
  - When adaptive (5 min) > custom (1-2 min), system incorrectly used adaptive
  - Now: custom interval is used directly when user explicitly sets it, unless quota is truly insufficient

### Improvements
- **Simplified Options UI** - Moved Test Mode from separate Developer section to Tado CE Exclusive section (4 sections instead of 5)

## [2.0.2] - 2026-02-14

**Presence Mode Select & Configurable Overlay Mode**

### ⚠️ Breaking Changes

- **Presence Mode Select** - `switch.tado_ce_away_mode` replaced by `select.tado_ce_presence_mode` ([Discussion #102](https://github.com/hiall-fyi/tado_ce/discussions/102) - @wyx087)
  - Migration: Update automations from `switch.turn_on/turn_off` to `select.select_option`
  - New "Auto" option resumes geofencing (was not possible with switch)

### Features

- **Presence Mode Select** - New `select.tado_ce_presence_mode` with 3 options:
  - `Auto` - Resume geofencing (deletes presence lock)
  - `Home` - Manual Home mode
  - `Away` - Manual Away mode

- **Configurable Overlay Mode** ([#101](https://github.com/hiall-fyi/tado_ce/issues/101) - @leoogermenia)
  - New `select.tado_ce_overlay_mode` entity
  - Choose how long manual temperature changes last:
    - `Tado Mode` (default) - Follows per-device settings in Tado app
    - `Next Time Block` - Until next scheduled change
    - `Manual` - Infinite override
  - Uses 0 API calls (local storage only)
  - **Note**: Default changed from infinite override to Tado Mode

### Bug Fixes

- **Fixed custom polling interval below 5 minutes not working** ([#107](https://github.com/hiall-fyi/tado_ce/issues/107) - @jakeycrx)
  - Custom intervals now support 1-1440 minutes (previously 1-4 min was ignored)
  - Adaptive polling default remains 5 minutes (sensible default for most users)
  - High-quota users can explicitly set 1-4 minute intervals via custom settings

- **Fixed polling stuck at 120 min in Uniform Mode** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38)
  - When Day Start Hour = Night Start Hour (Uniform Mode), adaptive polling incorrectly calculated `hours_until_night = 0`, causing 120 min fallback
  - Now correctly uses `reset_hours` as the effective time window in Uniform Mode

### Improvements
- **DELETE API** - New `delete_presence_lock()` method for resuming geofencing

## [2.0.1] - 2026-02-12

**Mold Risk Percentage Sensor, Hot Water Fix & Bootstrap Reserve**

### Features
- **Mold Risk Percentage Sensor** - New `sensor.{zone}_mold_risk_percentage` for historical tracking ([#90](https://github.com/hiall-fyi/tado_ce/issues/90))
- **Bootstrap Reserve Protection** - Reserves 3 API calls for auto-recovery ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38)
- **Test Mode Full Simulation** - Test Mode now fully simulates 100-call tier with independent 24h cycle
- **Day/Night Aware Adaptive Polling** - Night uses fixed 120 min interval; Day uses adaptive interval based on remaining quota and Reset Time
- **Improved Approach Factor Calculation** - Hybrid method with rate ratio and exponential curve fitting for more accurate preheat estimation

### Bug Fixes
- **Fixed climate entities unavailable after upgrade** ([#100](https://github.com/hiall-fyi/tado_ce/issues/100) - @Claeysjens)
- **Fixed hot water UI "jumping back" after temperature change** ([#98](https://github.com/hiall-fyi/tado_ce/issues/98) - @ChrisMarriott38)
- **Fixed Quota Reserve not preventing API limit exceeded** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38)
- **Fixed Mold Risk dew point calculation** - Now correctly uses room temperature instead of surface temperature ([#90](https://github.com/hiall-fyi/tado_ce/issues/90) - @ChrisMarriott38)
- **Fixed Thermal Analytics not available for SU02 zones** - Now creates sensors for ALL zones with heatingPower data, not just TRV zones ([#91](https://github.com/hiall-fyi/tado_ce/issues/91) - @ChrisMarriott38)
- **Fixed Day/Night polling intervals being ignored** - Adaptive polling now correctly uses Day/Night settings
- **Fixed Test Mode not restoring original Reset Time when disabled** - Backup `live_last_reset_utc` preserved
- **Fixed Polling Interval sensor showing wrong source** - Now correctly shows "Adaptive (Day)" or "Adaptive (Night)"
- **Fixed dynamic reset_seconds calculation** - Adaptive polling now calculates reset time dynamically from `last_reset_utc`

## [2.0.0] - 2026-02-09

**Smart Polling, Mold Risk Enhancement & Thermal Analytics**

### Features
- **API Monitoring Sensors** - New sensors: `next_sync`, `last_sync`, `polling_interval`, `call_history`, `api_call_breakdown` ([#86](https://github.com/hiall-fyi/tado_ce/discussions/86), [#65](https://github.com/hiall-fyi/tado_ce/issues/65))
- **Thermal Analytics** - New sensors for TRV zones: `thermal_inertia`, `avg_heating_rate`, `preheat_time`, etc.
- **Adaptive Smart Polling** - Automatically adjusts polling based on remaining API quota ([#89](https://github.com/hiall-fyi/tado_ce/issues/89) - @ChrisMarriott38)
- **Quota Reserve Protection** - Pauses polling when quota critically low ([#94](https://github.com/hiall-fyi/tado_ce/issues/94) - @ChrisMarriott38)
- **Enhanced Mold Risk** - Surface temperature calculation with window type config ([#90](https://github.com/hiall-fyi/tado_ce/issues/90) - @ChrisMarriott38)

### Bug Fixes
- Fixed hot water timer buttons not finding entity ([#93](https://github.com/hiall-fyi/tado_ce/issues/93) - @Fred224)
- Fixed various blocking I/O and threading issues
- Removed 'Tado CE' prefix from entity names

## [1.10.0] - 2026-02-05

**Coordinator Race Condition Fix**

### Bug Fixes
- **Fixed climate entity flickering** - 3-layer defense strategy prevents stale data from overwriting user actions ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun, @neonsp)
- Fixed state not syncing after mode changes
- Fixed heating power stuck after mode change

## [1.9.7] - 2026-02-04

- Fixed state flickering when rapidly changing modes ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.6] - 2026-02-04

- Fixed hvac_action reverting to IDLE after state change ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)

## [1.9.5] - 2026-02-02

- Fixed hvac_action not updating when setting temperature ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)

## [1.9.4] - 2026-02-02

**Boost Buttons**

### Features
- **Boost Button** - Sets zone to 25°C for 30 minutes
- **Smart Boost Button** - Intelligent boost with calculated duration

### Bug Fixes
- Fixed hvac_action stuck on "Heating" after switching to Auto ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)
- Fixed AC startup validation warnings ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed slow zone sensor updates ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)

## [1.9.3] - 2026-02-02

- Fixed slow state confirmation for Heating users ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar, @chinezbrun)
- Fixed AC DRY mode 422 error ([#79](https://github.com/hiall-fyi/tado_ce/issues/79) - @Fred224, @neonsp)

## [1.9.2] - 2026-02-01

- Fixed grey loading state issue ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @chinezbrun)
- Fixed Smart Comfort cache bloat

## [1.9.1] - 2026-01-31

- Fixed device migration crash on startup ([#74](https://github.com/hiall-fyi/tado_ce/issues/74))

## [1.9.0] - 2026-01-31

**Smart Comfort Analytics + Environment Sensors**

### Features
- **Smart Comfort Analytics** - Heating/Cooling rate, Time to Target, Heating Efficiency sensors
- **Smart Comfort Insights** - Historical comparison, Preheat Advisor, Smart Comfort Target ([#33](https://github.com/hiall-fyi/tado_ce/discussions/33))
- **Environment Sensors** - Mold Risk and Comfort Level per zone ([#64](https://github.com/hiall-fyi/tado_ce/issues/64))
- **Schedule Sensors** - Next Schedule Time and Temperature

### Bug Fixes
- Fixed API reset detection for 100-call limit ([#54](https://github.com/hiall-fyi/tado_ce/issues/54))
- Fixed temperature offset for multi-TRV rooms ([#66](https://github.com/hiall-fyi/tado_ce/issues/66))
- Fixed device sensor assignment ([#56](https://github.com/hiall-fyi/tado_ce/issues/56))

## [1.8.3] - 2026-01-26

- Cached AC capabilities to save API calls ([#61](https://github.com/hiall-fyi/tado_ce/issues/61) - @neonsp)
- NEW: Refresh AC Capabilities button
- Fixed AC OFF→ON state feedback ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)

## [1.8.2] - 2026-01-26

- Enhanced AC optimistic updates ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed Resume All Schedules delay ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)

## [1.8.1] - 2026-01-26

- Fixed AC optimistic updates not working ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @neonsp)
- Fixed Resume All Schedules not refreshing ([#44](https://github.com/hiall-fyi/tado_ce/issues/44) - @hapklaar)

## [1.8.0] - 2026-01-26

**Schedule Calendar + Multi-Home Prep**

- NEW: Schedule Calendar - Per-zone calendar showing heating schedules
- NEW: Per-zone Refresh Schedule button
- NEW: API Reset sensor attributes ([#54](https://github.com/hiall-fyi/tado_ce/issues/54) - @ChrisMarriott38)
- Multi-home prep: Per-home data files

## [1.7.0] - 2026-01-26

- NEW: Optimistic state updates - Immediate UI feedback
- NEW: Optional homeState sync to save API calls
- Multi-home prep: unique_id migration

## [1.6.3] - 2026-01-25

- NEW: HA History Detection for accurate API reset time

## [1.6.2] - 2026-01-25

- Fixed API call history not recording
- Fixed timezone issues in various sensors

## [1.6.1] - 2026-01-25

- Fixed API Usage/Reset sensors showing 0
- Added configurable refresh debounce delay

## [1.6.0] - 2026-01-25

- Migrated to native async API (faster, no subprocess)
- Fixed cumulative migration bug
- Fixed `climate.set_temperature` ignoring `hvac_mode` parameter

## [1.5.5] - 2026-01-24

- Fixed AC Auto mode turning off AC
- Reduced API calls per state change

## [1.5.4] - 2026-01-24

- Fixed all AC control issues (modes, fan, swing)
- Added unified swing dropdown

## [1.5.3] - 2026-01-24

- Added Resume All Schedules button
- Fixed AC control 422 errors

## [1.5.2] - 2026-01-24

- Fixed token loss on HACS upgrade

## [1.5.1] - 2026-01-24

- Fixed OAuth flow errors for new users
- Added re-authenticate option in UI

## [1.5.0] - 2026-01-24

**Async Architecture Rewrite**

- Migrated to async API calls
- Added temperature offset service
- Full AC mode/fan/swing support
- Hot water temperature control

## [1.4.1] - 2026-01-23

- Fixed authentication broken after upgrade

## [1.4.0] - 2026-01-23

- New in-app OAuth setup (no SSH required)
- Home selection for multi-home accounts

## [1.2.1] - 2026-01-22

- Fixed duplicate hub cleanup race condition

## [1.2.0] - 2026-01-21

**Zone-Based Device Organization**

- Each zone now appears as separate device
- Optional weather sensors
- Customizable polling intervals
- 60-70% reduction in API calls

## [1.1.0] - 2026-01-19

- Added Away Mode switch
- Added preset mode support (Home/Away)

## [1.0.1] - 2026-01-18

- Fixed auto-fetch home ID

## [1.0.0] - 2026-01-17

- Initial release
