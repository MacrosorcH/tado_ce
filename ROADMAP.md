# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## 🚧 In Progress

**Multi-Home Support** ([#110](https://github.com/hiall-fyi/tado_ce/issues/110) - @robvol87, [#145](https://github.com/hiall-fyi/tado_ce/issues/145) - @Blankf):

Refactoring global state to per-entry context to enable multiple Tado accounts/homes in a single HA instance.

✅ Already done (v1.7.0+):
- Per-home data files (`zones_{home_id}.json`, `ratelimit_{home_id}.json`, etc.)
- Per-home unique_id (`tado_ce_{home_id}`) for config entries
- Per-home ZoneConfigManager and APICallTracker
- Home selection in config flow

🔧 Remaining work:
- `_current_home_id` global → per-entry context (`hass.data[DOMAIN][entry_id]`)
- `get_async_client()` singleton → per-entry client instances
- `async_sync_tado()` → per-entry coordinator
- Per-entry cleanup in `async_unload_entry()`
- Multi-home setup guide documentation

This is also a prerequisite for the HomeKit / Data Source Abstraction work — the same `data_loader.py` coupling that blocks multi-home is the same code that needs refactoring for the data source router.

---

## Up Next

**Local API / HomeKit Hybrid** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)):

After Multi-Home is done, the path to HomeKit local control follows these phases:

1. **Data Source Abstraction Layer (Phase 1)** - Build a `DataSourceRouter` between entities and data sources (Cloud, HomeKit, future Local API/Matter). Cloud-only mode wraps existing `data_loader.py` with zero behavior change. Pure refactor.
2. **Entity Migration (Phase 2)** - Migrate entities per-file to use the router instead of direct `data_loader.py` calls. Each file independently tested. Pure refactor — no new features.
3. **HomeKit Local Control (Phase 3)** - Add HomeKit (HAP) as a data source. Local reads/writes for temperature, humidity, HVAC mode. Cloud API for data not available locally (heating %, battery, schedules, hot water). Proof of concept working — see Discussion #29 for details.
4. **Pure Local (Long-term research)** - Investigating 868MHz 6LoWPAN protocol between Bridge and TRVs for 100% local control. Requires specialized RF hardware and community help.

- **Prerequisite**: Multi-Home Support (in progress above)
- **Target**: April 2026

---

## Future Consideration

**API Management:**
- **Call Priority System** - Configurable weighting for different call types (e.g., zoneStates every 10 min, weather every 30 min). Requires significant coordinator architecture changes. Low priority - current adaptive polling handles most use cases.
- **Event-Driven Full Sync** ([#141](https://github.com/hiall-fyi/tado_ce/issues/141) - @Xavinooo) - Remove 6-hour periodic full sync, make it event-driven (only on HA restart/reload). Zone info, offsets, and AC capabilities rarely change. Saves API calls and simplifies quota planning.

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

**Per-Zone External Sensor Override** ([#106](https://github.com/hiall-fyi/tado_ce/issues/106), [#143](https://github.com/hiall-fyi/tado_ce/issues/143) - @BirbByte):
- **Per-Zone Temperature Sensor Override** - Allow selecting any HA temperature sensor (HomeKit, Zigbee, etc.) per zone for faster updates
- **Note**: v2.2.0 added Window Predicted sensor using local Tado temperature analysis; external sensor override for even faster detection still under consideration

**Other:**
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- **Temperature Update Delay Investigation** ([#124](https://github.com/hiall-fyi/tado_ce/issues/124) - @hapklaar) - User reports ~2 hour update intervals and slow climate card updates. Awaiting debug logs.
