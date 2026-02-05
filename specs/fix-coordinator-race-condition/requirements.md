# Requirements Document

## Introduction

This specification addresses Issue #44 - a critical race condition in the Tado CE Home Assistant integration that causes climate entities to flicker between states when users change temperature or mode settings. After three failed releases (v1.9.5, v1.9.6, v1.9.7), the root cause has been identified: the coordinator refresh reads stale data from zones.json BEFORE the API call completes, causing optimistic state to be incorrectly reverted.

The solution requires implementing coordinator-aware optimistic updates that prevent stale data from overwriting fresh entity state, while maintaining responsiveness and supporting multiple simultaneous zone changes.

## Glossary

- **Coordinator**: The Home Assistant component that periodically fetches data from the Tado API and distributes it to all entities
- **Optimistic_Update**: Setting entity state immediately before API confirmation, providing instant UI feedback
- **Zones_Json**: The cached API response file containing zone state data (temperature, heating_power, etc.)
- **Hvac_Action**: The current heating/cooling activity state (HEATING, COOLING, IDLE, OFF)
- **Hvac_Mode**: The thermostat operating mode (HEAT, COOL, AUTO, OFF)
- **Heating_Power**: Percentage value (0-100) indicating boiler output level
- **Debounce_Window**: Time period (15s + 2s buffer) during which optimistic state is protected from coordinator updates
- **Sequence_Number**: Monotonically increasing counter to track data freshness and prevent stale updates
- **Entity_Freshness**: Tracking mechanism to identify which entities have recent API calls in progress
- **TadoClimate**: The climate entity class for heating zones
- **TadoACClimate**: The climate entity class for air conditioning zones
- **Stale_Data**: API response data that was fetched before a recent entity state change

## Requirements

### Requirement 1: Optimistic State Protection

**User Story:** As a user, when I change the temperature or mode on my thermostat, I want the UI to respond immediately and maintain that state without flickering back to the old state, so that I have confidence my command was received.

#### Acceptance Criteria

1. WHEN a user sets a new target temperature, THE Climate_Entity SHALL immediately set hvac_action to HEATING (or COOLING for AC) and maintain this state for at least 15 seconds
2. WHEN the Coordinator refreshes with stale Zones_Json data (heating_power=0), THE Climate_Entity SHALL NOT revert the optimistic hvac_action state
3. WHEN the Coordinator refreshes with fresh data confirming the state change, THE Climate_Entity SHALL clear the optimistic state and use the API-confirmed state
4. IF an API call fails, THEN THE Climate_Entity SHALL immediately rollback the optimistic state to the previous confirmed state

### Requirement 2: Coordinator-Aware Data Freshness

**User Story:** As a developer, I want the coordinator to know which entities have recent API calls in progress, so that it doesn't overwrite their optimistic state with stale cached data.

#### Acceptance Criteria

1. WHEN an entity initiates an API call, THE Coordinator SHALL mark that entity as "fresh" with a timestamp
2. WHILE an entity is marked as fresh (within Debounce_Window), THE Coordinator SHALL skip updating that entity's state from Zones_Json
3. WHEN the Debounce_Window expires (17 seconds after API call), THE Coordinator SHALL automatically clear the freshness marker and resume normal updates
4. WHEN multiple entities have simultaneous API calls, THE Coordinator SHALL track freshness independently for each entity

### Requirement 3: Sequence-Based Stale Data Prevention

**User Story:** As a developer, I want a fallback mechanism to prevent stale data from overwriting fresh state, so that the system remains robust even if timing-based protection fails.

#### Acceptance Criteria

1. WHEN an entity initiates an API call, THE Climate_Entity SHALL assign a monotonically increasing Sequence_Number to that operation
2. WHEN the Coordinator provides updated data to an entity, THE Climate_Entity SHALL compare the data's Sequence_Number with its current state's Sequence_Number
3. IF the incoming data has a lower Sequence_Number than the current state, THEN THE Climate_Entity SHALL reject the update and keep the current state
4. WHEN an API call completes successfully, THE Climate_Entity SHALL update its Sequence_Number to match the confirmed state

### Requirement 4: Rapid Mode Change Handling

**User Story:** As a user, when I rapidly change modes (e.g., HEAT → OFF → AUTO within 2 seconds), I want each change to be tracked independently without the UI flickering between old and new states.

#### Acceptance Criteria

1. WHEN a user makes multiple mode changes within 1 second, THE Climate_Entity SHALL track each change with independent optimistic state
2. WHEN the Coordinator refreshes during rapid mode changes, THE Climate_Entity SHALL preserve the most recent user-initiated state
3. WHEN API responses arrive out of order, THE Climate_Entity SHALL use Sequence_Number to apply only the most recent confirmed state
4. WHEN a user changes from HEAT to OFF, THE Climate_Entity SHALL immediately confirm the OFF state without waiting for API response (heating_power=0 is expected)

### Requirement 5: Multi-Zone Independence

**User Story:** As a user with multiple zones, when I change settings in multiple zones simultaneously, I want each zone to respond independently without interfering with each other.

#### Acceptance Criteria

1. WHEN multiple zones have simultaneous API calls, THE Coordinator SHALL track Entity_Freshness independently for each zone
2. WHEN one zone's API call completes, THE Coordinator SHALL resume updates for that zone while other zones remain protected
3. WHEN the Coordinator refreshes, THE Coordinator SHALL update only zones that are not marked as fresh
4. WHEN a zone's Debounce_Window expires, THE Coordinator SHALL resume updates for that zone without affecting other zones

### Requirement 6: State Recovery and Persistence

**User Story:** As a user, when Home Assistant restarts while my thermostat is in an optimistic state, I want the system to recover gracefully without causing incorrect state or flickering.

#### Acceptance Criteria

1. WHEN Home Assistant restarts during an optimistic update window, THE Climate_Entity SHALL clear all optimistic state markers on initialization
2. WHEN the Coordinator performs its first refresh after restart, THE Climate_Entity SHALL accept the API data as the source of truth
3. WHEN an entity's Debounce_Window expires, THE Climate_Entity SHALL automatically clear optimistic state and accept the next Coordinator update
4. WHEN an API call fails and is retried, THE Climate_Entity SHALL maintain optimistic state until either success or explicit rollback

### Requirement 7: Heating vs AC Parity

**User Story:** As a developer, I want all optimistic update logic to work identically for both heating zones (TadoClimate) and AC zones (TadoACClimate), so that users have consistent behavior regardless of zone type.

#### Acceptance Criteria

1. WHEN optimistic state protection is implemented in TadoClimate, THE same logic SHALL be implemented in TadoACClimate
2. WHEN coordinator freshness tracking is added, THE Coordinator SHALL track both heating and AC zones using the same mechanism
3. WHEN sequence number tracking is implemented, THE TadoACClimate SHALL use the same Sequence_Number logic as TadoClimate
4. WHEN testing is performed, THE test suite SHALL include test cases for both heating and AC zones

### Requirement 8: Integration Testing Requirements

**User Story:** As a developer, I want comprehensive integration tests that catch race conditions before release, so that we don't ship broken versions to users.

#### Acceptance Criteria

1. WHEN integration tests run, THE test suite SHALL include a test that simulates coordinator refresh with stale data during optimistic update
2. WHEN integration tests run, THE test suite SHALL include a test that simulates rapid mode changes (< 1s between changes)
3. WHEN integration tests run, THE test suite SHALL include a test that simulates multiple zones changing simultaneously
4. WHEN integration tests run, THE test suite SHALL include a test that simulates HA restart during optimistic window
5. WHEN integration tests run, THE test suite SHALL include property-based tests that verify state transition consistency across random inputs

### Requirement 9: Backwards Compatibility

**User Story:** As a user upgrading from v1.9.7, I want the new version to work with my existing automations and not require any configuration changes.

#### Acceptance Criteria

1. WHEN upgrading from v1.9.7, THE Climate_Entity SHALL maintain the same entity_id and attributes
2. WHEN existing automations trigger, THE Climate_Entity SHALL respond to service calls with the same behavior as before (but without flickering)
3. WHEN the Coordinator refreshes, THE system SHALL not increase the total number of API calls compared to v1.9.7
4. WHEN users have custom templates reading hvac_action, THE attribute SHALL update correctly without breaking existing templates

### Requirement 10: Performance and Resource Constraints

**User Story:** As a system administrator, I want the race condition fix to have minimal performance impact on Home Assistant, so that it doesn't slow down my system.

#### Acceptance Criteria

1. WHEN tracking Entity_Freshness, THE Coordinator SHALL use in-memory data structures with O(1) lookup time
2. WHEN storing Sequence_Number, THE Climate_Entity SHALL use a simple integer counter without persistent storage
3. WHEN the Debounce_Window expires, THE Coordinator SHALL automatically clean up freshness markers without manual intervention
4. WHEN multiple zones are active, THE memory overhead SHALL be less than 1KB per zone for tracking data
