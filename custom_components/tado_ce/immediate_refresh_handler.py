"""Immediate Refresh Handler for Tado CE integration.

Handles immediate data refresh after user-initiated state changes.
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DATA_DIR, RATELIMIT_FILE, ZONES_FILE

_LOGGER = logging.getLogger(__name__)

# Signal name for notifying entities to update after zones.json refresh
SIGNAL_ZONES_UPDATED = "tado_ce_zones_updated"

# Entity types that should trigger immediate refresh
REFRESH_ENTITY_TYPES = {
    "climate",      # Temperature and HVAC mode changes
    "switch",       # Switch toggles
    "water_heater"  # Hot water state changes
}

# Rate limiting thresholds
QUOTA_WARNING_THRESHOLD = 0.8  # 80% quota used
QUOTA_CRITICAL_THRESHOLD = 0.9  # 90% quota used
MIN_QUOTA_FOR_REFRESH = 50  # Minimum remaining calls to allow refresh


class ImmediateRefreshHandler:
    """Handle immediate data refresh after user actions."""
    
    def __init__(self, hass: HomeAssistant):
        """Initialize immediate refresh handler.
        
        Args:
            hass: Home Assistant instance
        """
        self.hass = hass
        # CRITICAL FIX: Per-entity rate limiting instead of global only
        self._last_refresh_per_entity: dict[str, datetime] = {}
        self._global_last_refresh: Optional[datetime] = None
        self._min_global_interval = 2  # Reduced from 10s to allow multi-zone updates
        self._min_per_entity_interval = 2  # Per-entity minimum (seconds)
        self._consecutive_failures = 0
        self._max_backoff_interval = 300  # Max 5 minutes backoff
        
        # Debounce mechanism for batch updates
        self._pending_refresh: bool = False
        self._debounce_task: Optional[object] = None
        self._debounce_delay = 15.0  # v1.6.1: Default 15 seconds (was 1s), configurable via options
    
    def _get_debounce_delay(self) -> float:
        """Get debounce delay from config or use default.
        
        v1.6.1: Configurable via Options > Refresh Debounce Delay
        """
        try:
            from .const import DOMAIN
            entries = self.hass.config_entries.async_entries(DOMAIN)
            if entries:
                from .config_manager import ConfigurationManager
                config_manager = ConfigurationManager(entries[0])
                return float(config_manager.get_refresh_debounce_seconds())
        except Exception as e:
            _LOGGER.debug(f"Could not get debounce config, using default: {e}")
        return self._debounce_delay
    
    async def _get_rate_limit_info(self) -> dict:
        """Get current rate limit information.
        
        Returns:
            Dictionary with rate limit info, or empty dict if unavailable
        """
        try:
            from .data_loader import load_ratelimit_file
            return await self.hass.async_add_executor_job(load_ratelimit_file) or {}
        except Exception as e:
            _LOGGER.debug(f"Failed to read rate limit file: {e}")
        return {}
    
    async def _check_quota_available(self) -> tuple[bool, str]:
        """Check if sufficient API quota is available.
        
        Returns:
            Tuple of (can_refresh, reason)
        """
        rl_info = await self._get_rate_limit_info()
        
        # If no rate limit info, allow refresh (fail open)
        if not rl_info:
            return True, "no_rate_limit_data"
        
        remaining = rl_info.get("remaining")
        limit = rl_info.get("limit")
        status = rl_info.get("status")
        
        # Check if rate limited
        if status == "rate_limited" or remaining == 0:
            return False, "rate_limited"
        
        # Check minimum quota threshold
        if remaining is not None and remaining < MIN_QUOTA_FOR_REFRESH:
            return False, f"quota_too_low (remaining: {remaining})"
        
        # Check percentage thresholds
        if limit and remaining is not None:
            percentage_used = (limit - remaining) / limit
            
            if percentage_used >= QUOTA_CRITICAL_THRESHOLD:
                return False, f"quota_critical ({int(percentage_used * 100)}% used)"
            
            if percentage_used >= QUOTA_WARNING_THRESHOLD:
                _LOGGER.warning(
                    f"API quota warning: {int(percentage_used * 100)}% used "
                    f"({remaining}/{limit} remaining)"
                )
        
        return True, "ok"
    
    def _get_backoff_interval(self) -> int:
        """Calculate backoff interval based on consecutive failures.
        
        Returns:
            Backoff interval in seconds
        """
        if self._consecutive_failures == 0:
            return self._min_global_interval
        
        # Exponential backoff: 10s, 20s, 40s, 80s, 160s, 300s (max)
        backoff = self._min_global_interval * (2 ** self._consecutive_failures)
        return min(backoff, self._max_backoff_interval)
    
    def should_refresh(self, entity_id: str) -> bool:
        """Check if entity type should trigger immediate refresh.
        
        Args:
            entity_id: Entity ID (e.g., "climate.living_room")
            
        Returns:
            True if entity type should trigger refresh
        """
        domain = entity_id.split(".")[0]
        return domain in REFRESH_ENTITY_TYPES
    
    def can_refresh_now(self, entity_id: str) -> bool:
        """Check if refresh is allowed for this entity.
        
        CRITICAL FIX: Per-entity rate limiting allows multiple entities
        to refresh within the global interval, while still preventing
        API spam from a single entity.
        
        Args:
            entity_id: Entity ID requesting refresh
            
        Returns:
            True if refresh is allowed now
        """
        now = datetime.now()
        
        # Check global rate limit (prevents API spam)
        if self._global_last_refresh:
            global_elapsed = (now - self._global_last_refresh).total_seconds()
            required_global = self._get_backoff_interval()
            if global_elapsed < required_global:
                _LOGGER.debug(
                    f"Global backoff active: {int(required_global - global_elapsed)}s remaining "
                    f"(failures: {self._consecutive_failures})"
                )
                return False
        
        # Check per-entity rate limit (allows multiple entities)
        if entity_id in self._last_refresh_per_entity:
            entity_elapsed = (now - self._last_refresh_per_entity[entity_id]).total_seconds()
            if entity_elapsed < self._min_per_entity_interval:
                _LOGGER.debug(
                    f"Entity {entity_id} backoff active: "
                    f"{int(self._min_per_entity_interval - entity_elapsed)}s remaining"
                )
                return False
        
        return True
    
    async def trigger_refresh(self, entity_id: str, reason: str = "state_change", force: bool = False, skip_debounce: bool = False):
        """Trigger immediate refresh for an entity.
        
        Uses debouncing to batch multiple rapid changes into a single refresh.
        
        Args:
            entity_id: Entity ID that triggered the refresh
            reason: Reason for refresh (for logging)
            force: If True, skip entity type check (for buttons like Resume All Schedules)
            skip_debounce: If True, execute refresh immediately without debounce delay
        """
        if not force and not self.should_refresh(entity_id):
            _LOGGER.debug(f"Entity {entity_id} does not trigger immediate refresh")
            return
        
        # Check API quota before scheduling refresh
        can_refresh, quota_reason = await self._check_quota_available()
        if not can_refresh:
            _LOGGER.warning(
                f"Skipping immediate refresh for {entity_id}: {quota_reason}. "
                f"Will rely on normal polling."
            )
            return
        
        _LOGGER.debug(f"Scheduling debounced refresh for {entity_id} (reason: {reason})")
        
        # Cancel existing debounce task if any
        if self._debounce_task is not None:
            self._debounce_task.cancel()
            self._debounce_task = None
        
        # Mark refresh as pending
        self._pending_refresh = True
        self._last_refresh_per_entity[entity_id] = datetime.now()
        
        # Schedule debounced refresh
        async def _debounced_refresh():
            # Skip debounce delay if requested (for buttons like Resume All Schedules)
            if not skip_debounce:
                delay = self._get_debounce_delay()
                await asyncio.sleep(delay)
            
            if not self._pending_refresh:
                return
            
            self._pending_refresh = False
            
            # Check global rate limit
            now = datetime.now()
            if self._global_last_refresh:
                global_elapsed = (now - self._global_last_refresh).total_seconds()
                required_global = self._get_backoff_interval()
                if global_elapsed < required_global:
                    _LOGGER.debug(
                        f"Global backoff active: {int(required_global - global_elapsed)}s remaining"
                    )
                    return
            
            _LOGGER.info(f"Executing debounced refresh (triggered by: {reason})")
            
            try:
                await self._async_fetch_zone_states()
                
                self._global_last_refresh = datetime.now()
                
                if self._consecutive_failures > 0:
                    _LOGGER.info(f"Immediate refresh recovered after {self._consecutive_failures} failures")
                    self._consecutive_failures = 0
                
                _LOGGER.debug("Immediate refresh completed (1 API call)")
                
                # v1.9.3: Notify all climate entities to update immediately
                # This fixes the grey loading state issue (#44) where entities
                # wait for SCAN_INTERVAL (30s) to re-read zones.json
                async_dispatcher_send(self.hass, SIGNAL_ZONES_UPDATED)
                _LOGGER.debug("Sent zones_updated signal to all entities")
                
            except Exception as e:
                self._consecutive_failures += 1
                _LOGGER.error(
                    f"Immediate refresh failed (attempt {self._consecutive_failures}): {e}. "
                    f"Next backoff: {self._get_backoff_interval()}s"
                )
        
        self._debounce_task = asyncio.create_task(_debounced_refresh())
    
    async def _async_fetch_zone_states(self):
        """Fetch zone states using async API and save to file.
        
        This is more efficient than subprocess - only 1 API call for zoneStates.
        Weather and home state are not needed for immediate entity refresh.
        """
        from .async_api import get_async_client
        from .data_loader import get_current_home_id
        from .const import get_data_file
        import tempfile
        import shutil
        
        client = get_async_client(self.hass)
        zones_data = await client.api_call("zoneStates")
        
        if zones_data:
            # Get per-home file path
            home_id = get_current_home_id()
            zones_file = get_data_file("zones", home_id)
            
            # Save to zones.json using atomic write
            def write_file():
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                # Atomic write: write to temp file then move
                with tempfile.NamedTemporaryFile(
                    mode='w', dir=DATA_DIR, delete=False, suffix='.tmp'
                ) as tmp:
                    json.dump(zones_data, tmp, indent=2)
                    temp_path = tmp.name
                shutil.move(temp_path, zones_file)
            await self.hass.async_add_executor_job(write_file)
            _LOGGER.debug(f"Zone states refreshed ({len(zones_data.get('zoneStates', {}))} zones)")
            
            # Save rate limit info for API Usage sensor immediate update
            await client.save_ratelimit()
        else:
            raise Exception("Failed to fetch zone states")
    
    async def async_quick_sync(self):
        """Perform quick sync (zone states only).
        
        Uses async API to fetch only zoneStates (1 API call).
        """
        await self._async_fetch_zone_states()


# Global handler instance (initialized in __init__.py)
_handler: Optional[ImmediateRefreshHandler] = None


def get_handler(hass: HomeAssistant) -> ImmediateRefreshHandler:
    """Get or create the global immediate refresh handler.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        ImmediateRefreshHandler instance
    """
    global _handler
    if _handler is None:
        _handler = ImmediateRefreshHandler(hass)
    return _handler


def cleanup_handler() -> bool:
    """Clean up the global immediate refresh handler.
    
    MUST be called in async_unload_entry() to prevent memory leaks.
    Cancels any pending debounce tasks.
    
    Returns:
        True if handler was cleaned up, False if no handler existed
    """
    global _handler
    if _handler is not None:
        # Cancel pending debounce task to prevent orphaned coroutines
        if _handler._debounce_task is not None:
            _handler._debounce_task.cancel()
            _handler._debounce_task = None
            _LOGGER.debug("Cancelled pending debounce task")
        _handler = None
        _LOGGER.debug("Cleaned up ImmediateRefreshHandler")
        return True
    return False
