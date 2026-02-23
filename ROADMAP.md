# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Future Consideration

**API Management:**
- **Call Priority System** - Configurable weighting for different call types (e.g., zoneStates every 10 min, weather every 30 min). Requires significant coordinator architecture changes. Low priority - current adaptive polling handles most use cases.

**Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)):
- **Indoor Air Quality (IAQ)** - Air quality score per zone (requires additional sensors)
- **Air Comfort** - Similar to Tado app's comfort visualization

**Open Window Detection Enhancements** ([#135](https://github.com/hiall-fyi/tado_ce/issues/135) - @ChrisMarriott38):
- **Sensitivity Dropdown** - Add `select.{zone}_window_predicted_sensitivity` entity with Low/Medium/High options
  - Low = fewer false positives, may miss some events
  - Medium = current behavior (default)
  - High = more sensitive, may have more false positives
- **Cross-Zone Heating Detection** - Check if ANY zone is heating before triggering window predicted
  - Rationale: Shared boiler/heat pump means opening a window affects whole-house efficiency
  - Challenge 1: Distinguishing "window open" from "zone naturally cooling" when another zone is heating
  - Challenge 2: Passive/rarely-used zones (e.g., guest rooms) would false-positive when other zones are heating
  - Status: Needs more real-world data and research; current per-zone approach avoids passive zone false positives
- **Note**: Current Window Predicted sensor (v2.2.0) uses fixed thresholds. Sensitivity dropdown would map to preset threshold combinations internally.

**Hub Controls Migration:**
- **Quota Reserve Toggle** - Move `quota_reserve_enabled` from Config Options to Hub Controls for runtime toggle without reload
- **Test Mode Toggle** - Move `test_mode_enabled` from Config Options to Hub Controls for easier debugging
- **Benefit**: Allows automation control (e.g., "disable quota reserve when API remaining > 50") and faster toggling without entering Config Options
- **Note**: Waiting for community feedback on use cases before implementation

**Per-Zone External Sensor Override** ([#106](https://github.com/hiall-fyi/tado_ce/issues/106)):
- **Per-Zone Temperature Sensor Override** - Allow selecting any HA temperature sensor (HomeKit, Zigbee, etc.) per zone for faster updates
- **Note**: v2.2.0 added Window Predicted sensor using local Tado temperature analysis; external sensor override for even faster detection still under consideration

**Other:**
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- ~~Combi boiler mode~~ - ✅ Fixed in v2.2.1: Hot water detection now correctly skips overlay/timer entities for combi boilers ([#115](https://github.com/hiall-fyi/tado_ce/issues/115))
- **Temperature Update Delay Investigation** ([#124](https://github.com/hiall-fyi/tado_ce/issues/124) - @hapklaar) - User reports ~2 hour update intervals and slow climate card updates. Awaiting debug logs.

**Local API (Experimental):**
- **Local-first, cloud-fallback** - Use local API when available, fall back to cloud. Requires community help to test across different Tado hardware versions. See [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).
- **Hybrid mode** - Configurable per-feature (e.g., local for reads, cloud for writes)

**Multi-Home Support:**
- **Multi-home preference in config flow** - New users asked "Plan to add multiple homes?" to enable home_id prefix
- **Allow multiple integration entries** - Each entry for a different home
- **Thread-safe home_id handling** - Replace global `_current_home_id` with per-entry context (current architecture uses global state that would conflict with multiple homes)
- **Per-home async_api client** - Change from singleton to per-entry client instances
- **Multi-home setup guide** - Documentation for users with multiple properties
- **Note**: Multi-home infrastructure (per-home data files, device identifiers) is already in place. Remaining work is primarily refactoring global state to per-entry context.
