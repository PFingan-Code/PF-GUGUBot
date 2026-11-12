# open-qq-bot 分支代码审查报告（第二轮）

| 项目 | 内容 |
|---|---|
| 审查基线 | `feat/open-qq-bot-connector` 工作树（第一轮 16 项修复后，含未提交改动） |
| 上一轮报告 | `open-qq-bot-代码审查报告-2026-11-11.md`（16 项，已修复） |
| 审查日期 | 2026-11-12 |
| 审查方式 | OCR 委托工作流第二轮；逐文件复核 + 探针实测 + 变异测试 |
| 定向测试 | `PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot`，91 个用例通过（新增 12） |
| 代码修改 | 本轮修复 N1–N7（7 项），并升级版本至 `2.2.5-alpha3` |
| 发现数 | 7（High 0 / Medium 3 / Low 4） |

> 严重度定义：High = 明确的功能失效、权限残留或永久性不可用；Medium = 特定条件下消息丢失、重复或配额泄漏；Low = 健壮性、记账精度、排障准确性、测试卫生。
>
> 本轮聚焦第一轮修复后**残留与新引入**的缺陷，尤其是分片发送的失败语义与 `msg_seq` 配额记账。所有发现均以探针或变异测试机械证实，修复后以回归用例固化。

## 结论

**7 项已全部修复并通过验证，可合并。**

第一轮修复把「被动回复过期 → 整体降级重发」打通后，本轮发现该降级路径在**分片部分送达**时会重复已送达内容（N1），且网络层异常与去重重试耗尽两条路径会泄漏被动名额（N2/N3）。这三项是本轮核心（Medium）。其余为配额预估精度、网关停止竞态、排障命令准确性与测试卫生（Low）。

| 严重度 | 数量 | 编号 |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 3 | N1、N2、N3 |
| Low | 4 | N4、N5、N6、N7 |

---

## Medium

### N1 分片中途失败被当作整体被动过期，降级重发已送达片 → 重复消息

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/api_client.py:217`、`249`、`308`（三处 `except ApiError`）
- 降级触发侧：`connector.py:562-585`（`except ApiError` → `_send_active_fallback`）
- 部分送达告警侧：`connector.py:594-599`（`except PartialDelivery`，仅告警不补发）

**问题**

`send_group_text` / `send_group_markdown` / `send_c2c_text` 自动分片发送。第一轮已为「一片未发」（`_alloc_passive` 返回 False）引入 `PartialDelivery`，但**分片已送达、后续片在 POST 阶段抛 `ApiError`**（如被动窗口 40034005 失效）的路径仍裸抛 `ApiError`。

连接器侧 `except ApiError` 命中 `ERR_PASSIVE_EXPIRED` 后调用 `_send_active_fallback`，把**整段原文**作为主动消息重发——已送达的首片被再次发出，用户看到重复内容。

**机械证据（修复前探针）**

```
P1 calls total/passive/active: 6 2 4
P1 first passive chunk: '[MC] mc: A'
P1 active fallback chunk0: '[MC] mc: A'
P1 DUPLICATE(first chunk resent in active): True
```

**修复**

三处 `except ApiError as e` 在 `i > 0`（已有分片送达）时改抛 `PartialDelivery(i, len(chunks) - i) from e`。`PartialDelivery(RuntimeError)` 与 `ApiError` 是兄弟类（非子类），故绕过内层 `except ApiError` 降级分支，落到外层 `except PartialDelivery` 仅告警、不补发全文。

**验证**

- 回归：`TestChunking.test_group_text_midchunk_apierror_partial` / `..._markdown_...` / `..._c2c_...` 断言 `PartialDelivery(sent=1, remaining=2)` 且失败片 seq 回退。
- 端到端：`TestOutbound.test_midchunk_passive_expiry_no_duplicate_resend` 用真实 `ApiClient` 驱动 `send_message`，断言仅首片送达、`active == []`。
- **变异测试**：临时撤掉 `send_group_text` 的 `PartialDelivery` 包装，端到端用例立即失败：

```
AssertionError: Lists differ: ['AAAAAAAAAA', 'AAAAAAAAAA', 'AAAAAAAAAA'] != []
```

机械复现重复重发；恢复后转绿。

---

### N2 网络层异常裸抛，绕过 seq 回退 → 泄漏被动名额

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/common.py:115-120`（`http_json` 异常归一）
- 回退依赖侧：`api_client.py` 各 `except ApiError` 的 `_release_seqs`

**问题**

`http_json` 原先只捕获 `urllib.error.HTTPError`。`URLError`、超时、连接重置、`http.client.IncompleteRead` 等网络层失败会**裸抛**（非 `ApiError`），发送层的 `except ApiError` 接不住，已分配的 `msg_seq` 不回退。每遇一次网络抖动就白白消耗一个被动名额（上限 5），累积后正常消息因「次数耗尽」被丢弃。

**机械证据（修复前探针）**

```
P2 seq after URLError: 1 (0 = 已回退, 1 = 泄漏)
```

**修复**

`http_json` 增加 `except (OSError, http.client.HTTPException)` 兜底（`HTTPError` 已是 `OSError` 子类并在上方处理），统一抛 `ApiError(method, url, 0, str(e), None, None)`。`status=0` 使发送层 seq 回退与网关重试策略（`_is_credential_error` 只认 401/403）与 HTTP 错误走同一路径。

**验证**

- `TestSeqAccounting.test_network_error_releases_seq`：`_call` 抛 `status=0` 的 `ApiError`，断言 seq 回退到 0。
- `TestReviewRegressions.test_http_json_urlerror_becomes_apierror` / `..._incomplete_read_...`：mock `urlopen` 分别抛 `URLError` 与 `IncompleteRead`（后者属 `HTTPException` 而非 `OSError`），断言归一为 `status=0`。

---

### N3 去重重试直至名额耗尽时，未回退已分配的重试 seq → 泄漏

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/api_client.py:133`、`162`（群 / 单聊 `if new_seq is None` 分支）

**问题**

`_post_group_message` / `_post_c2c_message` 命中 40054005 去重时换 `msg_seq` 重试。当连续去重直到 `seq.allocate` 返回 `None`（名额耗尽），原代码直接 `raise`，**未回退此前重试已分配的 `retry_seqs`**。外层只回退初始被动 seq，重试 seq 永久泄漏。

**机械证据（修复前探针，起点预占 3）**

```
P3 seq after double-dup+exhaust: 4 (起点 3；3 = 无泄漏, 4 = 泄漏 1)
```

轨迹：被动分配 seq=4 → 重试 seq=5（retry_seqs=1）→ 再重试 allocate=None → 裸 raise（漏回退 retry_seqs）→ 外层回退 1 → 终值 4。

**修复**

两处 `if new_seq is None:` 在 `raise` 前补 `self._release_seqs(msg_id, retry_seqs)`。耗尽时重试 seq 与初始 seq 全部回退。

**验证**

`TestSeqAccounting.test_group_double_dup_exhaust_no_leak` / `..._c2c_...`：预占 `_seqs["M"]=3`，`_call` 恒抛去重错误，断言终值回到 3（无泄漏）。

---

## Low

### N4 主动降级配额预估漏传 has_mention，含 @ 消息少算分片

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/connector.py:652-656`（`_send_active_fallback` 配额预估）
- 实发通道判定：`connector.py:664`（`images or "<qqbot-at-" in plain` → Markdown）

**问题**

`_send_active_fallback` 用 `_chunk_count(target_type, plain, images)` 预估配额，漏传 `has_mention`。含 @ 标签但无图片的消息实发走 Markdown 通道（`split_markdown` 保护 @ 标签/URL，分片数可能更多），预估却按文本通道（`split_message`）计算，少算分片 → 配额记账偏低，极端下超发触发平台级限流。

**修复**

透传 `has_mention="<qqbot-at-" in plain`，与实发通道判定条件完全一致。

**验证**

`TestReviewRegressions.test_active_fallback_passes_has_mention`：mock `_chunk_count`，断言含 @ 时以 `has_mention=True` 调用且实发 markdown、无 @ 时 `has_mention=False` 且实发 text。

---

### N5 网关取址成功后建连前未复查 stop → 停止竞态新建连接

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/gateway.py:201-203`（`run` 循环）

**问题**

`run()` 循环顶部 `while not self._stop` 每轮复查，但 `_get_url()` 是阻塞 HTTP。若 `stop()` 在取址期间被调用，取址成功返回后**直接建 WS 并 `run_forever()`**，直到该连接自然关闭才在 `if self._stop: break`（line 209）退出——停止被延迟，且可能在已请求停止后仍新建一个网关会话。`continue`（取址失败重试）路径经 `while` 复查无此问题，唯独成功路径漏检。

**修复**

取址成功后、`logger.info("连接网关")` 前补 `if self._stop: break`。

**验证**

`TestGatewayResilience.test_stop_during_url_fetch_skips_connect`：`_get_url` 置 `_stop=True` 后返回 url，mock `WebSocketApp`，断言 `run()` 退出且 `WebSocketApp` 未被构造。

---

### N6 bot OpenID 取 id 优先，与 parser 的 member_openid 优先不一致

**位置**

- `GUGUbot/gugubot/connector/open_qq_bot/connector.py:262`（`_learn_bot_openid`）
- 对照：`parser.py:130`（`member_openid or id`）
- 消费侧：`connector.py:361-363`（`/botId` 排障命令回复 `debug_bot_id`）

**问题**

`_learn_bot_openid` 原取 `user.get("id") or user.get("member_openid")`，与 parser 的 `member_openid` 优先相反。群聊 mentions 中群内 OpenID 在 `member_openid`，`id` 可能是不同标识。`bot_openid` 仅用于 `/botId` 排障命令回复——当 `id ≠ member_openid` 时，`/botId` 回报全局 `id` 而非群内 `member_openid`，与 parser/出站 @ 标签所用标识空间不一致，误导用户配置白名单或 @ 标签。

> 注：parser 的自 @ 前缀剥离独立使用 mentions 的 `member_openid`，不依赖 `connector.bot_openid`，故本项**不影响命令解析**，仅影响排障命令准确性。

**修复**

改为 `user.get("member_openid") or user.get("id") or ""`，对齐 parser。

**验证**

`TestReviewRegressions.test_learn_bot_openid_prefers_member_openid`：mention 同时含 `id="GLOBAL_ID"` 与 `member_openid=BOT_OID`，断言 `bot_openid == BOT_OID`。

---

### N7 测试临时数据目录从不显式清理 → ResourceWarning / 残留

**位置**

- `tests/test_open_qq_bot.py:138-143`（`build_connector`）、`1598-1601`（`tearDownModule`）

**问题**

`build_connector` 为隔离配额持久化创建 `tempfile.TemporaryDirectory`，但从不显式 `cleanup()`，依赖 GC 触发，产生 ResourceWarning 并可能残留临时目录。

**修复**

模块级 `_TEMP_DIRS` 登记每个 ctx，新增 `tearDownModule()` 集中 `cleanup()` 并清空。`TestBoundOfficialQuit` 已用 `addCleanup` 的独立 tmpdir 不受影响。

**验证**

全量跑前后统计 `%TEMP%/gugubot_test_*`：`before=0 after=0`，无残留。

---

## 测试与验证汇总

| 项 | 结果 |
|---|---|
| 定向测试 | `PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot` → **Ran 91 tests, OK** |
| 新增回归 | 12 条：N1×4（群文本/群 Markdown/单聊 + 端到端无重发）、N2×3、N3×2、N4×1、N5×1、N6×1 |
| N1 变异测试 | 撤掉包装 → 端到端用例失败（active 重发 3 片）；恢复 → 转绿 |
| N7 临时目录 | 全量跑前后 `gugubot_test_*` 计数 0 → 0 |
| 打包 | `gugubot-v2.2.5-alpha3.mcdr`（94 文件，CRC OK，plugin.json 在根级，无 pycache/pyc） |

## 范围外说明（本轮未改）

- `GUGUbot/gugubot/logic/system/bound.py` 的 `if platform == "qq"`（小写）永不匹配官方平台键 `OpenQQBot`，属第一轮范围外的既有 bug，按约定未在本轮一并修改。
- `uv.lock` 工作树改动为 `uv run` 意外重写（`revision 2→3`、源 `pypi.org→mirrors.aliyun.com`、剥离 upload-time，依赖哈希不变），非修复内容，**未纳入提交**，建议 `git restore uv.lock` 还原。