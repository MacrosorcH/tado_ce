"""Area Manager for Tado CE Integration.

This module handles automatic area assignment for zone devices during setup.
It uses fuzzy matching to map zone names to existing Home Assistant areas.
"""
import logging
from typing import Optional
from difflib import SequenceMatcher

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Minimum similarity score for fuzzy matching (0.0 to 1.0)
MIN_SIMILARITY_SCORE = 0.7


def _calculate_similarity(str1: str, str2: str) -> float:
    """Calculate similarity between two strings (case-insensitive).
    
    Uses SequenceMatcher for fuzzy string matching.
    
    Args:
        str1: First string to compare
        str2: Second string to compare
        
    Returns:
        float: Similarity score between 0.0 (no match) and 1.0 (exact match)
    """
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


def find_matching_area(zone_name: str, hass: HomeAssistant) -> Optional[str]:
    """Find matching Home Assistant area for a zone name.
    
    Uses fuzzy matching to find the best matching area. Returns None if
    no confident match is found (similarity < MIN_SIMILARITY_SCORE).
    
    Args:
        zone_name: The Tado zone name (e.g., "Living Room", "Bedroom 1")
        hass: Home Assistant instance
        
    Returns:
        str: Area ID if match found, None otherwise
    """
    area_registry = ar.async_get(hass)
    
    # Get all areas
    areas = area_registry.async_list_areas()
    if not areas:
        _LOGGER.debug(f"No areas defined in Home Assistant")
        return None
    
    # Find best match
    best_match = None
    best_score = 0.0
    
    for area in areas:
        score = _calculate_similarity(zone_name, area.name)
        if score > best_score:
            best_score = score
            best_match = area
    
    # Only return match if confidence is high enough
    if best_match and best_score >= MIN_SIMILARITY_SCORE:
        _LOGGER.info(
            f"Area match: '{zone_name}' → '{best_match.name}' "
            f"(confidence: {best_score:.0%})"
        )
        return best_match.id
    else:
        _LOGGER.debug(
            f"No confident area match for '{zone_name}' "
            f"(best: '{best_match.name if best_match else 'none'}' at {best_score:.0%})"
        )
        return None


async def async_assign_zone_areas(hass: HomeAssistant, home_id: str, zones_info: list) -> None:
    """Assign areas to zone devices based on zone names.
    
    This function is called during integration setup to automatically assign
    Home Assistant areas to Tado zone devices. It uses fuzzy matching to find
    the best matching area for each zone.
    
    Args:
        hass: Home Assistant instance
        home_id: The Tado home ID
        zones_info: List of zone info dicts from zones_info.json
    """
    device_registry = dr.async_get(hass)
    
    assigned_count = 0
    skipped_count = 0
    
    for zone in zones_info:
        zone_id = str(zone.get('id'))
        zone_name = zone.get('name', f'Zone {zone_id}')
        
        # Build device identifier
        if home_id and home_id != "unknown":
            device_identifier = f"tado_ce_{home_id}_zone_{zone_id}"
        else:
            device_identifier = f"tado_ce_zone_{zone_id}"
        
        # Get device from registry
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, device_identifier)}
        )
        
        if not device:
            _LOGGER.debug(f"Device not found for zone {zone_name} ({device_identifier})")
            continue
        
        # Skip if device already has an area assigned
        if device.area_id:
            _LOGGER.debug(f"Zone '{zone_name}' already has area assigned, skipping")
            skipped_count += 1
            continue
        
        # Find matching area
        area_id = find_matching_area(zone_name, hass)
        
        if area_id:
            # Assign area to device
            device_registry.async_update_device(
                device.id,
                area_id=area_id
            )
            assigned_count += 1
            _LOGGER.info(f"Assigned area to zone '{zone_name}'")
        else:
            _LOGGER.debug(f"No area match found for zone '{zone_name}'")
    
    # Summary log
    if assigned_count > 0:
        _LOGGER.info(
            f"Auto-assigned {assigned_count} zone(s) to areas "
            f"({skipped_count} already assigned)"
        )
    else:
        _LOGGER.debug(
            f"No zones auto-assigned to areas "
            f"({skipped_count} already assigned, {len(zones_info) - skipped_count} no match)"
        )
