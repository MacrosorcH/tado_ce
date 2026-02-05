# Design Document

## Overview

This design addresses the coordinator race condition in Tado CE that causes climate entities to flicker between states. The root cause is that the coordinator refresh reads stale zones.json data BEFORE API calls complete, causing optimistic state to be incorrectly reverted.

The solution implements a three-layer defense strategy:

1. **Entity Freshness Tracking** - Coordinator tracks which entities have recent API calls and skips updating them
2. **Sequence Number Tracking** - Entities reject stale data using monotonic sequence numbers
3. **Explicit State Confirmation** - Entities only clear optimistic state when API confirms the exact expected state

This approach ensures optimistic updates remain stable while maintaining responsiveness and supporting multiple simultaneous zone changes.

## Architecture

### Current Architecture (v1.9.7)

```
User Action → Entity.set_temperature()
              ├─> Set optimistic state (hvac_action=HEATING)
              └─> Call API (async, takes ~1s)
                  
Coordinator.refresh() [runs every 30s]
├─> Fetch zones.json from API
├─> Distribute data to all entities
└─> Entity.update(zones_data)
    └─> Overwrites optimistic state with stale data ❌
```

### New Architecture (v1.10.0)

```
User Action → Entity.set_temperature()
              ├─> Assign sequence_number = coordinator.next_seq()
              ├─> Set optimistic state with sequence_number
              ├─> Mark entity as fresh: coordinator.mark_fresh(entity_id)
              └─> Call API (async)
                  └─> On success: confirm state with sequence_number
                  └─> On failure: rollback optimistic state
                  
Coordinator.refresh() [runs every 30s]
├─> Fetch zones.json from API
├─> Increment global sequence_number
├─> For each entity:
    ├─> Check if entity is fresh (within 17s window)
    ├─> If fresh: skip update ✓
    └─> If not fresh: Entity.update(zones_data, sequence_number)
        └─> Entity checks: if incoming_seq > current_seq:
            └─> Apply update
            └─> Else: reject stale data ✓
```


## Components and Interfaces

### 1. TadoDataUpdateCoordinator (Modified)

The coordinator is enhanced to track entity freshness and assign sequence numbers.

**New Attributes:**
```python
class TadoDataUpdateCoordinator:
    _entity_freshness: dict[str, float]  # entity_id -> timestamp of last API call
    _global_sequence: int  # Monotonically increasing counter
    _freshness_lock: asyncio.Lock  # Protect concurrent access
```

**New Methods:**
```python
def mark_entity_fresh(self, entity_id: str) -> None:
    """Mark entity as having a recent API call in progress."""
    async with self._freshness_lock:
        self._entity_freshness[entity_id] = time.time()

def is_entity_fresh(self, entity_id: str, debounce_seconds: int = 17) -> bool:
    """Check if entity has a recent API call (within debounce window)."""
    if entity_id not in self._entity_freshness:
        return False
    
    elapsed = time.time() - self._entity_freshness[entity_id]
    if elapsed > debounce_seconds:
        del self._entity_freshness[entity_id]
        return False
    
    return True

def get_next_sequence(self) -> int:
    """Get next sequence number for tracking data freshness."""
    self._global_sequence += 1
    return self._global_sequence
```


### 2. TadoClimate (Modified)

The climate entity is enhanced to track optimistic state with sequence numbers.

**New Attributes:**
```python
class TadoClimate:
    _optimistic_state: dict | None  # Current optimistic state
    _optimistic_sequence: int | None  # Sequence number of optimistic state
    _expected_hvac_mode: str | None  # Expected mode after API call
    _expected_hvac_action: str | None  # Expected action after API call
```

**Modified set_temperature Method:**
```python
async def async_set_temperature(self, **kwargs) -> None:
    """Set new target temperature with optimistic update."""
    temperature = kwargs.get(ATTR_TEMPERATURE)
    
    # Get sequence number from coordinator
    sequence = self.coordinator.get_next_sequence()
    
    # Set optimistic state
    self._optimistic_state = {
        "target_temperature": temperature,
        "hvac_action": HVACAction.HEATING,
        "timestamp": time.time(),
    }
    self._optimistic_sequence = sequence
    self._expected_hvac_mode = self._attr_hvac_mode
    self._expected_hvac_action = HVACAction.HEATING
    
    # Mark entity as fresh in coordinator
    self.coordinator.mark_entity_fresh(self.entity_id)
    
    # Trigger UI update
    self.async_write_ha_state()
    
    try:
        # Call API
        await self.coordinator.api.set_temperature(self._zone_id, temperature)
        
    except Exception as ex:
        # API failure - rollback optimistic state immediately
        self._optimistic_state = None
        self._optimistic_sequence = None
        self._expected_hvac_mode = None
        self._expected_hvac_action = None
        self.async_write_ha_state()
        raise
```

**Modified coordinator_update Method:**
```python
def coordinator_update(self, zones_data: dict) -> None:
    """Handle coordinator data update with sequence checking."""
    incoming_seq = zones_data.get("_sequence", 0)
    
    # Check if we have optimistic state
    if self._optimistic_sequence is not None:
        # Reject stale data (lower sequence number)
        if incoming_seq <= self._optimistic_sequence:
            _LOGGER.debug(
                f"Rejecting stale data for {self.entity_id}: "
                f"incoming_seq={incoming_seq}, optimistic_seq={self._optimistic_sequence}"
            )
            return
        
        # Check if API confirmed our expected state
        zone_data = zones_data.get(self._zone_id, {})
        current_mode = self._get_hvac_mode_from_data(zone_data)
        current_action = self._get_hvac_action_from_data(zone_data)
        
        if (current_mode == self._expected_hvac_mode and 
            current_action == self._expected_hvac_action):
            # State confirmed - clear optimistic tracking
            self._optimistic_state = None
            self._optimistic_sequence = None
            self._expected_hvac_mode = None
            self._expected_hvac_action = None
        else:
            # State not yet confirmed - keep optimistic state
            _LOGGER.debug(
                f"State not confirmed for {self.entity_id}: "
                f"expected={self._expected_hvac_action}, got={current_action}"
            )
            return
    
    # Apply update normally
    self._update_from_data(zones_data)
    self.async_write_ha_state()
```


### 3. TadoACClimate (Modified)

The AC climate entity receives identical changes to TadoClimate to maintain parity.

**Critical:** All changes to TadoClimate MUST be replicated to TadoACClimate:
- Same optimistic state tracking attributes
- Same sequence number logic
- Same coordinator_update method
- Same API call patterns (but with AC-specific payloads)

**Differences from TadoClimate:**
- Expected hvac_action is COOLING instead of HEATING
- API payload uses AC-specific temperature format
- Mode mapping uses AC modes (COOL, FAN_ONLY, DRY, etc.)

## Data Models

### OptimisticState

Tracks the current optimistic state of a climate entity.

```python
@dataclass
class OptimisticState:
    """Represents optimistic state for a climate entity."""
    
    target_temperature: float | None
    hvac_mode: str | None
    hvac_action: str | None
    preset_mode: str | None
    timestamp: float  # Unix timestamp when state was set
    sequence: int  # Sequence number for freshness tracking
    
    def is_expired(self, debounce_seconds: int = 17) -> bool:
        """Check if optimistic state has expired."""
        return time.time() - self.timestamp > debounce_seconds
```

### EntityFreshnessTracker

Tracks which entities have recent API calls in progress.

```python
class EntityFreshnessTracker:
    """Tracks entity freshness for coordinator updates."""
    
    def __init__(self):
        self._freshness: dict[str, float] = {}
        self._lock = asyncio.Lock()
    
    async def mark_fresh(self, entity_id: str) -> None:
        """Mark entity as fresh (has recent API call)."""
        async with self._lock:
            self._freshness[entity_id] = time.time()
    
    def is_fresh(self, entity_id: str, window_seconds: int = 17) -> bool:
        """Check if entity is fresh (within debounce window)."""
        if entity_id not in self._freshness:
            return False
        
        elapsed = time.time() - self._freshness[entity_id]
        if elapsed > window_seconds:
            # Auto-cleanup expired entries
            del self._freshness[entity_id]
            return False
        
        return True
    
    def clear(self, entity_id: str) -> None:
        """Clear freshness marker for entity."""
        self._freshness.pop(entity_id, None)
    
    def clear_all(self) -> None:
        """Clear all freshness markers (e.g., on HA restart)."""
        self._freshness.clear()
```

### SequenceTracker

Manages monotonically increasing sequence numbers for data freshness.

```python
class SequenceTracker:
    """Tracks sequence numbers for data freshness."""
    
    def __init__(self):
        self._sequence = 0
        self._lock = asyncio.Lock()
    
    async def next(self) -> int:
        """Get next sequence number."""
        async with self._lock:
            self._sequence += 1
            return self._sequence
    
    @property
    def current(self) -> int:
        """Get current sequence number."""
        return self._sequence
```


## Correctness Properties

A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.

The following properties define the correctness criteria for the coordinator race condition fix. Each property is universally quantified and references the specific requirements it validates.

### Property 1: Optimistic State Persistence

*For any* climate entity and any temperature change, when the user sets a new temperature, the entity's hvac_action should remain HEATING (or COOLING for AC) for at least 15 seconds, regardless of coordinator refresh timing.

**Validates: Requirements 1.1**

### Property 2: Stale Data Rejection

*For any* climate entity with optimistic state, when the coordinator provides data with a sequence number less than or equal to the entity's optimistic sequence, the entity should reject the update and preserve its optimistic state.

**Validates: Requirements 1.2, 4.2**

### Property 3: State Confirmation Round-Trip

*For any* climate entity with optimistic state, when the coordinator provides data that exactly matches the expected hvac_mode and hvac_action, the entity should clear all optimistic state markers and accept the confirmed state.

**Validates: Requirements 1.3**

### Property 4: API Failure Rollback

*For any* climate entity with optimistic state, when an API call fails, the entity should immediately clear optimistic state and revert to the last confirmed state from the coordinator.

**Validates: Requirements 1.4**

### Property 5: Freshness Marking Invariant

*For any* entity that initiates an API call, immediately after the call is initiated, the coordinator should have that entity marked as fresh with a timestamp.

**Validates: Requirements 2.1**

### Property 6: Fresh Entity Update Protection

*For any* entity marked as fresh (within the 17-second debounce window), when the coordinator performs a refresh, the coordinator should skip calling that entity's update method.

**Validates: Requirements 2.2, 5.3**

### Property 7: Automatic Expiration and Cleanup

*For any* entity marked as fresh, when time advances beyond the debounce window (17 seconds), the coordinator should automatically remove the freshness marker and resume normal updates for that entity.

**Validates: Requirements 2.3, 6.3, 10.3**

### Property 8: Multi-Entity Independence

*For any* set of entities where some are marked fresh and others are not, when the coordinator performs a refresh, only the non-fresh entities should receive updates, and each entity's freshness should be tracked independently.

**Validates: Requirements 2.4, 5.1**

### Property 9: Sequence Monotonicity

*For any* sequence of API calls from a climate entity, each subsequent call should be assigned a sequence number strictly greater than the previous call's sequence number.

**Validates: Requirements 3.1**

### Property 10: Stale Sequence Rejection

*For any* climate entity with current sequence number N, when the coordinator provides data with sequence number M where M < N, the entity should reject the update and maintain its current state.

**Validates: Requirements 3.3**

### Property 11: Sequence Update on Success

*For any* climate entity that successfully completes an API call, the entity's sequence number should be updated to match the coordinator's current sequence number.

**Validates: Requirements 3.4**

### Property 12: Rapid Change Tracking

*For any* sequence of mode changes made within 1 second, the climate entity should track each change independently, and the final state should match the last change in the sequence.

**Validates: Requirements 4.1**

### Property 13: Out-of-Order Response Handling (Confluence)

*For any* set of API responses that arrive in different orders, the climate entity should apply only the response with the highest sequence number, ensuring the final state is independent of arrival order.

**Validates: Requirements 4.3**

### Property 14: Independent Zone Completion

*For any* set of zones where multiple zones have simultaneous API calls, when one zone's API call completes, the coordinator should resume updates for only that zone while other zones remain protected.

**Validates: Requirements 5.2**

### Property 15: Independent Zone Expiration

*For any* set of zones with different freshness timestamps, when a zone's debounce window expires, the coordinator should resume updates for only that zone without affecting other zones' freshness status.

**Validates: Requirements 5.4**

### Property 16: Retry State Persistence

*For any* climate entity that experiences API call failures and retries, the entity should maintain its optimistic state across all retry attempts until either final success or explicit rollback.

**Validates: Requirements 6.4**


## Error Handling

### API Call Failures

**Scenario:** API call fails during optimistic update

**Handling:**
1. Catch exception in async_set_temperature/async_set_hvac_mode
2. Immediately clear optimistic state markers (_optimistic_state, _optimistic_sequence, _expected_*)
3. Trigger async_write_ha_state() to revert UI to last confirmed state
4. Re-raise exception to notify Home Assistant of failure
5. Log error with entity_id and exception details

**Example:**
```python
try:
    await self.coordinator.api.set_temperature(self._zone_id, temperature)
except Exception as ex:
    _LOGGER.error(f"API call failed for {self.entity_id}: {ex}")
    self._optimistic_state = None
    self._optimistic_sequence = None
    self._expected_hvac_mode = None
    self._expected_hvac_action = None
    self.async_write_ha_state()
    raise
```

### Coordinator Refresh Failures

**Scenario:** Coordinator fails to fetch zones.json from API

**Handling:**
1. Coordinator's _async_update_data raises UpdateFailed exception
2. Home Assistant's DataUpdateCoordinator handles retry logic automatically
3. Entities retain their last known state (no update called)
4. Freshness markers remain active (entities stay protected)
5. Next successful refresh will resume normal operation

**No special handling needed** - Home Assistant's coordinator framework handles this.

### Sequence Number Overflow

**Scenario:** Global sequence number approaches integer overflow (extremely rare)

**Handling:**
1. Python integers have unlimited precision - no overflow possible
2. If memory becomes concern (after billions of operations), reset sequence to 0
3. All entities' optimistic sequences will be cleared on next coordinator refresh
4. System recovers automatically within one refresh cycle (30s)

**Mitigation:** Not needed in practice, but could add sequence reset on HA restart if desired.

### Stale Freshness Markers

**Scenario:** Entity marked fresh but never receives coordinator update (e.g., coordinator stopped)

**Handling:**
1. Freshness markers auto-expire after 17 seconds
2. is_entity_fresh() automatically removes expired markers
3. Entity will accept next coordinator update after expiration
4. No manual cleanup needed

**Built-in protection** - time-based expiration prevents stale markers.

### Race Condition: Multiple Simultaneous API Calls

**Scenario:** User rapidly clicks temperature up/down, triggering multiple API calls

**Handling:**
1. Each API call gets independent sequence number
2. Each call updates optimistic state with new sequence
3. Coordinator updates are rejected if sequence < current optimistic sequence
4. Only the highest sequence (most recent change) is preserved
5. API responses arriving out-of-order are handled by sequence comparison

**Example:**
```python
# User clicks: 20°C → 21°C → 22°C (within 1 second)
# Sequence: 100 → 101 → 102
# Optimistic state tracks: seq=102, temp=22°C
# API response for seq=100 arrives → rejected (100 < 102)
# API response for seq=101 arrives → rejected (101 < 102)
# API response for seq=102 arrives → accepted (matches expected state)
```

### Home Assistant Restart During Optimistic Window

**Scenario:** HA restarts while entity has optimistic state active

**Handling:**
1. Entity __init__ does not restore optimistic state (not persisted)
2. First coordinator refresh after restart provides API truth
3. Entity accepts data (no optimistic sequence to compare against)
4. System recovers to correct state within one refresh cycle

**No persistence needed** - optimistic state is intentionally transient.


## Testing Strategy

### Dual Testing Approach

This feature requires both unit tests and property-based tests to ensure comprehensive coverage:

- **Unit tests**: Verify specific examples, edge cases, and integration points
- **Property tests**: Verify universal properties across all inputs

Both are complementary and necessary. Unit tests catch concrete bugs in specific scenarios, while property tests verify general correctness across the input space.

### Property-Based Testing Configuration

**Library:** Use `hypothesis` for Python property-based testing

**Configuration:**
- Minimum 100 iterations per property test (due to randomization)
- Each property test must reference its design document property
- Tag format: `# Feature: fix-coordinator-race-condition, Property {number}: {property_text}`

**Example:**
```python
from hypothesis import given, strategies as st

# Feature: fix-coordinator-race-condition, Property 2: Stale Data Rejection
@given(
    optimistic_seq=st.integers(min_value=1, max_value=1000),
    incoming_seq=st.integers(min_value=1, max_value=1000)
)
@settings(max_examples=100)
def test_stale_data_rejection_property(optimistic_seq, incoming_seq):
    """For any entity with optimistic state, incoming data with lower sequence should be rejected."""
    assume(incoming_seq <= optimistic_seq)  # Only test stale data case
    
    entity = create_test_entity()
    entity._optimistic_sequence = optimistic_seq
    entity._optimistic_state = {"hvac_action": "heating"}
    
    # Simulate coordinator update with stale data
    zones_data = {"_sequence": incoming_seq, "heating_power": 0}
    entity.coordinator_update(zones_data)
    
    # Verify optimistic state preserved
    assert entity._optimistic_sequence == optimistic_seq
    assert entity._optimistic_state is not None
    assert entity.hvac_action == "heating"
```

### Unit Test Coverage

**Core Scenarios:**
1. Basic optimistic update (set temperature → hvac_action=HEATING)
2. Coordinator refresh with stale data (heating_power=0) → state preserved
3. Coordinator refresh with fresh data (heating_power>0) → state confirmed
4. API failure → rollback to previous state
5. Rapid mode changes (HEAT → OFF → AUTO) → last change wins
6. Multiple zones simultaneous changes → independent tracking
7. HA restart during optimistic window → graceful recovery
8. Debounce window expiration → freshness cleared

**Edge Cases:**
1. OFF mode transition (immediate confirmation, no waiting)
2. Sequence number at boundary values (0, 1, MAX_INT)
3. Empty zones_data from coordinator
4. Entity not in zones_data (zone deleted)
5. Coordinator refresh during API call (race condition)

**Integration Points:**
1. Coordinator ↔ Entity communication
2. Entity ↔ API communication
3. Freshness tracker ↔ Coordinator
4. Sequence tracker ↔ Coordinator

### Property Test Coverage

Each correctness property from the design document should have a corresponding property-based test:

1. **Property 1**: Optimistic state persists for 15s regardless of coordinator timing
2. **Property 2**: Stale data (lower sequence) is always rejected
3. **Property 3**: State confirmation clears optimistic markers
4. **Property 4**: API failure always triggers rollback
5. **Property 5**: API call always marks entity fresh
6. **Property 6**: Fresh entities always skip updates
7. **Property 7**: Expiration always clears freshness after 17s
8. **Property 8**: Multi-entity freshness is independent
9. **Property 9**: Sequence numbers are monotonically increasing
10. **Property 10**: Lower sequence numbers are always rejected
11. **Property 11**: Successful API calls update sequence
12. **Property 12**: Rapid changes preserve last change
13. **Property 13**: Out-of-order responses use highest sequence
14. **Property 14**: Zone completion is independent
15. **Property 15**: Zone expiration is independent
16. **Property 16**: Retries preserve optimistic state

### Live Functional Tests

**Location:** `DEV/tests/integration/tests/test_live_functional.py`

**New Test Class:**
```python
class TestCoordinatorRaceCondition(unittest.TestCase):
    """Test coordinator race condition fix with live HA instance."""
    
    @async_test
    @skip_if_no_credentials
    async def test_optimistic_update_no_flicker(self):
        """Verify hvac_action doesn't flicker when setting temperature."""
        async with HAClient(self.config) as client:
            # Get first climate entity
            climate_entities = await client.get_climate_entities()
            entity_id = climate_entities[0]["entity_id"]
            
            # Get initial state
            initial_state = await client.get_state(entity_id)
            initial_temp = float(initial_state["attributes"]["temperature"])
            
            # Set new temperature
            new_temp = initial_temp + 1.0
            await client.call_service(
                "climate", "set_temperature",
                {"entity_id": entity_id, "temperature": new_temp}
            )
            
            # Poll hvac_action for 17 seconds
            for i in range(17):
                await asyncio.sleep(1)
                state = await client.get_state(entity_id)
                hvac_action = state["attributes"]["hvac_action"]
                
                # Should remain "heating" for at least 15 seconds
                if i < 15:
                    self.assertEqual(hvac_action, "heating",
                        f"hvac_action flickered to {hvac_action} at {i}s")
            
            # Restore original temperature
            await client.call_service(
                "climate", "set_temperature",
                {"entity_id": entity_id, "temperature": initial_temp}
            )
    
    @async_test
    @skip_if_no_credentials
    async def test_rapid_mode_changes(self):
        """Verify rapid mode changes don't cause flickering."""
        async with HAClient(self.config) as client:
            climate_entities = await client.get_climate_entities()
            entity_id = climate_entities[0]["entity_id"]
            
            # Get initial mode
            initial_state = await client.get_state(entity_id)
            initial_mode = initial_state["state"]
            
            try:
                # Rapid mode changes: HEAT → OFF → AUTO
                await client.call_service(
                    "climate", "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "heat"}
                )
                await asyncio.sleep(0.5)
                
                await client.call_service(
                    "climate", "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "off"}
                )
                await asyncio.sleep(0.5)
                
                await client.call_service(
                    "climate", "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "auto"}
                )
                
                # Wait for state to settle
                await asyncio.sleep(2)
                
                # Verify final state is AUTO
                final_state = await client.get_state(entity_id)
                self.assertEqual(final_state["state"], "auto",
                    "Final mode should be AUTO after rapid changes")
                
            finally:
                # Restore original mode
                await client.call_service(
                    "climate", "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": initial_mode}
                )
```

### Test Execution

**Unit Tests:**
```bash
python3 -m pytest custom_components/tado_ce/tests/ -v
```

**Property Tests:**
```bash
python3 -m pytest custom_components/tado_ce/tests/test_properties.py -v --hypothesis-show-statistics
```

**Live Functional Tests:**
```bash
python3 -m pytest DEV/tests/integration/tests/test_live_functional.py::TestCoordinatorRaceCondition -v
```

### Coverage Goals

- Unit test coverage: > 90% for modified files
- Property test coverage: 100% of correctness properties
- Live functional test coverage: Core race condition scenarios
- Integration test coverage: All entity-coordinator interactions

