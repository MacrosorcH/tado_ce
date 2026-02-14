# Tado CE Features Guide

Complete guide to all Tado CE exclusive features, configurations, and usage scenarios.

## 📑 Table of Contents

1. [API Management](#-api-management)
2. [Smart Polling](#-smart-polling)
3. [Thermal Analytics](#-thermal-analytics)
4. [Smart Comfort Analytics](#-smart-comfort-analytics)
5. [Enhanced Mold Risk Assessment](#-enhanced-mold-risk-assessment)
6. [Heating Cycle Detection](#-heating-cycle-detection)
7. [Enhanced Controls](#-enhanced-controls)
8. [Optional Features](#-optional-features)
9. [Configuration Scenarios](#-configuration-scenarios)
10. [Troubleshooting](#-troubleshooting)

---

## 📊 API Management

**Available:** v1.0.0+ | **Requirement:** None | **Always Enabled**

API Management provides real-time tracking of your Tado API usage, helping you avoid rate limiting and understand your API consumption patterns.

### Overview

Tado enforces API rate limits (100-20,000 calls/day depending on your plan). The official Home Assistant integration doesn't show actual usage, leaving users unaware until they get blocked. Tado CE solves this by:

- Reading actual rate limit data from Tado API response headers
- Automatically detecting your daily limit (100/5000/20000)
- Tracking when your limit resets each day
- Maintaining a history of all API calls
- Providing test mode to simulate low quota scenarios

### Sensors

| Sensor | Unit | Description |
|--------|------|-------------|
| `sensor.tado_ce_api_usage` | calls | Current API calls used today |
| `sensor.tado_ce_api_limit` | calls | Your daily API call limit |
| `sensor.tado_ce_api_remaining` | calls | Remaining calls until reset |
| `sensor.tado_ce_api_reset` | timestamp | When your limit resets |
| `sensor.tado_ce_next_sync` | timestamp | Next scheduled API sync time (v2.0.0) |
| `sensor.tado_ce_polling_interval` | minutes | Current polling interval (v2.0.0) |
| `sensor.tado_ce_call_history` | count | API call history with statistics (v2.0.0) |
| `sensor.tado_ce_api_call_breakdown` | text | API call breakdown by endpoint type (v2.0.0) |

### Configuration

**API History Retention:**
1. Go to Settings → Devices & Services → Tado CE
2. Click "Configure"
3. Set "API History Retention" (0-365 days, default: 14)
4. Set to 0 for unlimited retention

**Test Mode (v2.0.2+):**
1. Go to Settings → Devices & Services → Tado CE
2. Click "Configure"
3. Enable "Enable Test Mode"
4. Integration will fully simulate a 100 call/day API tier

**How Test Mode Works:**
- **Simulated Quota Tracking** - Each API call increments a simulated `used` counter (capped at 100)
- **Single Source of Truth** - All simulated values stored in `ratelimit.json`, read by all components
- **Full Protection Testing** - Quota Reserve (≤5 remaining), Bootstrap Reserve (≤3 remaining), and Adaptive Polling all use simulated values
- **Reset Detection** - When real API reset is detected, simulated counter resets to 0
- **Visibility** - All API sensors show `test_mode: true` attribute when enabled

**Note:** Test Mode is essential for testing quota protection features without actually having a 100 call limit. It simulates the exact behavior you'd experience with a real 100-call API tier.

### Usage Scenarios

#### Scenario 1: Monitor API Usage to Avoid Rate Limiting

**Goal:** Get alerted before hitting rate limit.

**Setup:**
```yaml
automation:
  - alias: "Alert: API Usage High"
    trigger:
      - platform: numeric_state
        entity_id: sensor.tado_ce_api_remaining
        below: 20  # Alert when <20 calls remaining
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Tado API Usage High"
          message: >
            Only {{ states('sensor.tado_ce_api_remaining') }} API calls remaining.
            Resets at {{ states('sensor.tado_ce_api_reset') }}.
```

**Benefits:**
- Avoid getting rate limited
- Know when to reduce polling frequency
- Plan manual actions around remaining quota

---

#### Scenario 2: Track API Usage Patterns

**Goal:** Understand which features consume most API calls.

**Setup:**
1. Enable API History with 30-day retention
2. Monitor `sensor.tado_ce_api_usage` over time
3. Check attributes for call breakdown by endpoint

**Example Dashboard Card:**
```yaml
type: entities
entities:
  - entity: sensor.tado_ce_api_usage
    name: "Calls Used Today"
  - entity: sensor.tado_ce_api_remaining
    name: "Calls Remaining"
  - entity: sensor.tado_ce_api_limit
    name: "Daily Limit"
  - entity: sensor.tado_ce_api_reset
    name: "Resets At"
```

**Benefits:**
- Identify API-heavy features
- Optimize configuration to reduce calls
- Understand daily usage patterns

---

#### Scenario 3: Test Low Quota Configuration

**Goal:** Test your setup with 100 call/day limit before upgrading plan.

**Setup:**
1. Enable Test Mode in configuration
2. Monitor API usage sensors - they will show `test_mode: true` attribute
3. Adjust polling intervals and optional features
4. Verify quota protection mechanisms work correctly

**Expected Behavior:**
- API limit sensor shows 100 (simulated)
- API usage sensor increments by 1 per API call
- Adaptive polling adjusts to longer intervals as simulated quota decreases
- Quota Reserve pauses polling when simulated remaining ≤5
- Bootstrap Reserve blocks ALL actions when simulated remaining ≤3
- When real API reset is detected, simulated counter resets to 0

**Benefits:**
- Test full quota protection without actually having low quota
- Verify Bootstrap Reserve and Quota Reserve work correctly
- Understand impact of different features on API usage
- Confidence that integration will work correctly when Tado hard-stops at 100 calls

---

## 🔄 Smart Polling

**Available:** v1.0.0+ | **Requirement:** None | **Always Enabled**

Smart Polling automatically adjusts API polling frequency based on time of day, remaining quota, and your configuration preferences.

### Overview

Smart Polling includes multiple strategies to optimize API usage:

- **Day/Night Polling** - More frequent during day, less at night
- **Adaptive Polling** - Auto-adjusts based on remaining quota
- **Quota Reserve Protection** - Pauses polling when quota critically low, auto-resumes after reset (v2.0.0)
- **Custom Intervals** - Override with fixed intervals
- **Optional Sensors** - Toggle features to save API calls

### Configuration

**Day/Night Schedule:**

| Option | Default | Description |
|--------|---------|-------------|
| Day Start Hour | 7 | When "day" period starts (0-23) |
| Night Start Hour | 23 | When "night" period starts (0-23) |
| Custom Day Interval | Empty | Fixed interval during day (1-1440 min) |
| Custom Night Interval | Empty | Fixed interval during night (1-1440 min) |

**Optional Sensors:**

| Option | Default | API Calls Saved |
|--------|---------|-----------------|
| Enable Weather Sensors | Off | 1 call per sync |
| Enable Mobile Device Tracking | Off | 1 call per full sync (every 6h) |
| Enable Home State Sync | Off | Required for Away Mode |

**Other Options:**

| Option | Default | Description |
|--------|---------|-------------|
| Refresh Debounce Delay | 15 s | Delay before refreshing after user actions |
| Sync Mobile Devices Frequently | Off | Sync mobile devices every quick sync instead of every 6h |

### How It Works

**Adaptive Polling:**
- Automatically adjusts polling speed based on remaining API quota
- Faster polling when quota is healthy
- Slower polling when quota is low
- Keeps 10% safety buffer

**Day/Night Aware Adaptive Polling (v2.0.1):**
- Night period: Fixed 120 min interval (MAX_POLLING_INTERVAL) to conserve quota
- Day period: Adaptive based on remaining quota after reserving Night calls
- Reset Time consideration: If Reset is before Night Start, use all quota until Reset (no need to reserve Night quota)
- Uniform Mode: If Day Start == Night Start, always uses Day (adaptive) polling - useful for 24/7 adaptive polling

**Quota Reserve Protection (v2.0.0):**
- Pauses polling when quota critically low (≤5% or ≤5 calls remaining)
- Reserves quota for manual operations (set temperature, change mode, etc.)
- Automatically resumes polling when API reset time passes
- Prevents "locked out" scenario where polling stops and never resumes

**Bootstrap Reserve Protection (v2.0.1):**
- Hard limit of 3 API calls that are NEVER used, even for manual actions
- Reserved for auto-recovery after API reset
- When triggered: Shows persistent notification "API limit reached. Use the Tado app for emergency changes."
- Notification auto-dismisses when API reset detected

**Day/Night Polling:**
- More frequent updates during day (default 7am-11pm)
- Less frequent updates at night (default 11pm-7am)
- Saves API calls when you're sleeping

### Usage Scenarios

#### Scenario 1: Configure Day/Night Polling for Low Quota (100 calls/day)

**Goal:** Stay under 100 calls/day with day/night polling.

**Setup:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Set Day Start Hour: 7
3. Set Night Start Hour: 23
4. Set Custom Day Interval: 30 minutes
5. Set Custom Night Interval: 120 minutes (2 hours)
6. Disable Weather Sensors
7. Disable Mobile Device Tracking

**Expected API Usage:**
- Day (7am-11pm, 16h): 32 syncs × 2 calls = 64 calls
- Night (11pm-7am, 8h): 4 syncs × 2 calls = 8 calls
- Full sync (every 6h): 4 syncs × 2 calls = 8 calls
- **Total: ~80 calls/day** (20% buffer)

**Benefits:**
- Predictable API usage
- More updates during active hours
- Stays well under 100 call limit

---

#### Scenario 2: Use Custom Intervals for Predictable Polling

**Goal:** Consistent polling every 10 minutes regardless of quota.

**Setup:**
1. Set Custom Day Interval: 10 minutes
2. Set Custom Night Interval: 10 minutes
3. Leave other options default

**Result:**
- Polls every 10 minutes 24/7
- ~288 calls/day (requires 500+ quota)
- Adaptive polling can still override if quota runs low

**Benefits:**
- Predictable polling schedule
- Consistent dashboard updates
- Automatic protection if quota drops

---

#### Scenario 3: Disable Optional Sensors to Save API Calls

**Goal:** Minimize API usage by disabling non-essential features.

**Setup:**
1. Disable "Enable Weather Sensors" (saves 1 call/sync)
2. Disable "Enable Mobile Device Tracking" (saves 1 call/full sync)
3. Keep "Enable Home State Sync" disabled unless using Away Mode

**API Calls Saved:**
- Weather: ~144 calls/day (at 10 min intervals)
- Mobile: ~4 calls/day (at 6h full sync)
- **Total saved: ~148 calls/day**

**Benefits:**
- Significant API usage reduction
- Still have core climate control
- Can re-enable features if quota increases

---

#### Scenario 4: Adaptive Polling for High Quota (5000+ calls/day)

**Goal:** Maximum update frequency with automatic quota protection.

**Setup:**
1. Set Custom Day Interval to 1 minute (for fastest updates)
2. Enable all optional sensors
3. Adaptive polling will protect if quota runs low

**Result:**
- Polls every 1 minute when custom interval set (v2.0.2+)
- ~1440+ calls/day with all features at 1-minute polling
- Automatically slows down if quota drops critically low

**Benefits:**
- Near real-time updates for high-quota users
- Never runs out of quota (adaptive override protection)
- Explicit opt-in for aggressive polling

---

## 🔥 Thermal Analytics

**Available:** v2.0.0+ | **Requirement:** Zones with heatingPower data (TRV or Smart Thermostat) | **Always Enabled**

Thermal Analytics provides real-time analysis of your heating system's thermal performance based on complete heating cycles.

### Overview

Thermal Analytics automatically measures how your rooms respond to heating by analyzing complete heating cycles. It calculates thermal properties like inertia, heating rate, and approach factor to help you:

- Optimize preheat timing
- Detect insulation issues
- Compare room performance
- Identify radiator/boiler problems
- Calculate energy efficiency

### Sensors

| Sensor | Unit | Description |
|--------|------|-------------|
| `_thermal_inertia` | minutes | Time constant for temperature changes |
| `_avg_heating_rate` | °C/hour | Average heating rate when heating is ON |
| `_preheat_time` | minutes | Estimated time to reach target temperature |
| `_analysis_confidence` | % | Confidence score for thermal analysis |
| `_heating_acceleration` | °C/h² | Rate of change of heating rate |
| `_approach_factor` | %/hour | How quickly zone approaches target |

### Detailed Sensor Explanations

#### 1. Thermal Inertia (`_thermal_inertia`)

**What it measures:** How quickly your room responds to heating.

**Values:**
- **Low (10-30 min):** Room heats/cools quickly - may indicate poor insulation or small room
- **Medium (30-60 min):** Typical for most rooms
- **High (60+ min):** Room heats/cools slowly - good insulation or large thermal mass

**Why it's useful:**
- Understand how long preheat needs to be
- Identify insulation issues
- Optimize heating schedules

---

#### 2. Average Heating Rate (`_avg_heating_rate`)

**What it measures:** How fast your room heats up (°C per hour).

**Values:**
- **Slow (<0.5°C/h):** Possible issues with radiator, boiler, or insulation
- **Normal (0.5-2.0°C/h):** Typical for most rooms
- **Fast (>2.0°C/h):** Small room or oversized radiator

**Why it's useful:**
- Detect radiator/boiler issues
- Calculate preheat time needed
- Compare room performance

---

#### 3. Preheat Time (`_preheat_time`)

**What it measures:** Estimated time needed to reach target temperature.

**Values:**
- **0 minutes:** Already at target
- **10-30 minutes:** Normal preheat
- **60+ minutes:** Large temperature difference or slow heating

**Why it's useful:**
- Know when to start heating before you arrive home
- Avoid arriving to cold room
- Optimize energy usage

---

#### 4. Analysis Confidence (`_analysis_confidence`)

**What it measures:** How reliable the thermal analysis is (0-100%).

**Values:**
- **Low (<50%):** Not enough data yet
- **Medium (50-80%):** Reasonable confidence
- **High (>80%):** High confidence, reliable estimates

**Why it's useful:**
- Know when to trust preheat estimates
- Wait for high confidence before using automation

---

#### 5. Heating Acceleration (`_heating_acceleration`)

**What it measures:** How heating rate changes over time.

**Values:**
- **Positive:** Heating getting faster
- **Zero:** Steady heating
- **Negative:** Heating slowing down (approaching target)

**Why it's useful:**
- Understand heating dynamics
- Advanced thermal modeling

---

#### 6. Approach Factor (`_approach_factor`)

**What it measures:** How quickly room approaches target temperature (% per hour).

**Values:**
- **Low (<50%/h):** Slow approach, multiple hours to target
- **Medium (50-100%/h):** Normal, 1-2 hours to target
- **High (>100%/h):** Fast approach, less than 1 hour

**Why it's useful:**
- Predict time to reach target
- Optimize preheat timing

---

### Configuration

**No configuration needed** - Thermal Analytics is automatically enabled for all HEATING zones that report heatingPower data.

**Supported Devices (v2.0.1+):**
- TRV devices (VA01, VA02, RU01, RU02)
- Smart Thermostats (SU02) - Added in v2.0.1

### Usage Scenarios

#### Scenario 1: Optimize Preheat Timing

**Goal:** Start heating before you arrive home so room is warm when you get there.

**Setup:**
1. Check `_preheat_time` sensor for your zone
2. Create automation to start heating X minutes before schedule

**Example Automation:**
```yaml
automation:
  - alias: "Bedroom Preheat"
    trigger:
      - platform: time
        at: "17:30:00"  # 30 min before 6pm schedule
    condition:
      - condition: numeric_state
        entity_id: sensor.bedroom_preheat_time
        above: 20  # Only preheat if needed
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedroom
        data:
          temperature: 21
```

**Tips:**
- Wait for `_analysis_confidence` > 80% before trusting preheat estimates
- Preheat time adjusts automatically based on current temperature
- Use `_preheat_advisor` sensor for recommended start time

---

#### Scenario 2: Detect Insulation Issues

**Goal:** Identify rooms with poor insulation or heat loss.

**Indicators:**
- **Low thermal inertia (<20 min)** - Heat escapes quickly
- **Low heating rate (<0.5°C/h)** - Struggling to heat up
- **High approach factor (>150%/h)** - Temperature fluctuates rapidly

**Example:**
```
Living Room:
  Thermal Inertia: 15 minutes ⚠️ (very low)
  Heating Rate: 0.4°C/hour ⚠️ (slow)
  → Possible issue: Window seal broken, door gap, poor wall insulation
```

**Action:**
1. Check for drafts around windows/doors
2. Verify radiator valve is fully open
3. Check boiler flow temperature
4. Consider insulation improvements

---

#### Scenario 3: Compare Room Performance

**Goal:** Understand which rooms heat efficiently and which don't.

**Comparison Table:**

| Room | Thermal Inertia | Heating Rate | Confidence | Status |
|------|----------------|--------------|------------|--------|
| Living Room | 45 min | 1.2°C/h | 95% | ✅ Normal |
| Bedroom | 35 min | 1.5°C/h | 90% | ✅ Good |
| Bathroom | 15 min | 0.6°C/h | 85% | ⚠️ Poor insulation |
| Kitchen | 60 min | 0.8°C/h | 80% | ✅ High thermal mass |

**Interpretation:**
- Bathroom: Low inertia + slow heating = insulation issue
- Kitchen: High inertia + moderate heating = good (thermal mass from appliances)

---

#### Scenario 4: Identify Radiator/Boiler Problems

**Goal:** Detect when heating system performance degrades.

**Indicators:**
- **Heating rate suddenly drops** (e.g., from 1.5°C/h to 0.8°C/h)
- **Preheat time increases** significantly
- **Approach factor decreases** over time

**Example:**
```
Bedroom - Last Week:
  Heating Rate: 1.5°C/hour ✅
  Preheat Time: 60 minutes ✅
  
Bedroom - This Week:
  Heating Rate: 0.7°C/hour ⚠️ (dropped 53%)
  Preheat Time: 130 minutes ⚠️ (increased 117%)
  → Possible issue: Radiator valve stuck, boiler flow temp low, air in system
```

**Action:**
1. Check radiator valve is fully open
2. Bleed radiators (remove air)
3. Check boiler flow temperature
4. Verify TRV battery level
5. Check for furniture blocking radiator

**Benefits:**
- Early detection of heating problems
- Prevent comfort issues
- Reduce energy waste from inefficient heating

---

#### Scenario 5: Calculate Energy Efficiency

**Goal:** Understand which rooms heat most efficiently.

**Efficiency Calculation:**
```
Efficiency = (Actual Heating Rate / Expected Heating Rate) × 100%

Where Expected Rate is based on:
- Room size
- Radiator size
- Boiler flow temperature
```

**Comparison Table:**

| Room | Heating Rate | Thermal Inertia | Efficiency | Status |
|------|--------------|-----------------|------------|--------|
| Living Room | 1.2°C/h | 45 min | 95% | ✅ Efficient |
| Bedroom | 1.5°C/h | 35 min | 110% | ✅ Very efficient |
| Bathroom | 0.6°C/h | 15 min | 60% | ⚠️ Inefficient |
| Kitchen | 0.8°C/h | 60 min | 85% | ✅ Good (high thermal mass) |

**Interpretation:**
- Bedroom: High efficiency - good insulation, properly sized radiator
- Bathroom: Low efficiency - poor insulation or undersized radiator
- Kitchen: Good efficiency considering high thermal mass

**Benefits:**
- Identify rooms needing insulation improvements
- Prioritize radiator upgrades
- Understand energy consumption patterns

---

## 🧠 Smart Comfort Analytics

**Available:** v1.9.0+ | **Requirement:** None | **Opt-in Configuration**

Smart Comfort Analytics learns from your heating patterns and provides predictive insights.

### Overview

Smart Comfort Analytics tracks your heating patterns over time and provides intelligent recommendations. It learns from:

- Historical temperature patterns
- Your manual temperature adjustments
- Heating schedules
- Time of day and day of week patterns
- Seasonal variations

### Sensors

| Sensor | Unit | Description |
|--------|------|-------------|
| `_historical_deviation` | °C | Difference from 7-day average at same time |
| `_next_schedule_time` | timestamp | When next schedule change occurs |
| `_next_schedule_temp` | °C | Target temperature for next schedule |
| `_preheat_advisor` | minutes | Recommended preheat start time |
| `_smart_comfort_target` | °C | AI-recommended target temperature |

### Detailed Sensor Explanations

#### 1. Historical Deviation (`_historical_deviation`)

**What it measures:** How current temperature compares to your 7-day average at this time.

**Values:**
- **Negative (e.g., -0.5°C):** Colder than usual
- **Zero:** Same as usual
- **Positive (e.g., +1.0°C):** Warmer than usual

**Why it's useful:**
- Spot unusual patterns (e.g., window left open)
- Detect issues early
- Identify if heating schedule needs adjustment

---

#### 2. Next Schedule Time (`_next_schedule_time`)

**What it measures:** When your next scheduled temperature change will occur.

**Why it's useful:**
- Know when heating will change automatically
- Plan manual overrides
- Understand your heating schedule

---

#### 3. Next Schedule Temperature (`_next_schedule_temp`)

**What it measures:** Target temperature for your next scheduled block.

**Why it's useful:**
- Preview upcoming temperature changes
- Plan manual adjustments

---

#### 4. Preheat Advisor (`_preheat_advisor`)

**What it measures:** Recommended time to start heating before your next schedule.

**Values:**
- **0 minutes:** No preheat needed
- **15-30 minutes:** Normal preheat
- **60+ minutes:** Large temperature difference

**Why it's useful:**
- Automatically calculate when to start heating
- Arrive home to warm room
- Optimize energy usage

---

#### 5. Smart Comfort Target (`_smart_comfort_target`)

**What it measures:** AI-recommended target temperature based on your patterns.

**How it works:**
- Learns from your manual adjustments
- Adapts to time of day and season
- Suggests optimal temperature

**Why it's useful:**
- Automatic temperature optimization
- Reduces manual adjustments
- Adapts to your preferences

---

### Configuration

**Enable Smart Comfort:**
1. Go to Settings → Devices & Services → Tado CE
2. Click "Configure"
3. Enable "Smart Comfort Analytics"
4. Restart Home Assistant

### Usage Scenarios

#### Scenario 1: Detect Unusual Patterns

**Goal:** Get notified when temperature is abnormal.

**Setup:**
```yaml
automation:
  - alias: "Alert: Room Colder Than Usual"
    trigger:
      - platform: numeric_state
        entity_id: sensor.bedroom_historical_deviation
        below: -2.0  # 2°C colder than usual
    action:
      - service: notify.mobile_app
        data:
          message: "Bedroom is 2°C colder than usual - check for open windows"
```

**Use Cases:**
- Window left open
- Radiator valve stuck
- Heating schedule not working
- Boiler issue

---

#### Scenario 2: Automatic Preheat

**Goal:** Use AI to calculate optimal preheat start time.

**Setup:**
```yaml
automation:
  - alias: "Smart Preheat Before Schedule"
    trigger:
      - platform: template
        value_template: >
          {{ now().timestamp() >= 
             (state_attr('sensor.bedroom_next_schedule_time', 'timestamp') - 
              (states('sensor.bedroom_preheat_advisor') | int * 60)) }}
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedroom
        data:
          temperature: "{{ states('sensor.bedroom_next_schedule_temp') }}"
```

**Benefits:**
- No manual calculation needed
- Adjusts automatically based on current conditions
- Learns from your heating patterns

---

#### Scenario 3: Energy Optimization

**Goal:** Reduce heating when room is warmer than usual.

**Setup:**
```yaml
automation:
  - alias: "Reduce Heating When Warmer Than Usual"
    trigger:
      - platform: numeric_state
        entity_id: sensor.living_room_historical_deviation
        above: 1.0  # 1°C warmer than usual
    condition:
      - condition: state
        entity_id: climate.living_room
        state: "heat"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room
        data:
          temperature: >
            {{ state_attr('climate.living_room', 'temperature') - 0.5 }}
```

**Use Cases:**
- Solar gain (sunny day)
- Extra people in room
- Cooking/appliances generating heat

---

#### Scenario 4: Learn from Manual Adjustments

**Goal:** Let Smart Comfort learn your preferences and suggest optimal temperatures.

**Setup:**
1. Enable Smart Comfort Analytics
2. Use climate entity to adjust temperature manually when needed
3. Monitor `_smart_comfort_target` sensor over 2-3 weeks

**Example Learning Pattern:**
```
Week 1:
  Morning (7am): You set 19°C
  Evening (6pm): You set 21°C
  Night (10pm): You set 18°C

Week 2:
  Morning: You set 19.5°C (cold day)
  Evening: You set 21°C
  Night: You set 18°C

Week 3:
  Smart Comfort Target suggests:
    Morning: 19.2°C (learned average)
    Evening: 21°C (consistent preference)
    Night: 18°C (consistent preference)
    Cold days: +0.5°C adjustment
```

**Automation:**
```yaml
automation:
  - alias: "Apply Smart Comfort Target"
    trigger:
      - platform: state
        entity_id: sensor.bedroom_smart_comfort_target
    condition:
      - condition: template
        value_template: >
          {{ states('sensor.bedroom_smart_comfort_target') != 'unknown' }}
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedroom
        data:
          temperature: "{{ states('sensor.bedroom_smart_comfort_target') }}"
```

**Benefits:**
- Automatic temperature optimization
- Learns your preferences over time
- Reduces need for manual adjustments
- Adapts to seasonal changes

---

#### Scenario 5: Seasonal Temperature Adaptation

**Goal:** Automatically adjust temperatures based on seasonal patterns.

**Setup:**
1. Enable Smart Comfort with 30-day history
2. Monitor historical deviation across seasons
3. Use smart comfort target for seasonal adjustments

**Seasonal Pattern Example:**
```
Winter (Dec-Feb):
  Historical Average: 21°C
  Smart Target: 21.5°C (you prefer warmer in winter)
  
Spring (Mar-May):
  Historical Average: 20°C
  Smart Target: 20°C (comfortable with less heating)
  
Summer (Jun-Aug):
  Historical Average: 18°C
  Smart Target: 18°C (minimal heating needed)
  
Autumn (Sep-Nov):
  Historical Average: 19.5°C
  Smart Target: 20°C (gradual increase as weather cools)
```

**Automation:**
```yaml
automation:
  - alias: "Seasonal Temperature Adjustment"
    trigger:
      - platform: time
        at: "06:00:00"  # Daily check
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room
        data:
          temperature: >
            {% set smart_target = states('sensor.living_room_smart_comfort_target') | float %}
            {% if smart_target > 0 %}
              {{ smart_target }}
            {% else %}
              {{ state_attr('climate.living_room', 'temperature') }}
            {% endif %}
```

**Benefits:**
- Automatic seasonal adaptation
- No manual schedule changes needed
- Learns your seasonal preferences
- Optimizes comfort and energy usage

---

## 💧 Enhanced Mold Risk Assessment

**Available:** v2.0.0+ | **Requirement:** Outdoor temperature sensor | **Always Enabled**

Enhanced Mold Risk uses surface temperature calculation to accurately detect cold spots where mold can grow.

### Configuration

**Window Type Settings:**

| Window Type | U-Value (W/m²K) | Description | Mold Risk |
|-------------|-----------------|-------------|-----------|
| Single Pane | 5.0 | Old single-glazed windows | ⚠️ High |
| Double Pane | 2.7 | Standard double-glazed (default) | ⚠️ Medium |
| Triple Pane | 1.0 | Modern triple-glazed | ✅ Low |
| Passive House | 0.8 | High-performance windows | ✅ Very Low |

**Configure Window Type:**
1. Go to Settings → Devices & Services → Tado CE
2. Click "Configure"
3. Select "Mold Risk Window Type"
4. Choose your window type
5. Restart Home Assistant

**Configure Outdoor Temperature Source:**
1. Go to Settings → Devices & Services → Tado CE
2. Click "Configure"
3. Select "Outdoor Temperature Entity"
4. Choose your weather integration's temperature sensor
5. Restart Home Assistant

### Thresholds

**Mold Risk Levels:**

| Risk Level | Surface RH | Action Required |
|------------|-----------|-----------------|
| Low | <60% | None - safe |
| Medium | 60-70% | Monitor - increase ventilation |
| High | 70-80% | Action needed - increase heating |
| Critical | >80% | Urgent - mold growth likely |

**How it works:**
- Calculates surface temperature of cold spots (e.g., windows)
- Compares with indoor humidity to estimate mold risk
- More accurate than room temperature alone

### Usage Scenarios

#### Scenario 1: Prevent Mold Growth

**Goal:** Get alerted when mold risk is high.

**Setup:**
```yaml
automation:
  - alias: "Alert: High Mold Risk"
    trigger:
      - platform: numeric_state
        entity_id: sensor.bedroom_mold_risk
        above: 70  # High risk threshold
        for:
          minutes: 30  # Sustained for 30 minutes
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ High Mold Risk in Bedroom"
          message: >
            Mold risk: {{ states('sensor.bedroom_mold_risk') }}%
            Surface temp: {{ state_attr('sensor.bedroom_mold_risk', 'surface_temperature') }}°C
            Action: Increase heating or open window for ventilation
```

---

#### Scenario 2: Automatic Ventilation

**Goal:** Open smart window when mold risk is high and outdoor humidity is low.

**Setup:**
```yaml
automation:
  - alias: "Auto Ventilation for Mold Prevention"
    trigger:
      - platform: numeric_state
        entity_id: sensor.bathroom_mold_risk
        above: 75
    condition:
      - condition: numeric_state
        entity_id: sensor.outdoor_humidity
        below: 60  # Only ventilate if outdoor air is dry
    action:
      - service: cover.open_cover
        target:
          entity_id: cover.bathroom_window
      - delay:
          minutes: 15
      - service: cover.close_cover
        target:
          entity_id: cover.bathroom_window
```

---

#### Scenario 3: Optimize Window Type Selection

**Goal:** Understand if window upgrade is worth it.

**Comparison:**

| Scenario | Indoor | Outdoor | Single Pane | Double Pane | Triple Pane |
|----------|--------|---------|-------------|-------------|-------------|
| Winter | 20°C | 0°C | 12.0°C (⚠️ 85% RH) | 15.4°C (⚠️ 72% RH) | 17.8°C (✅ 58% RH) |
| Cold Day | 20°C | 5°C | 14.5°C (⚠️ 78% RH) | 16.7°C (⚠️ 65% RH) | 18.5°C (✅ 55% RH) |
| Mild Day | 20°C | 10°C | 16.5°C (⚠️ 68% RH) | 17.8°C (✅ 58% RH) | 19.0°C (✅ 52% RH) |

**Interpretation:**
- Single pane: High mold risk even on mild days
- Double pane: Medium risk in winter, acceptable in mild weather
- Triple pane: Low risk in all conditions

**ROI Calculation:**
- Upgrade from single to double: ~40% reduction in mold risk
- Upgrade from double to triple: ~20% reduction in mold risk
- Consider upgrade if mold risk frequently >70%

---

#### Scenario 4: Monitor Bathroom After Shower

**Goal:** Prevent mold growth in bathroom after shower use.

**Setup:**
```yaml
automation:
  - alias: "Bathroom Post-Shower Monitoring"
    trigger:
      - platform: numeric_state
        entity_id: sensor.bathroom_humidity
        above: 70  # High humidity after shower
    action:
      - wait_for_trigger:
          - platform: numeric_state
            entity_id: sensor.bathroom_mold_risk
            above: 75
        timeout: "00:30:00"  # Wait up to 30 min
      - choose:
          - conditions:
              - condition: numeric_state
                entity_id: sensor.bathroom_mold_risk
                above: 75
            sequence:
              - service: notify.mobile_app
                data:
                  title: "⚠️ Bathroom Mold Risk High"
                  message: "Open window or turn on extractor fan"
              - service: switch.turn_on
                target:
                  entity_id: switch.bathroom_extractor_fan
              - delay:
                  minutes: 15
              - service: switch.turn_off
                target:
                  entity_id: switch.bathroom_extractor_fan
```

**Benefits:**
- Automatic mold prevention after showers
- Reduces manual intervention
- Protects bathroom from moisture damage

---

#### Scenario 5: Basement Mold Prevention

**Goal:** Monitor and prevent mold in basement with poor ventilation.

**Setup:**
```yaml
automation:
  - alias: "Basement Mold Prevention"
    trigger:
      - platform: numeric_state
        entity_id: sensor.basement_mold_risk
        above: 70
        for:
          hours: 2  # Sustained high risk
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.basement
        data:
          temperature: >
            {{ state_attr('climate.basement', 'temperature') + 1 }}
      - service: notify.mobile_app
        data:
          title: "⚠️ Basement Mold Risk"
          message: >
            Mold risk: {{ states('sensor.basement_mold_risk') }}%
            Increased heating by 1°C. Consider dehumidifier.
```

**Dashboard Card:**
```yaml
type: entities
title: Basement Mold Monitoring
entities:
  - entity: sensor.basement_mold_risk
    name: "Mold Risk"
  - entity: sensor.basement_temperature
    name: "Temperature"
  - entity: sensor.basement_humidity
    name: "Humidity"
  - type: attribute
    entity: sensor.basement_mold_risk
    attribute: surface_temperature
    name: "Surface Temp"
```

**Benefits:**
- Continuous basement monitoring
- Automatic heating adjustment
- Early warning for dehumidifier needs
- Prevents structural damage

---

## 📊 Adaptive Smart Polling

**Available:** v2.0.0+ | **Requirement:** None | **Always Enabled**

Adaptive Smart Polling automatically adjusts API polling interval based on remaining quota and time until reset.

### How It Works

**Formula:**
```
Interval = (Time Until Reset / Remaining Calls) / Safety Buffer

Where:
  Safety Buffer = 0.90 (keep 10% reserve)
  Adaptive Floor = 5 minutes (default minimum)
  Max Interval = 120 minutes
```

### Configuration

**Polling Interval Options:**

| Mode | Description | When to Use |
|------|-------------|-------------|
| Adaptive (Recommended) | Auto-adjusts based on quota, minimum 5 min | Default - works for all quota tiers |
| Custom Interval | Fixed interval (1-1440 min) | Override when you want specific polling |

**Set Custom Interval:**
1. Go to Settings → Devices & Services → Tado CE
2. Click "Configure"
3. Set Custom Day/Night Interval (1-1440 minutes)
4. Restart Home Assistant

**Note:** 
- Without custom interval: Adaptive polling uses 5-minute minimum (sensible default)
- With custom interval: You can set as low as 1 minute for high-quota users (v2.0.2+)
- Adaptive polling can still override custom interval if quota is critically low

### Usage Scenarios

#### Scenario 1: High Quota Tier (5000+ calls/day)

**Situation:**
- Quota: 5000 calls/day
- Remaining: 4500 calls
- Time until reset: 12 hours

**Adaptive Calculation:**
```
Interval = (720 min / 4500) / 0.90 = 0.16 / 0.90 = 0.18 minutes
Clamped to MIN_INTERVAL = 5 minutes
```

**Result:** Polls every 5 minutes (maximum frequency)

**Benefits:**
- Near real-time updates
- Never runs out of quota
- Automatically slows down if usage spikes

---

#### Scenario 2: Low Quota Tier (100 calls/day)

**Situation:**
- Quota: 100 calls/day
- Remaining: 50 calls
- Time until reset: 12 hours

**Adaptive Calculation:**
```
Interval = (720 min / 50) / 0.90 = 14.4 / 0.90 = 16 minutes
```

**Result:** Polls every 16 minutes

**Benefits:**
- Distributes calls evenly across remaining time
- Prevents running out of quota
- Automatically speeds up after reset

---

#### Scenario 3: Quota Running Low

**Situation:**
- Quota: 5000 calls/day
- Remaining: 10 calls (⚠️ low!)
- Time until reset: 6 hours

**Adaptive Calculation:**
```
Interval = (360 min / 10) / 0.90 = 36 / 0.90 = 40 minutes
```

**Result:** Polls every 40 minutes (slowed down to conserve quota)

**Benefits:**
- Prevents rate limiting
- Ensures some updates until reset
- Automatically speeds up after reset

---

#### Scenario 4: Custom Interval Override

**Situation:**
- You want consistent 10-minute polling
- Quota: 5000 calls/day
- Remaining: 4000 calls

**Setup:**
1. Enable "Custom Polling Interval" = 10 minutes
2. Adaptive polling monitors quota
3. If quota drops below safe threshold, adaptive overrides custom interval

**Result:**
- Normal: Polls every 10 minutes (custom)
- Low quota: Polls every 20+ minutes (adaptive override)

**Benefits:**
- Predictable polling when quota is healthy
- Automatic protection when quota is low

---

## 🔄 Heating Cycle Detection

**Available:** v2.0.0+ | **Requirement:** Zones with heatingPower data | **Always Enabled**

Heating Cycle Detection identifies complete heating cycles (heating ON → target reached → heating OFF) for accurate thermal analysis.

### Configuration

**Cycle Detection:**
- Automatically detects complete heating cycles
- Minimum cycle: 10 minutes
- Maximum cycle: 4 hours
- No configuration needed

**How it works:**
- Monitors when heating turns on
- Tracks temperature rise
- Detects when target is reached
- Analyzes complete cycle for thermal properties

### Usage Scenarios

#### Scenario 1: Monitor Heating Efficiency

**Goal:** Track how many cycles complete successfully vs timeout.

**Check Attributes:**
```yaml
sensor.bedroom_thermal_inertia:
  attributes:
    cycle_count: 15  # Total cycles analyzed
    timeout_count: 2  # Cycles that timed out
    success_rate: 87%  # (15-2)/15 = 87%
```

**Interpretation:**
- High success rate (>90%): Heating system working well
- Low success rate (<70%): Possible issues (target too high, slow heating, frequent interruptions)

---

#### Scenario 2: Detect Heating Issues

**Goal:** Get alerted when heating cycles fail frequently.

**Setup:**
```yaml
automation:
  - alias: "Alert: Heating Cycles Failing"
    trigger:
      - platform: state
        entity_id: sensor.bedroom_analysis_confidence
    condition:
      - condition: template
        value_template: >
          {{ state_attr('sensor.bedroom_thermal_inertia', 'timeout_count') | int > 5 }}
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Heating Issue Detected"
          message: >
            {{ state_attr('sensor.bedroom_thermal_inertia', 'timeout_count') }} 
            heating cycles timed out. Check radiator valve and boiler.
```

---

## ⚡ Enhanced Controls

**Available:** v1.0.0+ | **Requirement:** None | **Always Enabled**

Enhanced Controls provide improved responsiveness and convenience features for climate control.

### Overview

Enhanced Controls improve the user experience with:

- **Immediate Refresh** - Dashboard updates immediately after user actions
- **Smart Boost** - One-tap boost with intelligent duration
- **Enhanced Hot Water Timer** - AUTO/HEAT/OFF modes with timer presets
- **Temperature Offset** - Calibrate device temperature readings

### Features

#### 1. Immediate Refresh

**What it does:** Dashboard updates immediately after you change temperature or mode.

**How it works:**
- After any climate control action, integration triggers immediate refresh
- Configurable debounce delay (default: 15 seconds)
- Prevents stale data on dashboard

**Configuration:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Set "Refresh Debounce Delay" (1-60 seconds)
3. Lower values = faster updates, higher API usage

#### 2. Smart Boost

**What it does:** Quick heating boost with intelligent duration based on heating rate.

**How it works:**
- Calculates boost duration based on thermal analytics
- Considers current temperature and target
- Automatically returns to schedule after boost

**Usage:**
```yaml
service: tado_ce.set_climate_timer
target:
  entity_id: climate.living_room
data:
  temperature: 22
  time_period: 60  # Boost for 60 minutes
```

#### 3. Enhanced Hot Water Timer

**What it does:** Control hot water with AUTO/HEAT/OFF modes and timer presets.

**Modes:**
- **AUTO** - Follow schedule
- **HEAT** - Turn on for configured duration
- **OFF** - Turn off

**Timer Presets:**
- 30 minutes
- 60 minutes (default)
- 90 minutes

**Configuration:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Set "Hot Water Timer Duration" (5-1440 minutes)

#### 4. Temperature Offset

**What it does:** Calibrate device temperature readings for accuracy.

**Range:** -10°C to +10°C

**Usage:**
```yaml
service: tado_ce.set_climate_temperature_offset
target:
  entity_id: climate.bedroom
data:
  offset: -0.5  # Device reads 0.5°C too high
```

### Configuration

| Option | Default | Description |
|--------|---------|-------------|
| Refresh Debounce Delay | 15 s | Delay before refreshing after user actions (1-60 s) |
| Hot Water Timer Duration | 60 min | Duration when HEAT mode is activated (5-1440 min) |
| Enable Temperature Offset Attribute | Off | Adds `offset_celsius` to climate entities |

### Usage Scenarios

#### Scenario 1: Use Smart Boost for Quick Heating

**Goal:** Quickly heat room before guests arrive.

**Setup:**
```yaml
script:
  quick_boost_living_room:
    alias: "Quick Boost Living Room"
    sequence:
      - service: tado_ce.set_climate_timer
        target:
          entity_id: climate.living_room
        data:
          temperature: 22
          time_period: 60
      - service: notify.mobile_app
        data:
          message: "Living room boosted to 22°C for 60 minutes"
```

**Dashboard Button:**
```yaml
type: button
name: "Quick Boost"
icon: mdi:fire
tap_action:
  action: call-service
  service: script.quick_boost_living_room
```

**Benefits:**
- One-tap quick heating
- Automatic return to schedule
- No manual timer management

---

#### Scenario 2: Configure Hot Water Timer for Morning Routine

**Goal:** Turn on hot water for morning shower automatically.

**Setup:**
```yaml
automation:
  - alias: "Morning Hot Water"
    trigger:
      - platform: time
        at: "06:00:00"
    action:
      - service: tado_ce.set_water_heater_timer
        target:
          entity_id: water_heater.hot_water
        data:
          time_period: 60  # Heat for 60 minutes
      - service: notify.mobile_app
        data:
          message: "Hot water heating for morning shower"
```

**Manual Control:**
```yaml
type: entities
entities:
  - entity: water_heater.hot_water
  - type: buttons
    entities:
      - entity: button.hot_water_timer_30_min
        name: "30 min"
      - entity: button.hot_water_timer_60_min
        name: "60 min"
      - entity: button.hot_water_timer_90_min
        name: "90 min"
```

**Benefits:**
- Automatic morning hot water
- Manual timer buttons for flexibility
- Energy savings (only heat when needed)

---

#### Scenario 3: Calibrate Temperature Offset for Accurate Readings

**Goal:** Fix inaccurate temperature readings from TRV.

**Problem:**
- TRV shows 20.5°C
- Separate thermometer shows 20.0°C
- TRV reads 0.5°C too high

**Solution:**
```yaml
service: tado_ce.set_climate_temperature_offset
target:
  entity_id: climate.bedroom
data:
  offset: -0.5  # Correct the +0.5°C error
```

**Verification:**
1. Check `offset_celsius` attribute on climate entity
2. Compare TRV reading with reference thermometer
3. Adjust offset if needed

**Benefits:**
- Accurate temperature control
- Better comfort
- Correct thermal analytics data

---

#### Scenario 4: Immediate Dashboard Updates After Changes

**Goal:** See temperature changes immediately on dashboard.

**Configuration:**
1. Set Refresh Debounce Delay to 5 seconds (faster updates)
2. Monitor API usage to ensure it stays within limits

**Expected Behavior:**
- Change temperature on dashboard
- Wait 5 seconds (debounce delay)
- Dashboard refreshes with new state
- No stale data

**Trade-offs:**
- Lower delay = faster updates, more API calls
- Higher delay = slower updates, fewer API calls
- Default 15s is good balance for most users

**Benefits:**
- Immediate feedback on changes
- Better user experience
- Confidence that changes were applied

---

## 🔧 Optional Features

**Available:** Various versions | **Requirement:** Varies | **Opt-in Configuration**

Optional Features provide additional functionality that can be enabled based on your needs.

### Overview

Optional Features include:

- **Schedule Calendar** - View heating schedules as calendar events
- **Boiler Flow Temperature** - Monitor OpenTherm boiler flow temp
- **Device Tracking** - Mobile device presence detection
- **Home State Sync** - Home/away presence for automations

### Features

#### 1. Schedule Calendar

**What it does:** Shows heating schedules as calendar events in Home Assistant.

**Requirements:**
- Tado heating schedules configured in Tado app
- Calendar integration enabled

**Configuration:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Enable "Enable Schedule Calendar"
3. Restart Home Assistant

**Entities Created:**
- `calendar.{zone_name}_schedule` - Calendar entity per zone

#### 2. Boiler Flow Temperature

**What it does:** Monitors boiler flow temperature for OpenTherm systems.

**Requirements:**
- OpenTherm-compatible boiler
- Tado system with OpenTherm support

**Auto-Detection:**
- Automatically detected if available
- No configuration needed

**Entity:**
- `sensor.boiler_flow_temperature` - Current flow temp

#### 3. Device Tracking

**What it does:** Tracks mobile device presence (home/away).

**Requirements:**
- Mobile devices with geo-tracking enabled in Tado app

**Configuration:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Enable "Enable Mobile Device Tracking"
3. Restart Home Assistant

**Entities Created:**
- `device_tracker.{device_name}` - Device tracker per mobile device

**API Usage:**
- 1 call per full sync (every 6 hours)
- Can enable "Sync Mobile Devices Frequently" for more updates

#### 4. Home State Sync

**What it does:** Syncs home/away presence state.

**Requirements:**
- None (works regardless of Tado app geofencing setting)

**Configuration:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Enable "Enable Home State Sync"
3. Restart Home Assistant

**Entities Created:**
- `select.tado_ce_presence_mode` - Control presence mode (auto/home/away)
- `binary_sensor.tado_ce_home` - Read-only home/away status
- Climate entities show "home"/"away" preset

### Overlay Mode (v2.0.2)

**What it does:** Controls how long manual temperature changes last when you adjust temperature via Home Assistant.

**Entity:** `select.tado_ce_overlay_mode`

**Options:**

| Option | Description |
|--------|-------------|
| `Tado Mode` | Follows per-device "Manual Control" settings in Tado app (default) |
| `Next Time Block` | Override lasts until next scheduled change |
| `Manual` | Infinite override until you manually change back |

**How It Works:**

When you change temperature via Home Assistant (`climate.set_temperature`), the overlay mode determines how long that change lasts:

- **Tado Mode**: Respects the "Manual Control" setting you configured for each device in the Tado app. This is the most flexible option as you can configure different behaviors per device.
- **Next Time Block**: Override automatically ends when the next schedule block starts. Good for temporary adjustments.
- **Manual**: Override stays until you manually switch back to Auto mode. Use this if you want full control.

**Configuring Per-Device Behavior (Tado Mode):**

If using "Tado Mode", configure per-device behavior in the Tado app:
1. Open Tado app → Settings → Rooms & Devices
2. Select a device
3. Manual Control → Choose:
   - "Until next automatic change" (same as Next Time Block)
   - "Until you cancel" (same as Manual)
   - "For a set time" (timer-based)

**API Usage:** 0 calls (local storage only)

**Note:** Default changed from infinite override to Tado Mode in v2.0.2. Users relying on infinite override should either:
- Set Overlay Mode to "Manual", or
- Configure "Until you cancel" in Tado app for each device

---

### Understanding Geofencing vs Presence Mode

**Important:** Geofencing is a Tado account-level setting configured in the Tado app, not in this integration.

| Scenario | "Auto" Mode Behavior |
|----------|---------------------|
| Geofencing **enabled** in Tado app | Tado automatically switches Home/Away based on mobile device locations |
| Geofencing **disabled** in Tado app | Stays in current state (typically Home) - no automatic switching |

**How Presence Lock Works:**
- **"home" or "away"**: Creates a presence lock that overrides geofencing. Even if geofencing is enabled, Tado won't automatically change the state.
- **"auto"**: Deletes the presence lock. If geofencing is enabled, Tado resumes automatic control. If geofencing is disabled, nothing changes automatically.

**Note:** The "Home/Away State Sync" option in Tado CE integration settings only controls whether the integration syncs the home/away state from Tado - it does not enable or disable geofencing itself.

### Presence Mode Behavior Scenarios

Understanding how "Auto" mode behaves is crucial, especially when geofencing is disabled:

| Initial State | Action | Geofencing ON | Geofencing OFF |
|--------------|--------|---------------|----------------|
| Home (locked) | → Auto | Based on phone location | **Stays Home** |
| Away (locked) | → Auto | Based on phone location | **Stays Away** |
| Home (locked) | → Away | Forced Away | Forced Away |
| Away (locked) | → Home | Forced Home | Forced Home |

**Common Misconception:**
```
Home → Away → Auto = Back to Home?  ❌ WRONG (when geofencing OFF)
Home → Away → Auto = Stays Away     ✅ CORRECT (when geofencing OFF)
```

**Why?** When geofencing is disabled, Tado has no way to determine your actual location. The "Auto" option simply removes the presence lock - it doesn't change the presence state. The state remains whatever it was before unlocking.

**Recommendation:** If you have geofencing disabled in the Tado app:
- Use "Home" or "Away" directly instead of "Auto"
- Or use Home Assistant automations with other presence detection (router, BLE, etc.) to control the presence mode

### Configuration

| Option | Default | API Calls | Description |
|--------|---------|-----------|-------------|
| Enable Schedule Calendar | Off | 0 | Calendar entities showing heating schedules |
| Enable Mobile Device Tracking | Off | 1/full sync | Device tracker entities |
| Enable Home State Sync | Off | 0 | Required for Presence Mode select and presets |
| Sync Mobile Devices Frequently | Off | +1/sync | Sync mobile devices every quick sync |

### Usage Scenarios

#### Scenario 1: View Heating Schedule in Calendar

**Goal:** See heating schedule alongside other calendar events.

**Setup:**
1. Enable Schedule Calendar
2. Add calendar card to dashboard

**Dashboard Card:**
```yaml
type: calendar
entities:
  - calendar.living_room_schedule
  - calendar.bedroom_schedule
  - calendar.bathroom_schedule
```

**Benefits:**
- Visual schedule overview
- Plan manual overrides
- Understand heating patterns

---

#### Scenario 2: Monitor Boiler Flow Temperature

**Goal:** Track boiler performance and detect issues.

**Setup:**
```yaml
type: history-graph
entities:
  - entity: sensor.boiler_flow_temperature
hours_to_show: 24
```

**Alert on Low Flow Temp:**
```yaml
automation:
  - alias: "Alert: Low Boiler Flow Temperature"
    trigger:
      - platform: numeric_state
        entity_id: sensor.boiler_flow_temperature
        below: 40  # Below 40°C
        for:
          minutes: 30
    condition:
      - condition: state
        entity_id: climate.living_room
        state: "heat"
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Low Boiler Flow Temperature"
          message: >
            Boiler flow temp: {{ states('sensor.boiler_flow_temperature') }}°C
            Check boiler settings or call technician.
```

**Benefits:**
- Monitor boiler performance
- Detect heating issues early
- Optimize boiler settings

---

#### Scenario 3: Use Device Tracking for Presence Detection

**Goal:** Automatically adjust heating based on presence.

**Setup:**
```yaml
automation:
  - alias: "Away Mode When Everyone Leaves"
    trigger:
      - platform: state
        entity_id: group.family_devices
        to: "not_home"
        for:
          minutes: 30
    action:
      - service: select.select_option
        target:
          entity_id: select.tado_ce_presence_mode
        data:
          option: "away"
      - service: notify.mobile_app
        data:
          message: "Everyone left - Away mode activated"

  - alias: "Home Mode When Someone Arrives"
    trigger:
      - platform: state
        entity_id: group.family_devices
        to: "home"
    action:
      - service: select.select_option
        target:
          entity_id: select.tado_ce_presence_mode
        data:
          option: "home"
      - service: notify.mobile_app
        data:
          message: "Someone arrived - Home mode activated"
```

**Benefits:**
- Automatic away mode
- Energy savings when away
- Comfort when home

---

#### Scenario 4: Automate Away Mode Based on Presence

**Goal:** Use Home State Sync for advanced presence automations.

**Setup:**
```yaml
automation:
  - alias: "Vacation Mode"
    trigger:
      - platform: state
        entity_id: input_boolean.vacation_mode
        to: "on"
    action:
      - service: select.select_option
        target:
          entity_id: select.tado_ce_presence_mode
        data:
          option: "away"
      - service: climate.set_temperature
        target:
          entity_id: all
        data:
          temperature: 16  # Frost protection

  - alias: "Return from Vacation"
    trigger:
      - platform: state
        entity_id: input_boolean.vacation_mode
        to: "off"
    action:
      - service: select.select_option
        target:
          entity_id: select.tado_ce_presence_mode
        data:
          option: "auto"  # Resume geofencing (if enabled in Tado app)
      - service: climate.set_preset_mode
        target:
          entity_id: all
        data:
          preset_mode: "home"
```

**Benefits:**
- Manual vacation mode control
- Automatic temperature reduction
- Easy return to normal mode

---

## 🎯 Configuration Scenarios

### Scenario 1: Small Apartment (1-2 rooms)

**Profile:**
- Quota: 100 calls/day
- Zones: 1-2 heating zones
- Features needed: Basic monitoring

**Recommended Configuration:**
```yaml
Adaptive Polling: Enabled (default)
Smart Comfort: Disabled (save quota)
Weather Sensors: Disabled (save quota)
Mold Risk: Enabled (important for small spaces)
Window Type: Double Pane (typical)
```

**Expected API Usage:**
- ~80-120 calls/day
- Polling interval: ~15-20 minutes

---

### Scenario 2: Large House (5+ rooms)

**Profile:**
- Quota: 5000+ calls/day
- Zones: 5-10 heating zones
- Features needed: Full analytics

**Recommended Configuration:**
```yaml
Adaptive Polling: Enabled (default)
Smart Comfort: Enabled (useful for multiple zones)
Weather Sensors: Enabled (solar gain affects large houses)
Mold Risk: Enabled
Window Type: Per-zone (mix of double/triple pane)
Outdoor Temp: Weather integration
```

**Expected API Usage:**
- ~300-800 calls/day
- Polling interval: ~5-10 minutes

---

### Scenario 3: Energy Optimization Focus

**Profile:**
- Goal: Minimize energy usage
- Zones: Any
- Features needed: Preheat, efficiency tracking

**Recommended Configuration:**
```yaml
Adaptive Polling: Enabled
Smart Comfort: Enabled (for preheat advisor)
Thermal Analytics: Monitor closely
Automations:
  - Preheat before schedule (avoid heating too early)
  - Reduce heating when warmer than usual
  - Alert on low heating efficiency
```

**Key Sensors to Monitor:**
- `_preheat_time` - Optimize start time
- `_historical_deviation` - Detect free heat
- `_avg_heating_rate` - Track efficiency trends

---

### Scenario 4: Mold Prevention Focus

**Profile:**
- Goal: Prevent mold in high-risk areas (bathroom, basement)
- Zones: High-humidity zones
- Features needed: Mold risk monitoring

**Recommended Configuration:**
```yaml
Mold Risk: Enabled
Window Type: Accurate setting (affects calculation)
Outdoor Temp: Required (weather integration)
Automations:
  - Alert when mold risk >70%
  - Auto-ventilation when safe
  - Increase heating in high-risk zones
```

**Key Sensors to Monitor:**
- `_mold_risk` - Primary indicator
- `surface_temperature` (attribute) - Cold spot detection
- `temperature_source` (attribute) - Verify using surface estimation

---

### Scenario 5: Low Quota Tier (100 calls/day)

**Profile:**
- Quota: 100 calls/day
- Zones: Any number
- Goal: Stay under limit with essential features

**Recommended Configuration:**
```yaml
# Polling Schedule
Day Start Hour: 7
Night Start Hour: 23
Custom Day Interval: 30 minutes
Custom Night Interval: 120 minutes (2 hours)

# Features
Enable Weather Sensors: Off (saves 1 call/sync)
Enable Mobile Device Tracking: Off (saves 1 call/full sync)
Enable Home State Sync: Off
Enable Smart Comfort Analytics: Off (saves processing)
Enable Schedule Calendar: Off

# Smart Comfort Settings
Outdoor Temperature Entity: (leave empty or use weather integration)
```

**Expected API Usage:**
- Day (7am-11pm, 16h): 32 syncs × 2 calls = 64 calls
- Night (11pm-7am, 8h): 4 syncs × 2 calls = 8 calls
- Full sync (every 6h): 4 syncs × 2 calls = 8 calls
- **Total: ~80 calls/day** (20% buffer)

**Features Available:**
- ✅ Climate control
- ✅ Temperature/humidity sensors
- ✅ Thermal analytics (always enabled)
- ✅ Mold risk (always enabled)
- ✅ Heating cycle detection
- ❌ Weather sensors
- ❌ Smart Comfort analytics
- ❌ Device tracking

**Tips:**
- Use manual temperature adjustments instead of automations
- Check dashboard less frequently
- Disable optional features you don't need
- Monitor API usage sensor daily

---

### Scenario 6: High Quota Tier (5000+ calls/day)

**Profile:**
- Quota: 5000+ calls/day
- Zones: Any number
- Goal: Maximum features and update frequency

**Recommended Configuration:**
```yaml
# Polling Schedule
Day Start Hour: 7
Night Start Hour: 23
Custom Day Interval: (leave empty - use adaptive)
Custom Night Interval: (leave empty - use adaptive)

# Features
Enable Weather Sensors: On
Enable Mobile Device Tracking: On
Enable Home State Sync: On
Enable Smart Comfort Analytics: On
Enable Schedule Calendar: On
Sync Mobile Devices Frequently: On

# Smart Comfort Settings
Outdoor Temperature Entity: weather.home
Smart Comfort Mode: Moderate (±1.0°C)
Smart Comfort History Days: 30
```

**Expected API Usage:**
- Adaptive polling: ~5 minute intervals
- ~576 calls/day with all features
- Plenty of headroom for manual actions

**Features Available:**
- ✅ All features enabled
- ✅ Near real-time updates
- ✅ Full analytics
- ✅ Weather integration
- ✅ Device tracking
- ✅ Schedule calendar

**Benefits:**
- Maximum responsiveness
- All analytics features
- Rich automation possibilities
- No quota concerns

---

### Scenario 7: Mixed Zone Types (Heating + AC)

**Profile:**
- Zones: Mix of heating and AC zones
- Goal: Optimize for both zone types

**Recommended Configuration:**
```yaml
# Polling Schedule
Adaptive polling (default)

# Features
Enable Weather Sensors: On (important for AC efficiency)
Enable Smart Comfort Analytics: On
Thermal Analytics: Enabled for TRV zones only

# Per-Zone Settings
Heating Zones:
  - Monitor thermal inertia
  - Use preheat advisor
  - Track heating rate
  
AC Zones:
  - Monitor cooling efficiency
  - Track outdoor temperature impact
  - Use historical deviation for solar gain detection
```

**Key Differences:**

| Feature | Heating Zones | AC Zones |
|---------|---------------|----------|
| Thermal Analytics | ✅ Available | ❌ Not available (no heating power data) |
| Smart Comfort | ✅ Heating patterns | ✅ Cooling patterns |
| Weather Impact | Moderate | High (solar gain) |
| Preheat/Precool | Preheat advisor | Manual precool timing |

**Automations:**
```yaml
# Heating zone preheat
automation:
  - alias: "Preheat Bedroom"
    trigger:
      - platform: template
        value_template: >
          {{ now().timestamp() >= 
             (state_attr('sensor.bedroom_next_schedule_time', 'timestamp') - 
              (states('sensor.bedroom_preheat_advisor') | int * 60)) }}
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.bedroom
        data:
          temperature: "{{ states('sensor.bedroom_next_schedule_temp') }}"

# AC zone precool on hot days
automation:
  - alias: "Precool Living Room"
    trigger:
      - platform: numeric_state
        entity_id: sensor.outdoor_temperature
        above: 28
      - platform: time
        at: "14:00:00"  # Hottest part of day
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.living_room_ac
        data:
          temperature: 22
```

**Benefits:**
- Optimized for both heating and cooling
- Weather-aware automations
- Zone-specific strategies

---

### Scenario 8: OpenTherm Boiler Setup

**Profile:**
- Boiler: OpenTherm-compatible
- Goal: Monitor and optimize boiler performance

**Recommended Configuration:**
```yaml
# Features
Enable Weather Sensors: On
Enable Smart Comfort Analytics: On
Thermal Analytics: Monitor closely

# Boiler Flow Temperature
Auto-detected: sensor.boiler_flow_temperature
```

**Monitoring Dashboard:**
```yaml
type: vertical-stack
cards:
  - type: entities
    title: Boiler Performance
    entities:
      - entity: sensor.boiler_flow_temperature
        name: "Flow Temperature"
      - entity: sensor.outdoor_temperature
        name: "Outdoor Temperature"
      
  - type: history-graph
    title: Boiler Flow Temperature (24h)
    entities:
      - sensor.boiler_flow_temperature
    hours_to_show: 24
    
  - type: entities
    title: Zone Heating Rates
    entities:
      - entity: sensor.living_room_avg_heating_rate
      - entity: sensor.bedroom_avg_heating_rate
      - entity: sensor.bathroom_avg_heating_rate
```

**Optimization Automations:**
```yaml
automation:
  - alias: "Alert: Low Boiler Flow Temperature"
    trigger:
      - platform: numeric_state
        entity_id: sensor.boiler_flow_temperature
        below: 45
        for:
          minutes: 30
    condition:
      - condition: template
        value_template: >
          {{ states('climate.living_room') == 'heat' }}
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Low Boiler Flow Temperature"
          message: >
            Flow temp: {{ states('sensor.boiler_flow_temperature') }}°C
            Check boiler settings.

  - alias: "Alert: Heating Rate Dropped"
    trigger:
      - platform: template
        value_template: >
          {{ states('sensor.bedroom_avg_heating_rate') | float < 0.5 }}
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Heating Rate Low"
          message: >
            Bedroom heating rate: {{ states('sensor.bedroom_avg_heating_rate') }}°C/h
            Boiler flow: {{ states('sensor.boiler_flow_temperature') }}°C
            Check boiler and radiators.
```

**Benefits:**
- Monitor boiler performance
- Detect issues early
- Optimize flow temperature
- Correlate boiler temp with heating rates

---

## 🔧 Troubleshooting

### Issue: Thermal Analytics Shows "Unknown"

**Possible Causes:**
1. Zone doesn't report heatingPower data (rare - most HEATING zones do)
2. Not enough heating cycles collected (need 3-5 cycles)
3. HeatingCycleCoordinator not initialized
4. Heating always on (no complete cycles)

**Solution:**
1. Check if zone has heatingPower: Look at `sensor.{zone}_heating` entity
2. Wait 2-3 days for data collection
3. Check HA logs for coordinator warnings
4. Verify `cycle_count` attribute > 0
5. Ensure heating turns on/off regularly (not always on or always off)
6. Check `data_points` or `cycle_count` attribute to see how much data is available

**Note (v2.0.1):** Thermal Analytics is now available for ALL zones with heatingPower data, including SU02 Smart Thermostat zones.

---

### Issue: Inaccurate Thermal Analytics Values

**Possible Causes:**
1. Low confidence - Check `_analysis_confidence` sensor
2. Recent changes - Moved furniture, changed radiator settings, weather changed
3. External heat sources - Solar gain, cooking, people
4. Not enough heating cycles analyzed

**Solution:**
- Wait for confidence to reach >80%
- Values will stabilize after 5-10 heating cycles
- Check for external factors affecting temperature
- Avoid making changes to room during data collection period

---

### Issue: Heating Efficiency >200%

**This is normal!** High efficiency means you're getting free heat from:
- ☀️ Solar gain (sun through windows)
- 🍳 Internal heat sources (cooking, appliances, people)
- 🌡️ Warmer outdoor temperature
- 🪟 Better insulation (windows/doors closed)

**Interpretation:**
- **100%** = Normal heating (as expected)
- **<75%** = Slow heating (possible issue: open window, poor insulation, cold weather)
- **>125%** = Fast heating (external heat sources helping) ✅

**Action:**
- No action needed if efficiency is high
- Consider reducing heating target to save energy
- Use historical deviation to detect free heat patterns

---

### Issue: Mold Risk Always Shows "Room Temperature"

**Possible Causes:**
1. Outdoor temperature entity not configured
2. Outdoor temperature sensor unavailable
3. Window type not set

**Solution:**
1. Configure outdoor temperature entity in integration settings
2. Verify outdoor sensor is working: Check `sensor.outdoor_temperature`
3. Set window type in integration settings
4. Check `temperature_source` attribute - should show "surface_estimation"
5. If using weather integration, ensure it provides temperature data

---

### Issue: Adaptive Polling Too Slow

**Possible Causes:**
1. Low remaining quota
2. Custom interval set too high
3. Many zones consuming quota

**Solution:**
1. Check `sensor.tado_ce_api_usage` - how many calls remaining?
2. Disable custom interval to use pure adaptive
3. Disable optional features (weather, smart comfort) to save quota
4. Consider upgrading Tado subscription for higher quota
5. Check if Test Mode is enabled (simulates 100 call limit)

---

### Issue: Smart Comfort Sensors Not Appearing

**Possible Causes:**
1. Smart Comfort not enabled in configuration
2. Integration not restarted after enabling
3. Not enough historical data collected

**Solution:**
1. Go to Settings → Devices & Services → Tado CE → Configure
2. Enable "Smart Comfort Analytics"
3. Restart Home Assistant
4. Wait 5 minutes for sensors to appear
5. Wait 24-48 hours for meaningful data

---

### Issue: API Rate Limit Exceeded

**Possible Causes:**
1. Too many manual actions
2. Polling interval too short
3. Too many optional features enabled
4. Multiple Home Assistant instances using same account

**Solution:**
1. Check `sensor.tado_ce_api_remaining` - how many calls left?
2. Increase polling intervals (day/night)
3. Disable optional features:
   - Weather Sensors (saves 1 call/sync)
   - Mobile Device Tracking (saves 1 call/full sync)
   - Smart Comfort Analytics
4. Wait for reset time (check `sensor.tado_ce_api_reset`)
5. Ensure only one HA instance is using the account

---

### Issue: Reset Time Incorrect

**Possible Causes:**
1. Not enough API call history
2. First time setup (no reset detected yet)
3. API call history cleared

**Solution:**
1. Wait 24-48 hours for reset time detection
2. Check `sensor.tado_ce_api_reset` attributes for detection method
3. Verify API call history is being recorded
4. Check HA logs for reset time calculation messages
5. Reset time will be more accurate after first detected reset

---

### Issue: Schedule Calendar Not Showing Events

**Possible Causes:**
1. Schedule Calendar not enabled
2. No schedules configured in Tado app
3. Calendar integration not loaded

**Solution:**
1. Enable "Enable Schedule Calendar" in configuration
2. Restart Home Assistant
3. Verify schedules exist in Tado app
4. Check HA logs for calendar entity creation
5. Verify calendar integration is working

---

### Issue: Boiler Flow Temperature Not Detected

**Possible Causes:**
1. Boiler is not OpenTherm-compatible
2. Tado system doesn't support OpenTherm
3. Boiler not connected properly

**Solution:**
1. Verify boiler supports OpenTherm
2. Check Tado app for boiler flow temperature
3. If not in Tado app, feature not available
4. Ensure Tado wiring is correct for OpenTherm
5. Contact Tado support if boiler should be supported

---

### Issue: Device Tracking Not Working

**Possible Causes:**
1. Mobile Device Tracking not enabled
2. Geo-tracking not enabled in Tado app
3. No mobile devices registered

**Solution:**
1. Enable "Enable Mobile Device Tracking" in configuration
2. Restart Home Assistant
3. Enable geo-tracking in Tado mobile app
4. Verify mobile devices appear in Tado app
5. Wait for next full sync (every 6 hours)

---

### Issue: Temperature Offset Not Applying

**Possible Causes:**
1. Temperature Offset Attribute not enabled
2. Offset value out of range (-10 to +10°C)
3. Service call failed

**Solution:**
1. Enable "Enable Temperature Offset Attribute" in configuration
2. Verify offset value is within range
3. Check HA logs for service call errors
4. Use `tado_ce.get_temperature_offset` to verify current offset
5. Wait a few minutes for offset to apply

---

### Issue: Preheat Advisor Shows 0 Minutes

**Possible Causes:**
1. Already at or above target temperature
2. Heating rate unknown (not enough data)
3. Next schedule temperature same as current
4. Smart Comfort Analytics not enabled

**Solution:**
1. Check current temperature vs next schedule temperature
2. Wait for thermal analytics to collect data (3-5 heating cycles)
3. Verify `_avg_heating_rate` sensor has valid value
4. Enable Smart Comfort Analytics if disabled
5. Check `_analysis_confidence` - should be >50%

---

## 📚 Related Documentation

- [ENTITIES.md](ENTITIES.md) - Complete entity list
- [README.md](README.md) - Installation and setup
- [API_REFERENCE.md](API_REFERENCE.md) - Technical API details
- [ROADMAP.md](ROADMAP.md) - Planned features and ideas

---

**Last Updated:** v2.0.0 (2026-02-08)
