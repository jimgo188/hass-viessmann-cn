# Viessmann CN (菲斯曼互联) for Home Assistant

把「菲斯曼互联」App 里的中国区壁挂炉接进 Home Assistant：采暖、生活热水、
运行状态、故障与燃烧状态。纯云端集成，用 App 的账号密码登录，不需要抓包、
不需要改路由器、也不依赖米家。

## 为什么不用 ViCare 官方集成

菲斯曼中国区的设备连的是 `api.viessmann.cn`（国内独立服务器），
和欧洲 / 国际的 ViCare 账号体系完全不通。官方 `vicare` 集成登录不了这些设备；
本集成直接说中国区 App 的接口。

如果设备已经在米家里（型号 `vihtb.boiler.v100` 一类），米家那边通常只能看到
很有限的属性，本集成不依赖它。

## 实体

每台壁挂炉一个设备，包含：

| 实体 | 说明 |
|---|---|
| `water_heater.<名称>_domestic_hot_water` | 生活热水：当前水温、目标水温（1 °C 步进，范围取自锅炉） |
| `climate.<名称>_heating` | 采暖：出水温度、目标温度、开（采暖+热水）/关（仅热水） |
| `sensor.*_dhw_temperature` | 生活热水温度 |
| `sensor.*_heating_flow_temperature` | 采暖出水温度 |
| `sensor.*_operating_mode` | 运行模式（待机 / 仅生活热水 / 采暖+生活热水） |
| `sensor.*_fault_code` | 故障码，属性里带原始运行状态 |
| `sensor.*_firmware` | WiFi 固件版本（诊断） |
| `binary_sensor.*_burning` | 是否正在燃烧 |
| `binary_sensor.*_fault` | 是否报故障 |

把 `climate` 设为「关」写入的是**关闭采暖、保留生活热水**（模式 15），
不是切断锅炉电源；防冻保护仍在固件里生效。

## 安装

### HACS（推荐）

1. HACS → 集成 → 右上角 ⋮ → **自定义存储库**
2. 添加 `https://github.com/jimgo188/hass-viessmann-cn`，类别 **Integration**
3. 安装后重启 Home Assistant
4. 设置 → 设备与服务 → 添加集成 → 搜 **Viessmann CN**

### 手动

把 `custom_components/viessmann_cn/` 拷进 HA 的 `/config/custom_components/`，重启。

## 配置

填「菲斯曼互联」App 的**手机号 + 密码**。集成会登录、拉取家庭设备列表，
账号下没有绑定的壁挂炉会拒绝添加。

- 刷新间隔在集成 → 配置（选项）里改，默认 60 秒，最小 15 秒。
  菲斯曼云端本身刷新不快，调太小只会多打请求。
- 密码错误、账号被风控时会自动进入「重新登录」流程。
- 集成 → 诊断 可以导出云端返回的原始 JSON（手机号打码、不含密码），
  字段对不上时把它贴出来就能定位。

## 已知限制

- **只能云端轮询**。设备不开放局域网协议，App 也是走云；因此断网时 HA
  里的状态会停在最后一次成功读取。
- **写入有延迟**。云端接命令很快，但回读要 1~3 秒，所以设置温度后
  集成会轮询确认，一般 2~4 秒后才在界面上落定。
- 运行模式的取值（10 待机 / 15 仅热水 / 20 采暖+热水）来自对 App 的抓包
  与社区实现，不同型号可能有差异；写入前建议先在 App 里确认。
- 生活热水的「开关」没有独立接口，只由运行模式决定。
- 这是非官方集成，接口随时可能被厂商改动。

## 安全

燃气壁挂炉涉及用气用电安全。请保留锅炉自身的温控与防冻逻辑，不要把
HA 自动化当成唯一的安全保护；出门前在 App 里确认状态，比相信云端更可靠。

## 协议摘要

```
POST https://api.viessmann.cn/idass/user/login        {"phone","password"} -> data.data.access_token
GET  /idass/user/info?authToken=...                  -> userId
POST /api/family/list              userId=...        -> [{familyId}]
POST /api/home/familyDevices/v2    familyId=...      -> defaultRoom.boilerInfos[].physicsId
POST /api/device/detail            physicsId=...     -> [{boilerRequestData:{chSet,chMin,chMax,dhwSet,dhwMinSet,dhwMaxSet,mode},faultStatus}]
POST /api/device/scanStatus        physicsId=...     -> [{chProbe,dhwProbe,fire,runningStatus,modeName,wifiFirmwareVersion}]
POST /api/3/sendToDevice/setDhwTemp   physicsIds=...&temp=48
POST /api/3/sendToDevice/setChsetTemp physicsIds=...&temp=60
POST /api/3/sendToDevice/setMode      physicsIds=...&mode=20
```

请求头需要 App 的 `innerKey`（非密钥，仅指纹）和 `Authorization: <token>`；
业务错误放在 JSON 的 `code/msg` 里，401 表示登录态失效。

协议整理参考了 [stevenjoezhang/hass-viessmann-cn](https://github.com/stevenjoezhang/hass-viessmann-cn)
和作者对「菲斯曼互联」App 的抓包分析；本仓库重写了实现（独立 domain、
DataUpdateCoordinator、重新登录、写后回读校验、诊断导出、实体中英双语）。

## 测试

```sh
python3 tests/test_api.py   # 需要 aiohttp
python3 tests/test_e2e.py   # 需要 homeassistant，用 HA 自己的 venv 最省事
```

`tests/fake_api.py` 复刻了真实接口的嵌套结构（登录 `data.data`、列表包装、
写入 1 秒后生效），所以解析和写后校验都是对着真实形状验证的，而不是自说自话。

## 免责声明

非官方集成，仅供研究学习。作者不对因使用本集成造成的设备异常、费用或
安全问题负责。
