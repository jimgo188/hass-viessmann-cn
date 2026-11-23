"""Diagnostics support: full raw cloud payloads, credentials stripped."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import ViessmannConfigEntry
from .const import CONF_PASSWORD, CONF_USERNAME


def _mask_phone(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:3]}****{value[-4:]}"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ViessmannConfigEntry
) -> dict[str, Any]:
    """Return the raw API payloads, which is what makes field bugs debuggable."""
    coordinator = entry.runtime_data
    devices: dict[str, Any] = {}
    for physics_id, snapshot in (coordinator.data or {}).items():
        devices[physics_id] = {
            "info": snapshot.info,
            "detail": snapshot.detail,
            "scan": snapshot.scan,
        }
    return {
        "entry": {
            "username": _mask_phone(entry.data.get(CONF_USERNAME)),
            "has_password": bool(entry.data.get(CONF_PASSWORD)),
            "options": dict(entry.options),
        },
        "devices": devices,
    }
