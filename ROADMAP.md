# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

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
- **Global Surface Temp Offset** - Optional offset for users with laser thermometer measurements

**API Management:**
- **Call Priority System** - Configurable weighting for different call types (e.g., zoneStates every 10 min, weather every 30 min). Requires significant coordinator architecture changes. Low priority - current adaptive polling handles most use cases.

**Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)):
- **Indoor Air Quality (IAQ)** - Air quality score per zone (requires additional sensors)
- **Air Comfort** - Similar to Tado app's comfort visualization

**Hub Controls Migration:**
- **Quota Reserve Toggle** - Move `quota_reserve_enabled` from Config Options to Hub Controls for runtime toggle without reload
- **Test Mode Toggle** - Move `test_mode_enabled` from Config Options to Hub Controls for easier debugging
- **Benefit**: Allows automation control (e.g., "disable quota reserve when API remaining > 50") and faster toggling without entering Config Options
- **Note**: Waiting for community feedback on use cases before implementation

**Open Window Detection** ([#106](https://github.com/hiall-fyi/tado_ce/issues/106)):
- **Per-Zone Temperature Sensor Override** - Allow selecting any HA temperature sensor (HomeKit, Zigbee, etc.) per zone for faster updates
- **Rapid Temp Drop Detection** - Custom open window detection with configurable threshold (e.g., >2°C drop in 15 min)
- **Note**: Requires testing HomeKit sensor behavior (update frequency, reliability) before implementation

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
