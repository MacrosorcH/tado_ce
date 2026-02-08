#!/usr/bin/env python3
import json

# Read entity registry
with open('/config/.storage/core.entity_registry', 'r') as f:
    data = json.load(f)

# Find new API monitoring sensors
target_sensors = [
    'sensor.tado_ce_next_sync',
    'sensor.tado_ce_polling_interval',
    'sensor.tado_ce_call_history',
    'sensor.tado_ce_api_call_breakdown'
]

print("Checking for API Monitoring sensors:")
print("-" * 60)

for target in target_sensors:
    found = False
    for entity in data.get('data', {}).get('entities', []):
        if entity.get('entity_id') == target:
            print(f"✓ {target}")
            print(f"  Platform: {entity.get('platform')}")
            print(f"  Unique ID: {entity.get('unique_id')}")
            print(f"  Disabled: {entity.get('disabled_by')}")
            found = True
            break
    
    if not found:
        print(f"✗ {target} - NOT FOUND")

print("-" * 60)
