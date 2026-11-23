"""Async client for the Viessmann China cloud (菲斯曼互联 App).

The app authenticates with a phone number and password against
``https://api.viessmann.cn/idass/user/login`` and then talks plain
form-encoded or JSON REST to ``/api/...`` with a bearer token.

Everything here is deliberately tolerant about the *shape* of responses:
the cloud nests payloads differently per endpoint and per app version, so the
client normalises instead of assuming a fixed schema.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Iterable

import aiohttp

from .const import (
    API_BASE_URL,
    DEFAULT_HEADERS,
    ENDPOINT_DEVICE_DETAIL,
    ENDPOINT_FAMILY_DEVICES,
    ENDPOINT_FAMILY_DEVICES_V1,
    ENDPOINT_FAMILY_LIST,
    ENDPOINT_LOGIN,
    ENDPOINT_SCAN_STATUS,
    ENDPOINT_SET_CH_TEMP,
    ENDPOINT_SET_DHW_TEMP,
    ENDPOINT_SET_MODE,
    ENDPOINT_USER_INFO,
    FORM_CONTENT_TYPE,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

OK_CODES = (None, 0, "0", 200, "200")


class ViessmannError(Exception):
    """Base error for the Viessmann CN cloud."""


class ViessmannAuthError(ViessmannError):
    """The account was rejected (bad password, expired session, blocked)."""


class ViessmannConnectionError(ViessmannError):
    """The cloud could not be reached or answered with garbage."""


class ViessmannApiError(ViessmannError):
    """The cloud answered with a business error code."""

    def __init__(self, code: Any, message: str, path: str = "") -> None:
        text = f"{message} (code {code})"
        if path:
            text = f"{path}: {text}"
        super().__init__(text)
        self.code = code
        self.message = message
        self.path = path


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    """Yield every dict contained in a JSON structure, depth first."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _unwrap_data(body: dict[str, Any]) -> Any:
    """Return the useful part of a response.

    ``/idass/user/login`` answers ``{"code":0,"data":{"statusCode":200,
    "data":{...}}}`` while the ``/api`` endpoints answer ``{"code":0,
    "data":...}`` directly.
    """
    data = body.get("data")
    if isinstance(data, dict) and "code" not in data and "data" in data:
        return data.get("data")
    return data


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class ViessmannApi:
    """Small wrapper around the endpoints the app actually uses."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        base_url: str = API_BASE_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._user_id: str | None = None
        self._devices: list[dict[str, Any]] | None = None
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------------ HTTP

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        authenticated: bool = True,
        retry: bool = True,
    ) -> dict[str, Any]:
        headers = dict(DEFAULT_HEADERS)
        if extra_headers:
            headers.update(extra_headers)
        if data is not None:
            headers["Content-Type"] = FORM_CONTENT_TYPE
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        if authenticated:
            headers["Authorization"] = await self.async_get_token()

        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                json=json_body,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                text = await response.text()
                status = response.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ViessmannConnectionError(f"{method} {path}: {err}") from err

        try:
            body = json.loads(text) if text else {}
        except ValueError as err:
            raise ViessmannConnectionError(
                f"{method} {path}: non-JSON response (HTTP {status}): {text[:200]}"
            ) from err
        if not isinstance(body, dict):
            raise ViessmannConnectionError(f"{method} {path}: unexpected payload")

        code = body.get("code")
        if code not in OK_CODES and code != "0":
            message = str(body.get("msg") or "unknown error")
            endpoint = f"{method} {path}"
            if status == 401 or code in (401, "401"):
                if authenticated and retry:
                    _LOGGER.debug("Token rejected, logging in again")
                    self._token = None
                    return await self._request(
                        method,
                        path,
                        data=data,
                        json_body=json_body,
                        params=params,
                        extra_headers=extra_headers,
                        authenticated=authenticated,
                        retry=False,
                    )
                raise ViessmannAuthError(f"{endpoint}: {message}")
            raise ViessmannApiError(code, message, endpoint)

        if status == 401:
            if authenticated and retry:
                self._token = None
                return await self._request(
                    method,
                    path,
                    data=data,
                    json_body=json_body,
                    params=params,
                    extra_headers=extra_headers,
                    authenticated=authenticated,
                    retry=False,
                )
            raise ViessmannAuthError(f"{method} {path}: HTTP 401")

        return body

    # ------------------------------------------------------------------ auth

    async def async_get_token(self) -> str:
        if self._token is None:
            async with self._login_lock:
                if self._token is None:
                    token = await self._async_login()
                    self._token = token
        return self._token

    async def _async_login(self) -> str:
        try:
            body = await self._request(
                "POST",
                ENDPOINT_LOGIN,
                json_body={"phone": self._username, "password": self._password},
                authenticated=False,
            )
        except ViessmannApiError as err:
            # The cloud answers 500 "系统错误" for a wrong phone/password pair.
            raise ViessmannAuthError(str(err)) from err
        data = _unwrap_data(body) or {}
        token = None
        user_id = None
        for candidate in _walk_dicts(data):
            token = token or _first(candidate, "access_token", "accessToken", "token")
            user_id = user_id or _first(candidate, "userId", "user_id", "id")
        if not token:
            _LOGGER.warning("Login response without a token: %s", body)
            raise ViessmannAuthError("登录成功但没有返回 access_token")
        if user_id is not None:
            self._user_id = str(user_id)
        _LOGGER.debug("Logged in as user %s", self._user_id)
        return str(token)

    async def async_get_user_info(self) -> dict[str, Any]:
        token = await self.async_get_token()
        body = await self._request(
            "GET",
            ENDPOINT_USER_INFO,
            params={"authToken": token},
            extra_headers={"authToken": token},
            authenticated=True,
        )
        data = _unwrap_data(body)
        info = data if isinstance(data, dict) else {}
        user_id = _first(info, "userId", "user_id", "id")
        if user_id is not None:
            self._user_id = str(user_id)
        return info

    @property
    def user_id(self) -> str | None:
        return self._user_id

    # --------------------------------------------------------------- devices

    async def async_get_devices(self, refresh: bool = False) -> list[dict[str, Any]]:
        """Return every boiler of the account, with its physicsId."""
        if self._devices is not None and not refresh:
            return self._devices

        if self._user_id is None:
            try:
                await self.async_get_user_info()
            except ViessmannError as err:
                _LOGGER.debug("user/info failed, continuing with the login token: %s", err)

        families = await self._async_family_list()

        devices: list[dict[str, Any]] = []
        for family in families:
            family_id = _first(family, "familyId", "family_id", "id")
            if family_id is None:
                continue
            payload = await self._async_family_devices(str(family_id))
            seen: set[str] = set()
            for node in _walk_dicts(payload):
                for key in ("boilerInfos", "boilers", "deviceInfos", "devices"):
                    for boiler in _as_dict_list(node.get(key)):
                        physics_id = _first(boiler, "physicsId", "physics_id", "deviceId")
                        if physics_id is None or str(physics_id) in seen:
                            continue
                        seen.add(str(physics_id))
                        devices.append(self._normalise_device(boiler, family))
        self._devices = devices
        return devices

    async def _async_family_list(self) -> list[dict[str, Any]]:
        """Fetch families, tolerating a cloud that wants no userId at all."""
        payload = {"userId": self._user_id} if self._user_id else {}
        try:
            body = await self._request("POST", ENDPOINT_FAMILY_LIST, data=payload)
        except ViessmannApiError as err:
            if not payload:
                raise
            _LOGGER.debug("family/list with userId failed (%s), retrying without", err)
            body = await self._request("POST", ENDPOINT_FAMILY_LIST, data={})
        return _as_dict_list(_unwrap_data(body))

    async def _async_family_devices(self, family_id: str) -> Any:
        """v2 endpoint, with the older path as a fallback for some app versions."""
        try:
            body = await self._request(
                "POST", ENDPOINT_FAMILY_DEVICES, data={"familyId": family_id}
            )
        except ViessmannApiError as err:
            _LOGGER.debug("familyDevices/v2 failed (%s), trying v1 path", err)
            body = await self._request(
                "POST", ENDPOINT_FAMILY_DEVICES_V1, data={"familyId": family_id}
            )
        return _unwrap_data(body)

    @staticmethod
    def _normalise_device(boiler: dict[str, Any], family: dict[str, Any]) -> dict[str, Any]:
        physics_id = str(_first(boiler, "physicsId", "physics_id", "deviceId"))
        name = _first(boiler, "name", "boilerName", "deviceName", "roomName")
        return {
            "physics_id": physics_id,
            "name": str(name) if name else "壁挂炉",
            "family_id": str(_first(family, "familyId", "family_id", "id") or ""),
            "family_name": str(_first(family, "name", "familyName") or ""),
            "model": _first(boiler, "model", "deviceModel", "productName"),
            "raw": boiler,
        }

    async def async_get_device_detail(self, physics_id: str) -> dict[str, Any]:
        body = await self._request(
            "POST", ENDPOINT_DEVICE_DETAIL, data={"physicsId": physics_id}
        )
        items = _as_dict_list(_unwrap_data(body))
        if not items:
            raise ViessmannApiError(None, "设备详情为空")
        # The app's detail payload is a one-element list; some versions wrap
        # the useful part in "boilerRequestData".
        item = items[0]
        return item

    async def async_get_scan_status(self, physics_id: str) -> dict[str, Any]:
        body = await self._request(
            "POST", ENDPOINT_SCAN_STATUS, data={"physicsId": physics_id}
        )
        items = _as_dict_list(_unwrap_data(body))
        return items[0] if items else {}

    # -------------------------------------------------------------- controls

    async def async_set_dhw_temperature(self, physics_id: str, temperature: float) -> None:
        await self._request(
            "POST",
            ENDPOINT_SET_DHW_TEMP,
            data={"physicsIds": physics_id, "temp": str(int(round(temperature)))},
        )

    async def async_set_heating_temperature(self, physics_id: str, temperature: float) -> None:
        await self._request(
            "POST",
            ENDPOINT_SET_CH_TEMP,
            data={"physicsIds": physics_id, "temp": str(int(round(temperature)))},
        )

    async def async_set_mode(self, physics_id: str, mode: int) -> None:
        await self._request(
            "POST",
            ENDPOINT_SET_MODE,
            data={"physicsIds": physics_id, "mode": str(int(mode))},
        )


__all__ = [
    "ViessmannApi",
    "ViessmannApiError",
    "ViessmannAuthError",
    "ViessmannConnectionError",
    "ViessmannError",
    "as_float",
    "as_int",
    "first",
]

first = _first
as_float = _as_float
as_int = _as_int
