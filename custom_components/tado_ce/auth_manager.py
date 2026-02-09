"""Centralized Authentication Manager for Tado CE Integration.

This module provides thread-safe token management with automatic refresh
and caching to prevent race conditions when multiple entities request
access tokens simultaneously.

CRITICAL: This solves the token rotation race condition that occurs when
multiple entities (climate, sensor, switch) simultaneously refresh tokens,
causing authentication failures.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock, Condition
from typing import Optional
from urllib.request import Request, urlopen
from urllib.parse import urlencode

_LOGGER = logging.getLogger(__name__)


class TokenRefreshError(Exception):
    """Exception raised when token refresh fails."""
    pass


class AuthManager:
    """Thread-safe authentication manager with token caching.
    
    This class ensures that:
    1. Only one token refresh happens at a time (thread-safe)
    2. Tokens are cached to avoid unnecessary API calls
    3. Token rotation is handled correctly
    4. All platforms use the same token instance
    
    Usage:
        auth_manager = AuthManager(config_file_path, client_id, auth_url)
        token = auth_manager.get_access_token()
    """
    
    # Token cache duration (3600s = 1 hour, Tado tokens valid for 10 minutes)
    # We use 5 minutes to be safe
    TOKEN_CACHE_DURATION = 300
    
    def __init__(self, config_file: Path, client_id: str, auth_url: str):
        """Initialize authentication manager.
        
        Args:
            config_file: Path to config.json file
            client_id: Tado OAuth client ID
            auth_url: Tado OAuth token endpoint URL
        """
        self._config_file = config_file
        self._client_id = client_id
        self._auth_url = auth_url
        
        # CRITICAL FIX: Use Condition variable for proper thread synchronization
        self._lock = Lock()
        self._refresh_condition = Condition(self._lock)
        
        # Token cache
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        
        # Refresh state tracking
        self._refresh_in_progress = False
        self._last_refresh_attempt: Optional[datetime] = None
        self._consecutive_failures = 0
        
        _LOGGER.debug("AuthManager initialized")
    
    def get_access_token(self) -> Optional[str]:
        """Get valid access token with automatic refresh.
        
        This method is thread-safe and will:
        1. Return cached token if still valid
        2. Refresh token if expired or missing
        3. Handle concurrent refresh requests (only one actual refresh)
        
        CRITICAL FIX: Uses Condition variable for proper thread synchronization.
        Lock is released atomically when waiting, preventing race conditions.
        
        Returns:
            Valid access token, or None if refresh fails
        """
        with self._lock:
            # Check if cached token still valid
            if self._is_token_valid():
                _LOGGER.debug("Using cached access token")
                return self._access_token
            
            # Check if another thread is already refreshing
            if self._refresh_in_progress:
                # CRITICAL FIX: Wait using Condition (lock released atomically)
                _LOGGER.debug("Waiting for ongoing refresh...")
                self._refresh_condition.wait(timeout=10)
                
                # Lock re-acquired automatically after wait
                if self._is_token_valid():
                    _LOGGER.debug("Token refresh completed by another thread")
                    return self._access_token
                else:
                    _LOGGER.warning("Refresh completed but token still invalid")
                    return None
            
            # Perform token refresh
            return self._refresh_token()
    
    def _is_token_valid(self) -> bool:
        """Check if cached token is still valid.
        
        Returns:
            True if token exists and not expired
        """
        if not self._access_token or not self._token_expiry:
            return False
        
        # Add 10 second buffer to avoid edge cases
        return datetime.now() < (self._token_expiry - timedelta(seconds=10))
    
    def _refresh_token(self) -> Optional[str]:
        """Refresh access token using refresh token.
        
        This method MUST be called with lock held.
        
        CRITICAL FIX: Uses Condition.notify_all() to wake waiting threads.
        
        Returns:
            New access token, or None if refresh fails
        """
        # Mark refresh in progress
        self._refresh_in_progress = True
        self._last_refresh_attempt = datetime.now()
        
        try:
            # Load config to get refresh token
            config = self._load_config()
            refresh_token = config.get("refresh_token")
            
            if not refresh_token:
                _LOGGER.error("No refresh token available")
                self._consecutive_failures += 1
                return None
            
            _LOGGER.debug("Refreshing access token...")
            
            # Call Tado OAuth token endpoint
            data = urlencode({
                "client_id": self._client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }).encode()
            
            req = Request(f"{self._auth_url}/token", data=data)
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            
            with urlopen(req, timeout=10) as resp:
                token_data = json.loads(resp.read().decode())
                
                new_access_token = token_data.get("access_token")
                new_refresh_token = token_data.get("refresh_token")
                
                if not new_access_token:
                    _LOGGER.error("No access token in response")
                    self._consecutive_failures += 1
                    return None
                
                # CRITICAL: Save new refresh token immediately
                if new_refresh_token and new_refresh_token != refresh_token:
                    config["refresh_token"] = new_refresh_token
                    self._save_config(config)
                    _LOGGER.info("Refresh token rotated and saved")
                
                # Cache new access token
                self._access_token = new_access_token
                self._token_expiry = datetime.now() + timedelta(seconds=self.TOKEN_CACHE_DURATION)
                self._consecutive_failures = 0
                
                # CRITICAL FIX: Notify all waiting threads
                self._refresh_condition.notify_all()
                
                _LOGGER.debug("Access token refreshed successfully")
                return new_access_token
                
        except Exception as e:
            _LOGGER.error(f"Token refresh failed: {e}")
            self._consecutive_failures += 1
            
            # Check if refresh token expired
            if "invalid_grant" in str(e):
                _LOGGER.error("Refresh token expired - user must re-authenticate")
                # Clear invalid refresh token
                config = self._load_config()
                config["refresh_token"] = None
                self._save_config(config)
            
            # CRITICAL FIX: Notify waiting threads even on failure
            self._refresh_condition.notify_all()
            
            return None
            
        finally:
            # Always clear refresh in progress flag
            self._refresh_in_progress = False
    
    def _load_config(self) -> dict:
        """Load config from file.
        
        Returns:
            Config dictionary
        """
        if not self._config_file.exists():
            return {"home_id": None, "refresh_token": None}
        
        try:
            with open(self._config_file) as f:
                return json.load(f)
        except Exception as e:
            _LOGGER.error(f"Failed to load config: {e}")
            return {"home_id": None, "refresh_token": None}
    
    def _save_config(self, config: dict):
        """Save config to file atomically to prevent corruption.
        
        CRITICAL: Uses atomic write pattern to ensure config.json is never
        left in a corrupt state, even if process crashes during write.
        
        Args:
            config: Config dictionary to save
        """
        import tempfile
        import shutil
        
        temp_path = None
        try:
            # Atomic write: write to temp file first, then rename
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self._config_file.parent,
                delete=False,
                suffix='.tmp'
            ) as tmp_file:
                json.dump(config, tmp_file, indent=2)
                tmp_file.flush()
                temp_path = tmp_file.name
            
            # Verify temp file was created successfully
            if not Path(temp_path).exists():
                raise IOError(f"Temp file was not created: {temp_path}")
            
            # Verify temp file is valid JSON and not empty
            temp_size = Path(temp_path).stat().st_size
            if temp_size == 0:
                raise IOError("Temp file is empty")
            
            with open(temp_path, 'r') as f:
                json.load(f)  # Verify JSON is valid
            
            # Atomic rename (POSIX guarantees atomicity)
            shutil.move(temp_path, self._config_file)
            
            _LOGGER.debug("Config saved atomically")
            
        except Exception as e:
            _LOGGER.error(f"Failed to save config: {e}")
            
            # Clean up temp file if it exists
            if temp_path and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                    _LOGGER.debug(f"Cleaned up temp file: {temp_path}")
                except OSError as cleanup_error:
                    _LOGGER.error(f"Failed to cleanup temp file: {cleanup_error}")
            
            # Re-raise to notify caller
            raise
    
    def invalidate_token(self):
        """Invalidate cached token (force refresh on next request).
        
        This should be called when an API call returns 401/403.
        """
        with self._lock:
            _LOGGER.debug("Invalidating cached token")
            self._access_token = None
            self._token_expiry = None
    
    def get_stats(self) -> dict:
        """Get authentication manager statistics.
        
        Returns:
            Dictionary with stats (for debugging/monitoring)
        """
        with self._lock:
            return {
                "token_cached": self._access_token is not None,
                "token_valid": self._is_token_valid(),
                "token_expiry": self._token_expiry.isoformat() if self._token_expiry else None,
                "refresh_in_progress": self._refresh_in_progress,
                "last_refresh_attempt": self._last_refresh_attempt.isoformat() if self._last_refresh_attempt else None,
                "consecutive_failures": self._consecutive_failures,
            }


# Global singleton instance
_auth_manager: Optional[AuthManager] = None
_auth_manager_lock = Lock()


def cleanup_auth_manager() -> bool:
    """Clean up the global AuthManager instance.
    
    MUST be called in async_unload_entry() to ensure fresh auth state on reload.
    
    Returns:
        True if manager was cleaned up, False if no manager existed
    """
    global _auth_manager
    with _auth_manager_lock:
        if _auth_manager is not None:
            _auth_manager = None
            _LOGGER.debug("Cleaned up AuthManager")
            return True
    return False


def get_auth_manager(config_file: Path, client_id: str, auth_url: str) -> AuthManager:
    """Get or create global AuthManager instance (thread-safe).
    
    This ensures all platforms use the same AuthManager instance,
    preventing race conditions during concurrent initialization.
    
    CRITICAL FIX: Uses double-checked locking pattern to prevent
    multiple instances being created when multiple entities start
    simultaneously during Home Assistant startup.
    
    Args:
        config_file: Path to config.json
        client_id: Tado OAuth client ID
        auth_url: Tado OAuth token endpoint URL
        
    Returns:
        Global AuthManager instance
    """
    global _auth_manager
    
    # First check (without lock) - fast path for already initialized
    if _auth_manager is not None:
        return _auth_manager
    
    # Acquire lock for initialization
    with _auth_manager_lock:
        # Second check (with lock) - ensure only one thread creates instance
        if _auth_manager is None:
            _auth_manager = AuthManager(config_file, client_id, auth_url)
            _LOGGER.debug("Global AuthManager created (thread-safe)")
        
        return _auth_manager
