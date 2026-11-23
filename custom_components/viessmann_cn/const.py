"""Constants for the Viessmann China (菲斯曼互联) integration."""

from __future__ import annotations

import os
from datetime import timedelta

DOMAIN = "viessmann_cn"
NAME = "Viessmann CN"
MANUFACTURER = "Viessmann 菲斯曼"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BASE_URL = "base_url"
CONF_SCAN_INTERVAL = "scan_interval"

# The app talks to the Chinese cloud only; there is no ViCare/viessmann.com
# account overlap for these devices. The override exists for tests.
API_BASE_URL = os.environ.get("VIESSMANN_CN_API_BASE_URL", "https://api.viessmann.cn")

ENDPOINT_LOGIN = "/idass/user/login"
ENDPOINT_USER_INFO = "/idass/user/info"
ENDPOINT_FAMILY_LIST = "/api/family/list"
ENDPOINT_FAMILY_DEVICES = "/api/home/familyDevices/v2"
ENDPOINT_DEVICE_DETAIL = "/api/device/detail"
ENDPOINT_SCAN_STATUS = "/api/device/scanStatus"

ENDPOINT_SET_CH_TEMP = "/api/3/sendToDevice/setChsetTemp"
ENDPOINT_SET_DHW_TEMP = "/api/3/sendToDevice/setDhwTemp"
ENDPOINT_SET_MODE = "/api/3/sendToDevice/setMode"

# Static header lifted from the official app (v5.x). The cloud rejects
# requests without it; it is not a credential, just an app fingerprint.
INNER_KEY = "81F862CB8ABBE1FD66E7C452431CE679"
USER_AGENT = "FeiSiMan/5.0.5 (iPhone; iOS 26.2.1; Scale/3.00)"

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-Hans;q=1",
    "innerKey": INNER_KEY,
}
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded;charset=UTF-8"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 900
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

REQUEST_TIMEOUT = 20
# A cloud write is not immediate: poll the detail endpoint until it sticks.
VERIFY_TIMEOUT = 8.0
VERIFY_INTERVAL = 1.5

# 运行模式 (boilerRequestData.mode), as observed in the app / reference
# implementations. 10 = standby (frost protection), 15 = domestic hot water
# only, 20 = heating + domestic hot water.
MODE_STANDBY = 10
MODE_DHW_ONLY = 15
MODE_HEATING_DHW = 20

MODE_NAMES: dict[int, str] = {
    MODE_STANDBY: "待机",
    MODE_DHW_ONLY: "仅生活热水",
    MODE_HEATING_DHW: "采暖+生活热水",
}

# Fallback limits, overridden by the values the boiler reports.
FALLBACK_DHW_MIN = 35.0
FALLBACK_DHW_MAX = 60.0
FALLBACK_CH_MIN = 20.0
FALLBACK_CH_MAX = 80.0
