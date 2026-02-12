# Changelog

All notable changes to Tado CE will be documented in this file.

## [2.0.2] - 2026-02-12

**Presence Mode Select & Overlay Mode Fix**

### ⚠️ Breaking Changes

- **Presence Mode Select** - `switch.tado_ce_away_mode` replaced by `select.tado_ce_presence_mode` ([Discussion #102](https://github.com/hiall-fyi/tado_ce/discussions/102) - @wyx087)
  - Migration: Update automations from `switch.turn_on/turn_off` to `select.select_option`
  - New "Auto" option resumes geofencing (was not possible with switch)

- **Overlay Mode Default** - Changed from `MANUAL` to `TADO_MODE` ([#101](https://github.com/hiall-fyi/tado_ce/issues/101) - @leoogermenia)
  - Temperature changes now respect per-device "Manual Control" settings in Tado app
  - Users relying on infinite override should set "Until you cancel" in Tado app

### Features
- **Presence Mode Select** - New `select.tado_ce_presence_mode` with 3 options:
  - `auto` - Resume geofencing (deletes presence lock)
  - `home` - Manual Home mode
  - `away` - Manual Away mode

### Improvements
- **TADO_MODE Termination** - Overlay behavior now follows Tado app settings per device
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
