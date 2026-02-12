# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## v2.0.0 - Adaptive Polling, Thermal Analytics, Enhanced Mold Risk, Adaptive Preheat & API Monitoring

Major release with adaptive polling, thermal analytics, enhanced mold risk, adaptive preheat, and API monitoring.

### ✅ All Completed

**Adaptive Smart Polling** ([#89](https://github.com/hiall-fyi/tado_ce/issues/89)):
- [x] Real-time adaptive intervals - Calculate polling based on remaining quota and time
- [x] Universal quota support - Works for any tier (100, 5000, 20000)
- [x] Self-healing behavior - Automatically adapts to manual calls and HA restarts
- [x] Transparent logging - Full visibility into interval calculations
- [x] Quota Reserve Protection - Pauses polling when quota critically low

**Enhanced Mold Risk Assessment** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)):
- [x] U-value estimation - Calculate window surface temperature from outdoor temp and window type
- [x] 2-tier fallback strategy - Automatic fallback: U-value estimation → room temperature
- [x] Configurable window types - Single/double/triple pane with standard U-values
- [x] ASHRAE 160 compliance - Surface temperature-based mold risk assessment

**Thermal Analytics** ([#78](https://github.com/hiall-fyi/tado_ce/issues/78)):
- [x] Two-Phase Heating Model - Separate boost and maintenance phases
- [x] Heating Cycle Tracking - Track heating cycles with start/end times
- [x] Smart Comfort Analytics - Comfort score, thermal stability, efficiency metrics
- [x] Second-Order Analysis - Heating acceleration and approach factor for improved preheat estimation
- [x] Heating Acceleration Sensor - Shows how quickly heating rate increases (°C/h²)
- [x] Approach Factor Sensor - Shows deceleration near setpoint (%)
- [x] Preheat Binary Sensor - `binary_sensor.{zone}_preheat_now` turns ON when it's time to start heating ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- [x] UFH Slow Response Mode - Configurable buffer time for underfloor heating thermal lag ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- [x] Adaptive Preheat - Auto-trigger heating when preheat_now turns ON, uses NEXT_TIME_BLOCK termination ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)

**API Monitoring** ([#65](https://github.com/hiall-fyi/tado_ce/issues/65), [Discussion #86](https://github.com/hiall-fyi/tado_ce/discussions/86)):
- [x] Next Sync Sensor - Shows next API sync time with countdown
- [x] Polling Interval Sensor - Shows current polling interval with source
- [x] Call History Sensor - API call history with statistics
- [x] API Call Breakdown Sensor - Breakdown by endpoint type
- [x] Granular API Call Options - Enable/disable optional call types in Options

**Multi-Home Infrastructure** (foundation for future multi-home support):
- [x] Per-home data file naming - `get_data_file(base_name, home_id)` in const.py
- [x] Data loader home_id support - `set_current_home_id()` / `get_current_home_id()`
- [x] Hub device identifier with home_id - `tado_ce_hub_{home_id}` format

**Setup & Polish:**
- [x] Auto-assign Areas - Match zone names to HA areas using fuzzy matching ([#14](https://github.com/hiall-fyi/tado_ce/issues/14))
- [x] Setup wizard improvements - Streamlined flow with better error messages
- [x] Cleanup deprecated files - Removed tado_api.py, error_handler.py, orphan data files

---

## v2.0.1 - Mold Risk Percentage Sensor, Hot Water Fix, Bootstrap Reserve & Test Mode Enhancement

**Mold Risk Enhancements** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)):
- [x] **Mold Risk Percentage Sensor** - `sensor.{zone}_mold_risk_percentage` exposes surface RH as dedicated sensor for history/graphs

**Bug Fixes** ([#98](https://github.com/hiall-fyi/tado_ce/issues/98)):
- [x] **Hot Water 3-Layer Defense** - Full parity with climate entities for optimistic updates

**Quota Reserve Improvements** ([#99](https://github.com/hiall-fyi/tado_ce/issues/99) - @ChrisMarriott38):
- [x] **Bootstrap Reserve** - Hard limit of 3 calls that are NEVER used (even for manual actions), reserved for auto-recovery after API reset
- [x] **Persistent Notification** - Show HA notification when API limit exceeded, explaining to use Tado app for emergency changes

**Test Mode Enhancement** ([#97](https://github.com/hiall-fyi/tado_ce/issues/97), [#98](https://github.com/hiall-fyi/tado_ce/issues/98), [#99](https://github.com/hiall-fyi/tado_ce/issues/99)):
- [x] **Full 100-Call Simulation** - Test Mode now fully simulates a 100-call API tier for end-to-end testing of quota protection features
- [x] **Single Source of Truth** - All simulated values stored in `ratelimit.json`, read by all components without recalculation
- [x] **Simulated Quota Tracking** - Each API call increments simulated `used` counter (capped at 100)
- [x] **Reset Detection** - Detects real API reset and resets simulated counter to 0
- [x] **test_mode Attribute** - All API sensors now show `test_mode: true/false` attribute for visibility

---

## v2.0.2 - Presence Mode Select Entity & Overlay Mode Fix

### ✅ All Completed

**Presence Mode Enhancement** ([Discussion #102](https://github.com/hiall-fyi/tado_ce/discussions/102) - @wyx087):
- [x] **Presence Mode Select** - Replace `switch.tado_ce_away_mode` with `select.tado_ce_presence_mode`
- [x] **3 Options** - `auto` (resume geofencing), `home` (manual), `away` (manual)
- [x] **DELETE API** - Add `delete_presence_lock()` to resume geofencing (Auto mode)
- [x] **Breaking Change** - Existing automations using `switch.tado_ce_away_mode` will need updating

**Overlay Mode Fix** ([#101](https://github.com/hiall-fyi/tado_ce/issues/101) - @leoogermenia):
- [x] **Change Default to TADO_MODE** - Remove hardcoded `MANUAL` termination, use `TADO_MODE` instead
- [x] **Respect Tado App Settings** - Overlay behavior now follows per-device "Manual Control" setting in Tado app
- [x] **Zero Config** - No new settings needed, users configure overlay mode in Tado app as intended
- [x] **Both Heating & AC** - Applied to `TadoClimate` and `TadoACClimate` classes
- [x] **Breaking Change** - Users relying on infinite `MANUAL` override should update Tado app settings
- [ ] **Both Heating & AC** - Apply to `TadoClimate` and `TadoACClimate` classes
- [ ] **Breaking Change** - Users relying on infinite `MANUAL` override should update Tado app settings

---

## Future Consideration

Features under consideration - need more community feedback or technical research.

**Per-Zone Configuration** (Foundation for multiple features):
- **Per-Zone Settings UI** - Allow different settings per zone instead of global-only
- **Overlay Mode** - Different overlay modes per zone (e.g., bedroom uses NEXT_TIME_BLOCK, living room uses MANUAL)
- **Mold Risk Window Type** - Different window types per zone for homes with mixed windows ([#90](https://github.com/hiall-fyi/tado_ce/issues/90))
- **UFH Buffer** - Different buffer times per zone based on floor type
- **API Call Priority** - Per-zone polling frequency (e.g., main zones more frequent)
- **Note**: This is a significant UI/UX change that would benefit many features. Consider implementing as a unified "Zone Settings" page in Options flow.

**Mold Risk Enhancements** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)):
- ~~Per-Zone Window Type~~ - Moved to "Per-Zone Configuration" above

**API Management:**
- **Call Priority System** - Configurable weighting for different call types (e.g., zoneStates every 10 min, weather every 30 min). Requires significant coordinator architecture changes. Low priority - current adaptive polling handles most use cases.

**Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)):
- **Indoor Air Quality (IAQ)** - Air quality score per zone (requires additional sensors)
- **Air Comfort** - Similar to Tado app's comfort visualization

**Other:**
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- Combi boiler mode - hide timers/schedules for on-demand hot water ([#15](https://github.com/hiall-fyi/tado_ce/issues/15))

**Local API (Experimental):**
- **Local-first, cloud-fallback** - Use local API when available, fall back to cloud. Requires community help to test across different Tado hardware versions. See [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).
- **Hybrid mode** - Configurable per-feature (e.g., local for reads, cloud for writes)

**Multi-Home Support:**
- **Multi-home preference in config flow** - New users asked "Plan to add multiple homes?" to enable home_id prefix
- **Allow multiple integration entries** - Each entry for a different home
- **Thread-safe home_id handling** - Replace global `_current_home_id` with per-entry context (current architecture uses global state that would conflict with multiple homes)
- **Per-home async_api client** - Change from singleton to per-entry client instances
- **Multi-home setup guide** - Documentation for users with multiple properties
- **Note**: Multi-home infrastructure (per-home data files, device identifiers) is already in place. Remaining work is primarily refactoring global state to per-entry context. Estimated 12-17 hours of work.

---

## Migration Design

All migrations are cumulative - users can upgrade directly from any version (e.g., v1.6.0 → v2.0.0) and all intermediate migrations will be applied automatically. Each migration step is idempotent (safe to run multiple times).

Entity IDs remain stable throughout migration if entity `unique_id` is unchanged.
