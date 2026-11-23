"""Binary sensors for Viessmann CN boilers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DeviceSnapshot, ViessmannCoordinator
from .entity import ViessmannEntity


@dataclass(frozen=True, kw_only=True)
class ViessmannBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[DeviceSnapshot], bool | None]


BINARY_SENSORS: tuple[ViessmannBinarySensorDescription, ...] = (
    ViessmannBinarySensorDescription(
        key="burning",
        translation_key="burning",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:fire",
        value_fn=lambda s: s.burning,
    ),
    ViessmannBinarySensorDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.fault,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ViessmannCoordinator = entry.runtime_data
    async_add_entities(
        ViessmannBinarySensor(coordinator, snapshot.info, description)
        for snapshot in (coordinator.data or {}).values()
        for description in BINARY_SENSORS
    )


class ViessmannBinarySensor(ViessmannEntity, BinarySensorEntity):
    """Boiler is firing / boiler reports a fault."""

    entity_description: ViessmannBinarySensorDescription

    def __init__(self, coordinator, device, description) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return self.entity_description.value_fn(snapshot)
