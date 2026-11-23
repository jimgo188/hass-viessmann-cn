"""Unit tests of the API client against a fake Viessmann cloud.

    /home/ubuntu/hermes_work/.ha-venv/bin/python tests/test_api.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiohttp  # noqa: E402

from custom_components.viessmann_cn.api import (  # noqa: E402
    ViessmannApi,
    ViessmannAuthError,
    ViessmannConnectionError,
)
from tests.fake_api import FakeCloud  # noqa: E402


async def main() -> int:
    failures: list[str] = []

    def check(name, got, want):
        if got != want:
            failures.append(f"{name}: {got!r} != {want!r}")
            print(f"  ✗ {name}: {got!r} != {want!r}")
        else:
            print(f"  ✓ {name} = {got!r}")

    fake = FakeCloud(write_delay=0.4)
    base_url = await fake.start()
    print(f"fake cloud on {base_url}")

    async with aiohttp.ClientSession() as session:
        print("1. 登录 / 设备发现")
        api = ViessmannApi(session, fake.username, fake.password, base_url)
        check("token", await api.async_get_token() is not None, True)
        info = await api.async_get_user_info()
        check("userId", api.user_id, "424242")
        check("用户信息手机号", info.get("phone"), fake.username)
        devices = await api.async_get_devices()
        check("设备数量", len(devices), 1)
        check("physicsId", devices[0]["physics_id"], "P-1000")
        check("设备名", devices[0]["name"], "壁挂炉")
        check("型号", devices[0]["model"], "Vitodens 100-W")

        print("2. 状态读取")
        detail = await api.async_get_device_detail("P-1000")
        check("detail 是 dict", isinstance(detail, dict), True)
        check("dhwSet", detail["boilerRequestData"]["dhwSet"], 48)
        scan = await api.async_get_scan_status("P-1000")
        check("dhwProbe", scan.get("dhwProbe"), 47)
        check("fire", scan.get("fire"), 1)

        print("3. 写生活热水温度（云端延迟生效）")
        await api.async_set_dhw_temperature("P-1000", 52)
        check("请求已发出", fake.set_calls[-1], ("dhw", "52"))
        # 立刻读还是旧值，等 1 秒后才变
        await asyncio.sleep(0.6)
        fresh = await api.async_get_device_detail("P-1000")
        check("延迟后回读", fresh["boilerRequestData"]["dhwSet"], 52)

        print("4. token 失效后自动重新登录")
        fake.valid_tokens.clear()
        logins = fake.login_count
        scan = await api.async_get_scan_status("P-1000")
        check("重新登录一次", fake.login_count, logins + 1)
        check("重登后仍能读取", scan.get("dhwProbe"), 47)

        print("5. 错误密码")
        bad = ViessmannApi(session, fake.username, "wrong", base_url)
        try:
            await bad.async_get_token()
        except ViessmannAuthError as err:
            check("AuthError", "500" in str(err) or "系统" in str(err), True)
        else:
            check("AuthError", "not raised", "raised")

        print("6. 服务器不可达")
        dead = ViessmannApi(session, "x", "y", "http://127.0.0.1:9")
        try:
            await dead.async_get_token()
        except ViessmannConnectionError:
            check("ConnectionError", True, True)
        else:
            check("ConnectionError", "not raised", "raised")

        print("7. 请求头与表单编码")
        check(
            "innerKey",
            fake.last_detail_headers.get("innerKey"),
            "81F862CB8ABBE1FD66E7C452431CE679",
        )
        check("form 编码", fake.last_detail_content_type, "application/x-www-form-urlencoded")

    await fake.stop()
    print()
    if failures:
        print(f"失败 {len(failures)} 项")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
