# Roadmap

Feature requests and planned improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## v2.0.0 - Multiple Homes Enabled + Smart Boost + ML Predictions

Major release enabling full multi-home support, smart boost feature, and ML-based predictions.

**Regression-Based Predictive Models** (Self-Learning):
- [ ] **Linear Regression Framework** - NumPy OLS implementation for per-zone predictions
- [ ] **Heating Rate Prediction** - ML-based heating rate using delta_temp, valve%, power, time features
- [ ] **Comfort Level Estimation** - Multi-factor comfort score (temp, humidity, rate)
- [ ] **Time to Target Prediction** - Accurate ETA based on learned heating patterns
- [ ] **Heating Intensity Advisor** - Suggest target temp for desired valve % (indirect valve control)
- [ ] **Cold Start Handling** - Graceful fallback during learning period (1-2 weeks)
- [ ] **Model Persistence** - Training data survives HA restarts, 30-day rolling window
- [ ] **Feature Importance** - Expose which factors affect predictions most

**Multi-Home Support:**
- [ ] **Allow multiple integration entries** - Each entry for a different home
- [ ] **Thread-safe home_id handling** - Add lock for `_current_home_id` in data_loader.py (required for concurrent multi-home)
- [ ] **Multi-home setup guide** - Documentation for users with multiple properties

**Smart Boost (Phase 4):**
- [ ] **Smart Boost Button** - One-tap boost with intelligent duration
- [ ] **Duration Calculation** - `(target - current) / heating_rate`
- [ ] **Reasonable Caps** - Max 3 h to prevent runaway heating

**API Monitoring Enhancements** ([#65](https://github.com/hiall-fyi/tado_ce/issues/65)):
- [ ] **Call History Sensor** - Separate sensor for Activity card visualization
- [ ] **Call Priority System** - Configurable weighting for different call types
- [ ] **Granular API Call Options** - Enable/disable optional call types in Advanced settings

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
- **Preheat Binary Sensor** - `binary_sensor.zone_preheat_now` that turns ON when it's time to start heating ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- **Turnkey Early Start Replacement** - Auto-trigger heating at recommended preheat time, stop when target reached or next schedule starts ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- **UFH Slow Response Mode** - Add buffer time for underfloor heating thermal lag ([Discussion #72](https://github.com/hiall-fyi/tado_ce/discussions/72) - @thefern69)
- Rate Trend indicator for UFH - detect "acceleration" when heating is catching up ([#33](https://github.com/hiall-fyi/tado_ce/discussions/33))
- Air Comfort sensors (humidity comfort level)
- Boost button entity
- Apply for HACS default repository inclusion
- Max Flow Temperature control (requires OpenTherm, [#15](https://github.com/hiall-fyi/tado_ce/issues/15))
- Combi boiler mode - hide timers/schedules for on-demand hot water ([#15](https://github.com/hiall-fyi/tado_ce/issues/15))

---

## Backlog (Future Consideration)

**Environment Sensors** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)):
- [ ] **Indoor Air Quality (IAQ)** - Air quality score per zone (requires additional sensors)
- [ ] **Air Comfort** - Similar to Tado app's comfort visualization

---

## Migration Design

All migrations are cumulative - users can upgrade directly from any version (e.g., v1.6.0 → v2.0.0) and all intermediate migrations will be applied automatically. Each migration step is idempotent (safe to run multiple times).

Entity IDs remain stable throughout migration if entity `unique_id` is unchanged.
