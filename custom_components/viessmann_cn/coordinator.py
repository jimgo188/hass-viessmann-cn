"""Coordinator and normalised device snapshot for Viessmann CN."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    ViessmannApi,
    ViessmannApiError,
    ViessmannAuthError,
    ViessmannConnectionError,
    as_float,
    as_int,
    first,
)
from .const import DOMAIN, MODE_NAMES, VERIFY_INTERVAL, VERIFY_TIMEOUT

_LOGGER = logging.getLogger(__name__)

DETAIL_KEYS = ("boilerRequestData", "requestData", "boilerStatus", "deviceData")


def _detail_sources(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Candidate dicts inside a detail payload, most specific first."""
    sources: list[dict[str, Any]] = [detail]
    for key in DETAIL_KEYS:
        value = detail.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _pick(detail: dict[str, Any], *keys: str) -> Any:
    for source in _detail_sources(detail):
        value = first(source, *keys)
        if value is not None:
            return value
    return None


@dataclass
class DeviceSnapshot:
    """One boiler, detail + live scan merged into one read-only picture."""

    info: dict[str, Any]
    detail: dict[str, Any] = field(default_factory=dict)
    scan: dict[str, Any] = field(default_factory=dict)

    @property
    def physics_id(self) -> str:
        return self.info["physics_id"]

    @property
    def name(self) -> str:
        return self.info.get("name") or "壁挂炉"

    @property
    def model(self) -> str | None:
        value = self.info.get("model") or _pick(self.detail, "model", "deviceModel")
        return str(value) if value else None

    # ------------------------------------------------------------- setpoints

    @property
    def dhw_set(self) -> float | None:
        return as_float(_pick(self.detail, "dhwSet", "dhwSetTemp", "hotWaterSetTemp"))

    @property
    def dhw_min(self) -> float | None:
        return as_float(_pick(self.detail, "dhwMinSet", "dhwMin"))

    @property
    def dhw_max(self) -> float | None:
        return as_float(_pick(self.detail, "dhwMaxSet", "dhwMax"))

    @property
    def ch_set(self) -> float | None:
        return as_float(_pick(self.detail, "chSet", "chSetTemp", "heatingSetTemp"))

    @property
    def ch_min(self) -> float | None:
        return as_float(_pick(self.detail, "chMin", "chMinSet"))

    @property
    def ch_max(self) -> float | None:
        return as_float(_pick(self.detail, "chMax", "chMaxSet"))

    # ------------------------------------------------------------ live scan

    @property
    def dhw_temperature(self) -> float | None:
        return as_float(first(self.scan, "dhwProbe", "dhwTemp", "hotWaterTemp"))

    @property
    def ch_temperature(self) -> float | None:
        return as_float(first(self.scan, "chProbe", "chTemp", "heatingTemp"))

    @property
    def burning(self) -> bool | None:
        fire = as_int(first(self.scan, "fire", "burning", "flame"))
        return None if fire is None else fire == 1

    @property
    def pressure(self) -> float | None:
        return as_float(first(self.scan, "waterPressure", "pressure"))

    @property
    def running_status(self) -> int | None:
        return as_int(first(self.scan, "runningStatus", "runStatus"))

    @property
    def mode_name(self) -> str | None:
        value = first(self.scan, "modeName", "runningStatusName")
        return str(value) if value else None

    @property
    def firmware(self) -> str | None:
        value = first(self.scan, "wifiFirmwareVersion", "firmwareVersion", "wifiVersion")
        return str(value) if value else None

    # ---------------------------------------------------------------- boiler

    @property
    def mode(self) -> int | None:
        return as_int(_pick(self.detail, "mode", "runMode", "workMode"))

    @property
    def mode_label(self) -> str | None:
        if self.mode is None:
            return None
        return MODE_NAMES.get(self.mode, f"模式 {self.mode}")

    @property
    def fault_code(self) -> int | None:
        return as_int(_pick(self.detail, "faultStatus", "faultCode", "errorCode"))

    @property
    def fault(self) -> bool | None:
        code = self.fault_code
        return None if code is None else code != 0


class ViessmannCoordinator(DataUpdateCoordinator[dict[str, DeviceSnapshot]]):
    """Poll detail + scanStatus for every boiler of the account."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        api: ViessmannApi,
        config_entry: ConfigEntry,
        update_interval,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, DeviceSnapshot]:
        try:
            devices = await self.api.async_get_devices()
        except ViessmannAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ViessmannConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except ViessmannApiError as err:
            raise UpdateFailed(str(err)) from err

        snapshots: dict[str, DeviceSnapshot] = {}
        errors: list[str] = []
        for device in devices:
            physics_id = device["physics_id"]
            previous = (self.data or {}).get(physics_id)
            try:
                detail = await self.api.async_get_device_detail(physics_id)
                scan = await self.api.async_get_scan_status(physics_id)
            except ViessmannAuthError:
                raise
            except (ViessmannConnectionError, ViessmannApiError) as err:
                errors.append(f"{physics_id}: {err}")
                if previous is not None:
                    snapshots[physics_id] = previous
                continue
            snapshots[physics_id] = DeviceSnapshot(info=device, detail=detail, scan=scan)

        if not snapshots and errors:
            raise UpdateFailed("; ".join(errors))
        for message in errors:
            _LOGGER.debug("Partial update failure: %s", message)
        return snapshots

    async def async_verify_setpoint(
        self,
        physics_id: str,
        keys: tuple[str, ...],
        target: float,
        *,
        timeout: float = VERIFY_TIMEOUT,
        interval: float = VERIFY_INTERVAL,
    ) -> bool:
        """Poll the cloud until a written setpoint is actually reported back.

        The boiler accepts a write instantly but reflects it a few seconds
        later; without this the slider springs back to the old value.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            await asyncio.sleep(interval)
            try:
                detail = await self.api.async_get_device_detail(physics_id)
            except ViessmannAuthError:
                raise
            except (ViessmannConnectionError, ViessmannApiError) as err:
                _LOGGER.debug("Verification poll failed: %s", err)
                continue
            current = as_float(_pick(detail, *keys))
            snapshot = (self.data or {}).get(physics_id)
            if snapshot is not None:
                snapshot.detail = detail
                self.async_update_listeners()
            if current is not None and abs(current - target) < 0.5:
                _LOGGER.debug("Setpoint %s = %s confirmed", keys, target)
                return True
        _LOGGER.warning("Setpoint %s = %s was not confirmed by the cloud", keys, target)
        return False

    def async_patch_detail(self, physics_id: str, key: str, value: Any) -> None:
        """Optimistically write a setpoint so the UI does not bounce back."""
        snapshot = (self.data or {}).get(physics_id)
        if snapshot is None:
            return
        for source in _detail_sources(snapshot.detail):
            if key in source:
                source[key] = value
                self.async_update_listeners()
                return
        snapshot.detail.setdefault("boilerRequestData", {})[key] = value
        self.async_update_listeners()
