# Tado CE - Credits & Acknowledgments

**All Versions** - Community contributions that made this integration possible

---

## v2.2.1 (2026-02-23) - Hot Water Detection & API Options Fixes

### Bug Reports & Issue Reporters

**[@jeverley](https://github.com/jeverley)** - [Issue #115](https://github.com/hiall-fyi/tado_ce/issues/115)
- Follow-up report on Hot Water per-zone config detection
- Identified that v2.2.0 detection used overlayType/temperature which are null in scheduled mode
- Tank-based hot water systems have schedules, combi boilers don't

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #134](https://github.com/hiall-fyi/tado_ce/issues/134)
- Reported API Options not saving after changes
- Identified that NumberSelector returns float but validation expected int

**[@Xavinooo](https://github.com/Xavinooo)** - [Issue #134](https://github.com/hiall-fyi/tado_ce/issues/134)
- Confirmed API Options saving issue
- Helped validate the fix

### What Was Fixed

- ✅ **Issue #115**: Hot Water per-zone config detection now uses nextScheduleChange as primary indicator
- ✅ **Issue #134**: API Options now correctly handles float values from NumberSelector
- ✅ **Issue #134**: Legacy TextSelector string data from older configs now handled

---

## v2.2.0 (2026-02-23) - Calibration Sensors & Actionable Insights

### Feature Requests & Contributors

**[@tigro7](https://github.com/tigro7)** - [Discussion #112](https://github.com/hiall-fyi/tado_ce/discussions/112)
- Proposed actionable recommendation attributes on environment sensors
- Requested early open window detection (Window Predicted sensor)
- Inspired the Home Insights and Zone Insights aggregation sensors
- Detailed use cases for mold risk calibration with laser thermometer

### Bug Reports & Issue Reporters

**[@BruceRobertson](https://github.com/BruceRobertson)** - [Issue #125](https://github.com/hiall-fyi/tado_ce/issues/125)
- Reported heating cycle never completing after ~50 minutes
- Identified that on_temperature_update() stopped appending readings at 100 (memory limit)

**[@slflowfoon](https://github.com/slflowfoon)** - [Issue #127](https://github.com/hiall-fyi/tado_ce/issues/127)
- Reported API call history save error on first run (directory not found)
- Identified missing mkdir() call in _save_history_sync()

**[@hacker4257](https://github.com/hacker4257)** - [PR #132](https://github.com/hiall-fyi/tado_ce/pull/132)
- Submitted improved fix for API call history save error (#127)
- Proposed using `history_file.parent` instead of `data_dir` for better future-proofing

**[@BirbByte](https://github.com/BirbByte)** - [Issue #128](https://github.com/hiall-fyi/tado_ce/issues/128)
- Reported AC swing mode validation issue causing immediate turn-off
- Identified that Mitsubishi MSZ-AP units don't support "OFF" as swing value
- Provided detailed debug logs and AC capabilities comparison

**[@jeverley](https://github.com/jeverley)** - [Issue #115](https://github.com/hiall-fyi/tado_ce/issues/115)
- Reported Hot Water per-zone config missing for tank-based systems
- Identified that v2.1.1 blanket-skipped ALL per-zone config for Hot Water zones
- Tank-based systems DO support overlay mode and schedules

**[@Xavinooo](https://github.com/Xavinooo)** - [Issue #126](https://github.com/hiall-fyi/tado_ce/issues/126)
- Reported polling override issues (custom night interval being overridden)
- Identified is_daytime() failure when night_start < day_start
- Reported config persistence issue when clearing custom interval

### What Was Added/Fixed

- ✅ **Discussion #112**: Surface Temperature Sensor - standalone cold spot sensor for mold risk calibration
- ✅ **Discussion #112**: Dew Point Sensor - standalone dew point for dehumidifier automations
- ✅ **Discussion #112**: Window Predicted Binary Sensor - early open window detection (before Tado cloud)
- ✅ **Discussion #112**: Actionable Recommendation Attributes - delta-format guidance on all environment sensors
- ✅ **Discussion #112**: Home Insights Sensor - hub-level aggregation with priority ranking
- ✅ **Discussion #112**: Zone Insights Sensor - per-zone insights with dynamic icon
- ✅ **Issue #125**: Fixed heating cycle never completing after ~50 minutes
- ✅ **Issue #127**: Fixed API call history save error on first run
- ✅ **Issue #115**: Fixed Hot Water per-zone config for tank-based systems
- ✅ **Issue #126**: Fixed polling override issues (3 bugs + NumberSelector improvement)
- ✅ Fixed heating anomaly insight firing false positives on every poll cycle
- ✅ Fixed environment sensor cleanup missing v2.2.0 entities on reload
- ✅ Fixed NameError: datetime in Home Insights heating anomaly tracking
- ✅ Implemented weather impact insight with file-backed rolling history (outdoor_temp_history_{home_id}.json)

---


## v2.1.1 (2026-02-19) - Test Mode & Hot Water Hotfix

### Bug Reports & Issue Reporters

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #115](https://github.com/hiall-fyi/tado_ce/issues/115), [Issue #119](https://github.com/hiall-fyi/tado_ce/issues/119), [Issue #120](https://github.com/hiall-fyi/tado_ce/issues/120)
- Reported Test Mode adaptive polling not respecting configured interval
- Identified that Test Mode was recalculating reset time from Live mode's `last_reset_utc`
- Reported Hot Water zone incorrectly getting heating-only entities (Overlay Mode, Timer Duration, Thermal Analytics)
- Thorough testing across multiple configurations

### What Was Fixed

- ✅ **Issue #119, #120**: Test Mode adaptive polling now correctly uses configured interval without recalculation
- ✅ **Issue #115**: Hot Water zones no longer get per-zone config entities (Overlay Mode, Timer Duration, Thermal Analytics)

---

## v2.1.0 (2026-02-18) - Per-Zone Configuration

### Feature Requests & Contributors

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #91](https://github.com/hiall-fyi/tado_ce/issues/91), [Issue #90](https://github.com/hiall-fyi/tado_ce/issues/90)
- Requested per-zone Thermal Analytics control for zones that never call for heat
- Proposed Surface Temperature Offset for mold risk calibration
- Continued testing and feedback on thermal analytics accuracy

### Bug Reports & Issue Reporters

**[@jakeycrx](https://github.com/jakeycrx)** - [Issue #107](https://github.com/hiall-fyi/tado_ce/issues/107)
- Follow-up report on custom polling interval still not working below 5 minutes
- Identified that v2.0.2 fix was incomplete (adaptive interval still clamped)

### What Was Added/Fixed

- ✅ **Issue #91**: Per-Zone Thermal Analytics - multi-select to disable zones that never call for heat
- ✅ **Issue #90**: Per-Zone Surface Temp Offset - calibrate mold risk with laser thermometer measurements
- ✅ **Issue #107**: Custom polling interval now truly respects user settings (adaptive no longer overrides)
- ✅ Per-Zone Overlay Mode - configure overlay termination per zone
- ✅ Per-Zone Timer Duration - set custom timer duration per zone
- ✅ Fixed Preheat Time sensors showing `unknown` after HA restart
- ✅ Fixed NEXT_TIME_BLOCK API error (now correctly maps to TADO_MODE)

---

## v2.0.2 (2026-02-14) - Presence Mode Select & Configurable Overlay Mode

### Feature Requests & Contributors

**[@wyx087](https://github.com/wyx087)** - [Discussion #102](https://github.com/hiall-fyi/tado_ce/discussions/102)
- Requested ability to resume geofencing from Home Assistant
- Proposed 3-option select entity (Auto/Home/Away) to replace binary switch

**[@leoogermenia](https://github.com/leoogermenia)** - [Issue #101](https://github.com/hiall-fyi/tado_ce/issues/101)
- Requested configurable overlay mode for manual temperature changes
- Detailed use case: evening temperature override being reset by schedule
- Proposed 3 overlay modes: Tado Mode, Next Time Block, Manual

### Bug Reports & Issue Reporters

**[@jakeycrx](https://github.com/jakeycrx)** - [Issue #107](https://github.com/hiall-fyi/tado_ce/issues/107)
- Reported custom polling interval below 5 minutes not working
- Screenshots showing 1-minute setting but 5-minute actual polling

### What Was Added

- ✅ **Discussion #102**: Presence Mode Select - `select.tado_ce_presence_mode` with Auto/Home/Away options
- ✅ **Issue #101**: Configurable Overlay Mode - `select.tado_ce_overlay_mode` with 3 options
- ✅ **Issue #107**: Allow 1-minute polling for high-quota users (changed MIN_POLLING_INTERVAL from 5 to 1)

---

## v2.0.1 (2026-02-12) - Mold Risk Percentage Sensor, Hot Water Fix & Bootstrap Reserve

### Bug Reports & Issue Reporters

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #98](https://github.com/hiall-fyi/tado_ce/issues/98), [Issue #99](https://github.com/hiall-fyi/tado_ce/issues/99)
- Reported hot water UI "jumping back" after temperature change
- Identified that water_heater.py was missing optimistic update protection
- Reported Quota Reserve not preventing API limit exceeded
- Proposed Bootstrap Reserve concept for auto-recovery after API reset
- Suggested persistent notification when API limit reached

**[@Claeysjens](https://github.com/Claeysjens)** - [Issue #100](https://github.com/hiall-fyi/tado_ce/issues/100)
- Reported climate entities unavailable after v2.0.0 upgrade
- Provided detailed logs and data files that identified the root cause
- Quick bug report that caught this critical issue within hours of release

### What Was Added/Fixed

- ✅ **Issue #90**: Mold Risk Percentage Sensor - `sensor.{zone}_mold_risk_percentage` for historical tracking
- ✅ **Issue #98**: Hot Water 3-layer defense - full parity with climate entities for optimistic updates
- ✅ **Issue #99**: Bootstrap Reserve Protection - hard limit of 3 calls for auto-recovery
- ✅ **Issue #99**: Persistent notification when API limit reached
- ✅ **Issue #100**: Fixed per-home file auto-detection matching wrong files (strict regex pattern)

---

## v2.0.0 (2026-02-09) - Smart Polling, Mold Risk Enhancement & Thermal Analytics

### Feature Ideas & Suggestions

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #89](https://github.com/hiall-fyi/tado_ce/issues/89), [Issue #90](https://github.com/hiall-fyi/tado_ce/issues/90), [Issue #94](https://github.com/hiall-fyi/tado_ce/issues/94)
- Proposed Adaptive Smart Polling based on remaining API quota
- Professional testing and validation of polling calculations
- Suggested Enhanced Mold Risk with surface temperature calculation
- Proposed window U-value configuration for accurate cold spot detection
- Reported API reset detection failure when quota exhausted before reset time (led to Quota Reserve Protection)

**[@dimitri-frank](https://github.com/dimitri-frank)** - [Issue #78](https://github.com/hiall-fyi/tado_ce/issues/78)
- Proposed Two-Phase Heating Model (Thermal Inertia + Heating Rate)
- Detailed analysis of "Phase A" (system response time) vs "Phase B" (actual heating)
- Inspired the `_thermal_inertia` and `_avg_heating_rate` sensors

**[@thefern69](https://github.com/thefern69)** - [Issue #78](https://github.com/hiall-fyi/tado_ce/issues/78), [Discussion #33](https://github.com/hiall-fyi/tado_ce/discussions/33)
- Proposed Second Order Metrics for UFH and high thermal mass systems
- Suggested Heating Acceleration and Approach Factor sensors
- Original Smart Comfort idea that evolved into Thermal Analytics

**[@Fred224](https://github.com/Fred224)** - [Issue #84](https://github.com/hiall-fyi/tado_ce/issues/84), [Issue #93](https://github.com/hiall-fyi/tado_ce/issues/93)
- Reported Timer Duration UI limitation (HA Core issue, documented workaround)
- Reported Hot Water Timer buttons not finding entity (fixed entity registry lookup)

### What Was Added/Fixed

- ✅ **Issue #89**: Adaptive Smart Polling - real-time interval based on remaining quota
- ✅ **Issue #90**: Enhanced Mold Risk - surface temperature calculation with window U-value
- ✅ **Issue #94**: Quota Reserve Protection - auto-resume polling after reset time passes
- ✅ **Issue #78**: Thermal Analytics - complete heating cycle tracking with first/second order metrics
- ✅ **Issue #84**: Documented timer duration workaround via services
- ✅ **Issue #93**: Hot Water Timer buttons now use entity registry lookup
- ✅ **Discussion #86**: API Monitoring Sensors for dashboard visualization

---

## v1.10.0 (2026-02-05) - Coordinator Race Condition Fix

### Bug Reports & Issue Reporters

**[@hapklaar](https://github.com/hapklaar)**, **[@chinezbrun](https://github.com/chinezbrun)**, **[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Extensive testing through v1.9.5-v1.9.7 iterations
- Detailed logs showing race conditions, flickering, and state sync issues
- Patience through multiple hotfix attempts
- Real-world testing across different network conditions and geographic locations
- Identified environmental factors (network latency, ISP routing) affecting race conditions

### What Was Fixed

- ✅ **Issue #44**: Complete architectural fix for coordinator race condition
- ✅ **Issue #44**: Fixed climate entity flickering during rapid mode changes
- ✅ **Issue #44**: Fixed state not syncing after mode changes
- ✅ **Issue #44**: Fixed optimistic updates not working consistently
- ✅ **Issue #44**: Fixed heating power stuck after mode change
- ✅ **Issue #44**: Fixed grey loading state during rapid changes
- ✅ **Issue #44**: Fixed rapid mode changes causing confusion (HEAT→OFF→AUTO)

---

## v1.9.7 (2026-02-04) - Explicit Optimistic State Tracking

### Bug Reports & Issue Reporters

**[@chinezbrun](https://github.com/chinezbrun)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported state flickering when rapidly changing modes (HEAT → OFF → AUTO)
- Identified that time-based window wasn't tracking WHAT state to preserve
- Provided detailed logs showing wrong state preservation

### What Was Fixed

- ✅ **Issue #44**: Fixed state flickering during rapid mode changes
- ✅ **Issue #44**: Fixed wrong state preservation (OFF mode no longer preserves old HEAT state)

---

## v1.9.6 (2026-02-04) - Optimistic Update Consistency Fix

### Bug Reports & Issue Reporters

**[@hapklaar](https://github.com/hapklaar)**, **[@chinezbrun](https://github.com/chinezbrun)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported hvac_action reverting to IDLE after ~17 seconds
- Identified that optimistic update wasn't preserving hvac_action consistently
- Continued testing and detailed feedback

### What Was Fixed

- ✅ **Issue #44**: hvac_action now stays at "Heating" consistently instead of reverting to "Idle"
- ✅ Improved state consistency for all entity types (hot water, switches)
- ✅ Better API failure handling with proper rollback

---

## v1.9.5 (2026-02-02) - Hotfix: hvac_action not updating

### Bug Reports & Issue Reporters

**[@hapklaar](https://github.com/hapklaar)**, **[@chinezbrun](https://github.com/chinezbrun)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported hvac_action not updating for the zone being changed
- Identified pattern: Zone A's hvac_action only updates after changing Zone B
- Provided detailed logs showing optimistic update wasn't setting hvac_action based on temperature

### What Was Fixed

- ✅ **Issue #44**: hvac_action now updates immediately based on target vs current temperature
  - Heating zones: `hvac_action = HEATING` when target > current
  - Heating zones: `hvac_action = IDLE` when target <= current
  - AC zones: `hvac_action` matches current mode when changing temperature

---

## v1.9.4 (2026-02-02) - Boost Buttons & Bug Fixes

### Bug Reports & Issue Reporters

**[@hapklaar](https://github.com/hapklaar)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported hvac_action stuck on "Heating" after switching to Auto mode
- Provided debug logs showing the optimistic update wasn't setting hvac_action

**[@chinezbrun](https://github.com/chinezbrun)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported Heating Power sensor not updating immediately after actions
- Confirmed v1.9.3 speed improvements and identified remaining sensor delay

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported AC startup validation warnings ("Fan mode is not valid")
- Tested and confirmed the fix

### What Was Fixed

- ✅ **Issue #44**: hvac_action now sets to IDLE when switching to AUTO mode (optimistic update)
- ✅ **Issue #44**: Zone sensors (Temperature, Humidity, Heating Power) now update immediately via signal
- ✅ **Issue #44**: AC startup validation warnings suppressed by setting default fan/swing modes

### New Features

- ✅ **Boost Button** - Official Tado-style boost (25°C for 30 min)
- ✅ **Smart Boost Button** - Intelligent duration based on heating rate

---

## v1.9.3 (2026-02-02) - Fix: Slow State Confirmation

### Bug Reports & Issue Reporters

**[@hapklaar](https://github.com/hapklaar)**, **[@chinezbrun](https://github.com/chinezbrun)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported slow state confirmation (25-30s delay) after climate changes
- @hapklaar provided detailed screenshots and debug logs that confirmed the root cause
- Identified that immediate refresh handler updated zones.json but entities didn't re-read

### What Was Fixed

- ✅ **Issue #44**: Signal-based entity update - climate entities now listen for `SIGNAL_ZONES_UPDATED` and re-read fresh data immediately after zones.json refresh
- ✅ State confirmation time reduced from 25-30s to ~6-8s (debounce_delay + API time)

---

## v1.9.2 (2026-02-01) - Hotfix: Grey Loading State

### Bug Reports & Issue Reporters

**[@chinezbrun](https://github.com/chinezbrun)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported grey loading state issue (15-20 second delay) when changing climate modes
- Extensive testing across multiple versions (v1.5.0 to v1.9.1) to help identify the regression
- Provided detailed timestamps and screenshots showing the delay

### What Was Fixed

- ✅ **Issue #44**: Grey loading state - changed from fire-and-forget to await pattern for API calls
- ✅ Service calls now await API completion (with 10s timeout) for proper HA Frontend state sync
- ✅ Fixed race condition where refresh failures incorrectly triggered rollback
- ✅ Fixed Smart Comfort cache bloat - deduplicate readings on cache load

---

## v1.9.1 (2026-01-31) - Hotfix: Device Migration Error

### Bug Reports & Issue Reporters

**[@thefern69](https://github.com/thefern69)** - [Issue #74](https://github.com/hiall-fyi/tado_ce/issues/74)
- Reported startup crash after upgrading to v1.9.0
- Identified device identifier unpacking error in migration code
- Quick bug report that caught this critical issue within hours of release

### What Was Fixed

- ✅ **Issue #74**: Device migration error - fixed identifier tuple unpacking for non-standard device identifiers

---

## v1.9.0 (2026-01-31) - Smart Comfort Analytics + Bug Fixes

### Feature Ideas & Suggestions

**[@thefern69](https://github.com/thefern69)** - [Discussion #33](https://github.com/hiall-fyi/tado_ce/discussions/33)
- Proposed room-aware early start / preheat concept
- Inspired the Smart Comfort Analytics suite (heating rate, cooling rate, preheat advisor)

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #64](https://github.com/hiall-fyi/tado_ce/issues/64)
- Proposed Mold Risk Indicator based on temp + humidity
- Suggested environment monitoring features
- Inspired the Comfort Level sensor (author's personal implementation now shared with community)

### Bug Reports & Issue Reporters

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #54](https://github.com/hiall-fyi/tado_ce/issues/54)
- Reported API reset detection not working with 100-call limit accounts
- Helped identify that hardcoded threshold needed to be dynamic

**[@neonsp](https://github.com/neonsp)** - [Issue #61](https://github.com/hiall-fyi/tado_ce/issues/61)
- Reported Refresh AC Capabilities button not recording API calls in history
- Identified missing call type tracking for capabilities endpoint

**[@colinada](https://github.com/colinada)** - [Issue #66](https://github.com/hiall-fyi/tado_ce/issues/66)
- Reported temperature offset only applying to first TRV in multi-TRV rooms
- Identified that offset service needed to loop through all devices

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #56](https://github.com/hiall-fyi/tado_ce/issues/56)
- Reported Battery/Connection sensors assigned to wrong zone when device serves multiple zones
- Helped identify that HEATING zones should be prioritized over HOT_WATER

**[@hapklaar](https://github.com/hapklaar)**, **[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Continued testing and feedback on AC turn-off behavior
- Debug logging added to help diagnose intermittent restore-to-ON issue

### What Was Added/Fixed

- ✅ **Discussion #33**: Smart Comfort Analytics - Heating Rate, Cooling Rate, Time to Target, Heating Efficiency, Preheat Advisor
- ✅ **Issue #64**: Environment Sensors - Mold Risk Indicator, Comfort Level sensor
- ✅ **Issue #54**: API reset detection now uses dynamic threshold for both 5000 and 100 call limits
- ✅ **Issue #61**: Refresh AC Capabilities button now tracked in call history (Code 8)
- ✅ **Issue #66**: Temperature offset now applied to ALL devices in multi-TRV zones
- ✅ **Issue #56**: Device sensors now assigned to HEATING zones over HOT_WATER when device serves multiple zones
- ✅ **Issue #44**: Added detailed debug logging for AC turn-off diagnosis

---

## v1.8.3 (2026-01-26) - AC Optimistic Updates & Cached Capabilities

### Bug Reports & Issue Reporters

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44), [Issue #61](https://github.com/hiall-fyi/tado_ce/issues/61)
- Reported AC OFF→ON only shows mode change, not temperature/fan/hvac_action
- Reported restart consuming 6 API calls (4 for AC capabilities that don't change)
- Identified that AC capabilities should be cached

### What Was Fixed

- ✅ **Issue #44**: AC OFF→ON optimistic updates now include hvac_mode and hvac_action
- ✅ **Issue #61**: AC capabilities now cached on first fetch, saving API calls on every restart

---

## v1.8.2 (2026-01-26) - AC Optimistic Updates Enhancement

### Bug Reports & Issue Reporters

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported AC turning on from OFF only shows mode change, not temperature/fan mode
- Identified that optimistic updates needed to include all attributes

**[@hapklaar](https://github.com/hapklaar)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported Resume All Schedules button taking ~20 seconds to update
- Identified debounce delay was being applied unnecessarily

### What Was Fixed

- ✅ **Issue #44**: AC optimistic updates now include temperature, fan mode, and hvac action when turning on
- ✅ **Issue #44**: Resume All Schedules button now refreshes immediately (skips debounce delay)

---

## v1.8.1 (2026-01-26) - AC Optimistic Updates Hotfix

### Bug Reports & Issue Reporters

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported AC zones still bouncing back after v1.8.0
- Identified that AC class was missing optimistic update protection

**[@hapklaar](https://github.com/hapklaar)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported Resume All Schedules button not refreshing climate entities

### What Was Fixed

- ✅ **Issue #44**: AC optimistic updates - AC zones now have same protection as heating zones
- ✅ **Issue #44**: Resume All Schedules refresh - button now properly triggers immediate refresh
- ✅ AC state changes (temperature, mode, fan, swing) update immediately without bouncing back

---

## v1.8.0 (2026-01-26) - Schedule Calendar & Multi-Home Data

### Feature Contributors

**Schedule Calendar** - [Discussion #51](https://github.com/hiall-fyi/tado_ce/discussions/51)
- Per-zone calendar entities showing heating schedules from Tado app
- Opt-in feature to minimize API calls

### Bug Reports & Issue Reporters

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #54](https://github.com/hiall-fyi/tado_ce/issues/54), [Issue #55](https://github.com/hiall-fyi/tado_ce/issues/55)
- Requested `last_reset` and `reset_at` attributes on API Reset sensor
- Suggested Home State Sync should default to OFF (consistent with Weather/Mobile Devices)
- Helped maintain API-saving defaults across all optional features

### What Was Added/Fixed

- ✅ **NEW**: Schedule Calendar - per-zone calendar entities (opt-in)
- ✅ **NEW**: Per-zone Refresh Schedule button
- ✅ **NEW**: API Reset sensor `reset_at` and `last_reset` attributes ([#54](https://github.com/hiall-fyi/tado_ce/issues/54))
- ✅ Multi-home prep: Per-home data files (`zones_{home_id}.json`)
- ✅ Auto-migration for existing data files
- ✅ **Issue #55**: Home State Sync default changed to OFF

---

## v1.7.0 (2026-01-26) - Multi-Home Preparation

### Bug Reports & Feature Contributors

**[@neonsp](https://github.com/neonsp)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44), [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Reported UI not updating immediately after state changes
- Requested optional homeState sync to save API calls
- Continued testing and feedback

### What Was Added/Fixed

- ✅ **Issue #44**: Optimistic state updates - immediate UI feedback with rollback on failure
- ✅ **Issue #31**: Optional homeState sync - saves 1 API call per quick sync
- ✅ Multi-home prep: unique_id migration to `tado_ce_{home_id}`
- ✅ Fixed options float validation (NumberSelector returns float)

---

## v1.6.0 (2026-01-25) - Refresh & Automation Fixes

### Bug Reports & Issue Reporters

**[@neonsp](https://github.com/neonsp)** - [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Reported `climate.set_temperature` ignoring `hvac_mode` parameter in Node-RED
- Helped identify missing `ATTR_HVAC_MODE` handling in `async_set_temperature()`

**[@hapklaar](https://github.com/hapklaar)** - [Issue #44](https://github.com/hiall-fyi/tado_ce/issues/44)
- Reported climate entities not updating consistently when changing multiple zones
- Identified Resume All Schedules button not refreshing dashboard
- Provided detailed screenshots showing the issue

### What Was Fixed

- ✅ **Issue #31**: `climate.set_temperature` now handles `hvac_mode` parameter for Node-RED/automation compatibility
- ✅ **Issue #44**: Debounced refresh mechanism for multi-zone updates (multiple changes = 1 API call)
- ✅ **Issue #44**: Resume All Schedules button now triggers immediate refresh

---

## v1.5.5 (2026-01-24) - AC Auto Mode & API Optimization

### Bug Reports & Issue Reporters

**[@neonsp](https://github.com/neonsp)** - [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Reported AC Auto mode turning off AC instead of setting Tado's AUTO mode
- Identified 3 API calls per state change, suggested optimization
- Continued testing and feedback throughout v1.5.x AC fixes

### What Was Fixed

- ✅ **Issue #31**: AC Auto mode fix - removed confusing `AUTO` option (use `Heat/Cool` instead)
- ✅ **Issue #31**: Reduced API calls per state change from 3 to 2 (optimized immediate refresh)

---

## v1.5.4 (2026-01-24) - Complete AC Fix

### Bug Reports & Issue Reporters

**[@neonsp](https://github.com/neonsp)** - [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Comprehensive AC testing and debug output
- Identified all 6 AC issues (fan/swing state, idle status, DRY mode, temperature, swing reset, power sensor)
- Provided API response data confirming correct field names (`fanLevel`, `verticalSwing`, `horizontalSwing`, `acPower.value`)
- Suggested unified swing dropdown matching official integration

### What Was Fixed/Added

- ✅ **Issue #31**: AC fan/swing state not updating - fixed field names
- ✅ **Issue #31**: AC always showing "idle" - use `acPower.value`
- ✅ **Issue #31**: DRY mode 422 error - mode-specific payload
- ✅ **Issue #31**: Temperature disappearing when AC off - preserve value
- ✅ **Issue #31**: Swing reset when changing settings - preserve unified state
- ✅ **Issue #31**: AC Power sensor showing 0% - handle `value` vs `percentage`
- ✅ Unified swing dropdown (off/vertical/horizontal/both)
- ✅ Entity unique_id stability (use zone_id instead of zone_name)

---

## v1.5.3 (2026-01-24) - AC Fix & Resume All Schedules

### Bug Reports & Issue Reporters

**[@neonsp](https://github.com/neonsp)** - [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Reported AC control 422 errors
- Provided critical API payload from app.tado.com showing correct field names
- Helped identify `fanSpeed` → `fanLevel`, `swing` → `verticalSwing`/`horizontalSwing` fix

### Feature Contributors

**[@hapklaar](https://github.com/hapklaar)** - [Discussion #39](https://github.com/hiall-fyi/tado_ce/discussions/39)
- Requested Resume All Schedules button
- Shared automation use case for resetting manual overrides

### What Was Fixed/Added

- ✅ **Issue #31**: AC control 422 error - fixed API field names
- ✅ **Discussion #39**: Resume All Schedules button on Hub device
- ✅ Blocking I/O warning in config_flow.py
- ✅ Comprehensive upgrade logging at INFO level

---

## v1.5.2 (2026-01-24) - Data Storage Fix

### Bug Reports & Issue Reporters

**[@jeverley](https://github.com/jeverley)** - [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Reported token loss after HACS upgrade
- Identified that data directory was being overwritten

**[@hapklaar](https://github.com/hapklaar)** - [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Confirmed token loss issue
- Helped validate the problem

**[@wrowlands3](https://github.com/wrowlands3)** - [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Additional confirmation of the upgrade issue

### What Was Fixed

- ✅ **Issue #34**: Token loss on HACS upgrade - data directory moved to `/config/.storage/tado_ce/`

---

## v1.5.1 (2026-01-24) - OAuth & Re-auth Fix

### Bug Reports & Issue Reporters

**[@mkruiver](https://github.com/mkruiver)** - [Issue #36](https://github.com/hiall-fyi/tado_ce/issues/36)
- Reported OAuth flow "invalid flow specified" error for new users

**[@jeverley](https://github.com/jeverley)** - [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Requested re-authenticate option in UI

**[@hapklaar](https://github.com/hapklaar)** - [Issue #34](https://github.com/hiall-fyi/tado_ce/issues/34)
- Supported re-authenticate feature request

**[@harryvandervossen](https://github.com/harryvandervossen)** - [Discussion #35](https://github.com/hiall-fyi/tado_ce/discussions/35)
- Provided detailed OAuth flow feedback

### What Was Fixed

- ✅ **Issue #36**: OAuth flow error - simplified to manual check approach
- ✅ **Issue #34**: Re-authenticate option added via reconfigure flow

---

## v1.5.0 (2026-01-24) - Async & Stability Release

### Bug Reports & Issue Reporters

**[@hapklaar](https://github.com/hapklaar)** - [Issue #26](https://github.com/hiall-fyi/tado_ce/issues/26)
- Reported null value crash in water_heater entities
- Helped identify the `temperature: null` API response issue for HOT_WATER zones

**[@neonsp](https://github.com/neonsp)** - [Issue #31](https://github.com/hiall-fyi/tado_ce/issues/31)
- Reported AC zone missing DRY/FAN modes, fan levels, and swing options
- Provided detailed API response data showing AC capabilities endpoint
- Helped identify that AC capabilities require separate API endpoint

### Feature Contributors

**[@pisolofin](https://github.com/pisolofin)** - [Issue #24](https://github.com/hiall-fyi/tado_ce/issues/24)
- Requested `get_temperature_offset` service for automations

**[@ohipe](https://github.com/ohipe)** - [Issue #25](https://github.com/hiall-fyi/tado_ce/issues/25)
- Requested optional `offset_celsius` attribute on climate entities
- Identified HVAC mode behavior difference from official integration

**[@beltrao](https://github.com/beltrao)** - [Issue #28](https://github.com/hiall-fyi/tado_ce/issues/28)
- Requested frequent mobile device sync option for presence automations

### What Was Fixed/Added

- ✅ **Issue #24**: `tado_ce.get_temperature_offset` service
- ✅ **Issue #25**: Optional `offset_celsius` attribute, HVAC mode logic fix
- ✅ **Issue #26**: Null value crash fix for water_heater and climate entities
- ✅ **Issue #27**: Async migration, blocking I/O warning fix
- ✅ **Issue #28**: Frequent mobile device sync option
- ✅ **Issue #31**: Full AC capabilities support (DRY/FAN modes, fan levels, swing)

---

## v1.4.1 (2026-01-23) - Hotfix Release

### Bug Reports & Issue Reporters

**[@hapklaar](https://github.com/hapklaar)** - [Issue #26](https://github.com/hiall-fyi/tado_ce/issues/26)
- First to report authentication broken after v1.2.1 → v1.4.0 upgrade
- Quick bug report that caught this critical issue early

**[@mjsarfatti](https://github.com/mjsarfatti)** - [Issue #26](https://github.com/hiall-fyi/tado_ce/issues/26)
- Additional confirmation of the upgrade issue
- Helped validate the problem

### What Was Fixed

- ✅ **Issue #26**: Authentication broken after upgrade - missing migration path from VERSION 2/3 to VERSION 4

---

## v1.4.0 (2026-01-23) - Setup Simplification Release

### Feature Contributors

**Setup Flow Redesign**
- New device authorization flow - no more SSH required
- Home selection for multi-home accounts

### Bug Reports & Issue Reporters

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #15](https://github.com/hiall-fyi/tado_ce/issues/15), [Issue #16](https://github.com/hiall-fyi/tado_ce/issues/16), [Issue #17](https://github.com/hiall-fyi/tado_ce/issues/17)
- Reported Boiler Flow Temperature sensor issues
- Identified API Reset time confusion after re-authentication
- Reported Options UI issues (checkboxes, values not saving)
- Suggested uniform polling mode

**[@jeverley](https://github.com/jeverley)** - [Issue #22](https://github.com/hiall-fyi/tado_ce/issues/22)
- Reported climate preset mode stuck on Away
- Helped identify mobile device location vs home state issue

**[@hapklaar](https://github.com/hapklaar)**
- Volunteered for OpenTherm testing

### What Was Fixed

- ✅ **Issue #15**: Boiler Flow Temperature sensor - auto-detect OpenTherm, moved to Hub device
- ✅ **Issue #16**: API Reset time now uses actual Tado API reset time
- ✅ **Issue #17**: Options UI fixes, uniform polling mode support
- ✅ **Issue #22**: Climate preset mode now uses home state instead of mobile device location

---

## v1.2.1 (2026-01-22) - Hotfix Release

### Bug Reports & Issue Reporters

**[@marcovn](https://github.com/marcovn)** - [Issue #10](https://github.com/hiall-fyi/tado_ce/issues/10), [Issue #11](https://github.com/hiall-fyi/tado_ce/issues/11)
- Reported duplicate hub issue after v1.1.0 → v1.2.0 upgrade
- Reported confusing entity names for multi-device zones
- Provided valuable feedback and testing
- Helped identify both critical issues in v1.2.1

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #10](https://github.com/hiall-fyi/tado_ce/issues/10)
- Reported duplicate hub cleanup issue
- Provided detailed testing feedback
- Helped validate the fix

**[@hapklaar](https://github.com/hapklaar)** - [Issue #10](https://github.com/hiall-fyi/tado_ce/issues/10)
- Reported duplicate hub issue
- Contributed to testing and validation

### What Was Fixed

- ✅ **Issue #10**: Duplicate hub cleanup race condition - automatic cleanup on upgrade
- ✅ **Issue #11**: Multi-device zone entity naming - clear device type + index suffixes

---

## v1.2.0 (2026-01-21) - Major Stability Release

### Feature Contributors

**[@wrowlands3](https://github.com/wrowlands3)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Requested zone-based device organization
- Suggested improved entity naming (remove "Tado CE" prefix)
- Highlighted difficulty in searching and identifying zones in UI
- Helped shape the device organization structure

**[@ChrisMarriott38](https://github.com/ChrisMarriott38)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Requested boiler flow temperature sensor integration
- Suggested optional weather sensors toggle to save API calls
- Requested API call tracking with detailed history and diagnostic codes
- Suggested enhanced reset time display (human-readable timestamp)
- Proposed customizable day/night polling intervals for shift workers
- Requested test mode with enforced API limits (100 calls) for testing
- Suggested pre-release testing mechanism for community feedback
- Provided extensive testing feedback and bug reports
- Identified API polling patterns and optimization opportunities
- Shared advanced use cases: mold risk calculations, air quality index, weather compensation for heat pumps
- Helped validate temperature and humidity sensor functionality
- Provided detailed feedback on API optimization and usage patterns

**[@donnie-darko](https://github.com/donnie-darko)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Requested `set_water_heater_timer` service with temperature parameter
- Proposed service compatibility with official Tado integration
- Shared solar water heater use case and automation requirements
- Suggested parameter naming alignment (`time_period` vs `duration`)
- Helped shape service design for seamless migration from official integration
- Provided NODE-RED workflow requirements for solar thermal systems

**[@marcovn](https://github.com/marcovn)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Participated in Issue #4 discussions
- Contributed to community feedback

**[@StreborStrebor](https://github.com/StreborStrebor)** - [Issue #4](https://github.com/hiall-fyi/tado_ce/issues/4)
- Requested immediate refresh after user actions
- Highlighted the 2-minute delay issue
- Reported device card not updating after temperature/mode changes
- Requested AC fan mode controls (Auto, Low, Medium, High)
- Requested AC swing mode controls (Off, Vertical, Horizontal, Both)
- Suggested disabling weather polling to free up API calls for more frequent updates
- Helped prioritize UX improvements

### Bug Reports & Issue Reporters

**[@LorDHarA](https://github.com/LorDHarA)** - [Issue #1](https://github.com/hiall-fyi/tado_ce/issues/1) *(Fixed in v1.0.1)*
- Identified 403 authentication error for new users
- Led to auto-fetch home ID feature
- Helped improve initial setup experience

**[@hapklaar](https://github.com/hapklaar)** - [Issue #2](https://github.com/hiall-fyi/tado_ce/issues/2), [Issue #5](https://github.com/hiall-fyi/tado_ce/issues/5)
- Suggested adding humidity attribute to climate entities *(Implemented in v1.1.0)*
- Suggested adding preset mode support (Home/Away) *(Implemented in v1.1.0)*
- Reported away mode switch toggling back issue
- Reported 2-minute delay for temperature/mode changes
- Both issues fixed with Immediate Refresh feature
- Generous Buy Me a Coffee supporter! ☕

**[@MJWMJW2](https://github.com/MJWMJW2)** - [Issue #3](https://github.com/hiall-fyi/tado_ce/issues/3) *(Implemented in v1.1.0)*
- Requested Away Mode switch for manual Home/Away toggle
- Improved geofencing control

**[@ctcampbell](https://github.com/ctcampbell)** - [Issue #6](https://github.com/hiall-fyi/tado_ce/issues/6)
- Requested proper AUTO/HEAT/OFF operation modes for hot water
- Highlighted limitations of ON/OFF only modes (water runs forever or schedule never runs)
- Requested timer-based HEAT mode support
- Requested AUTO mode to return to schedule
- Led to comprehensive hot water operation modes implementation in v1.2.0

**[@greavous1138](https://github.com/greavous1138)** - [Issue #7](https://github.com/hiall-fyi/tado_ce/issues/7)
- Reported `duration` parameter not working in `climate.set_temperature` service
- Identified YAML configuration error with timer duration
- Requested boost button feature
- Helped identify service parameter issues
- Contributed to climate timer service improvements

**[@thefern69](https://github.com/thefern69)** - [Issue #9](https://github.com/hiall-fyi/tado_ce/issues/9)
- Provided Docker installation instructions
- Helped improve README documentation for Docker users

### Community Quotes

> "This integration saves me from rate limit headaches!" - Community feedback

> "The immediate refresh feature is exactly what I needed!" - @hapklaar

> "Zone-based devices make organization so much better!" - @wrowlands3

> "API call tracking gives me peace of mind about my quota." - @ChrisMarriott38

> "What an incredible reply! So detailed thanks! I'm ultra novice at code things, just a dabble here and there, but have done Extensive testing for other tools/plugins/web/developers over the years for work." - @ChrisMarriott38

> "Boiler Flow would be my No1 To be included in the API pull. So i dont have to have that as a separate rest API call if possible. to save the Limit." - @ChrisMarriott38

> "This integration turns 'on' which turns the water on until I manually cancel the state (i.e. forever), or 'off' which means my schedule never runs." - @ctcampbell (Issue #6 - Fixed in v1.2.0)

> "First of all, thanks for making this integration, this morning I was actually able to use my Tado system via HA when I woke up!" - @greavous1138

---

## 🌟 Special Thanks

**Hardware Verification:**

**[@wyx087](https://github.com/wyx087)** - [Discussion #21](https://github.com/hiall-fyi/tado_ce/discussions/21)
- Verified Tado V2 hardware compatibility
- Confirmed integration works perfectly with V2 devices

**Community Testers & Feedback Providers:**
- Users who shared their setup configurations
- Community members who provided detailed use cases
- All supporters on Buy Me a Coffee

**Technical Contributions:**
- Bug reports that helped identify edge cases
- Feature requests that shaped the roadmap
- Detailed feedback on API usage patterns
- Real-world testing across different Tado setups
- Advanced automation examples (mold risk, air quality, weather compensation)
- Documentation improvements and setup guides

---

## 📊 Overall Impact

**Total Issues Addressed:** 25+ issues across all versions
**Features Implemented:** 30+ new features
**Bug Fixes:** 20+ critical/high-priority fixes
**API Optimization:** 60-70% reduction in API calls
**Community Engagement:** Active discussions and continuous feedback

---

## 🎯 Looking Forward

The community continues to shape Tado CE's future! Current discussions:

**Completed in v1.10.0:**
- ✅ Coordinator race condition fix - @hapklaar, @chinezbrun, @neonsp
- ✅ Climate entity flickering fix - @hapklaar, @chinezbrun, @neonsp
- ✅ State sync improvements - @hapklaar, @chinezbrun, @neonsp

**Completed in v1.9.4:**
- ✅ Boost button entity - @greavous1138

**Requested Features:**
- Air Comfort sensors (humidity comfort level)
- Multiple homes support (simultaneous)
- Max Flow Temperature control (requires OpenTherm) - @ChrisMarriott38
- Combi boiler mode - @ChrisMarriott38
- Auto-assign devices to Areas during setup
- Local API support (reduce cloud dependency) - [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)

**Want to contribute?** Open an issue or join the discussion on [GitHub](https://github.com/hiall-fyi/tado_ce/issues)!

---

**Made with ❤️ by the Tado CE community**

*Special thanks to everyone who uses, tests, reports issues, and supports this project. You make this integration better every day!*
