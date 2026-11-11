# GUGUBot：消息处理流程（QQ ↔ MC）与 QQ 功能清单

> 基于源码分析（插件版本 2.2.4，`GUGUbot/` 目录），不依赖 README 描述。
> 生成日期：2026-11-10

## 一、QQ 群消息处理链路

```
NapCat/LLOneBot ──WS──▶ QQWebSocketConnector ──▶ QQParser ──▶ SystemManager
                                                                    │ 逐个系统尝试消费
                    ┌───────────────────────────────────────────────┘
                    ▼ 未被消费的普通聊天
              EchoSystem ──▶ ConnectorManager ──▶ MC / Bridge / 其他群
```

### 1. 接入层 `GUGUbot/gugubot/connector/qq_connector.py` + `ws/`

- 插件作为 WebSocket **客户端**连接 NapCat/LLOneBot 的正向 WS（OneBot v11 协议）。
  配置项在 `connector.QQ.connection`：host / port / post_path / `use_ssl` / `token` /
  `verify` / `ca_certs` / `reconnect`。连接时故意关闭 ping/pong（OneBot 端不需要）。
- 收到的 JSON 分两类处理：
  - 带 `echo` 的是 API 调用响应 → 存入 `bot.function_return`，供等待中的协程取；
  - 其余事件 → `server.schedule_task(parser.process_message(raw))` 投递到 MCDR
    事件循环，WS 回调线程不直接执行业务。
- `Bot` 类通过 `__getattr__` 动态代理 OneBot API：`get_*` / `can_*` 自动附加 uuid echo
  并轮询等待返回值（超过 `max_wait_time` 返回 None，过期请求自动清理），其余 action
  发完即忘。

### 2. 解析层 `GUGUbot/gugubot/parser/qq_parser.py`

- 只处理 `post_type ∈ {message, notice, request}`。
- 来源过滤（`_is_valid_source`）：群号必须在 `permissions.group_ids` 或
  `admin_group_ids` 内；私聊仅在 `friend_is_admin=true` 时接收。
- 消息统一转成 OneBot **消息段数组** `[{type, data}]`：
  - `raw_message` 为 CQ 码字符串 → `CQHandler.parse`（正则拆分 CQ 码 + HTML 反转义）；
  - 上报已是数组 → `ArrayHandler.parse` 直通。
- 提取群号 / QQ 号、`sender.card`（群名片优先于昵称）、`is_admin`
  （在 `admin_ids` 或 `admin_group_ids` 内）。
- **回复定向**：消息含 `reply` 段时调用 `get_msg` 拉取原消息；若原消息是机器人自己发的，
  按 `chat_templates` 反向解析出原 MC 玩家名作为 `receiver`。
  即 QQ 里"引用回复某条转发消息" = 在 MC 里 @ 那位玩家。
- `notice` / `request` 事件将 `notice_type` / `request_type` 存为 `event_sub_type`
  （退群解绑依赖 `group_decrease`）。
- `system.bound_notice.exclude_ids` 中的用户消息被静默丢弃。

### 3. 分发层 `GUGUbot/gugubot/logic/system/system_manager.py`

- 按注册顺序逐个调用系统 `process_broadcast_info`，**第一个返回 True 的消费即停止**。
  注册顺序在 `GUGUbot/gugubot/__init__.py` 的 `on_load` 中定义
  （例如 ban_words 被插到索引 1 的位置）。
- 未被消费的普通聊天落到 `EchoSystem`：
  - QQ 私聊消息不转发；
  - 管理群（`admin_group_ids`）消息不转发；
  - 来源 connector `enable_send=False` 时不转发；
  - 目标跳过 `enable_receive=False` 的 connector；
  - 通过 `ConnectorManager.broadcast_processed_info` 并发广播给其他 connector。
- QQ → MC 渲染走 `McMessageBuilder.array_to_rtext`：
  - `at` 段换成绑定玩家名（未绑定显示 QQ 号，@机器人 本身跳过）；
  - `face` 段查 `GUGUbot/gugubot/constant/qq_emoji_map.py` 转中文表情名
    （如 76→赞、14→微笑；低版本 MC 降级为 `[表情]` 文本）；
  - 图片可转 ChatImage / ImagePreview 预览。

### 4. 发送层 `QQWebSocketConnector.send_message`

- 目标群 = `permissions.forward_group_ids`（为空回退 `group_ids`），支持
  group / private / temp 三种目标类型。
- MC → QQ 消息加来源前缀：`chat_templates` 支持 `[{模板: 权重}]` 加权随机，
  占位符 `{display_name}` / `{sender}`；旧的纯字符串列表格式首次使用时自动迁移为
  权重格式并写回配置。
- 剥离 MC 颜色码 `§x`。
- 超过 `max_message_length`（默认 2000）自动分片：
  - 文本优先在换行边界切分，图片按 100 字符估算长度；
  - 多片发送之间随机 sleep 0.5~1.5s，避免触发平台频率限制。

## 二、MC 消息 → QQ 的处理链路

> 与 QQ → MC 共用同一套解析/分发框架，但捕获入口、过滤器与展示格式不同。
> 发送端的模板前缀、颜色码剥离、分片与限流见「一.4 发送层」，本节不重复。

```
MCDR 事件 ──▶ MCConnector.on_message ──▶ MCParser ──▶ SystemManager ──▶ EchoSystem
(玩家聊天)      (仅 info.is_player)         │ 过滤 ignore_mc_command_patterns
                                            ▼ 未被消费
                                   ConnectorManager（排除来源、enable_receive=false）
                                            ▼
                              QQWebSocketConnector.send_message ──▶ 群 / 私聊 / 临时会话
```

### 1. 捕获：来源不止"聊天"一种

| 消息类型 | MCDR 事件 | 处理入口 |
|---|---|---|
| 玩家聊天 | `on_user_info` | `MCConnector.on_message`（仅 `info.is_player` 为真） |
| 玩家进出 | `on_info` | `logic/plugins/player_notice.py`：按 `player_join_patterns` / `player_left_patterns` 正则匹配（第一个捕获组为玩家名） |
| 成就 / 死亡 | `PlayerAdvancementEvent` / `PlayerDeathEvent`（mg_events） | `logic/plugins/mg_event.py` |
| 服务器开关机 | `on_server_startup` / `on_server_stop` | `logic/plugins/server_notice.py` |

### 2. 过滤（`MCParser._ignore_message`）

- `connector.minecraft.ignore_mc_command_patterns`：正则列表，命中的玩家聊天直接丢弃
  （常用于忽略 `!!` 开头的 MCDR 指令等玩家发送的指令文本）。
- `!!qq` 前缀例外放行——它是 MC 端主动发 QQ 的跨平台命令
  （`system.cross_broadcast.qq_command`，见 `cross_broadcast.py`），不能被忽略规则吞掉。

### 3. 解析（`GUGUbot/gugubot/parser/mc_parser.py`）

构造 `BroadcastInfo`：

- `event_type="message"`、`event_sub_type="group"`；
- `sender` / `sender_id` = MC 玩家名；
- `is_admin` = 绑定系统 `PlayerManager.is_admin(玩家名)` 的结果；
- `message` = `CQHandler.parse(content)` 生成的消息段数组（MC 聊天通常是纯文本，
  直接成为 `text` 段）；
- `_source=Source(connector.source)`（来源链，默认 `Minecraft`，供 echo 排除与 Bridge 判断）。

### 4. 分发（`SystemManager.broadcast_command`）

- 与 QQ 来源一致：按注册顺序逐个系统尝试消费，第一个返回 True 即停止。
- 未被消费的普通聊天由 `EchoSystem` 转发：
  - 来源 connector（`connector.minecraft.enable_send`）关闭时整条不转发；
  - 目标排除来源自身和所有 `enable_receive=false` 的 connector；
  - 通过 `ConnectorManager.broadcast_processed_info` **并发**投递给 QQ / Bridge 等目标。
- 游戏内聊天命令（如 `!!qq`、`#...`）若被对应系统消费，则不会作为聊天进入 QQ。

### 5. 到达 QQ 后的处理（`QQWebSocketConnector.send_message`）

- 因来源不是 QQ，消息会加模板前缀（详见 一.4）：
  - `chat_templates` 加权随机，占位符 `{display_name}` = 来源名
    （默认 `Minecraft`，即 `connector.minecraft.source_name`）、`{sender}` = 玩家名；
  - 默认格式：`[Minecraft] 玩家名: 消息内容`。
- 剥离 MC 颜色码 `§x` → 按 `max_message_length`（默认 2000）分片 →
  多片之间随机间隔 0.5~1.5s → 发送到 `forward_group_ids`（为空回退 `group_ids`）。

### 6. 事件通知（非聊天）走专用通知群

开关机、玩家进出、成就/死亡不经过 `EchoSystem`，由各自插件直接构造
`ProcessedInfo` 并广播，目标群为 `connector.QQ.permissions.notice_forward_groups`
（为空回退 `forward_group_ids` / `group_ids`）。各类型开关：

- 开关机：`connector.minecraft.server_start_notice` / `server_stop_notice`
- 玩家进出：`player_join_notice` / `player_left_notice`
  （机器人进出用 `bot_join_notice` / `bot_left_notice`，通过 `bot_names_pattern` 区分）；
  `player_notice_cooldown` 控制离开延迟合并（期间重进则不通知）
- 成就 / 死亡：`connector.minecraft.mc_achievement` / `mc_death`

### 7. 多服（Bridge）场景

- 子服玩家聊天经 `BridgeConnector` 先到主服，再进入上述同一链路转发到 QQ；
- `!!qq` 在子服同样有效（`cross_broadcast.py` 同时识别 `minecraft` 与
  `minecraft_bridge` 来源）；
- `bridge.show_in_game=false` 只影响子服消息**是否显示在主服游戏内**，
  不影响其继续转发到 QQ。

### 8. 与人格风格的关系

`#风格` 的 i18n 覆盖只作用于通知/系统提示等翻译文案（`server.tr`），
**不会改写玩家原始聊天内容**；MC → QQ 的聊天转发保持原文。

## 三、QQ 专属功能清单

| 功能 | 实际行为 | 关键位置 |
|---|---|---|
| 双向聊天互通 | 群聊 → MC；MC 聊天/事件 → 指定群 | `logic/system/echo.py` |
| 收发群分离 | `group_ids` 监听群 ≠ `forward_group_ids` 发送群；`notice_forward_groups` 供开关机、进出、成就/死亡等通知专用 | 配置 `connector.QQ.permissions` |
| 权限模型 | `admin_ids`（管理员 QQ）、`admin_group_ids`（整群视为管理员）、`friend_is_admin`（好友即管理）；管理群消息不广播 | `parser/qq_parser.py` |
| 回复定向 | 引用回复机器人的转发消息 → MC 内 @ 原玩家 | `parser/qq_parser.py` |
| 跨平台强制广播 | QQ 端 `#mc <消息>` 仅发 MC（可附带把被回复的图片转进 MC）；MC 端 `!!qq <消息>` 仅发 QQ，可指定 `qq_forward_group_ids` | `logic/plugins/cross_broadcast.py` |
| 绑定系统 | `#绑定` / `#解绑` / `#绑定 列表`，Java/基岩分开数量上限；退群事件 `group_decrease` 自动解绑（可配移除白名单）；绑定可选自动加白名单 | `logic/system/bound.py` |
| 群名片同步 | 绑定成功及自动修复时 `set_group_card` 改为游戏名（`others.change_group_card`） | `logic/system/bound.py`、`logic/plugins/inactive_check.py` |
| 未绑定提醒 | 未绑定成员发言时提醒绑定（排除管理员、管理群、exclude_ids） | `logic/system/bound_notice.py` |
| 群成员对账 | `get_group_member_list` 比对群成员与绑定库：不活跃检查、未绑定检查，可私聊/群提醒并自动修名片 | `logic/plugins/inactive_check.py`、`logic/plugins/unbound_check.py` |
| 违禁词 | 命中即**拦截该条消息**并回复违禁理由（管理员豁免；词库存 `data/system/ban_words.json`）。注意：README 写"撤回"，但代码未调用 `delete_msg`，实际是拦截而非撤回 | `logic/system/ban_word.py` |
| 关键词回复 | 群消息命中关键词自动回复，支持图片回复（缓存到数据目录） | `logic/system/key_word.py` |
| 人格风格 | `#风格 <名>` 切换 normal / 傲娇 / 萝莉 / 病娇 / 中二病 / 雌小鬼 / 御姐 / 波奇酱；本质是整份 i18n 翻译覆盖，连连接日志、报错都会变人设语气 | `logic/system/style.py`、`utils/style_manager.py`、`constant/*.yml` |
| 群命令全集 | `#帮助` `#list` `#tps` `#白名单` `#执行`(RCON) `#mcdr` `#待办` `#投票` `#echo` `#风格` 等，全部可在群里触发 | `logic/system/` |
| 多媒体消息 | CQ 码/数组双格式；text/at/image/face/record/reply 等消息段；发送支持分片；QQ 表情→中文名映射 | `builder/` |
| 多服互联 | Bridge 将 QQ 消息同步到子服；`#执行@服务器名` 跨服执行 | `connector/bridge_connector.py` |
| WebUI | 注册 GUGUBot 配置页（PF-MCDR-WebUI 存在时） | `webui_register.py` |

## 四、两个容易踩坑的点

1. 配置里的 `connector.QQ.others.forward_other_bot` 目前**只有迁移逻辑引用**
   （`utils/config_migrator.py`），运行时代码未使用，属于遗留项。
2. 插件只做 OneBot **正向 WS 客户端**，不监听 WS 端口；
   `ws/websocket_server.py` 在 QQ 链路上未被使用。
