#!/usr/bin/env python3
import json

# Read entity registry
with open('/config/.storage/core.entity_registry', 'r') as f:
    data = json.load(f)

# Find all tado_ce sensors
tado_sensors = []
for entity in data.get('data', {}).get('entities', []):
    entity_id = entity.get('entity_id', '')
    if entity_id.startswith('sensor.tado_ce'):
        tado_sensors.append({
            'entity_id': entity_id,
            'unique_id': entity.get('unique_id'),
            'disabled': entity.get('disabled_by')
        })

# Sort by entity_id
tado_sensors.sort(key=lambda x: x['entity_id'])

print(f"Found {len(tado_sensors)} Tado CE sensors:")
for sensor in tado_sensors:
    status = "DISABLED" if sensor['disabled'] else "ENABLED"
    print(f"  [{status}] {sensor['entity_id']}")

# Check for breakdown sensor specifically
breakdown = [s for s in tado_sensors if 'breakdown' in s['entity_id']]
if breakdown:
    print(f"\n✓ Breakdown sensor found: {breakdown[0]['entity_id']}")
else:
    print("\n✗ Breakdown sensor NOT found")
