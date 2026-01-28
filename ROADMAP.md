# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## v1.9.0 - Hub Device Migration + Smart Heating Analytics

Hub device identifier migration plus intelligent heating analytics.

**Multi-Home Migration:**
- [x] **Change hub device identifier** - From `tado_ce_hub` to `tado_ce_hub_{home_id}`
- [x] **Zone device migration** - From `tado_ce_zone_X` to `tado_ce_{home_id}_zone_X`
- [x] **Device registry migration** - Existing devices updated automatically
- [x] **Entity IDs stable** - No entity ID changes for existing users

**Smart Heating Analytics (Phase 1+2):**
- [x] **Heating Rate Sensor** - °C/hour when heating is active
- [x] **Cooling Rate Sensor** - °C/hour when heating is off (heat loss rate)
- [x] **Time to Target Sensor** - Estimated minutes to reach target temperature
- [x] **Comfort at Risk Binary Sensor** - Alert when target may be missed
- [x] **Weather Compensation** - Adjust predictions based on outdoor temperature
- [x] **2-Tier Data Loading** - Cache file + Recorder history for instant bootstrap

**Bug Fixes:**
- [x] **Fixed API reset detection for 100-call limit** - Dynamic threshold now works with both 5000 and 100 call limits ([#54](https://github.com/hiall-fyi/tado_ce/issues/54))
- [x] **AC turn-off debug logging** - Added detailed logging to diagnose intermittent restore-to-ON issue ([#44](https://github.com/hiall-fyi/tado_ce/issues/44))
- [x] **Refresh AC Capabilities now tracked in call history** - API calls from button now recorded ([#61](https://github.com/hiall-fyi/tado_ce/issues/61))
- [x] **Fixed temperature offset for multi-TRV rooms** - Offset now applied to ALL devices in a zone ([#66](https://github.com/hiall-fyi/tado_ce/issues/66))
- [x] **Fixed device sensor assignment** - Battery/Connection sensors now assigned to HEATING zones over HOT_WATER ([#56](https://github.com/hiall-fyi/tado_ce/issues/56))

**Data Sources:**
- Tier 1: Cache file (2h detailed data, survives restarts)
- Tier 2: Recorder history (24h, for bootstrap after cache expires)

---

## v1.10.0 - Smart Heating Insights

Leverage long-term statistics for predictive insights.

**Smart Heating Insights Sensor:**
- [ ] **Historical Temperature Comparison** - Compare current temp vs 7-day same-time average
- [ ] **Rate Anomaly Detection** - Alert when heating rate deviates significantly from historical
- [ ] **Preheat Advisor** - Suggest optimal preheat time based on historical warm-up patterns

**Example Insights:**
```
"Past 7 days at this time: avg 18.5°C, today: 17.2°C (-1.3°C)"
"Heating rate today: 1.2°C/h vs historical 2.5°C/h (-52% - possible issue?)"
"Suggested preheat time: 06:15 (typical warm-up: 45 min)"
```

---

## v2.0.0 - Multiple Homes Enabled + Smart Boost

Major release enabling full multi-home support plus smart boost feature.

**Multi-Home Support:**
- [ ] **Allow multiple integration entries** - Each entry for a different home
- [ ] **Thread-safe home_id handling** - Add lock for `_current_home_id` in data_loader.py (required for concurrent multi-home)
- [ ] **Multi-home setup guide** - Documentation for users with multiple properties

**Smart Boost (Phase 4):**
- [ ] **Smart Boost Button** - One-tap boost with intelligent duration
- [ ] **Duration Calculation** - `(target - current) / heating_rate`
- [ ] **Reasonable Caps** - Max 3 hours to prevent runaway heating

**API Monitoring Enhancements** ([#65](https://github.com/hiall-fyi/tado_ce/issues/65)):
- [ ] **Call History Sensor** - Separate sensor for Activity card visualization
- [ ] **Call Priority System** - Configurable weighting for different call types
- [ ] **Granular API Call Options** - Enable/disable optional call types in Advanced settings

**API Call Types - What's Configurable:**

| Code | Type | Configurable? | Notes |
|------|------|---------------|-------|
| 1 | zoneStates | ❌ Required | Core data - temperature, humidity, heating status |
| 2 | weather | ✅ Already available | Weather sync option |
| 3 | zones | ❌ Required | Zone configuration, needed at startup |
| 4 | mobileDevices | ✅ Already available | Mobile devices sync option |
| 5 | overlay | ❌ Required | Manual overrides, needed for heating control |
| 6 | presenceLock | ✅ Will add | Home/Away lock status |
| 7 | homeState | ✅ Already available | Home state sync option |
| 8 | capabilities | ✅ Auto-cached | AC capabilities, fetched once and cached |

**Setup & Polish:**
- [ ] **Auto-assign Areas** - Suggest HA Areas based on zone names during setup ([#14](https://github.com/hiall-fyi/tado_ce/issues/14))
- [ ] **Setup wizard improvements** - Streamlined flow with better error messages
- [ ] **Delete tado_api.py** - File deprecated in v1.6.0, now fully removed
- [ ] **Delete error_handler.py** - Only used by tado_api.py, remove together

**Local API (Experimental):**
- [ ] **Local-first, cloud-fallback** - Use local API when available, fall back to cloud
- [ ] **Hybrid mode** - Configurable per-feature (e.g., local for reads, cloud for writes)
- [ ] **Community testing program** - Beta channel for local API testing

**Note**: Local API requires community help to test across different Tado hardware versions. See [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).

---

## Considering (Need More Feedback)

- Rate Trend indicator for UFH - detect "acceleration" when heating is catching up ([#33](https://github.com/hiall-fyi/tado_ce/discussions/33))
- Air Comfort sensors (humidity comfort level)
- Boost button entity
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- Combi boiler mode - hide timers/schedules for on-demand hot water ([#15](https://github.com/hiall-fyi/tado_ce/issues/15))

---

## Backlog (Future Consideration)

**Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)):
- [ ] **Mold Risk Indicator** - Calculate mold risk from temp + humidity
- [ ] **Indoor Air Quality (IAQ)** - Air quality score per zone
- [ ] **Air Comfort** - Similar to Tado app's comfort visualization

---

## Migration Design

All migrations are cumulative - users can upgrade directly from any version (e.g., v1.6.0 → v2.0.0) and all intermediate migrations will be applied automatically. Each migration step is idempotent (safe to run multiple times).

Entity IDs remain stable throughout migration if entity `unique_id` is unchanged.
