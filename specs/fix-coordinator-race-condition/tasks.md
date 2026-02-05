# Implementation Plan: Fix Coordinator Race Condition

## Overview

This implementation plan addresses Issue #44 - the coordinator race condition that causes climate entities to flicker between states. The solution implements a three-layer defense strategy: entity freshness tracking, sequence number tracking, and explicit state confirmation.

## Tasks

- [x] 1. Add coordinator freshness tracking infrastructure
  - Add `_entity_freshness` dict, `_global_sequence` counter, and `_freshness_lock` to TadoDataUpdateCoordinator
  - Implement `mark_entity_fresh()`, `is_entity_fresh()`, and `get_next_sequence()` methods
  - Modify `_async_update_data()` to attach sequence numbers to zones data
  - Modify coordinator update distribution to skip fresh entities
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1_

- [-] 2. Implement optimistic state tracking in TadoClimate
  - [x] 2.1 Add optimistic state attributes to TadoClimate
    - Add `_optimistic_state`, `_optimistic_sequence`, `_expected_hvac_mode`, `_expected_hvac_action` attributes
    - _Requirements: 1.1, 1.2_
  
  - [x] 2.2 Modify async_set_temperature with optimistic updates
    - Get sequence number from coordinator
    - Set optimistic state with sequence number
    - Mark entity as fresh in coordinator
    - Add try/except for API failure rollback
    - _Requirements: 1.1, 1.4_
  
  - [x] 2.3 Modify async_set_hvac_mode with optimistic updates
    - Same pattern as set_temperature
    - Handle OFF mode special case (immediate confirmation)
    - _Requirements: 4.1, 4.4_
  
  - [x] 2.4 Implement coordinator_update with sequence checking
    - Check incoming sequence vs optimistic sequence
    - Reject stale data (lower sequence)
    - Check for state confirmation (expected vs actual)
    - Clear optimistic state on confirmation
    - _Requirements: 1.2, 1.3, 3.3, 3.4_
  
  - [ ] 2.5 Write property test for optimistic state persistence
    - **Property 1: Optimistic State Persistence**
    - **Validates: Requirements 1.1**
  
  - [ ] 2.6 Write property test for stale data rejection
    - **Property 2: Stale Data Rejection**
    - **Validates: Requirements 1.2, 4.2**
  
  - [ ] 2.7 Write property test for state confirmation round-trip
    - **Property 3: State Confirmation Round-Trip**
    - **Validates: Requirements 1.3**
  
  - [ ] 2.8 Write property test for API failure rollback
    - **Property 4: API Failure Rollback**
    - **Validates: Requirements 1.4**

- [ ] 3. Replicate all changes to TadoACClimate (AC parity)
  - [ ] 3.1 Add same optimistic state attributes to TadoACClimate
    - Copy all attributes from TadoClimate
    - _Requirements: 7.1, 7.3_
  
  - [ ] 3.2 Modify async_set_temperature in TadoACClimate
    - Use COOLING instead of HEATING for expected action
    - Same sequence and freshness logic
    - _Requirements: 7.1_
  
  - [ ] 3.3 Modify async_set_hvac_mode in TadoACClimate
    - Handle AC-specific modes (COOL, FAN_ONLY, DRY)
    - Same optimistic update pattern
    - _Requirements: 7.1_
  
  - [ ] 3.4 Implement coordinator_update in TadoACClimate
    - Identical logic to TadoClimate
    - _Requirements: 7.1, 7.3_
  
  - [ ] 3.5 Write unit tests for TadoACClimate
    - Test AC-specific modes and actions
    - _Requirements: 7.4_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Add coordinator property tests
  - [ ] 5.1 Write property test for freshness marking
    - **Property 5: Freshness Marking Invariant**
    - **Validates: Requirements 2.1**
  
  - [ ] 5.2 Write property test for fresh entity update protection
    - **Property 6: Fresh Entity Update Protection**
    - **Validates: Requirements 2.2, 5.3**
  
  - [ ] 5.3 Write property test for automatic expiration
    - **Property 7: Automatic Expiration and Cleanup**
    - **Validates: Requirements 2.3, 6.3, 10.3**
  
  - [ ] 5.4 Write property test for multi-entity independence
    - **Property 8: Multi-Entity Independence**
    - **Validates: Requirements 2.4, 5.1**

- [ ] 6. Add sequence number property tests
  - [ ] 6.1 Write property test for sequence monotonicity
    - **Property 9: Sequence Monotonicity**
    - **Validates: Requirements 3.1**
  
  - [ ] 6.2 Write property test for stale sequence rejection
    - **Property 10: Stale Sequence Rejection**
    - **Validates: Requirements 3.3**
  
  - [ ] 6.3 Write property test for sequence update on success
    - **Property 11: Sequence Update on Success**
    - **Validates: Requirements 3.4**

- [ ] 7. Add rapid change and multi-zone property tests
  - [ ] 7.1 Write property test for rapid change tracking
    - **Property 12: Rapid Change Tracking**
    - **Validates: Requirements 4.1**
  
  - [ ] 7.2 Write property test for out-of-order response handling
    - **Property 13: Out-of-Order Response Handling**
    - **Validates: Requirements 4.3**
  
  - [ ] 7.3 Write property test for independent zone completion
    - **Property 14: Independent Zone Completion**
    - **Validates: Requirements 5.2**
  
  - [ ] 7.4 Write property test for independent zone expiration
    - **Property 15: Independent Zone Expiration**
    - **Validates: Requirements 5.4**
  
  - [ ] 7.5 Write property test for retry state persistence
    - **Property 16: Retry State Persistence**
    - **Validates: Requirements 6.4**

- [ ] 8. Add live functional tests
  - [ ] 8.1 Write live test for optimistic update without flicker
    - Test that hvac_action remains HEATING for 15+ seconds
    - Poll state every second for 17 seconds
    - _Requirements: 1.1, 1.2_
  
  - [ ] 8.2 Write live test for rapid mode changes
    - Test HEAT → OFF → AUTO within 2 seconds
    - Verify final state is AUTO
    - _Requirements: 4.1, 4.2_
  
  - [ ] 8.3 Write live test for multiple zones simultaneous changes
    - Change temperature in 2+ zones simultaneously
    - Verify each zone maintains independent state
    - _Requirements: 5.1, 5.2_

- [ ] 9. Add unit tests for edge cases
  - [ ] 9.1 Write unit test for OFF mode immediate confirmation
    - Test that OFF mode doesn't wait for API response
    - _Requirements: 4.4_
  
  - [ ] 9.2 Write unit test for HA restart during optimistic window
    - Test that entity clears optimistic state on init
    - _Requirements: 6.1, 6.2_
  
  - [ ] 9.3 Write unit test for backwards compatibility
    - Test that entity_id and attributes unchanged
    - Test that service calls work the same
    - _Requirements: 9.1, 9.2, 9.4_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (minimum 100 iterations each)
- Unit tests validate specific examples and edge cases
- Live functional tests validate real-world behavior with actual HA instance
- **CRITICAL**: All changes to TadoClimate MUST be replicated to TadoACClimate (heating/AC parity)
