"""Domestic hot water entity for Viessmann CN boilers."""

from __future__ import annotations

import logging

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FALLBACK_DHW_MAX,
    FALLBACK_DHW_MIN,
    MODE_DHW_ONLY,
    MODE_HEATING_DHW,
    MODE_STANDBY,
)
from .coordinator import ViessmannCoordinator
from .entity import ViessmannEntity

_LOGGER = logging.getLogger(__name__)

DHW_STATE_KEYS = ("dhwSet", "dhwSetTemp", "hotWaterSetTemp")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ViessmannCoordinator = entry.runtime_data
    async_add_entities(
        ViessmannWaterHeater(coordinator, snapshot.info)
        for snapshot in (coordinator.data or {}).values()
    )


class ViessmannWaterHeater(ViessmannEntity, WaterHeaterEntity):
    """生活热水: current and target domestic hot water temperature."""

    _attr_translation_key = "dhw"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 1.0
    _attr_min_temp = FALLBACK_DHW_MIN
    _attr_max_temp = FALLBACK_DHW_MAX

    def __init__(self, coordinator: ViessmannCoordinator, device: dict) -> None:
        super().__init__(coordinator, device, "dhw")

    @property
    def native_current_temperature(self) -> float | None:
        snapshot = self.snapshot
        return snapshot.dhw_temperature if snapshot else None

    @property
    def native_target_temperature(self) -> float | None:
        snapshot = self.snapshot
        return snapshot.dhw_set if snapshot else None

    @property
    def min_temp(self) -> float:
        snapshot = self.snapshot
        value = snapshot.dhw_min if snapshot else None
        return value if value is not None else FALLBACK_DHW_MIN

    @property
    def max_temp(self) -> float:
        snapshot = self.snapshot
        value = snapshot.dhw_max if snapshot else None
        return value if value is not None else FALLBACK_DHW_MAX

    @property
    def current_operation(self) -> str | None:
        """Report whether DHW is available, derived from the boiler mode."""
        snapshot = self.snapshot
        if snapshot is None or snapshot.mode is None:
            return None
        if snapshot.mode in (MODE_HEATING_DHW, MODE_DHW_ONLY):
            return "on"
        if snapshot.mode == MODE_STANDBY:
            return "off"
        return None

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temperature = float(temperature)
        await self.coordinator.api.async_set_dhw_temperature(self._physics_id, temperature)
        self.coordinator.async_patch_detail(self._physics_id, "dhwSet", temperature)
        await self.coordinator.async_verify_setpoint(
            self._physics_id, DHW_STATE_KEYS, temperature
        )
