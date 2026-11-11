# AGENTS.md

GUGUBot — MCDReforged 插件，实现 Minecraft 服务器与 QQ 群互通（聊天同步、白名单、玩家绑定、违禁词、关键词、多服互联）。Python ≥ 3.10，uv 管理（`.python-version` / `uv.lock`）。项目以中文为主（README、docs、代码注释、i18n）。

## 布局

- 插件源码在 `GUGUbot/`（大写目录）下的 `gugubot/` 包，**不在仓库根目录**。
- `pyproject.toml` 只是元数据 + `docs` 可选依赖组；`pip install .` 装不出插件包，本地开发用 `PYTHONPATH=GUGUbot` 直接引用源码。
- 运行时依赖以 `GUGUbot/requirements.txt` 为准（含 mcstatus、websocket-client、websocket-server；pyproject 的 dependencies 不全）。
- 插件元数据在 `GUGUbot/mcdreforged.plugin.json`（id `gugubot`）；未写 entrypoint，入口是 `gugubot/__init__.py` 的 `on_load`，所有 connector/system 在此接线。
- 插件前置（plugin.json `dependencies`）：whitelist_api≥1.3.0、mg_events≥0.2.3、player_ip_logger≥1.1.0。

## 命令

```bash
# 测试（stdlib unittest，无 pytest 配置；PYTHONPATH 必须指向 GUGUbot）
PYTHONPATH=GUGUbot python -m unittest discover -s tests
# 单个模块
PYTHONPATH=GUGUbot python -m unittest tests.test_websocket
# 测试依赖（临时跑可用 uv run --with mcdreforged --with requests --with ruamel-yaml --with websocket-client --with websocket-server --with mcstatus）
pip install mcdreforged requests "ruamel.yaml" websocket-client websocket-server mcstatus

# 文档（MkDocs Material；push 到 main 且改动 docs/、mkdocs.yml、pyproject.toml 时 CI 自动部署 GitHub Pages）
pip install -e ".[docs]"
mkdocs serve

# 打包 .mcdr（= 压缩 GUGUbot/ 目录内容，CI package.yml 同款）
cd GUGUbot && zip -r ../gugubot.mcdr . -x "*/__pycache__/*" "*.pyc"
```

## CI 自动同步的文件（勿手动改）

- 根目录 `default_config.yml` ← CI 从 `GUGUbot/gugubot/config/defaults/default_config.yml` 复制，**只改后者**。
- `GUGUbot/README.md` ← CI 从根 `README.md` 复制，**只改根 README**。

## 版本号两处同步

改版本必须同时更新 `GUGUbot/mcdreforged.plugin.json` 和 `pyproject.toml` 的 `version`（release 工作流按 plugin.json 的版本命名产物 `gugubot-vX.X.X.mcdr`）。源码中没有其他硬编码版本。

## 架构（消息流）

- `connector/` — 连接与路由：`QQWebSocketConnector`（NapCat/LLOneBot OneBot，CQ 码）、`MCConnector`（游戏事件）、`BridgeConnector`（minecraft_bridge 多服互联）、`TestConnector`；`ConnectorManager` 统一收发。
- `parser/` — 入站消息解析（qq_parser / mc_parser / basic_parser，`InfoSource` 抽象消息来源）。
- `builder/` — 出站消息构建（basic / qq / mc builder，模板来自配置）。
- `logic/system/` — QQ/游戏命令系统：继承 `BasicSystem`，在 `on_load` 注册进 `SystemManager`（支持 before/after 排序）；开关由配置 `[system][<name>][enable]` 控制。
- `logic/plugins/` — 事件钩子：成就/死亡（mg_event）、进出服通知、不活跃/未绑定检查、跨服广播、激活白名单。
- `api.py` — 给其他 MCDR 插件的公开 API：对方监听 `gugubot.register`（`REGISTER_EVENT`）注册 `#命令`，通过 `CommandContext.reply()/rcon()` 回复与执行。**外部插件扩展命令走这条路，不要改 BasicSystem 或源码**。
- `constant/*.yml` — 机器人人格风格预设（normal、傲娇、萝莉…），由 StyleManager 加载切换。
- 旧 v1 配置在 `on_load` 时由 `utils/config_migrator.py` 自动迁移到 v2。
- 用户可见文案走 MCDR i18n（`server.tr("gugubot.system.<name>.<key>")`），键定义在 `GUGUbot/lang/zh_cn.yml` 与 `en_us.yml`，**两个语言文件都要加**。

## 测试现状（2026-11 于 HEAD 验证）

- `tests/test_config.py`、`tests/test_parser.py` 引用的是重构前的旧模块路径（如 `gugubot.config.BasicConfig`、`gugubot.parser.message.*`），当前代码上 import 即失败。
- `tests/test_plugin_api.py` 部分用例的 fixture 与现行 `Source` API 有漂移，同样红。
- `test_websocket`、`test_tps_parser` 等可通过 → 验证自己的改动请跑**定向测试**，不要把全量红当成自己的回归；如顺手，修复过期测试优于绕过。
