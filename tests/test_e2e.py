"""End-to-end test: real Home Assistant, fake Viessmann cloud.

    /home/ubuntu/hermes_work/.ha-venv/bin/python tests/test_e2e.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIG_DIR = "/tmp/ha-viessmann-e2e"
FAKE_PORT = 18971

# The component reads the base URL from the environment at import time; point
# it at the fake cloud before Home Assistant imports anything.
os.environ["VIESSMANN_CN_API_BASE_URL"] = f"http://127.0.0.1:{FAKE_PORT}"

from homeassistant import bootstrap, core  # noqa: E402
from homeassistant.runner import RuntimeConfig  # noqa: E402

from tests.fake_api import FakeCloud  # noqa: E402


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.levelname} {record.name}: {record.getMessage()}")


async def main() -> int:
    failures: list[str] = []

    def check(name, got, want):
        if got != want:
            failures.append(f"{name}: {got!r} != {want!r}")
            print(f"  ✗ {name}: {got!r} != {want!r}", flush=True)
        else:
            print(f"  ✓ {name} = {got!r}", flush=True)

    fake = FakeCloud(write_delay=1.0)
    await fake.start(FAKE_PORT)

    Path(CONFIG_DIR, "custom_components").mkdir(parents=True, exist_ok=True)
    shutil.rmtree(Path(CONFIG_DIR, ".storage"), ignore_errors=True)
    link = Path(CONFIG_DIR, "custom_components", "viessmann_cn")
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(ROOT / "custom_components" / "viessmann_cn")
    Path(CONFIG_DIR, "configuration.yaml").write_text(
        "homeassistant:\n  name: E2E\n  time_zone: Asia/Shanghai\n", encoding="utf-8"
    )

    handler = ListHandler()
    logging.getLogger("custom_components.viessmann_cn").addHandler(handler)
    logging.getLogger("custom_components.viessmann_cn").setLevel(logging.DEBUG)

    print("1. 启动 Home Assistant", flush=True)
    runtime = RuntimeConfig(config_dir=CONFIG_DIR, skip_pip=True)
    hass: core.HomeAssistant = await bootstrap.async_setup_hass(runtime)
    assert hass is not None
    await hass.async_start()
    print(f"  HA {core.__version__} 启动完成", flush=True)

    print("2. 配置流程（手机号+密码）", flush=True)
    flow = await hass.config_entries.flow.async_init(
        "viessmann_cn", context={"source": "user"}
    )
    check("flow 类型", flow["type"], "form")
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"username": fake.username, "password": fake.password}
    )
    await hass.async_block_till_done()
    check("配置结果", result["type"], "create_entry")
    entries = hass.config_entries.async_entries("viessmann_cn")
    check("配置条目数量", len(entries), 1)
    entry = entries[0]
    check("unique_id", entry.unique_id, "user_424242")

    print("2b. 错误密码被拒绝", flush=True)
    bad_flow = await hass.config_entries.flow.async_init(
        "viessmann_cn", context={"source": "user"}
    )
    bad_result = await hass.config_entries.flow.async_configure(
        bad_flow["flow_id"], {"username": fake.username, "password": "wrong-password"}
    )
    check("仍是表单", bad_result["type"], "form")
    check("错误提示", bad_result["errors"].get("base"), "invalid_auth")
    hass.config_entries.flow.async_abort(bad_flow["flow_id"])

    print("3. 实体", flush=True)
    await asyncio.sleep(0.5)
    await hass.async_block_till_done()
    states = {s.entity_id: s for s in hass.states.async_all()}
    mine = {
        eid: st
        for eid, st in states.items()
        if eid.split(".", 1)[0]
        in ("water_heater", "climate", "sensor", "binary_sensor")
        and st.attributes.get("friendly_name", "").startswith("壁挂炉")
    }
    for eid, st in sorted(mine.items()):
        print(f"    {eid} = {st.state} {dict(st.attributes)}", flush=True)

    dhw_id = next((e for e in mine if e.startswith("water_heater.")), None)
    heat_id = next((e for e in mine if e.startswith("climate.")), None)
    check("生活热水实体", dhw_id is not None, True)
    check("采暖实体", heat_id is not None, True)

    if dhw_id:
        st = states[dhw_id]
        check("热水当前温度", st.attributes.get("current_temperature"), 47.0)
        check("热水设定温度", st.attributes.get("temperature"), 48.0)
        check("热水最小温度", st.attributes.get("min_temp"), 35.0)
        check("热水最大温度", st.attributes.get("max_temp"), 60.0)
    if heat_id:
        st = states[heat_id]
        check("采暖当前温度", st.attributes.get("current_temperature"), 45.0)
        check("采暖设定温度", st.attributes.get("temperature"), 55.0)
        check("hvac_mode", st.state, "heat")
        check("hvac_action", st.attributes.get("hvac_action"), "heating")

    suffix_checks = {
        "_dhw_temperature": "47.0",
        "_heating_flow_temperature": "45.0",
        "_operating_mode": "采暖+生活热水",
        "_burning": "on",
        "_fault": "off",
    }
    for suffix, want in suffix_checks.items():
        hit = next((e for e in mine if e.endswith(suffix)), None)
        check(f"传感器 {suffix}", states[hit].state if hit else None, want)

    print("4. 调生活热水温度", flush=True)
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {"entity_id": dhw_id, "temperature": 52},
        blocking=True,
    )
    await hass.async_block_till_done()
    check("云端收到写请求", ("dhw", "52") in fake.set_calls, True)
    check("云端值", fake.dhw_set, 52.0)
    st = hass.states.get(dhw_id)
    check("实体目标温度", st.attributes.get("temperature"), 52.0)

    print("5. 采暖开关与温度", flush=True)
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": heat_id, "hvac_mode": "off"},
        blocking=True,
    )
    await hass.async_block_till_done()
    check("云端模式", fake.mode, 15)
    check("实体模式", hass.states.get(heat_id).state, "off")

    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": heat_id, "hvac_mode": "heat"},
        blocking=True,
    )
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": heat_id, "temperature": 60},
        blocking=True,
    )
    await hass.async_block_till_done()
    check("云端模式（恢复）", fake.mode, 20)
    check("云端采暖设定", fake.ch_set, 60.0)
    check("实体采暖设定", hass.states.get(heat_id).attributes.get("temperature"), 60.0)

    print("6. 诊断信息不泄露密码", flush=True)
    from custom_components.viessmann_cn.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    diag = await async_get_config_entry_diagnostics(hass, entry)
    dump = repr(diag)
    check("诊断里有 detail", "boilerRequestData" in dump, True)
    check("诊断里有 scan", "dhwProbe" in dump, True)
    check("密码不在诊断里", fake.password in dump, False)
    check("手机号已打码", "138****0000" in dump, True)

    print("6b. 选项：修改轮询间隔", flush=True)
    options_flow = await hass.config_entries.options.async_init(entry.entry_id)
    check("选项表单", options_flow["type"], "form")
    options_result = await hass.config_entries.options.async_configure(
        options_flow["flow_id"], {"scan_interval": 30}
    )
    await hass.async_block_till_done()
    check("选项已保存", options_result["type"], "create_entry")
    check("entry options", entry.options.get("scan_interval"), 30)
    check("重载后间隔生效", entry.runtime_data.update_interval.total_seconds(), 30.0)

    print("7. 卸载", flush=True)
    check("卸载成功", await hass.config_entries.async_unload(entry.entry_id), True)
    await hass.async_block_till_done()

    await hass.async_stop(force=True)
    await fake.stop()

    print()
    errors = [
        r
        for r in handler.records
        if r.startswith("ERROR") or r.startswith("WARNING")
    ]
    if errors:
        print("集成日志中的 WARNING/ERROR：")
        for line in errors[:15]:
            print("  ", line)
    if failures:
        print(f"失败 {len(failures)} 项")
        for item in failures:
            print("  -", item)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
