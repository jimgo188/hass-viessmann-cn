"""A tiny stateful fake of the Viessmann China cloud, for tests.

Mirrors the response nesting of the real endpoints (login wraps the payload
in data.data, /api endpoints answer {"code":0,"data":[...]}), and applies
writes with a delay like the real boiler does.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

TOKEN = "test-token-1"
USER_ID = "424242"
PHYSICS_ID = "P-1000"
FAMILY_ID = "F-1"


class FakeCloud:
    def __init__(self, *, write_delay: float = 1.0) -> None:
        self.write_delay = write_delay
        self.username = "13800000000"
        self.password = "secret"
        self.token = TOKEN

        self.dhw_set = 48
        self.dhw_min = 35
        self.dhw_max = 60
        self.ch_set = 55
        self.ch_min = 30
        self.ch_max = 80
        self.mode = 20
        self.fault = 0
        self.fire = 1

        self.dhw_probe = 47
        self.ch_probe = 45

        self.fail_family_v2 = False

        self.requests: list[tuple[str, str]] = []
        self.last_detail_headers: dict[str, str] = {}
        self.last_detail_content_type: str | None = None
        self.login_count = 0
        self.set_calls: list[tuple[str, str]] = []
        self.valid_tokens: set[str] = {TOKEN}
        self.runner: web.AppRunner | None = None
        self.port = 0

    # --------------------------------------------------------------- helpers

    def detail(self) -> dict[str, Any]:
        return {
            "boilerRequestData": {
                "chSet": self.ch_set,
                "chMin": self.ch_min,
                "chMax": self.ch_max,
                "dhwSet": self.dhw_set,
                "dhwMinSet": self.dhw_min,
                "dhwMaxSet": self.dhw_max,
                "mode": self.mode,
            },
            "faultStatus": self.fault,
            "deviceModel": "Vitodens 100-W",
        }

    def scan(self) -> dict[str, Any]:
        return {
            "chProbe": self.ch_probe,
            "dhwProbe": self.dhw_probe,
            "fire": self.fire,
            "runningStatus": 2,
            "sysPattern": 1,
            "modeName": "采暖",
            "wifiFirmwareVersion": "1.2.3",
        }

    def _schedule(self, apply) -> None:
        asyncio.get_running_loop().call_later(self.write_delay, apply)

    async def _auth(self, request: web.Request) -> bool:
        if request.headers.get("Authorization") not in self.valid_tokens:
            return False
        if request.headers.get("innerKey") != "81F862CB8ABBE1FD66E7C452431CE679":
            return False
        return True

    @staticmethod
    def _unauthorized(message: str = "not logged in") -> web.Response:
        return web.json_response(
            {"code": 401, "msg": message, "data": None}, status=401
        )

    # -------------------------------------------------------------- handlers

    async def handle_login(self, request: web.Request) -> web.Response:
        self.login_count += 1
        body = await request.json()
        if body.get("phone") != self.username or body.get("password") != self.password:
            return web.json_response(
                {"code": 500, "msg": "系统错误，请联系开发人员！", "data": None},
                status=500,
            )
        token = f"test-token-{self.login_count}"
        self.valid_tokens.add(token)
        return web.json_response(
            {
                "code": 0,
                "msg": "操作成功",
                "data": {
                    "statusCode": 200,
                    "data": {"access_token": token, "userId": USER_ID, "expiresIn": 7200},
                },
            }
        )

    async def handle_user_info(self, request: web.Request) -> web.Response:
        if not await self._auth(request):
            return self._unauthorized()
        return web.json_response(
            {"code": 0, "msg": "操作成功", "data": {"userId": USER_ID, "phone": self.username}}
        )

    async def handle_family_list(self, request: web.Request) -> web.Response:
        if not await self._auth(request):
            return self._unauthorized()
        return web.json_response(
            {
                "code": 0,
                "data": [{"familyId": FAMILY_ID, "familyName": "我的家"}],
            }
        )

    async def handle_family_devices(self, request: web.Request) -> web.Response:
        if not await self._auth(request):
            return self._unauthorized()
        if self.fail_family_v2 and request.path.endswith("/v2"):
            return web.json_response(
                {"code": 500, "msg": "系统错误", "data": None}, status=500
            )
        return web.json_response(
            {
                "code": 0,
                "data": {
                    "defaultRoom": {
                        "boilerInfos": [
                            {
                                "physicsId": PHYSICS_ID,
                                "name": "壁挂炉",
                                "model": "Vitodens 100-W",
                            }
                        ]
                    }
                },
            }
        )

    async def handle_detail(self, request: web.Request) -> web.Response:
        self.last_detail_headers = dict(request.headers)
        self.last_detail_content_type = request.content_type
        if not await self._auth(request):
            return self._unauthorized()
        return web.json_response({"code": 0, "data": [self.detail()]})

    async def handle_scan(self, request: web.Request) -> web.Response:
        if not await self._auth(request):
            return self._unauthorized()
        return web.json_response({"code": 0, "data": [self.scan()]})

    async def handle_set_dhw(self, request: web.Request) -> web.Response:
        if not await self._auth(request):
            return self._unauthorized()
        form = await request.post()
        temp = float(form["temp"])
        self.set_calls.append(("dhw", form["temp"]))
        self._schedule(lambda: setattr(self, "dhw_set", temp))
        return web.json_response({"code": 0, "data": None})

    async def handle_set_ch(self, request: web.Request) -> web.Response:
        if not await self._auth(request):
            return self._unauthorized()
        form = await request.post()
        temp = float(form["temp"])
        self.set_calls.append(("ch", form["temp"]))
        self._schedule(lambda: setattr(self, "ch_set", temp))
        return web.json_response({"code": 0, "data": None})

    async def handle_set_mode(self, request: web.Request) -> web.Response:
        if not await self._auth(request):
            return self._unauthorized()
        form = await request.post()
        mode = int(float(form["mode"]))
        self.set_calls.append(("mode", form["mode"]))
        self._schedule(lambda: setattr(self, "mode", mode))
        return web.json_response({"code": 0, "data": None})

    async def handle_catch(self, request: web.Request) -> web.Response:
        self.requests.append((request.method, request.path))
        return web.json_response({"code": 404, "msg": "not found", "data": None}, status=404)

    # -------------------------------------------------------------- lifecycle

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/idass/user/login", self.handle_login)
        app.router.add_get("/idass/user/info", self.handle_user_info)
        app.router.add_post("/api/family/list", self.handle_family_list)
        app.router.add_post("/api/home/familyDevices/v2", self.handle_family_devices)
        app.router.add_post("/api/home/familyDevices", self.handle_family_devices)
        app.router.add_post("/api/device/detail", self.handle_detail)
        app.router.add_post("/api/device/scanStatus", self.handle_scan)
        app.router.add_post("/api/3/sendToDevice/setDhwTemp", self.handle_set_dhw)
        app.router.add_post("/api/3/sendToDevice/setChsetTemp", self.handle_set_ch)
        app.router.add_post("/api/3/sendToDevice/setMode", self.handle_set_mode)
        app.router.add_route("*", "/{tail:.*}", self.handle_catch)
        return app

    async def start(self, port: int = 0) -> str:
        self.runner = web.AppRunner(self.app())
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", port)
        await site.start()
        # aiohttp exposes the bound port on the site's server sockets
        self.port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        return f"http://127.0.0.1:{self.port}"

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
