"""QQ 官方机器人连接器（open-qq-bot）。

继承 :class:`BasicConnector`，把 QQ 官方机器人 WebSocket API 适配进
GUGUBot 的 connector 管线，与 OneBot 版 QQWebSocketConnector 并行使用：

- 入站：gateway 线程收到事件 → 去重/过滤 → ``server.schedule_task``
  交给 :class:`OpenQQBotParser` → BroadcastInfo → 既有系统管线
- 出站：``send_message(ProcessedInfo)`` → 段数组转官方文本/Markdown
  （含跨源前缀、颜色码剥离、@/图片转换）→ ``asyncio.to_thread`` 调 API

与 OneBot 版的关键差异（官方平台限制，见 devDocs/open-qq-bot/）：
- 出站均为主动消息，受频控（单群 20 条/分钟、1000 条/天），无配额管理前
  不适合做高流量的 MC→QQ 全量聊天同步
- @ 标签仅 Markdown 通道渲染；被动回复有 5 分钟/5 次窗口（SeqManager 管理）
"""

import asyncio
import random
import re
from typing import Optional

from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.connector.open_qq_bot.api_client import ApiClient, TokenManager
from gugubot.connector.open_qq_bot.common import (
    ERR_PASSIVE_EXPIRED,
    ApiError,
    DedupSet,
    QuotaManager,
)
from pathlib import Path
from gugubot.connector.open_qq_bot.gateway import Gateway
from gugubot.connector.open_qq_bot.parser import OpenQQBotParser
from gugubot.utils.types import ProcessedInfo

INTENTS_DEFAULT = (1 << 25) | (1 << 24)  # GROUP_AND_C2C_EVENT | GROUP_MEMBER_EVENT
OPENID_RE = re.compile(r"^[0-9A-Fa-f]{32}$")

MC_COLOR_CODE = re.compile(r"§[0-9a-fk-or]", re.IGNORECASE)


class OpenQQBotConnector(BasicConnector):
    """QQ 官方机器人连接器。

    配置段为 ``connector.open-qq-bot``（注意：段名即配置路径，
    ``source_name`` 仅用于消息来源显示，两者解耦的做法与
    BridgeConnector 相同——先按段名 super 初始化，再覆盖 ``self.source``）。
    """

    SECTION = "open-qq-bot"

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

        self.app_id = config.get_keys(
            ["connector", self.SECTION, "connection", "app_id"], ""
        )
        self.app_secret = config.get_keys(
            ["connector", self.SECTION, "connection", "app_secret"], ""
        )
        self.sandbox = config.get_keys(
            ["connector", self.SECTION, "connection", "sandbox"], False
        )
        self.intents = config.get_keys(
            ["connector", self.SECTION, "connection", "intents"], INTENTS_DEFAULT
        )
        self.max_message_length = config.get_keys(
            ["connector", self.SECTION, "connection", "max_message_length"], 2000
        )
        self.per_minute = config.get_keys(
            ["connector", self.SECTION, "rate_limit", "per_minute"], 20
        )
        self.per_day = config.get_keys(
            ["connector", self.SECTION, "rate_limit", "per_day"], 1000
        )
        try:
            quota_path = Path(server.get_data_folder()) / "open_qq_bot_quota.json"
        except Exception:
            quota_path = None
        self.quota = QuotaManager(self.per_minute, self.per_day, quota_path)

        self.tokens = TokenManager(self.app_id, self.app_secret)
        self.api = ApiClient(
            self.tokens, sandbox=self.sandbox, max_message_length=self.max_message_length
        )
        self.dedup = DedupSet()
        self.gateway = Gateway(
            gateway_url_getter=self.api.gateway_url,
            token_getter=self.tokens.get,
            on_event=self._on_gateway_event,
            on_ready=self._on_ready,
            intents=self.intents,
        )

    # ---- BasicConnector 接口 ----

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

    def _on_gateway_event(self, t: str, d: dict, event_id: Optional[str]) -> None:
        """网关线程回调：去重/过滤后调度到 MCDR 事件循环。"""
        if not self.enable:
            return
        allowed = set(OpenQQBotParser.MESSAGE_EVENTS) | set(OpenQQBotParser.NOTICE_EVENTS)
        if t not in allowed:
            self.logger.debug("忽略事件 %s", t)
            return
        author = d.get("author") or {}
        if author.get("bot"):
            return
        msg_id = d.get("id")
        if msg_id and self.dedup.seen(msg_id):
            return
        if self.parser is None:
            return
        event = {"t": t, "d": d, "event_id": event_id}
        self.server.schedule_task(self.parser.process_message(event))

    def _dispatch_event(self, raw: dict) -> None:
        """on_message 的同步实现（不经过网关线程）。"""
        if not self.enable:
            return
        if self.parser is None:
            return
        self.server.schedule_task(self.parser.process_message(raw))

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

    def _segments_to_official(self, message: list):
        """内部段数组 → (纯文本, 图片 URL 列表)。

        - text 段拼接；at 段转 ``@id`` 文本
        - image 段提取公网 URL（data.file / data.url）
        """
        texts, images = [], []
        for item in message:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            data = item.get("data") or {}
            if item_type == "text":
                texts.append(data.get("text", ""))
            elif item_type == "at":
                texts.append(f"@{data.get('qq', '')}")
            elif item_type == "image":
                url = data.get("file") or data.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    images.append(url)
                else:
                    texts.append("[图片]")
        plain = "".join(texts).strip()
        return plain, images

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

        plain, images = self._segments_to_official(message)
        if not plain and not images:
            return

        resolved = self._resolve_targets(processed_info)
        for target_id, target_type in resolved.items():
            # 被动回复锚点：仅当目标与触发消息同一会话时使用（5 分钟/5 次窗口）
            anchor_id = self._reply_anchor(processed_info, target_id)
            # 主动消息配额（官方：单群 20 条/分钟、1000 条/天）；被动回复不占配额
            if anchor_id is None and not self.quota.allow(target_id):
                self.logger.warning(
                    f"{self.log_prefix} 主动消息配额已用尽（{target_id}: "
                    f"{self.per_minute}/分钟、{self.per_day}/天），丢弃本条"
                )
                continue
            try:
                if target_type == "private":
                    try:
                        self.api.send_c2c_text(target_id, plain, msg_id=anchor_id)
                    except ApiError as e:
                        if not (anchor_id and e.has_code(*ERR_PASSIVE_EXPIRED)):
                            raise
                        self._send_active_fallback(target_id, target_type, plain, images)
                elif images:
                    content = plain + "\n\n" + "\n\n".join(
                        f"![图片]({url})" for url in images
                    )
                    try:
                        self.api.send_group_markdown(target_id, content, msg_id=anchor_id)
                    except ApiError as e:
                        if not (anchor_id and e.has_code(*ERR_PASSIVE_EXPIRED)):
                            raise
                        self._send_active_fallback(target_id, target_type, content, images)
                else:
                    try:
                        self.api.send_group_text(target_id, plain, msg_id=anchor_id)
                    except ApiError as e:
                        if not (anchor_id and e.has_code(*ERR_PASSIVE_EXPIRED)):
                            raise
                        self._send_active_fallback(target_id, target_type, plain, images)
            except Exception as e:
                code = getattr(e, "err_code", None) or getattr(e, "api_code", "?")
                self.logger.warning(
                    f"{self.log_prefix} 发送到 {target_id} 失败（{code}）：{e}"
                )

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
                    self.logger.debug(
                        f"{self.log_prefix} 回复目标 {target_id} 无法映射到来源会话，跳过"
                    )
            else:
                self.logger.debug(f"{self.log_prefix} 跳过非本连接器目标：{target_id}")
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
        """被动回复窗口失效（40034005 等）时的主动消息降级。"""
        if not self.quota.allow(target_id):
            self.logger.warning(
                f"{self.log_prefix} 主动消息配额已用尽（{target_id}），降级发送已丢弃"
            )
            return
        self.logger.info(
            f"{self.log_prefix} 被动回复失效，降级为主动消息发送到 {target_id}"
        )
        if target_type == "private":
            self.api.send_c2c_text(target_id, plain)
        elif images:
            content = plain + "\n\n" + "\n\n".join(f"![图片]({url})" for url in images)
            self.api.send_group_markdown(target_id, content)
        else:
            self.api.send_group_text(target_id, plain)
