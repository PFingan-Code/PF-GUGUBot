"""QQ 官方机器人事件解析器（open-qq-bot 连接器）。

将官方 WebSocket 事件（GROUP_MESSAGE_CREATE / GROUP_AT_MESSAGE_CREATE /
C2C_MESSAGE_CREATE）转换为内部 :class:`BroadcastInfo`，接入既有系统管线
（关键词/违禁词/绑定/echo 等），使系统能力对两种 QQ 接入方式透明。
"""

import base64
import json
import re
from typing import Optional

from gugubot.parser.basic_parser import BasicParser
from gugubot.utils.types import BroadcastInfo, Source

# 表情消息：<faceType=6,faceId="0",ext="eyJ0ZXh0IjoiIn0=">
# ext 为 base64 的 JSON，text 字段是官方给出的描述（如「呲牙」）
FACE_TAG = re.compile(r'<faceType=(\d+),faceId="([^"]*)",ext="([^"]*)">')

# content 中的 @ 标记：<@member_openid> / <@all>（官方在 content 里插入，
# 被 @ 的对象同时会出现在 mentions 中）
AT_TAG = re.compile(r"<@([^<>]+)>")


class OpenQQBotParser(BasicParser):
    """官方事件 → BroadcastInfo 解析器。"""

    MESSAGE_EVENTS = {
        "GROUP_AT_MESSAGE_CREATE",
        "GROUP_MESSAGE_CREATE",
        "C2C_MESSAGE_CREATE",
    }

    # 通知事件 → 内部 event_sub_type（供 bound 系统做退群解绑等）
    NOTICE_EVENTS = {"GROUP_MEMBER_REMOVE": "group_decrease"}

    async def parse(self, raw: dict) -> Optional[BroadcastInfo]:
        """解析单个官方事件。

        Parameters
        ----------
        raw : dict
            connector 包装的事件：``{"t": 事件名, "d": 事件体, "event_id": ...}``。

        Notes
        -----
        原始事件体 ``d`` 写入 ``BroadcastInfo.raw``，供被动回复锚点使用。
        """
        t = raw.get("t")

        if t in self.NOTICE_EVENTS:
            return self._parse_notice(t, raw.get("d") or {})

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

    def _parse_notice(self, t: str, d: dict) -> Optional[BroadcastInfo]:
        """通知事件：GROUP_MEMBER_REMOVE → group_decrease（供 bound 系统退群解绑）。"""
        member_openid = str(d.get("member_openid", ""))
        if not member_openid:
            return None
        source_id = str(d.get("group_openid", ""))
        # 与消息事件共用同一份白名单：机器人所在但未监听的群，退群不解绑
        # （用户可能仍在监听群内，未监听群的退群不应触发绑定清理）
        if not self._is_valid_group(source_id):
            self.logger.debug("群 %s 不在 open-qq-bot 白名单，忽略 %s 事件", source_id, t)
            return None
        return BroadcastInfo(
            event_type="notice",
            event_sub_type=self.NOTICE_EVENTS[t],
            message=[{"type": "text", "data": {"text": ""}}],
            raw=d,
            server=self.server,
            logger=self.logger,
            _source=Source(self.connector.source),
            source_id=source_id,
            sender=member_openid,
            sender_id=member_openid,
        )

    def _build_segments(self, d: dict) -> list:
        """content + mentions + attachments → 内部统一消息段格式。

        - @ 成员（content 中的 ``<@member_openid>``）产出独立 ``at`` 段
          （``data.qq`` 为 OpenID），下游 McMessageBuilder 才能渲染游戏内
          高亮与点击@；只有同时出现在 ``mentions`` 里的标记才算真 @，
          用户手打的 ``<@xxx>`` 不在 mentions 中，原样保留为文本，不会被
          误识别成提及
        - @机器人自身（mentions 中 bot=true）：不产出 at 段（否则 bound
          系统会把它当成绑定目标），渲染出的前缀被剥离——全量模式下用户
          习惯 ``@机器人 #命令``，不剥离则首段不再以 ``#`` 开头，命令无法
          识别（对照 demo 的 at_me 处理）
        - @全体成员（``<@all>``，mentions 中 scope=all）转文本，不产 at 段
        - 表情标记（<faceType=...>）替换为描述文本：[呲牙] / [表情包]
        - 图片附件转为 OneBot 风格 image 段（data.file = 公网 URL，
          下游 McMessageBuilder 可直接消费）
        """
        content = (d.get("content") or "").strip()

        mentions = {}
        for user in d.get("mentions") or []:
            for key in ("member_openid", "id"):
                oid = str(user.get(key) or "")
                if oid:
                    mentions[oid] = user
        at_all = any(
            str(user.get("scope", "")) == "all" for user in d.get("mentions") or []
        )

        segments = []
        bot_rendered = []
        # split 后偶数下标是文本，奇数下标是 <@...> 里的目标 OpenID
        for index, part in enumerate(AT_TAG.split(content)):
            if index % 2 == 0:
                self._append_text(segments, FACE_TAG.sub(self._render_face, part))
                continue

            oid = part
            if oid == "all":
                if at_all:
                    self._append_text(segments, "@全体成员")
                else:
                    # 手打的 <@all>：mentions 里没有 scope=all，按普通文本处理
                    self._append_text(segments, f"<@{oid}>")
                continue

            user = mentions.get(oid)
            if user is None:
                # 手打的 <@xxx>：不是官方插入的提及标记，原样保留
                self._append_text(segments, f"<@{oid}>")
                continue

            display = str(
                user.get("member_nickname") or user.get("username") or oid
            )
            if user.get("bot") or user.get("is_you"):
                # 机器人自身/其它机器人：只留可读文本，绝不产出 at 段
                rendered = f"@{display}"
                bot_rendered.append(rendered)
                self._append_text(segments, rendered)
                continue

            # name 仅作未绑定玩家时的游戏内显示兜底（mc_builder 使用），
            # 真实绑定关系仍以 qq=OpenID 为准
            segments.append(
                {"type": "at", "data": {"qq": oid, "name": display}}
            )

        self._strip_bot_prefix(segments, bot_rendered)

        for att in d.get("attachments") or []:
            if str(att.get("content_type", "")).startswith("image") and att.get("url"):
                segments.append({"type": "image",
                                 "data": {"file": att["url"], "url": att["url"]}})
        return segments

    @staticmethod
    def _append_text(segments: list, text: str) -> None:
        """追加文本段：合并相邻文本，空串直接丢弃。"""
        if not text:
            return
        if segments and segments[-1].get("type") == "text":
            segments[-1]["data"]["text"] += text
        else:
            segments.append({"type": "text", "data": {"text": text}})

    @staticmethod
    def _strip_bot_prefix(segments: list, bot_rendered: list) -> None:
        """剥离 @机器人 渲染前缀（仅剥一次，剥空则保留原文）。"""
        if not segments or not bot_rendered or segments[0].get("type") != "text":
            return
        text = segments[0]["data"]["text"]
        for prefix in bot_rendered:
            if not text.startswith(prefix):
                continue
            rest = text[len(prefix):].lstrip()
            if rest:
                segments[0]["data"]["text"] = rest
            elif len(segments) > 1:
                # 纯 @机器人 前缀 + 其它内容：丢掉空文本段
                segments.pop(0)
            # 否则消息只有 @机器人：保留原文，避免解析成空消息
            break

    @staticmethod
    def _render_face(match: re.Match) -> str:
        """``<faceType=..,faceId="..",ext="..">`` → 可读文本。

        ext 是 base64 的 JSON，``text`` 字段为官方给出的表情描述（如「呲牙」），
        渲染成 ``[呲牙]``；描述本身自带方括号（如 ``[搓手]``）则原样输出，避免双重括号。
        自定义大表情（faceType=6）没有描述，真实画面在同事件的图片附件里，
        这里只留一个 ``[表情包]`` 占位，附件会另生成 image 段。
        """
        face_type, ext = match.group(1), match.group(3)
        desc = ""
        if ext:
            try:
                padded = ext + "=" * (-len(ext) % 4)
                payload = json.loads(base64.b64decode(padded).decode("utf-8"))
                desc = str(payload.get("text") or "").strip()
            except Exception:
                desc = ""
        if desc:
            # 官方部分表情的描述自带方括号（如 [搓手]），避免出现双重括号
            if not (desc.startswith("[") and desc.endswith("]")):
                desc = f"[{desc}]"
            return desc
        return "[表情]" if face_type == "1" else "[表情包]"

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
