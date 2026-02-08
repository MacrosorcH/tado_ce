"""Storage for heating cycle data with multi-home support."""
import json
import logging
from datetime import datetime, timedelta, timezone

import aiofiles
import aiofiles.os

from .heating_cycle_models import HeatingCycle

_LOGGER = logging.getLogger(__name__)


class HeatingCycleStorage:
    """Persist heating cycles to disk with multi-home support and atomic writes."""
    
    def __init__(self, hass, home_id: str):
        """Initialize storage with home ID."""
        self._hass = hass
        self._home_id = home_id
        self._storage_path = hass.config.path(
            f".storage/tado_ce/heating_cycle_history_{home_id}.json"
        )
        self._data: dict = {"version": "1.0", "zones": {}}
        
    async def async_load(self) -> None:
        """Load cycle data from disk with migration support."""
        try:
            # Try new path first (with home_id)
            path_exists = await aiofiles.os.path.exists(self._storage_path)
            if path_exists:
                async with aiofiles.open(self._storage_path, 'r') as f:
                    content = await f.read()
                    loaded_data = json.loads(content)
                    self._data = self._migrate_data_format(loaded_data)
                    _LOGGER.debug(
                        "Loaded heating cycle history for home %s: %d zones",
                        self._home_id,
                        len(self._data.get("zones", {}))
                    )
            else:
                # Try legacy path (without home_id) for migration
                legacy_path = self._hass.config.path(
                    ".storage/tado_ce/heating_cycle_history.json"
                )
                legacy_exists = await aiofiles.os.path.exists(legacy_path)
                if legacy_exists:
                    _LOGGER.info(
                        "Migrating heating cycle history from legacy path: %s",
                        legacy_path
                    )
                    async with aiofiles.open(legacy_path, 'r') as f:
                        content = await f.read()
                        loaded_data = json.loads(content)
                        self._data = self._migrate_data_format(loaded_data)
                        # Save to new path
                        await self._save_to_disk()
                        _LOGGER.info(
                            "Migrated %d zones to new storage path",
                            len(self._data.get("zones", {}))
                        )
                else:
                    _LOGGER.debug("No existing heating cycle history found")
                    
        except json.JSONDecodeError as e:
            _LOGGER.error("Corrupted heating cycle storage file: %s", e)
            # Rename corrupted file
            corrupted_path = f"{self._storage_path}.corrupted"
            try:
                await aiofiles.os.rename(self._storage_path, corrupted_path)
                _LOGGER.info("Renamed corrupted file to %s", corrupted_path)
            except FileNotFoundError:
                pass
            self._data = {"version": "1.0", "zones": {}}
        except Exception as e:
            _LOGGER.error("Failed to load heating cycle storage: %s", e)
            self._data = {"version": "1.0", "zones": {}}
    
    def _migrate_data_format(self, loaded_data: dict) -> dict:
        """Migrate old data format to new format.
        
        Old format: {"zone_id": [cycles], ...}
        New format: {"version": "1.0", "zones": {"zone_id": {"cycles": [...]}, ...}}
        """
        # Check if already new format
        if "version" in loaded_data and "zones" in loaded_data:
            return loaded_data
        
        # Migrate old format
        _LOGGER.info("Migrating heating cycle data from old format")
        new_data = {"version": "1.0", "zones": {}}
        
        for zone_id, cycles in loaded_data.items():
            if isinstance(cycles, list):
                new_data["zones"][zone_id] = {"cycles": cycles}
                _LOGGER.debug(
                    "Migrated zone %s with %d cycles",
                    zone_id, len(cycles)
                )
        
        return new_data
    
    async def save_cycle(self, zone_id: str, cycle: HeatingCycle) -> None:
        """Save completed cycle for a zone."""
        if zone_id not in self._data["zones"]:
            self._data["zones"][zone_id] = {"cycles": []}
        
        self._data["zones"][zone_id]["cycles"].append(cycle.to_dict())
        
        _LOGGER.debug(
            "Saved cycle for zone %s: %s -> %s (completed=%s, interrupted=%s)",
            zone_id,
            cycle.start_time.isoformat(),
            cycle.end_time.isoformat() if cycle.end_time else "active",
            cycle.completed,
            cycle.interrupted
        )
        
        # Cleanup old cycles (keep 2x rolling window)
        await self._cleanup_old_cycles(zone_id)
        
        # Save to disk (atomic write)
        await self._save_to_disk()
    
    async def get_cycles(
        self, zone_id: str, window_days: int = 7
    ) -> list[HeatingCycle]:
        """Get cycles for a zone within rolling window."""
        if zone_id not in self._data["zones"]:
            return []
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        cycles = []
        
        for cycle_dict in self._data["zones"][zone_id]["cycles"]:
            cycle = HeatingCycle.from_dict(cycle_dict)
            # Only include completed, non-interrupted cycles within window
            if cycle.start_time >= cutoff and cycle.completed and not cycle.interrupted:
                cycles.append(cycle)
        
        return cycles
    
    async def get_active_cycles(self) -> dict[str, HeatingCycle]:
        """Get all active cycles (for resume after restart)."""
        active = {}
        for zone_id, zone_data in self._data["zones"].items():
            for cycle_dict in zone_data["cycles"]:
                cycle = HeatingCycle.from_dict(cycle_dict)
                if not cycle.completed and not cycle.interrupted:
                    active[zone_id] = cycle
                    break  # Only one active cycle per zone
        
        if active:
            _LOGGER.info("Found %d active cycles to resume", len(active))
        
        return active
    
    async def get_all_zone_ids(self) -> list[str]:
        """Get all zone IDs with stored cycle data."""
        return list(self._data["zones"].keys())
    
    async def _cleanup_old_cycles(self, zone_id: str) -> None:
        """Remove cycles older than 2x rolling window."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)  # 2x default window
        
        cycles = self._data["zones"][zone_id]["cycles"]
        original_count = len(cycles)
        
        self._data["zones"][zone_id]["cycles"] = [
            c for c in cycles
            if datetime.fromisoformat(c["start_time"]) >= cutoff
        ]
        
        removed_count = original_count - len(self._data["zones"][zone_id]["cycles"])
        if removed_count > 0:
            _LOGGER.debug(
                "Cleaned up %d old cycles for zone %s",
                removed_count,
                zone_id
            )
    
    async def _save_to_disk(self) -> None:
        """Save cycle data to disk with atomic write."""
        import os
        try:
            # Ensure directory exists (async)
            await aiofiles.os.makedirs(
                os.path.dirname(self._storage_path), exist_ok=True
            )
            
            # Write to temp file
            temp_path = f"{self._storage_path}.tmp"
            async with aiofiles.open(temp_path, 'w') as f:
                await f.write(json.dumps(self._data, indent=2))
            
            # Atomic move
            await aiofiles.os.replace(temp_path, self._storage_path)
            
            _LOGGER.debug("Saved heating cycle history to %s", self._storage_path)
        except Exception as e:
            _LOGGER.error("Failed to save heating cycle history: %s", e)
