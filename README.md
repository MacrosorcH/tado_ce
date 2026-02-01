# Tado CE - Custom Integration for Home Assistant

<div align="center">

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.1.3-blue?style=for-the-badge&logo=home-assistant) ![Tado](https://img.shields.io/badge/Tado-V3%2FV3%2B-orange?style=for-the-badge) ![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-1.9.2-purple?style=for-the-badge) ![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge) ![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge) ![Tests](https://img.shields.io/badge/Tests-494%20Passing-success?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub forks](https://img.shields.io/github/forks/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/tado_ce?style=for-the-badge&logo=github) ![GitHub last commit](https://img.shields.io/github/last-commit/hiall-fyi/tado_ce?style=for-the-badge&logo=github)

**A comprehensive Tado integration with smart API management, comfort analytics, and environment monitoring.**

[Quick Start](#-quick-start) • [Features](#-features) • [Configuration](#-configuration-options) • [Troubleshooting](#-troubleshooting) • [Discussions](https://github.com/hiall-fyi/tado_ce/discussions)

</div>

---

## Why Tado CE?

Tado CE was created in response to Tado's 2025 API rate limits (100-20,000 calls/day depending on plan). The official Home Assistant integration doesn't show your actual API usage, leaving users unaware until they get blocked.

What started as an API management solution has evolved into a **comprehensive smart climate integration** with real-time rate limit tracking, smart day/night polling, comfort analytics, environment monitoring, and enhanced controls for heating, AC, and hot water.

---

## Quick Start

**Prerequisites:** Home Assistant 2024.1+ and a Tado account with V2/V3/V3+ devices.

### 1. Install via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hiall-fyi&repository=tado_ce&category=integration)

1. Click the button above (or add `https://github.com/hiall-fyi/tado_ce` as a custom repository in HACS)
2. Install "Tado CE" from HACS
3. Restart Home Assistant

<details>
<summary>Manual Installation</summary>

```bash
cp -r tado_ce /config/custom_components/
```
</details>

### 2. Add Integration & Authenticate

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **Tado CE** and click **Submit**
3. Visit `https://login.tado.com/device` and enter the code shown
4. Authorize in your browser, then click **Submit**
5. If you have multiple homes, select which one to use

That's it! No SSH required.

### 3. Verify Success

Check **Settings > System > Logs** for:

```
Tado CE: Integration loading...
Tado CE: Polling interval set to 30m (day)
Tado CE full sync SUCCESS
Tado CE: Integration loaded successfully
```

### 4. Configure Options

Click the **gear icon** on the integration card to customize features, polling schedule, and Smart Comfort settings.

---

## Features

Full climate, AC, and hot water control with timer support, geofencing, presence detection, weather data, and more.

**Tado CE Exclusive:**

| Category | Feature | Description |
|----------|---------|-------------|
| **API Management** | Real API Rate Limit | Actual usage from Tado API headers, not estimates |
| | Reset Time Detection | Automatically detects when your rate limit resets |
| | Dynamic Limit Detection | Auto-detects your limit (100/5000/20000) |
| | API Call History | Track all API calls with configurable retention |
| | Test Mode | Simulate 100 call limit for testing |
| **Smart Polling** | Day/Night Polling | More frequent during day, less at night to save API calls |
| | Customizable Intervals | Configure day/night hours and custom polling intervals |
| | Optional Sensors | Toggle Weather/Mobile/Home State on/off to save API calls |
| **Smart Comfort** | Analytics | Heating/cooling rates, time-to-target, efficiency (opt-in) |
| | Preheat Advisor | Suggest optimal preheat start time based on historical patterns |
| | Schedule Sensors | Next schedule time and temperature per zone |
| **Environment** | Mold Risk | Per-zone mold risk indicator (always enabled) |
| | Comfort Level | Adaptive comfort sensor using ASHRAE 55 model (always enabled) |
| **Enhanced Controls** | Immediate Refresh | Dashboard updates immediately after user actions |
| | Enhanced Hot Water | AUTO/HEAT/OFF modes with timer presets (30/60/90 min) |
| | Schedule Calendar | View heating schedules as calendar events (opt-in) |
| | Boiler Flow Temp | Auto-detected sensor for OpenTherm systems |
| **Architecture** | Zone-Based Devices | Each zone as separate device with cleaner entity names |
| | Multi-Home Selection | Select which home to configure during setup |
| | Full Async | Non-blocking API calls for better responsiveness |

---

## Configuration Options

Access via **Settings > Devices & Services > Tado CE > gear icon**.

<details>
<summary><strong>Features</strong></summary>

| Option | Default | Description |
|--------|---------|-------------|
| Enable Weather Sensors | Off | Outside temp, solar intensity, weather state. Saves 1 API call/sync when disabled |
| Enable Mobile Device Tracking | Off | Device tracker entities. Saves 1 API call/full sync when disabled |
| Enable Home State Sync | Off | Home/away presence. Required for Away Mode switch and presets |
| Enable Temperature Offset Attribute | Off | Adds `offset_celsius` to climate entities (1 API call/device every 6h) |
| Enable Schedule Calendar | Off | Calendar entities showing heating schedules |
| Enable Smart Comfort Analytics | Off | Heating rate, cooling rate, time-to-target, efficiency, preheat advisor, schedule sensors |
| API History Retention | 14 d | Days to keep API call history (0 = forever) |

</details>

<details>
<summary><strong>Polling Schedule</strong></summary>

| Option | Default | Description |
|--------|---------|-------------|
| Day Start Hour | 7 | When "day" period starts (0-23) |
| Night Start Hour | 23 | When "night" period starts (0-23). Set Day = Night for uniform 24/7 polling |
| Custom Day Interval | Empty | Override smart polling with fixed interval (1-1440 min) |
| Custom Night Interval | Empty | Override smart polling with fixed interval (1-1440 min) |
| Refresh Debounce Delay | 15 s | Delay before refreshing after user actions (1-60 s) |
| Sync Mobile Devices Frequently | Off | Mobile devices sync every quick sync instead of only during full sync (every 6 h) |

When custom intervals are not set, Tado CE uses smart polling that automatically adjusts based on your API quota.

</details>

<details>
<summary><strong>Smart Comfort Settings</strong></summary>

| Option | Default | Description |
|--------|---------|-------------|
| Outdoor Temperature Entity | Empty | External weather sensor for more accurate outdoor temp |
| Smart Comfort Mode | None | Temperature compensation: None / Light (±0.5°C) / Moderate (±1.0°C) / Aggressive (±2.0°C) |
| Use Feels Like Temperature | Off | Use "feels like" instead of actual temperature for compensation |
| Smart Comfort History Days | 7 | Days of history for heating rate calculations (1-30) |

</details>

<details>
<summary><strong>Experimental</strong></summary>

| Option | Default | Description |
|--------|---------|-------------|
| Hot Water Timer Duration | 60 min | Duration when HEAT mode is activated (5-1440 min) |
| Enable Test Mode | Off | Simulates 100 API call limit for testing |

</details>

**Note**: Changes take effect immediately without restart.

---

## Entities

Quick overview of entities created by Tado CE:

- **Hub**: API usage/reset sensors, weather sensors, away mode switch, resume all schedules button
- **Per Zone**: Climate control, temperature/humidity, heating power, mode, battery, connection
- **Environment**: Mold risk, comfort level (always enabled)
- **Smart Comfort**: Heating/cooling rates, time-to-target, efficiency, preheat advisor, schedule sensors (opt-in)
- **Hot Water**: Water heater with AUTO/HEAT/OFF modes, timer buttons (30/60/90 min)
- **Switches**: Child lock, early start per zone

---

## Services

| Service | Description |
|---------|-------------|
| `set_climate_timer` | Set heating/cooling with timer or until next schedule |
| `set_water_heater_timer` | Turn on hot water with timer |
| `resume_schedule` | Delete overlay, return to schedule |
| `set_climate_temperature_offset` | Calibrate device temperature (-10 to +10°C) |
| `get_temperature_offset` | Fetch current offset (Tado CE exclusive) |
| `identify_device` | Flash device LED |
| `set_away_configuration` | Configure away temperature |
| `add_meter_reading` | Add Energy IQ reading (supports historical dates) |

All services available in **Developer Tools > Services** with full parameter documentation.

---

## Smart Polling

The integration automatically adjusts polling frequency based on your API limit and time of day.

| API Limit | Day (7am-11pm) | Night (11pm-7am) | Est. Calls/Day |
|-----------|----------------|------------------|----------------|
| 100 | 30 min | 2 h | ~80 calls |
| 1,000 | 15 min | 1 h | ~160 calls |
| 5,000 | 10 min | 30 min | ~240 calls |
| 20,000 | 5 min | 15 min | ~480 calls |

<details>
<summary>100 Calls/Day Breakdown</summary>

| Time Period | Duration | Interval | Syncs | Calls | Total |
|-------------|----------|----------|-------|-------|-------|
| Day (7am-11pm) | 16h | 30 min | 32 | 2 | 64 |
| Night (11pm-7am) | 8h | 2h | 4 | 2 | 8 |
| Full sync | 24h | 6h | 4 | 2 | 8 |
| **Total** | | | | | **80** |

This leaves a 20% buffer for manual syncs or service calls.

</details>

---

## Supported Devices

| Device | Type | Support |
|--------|------|---------|
| Smart Thermostat V2 | HEATING | Full (community verified) |
| Smart Thermostat V3/V3+ | HEATING | Full |
| Smart Radiator Thermostat (SRT/VA02) | HEATING | Full |
| Smart AC Control V3/V3+ | AIR_CONDITIONING | Full |
| Wireless Temperature Sensor | HEATING | Full |
| Internet Bridge V3 | Infrastructure | N/A |
| **Tado X Series** | Matter/Thread | Not Supported |

Tado X devices use Matter over Thread - use the [Home Assistant Matter integration](https://community.home-assistant.io/t/using-tado-smart-thermostat-x-through-matter/736576) instead.

---

## Limitations

| Limitation | Description |
|------------|-------------|
| Cloud-Only | All control goes through Tado's cloud servers |
| No GPS | Device trackers only show home/not_home status |
| Rotating Tokens | If token expires, re-authentication required |
| No Schedule Management | Use Tado app for schedule changes |
| No Historical Data | Would consume too many API calls |

---

## Troubleshooting

<details>
<summary><strong>⚠️ Options not saving (v1.9.0+)</strong></summary>

If clicking "Submit" in Configure doesn't show "Successfully saved", the **Outdoor Temperature Entity** field may be empty.

**This is a Home Assistant Core limitation** ([Issue #154795](https://github.com/home-assistant/core/issues/154795)) - EntitySelector cannot handle empty values.

**Workaround:**
1. Go to **Settings → Devices & Services → Tado CE → Configure**
2. Expand **Smart Comfort Settings**
3. Set **Outdoor Temperature Entity** to any weather entity (e.g., `weather.home`)
4. Click **Submit**

If you don't want weather compensation, set "Smart Comfort Mode" to "None".

</details>

<details>
<summary><strong>Token refresh failed / Re-authentication required</strong></summary>

1. Go to **Settings > Devices & Services > Tado CE**
2. Click **Configure** or look for re-authentication prompt
3. Follow the device authorization flow (link + code)

</details>

<details>
<summary><strong>No device tracker entities</strong></summary>

Device trackers only appear for mobile devices with geo tracking enabled in the Tado app.

</details>

<details>
<summary><strong>Enable debug logging</strong></summary>

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.tado_ce: debug
```

Restart Home Assistant and check **Settings > System > Logs**.

</details>

For other issues, check logs at **Settings > System > Logs** (filter by "tado_ce") or [open an issue on GitHub](https://github.com/hiall-fyi/tado_ce/issues).

---

## Documentation

| Document | Description |
|----------|-------------|
| [ENTITIES.md](ENTITIES.md) | Complete list of all sensors, switches, and controls |
| [API_REFERENCE.md](API_REFERENCE.md) | API call types, optimization tips, troubleshooting |
| [ROADMAP.md](ROADMAP.md) | Planned features, ideas, and known limitations |
| [RELEASE_CREDITS.md](RELEASE_CREDITS.md) | Community contributors and acknowledgments |
| [CHANGELOG.md](CHANGELOG.md) | Version history and release notes |

## External Resources

- [Tado API Rate Limit Announcement](https://community.home-assistant.io/t/tado-rate-limiting-api-calls/928751)
- [Official Tado Integration](https://www.home-assistant.io/integrations/tado/)
- [Tado API Documentation (Community)](https://github.com/kritsel/tado-openapispec-v2)

---

## License

**GNU Affero General Public License v3.0 (AGPL-3.0)**

Free to use, modify, and distribute. Modifications must be open source under AGPL-3.0 with attribution.

**Original Author:** Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))

See [LICENSE](LICENSE) for full details.

---

## Contributing

Contributions welcome! 

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=hiall-fyi/tado_ce&type=Date)](https://star-history.com/#hiall-fyi/tado_ce&Date)

---

### Support This Project

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**Made with ❤️ by Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))**

</div>

---

**Version**: 1.9.2 | **Last Updated**: 2026-02-01 | **Tested On**: Home Assistant 2026.1.3

---

<details>
<summary><strong>Disclaimer</strong></summary>

This project is not affiliated with, endorsed by, or connected to tado GmbH or Home Assistant. tado and the tado logo are registered trademarks of tado GmbH. Home Assistant is a trademark of Nabu Casa, Inc.

This integration is provided "as is" without warranty. Use at your own risk.

</details>
