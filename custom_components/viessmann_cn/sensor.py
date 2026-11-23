"""Sensors for Viessmann CN boilers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import DeviceSnapshot, ViessmannCoordinator
from .entity import ViessmannEntity


@dataclass(frozen=True, kw_only=True)
class ViessmannSensorDescription(SensorEntityDescription):
    """Sensor bound to a property of the polled snapshot."""

    value_fn: Callable[[DeviceSnapshot], StateType]


SENSORS: tuple[ViessmannSensorDescription, ...] = (
    ViessmannSensorDescription(
        key="dhw_temperature",
        translation_key="dhw_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.dhw_temperature,
    ),
    ViessmannSensorDescription(
        key="ch_temperature",
        translation_key="ch_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.ch_temperature,
    ),
    ViessmannSensorDescription(
        key="operating_mode",
        translation_key="operating_mode",
        icon="mdi:state-machine",
        value_fn=lambda s: s.mode_label,
    ),
    ViessmannSensorDescription(
        key="fault_code",
        translation_key="fault_code",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.fault_code,
    ),
    ViessmannSensorDescription(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.firmware,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ViessmannCoordinator = entry.runtime_data
    async_add_entities(
        ViessmannSensor(coordinator, snapshot.info, description)
        for snapshot in (coordinator.data or {}).values()
        for description in SENSORS
    )


class ViessmannSensor(ViessmannEntity, SensorEntity):
    """One read-only value of the boiler."""

    entity_description: ViessmannSensorDescription

    def __init__(
        self,
        coordinator: ViessmannCoordinator,
        device: dict[str, Any],
        description: ViessmannSensorDescription,
    ) -> None:
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        snapshot = self.snapshot
        if snapshot is None:
            return None
        return self.entity_description.value_fn(snapshot)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        snapshot = self.snapshot
        if snapshot is None or self.entity_description.key != "fault_code":
            return None
        return {
            "fault": snapshot.fault,
            "mode": snapshot.mode,
            "running_status": snapshot.running_status,
            "mode_name": snapshot.mode_name,
        }
