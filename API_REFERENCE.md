# Tado CE - API Reference

This document explains how Tado CE interacts with the Tado API, including call types, what data each call fetches, and how to optimize your API usage.

---

## API Call Types

Tado CE tracks all API calls with a code system for easy identification:

| Code | Type | Description | Configurable |
|------|------|-------------|--------------|
| 1 | zoneStates | Current state of all zones (temperature, humidity, heating status, overlay status) | No (required) |
| 2 | weather | Outdoor weather data from Tado (temperature, solar intensity, weather state) | Yes |
| 3 | zones | Zone configuration (names, types, devices) | No (required) |
| 4 | mobileDevices | Geofencing device locations | Yes |
| 5 | overlay | Manual overrides (set/delete temperature or mode changes) | N/A (action-triggered) |
| 6 | presenceLock | Home/Away mode lock status | Planned |
| 7 | homeState | Home presence state (home/away) | Yes |
| 8 | capabilities | AC zone capabilities (modes, fan levels, swing options) | Auto-cached |

### Required Calls (Cannot Be Disabled)

| Code | Type | Why Required |
|------|------|--------------|
| 1 | zoneStates | Core data - temperature, humidity, heating status for all zones |
| 3 | zones | Zone configuration, needed at startup to identify your devices |

Disabling these would break basic functionality like temperature readings and heating control.

### Configurable Calls

These can be toggled in **Settings > Devices & Services > Tado CE > Configure**:

| Code | Type | Option | API Savings |
|------|------|--------|-------------|
| 2 | weather | Enable Weather Sensors | 1 call per sync |
| 4 | mobileDevices | Enable Mobile Device Tracking | 1 call per full sync |
| 7 | homeState | Enable Home State Sync | 1 call per quick sync |

### Auto-Cached Calls

| Code | Type | Behavior |
|------|------|----------|
| 8 | capabilities | Fetched once per AC zone, cached locally. Only re-fetched via "Refresh AC Capabilities" button |

### Action-Triggered Calls

| Code | Type | When Triggered |
|------|------|----------------|
| 5 | overlay | When you change temperature/mode via Tado CE services |

These are not polling calls - they only happen when you take an action.

---

## What is "Overlay"?

An **overlay** is Tado's term for a manual override. When you change the temperature or mode away from the schedule, Tado creates an "overlay" on top of the schedule.

### Overlay Types

| Type | Behavior |
|------|----------|
| MANUAL | Stays until you cancel it |
| TIMER | Reverts after X minutes |
| TADO_MODE | Reverts at next schedule change (Next Block) |

### How Overlay Relates to API Calls

- **Code 5** tracks **write** operations only (`set_zone_overlay`, `delete_zone_overlay`)
- The overlay **status** (whether a zone has a manual override) comes from **Code 1** (zoneStates), not a separate call
- If you use HomeKit or another system for climate control, you won't trigger Code 5 calls through Tado CE

---

## Sync Types

Tado CE uses two sync types to balance data freshness with API efficiency:

### Quick Sync

Runs frequently (based on your polling interval). Fetches:
- zoneStates (Code 1) - always
- homeState (Code 7) - if enabled

**Typical calls per quick sync:** 1-2

### Full Sync

Runs every 6 hours. Fetches everything from quick sync plus:
- zones (Code 3)
- weather (Code 2) - if enabled
- mobileDevices (Code 4) - if enabled

**Typical calls per full sync:** 2-5 (depending on options)

---

## Call History

All API calls are recorded in the `sensor.tado_ce_api_usage` entity attributes:

```yaml
call_history:
  - "2026-01-28 10:30:15 - Code 1 (zoneStates)"
  - "2026-01-28 10:30:16 - Code 7 (homeState)"
  - "2026-01-28 10:00:15 - Code 1 (zoneStates)"
```

### Viewing Call History

1. Go to **Developer Tools > States**
2. Search for `sensor.tado_ce_api_usage`
3. Expand **Attributes** to see `call_history`

### History Retention

Configure via **Options > API History Retention** (default: 14 days, 0 = forever)

---

## Optimizing API Usage

### For HomeKit Users

If you control climate via HomeKit:
- Disable **Weather Sensors** (unless using Smart Comfort)
- Disable **Mobile Device Tracking** (unless using device trackers)
- Disable **Home State Sync** (unless using Tado geofencing)

You won't trigger Code 5 (overlay) calls since climate changes go through HomeKit, not Tado CE.

### For 100 Calls/Day Limit

With all optional syncs disabled:
- Quick sync: 1 call (zoneStates only)
- Full sync: 2 calls (zoneStates + zones)

This gives you maximum headroom for manual actions and automations.

### For Auto-Assist Users (20,000 calls/day)

You can enable all features without concern:
- Weather Sensors
- Mobile Device Tracking
- Home State Sync
- Smart Comfort Analytics
- Schedule Calendar

Even with 5-minute polling, you'll use ~500 calls/day.

---

## Rate Limit Headers

Tado CE reads rate limit information from API response headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Your daily limit (100/5000/20000) |
| `X-RateLimit-Remaining` | Calls remaining today |
| `X-RateLimit-Reset` | Reset time (note: often inaccurate) |

### Reset Time Detection

Tado CE uses multiple strategies to detect your actual reset time:

1. **Detected Reset** - When remaining increases significantly, record the time
2. **HA History** - Check sensor history for usage drops
3. **Extrapolation** - Calculate from usage rate and call history
4. **First Call Mode** - Fallback using historical first-call times

The API's `X-RateLimit-Reset` header often points to midnight UTC, which is incorrect. Tado CE calculates the actual reset time based on observed behavior.

---

## Troubleshooting

### High API Usage

1. Check **call_history** attribute for unexpected calls
2. Disable optional syncs you don't need
3. Increase polling intervals via custom day/night settings

### Missing Data

If certain data isn't updating:
1. Check if the relevant sync option is enabled
2. Check logs for API errors
3. Verify you haven't hit your rate limit

### Call History Not Recording

1. Ensure **API History Retention** > 0
2. Check logs for file I/O errors
3. Verify `/config/.storage/tado_ce/` directory exists

---

## Data Storage

Tado CE stores API-related data in `/config/.storage/tado_ce/`:

| File | Contents |
|------|----------|
| `ratelimit_{home_id}.json` | Current rate limit status, reset time |
| `api_call_history_{home_id}.json` | Historical API calls for tracking |
| `ac_capabilities_{home_id}.json` | Cached AC zone capabilities |
| `schedules_{home_id}.json` | Cached heating schedules |

These files persist across restarts and upgrades.

---

## Related Documentation

- [README.md](README.md) - Main documentation
- [ENTITIES.md](ENTITIES.md) - Complete entity reference
- [ROADMAP.md](ROADMAP.md) - Planned features

---

**Version**: 1.9.0  
**Last Updated**: 2026-01-31
