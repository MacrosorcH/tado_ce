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
- [ ] **Multi-home setup guide** - Documentation for users with multiple properties

**Smart Boost (Phase 4):**
- [ ] **Smart Boost Button** - One-tap boost with intelligent duration
- [ ] **Duration Calculation** - `(target - current) / heating_rate`
- [ ] **Reasonable Caps** - Max 3 hours to prevent runaway heating

**Setup & Polish:**
- [ ] **Auto-assign Areas** - Suggest HA Areas based on zone names during setup ([#14](https://github.com/hiall-fyi/tado_ce/issues/14))
- [ ] **Setup wizard improvements** - Streamlined flow with better error messages
- [ ] **Delete tado_api.py** - File deprecated in v1.6.0, now fully removed

**Local API (Experimental):**
- [ ] **Local-first, cloud-fallback** - Use local API when available, fall back to cloud
- [ ] **Hybrid mode** - Configurable per-feature (e.g., local for reads, cloud for writes)
- [ ] **Community testing program** - Beta channel for local API testing

**Note**: Local API requires community help to test across different Tado hardware versions. See [Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29).

---

## Considering (Need More Feedback)

- Air Comfort sensors (humidity comfort level)
- Boost button entity
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- Combi boiler mode - hide timers/schedules for on-demand hot water ([#15](https://github.com/hiall-fyi/tado_ce/issues/15))

---

## Migration Design

All migrations are cumulative - users can upgrade directly from any version (e.g., v1.6.0 → v2.0.0) and all intermediate migrations will be applied automatically. Each migration step is idempotent (safe to run multiple times).

Entity IDs remain stable throughout migration if entity `unique_id` is unchanged.
