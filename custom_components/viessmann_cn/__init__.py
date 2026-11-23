"""The Viessmann China (菲斯曼互联) integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ViessmannApi
from .const import (
    API_BASE_URL,
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ViessmannCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.WATER_HEATER,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

ViessmannConfigEntry = ConfigEntry[ViessmannCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ViessmannConfigEntry) -> bool:
    """Set up one Viessmann CN account."""
    session = async_get_clientsession(hass)
    api = ViessmannApi(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_BASE_URL, API_BASE_URL),
    )
    interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    coordinator = ViessmannCoordinator(hass, api, entry, interval)
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        _LOGGER.warning("The account has no boiler bound to it")
        return False

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ViessmannConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(
    hass: HomeAssistant, entry: ViessmannConfigEntry
) -> None:
    """Apply a new scan interval by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
