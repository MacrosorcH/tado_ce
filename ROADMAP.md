# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## v2.1.0 (In Development)

**Per-Zone Configuration**

Completed:
- ✅ 4 sections Options Flow (Tado CE Exclusive, Tado Data, Settings, Polling & API)
- ✅ Per-Zone Thermal Analytics - multi-select in Options to exclude passive zones
- ✅ Per-Zone Configuration Entities (requires "Zone Configuration" enabled):
  - `select.{zone}_heating_type` (Radiator/UFH)
  - `number.{zone}_ufh_buffer` (UFH buffer minutes)
  - `switch.{zone}_adaptive_preheat`
  - `select.{zone}_smart_comfort_mode`
  - `select.{zone}_window_type`
  - `select.{zone}_overlay_mode` (Tado Mode/Next Time Block/Timer/Manual)
  - `select.{zone}_overlay_timer_duration`
  - `number.{zone}_min_temp` / `number.{zone}_max_temp`
  - `number.{zone}_temp_offset`

Planned:
- **Per-Zone Surface Temp Offset** - Optional offset for mold risk calculation ([#90](https://github.com/hiall-fyi/tado_ce/issues/90))

---

## v2.2.0 (Planned)

**Mold Risk Enhancements** ([#109](https://github.com/hiall-fyi/tado_ce/issues/109)):
- **Actionable Recommendations** - When mold risk is Medium/High, suggest what changes would help (e.g., "Reduce humidity by 10%" or "Increase temperature by 2°C")

---

## Future Consideration

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
