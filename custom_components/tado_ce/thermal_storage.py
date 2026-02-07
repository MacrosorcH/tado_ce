"""Unified storage for thermal analytics data.

Combines smart_comfort_cache and heating_cycle_history into a single storage system.
Handles migration from old formats automatically.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any

import aiofiles
import aiofiles.os

from .heating_cycle_models import HeatingCycle, TemperatureReading

_LOGGER = logging.getLogger(__name__)

# Storage version for migration tracking
STORAGE_VERSION = "2.0"


class ThermalStorage:
    """Unified storage for thermal analytics data.
    
    New format (v2.0):
    {
        "version": "2.0",
        "saved_at": "2026-02-07T12:00:00",
        "history_days": 30,
        "zones": {
            "1": {
                "zone_id": 1,
                "zone_name": "Dining",
                "temperature_history": [...],
                "heating_cycles": [...]
            }
        }
    }
    """
    
    def __init__(self, hass, home_id: str, history_days: int = 30):
        """Initialize storage."""
        self._hass = hass
        self._home_id = home_id
        self._history_days = history_days
        self._storage_path = Path(hass.config.path(
            f".storage/tado_ce/thermal_analytics_cache_{home_id}.json"
        ))
        self._data: dict = {
            "version": STORAGE_VERSION,
            "saved_at": None,
            "history_days": history_days,
            "zones": {}
        }
        self._dirty = False
        self._last_save_time: Optional[datetime] = None
    
    @property
    def zones(self) -> dict:
        """Get zones data."""
        return self._data.get("zones", {})
    
    async def async_load(self) -> int:
        """Load data from disk with automatic migration.
        
        Returns:
            Number of temperature readings loaded
        """
        total_readings = 0
        
        # Try new format first
        if self._storage_path.exists():
            total_readings = await self._load_new_format()
        else:
            # Try migration from old formats
            total_readings = await self._migrate_from_old_formats()
        
        return total_readings
    
    async def _load_new_format(self) -> int:
        """Load from new unified format."""
        try:
            async with aiofiles.open(self._storage_path, 'r') as f:
                content = await f.read()
                self._data = json.loads(content)
            
            # Validate version
            if self._data.get("version") != STORAGE_VERSION:
                _LOGGER.warning(
                    "Storage version mismatch: %s != %s, may need migration",
                    self._data.get("version"),
                    STORAGE_VERSION
                )
            
            total_readings = sum(
                len(z.get("temperature_history", []))
                for z in self._data.get("zones", {}).values()
            )
            
            _LOGGER.info(
                "Loaded thermal analytics cache: %d zones, %d readings",
                len(self._data.get("zones", {})),
                total_readings
            )
            return total_readings
            
        except json.JSONDecodeError as e:
            _LOGGER.error("Corrupted thermal analytics cache: %s", e)
            await self._backup_corrupted_file()
            return 0
        except Exception as e:
            _LOGGER.error("Failed to load thermal analytics cache: %s", e)
            return 0
    
    async def _migrate_from_old_formats(self) -> int:
        """Migrate from old smart_comfort_cache and heating_cycle_history formats."""
        total_readings = 0
        
        # Paths for old files
        smart_comfort_path = Path(self._hass.config.path(
            f".storage/tado_ce/smart_comfort_cache_{self._home_id}.json"
        ))
        heating_cycle_path = Path(self._hass.config.path(
            f".storage/tado_ce/heating_cycle_history_{self._home_id}.json"
        ))
        
        # Also check legacy paths without home_id
        legacy_smart_comfort = Path(self._hass.config.path(
            ".storage/tado_ce/smart_comfort_cache.json"
        ))
        legacy_heating_cycle = Path(self._hass.config.path(
            ".storage/tado_ce/heating_cycle_history.json"
        ))
        
        # Migrate smart_comfort_cache
        sc_path = smart_comfort_path if smart_comfort_path.exists() else (
            legacy_smart_comfort if legacy_smart_comfort.exists() else None
        )
        if sc_path:
            readings = await self._migrate_smart_comfort_cache(sc_path)
            total_readings += readings
            _LOGGER.info(
                "Migrated %d readings from smart_comfort_cache",
                readings
            )
        
        # Migrate heating_cycle_history
        hc_path = heating_cycle_path if heating_cycle_path.exists() else (
            legacy_heating_cycle if legacy_heating_cycle.exists() else None
        )
        if hc_path:
            cycles = await self._migrate_heating_cycle_history(hc_path)
            _LOGGER.info(
                "Migrated %d heating cycles from heating_cycle_history",
                cycles
            )
        
        # Save migrated data
        if total_readings > 0 or self._data["zones"]:
            await self.async_save()
            _LOGGER.info(
                "Migration complete: saved to %s",
                self._storage_path
            )
        
        return total_readings
    
    async def _migrate_smart_comfort_cache(self, path: Path) -> int:
        """Migrate from old smart_comfort_cache format.
        
        Old format:
        {
            "saved_at": "...",
            "history_days": 30,
            "zones": {
                "1": {
                    "zone_id": "1",  # string
                    "zone_name": "Dining",
                    "readings": [
                        {"timestamp": "...", "temperature": 18.5, "is_heating": false, "target_temperature": null}
                    ]
                }
            }
        }
        """
        try:
            async with aiofiles.open(path, 'r') as f:
                content = await f.read()
                old_data = json.loads(content)
            
            total_readings = 0
            
            for zone_id, zone_data in old_data.get("zones", {}).items():
                # Convert zone_id to int if it's a string
                zone_id_int = int(zone_id) if isinstance(zone_id, str) else zone_id
                zone_id_str = str(zone_id_int)
                
                if zone_id_str not in self._data["zones"]:
                    self._data["zones"][zone_id_str] = {
                        "zone_id": zone_id_int,
                        "zone_name": zone_data.get("zone_name", f"Zone {zone_id}"),
                        "temperature_history": [],
                        "heating_cycles": []
                    }
                
                # Convert readings to temperature_history
                readings = zone_data.get("readings", [])
                for reading in readings:
                    self._data["zones"][zone_id_str]["temperature_history"].append({
                        "timestamp": reading.get("timestamp"),
                        "temperature": reading.get("temperature"),
                        "is_heating": reading.get("is_heating", False),
                        "target_temperature": reading.get("target_temperature")
                    })
                    total_readings += 1
            
            self._data["history_days"] = old_data.get("history_days", 30)
            return total_readings
            
        except Exception as e:
            _LOGGER.error("Failed to migrate smart_comfort_cache: %s", e)
            return 0
    
    async def _migrate_heating_cycle_history(self, path: Path) -> int:
        """Migrate from old heating_cycle_history format.
        
        Old format (v1.0):
        {
            "version": "1.0",
            "zones": {
                "1": {
                    "cycles": [...]
                }
            }
        }
        
        Even older format:
        {
            "1": [cycles],
            "2": [cycles]
        }
        """
        try:
            async with aiofiles.open(path, 'r') as f:
                content = await f.read()
                old_data = json.loads(content)
            
            total_cycles = 0
            
            # Handle v1.0 format
            if "version" in old_data and "zones" in old_data:
                zones_data = old_data["zones"]
            else:
                # Handle even older format (direct zone_id -> cycles mapping)
                zones_data = {
                    zone_id: {"cycles": cycles}
                    for zone_id, cycles in old_data.items()
                    if isinstance(cycles, list)
                }
            
            for zone_id, zone_data in zones_data.items():
                zone_id_str = str(zone_id)
                
                if zone_id_str not in self._data["zones"]:
                    self._data["zones"][zone_id_str] = {
                        "zone_id": int(zone_id),
                        "zone_name": f"Zone {zone_id}",
                        "temperature_history": [],
                        "heating_cycles": []
                    }
                
                cycles = zone_data.get("cycles", [])
                self._data["zones"][zone_id_str]["heating_cycles"].extend(cycles)
                total_cycles += len(cycles)
            
            return total_cycles
            
        except Exception as e:
            _LOGGER.error("Failed to migrate heating_cycle_history: %s", e)
            return 0
    
    async def _backup_corrupted_file(self) -> None:
        """Backup corrupted file for debugging."""
        if self._storage_path.exists():
            backup_path = self._storage_path.with_suffix(".corrupted")
            try:
                await aiofiles.os.rename(
                    str(self._storage_path),
                    str(backup_path)
                )
                _LOGGER.info("Backed up corrupted file to %s", backup_path)
            except Exception as e:
                _LOGGER.error("Failed to backup corrupted file: %s", e)
    
    async def async_save(self) -> bool:
        """Save data to disk with atomic write."""
        try:
            # Ensure directory exists
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Update metadata
            self._data["version"] = STORAGE_VERSION
            self._data["saved_at"] = datetime.now(timezone.utc).isoformat()
            self._data["history_days"] = self._history_days
            
            # Write to temp file
            temp_path = self._storage_path.with_suffix(".tmp")
            async with aiofiles.open(temp_path, 'w') as f:
                await f.write(json.dumps(self._data, indent=2))
            
            # Atomic move
            await aiofiles.os.replace(str(temp_path), str(self._storage_path))
            
            self._dirty = False
            self._last_save_time = datetime.now(timezone.utc)
            
            total_readings = sum(
                len(z.get("temperature_history", []))
                for z in self._data.get("zones", {}).values()
            )
            _LOGGER.debug(
                "Saved thermal analytics cache: %d zones, %d readings",
                len(self._data.get("zones", {})),
                total_readings
            )
            return True
            
        except Exception as e:
            _LOGGER.error("Failed to save thermal analytics cache: %s", e)
            return False
    
    def get_zone_data(self, zone_id: str) -> Optional[dict]:
        """Get data for a specific zone."""
        return self._data["zones"].get(str(zone_id))
    
    def set_zone_name(self, zone_id: str, zone_name: str) -> None:
        """Set zone name (for display purposes)."""
        zone_id_str = str(zone_id)
        if zone_id_str not in self._data["zones"]:
            self._data["zones"][zone_id_str] = {
                "zone_id": int(zone_id),
                "zone_name": zone_name,
                "temperature_history": [],
                "heating_cycles": []
            }
        else:
            self._data["zones"][zone_id_str]["zone_name"] = zone_name
    
    def add_temperature_reading(
        self,
        zone_id: str,
        timestamp: datetime,
        temperature: float,
        is_heating: bool,
        target_temperature: Optional[float]
    ) -> None:
        """Add a temperature reading for a zone."""
        zone_id_str = str(zone_id)
        
        if zone_id_str not in self._data["zones"]:
            self._data["zones"][zone_id_str] = {
                "zone_id": int(zone_id),
                "zone_name": f"Zone {zone_id}",
                "temperature_history": [],
                "heating_cycles": []
            }
        
        self._data["zones"][zone_id_str]["temperature_history"].append({
            "timestamp": timestamp.isoformat(),
            "temperature": temperature,
            "is_heating": is_heating,
            "target_temperature": target_temperature
        })
        
        self._dirty = True
        
        # Cleanup old readings
        self._cleanup_old_readings(zone_id_str)
    
    def _cleanup_old_readings(self, zone_id: str) -> None:
        """Remove readings older than history_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._history_days)
        
        readings = self._data["zones"][zone_id]["temperature_history"]
        original_count = len(readings)
        
        self._data["zones"][zone_id]["temperature_history"] = [
            r for r in readings
            if datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) >= cutoff
        ]
        
        removed = original_count - len(self._data["zones"][zone_id]["temperature_history"])
        if removed > 0:
            _LOGGER.debug(
                "Cleaned up %d old readings for zone %s",
                removed,
                zone_id
            )
    
    def add_heating_cycle(self, zone_id: str, cycle: HeatingCycle) -> None:
        """Add a completed heating cycle for a zone."""
        zone_id_str = str(zone_id)
        
        if zone_id_str not in self._data["zones"]:
            self._data["zones"][zone_id_str] = {
                "zone_id": int(zone_id),
                "zone_name": f"Zone {zone_id}",
                "temperature_history": [],
                "heating_cycles": []
            }
        
        self._data["zones"][zone_id_str]["heating_cycles"].append(cycle.to_dict())
        self._dirty = True
        
        # Cleanup old cycles
        self._cleanup_old_cycles(zone_id_str)
    
    def _cleanup_old_cycles(self, zone_id: str) -> None:
        """Remove cycles older than 2x history_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._history_days * 2)
        
        cycles = self._data["zones"][zone_id]["heating_cycles"]
        original_count = len(cycles)
        
        self._data["zones"][zone_id]["heating_cycles"] = [
            c for c in cycles
            if datetime.fromisoformat(c["start_time"].replace("Z", "+00:00")) >= cutoff
        ]
        
        removed = original_count - len(self._data["zones"][zone_id]["heating_cycles"])
        if removed > 0:
            _LOGGER.debug(
                "Cleaned up %d old cycles for zone %s",
                removed,
                zone_id
            )
    
    def get_temperature_history(
        self,
        zone_id: str,
        window_days: Optional[int] = None
    ) -> list[dict]:
        """Get temperature history for a zone."""
        zone_data = self.get_zone_data(zone_id)
        if not zone_data:
            return []
        
        readings = zone_data.get("temperature_history", [])
        
        if window_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
            readings = [
                r for r in readings
                if datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) >= cutoff
            ]
        
        return readings
    
    def get_heating_cycles(
        self,
        zone_id: str,
        window_days: Optional[int] = None,
        completed_only: bool = True
    ) -> list[HeatingCycle]:
        """Get heating cycles for a zone."""
        zone_data = self.get_zone_data(zone_id)
        if not zone_data:
            return []
        
        cycles = []
        cutoff = None
        if window_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        
        for cycle_dict in zone_data.get("heating_cycles", []):
            try:
                cycle = HeatingCycle.from_dict(cycle_dict)
                
                # Filter by time window
                if cutoff and cycle.start_time < cutoff:
                    continue
                
                # Filter by completion status
                if completed_only and (not cycle.completed or cycle.interrupted):
                    continue
                
                cycles.append(cycle)
            except Exception as e:
                _LOGGER.warning("Failed to parse heating cycle: %s", e)
        
        return cycles
    
    @property
    def is_dirty(self) -> bool:
        """Check if data has unsaved changes."""
        return self._dirty
