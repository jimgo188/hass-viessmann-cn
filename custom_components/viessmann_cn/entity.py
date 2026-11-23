"""Base entity for the Viessmann CN integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import DeviceSnapshot, ViessmannCoordinator


class ViessmannEntity(CoordinatorEntity[ViessmannCoordinator]):
    """Common behaviour: one HA device per boiler, shared coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ViessmannCoordinator,
        device: dict[str, Any],
        unique_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._device = device
        self._physics_id = device["physics_id"]
        self._attr_unique_id = f"{self._physics_id}_{unique_suffix}"

    @property
    def snapshot(self) -> DeviceSnapshot | None:
        return (self.coordinator.data or {}).get(self._physics_id)

    @property
    def available(self) -> bool:
        return super().available and self.snapshot is not None

    @property
    def device_info(self) -> DeviceInfo:
        snapshot = self.snapshot
        return DeviceInfo(
            identifiers={(DOMAIN, self._physics_id)},
            name=self._device.get("name") or "壁挂炉",
            manufacturer=MANUFACTURER,
            model=(snapshot.model if snapshot else None) or "壁挂炉",
            sw_version=snapshot.firmware if snapshot else None,
        )
