"""QQ 官方机器人事件解析器（open-qq-bot 连接器）。

将官方 WebSocket 事件（GROUP_MESSAGE_CREATE / GROUP_AT_MESSAGE_CREATE /
C2C_MESSAGE_CREATE）转换为内部 :class:`BroadcastInfo`，接入既有系统管线
（关键词/违禁词/绑定/echo 等），使系统能力对两种 QQ 接入方式透明。
"""

import re
from typing import Optional

from gugubot.parser.basic_parser import BasicParser
from gugubot.utils.types import BroadcastInfo, Source

# @成员 的原始标记（全量模式 GROUP_MESSAGE_CREATE 保留 <@member_openid>）
AT_MARKER = re.compile(r"<@([0-9A-Fa-f]{32})>")


class OpenQQBotParser(BasicParser):
    """官方事件 → BroadcastInfo 解析器。"""

    MESSAGE_EVENTS = {
        "GROUP_AT_MESSAGE_CREATE",
        "GROUP_MESSAGE_CREATE",
        "C2C_MESSAGE_CREATE",
    }

    async def parse(self, raw: dict) -> Optional[BroadcastInfo]:
        """解析单个官方事件。

        Parameters
        ----------
        raw : dict
            connector 包装的事件：``{"t": 事件名, "d": 事件体, "event_id": ...}``。
        """
        t = raw.get("t")
        if t not in self.MESSAGE_EVENTS:
            return None
        d = raw.get("d") or {}

        author = d.get("author") or {}
        if author.get("bot"):
            return None  # 跳过机器人自己的消息，防止回环

        sender_id = (author.get("member_openid") or author.get("user_openid")
                     or author.get("id") or "")
        if not sender_id:
            return None
        sender_name = author.get("username") or f"{sender_id[:8]}…"

        message_segments = self._build_segments(d)
        if not message_segments:
            return None  # 空消息（无文本无附件）

        if t == "C2C_MESSAGE_CREATE":
            event_sub_type = "private"
            source_id = sender_id
        else:
            event_sub_type = "group"
            source_id = d.get("group_openid", "")
            if not self._is_valid_group(source_id):
                self.logger.debug("群 %s 不在 open-qq-bot 白名单，忽略", source_id)
                return None

        return BroadcastInfo(
            event_type="message",
            event_sub_type=event_sub_type,
            message=message_segments,
            raw=d,
            server=self.server,
            logger=self.logger,
            _source=Source(self.connector.source),
            source_id=str(source_id),
            sender=sender_name,
            sender_id=sender_id,
            receiver=None,
            is_admin=self._is_admin(sender_id, author),
        )

    # ---- 内部 ----

    def _build_segments(self, d: dict) -> list:
        """content + mentions + attachments → 内部统一消息段格式。

        - @ 标记（<@member_openid>）替换为 @昵称 文本
        - 图片附件转为 OneBot 风格 image 段（data.file = 公网 URL，
          下游 McMessageBuilder 可直接消费）
        """
        text = (d.get("content") or "").strip()
        for user in d.get("mentions") or []:
            oid = user.get("member_openid") or user.get("id") or ""
            if oid:
                text = text.replace(f"<@{oid}>", f"@{user.get('username', oid)}")
        text = text.replace("<@all>", "@全体成员")

        segments = []
        if text:
            segments.append({"type": "text", "data": {"text": text}})
        for att in d.get("attachments") or []:
            if str(att.get("content_type", "")).startswith("image") and att.get("url"):
                segments.append({"type": "image",
                                 "data": {"file": att["url"], "url": att["url"]}})
        return segments

    def _is_valid_group(self, group_openid: str) -> bool:
        """群白名单：permissions.group_ids 非空时仅响应列表内的群。"""
        section = getattr(self.connector, "SECTION", "open-qq-bot")
        group_ids = self.connector.config.get_keys(
            ["connector", section, "permissions", "group_ids"], []
        ) or []
        group_ids = [g for g in group_ids if g]
        return not group_ids or group_openid in group_ids

    def _is_admin(self, sender_id: str, author: dict) -> bool:
        """管理员判定：permissions.admin_ids（OpenID 列表）或群角色 admin/owner。"""
        section = getattr(self.connector, "SECTION", "open-qq-bot")
        admin_ids = self.connector.config.get_keys(
            ["connector", section, "permissions", "admin_ids"], []
        ) or []
        if sender_id in admin_ids:
            return True
        return author.get("member_role") in ("admin", "owner")
