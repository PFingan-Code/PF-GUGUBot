"""QQ 官方机器人连接器（open-qq-bot）。

继承 :class:`BasicConnector`，把 QQ 官方机器人 WebSocket API 适配进
GUGUBot 的 connector 管线，与 OneBot 版 QQWebSocketConnector 并行使用：

- 入站：gateway 线程收到事件 → 去重/过滤 → ``server.schedule_task``
  交给 :class:`OpenQQBotParser` → BroadcastInfo → 既有系统管线
- 出站：``send_message(ProcessedInfo)`` → 段数组转官方文本/Markdown
  （含跨源前缀、颜色码剥离、@/图片转换）→ ``asyncio.to_thread`` 调 API；
  同源命令回复/群消息池优先用 msg_id 被动回复，无可用锚点走主动消息
- @ 标签仅 Markdown 通道渲染

与 OneBot 版的关键差异（官方平台限制）：
- 主动消息受频控（单群 20 条/分钟、1000 条/天），配额由 QuotaManager 管理
- 被动回复有 5 分钟/每条 5 次窗口（SeqManager 严格递增 msg_seq）；池用
  5 分钟 -10 秒的保守本地窗口，过期/超次即降级主动消息
"""

import asyncio
import logging
import random
import re
import time
import traceback
import weakref
from typing import Optional

from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.connector.open_qq_bot.api_client import (
    ApiClient,
    PartialDelivery,
    TokenManager,
)
from gugubot.connector.open_qq_bot.common import (
    ERR_PASSIVE_EXPIRED,
    INTENTS,
    ApiError,
    DedupSet,
    PassiveMsgPool,
    QuotaManager,
    at_user_tag,
    random_send_delay,
    split_markdown,
    split_message,
)
from pathlib import Path
from gugubot.connector.open_qq_bot.gateway import Gateway
from gugubot.connector.open_qq_bot.parser import OpenQQBotParser
from gugubot.utils.types import ProcessedInfo

OPENID_RE = re.compile(r"^[0-9A-Fa-f]{32}$")

MC_COLOR_CODE = re.compile(r"§[0-9a-fk-or]", re.IGNORECASE)

# 消息 content 中的 @ 标记（<@openid> / <@all>），调试命令匹配前剥离
AT_TAG_RE = re.compile(r"<@[^>]*>")

# 出站文本框里的 mention 标签：外部聊天内容不得伪造 @成员/@全体
MENTION_TAG_RE = re.compile(r"<qqbot-at-[^>]*>", re.IGNORECASE)

# 图片外链 URL 白名单：Markdown 通道以 ``![图片](url)`` 拼接，URL 若含
# ``(``/``)`` 可提前闭合语法、引号/空白/反斜杠（尾 ``\`` 转义收尾 ``)``）
# 可吞掉后续内容并注入活标签（如伪造 ``<qqbot-at-user/>``），一律拒绝
IMAGE_URL_RE = re.compile(r"^https?://[^\s()<>\[\]\"'\\]+$")


class _MCDRForwardHandler(logging.Handler):
    """把 ``gugubot.open_qq_bot`` 子包 logger 的记录转发到 MCDR 插件 logger。

    背景：子包模块（gateway/api_client/common/connector）共用该 logger，
    但从不 addHandler；MCDR 的 console/file handler 挂在插件自身 logger 上，
    root 无 handler → INFO 全丢、WARNING+ 只落 lastResort 裸 stderr。

    - DEBUG 走 ``target.mdebug(no_check=True)``：MCDReforgedLogger 构造即
      setLevel(INFO)，``log(DEBUG, ...)`` 会被级别门丢弃，verbose 形同虚设
    - 有 exc_info 时把格式化堆栈附进消息（``record.getMessage()`` 不含堆栈）
    - 目标 logger 经连接器弱引用在 emit 时解析：连接器 ``__init__`` 时
      ``self.logger`` 尚为 None（ConnectorManager 注册时才覆写为 MCDR
      logger），插件重载后须指向新实例；连接器被回收后记录静默丢弃，
      handler 不延长其生命周期
    """

    def __init__(self, connector) -> None:
        super().__init__()
        self._connector_ref = weakref.ref(connector)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            connector = self._connector_ref()
            target = getattr(connector, "logger", None)
            if target is None:
                return
            msg = record.getMessage()
            if record.exc_info:
                msg = f"{msg}\n" + "".join(
                    traceback.format_exception(*record.exc_info)
                )
            if record.levelno >= logging.INFO:
                target.log(record.levelno, msg)
            else:
                target.mdebug(msg, no_check=True)
        except Exception:
            # 转发目标异常（如测试桩缺 .log/.mdebug）不得反噬调用方：
            # 网关线程在 WS 收包路径上打日志，emit 抛错会中断收包循环
            self.handleError(record)


class OpenQQBotConnector(BasicConnector):
    """QQ 官方机器人连接器。

    配置段为 ``connector.open-qq-bot``（注意：段名即配置路径，
    ``source_name`` 仅用于消息来源显示，两者解耦的做法与
    BridgeConnector 相同——先按段名 super 初始化，再覆盖 ``self.source``）。
    """

    SECTION = "open-qq-bot"

    # 连接器级调试命令（OpenID 查询，部署/排障用，在广播管线前拦截）
    DEBUG_COMMANDS = ("/groupId", "/userId", "/botId")

    def __init__(self, server, config: Optional[BotConfig] = None):
        source_name = config.get_keys(
            ["connector", self.SECTION, "source_name"], "OpenQQBot"
        )
        super().__init__(
            source=self.SECTION, parser=OpenQQBotParser, server=server, config=config
        )
        # enable/enable_receive/enable_send 已按段名读取完毕，这里仅覆盖显示名
        self.source = source_name
        connector_basic_name = self.server.tr("gugubot.connector.name")
        self.log_prefix = f"[{connector_basic_name}{self.source}]"

        # 排障日志开关：MCDR 的 debug.<option> 不作用于插件 logger
        # （set_debug_options 设在主 logger 的子类上），故按配置显式调试模块 logger；
        # 同一 logger 还会输出 ApiClient 的 HTTP 请求/响应明细。
        self.verbose = bool(
            config.get_keys(["connector", self.SECTION, "verbose"], False)
        )
        self._diag_logger = logging.getLogger("gugubot.open_qq_bot")
        # 子包日志修复：该 logger 原本无任何 handler（MCDR 的 console/file
        # handler 挂在插件自身 logger 上，root 也没有），INFO 全丢、WARNING+
        # 只落 lastResort 裸 stderr。挂转发 handler 后一处 attach 全子包受益；
        # 按属性防重挂（MCDR 插件重载时模块级 logger 仍存活）
        handler = getattr(self._diag_logger, "_mcdr_forward_handler", None)
        if handler is None:
            handler = _MCDRForwardHandler(self)
            handler.setLevel(logging.INFO)
            self._diag_logger.addHandler(handler)
            self._diag_logger.propagate = False
            self._diag_logger._mcdr_forward_handler = handler
        # 重载后重新指向新连接器实例；默认放行 INFO，verbose 时放行 DEBUG
        handler._connector_ref = weakref.ref(self)
        handler.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        self._diag_logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)

        self.app_id = config.get_keys(
            ["connector", self.SECTION, "connection", "app_id"], ""
        )
        self.app_secret = config.get_keys(
            ["connector", self.SECTION, "connection", "app_secret"], ""
        )
        self.sandbox = config.get_keys(
            ["connector", self.SECTION, "connection", "sandbox"], False
        )
        self.intents = INTENTS
        # 分片长度上限：配置边界防御（非整数/<=0 会导致分片死循环或 TypeError）
        try:
            self.max_message_length = max(1, int(config.get_keys(
                ["connector", self.SECTION, "connection", "max_message_length"],
                2000,
            )))
        except (TypeError, ValueError):
            self.max_message_length = 2000
        self.per_minute = config.get_keys(
            ["connector", self.SECTION, "rate_limit", "per_minute"], 20
        )
        self.per_day = config.get_keys(
            ["connector", self.SECTION, "rate_limit", "per_day"], 1000
        )
        # Bot 维度全局主动消息限速（官方 30~60 条/分钟，多群广播合计）
        self.bot_per_minute = config.get_keys(
            ["connector", self.SECTION, "rate_limit", "bot_per_minute"], 30
        )
        try:
            quota_path = Path(server.get_data_folder()) / "open_qq_bot_quota.json"
        except Exception:
            quota_path = None
        self.quota = QuotaManager(
            self.per_minute, self.per_day, quota_path,
            bot_per_minute=self.bot_per_minute,
        )
        # 机器人自身群聊 OpenID：READY 只返回数字 id（与 OpenID 不同源），
        # 只能从被 @ 事件的 mentions(bot:true) 习得；供 /botId 查询使用
        self.bot_openid = None

        self.tokens = TokenManager(self.app_id, self.app_secret)
        self.api = ApiClient(
            self.tokens, sandbox=self.sandbox, max_message_length=self.max_message_length
        )
        self.dedup = DedupSet()
        # 群消息被动回复池：MC→QQ 广播优先复用最近群消息的 msg_id，
        # 省下主动配额。本地窗口 290 秒（5 分钟 -10 秒），过期/超次即淘汰
        self.passive_pool = None
        pool_enabled = config.get_keys(
            ["connector", self.SECTION, "passive_pool", "enable"], True
        )
        if pool_enabled:
            try:
                pool_size = int(config.get_keys(
                    ["connector", self.SECTION, "passive_pool", "max_per_group"], 10
                ))
            except (TypeError, ValueError):
                pool_size = 10
            self.passive_pool = PassiveMsgPool(self.api.seq, max_per_group=pool_size)
        self.gateway = Gateway(
            gateway_url_getter=self.api.gateway_url,
            token_getter=self.tokens.get,
            on_event=self._on_gateway_event,
            on_ready=self._on_ready,
            intents=self.intents,
        )

    # ---- BasicConnector 接口 ----

    def _diag(self, msg: str, *args) -> None:
        """排障日志：仅 ``connector.open-qq-bot.verbose=true`` 时输出。"""
        if self.verbose:
            self._diag_logger.debug(msg, *args)

    async def connect(self) -> None:
        if not self.enable:
            self.logger.info(
                f"{self.log_prefix} {self.server.tr('gugubot.connector.open-qq-bot.disabled')}"
            )
            return
        if not self.app_id or not self.app_secret:
            self.logger.warning(
                f"{self.log_prefix} "
                f"{self.server.tr('gugubot.connector.open-qq-bot.not_configured')}"
            )
            return
        self.logger.info(
            f"{self.log_prefix} "
            f"{self.server.tr('gugubot.connector.open-qq-bot.try_connect')}"
        )
        self.gateway.connect()

    async def disconnect(self) -> None:
        self.gateway.stop()
        self.logger.info(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.open-qq-bot.closed')}"
        )

    @property
    def connected(self) -> bool:
        """官方网关是否在线（网关线程存活即视为在线/重连中）。

        健康检查面：网关线程意外死亡时插件仍显示已加载，可通过此属性
        探测真实连接状态（避免「线程已死但插件看起来正常」）。
        """
        return bool(self.enable and self.gateway.alive)

    async def on_message(self, raw: dict) -> None:
        """直接注入一个官方事件（dict 形态），供测试或其他插件调用。"""
        self._dispatch_event(raw)

    async def send_message(self, processed_info: ProcessedInfo) -> None:
        if not self.enable:
            return
        # ApiClient 为同步阻塞实现，放入线程避免阻塞 MCDR 事件循环
        await asyncio.to_thread(self._send_sync, processed_info)

    # ---- 入站 ----

    def _on_ready(self, user: dict) -> None:
        username = user.get("username", "?")
        self.logger.info(
            f"{self.log_prefix} "
            f"{self.server.tr('gugubot.connector.open-qq-bot.connect_success', username=username)}"
        )

    def _record_passive_anchor(self, t: str, d: dict) -> None:
        """记录群消息 msg_id 到被动回复池（去重之后、调试命令拦截之前）。

        调试命令消息也记录：其 msg_id 仍可用于被动回复，调试回复消耗的
        一次额度由 SeqManager 统一记账，不会与池重复计数。
        """
        if self.passive_pool is None:
            return
        if t not in ("GROUP_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"):
            return
        group = d.get("group_openid")
        msg_id = d.get("id")
        if not group or not msg_id:
            return
        self.passive_pool.record(str(group), str(msg_id))

    def _on_gateway_event(self, t: str, d: dict, event_id: Optional[str]) -> None:
        """网关线程回调：去重/过滤后调度到 MCDR 事件循环。"""
        if not self.enable:
            return
        allowed = set(OpenQQBotParser.MESSAGE_EVENTS) | set(OpenQQBotParser.NOTICE_EVENTS)
        if t not in allowed:
            self._diag("忽略事件 %s", t)
            return
        author = d.get("author") or {}
        if author.get("bot"):
            return
        msg_id = d.get("id")
        if msg_id and self.dedup.seen(msg_id):
            self._diag("%s 重复事件已去重：msg_id=%s", self.log_prefix, msg_id)
            return
        # 诊断日志：开启 MCDR debug 后可见（内容和发送结果不放 INFO，避免噪音）
        self._diag(
            "%s 入站 %s | 会话=%s | 发送者=%s | 内容=%r | 提及机器人=%s",
            self.log_prefix,
            t,
            d.get("group_openid") or author.get("user_openid") or author.get("id") or "",
            author.get("username") or author.get("member_openid")
            or author.get("user_openid") or "?",
            (d.get("content") or "")[:200],
            any(u.get("bot") for u in d.get("mentions") or []),
        )
        # 记录机器人自身 OpenID；拦截 /groupId /userId /botId（不进广播管线）
        self._record_passive_anchor(t, d)
        self._learn_bot_openid(d)
        if self._try_debug_command(t, d):
            return
        if self.parser is None:
            return
        event = {"t": t, "d": d, "event_id": event_id}
        self.server.schedule_task(self.parser.process_message(event))

    def _dispatch_event(self, raw: dict) -> None:
        """on_message 的同步实现（不经过网关线程）。"""
        if not self.enable:
            return
        d = raw.get("d") or {}
        self._record_passive_anchor(raw.get("t"), d)
        self._learn_bot_openid(d)
        if self._try_debug_command(raw.get("t"), d):
            return
        if self.parser is None:
            return
        self.server.schedule_task(self.parser.process_message(raw))

    # ---- 连接器级调试命令 ----

    def _learn_bot_openid(self, d: dict) -> None:
        """从 mentions 的 bot:true 条目记录机器人自身 OpenID（首遇即固定）。

        READY 事件返回的是数字 id，与群聊可用的 OpenID 不同源；
        机器人的群聊 OpenID 只能从被 @ 事件的 mentions 中习得。
        """
        if self.bot_openid:
            return
        for user in d.get("mentions") or []:
            if user.get("bot"):
                oid = user.get("member_openid") or user.get("id") or ""
                if oid:
                    self.bot_openid = oid
                    self.logger.info(
                        f"{self.log_prefix} 记录机器人自身 OpenID={oid}（来自 mentions）"
                    )
                    return

    def _try_debug_command(self, t: str, d: dict) -> bool:
        """拦截 /groupId /userId /botId 查询命令并被动回复。

        - 在广播管线之前拦截：不触发关键词/违禁词，也不会转发进 MC
        - 带 msg_id 被动锚点回复，不占主动消息配额
        - 不受 group_ids 白名单约束：向白名单添加新群前，需要先能在该群
          查询 OpenID（OpenID 为不透明标识而非 QQ 号，泄露风险可忽略）
        - 回复为阻塞 HTTP，经事件循环 + 线程池调度执行（见 _schedule_debug_reply），
          避免卡住网关 WS 读线程（延迟心跳 ACK 处理，触发误重连）或 MCDR 事件循环

        Returns
        -------
        bool
            True 表示已作为调试命令处理（回复任务已调度），调用方不再分发该事件
        """
        if t not in OpenQQBotParser.MESSAGE_EVENTS:
            return False
        content = AT_TAG_RE.sub("", d.get("content") or "").strip()
        if not content:
            return False
        command = content.split()[0]
        if command not in self.DEBUG_COMMANDS:
            return False

        is_group = t != "C2C_MESSAGE_CREATE"
        author = d.get("author") or {}
        msg_id = d.get("id")
        if is_group:
            chat_id = d.get("group_openid", "")
        else:
            chat_id = author.get("user_openid") or author.get("id") or ""

        self._diag(
            "%s 调试命令 %s | 会话=%s | msg_id=%s",
            self.log_prefix, command, chat_id, msg_id,
        )

        if command == "/groupId":
            if is_group:
                self._schedule_debug_reply(
                    chat_id,
                    self.server.tr(
                        "gugubot.connector.open-qq-bot.debug_group_id",
                        group_id=d.get("group_openid", ""),
                    ),
                    msg_id, is_group,
                )
            else:
                self._schedule_debug_reply(
                    chat_id,
                    self.server.tr("gugubot.connector.open-qq-bot.debug_group_id_c2c"),
                    msg_id, is_group,
                )
            return True

        if command == "/userId":
            if is_group:
                members = [
                    (u.get("member_openid") or u.get("id") or "",
                     u.get("username") or "")
                    for u in d.get("mentions") or []
                    if not u.get("bot")
                ]
                if not members:
                    text = self.server.tr(
                        "gugubot.connector.open-qq-bot.debug_user_id_usage"
                    )
                elif len(members) > 1:
                    text = self.server.tr(
                        "gugubot.connector.open-qq-bot.debug_user_id_multi"
                    )
                else:
                    user_id, username = members[0]
                    text = self.server.tr(
                        "gugubot.connector.open-qq-bot.debug_user_id",
                        username=username or user_id[:8],
                        user_id=user_id,
                    )
                self._schedule_debug_reply(chat_id, text, msg_id, is_group)
            else:
                self._schedule_debug_reply(
                    chat_id,
                    self.server.tr(
                        "gugubot.connector.open-qq-bot.debug_user_id_self",
                        user_id=chat_id,
                    ),
                    msg_id, is_group,
                )
            return True

        # /botId：自身 OpenID 尚未习得时提示先 @机器人
        if self.bot_openid:
            text = self.server.tr(
                "gugubot.connector.open-qq-bot.debug_bot_id", bot_id=self.bot_openid
            )
        else:
            text = self.server.tr(
                "gugubot.connector.open-qq-bot.debug_bot_id_unknown"
            )
        self._schedule_debug_reply(chat_id, text, msg_id, is_group)
        return True

    def _schedule_debug_reply(self, chat_id: str, text: str, msg_id, is_group: bool) -> None:
        """调度调试命令的被动回复任务（真正的发送见 _debug_reply）。"""
        if not chat_id:
            return
        self.server.schedule_task(
            self._debug_reply_task(chat_id, text, msg_id, is_group)
        )

    async def _debug_reply_task(self, chat_id: str, text: str, msg_id, is_group: bool) -> None:
        try:
            await asyncio.to_thread(self._debug_reply, chat_id, text, msg_id, is_group)
        except Exception as e:
            self.logger.warning(f"{self.log_prefix} 调试命令回复失败: {e}")

    def _debug_reply(self, chat_id: str, text: str, msg_id, is_group: bool) -> None:
        """调试命令的被动回复（阻塞实现，经 _debug_reply_task 在线程池中执行）。

        失败仅告警（被动窗口过期即放弃，不降级）。
        """
        if is_group:
            self.api.send_group_text(chat_id, text, msg_id=msg_id)
        else:
            self.api.send_c2c_text(chat_id, text, msg_id=msg_id)
        self._diag(
            "%s 调试命令回复已发送 → %s: %r", self.log_prefix, chat_id, text[:120]
        )

    # ---- 出站 ----

    def _default_targets(self) -> dict:
        """默认投递目标：forward_group_ids 回退 group_ids（与 QQ 连接器同约定）。"""
        forward_group_ids = self.config.get_keys(
            ["connector", self.SECTION, "permissions", "forward_group_ids"], []
        )
        if not forward_group_ids or not any(forward_group_ids):
            forward_group_ids = self.config.get_keys(
                ["connector", self.SECTION, "permissions", "group_ids"], []
            )
        return {str(g): "group" for g in forward_group_ids if g}

    def _strip_color_codes(self, message: list) -> list:
        """剥离 Minecraft 颜色码（§x），返回新列表。"""
        result = []
        for item in message:
            if isinstance(item, dict) and item.get("type") == "text":
                new_item = item.copy()
                new_data = item.get("data", {}).copy()
                if "text" in new_data:
                    new_data["text"] = MC_COLOR_CODE.sub("", new_data["text"])
                new_item["data"] = new_data
                result.append(new_item)
            else:
                result.append(item)
        return result

    def _build_source_prefix(self, processed_info: ProcessedInfo) -> list:
        """跨源消息前缀（chat_templates 加权随机，占位符 {display_name}/{sender}）。"""
        source = processed_info.source
        chat_templates = self.config.get_keys(
            ["connector", self.SECTION, "chat_templates"], []
        )
        prefix_text = None
        if chat_templates and isinstance(chat_templates, list):
            templates, weights = [], []
            for item in chat_templates:
                if isinstance(item, dict):
                    for template_str, weight in item.items():
                        templates.append(template_str)
                        weights.append(weight if isinstance(weight, (int, float)) else 1)
            if templates:
                prefix_text = random.choices(templates, weights=weights, k=1)[0].format(
                    display_name=source.origin, sender=processed_info.sender
                )
        if prefix_text is None:
            prefix_text = f"[{source.origin}] {processed_info.sender}: "
        return [{"type": "text", "data": {"text": prefix_text}}]

    def _segments_to_official(self, message: list, *, allow_mention: bool = False):
        """内部段数组 → (纯文本, 图片 URL 列表, 是否含 @ 提及)。

        - text 段拼接（剥离外部内容伪造的 ``<qqbot-at-*>`` 标签）
        - at 段：群聊且 qq 为 32 位 OpenID 时渲染成 Markdown 的
          ``<qqbot-at-user id="..."/>``（实测纯文本不渲染，见 demo README）；
          ``all`` 与其它值一律退化为 ``@id`` 文本，不支持从服务器 @全体
        - image 段提取公网 URL（data.file / data.url）：须通过
          :data:`IMAGE_URL_RE` 白名单校验，否则降级为 ``[图片]`` 占位文本
          （保留图片语义，不静默丢弃，也不给 Markdown 注入留下入口）
        """
        texts, images = [], []
        has_mention = False
        for item in message:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            data = item.get("data") or {}
            if item_type == "text":
                texts.append(MENTION_TAG_RE.sub("", data.get("text", "")))
            elif item_type == "at":
                target = str(data.get("qq", ""))
                if allow_mention and OPENID_RE.match(target):
                    texts.append(at_user_tag(target))
                    has_mention = True
                else:
                    texts.append(f"@{target}")
            elif item_type == "image":
                url = data.get("file") or data.get("url")
                if isinstance(url, str) and IMAGE_URL_RE.match(url):
                    images.append(url)
                else:
                    # URL 不在白名单（可注入 Markdown 语法的字符）→ 占位文本
                    texts.append("[图片]")
        plain = "".join(texts).strip()
        return plain, images, has_mention

    def _markdown_content(self, plain: str, images: list) -> str:
        """群 Markdown 通道完整内容（图片以 ``![图片](url)`` 追加）。"""
        content = plain
        if images:
            content += "\n\n" + "\n\n".join(f"![图片]({url})" for url in images)
        return content

    def _plan_chunks(self, target_type: str, plain: str, images: list,
                     has_mention: bool = False) -> list:
        """按 ApiClient 相同规则切分出实际分片列表。

        与 :meth:`ApiClient.send_group_text` / ``send_group_markdown``
        的分片逻辑严格一致，供分片数预估与后缀补发复用。
        """
        if target_type == "private" or not (images or has_mention):
            return split_message(plain or "", self.max_message_length)
        return split_markdown(
            self._markdown_content(plain or "", images or []),
            self.max_message_length,
        )

    def _chunk_count(self, target_type: str, plain: str, images: list,
                     has_mention: bool = False) -> int:
        """预估本次发送将产生的 API 分片数（与 ApiClient 分片逻辑一致）。

        供主动消息配额按实际请求数记账（一次分片发送 ≠ 一个 API 请求）。
        """
        return max(1, len(self._plan_chunks(target_type, plain, images,
                                            has_mention)))

    def _send_sync(self, processed_info: ProcessedInfo) -> None:
        """阻塞发送实现（由 send_message 通过 asyncio.to_thread 调用）。"""
        source = processed_info.source
        message = self._strip_color_codes(list(processed_info.processed_message or []))

        # 跨源消息加来源前缀（进/出群通知类 sender 为空，仅加来源标签）
        if not source.is_from(self.source) and source.origin:
            if processed_info.sender:
                message = self._build_source_prefix(processed_info) + message
            else:
                message = [{"type": "text", "data": {"text": f"[{source.origin}] "}}] + message

        plain, images, _ = self._segments_to_official(message)
        if not plain and not images:
            self._diag("%s 出站内容为空（无文本/图片），跳过", self.log_prefix)
            return

        resolved = self._resolve_targets(processed_info)
        self._diag(
            "%s 出站目标：%s（来源=%s/%s）",
            self.log_prefix, list(resolved.items()) or "无",
            source.origin, processed_info.source_id,
        )
        for target_id, target_type in resolved.items():
            # @ 提及仅在群聊渲染，且必须走 Markdown；私聊保持纯文本
            if target_type == "group":
                target_plain, target_images, has_mention = self._segments_to_official(
                    message, allow_mention=True
                )
            else:
                target_plain, target_images, has_mention = plain, images, False
                # 单聊暂不支持富媒体下发：图片以占位符并入文本，避免内容静默丢失
                if target_images:
                    target_plain = f"{target_plain}\n[图片]" if target_plain else "[图片]"
                    target_images = []
            # 被动回复锚点：优先同源事件（命令回复），其次取本群被动消息池。
            # 池路径一次性原子预留整块 msg_seq（预留即分配，对其他回复路径
            # 具约束力，也不与已分配部分重复计数）
            anchor_id = self._reply_anchor(processed_info, target_id)
            needed = self._chunk_count(target_type, target_plain, target_images,
                                       has_mention)
            pooled_anchor = None
            pooled_seqs = None
            if anchor_id is None and target_type == "group" and self.passive_pool:
                pooled = self.passive_pool.acquire(target_id, needed)
                if pooled:
                    anchor_id, pooled_seqs = pooled
                    pooled_anchor = anchor_id
            # 主动消息配额（官方：单群 20 条/分钟、1000 条/天、Bot 全局 30~60
            # 条/分钟）；被动回复不占配额；分片按实际 API 请求数记账
            if anchor_id is None and not self.quota.allow_many(target_id, needed):
                self.logger.warning(
                    f"{self.log_prefix} 主动消息配额已用尽（{target_id}: "
                    f"{self.per_minute}/分钟、{self.per_day}/天），丢弃本条"
                )
                continue
            self._diag(
                "%s 发送 → %s（%s，msg_id=%s）：%r",
                self.log_prefix, target_id,
                "被动(池)" if pooled_anchor else ("被动" if anchor_id else "主动"),
                anchor_id, target_plain[:120],
            )
            try:
                if target_type == "private":
                    try:
                        sent = self.api.send_c2c_text(target_id, target_plain, msg_id=anchor_id)
                    except ApiError as e:
                        if not (anchor_id and e.has_code(*ERR_PASSIVE_EXPIRED)):
                            raise
                        sent = True
                        if anchor_id and self.passive_pool:
                            self.passive_pool.invalidate(target_id, anchor_id)
                        self._send_active_fallback(target_id, target_type, target_plain, target_images)
                elif target_images or has_mention:
                    content = self._markdown_content(target_plain, target_images)
                    try:
                        sent = self.api.send_group_markdown(target_id, content,
                                                            msg_id=anchor_id,
                                                            seqs=pooled_seqs)
                    except ApiError as e:
                        if not (anchor_id and e.has_code(*ERR_PASSIVE_EXPIRED)):
                            raise
                        sent = True
                        if anchor_id and self.passive_pool:
                            self.passive_pool.invalidate(target_id, anchor_id)
                        # 降级传纯文本 + 图片列表，由 _send_active_fallback
                        # 统一拼装 Markdown（避免图片 URL 重复追加）
                        self._send_active_fallback(target_id, target_type, target_plain, target_images)
                else:
                    try:
                        sent = self.api.send_group_text(target_id, target_plain,
                                                        msg_id=anchor_id,
                                                        seqs=pooled_seqs)
                    except ApiError as e:
                        if not (anchor_id and e.has_code(*ERR_PASSIVE_EXPIRED)):
                            raise
                        sent = True
                        if anchor_id and self.passive_pool:
                            self.passive_pool.invalidate(target_id, anchor_id)
                        self._send_active_fallback(target_id, target_type, target_plain, target_images)
                if sent is None and anchor_id:
                    # send_* 在一片未发出时返回 None（SeqManager 上限）而非抛错，
                    # 此时消息未发出：降级为主动消息，避免静默丢失
                    if anchor_id and self.passive_pool:
                        self.passive_pool.invalidate(target_id, anchor_id)
                    self.logger.info(
                        f"{self.log_prefix} 被动回复次数耗尽，降级为主动消息发送到 {target_id}"
                    )
                    self._send_active_fallback(target_id, target_type, target_plain, target_images)
                self._diag("%s 发送成功 → %s", self.log_prefix, target_id)
            except PartialDelivery as e:
                # 分片部分送达：整体降级重发会重复已送达内容；仅当失败原因
                # 是被动锚点中途失效（ERR_PASSIVE_EXPIRED）时，未发送尾部
                # 尚未送达，按主动消息补发后缀（配额允许时）
                cause = e.__cause__
                expired = isinstance(cause, ApiError) \
                    and cause.has_code(*ERR_PASSIVE_EXPIRED)
                if expired and anchor_id and self.passive_pool:
                    self.passive_pool.invalidate(target_id, anchor_id)
                self.logger.warning(
                    f"{self.log_prefix} 发送到 {target_id} 部分送达："
                    f"{e.sent} 片成功，{e.remaining} 片未发出"
                    + ("（被动锚点失效）" if expired else "，剩余内容已丢弃")
                )
                if expired and self.quota.allow_many(target_id, e.remaining):
                    chunks = self._plan_chunks(target_type, target_plain,
                                               target_images, has_mention)
                    suffix = chunks[e.sent:]
                    self.logger.info(
                        f"{self.log_prefix} 被动锚点中途失效，剩余 {len(suffix)} 片"
                        f"转主动消息补发到 {target_id}"
                    )
                    for idx, chunk in enumerate(suffix):
                        # 各片已是预切分结果（ApiClient 内部再切必为单片，
                        # 其片间限速不会触发）：在此显式限速，与其他多片
                        # 发送路径的突发保护保持一致
                        if idx > 0:
                            time.sleep(random_send_delay())
                        try:
                            if target_type == "private":
                                # 单聊走 C2C 端点，与主发送路径一致；
                                # 复用群端点会必然报错且浪费已预留配额
                                self.api.send_c2c_text(target_id, chunk)
                            elif target_images or has_mention:
                                self.api.send_group_markdown(target_id, chunk)
                            else:
                                self.api.send_group_text(target_id, chunk)
                        except Exception as send_err:
                            # 补发失败不得逃逸出本处理器（同级 handler 不拦截
                            # handler 内新抛的异常）：中止补发并告警，其余目标
                            # 照常投递——降级路径不得比主路径更脆
                            self.logger.warning(
                                f"{self.log_prefix} 后缀补发到 {target_id} 失败，"
                                f"自第 {e.sent + idx + 1} 片起剩余 "
                                f"{len(suffix) - idx} 片未送达：{send_err}"
                            )
                            break
                elif expired:
                    self.logger.warning(
                        f"{self.log_prefix} 主动消息配额不足（{target_id}），"
                        f"剩余 {e.remaining} 片丢弃"
                    )
            except Exception as e:
                code = getattr(e, "err_code", None) or getattr(e, "api_code", "?")
                self.logger.warning(
                    f"{self.log_prefix} 发送到 {target_id} 失败（{code}）：{e}"
                )
            finally:
                if pooled_anchor:
                    # 预留块不回退（见 PassiveMsgPool）；仅及时淘汰已用尽条目
                    self.passive_pool.release(target_id, pooled_anchor)

    def _resolve_targets(self, processed_info: ProcessedInfo) -> dict:
        """解析投递目标。

        - 数字 ID = OneBot 连接器领地，跳过
        - 32 位 OpenID = 本连接器会话，直接投递
        - 显示名（BasicSystem.reply 对非数字 source_id 的回退形态，key == 显示名
          或段名）→ 映射回触发消息的 ``processed_info.source_id``（来源群/用户）
        - 无法解析时回退默认目标集合（MC 广播等 target=None 的场景不走这里）
        """
        section = self.SECTION
        targets = processed_info.target or self._default_targets()
        resolved = {}
        for target_id, target_type in (targets or {}).items():
            target_id = str(target_id)
            if OPENID_RE.match(target_id):
                resolved[target_id] = target_type
            elif target_id in (self.source, section):
                sid = str(processed_info.source_id or "")
                if OPENID_RE.match(sid):
                    resolved[sid] = target_type
                else:
                    self._diag(
                        f"{self.log_prefix} 回复目标 {target_id} 无法映射到来源会话，跳过"
                    )
            else:
                self._diag(f"{self.log_prefix} 跳过非本连接器目标：{target_id}")
        return resolved

    def _reply_anchor(self, processed_info: ProcessedInfo, target_id: str):
        """取被动回复锚点：仅当目标与触发消息同一会话时有效。"""
        raw = processed_info.raw
        if not isinstance(raw, dict):
            return None
        author = raw.get("author") or {}
        chat = raw.get("group_openid") or author.get("member_openid") \
            or author.get("user_openid")
        if chat == target_id:
            return raw.get("id")
        return None

    def _send_active_fallback(self, target_id, target_type, plain, images):
        """被动回复窗口失效（40034005 等）时的主动消息降级。

        ``plain`` 必须是不含图片 Markdown 的纯文本：图片统一由本方法
        拼装（调用方传已拼装内容会导致图片重复追加）。
        """
        if not self.quota.allow_many(
            target_id,
            self._chunk_count(target_type, plain, images,
                              has_mention="<qqbot-at-" in plain),
        ):
            self.logger.warning(
                f"{self.log_prefix} 主动消息配额已用尽（{target_id}），降级发送已丢弃"
            )
            return
        self.logger.info(
            f"{self.log_prefix} 被动回复失效，降级为主动消息发送到 {target_id}"
        )
        if target_type == "private":
            self.api.send_c2c_text(target_id, plain)
        elif images or "<qqbot-at-" in plain:
            self.api.send_group_markdown(target_id, self._markdown_content(plain, images))
        else:
            self.api.send_group_text(target_id, plain)
