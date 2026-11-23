"""Central heating entity for Viessmann CN boilers."""

from __future__ import annotations

import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    FALLBACK_CH_MAX,
    FALLBACK_CH_MIN,
    MODE_DHW_ONLY,
    MODE_HEATING_DHW,
    MODE_STANDBY,
)
from .coordinator import ViessmannCoordinator
from .entity import ViessmannEntity

_LOGGER = logging.getLogger(__name__)

CH_STATE_KEYS = ("chSet", "chSetTemp", "heatingSetTemp")

MODE_TO_HVAC: dict[int, HVACMode] = {
    MODE_STANDBY: HVACMode.OFF,
    MODE_DHW_ONLY: HVACMode.OFF,
    MODE_HEATING_DHW: HVACMode.HEAT,
}
HVAC_TO_MODE: dict[HVACMode, int] = {
    HVACMode.HEAT: MODE_HEATING_DHW,
    # Turning heating off keeps domestic hot water alive.
    HVACMode.OFF: MODE_DHW_ONLY,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ViessmannCoordinator = entry.runtime_data
    async_add_entities(
        ViessmannClimate(coordinator, snapshot.info)
        for snapshot in (coordinator.data or {}).values()
    )


class ViessmannClimate(ViessmannEntity, ClimateEntity):
    """采暖: flow temperature of the heating circuit."""

    _attr_translation_key = "heating"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 1.0
    _attr_min_temp = FALLBACK_CH_MIN
    _attr_max_temp = FALLBACK_CH_MAX

    def __init__(self, coordinator: ViessmannCoordinator, device: dict) -> None:
        super().__init__(coordinator, device, "heating")

    @property
    def native_current_temperature(self) -> float | None:
        snapshot = self.snapshot
        return snapshot.ch_temperature if snapshot else None

    @property
    def native_target_temperature(self) -> float | None:
        snapshot = self.snapshot
        return snapshot.ch_set if snapshot else None

    @property
    def min_temp(self) -> float:
        snapshot = self.snapshot
        value = snapshot.ch_min if snapshot else None
        return value if value is not None else FALLBACK_CH_MIN

    @property
    def max_temp(self) -> float:
        snapshot = self.snapshot
        value = snapshot.ch_max if snapshot else None
        return value if value is not None else FALLBACK_CH_MAX

    @property
    def hvac_mode(self) -> HVACMode | None:
        snapshot = self.snapshot
        if snapshot is None or snapshot.mode is None:
            return None
        return MODE_TO_HVAC.get(snapshot.mode)

    @property
    def hvac_action(self) -> HVACAction | None:
        snapshot = self.snapshot
        if snapshot is None:
            return None
        if snapshot.burning is None:
            return None
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return HVACAction.HEATING if snapshot.burning else HVACAction.IDLE

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temperature = float(temperature)
        await self.coordinator.api.async_set_heating_temperature(
            self._physics_id, temperature
        )
        self.coordinator.async_patch_detail(self._physics_id, "chSet", temperature)
        await self.coordinator.async_verify_setpoint(
            self._physics_id, CH_STATE_KEYS, temperature
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        mode = HVAC_TO_MODE.get(hvac_mode)
        if mode is None:
            _LOGGER.warning("Unsupported HVAC mode requested: %s", hvac_mode)
            return
        await self.coordinator.api.async_set_mode(self._physics_id, mode)
        self.coordinator.async_patch_detail(self._physics_id, "mode", mode)
        await self.coordinator.async_verify_setpoint(
            self._physics_id, ("mode", "runMode", "workMode"), float(mode)
        )
