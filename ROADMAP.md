# Roadmap

Planned features and improvements for Tado CE.

For completed features, see [CHANGELOG.md](CHANGELOG.md).

---

## Up Next

**On API-call optimisation as a through-line.** A design principle that runs through the whole v4.x line: spend as few of your daily Tado API calls as possible without losing freshness. The pieces already shipped (the 5-minute polling floor, per-type refresh floors you can tune, deferring to HomeKit's dial when local control is connected, and taking the offset refresh off its all-at-once burst) are in the changelog. The next step on this front is the API resilience pass under **Later** below, which hardens how the integration degrades when any one Tado endpoint is unavailable. The goal stays the same: your quota goes further and local control stays solid.

All AC writes (target temperature, HVAC mode, swing, fan, timers) currently go through the cloud. See the AC entry below for why HomeKit local control on Smart AC Control V3+ isn't on the active roadmap.

## Later — feature additions, no fixed release

These were first pencilled in for the cycle after v4.1.0. They're still wanted and well-specified, and the foundation (persistence, polling rework, HomeKit reliability) is in place, but none is built yet and none is tied to a particular release. They'll land when a cycle has room for them.

- **Auto-Assist detection** — a hub diagnostic sensor that tells you whether your home has Tado's paid Auto-Assist enabled, so it's clear which features come from Tado's subscription and which Tado CE predicts on its own. Designed to cost no extra API calls where possible.
- **Air Comfort** ([#64](https://github.com/hiall-fyi/tado_ce/issues/64)) — a per-zone Air Freshness reading worked out from window-opening history and AC activity, with no extra API calls. Optional Outdoor Air Quality from any external sensor you choose via the Options Flow, the same way external temperature and humidity already work.
- **External boiler flow temperature sensor** ([#254](https://github.com/hiall-fyi/tado_ce/issues/254) - @apilone) — read your boiler's flow temperature from any HA sensor for Weather Compensation, so OpenTherm owners on myVaillant / ebusd / OTGW don't need Tado's own bridge for it. Ships alongside the Air Comfort external-sensor plumbing since both use the same Options Flow pattern.
- **API resilience pass** — a review of every Tado endpoint the integration relies on, hardening how it degrades when any one of them is unavailable so a single Tado-side hiccup doesn't take entities down with it. Also settles a long-standing request: per-zone hysteresis / Acceptance Range and Minimum On/Off Time can't be exposed as entities because Tado serves them from a newer API the integration doesn't reach. They become a documentation note rather than a sensor.

## v5.0.0 — Legacy cleanup

A spring-clean release that drops backward-compat code accumulated through the v3.x and v4.x cycles. The cleanup is laser-focused on dead surface area, not behaviour change.

**Minimum supported upgrade path: v4.x.x.** Installs running v3.x or earlier should upgrade to v4.x first (any v4 release is fine), then to v5.0.0. v5.0.0 will not auto-migrate v3.x option keys, entity unique_ids, or storage layouts; the migration code that handled those upgrades will be removed. The v3 to v4 migration path stays open through every v4.x release, so there is no rush to upgrade in one jump.

Planned removals:

- **Legacy option-key migration** — a couple of settings renamed across the v3.x / v4.x cycles are still read through a backward-compat fallback. v5.0.0 migrates them forward once at startup and drops the fallback.
- **Entity-naming polish** — a doubled calendar slug and a couple of internal naming inconsistencies get a clean baseline. These change entity IDs, so they ride the breaking-change boundary with a migration step rather than stranding your existing entities.
- **Hand-pinned entity IDs retired** — a couple of entities (the heating-circuit select, the Identify button) set their `entity_id` by hand to sidestep a Home Assistant 2026.6 quirk that doubles the slug when a zone device shares its area name (`select.lounge_lounge_heating_circuit`). Once Home Assistant fixes the doubling upstream, those hand-set IDs are dead weight that stops the naming following HA's own default; v5.0.0 drops them so entity naming is fully HA-native again, with a migration step since removing a pin changes the ID. Gated on the upstream fix actually landing, so it stays here until then.
- **Boiler sensor entity IDs finish their rename** — v4.1.4 renamed the boiler diagnostic sensors from "Bridge …" to "Boiler …" for their display names, which was safe and changed nothing you'd script against. The underlying entity IDs still carry the old `bridge_` wording, though. Aligning those to `boiler_` changes the entity ID, so it waits for this breaking-change release with a migration step rather than orphaning the entities now. Until then the display name and the entity ID read slightly differently, which is cosmetic.
- **Hot-water tank capability reads its own store** — the v4.1.4 fix that lets temperature-controlled hot-water tanks switch to Heat reuses the same capability cache the AC zones already use, so it shipped without a new storage layer. It works fine as-is; the tidy-up is renaming that shared store and its helper so the name reflects that it now covers hot water too. Because the store is saved to disk, renaming it needs a one-time migration, which is why it rides this release rather than a patch.
- **Climate AC + Heating share a base class** — the two climate entity files repeat nearly the same setup code; sharing a base saves a good chunk and moves the write path to async. Gated on a thorough test pass first, since the two paths are deliberately cloned today. This also unblocks a per-zone override-duration read and a tighter error guard that were parked in v4.1.0-beta.3.
- **AC swing legacy input retired** — older automations can still call the pre-v4.1 unified `swing_mode` values via a compatibility shim (which logs a deprecation warning). It's removed at v5.0.0; update those automations to the per-axis swing services before then.
- **Dead-code and translation-key cleanup** — v3.x migration branches that are unreachable once v5's minimum-upgrade-from-v4.x rule holds, plus a handful of inconsistently-named translation keys, get swept together at the breaking-change boundary.
- **Service-call consistency** — three older services use a plain entity field instead of the entity picker, and timer vs open-window durations read in different units. Aligned here with the old form kept working through a deprecation window, since changing them affects how you call the service from automations.

No timeline yet. Detailed findings are tracked internally.

## Future Consideration

### AC

- **Smart AC Control V3+ standalone HomeKit pairing** ([Discussion #271](https://github.com/hiall-fyi/tado_ce/discussions/271) - @MacrosorcH) — Smart AC Control units are autonomous WiFi devices, each with its own 8-digit HomeKit code, paired separately from the Internet Bridge. Tado CE only handles the bridge pairing today, so AC zones use the cloud path for every operation regardless of HomeKit configuration. Adding standalone-unit support means a separate pairing flow per AC unit, multi-pairing controller management, and HAP HeaterCooler service handling on top of the existing Thermostat path (different characteristics, different state machine). Not actively planned — I don't have Smart AC Control hardware to develop or test against, and this class of feature can't be reliably built blind.
- **AC cloud-path fixes still land from field reports.** The hardware gap above blocks *local* HomeKit control, but the cloud path AC uses today is maintained, and a user with the unit can drive a fix without me owning one. In v4.1.0, [#305](https://github.com/hiall-fyi/tado_ce/issues/305) (@stefanzweig1979) was exactly that: fan changes never reached older units because the integration sent the fan setting under the wrong field name (the plural `fanSpeeds` from the capability list, where the write payload wants the singular `fanSpeed`). A debug log plus a captured Tado web-app request confirmed the correct field, and the fix shipped. So a cloud-side AC issue with a clear repro is actionable; only the standalone local-control feature is hardware-blocked.

### Weather Compensation

- **Exponential Heating Curve** ([#187](https://github.com/hiall-fyi/tado_ce/issues/187) - @driagi) — Non-linear heating curve for weather compensation, using a building thermal sensitivity coefficient (`k` factor). Better models real-world heat loss in well-insulated vs poorly-insulated buildings compared to the current linear approach. Would sit alongside the existing linear presets as an "Expert" option. Deferred for real-world validation during the next heating season.

### Infrastructure

- **Local Only Mode** — A toggle that stops all cloud polling after initial setup, running purely off HomeKit bridge data. Technically feasible — the coordinator already skips cloud calls when HomeKit provides live data. Tradeoff: cloud-only data (schedules, battery, heating power, geofencing) would go stale. Could include a daily cloud check for diagnostics.
- **Bridge wiring-state poll cadence** ([#289](https://github.com/hiall-fyi/tado_ce/issues/289) - @driagi) — the boiler wiring sensor reads the bridge every 60 seconds on its own loop. These calls hit the bridge directly with its local auth key, so they don't count against your daily Tado cloud quota, but a minute-by-minute read of an almost-static value is heavier on the bridge than it needs to be. The wiring state only changes when you rewire the boiler, so a much slower cadence (or an event-driven refresh) covers it. Surfaced while diagnosing #289's call volume.
- **Smart polling pause/resume rework** — the polling cadence has grown a handful of separate decisions (when to slow down on low quota, when to pause entirely, when to resume after the quota resets) that were each added on their own and never designed as one piece. The plan is to pull them into a single clear state machine so the edges line up. Held back until [#278](https://github.com/hiall-fyi/tado_ce/issues/278) (@Newreader) has a reproducible case: that report (frost-protection zones reverting after a quota window) is the one signal that would tell us whether the pause/resume path is actually where the bug lives, and so far it hasn't reproduced on a setup I can observe. The tier-aware quota reserve that the rework was originally going to fix already landed in v4.0.2, so this is now about the state machine's clarity, not a missing feature.
- **#278 frost-protection revert** ([#278](https://github.com/hiall-fyi/tado_ce/issues/278) - @Newreader) — zones on frost protection reverted to a heating setpoint after several hours, with no automation firing. The leading theory (Tado's server clearing the overlay during a low-quota window) hasn't reproduced on a controlled setup, so the root cause is still open. Tracking it here so the next person who hits it has the prior investigation to build on rather than starting cold.
- **Smart Valve and Offset Sync read different temperatures** — the two compensation modes don't read the room the same way. On a zone with a HomeKit bridge connected, Smart Valve Control reads the live HomeKit-merged temperature, while Offset Sync reads the cloud reading. Only one mode runs per zone, so they never fight inside a single zone, but two zones set up the same way can compensate off slightly different numbers depending on which mode they're in. It's a small difference in practice and there's no bug today, but the inconsistency is worth tidying so both modes share one source. Folds in naturally with the temperature-source work the integration already exposes per zone.
  - **Pick the source direction deliberately, it's not a free change.** Moving Offset Sync onto the live HomeKit reading only helps zones that have a bridge connected, so it trades the current mode-to-mode inconsistency for a new connected-vs-cloud-only one. The cleaner direction is usually the other way (both modes read the cloud reading), but that gives up Smart Valve's real-time response. Decide this on its own before building, not as a rider on another change.
  - **It ties into the overnight offset-swing fix.** That fix waits for the cloud reading to catch up to the last write before correcting again, keyed on the cloud poll. Offset Sync reads the cloud reading today, so that timing lines up. If Offset Sync is ever switched to the live HomeKit reading, the wait has to follow the HomeKit reading instead, or it'll hold off corrections longer than it should. Whoever does this must re-check the swing fix's timing in the same pass.

### Long-Term Exploration

- **Fully Local Control** ([Discussion #29](https://github.com/hiall-fyi/tado_ce/discussions/29)) — Control via the 868MHz protocol between Bridge and TRVs, bypassing both cloud and HomeKit. Requires specialized hardware and community help.
