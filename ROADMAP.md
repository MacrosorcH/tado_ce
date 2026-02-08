# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## v1.11.0 - Smart Polling & Environment Sensors

Adaptive polling and enhanced mold risk assessment.

### ✅ Completed for v1.11.0

**Adaptive Smart Polling** ([#89](https://github.com/hiall-fyi/tado_ce/issues/89)):
- [x] **Real-time adaptive intervals** - Calculate polling based on remaining quota and time
- [x] **Universal quota support** - Works for any tier (100, 200, 500, 5000, 20000+)
- [x] **Self-healing behavior** - Automatically adapts to manual calls and HA restarts
- [x] **Transparent logging** - Full visibility into interval calculations

**Note**: Originally planned for v2.0.0, but accelerated to v1.11.0 based on user validation.

**Enhanced Mold Risk Assessment** ([#90](https://github.com/hiall-fyi/tado_ce/issues/90)):
- [x] **U-value estimation** - Calculate window surface temperature from outdoor temp and window type
- [x] **2-tier fallback strategy** - Automatic fallback: U-value estimation → room temperature
- [x] **Configurable window types** - Single/double/triple pane with standard U-values
- [x] **ASHRAE 160 compliance** - Surface temperature-based mold risk assessment

**Note**: Industry-standard approach using surface temperature instead of room average. External sensor support not implemented due to complexity and limited use case.

---

## v2.0.0 - Multiple Homes Enabled

Major release enabling full multi-home support.

### ✅ Completed for v2.0.0

**Multi-Home Infrastructure** (foundation for future multi-home support):
- [x] **Per-home data file naming** - `get_data_file(base_name, home_id)` in const.py
- [x] **Data loader home_id support** - `set_current_home_id()` / `get_current_home_id()` with fallback to legacy files
- [x] **Hub device identifier with home_id** - `tado_ce_hub_{home_id}` format

### 🔲 Remaining for v2.0.0

**API Monitoring Enhancements** ([#65](https://github.com/hiall-fyi/tado_ce/issues/65)):
- [ ] **Call History Sensor** - Separate sensor for Activity card visualization
- [ ] **Call Priority System** - Configurable weighting for different call types
- [ ] **Granular API Call Options** - Enable/disable optional call types in Advanced settings

**Multi-Home Support:**
- [ ] **Multi-home preference in config flow** - New users asked "Plan to add multiple homes?" to enable home_id prefix
- [ ] **Backwards-compatible entity unique_id** - Existing users keep current IDs, new users can opt-in to prefix
- [ ] **Allow multiple integration entries** - Each entry for a different home
- [ ] **Thread-safe home_id handling** - Replace global `_current_home_id` with per-entry context
- [ ] **Per-home async_api client** - Change from singleton to per-entry client instances
- [ ] **Per-home file paths in async_api** - Use `get_data_file(base_name, home_id)` instead of constants
- [ ] **Multi-home setup guide** - Documentation for users with multiple properties

**Setup & Polish:**
- [ ] **Auto-assign Areas** - Suggest HA Areas based on zone names during setup ([#14](https://github.com/hiall-fyi/tado_ce/issues/14))
- [ ] **Setup wizard improvements** - Streamlined flow with better error messages
- [x] **Delete tado_api.py** - File deprecated in v1.6.0, removed in v2.0.0
- [x] **Delete error_handler.py** - Only used by tado_api.py, removed in v2.0.0
- [x] **Cleanup orphan data files** - Legacy files migrated to per-home format (e.g., `zones.json` → `zones_{home_id}.json`) in v2.0.0

**Local API (Experimental):**
- [ ] **Local-first, cloud-fallback** - Use local API when available, fall back to cloud
- [ ] **Hybrid mode** - Configurable per-feature (e.g., local for reads, cloud for writes)
- [ ] **Community testing program** - Beta channel for local API testing

**Note**: Local API requires community help to test across different Tado hardware versions. See [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).

---

## Future Consideration

Features under consideration - need more community feedback or technical research.

**Heating Intelligence:**
- **Second Order Approximation for Preheat** - Use quadratic model (heating acceleration/deceleration) instead of linear rate for more accurate preheat timing. Accounts for: heating slowing as approaching target, thermal momentum of UFH, cooling rate before heating starts ([#78](https://github.com/hiall-fyi/tado_ce/issues/78) - @dimitri-frank, @thefern69)
- **Preheat Binary Sensor** - `binary_sensor.zone_preheat_now` that turns ON when it's time to start heating ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- **Turnkey Early Start Replacement** - Auto-trigger heating at recommended preheat time, stop when target reached or next schedule starts ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- **UFH Slow Response Mode** - Add buffer time for underfloor heating thermal lag ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- **Rate Trend Indicator** - Detect "acceleration" when heating is catching up, useful for UFH ([Discussion #33](https://github.com/hiall-fyi/tado_ce/discussions/33))

**Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)):
- **Indoor Air Quality (IAQ)** - Air quality score per zone (requires additional sensors)
- **Air Comfort** - Similar to Tado app's comfort visualization

**Other:**
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- Combi boiler mode - hide timers/schedules for on-demand hot water ([#15](https://github.com/hiall-fyi/tado_ce/issues/15))

---

## Migration Design

All migrations are cumulative - users can upgrade directly from any version (e.g., v1.6.0 → v2.0.0) and all intermediate migrations will be applied automatically. Each migration step is idempotent (safe to run multiple times).

Entity IDs remain stable throughout migration if entity `unique_id` is unchanged.
