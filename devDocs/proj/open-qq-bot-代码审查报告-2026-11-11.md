# open-qq-bot 分支代码审查报告

| 项目 | 内容 |
|---|---|
| 审查基线 | `main` → `feat/open-qq-bot-connector` |
| merge-base | `593357f35a258ba6520a3ab2f27babba66d16f8e` |
| 提交数 | 25 |
| 变更规模 | 68 个文件，+8683 / -5 |
| OCR 可审查文件 | 21 个，已审查 21 个（100%） |
| OCR 排除 | 47 个（文档、图片、测试等） |
| 定向测试 | `PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot`，52 个用例通过 |
| 审查日期 | 2026-11-11 |
| 审查方式 | OCR 委托工作流；规则、diff、逐文件人工复核 |
| 代码修改 | 无（仅审查） |

> 说明：仓库没有 `master` 分支，本次按需求以 `main` 作为基线。
>
> 严重度定义：High = 会导致明确的功能失效、权限残留或永久性不可用；Medium = 特定条件下消息丢失、重复、功能不一致；Low = 健壮性、可维护性、测试或 demo 问题。

## 结论

**不建议直接合并。**

`H-1` 会让官方连接器的退群解绑完全失效，`H-2` 会让网关在启动瞬时故障后永久离线；其余问题以健壮性、消息完整性和功能一致性为主。

| 严重度 | 数量 |
|---|---|
| Critical | 0 |
| High | 2 |
| Medium | 7 |
| Low | 7 |

---

## High

### H-1 官方绑定与退群解绑使用不同的平台键，退群清理完全不生效

**位置**

- `GUGUbot/gugubot/logic/system/bound.py:822`、`833-842`、`812-814`
- 绑定写入侧：`bound.py:169`、`410`
- 官方连接器显示名：`GUGUbot/gugubot/connector/open_qq_bot/connector.py:64-71`
- 测试：`tests/test_open_qq_bot.py:608-634`、`683-693`

**问题**

绑定流程使用原始来源显示名作为平台键：

```python
source = broadcast_info.source.origin
...
platform=platform
```

官方连接器的 `source` 被覆盖为配置里的 `source_name`，默认是 `"OpenQQBot"`，所以实际存储为：

```json
{"accounts": {"OpenQQBot": ["<32位 OpenID>"]}}
```

但退群处理却按 `"QQ"` 查找：

```python
player = self.player_manager.get_player(user_id, platform="QQ")
```

`PlayerManager.get_player` 在指定 `platform` 时只匹配该平台键（`utils/player_manager.py:164-168`），因此永远查不到官方绑定，直接返回 `False`。结果是：

- 绑定记录不删除；
- 玩家名不从白名单移除；
- 日志甚至不会输出“已清理”。

即使把查找改成 `source.origin`，后面的逻辑仍会误判：

```python
for platform, accounts in player.accounts.items():
    if platform != "QQ" and accounts:
        has_other_platform_accounts = True
```

`"OpenQQBot"` 会被当成“其他平台”，导致保留整个 Player；而删除时又只操作 `player.accounts["QQ"]`。

另外，docstring 声称“绑定库平台键同为 QQ，与 OneBot 版互通”，这是错误的：官方 OpenID 与 QQ 号不是同一标识空间。

**测试为何没发现**

`TestBoundOfficialQuit` 的 fake `get_player` 只按传入的 `platform` 查找，而 fixture 直接构造 `accounts={"QQ": [USER_OID]}`：

```python
async def test_official_quit_unbinds(self):
    handled, players, bs = await self._run(accounts={"QQ": [USER_OID]})
```

它没有复现真实绑定写入后的 `"OpenQQBot"` 键，因此测试通过反而掩盖了缺陷。

**影响**

通过官方机器人完成绑定的玩家，在退出 QQ 群后仍保留白名单和绑定，形成长期权限残留。

**建议**

- 退群分支使用与绑定时相同的平台键（`broadcast_info.source.origin`，或引入稳定的 connector key 而不是显示名）；
- “其他平台账户”判断排除该平台键；
- 用真实 `PlayerManager` + 临时文件重写该测试，fixture 使用 `"OpenQQBot"`；
- 修正 docstring，明确 OpenID 与 OneBot QQ 号不互通。

---

### H-2 网关启动/重连时 `_get_url()` 抛异常会永久杀死网关线程

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/gateway.py:165-170`、`193-199`
- `GUGUbot/gugubot/connector/open_qq_bot/api_client.py:46-56`、`85-86`

**问题**

```python
while not self._stop:
    ...
    url = self._get_url()
    logger.info("连接网关：%s", url)
```

`_get_url()` 会走 `ApiClient.gateway_url()` → `TokenManager.get()`，其中包含 HTTP 请求。网络超时、QQ 接口 5xx、错误的 app_secret、返回体缺少 `access_token` 都会抛异常。该调用不在 `try` 内，异常直接逃出 `run()`：

```python
def _run_guarded(self):
    try:
        self.run()
    except GatewayStopped as e:
        ...
    except Exception:
        logger.exception("网关线程异常退出")
```

线程结束后没有任何重启逻辑，`connect()` 也不会再次调用。插件仍显示已加载，但官方 QQ 连接永久离线，只能重载插件恢复。重连循环中的后续 `_get_url()` 失败同样会终止线程。

**影响**

启动瞬间的短暂网络故障或一次 token 接口失败，会让整个官方连接器在本次运行期间不可用；错误凭据也不会给出明确提示，只留下线程异常日志。

**建议**

- 将 URL/token 获取纳入重试循环，复用现有指数退避；
- 区分可重试错误与凭据错误（401/403 等可给出明确告警并停止）；
- 增加连接状态/健康检查，避免“线程已死但插件看起来正常”。

---

## Medium

### M-1 被动回复过期降级时图片 URL 被重复追加

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/connector.py:514-526`
- `connector.py:589-605`

**问题**

群消息含图片时，先构造已包含图片 Markdown 的 `content`：

```python
content = target_plain
if target_images:
    content += "\n\n" + "\n\n".join(f"![图片]({url})" for url in target_images)
```

被动回复过期后：

```python
self._send_active_fallback(target_id, target_type, content, target_images)
```

降级函数又追加一次：

```python
if images:
    content += "\n\n" + "\n\n".join(f"![图片]({url})" for url in images)
```

已用脚本复现，同一 URL 出现两次。

**影响**

被动窗口失效时群内出现重复图片。

**建议**

降级时传 `target_plain` + `target_images`，或给降级函数增加“内容已含图片”的标志。

---

### M-2 只有群文本会分片；Markdown 与单聊文本没有长度限制

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/api_client.py:137`（群文本分片）
- `api_client.py:160-176`（Markdown 不分片）
- `api_client.py:201-211`（单聊文本不分片）
- `GUGUbot/gugubot/config/defaults/default_config.yml:70`

**问题**

`send_group_text` 使用 `split_message(content, self.max_message_length)`，但：

- `send_group_markdown` 直接把完整 `content` 放入请求体；
- `send_c2c_text` 也不分片。

而含图片或 @ 提及的群消息会强制走 Markdown 通道（`connector.py:514-521`）。长 MC 聊天 + 图片、长命令回复、长私聊消息都可能超过 2000 字符，触发 `40054007`，整条消息被丢弃。

**影响**

长消息静默丢失；用户只看到发送失败日志。

**建议**

- Markdown 按安全边界分片（避免切断 URL、`<qqbot-at-user>` 标签）；
- 单聊文本复用 `split_message`；
- 或明确截断并追加“内容过长”提示。

---

### M-3 群文本分片中途失败被当成整体成功

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/api_client.py:139-158`
- `GUGUbot/gugubot/connector/open_qq_bot/connector.py:535-541`

**问题**

分片循环中，如果被动回复次数耗尽：

```python
if not self._alloc_passive(body, msg_id):
    self.logger.warning("分片 %s/%s 因被动回复次数耗尽未发送", ...)
    break
...
return last_resp
```

若前面的分片已成功，`last_resp` 非 `None`。调用方只在 `sent is None` 时降级为主动消息，因此剩余分片被静默丢弃，日志仍打印“发送成功”。

**影响**

长消息被截断，且没有任何用户可见提示；剩余内容不会通过主动消息补发。

**建议**

返回明确的“部分成功”结果，或在未发送完所有分片时返回 `None`/抛错，让调用方补发或告警。

---

### M-4 被动回复 `msg_seq` 记账泄漏，测试还固化了泄漏行为

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/api_client.py:201-225`（单聊）
- `api_client.py:90-111`、`214-222`（重复消息重试）
- `tests/test_open_qq_bot.py:896-912`

**问题**

三处记账不一致：

1. `send_c2c_text` 在 `_alloc_passive` 分配 seq 后，只有 `retried_seq` 为真时才 `release`。首次请求因非重复错误失败时，seq 不会回退；群文本路径则在 `except` 中释放（`152-155`）。
2. 命中 `40054005` 去重重试时，会再分配一个新 seq；如果重试成功，旧 seq 没有释放，一条实际送达的消息消耗了两个被动回复名额。
3. 测试 `test_c2c_retry_failure_releases_seq` 在两次失败后断言：

```python
self.assertEqual(client.seq._seqs.get("M"), 1)
```

这等于把“泄漏一个 seq”写成了预期行为。

**影响**

同一 `msg_id` 的可用被动回复次数提前耗尽，后续回复被降级为主动消息，占用配额甚至被丢弃。

**建议**

- 为一次发送记录所有分配过的 seq，失败时全部释放；
- 去重重试成功时释放旧 seq；
- 将测试期望改为 0，并补充“重试成功不泄漏”的用例。

---

### M-5 官方连接器在所有服务器注册，缺少 `is_main_server` 保护

**位置**

- `GUGUbot/gugubot/__init__.py:109-113`

**问题**

```python
if is_main_server:
    connectors.append(QQWebSocketConnector(server, gugubot_config))

# QQ 官方机器人连接器
connectors.append(OpenQQBotConnector(server, gugubot_config))
```

OneBot 连接器只在主服注册，官方连接器却无条件加入。多服互联场景下，如果各服配置相同（或共享配置），每个服务器都会用同一组 app_id/app_secret 建立网关会话，并以 `shard: [0, 1]` 接收同一批事件，造成重复广播/重复命令处理；同时 `BoundSystem` 只在主服创建，子服上的绑定命令无法正常工作。

默认 `enable: false` 降低了触发概率，但这是条件性真实缺陷。

**建议**

与 OneBot 保持一致，仅主服注册官方连接器；或在配置/文档中明确“只能在一台服务器启用”，并增加启动检测。

---

### M-6 `!!qq` 没有接入官方连接器

**位置**

- `GUGUbot/gugubot/logic/plugins/cross_broadcast.py:47-77`
- `cross_broadcast.py:151-158`
- `connector.py:563-574`

**问题**

`#mc` 已同时支持 OneBot 和官方连接器：

```python
if source_name in (qq_source, official_source) and text.startswith(...):
```

但 MC 端 `!!qq` 仍然只发往 `qq_source`（OneBot）：

```python
return await self._broadcast_to(broadcast_info, remaining, qq_source, target=target)
```

只启用官方连接器时：

- `_broadcast_to` 找不到 `"QQ"` connector，返回 `False`；
- 随后 echo 会把原文（包含 `!!qq` 前缀）转发给官方连接器，命令文本泄漏到 QQ 群，或直接无输出。

另外 `_build_qq_forward_target()` 使用 `qq_forward_group_ids` 的数字群号，而官方连接器需要 32 位群 OpenID，即使路由过去也会被 `_resolve_targets` 跳过。

**影响**

官方-only 部署下 `!!qq` 不可用，且可能把命令原文当普通消息发出；功能与文档承诺不一致。

**建议**

- 将 `!!qq` 路由到所有已启用的 QQ 类连接器，或在官方连接器启用时优先走官方；
- 增加官方专用 `forward_group_openids` 配置；
- 未命中任何目标时不要回落到 echo。

---

### M-7 全量模式下 @机器人 前缀导致 `#命令` 无法识别

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/parser.py:123-128`
- `GUGUbot/gugubot/logic/system/basic_system.py:97-102`
- demo 的对照处理：`devDocs/open-qq-bot/demo/qq_official_demo.py:712-716`

**问题**

`GROUP_MESSAGE_CREATE` 全量模式下，消息中的 `<@bot_openid>` 被替换成文本：

```python
text = text.replace(f"<@{oid}>", f"@{user.get('username', oid)}")
```

于是 `@机器人 #绑定 Steve` 变成以 `@机器人 ` 开头的单个 text 段。`BasicSystem.is_command` 要求首段文本以 `#` 开头，命令不会被识别。

demo 明确处理了这一点：

```python
if at_me and self.bot_username and content.startswith(f"@{self.bot_username}"):
    content = content[len(self.bot_username) + 1:].strip() or content
```

插件没有对应逻辑。

**影响**

全量模式（配置注释推荐用于 `group_ids`）下，用户习惯性的 `@机器人 #命令` 全部失效；AT 模式通常不受影响。

**建议**

在 parser/connector 中根据 `mentions` 的 `bot: true` 识别机器人自身，剥离渲染出的 `@昵称` 前缀后再交给系统分发；保留原始 `raw` 供被动回复锚点使用。

---

## Low

### L-1 `split_message` 对非法 `max_message_length` 无防护，0 会死循环

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/common.py:171-186`
- 配置传入：`connector.py:95-97`

当 `max_length <= 0` 时：

```python
while len(rest) > max_length:
    cut = rest.rfind("\n", 0, max_length)
    if cut <= 0:
        cut = max_length
    chunks.append(rest[:cut].strip())
    rest = rest[cut:].strip()
```

`cut=0` 时 `rest[0:]` 不变，形成无限循环，占死一个 `asyncio.to_thread` 工作线程。非整数配置还会直接 `TypeError`。

**建议**：配置边界统一 `max(1, int(value))`，`split_message` 内再加防御。

---

### L-2 `QuotaManager` 只有单目标限额，缺少 Bot 全局限额

**位置**

- `common.py:204-248`
- 调用：`connector.py:494`

docstring 自己写了官方还有“Bot 维度 30~60 条/分钟”，但实现只按群/用户 key 计数；另外一次分片发送只调用一次 `quota.allow`，实际可能发出多个 API 请求。多群同时广播时可能触发平台全局限流，消息被 API 拒绝后仅记录 warning。

**建议**：增加全局滑动窗口；按实际分片数计数。

---

### L-3 `echo.py` 私聊判断包含死代码

**位置**

- `GUGUbot/gugubot/logic/system/echo.py:54-62`

```python
broadcast_info.source.is_from("open-qq-bot")
```

`Source.is_from` 比较的是 `origin`，而官方连接器的 origin 是显示名（默认 `"OpenQQBot"`），该条件永远为假；真正生效的是下面按配置 `source_name` 的判断。逻辑无害，但容易误导后续维护。

**建议**：删除死分支，或统一改为按配置显示名判断。

---

### L-4 官方退群分支复制大量 OneBot 逻辑，且缺少管理群通知

**位置**

- `bound.py:808-853`
- 对照：`bound.py:756-801`

官方分支复制了白名单移除、其他平台判断、Player 删除等约 40 行逻辑，但：

- 不发送管理群退群通知；
- 无法做“是否还在其他群”检查（官方接口权限限制，可接受）；
- docstring 的“平台键同为 QQ”描述错误。

**建议**：抽取公共清理函数，仅把“是否还有其他群”作为策略参数；明确记录官方路径的差异。

---

### L-5 存在未使用、未测试的 API 面积

**位置**

- `api_client.py:178-265`

`send_group_media`、`upload_group_media`、`recall_group_message`、`upload_c2c_media`、`recall_c2c_message`、`get_group_info`、`get_group_bot_state`、`get_group_members`、`send_group_file_chunked` 均未被连接器调用，也没有测试覆盖。与此同时，单聊图片仍被降级为 `[图片]` 占位（`connector.py:487-490`），尽管官方提供了 C2C 富媒体接口。

**建议**：要么接入并补测试，要么标记实验性/删除，避免长期漂移。

---

### L-6 测试 bootstrap 不可移植，且 fixture 固化了 H-1

**位置**

- `tests/test_open_qq_bot.py:17-35`、`50-51`、`66`
- `tests/test_open_qq_bot.py:608-634`

问题包括：

- 硬编码 `E:\Project\PF-GUGUBot\GUGUbot` 并 `sys.path.insert`；
- 强制注册 `gugubet` 别名；
- import 阶段直接 `print` 调试信息；
- `TestBoundOfficialQuit` 使用 `accounts={"QQ": ...}`，没有复现真实平台键。

项目文档已经约定用 `PYTHONPATH=GUGUbot`，这些 hack 在 Linux/CI 上会直接失败；本地 52 个用例通过只是因为该 Windows 路径恰好存在。

**建议**：移除硬编码路径与 alias，按 `PYTHONPATH=GUGUbot` 运行；测试改用真实 `PlayerManager`。

---

### L-7 demo 的违禁词豁免逻辑会吞掉管理员命令

**位置**

- `devDocs/open-qq-bot/demo/qq_official_demo.py:754-761`
- 调用顺序：`:722-728`

```python
if author.get("member_role") in ("admin", "owner"):
    log.info("违禁词命中但发送者为 %s，豁免", ...)
    return True
```

调用方 `if self._ban_word_check(...): return`，返回 `True` 表示“已处理并终止”。管理员消息只要命中违禁词（包括含违禁词的命令），就会被直接吞掉，后续命令/关键词都不会执行。GUGUBot 的对应实现返回 `False`，让流程继续。

另外 `_track_activity`（`:633-645`）在网关线程中每条消息同步写一次 JSON，负载高时可能阻塞心跳。

demo 不随插件发布，故为 Low。

---

## 文件覆盖清单

| # | 文件 | 结果 |
|---|---|---|
| 1 | `.gitignore` | 已审查，无问题 |
| 2 | `GUGUbot/gugubot/__init__.py` | M-5 |
| 3 | `GUGUbot/gugubot/config/defaults/default_config.yml` | M-2、L-1 相关配置 |
| 4 | `GUGUbot/gugubot/connector/__init__.py` | 已审查，无问题 |
| 5 | `GUGUbot/gugubot/connector/open_qq_bot/__init__.py` | 已审查，无问题 |
| 6 | `GUGUbot/gugubot/connector/open_qq_bot/api_client.py` | M-2、M-3、M-4、L-5 |
| 7 | `GUGUbot/gugubot/connector/open_qq_bot/common.py` | L-1、L-2 |
| 8 | `GUGUbot/gugubot/connector/open_qq_bot/connector.py` | M-1、M-2、M-4、L-5 |
| 9 | `GUGUbot/gugubot/connector/open_qq_bot/gateway.py` | H-2 |
| 10 | `GUGUbot/gugubot/connector/open_qq_bot/parser.py` | M-7 |
| 11 | `GUGUbot/gugubot/connector/qq_connector.py` | 已审查，无问题 |
| 12 | `GUGUbot/gugubot/logic/plugins/cross_broadcast.py` | M-6 |
| 13 | `GUGUbot/gugubot/logic/system/bound.py` | H-1、L-4 |
| 14 | `GUGUbot/gugubot/logic/system/echo.py` | L-3 |
| 15 | `GUGUbot/lang/en_us.yml` | 已核对新增 key，无缺失 |
| 16 | `GUGUbot/lang/zh_cn.yml` | 已核对新增 key，无缺失 |
| 17 | `GUGUbot/mcdreforged.plugin.json` | 版本号更新，无问题 |
| 18 | `devDocs/open-qq-bot/demo/.gitignore` | 已审查，无问题 |
| 19 | `devDocs/open-qq-bot/demo/config.example.json` | 已审查，无问题 |
| 20 | `devDocs/open-qq-bot/demo/qq_official_demo.py` | L-7 |
| 21 | `pyproject.toml` | 版本号更新（`2.2.5a2` 与 `2.2.5-alpha2` PEP 440 等价），无问题 |

**额外人工审查（OCR 排除）**

| 文件 | 结果 |
|---|---|
| `tests/test_open_qq_bot.py` | L-6；并确认 H-1 的测试会误通过 |

---

## 建议修复顺序

1. **H-1**：统一官方绑定/退群解绑的平台键，修正测试 fixture。
2. **H-2**：网关 URL/token 获取加入重试，避免线程永久退出。
3. **M-4 + M-3**：先修被动回复 seq 记账和分片部分失败，避免消息静默丢失。
4. **M-2 + M-1**：补 Markdown/C2C 分片，修降级重复图片。
5. **M-5 / M-6 / M-7**：多服注册保护、`!!qq` 路由、@前缀命令识别。
6. **Low**：按需清理，其中 L-6 建议优先处理，否则 CI 无法稳定验证上述修复。

---

## 附录：复现命令

```bash
# 查看审查范围
git log --oneline main..HEAD
git diff --stat main...HEAD

# 运行官方连接器定向测试（测试文件当前自带硬编码路径）
PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot
```

本次仅审查，未应用任何修改。
