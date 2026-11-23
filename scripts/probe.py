#!/usr/bin/env python3
"""Print what the Viessmann CN cloud returns for your account.

Run this on a machine that has ``aiohttp`` when the integration shows
``unknown`` values: it prints the raw detail / scanStatus JSON so the field
names can be checked (or pasted into an issue).

    python3 scripts/probe.py --phone 13800000000
    python3 scripts/probe.py --phone 13800000000 --base-url http://127.0.0.1:18971

The password is read from ``VIESSMANN_PASSWORD`` or prompted for, never from
the command line, so it does not end up in your shell history.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp  # noqa: E402

from custom_components.viessmann_cn.api import (  # noqa: E402
    ViessmannApi,
    ViessmannError,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True, help="App 登录手机号")
    parser.add_argument("--base-url", default=None, help="覆盖云端地址（调试用）")
    args = parser.parse_args()

    password = os.environ.get("VIESSMANN_PASSWORD") or getpass.getpass("密码: ")

    async with aiohttp.ClientSession() as session:
        api = ViessmannApi(
            session,
            args.phone,
            password,
            args.base_url or "https://api.viessmann.cn",
        )
        try:
            await api.async_get_token()
            info = await api.async_get_user_info()
            devices = await api.async_get_devices(refresh=True)
            print(f"\n登录成功，userId={api.user_id}，设备 {len(devices)} 台")
            for device in devices:
                print(f"\n=== {device['name']} ({device['physics_id']}) ===")
                detail = await api.async_get_device_detail(device["physics_id"])
                scan = await api.async_get_scan_status(device["physics_id"])
                print("\n-- detail --")
                print(json.dumps(detail, ensure_ascii=False, indent=2))
                print("\n-- scanStatus --")
                print(json.dumps(scan, ensure_ascii=False, indent=2))
            print("\n把上面的 JSON 发出来即可核对字段。")
            return 0
        except ViessmannError as err:
            print(f"失败: {err}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
