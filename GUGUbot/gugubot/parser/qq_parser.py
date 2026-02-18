import html
import json
import re
import traceback
from typing import Dict, List, Optional

from gugubot.builder.qq_builder import ArrayHandler, CQHandler
from gugubot.parser.basic_parser import BasicParser
from gugubot.utils.types import BroadcastInfo, Source


class QQParser(BasicParser):
    PROCESS_TYPE = ["message", "notice", "request"]

    """QQ消息解析器。

    处理来自QQ平台的消息，包括群聊消息、私聊消息等。
    """

    def _get_reply_message_id(self, message: List[dict]) -> Optional[int]:
        """从消息中获取回复消息的ID"""
        for item in message:
            if item.get("type") == "reply":
                if msg_id := item.get("data", {}).get("id"):
                    try:
                        return int(msg_id)
                    except (ValueError, TypeError):
                        pass
        return None

    def _extract_sender_from_template(self, text: str, template: str) -> Optional[str]:
        """从模板中提取发送者名字，模板如 "[{display_name}] {sender}: "

        支持模板前面有额外前缀、后面有正文消息的情况
        """
        try:
            # display_name 不跨越方括号，sender 不包含常见分隔符
            pattern = (
                re.escape(template)
                .replace(r"\{display_name\}", r"[^\[\]]+")
                .replace(r"\{sender\}", r"([^\[\]:\n]+)")
            )
            if match := re.search(pattern, text):
                return match.group(1).strip()
        except re.error:
            pass
        return None

    def _parse_sender_from_template(self, text: str, templates: List) -> Optional[str]:
        """使用聊天模板从消息文本中解析出发送者名字"""
        # 没有配置模板时，尝试默认格式 [{source}] {sender}:
        if not templates:
            # sender 不包含 [ ] : 这些分隔符
            if match := re.search(r"\[[^\[\]]+\]\s*([^\[\]:\n]+):\s", text):
                return match.group(1).strip()
            return None

        # 展开模板列表（支持新旧两种格式）
        template_strs = (
            key for item in templates
            for key in (item.keys() if isinstance(item, dict) else [item])
        )
        return next(
            (sender for t in template_strs if (sender := self._extract_sender_from_template(text, t))),
            None
        )

    def _get_replied_text(self, data: dict) -> str:
        """从API返回的消息数据中提取文本内容"""
        if raw := data.get("raw_message", ""):
            # 解码 HTML 实体 & 移除 CQ 码
            text = html.unescape(raw)
            return re.sub(r"\[CQ:[^\]]+\]", "", text)
        return "".join(
            item.get("data", {}).get("text", "")
            for item in data.get("message", [])
            if item.get("type") == "text"
        )

    async def _get_receiver_from_reply(self, message: List[dict]) -> Optional[str]:
        """从回复消息中获取原始发送者作为receiver（仅当回复机器人消息时）"""
        if not (reply_msg_id := self._get_reply_message_id(message)):
            return None

        try:
            replied_msg = await self.connector.bot.get_msg(message_id=reply_msg_id)
            if not replied_msg or replied_msg.get("status") != "ok":
                return None

            data = replied_msg.get("data", {})

            # 仅处理回复机器人自己的消息
            if data.get("sender", {}).get("user_id") != self.connector.bot.self_id:
                return None

            if not (replied_text := self._get_replied_text(data)):
                return None

            templates = self.connector.config.get_keys(["connector", "QQ", "chat_templates"], [])
            if sender := self._parse_sender_from_template(replied_text, templates):
                self.logger.debug(f"从回复消息中解析出receiver: {sender}")
                return sender

        except Exception as e:
            self.logger.debug(f"获取回复消息receiver失败: {e}")

        return None

    async def parse(self, raw_message: str) -> Optional[BroadcastInfo]:
        """解析QQ消息。

        Parameters
        ----------
        raw_message : str
            QQ WebSocket接收到的JSON格式消息

        Returns
        -------
        Optional[BroadcastInfo]
            解析后的广播信息对象，如果是回调消息则返回None
        """
        try:
            message_data: Dict = json.loads(raw_message)

            echo = message_data.get("echo")  # 处理API调用的返回结果
            if echo:
                self.connector.bot.function_return[echo] = message_data
                return None

            event_type = message_data.get("post_type", "")
            if event_type not in self.PROCESS_TYPE:
                return None

            if not self._is_valid_source(message_data, event_type):
                return None

            if event_type == "message":
                # 处理事件消息
                self_id = message_data.get("self_id")
                if self_id is not None:
                    self.connector.bot.self_id = self_id

                message = message_data.get("raw_message", "")
                parsed_message = CQHandler.parse(message) if isinstance(message, str) else ArrayHandler.parse(message)

                source_id = message_data.get("user_id") if message_data.get(
                    "message_type") == 'private' else message_data.get("group_id")
                source_type = "private" if message_data.get("message_type") == 'private' else "group"

                sender = message_data.get("sender", {})
                sender_name = sender.get("card") or sender.get("nickname")
                sender_id = str(sender.get("user_id"))

                # 检查是否应该排除此用户的消息
                if await self._should_exclude_user(sender_id, source_id, source_type):
                    self.logger.debug(f"已在connector层拦截排除用户 {sender_id} 的消息")
                    return None

                # 尝试从回复消息中获取receiver（如果回复的是机器人转发的消息）
                receiver = await self._get_receiver_from_reply(parsed_message)

                # 创建并处理QQ消息对象
                broadcast_info = BroadcastInfo(
                    event_type=event_type,
                    event_sub_type=source_type,
                    message=parsed_message,
                    raw=message_data,
                    server=self.server,
                    logger=self.logger,
                    _source=Source(self.connector.source),  # 使用 Source 类追踪来源链
                    source_id=str(source_id),
                    sender=sender_name,
                    sender_id=sender_id,
                    receiver=receiver,  # 从回复消息中解析的接收者
                    is_admin=self._is_admin(source_id) or self._is_admin(sender_id)
                )

            else:
                sub_type = message_data.get("request_type") if event_type == "request" else message_data.get(
                    "notice_type")

                broadcast_info = BroadcastInfo(
                    event_type=event_type,
                    event_sub_type=sub_type,
                    message=message_data,
                    raw=message_data,
                    server=self.server,
                    logger=self.logger,
                    _source=Source(self.connector.source),  # 使用 Source 类追踪来源链
                    source_id=message_data.get("user_id"),
                )

            return broadcast_info

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"QQ消息解析失败: {error_msg}")
            raise

    def _is_admin(self, sender_id) -> bool:
        """检查是否是管理员"""
        config = self.system_manager.config
        admin_ids = config.get_keys(["connector", "QQ", "permissions", "admin_ids"], [])
        admin_groups = config.get_keys(["connector", "QQ", "permissions", "admin_group_ids"], [])

        if str(sender_id) in [str(i) for i in admin_ids + admin_groups]:
            return True
        return False

    def _friend_is_admin(self, message_data, event_type: str) -> bool:
        """检查是否是好友管理员"""
        if event_type != "message":
            return False

        config = self.connector.config
        friend_is_admin = config.get_keys(["connector", "QQ", "permissions", "friend_is_admin"], False)

        is_private_chat = message_data.get("message_type") == 'private'

        return friend_is_admin and is_private_chat

    def _is_valid_source(self, message_data, event_type: str) -> bool:
        friend_is_admin = self._friend_is_admin(message_data, event_type)

        if event_type == "message":
            source_id = message_data.get("user_id") if message_data.get(
                "message_type") == 'private' else message_data.get("group_id")
        else:
            # 对于 notice 和 request 类型，直接使用 user_id 或 group_id
            source_id = message_data.get("group_id") or message_data.get("user_id")

        admin_ids = self.connector.config.get_keys(["connector", "QQ", "permissions", "admin_ids"], [])
        admin_groups = self.connector.config.get_keys(["connector", "QQ", "permissions", "admin_group_ids"], [])
        group_ids = self.connector.config.get_keys(["connector", "QQ", "permissions", "group_ids"], [])

        valid_source = [str(i) for i in admin_ids + admin_groups + group_ids]

        return friend_is_admin or str(source_id) in valid_source

    async def _should_exclude_user(self, user_id: str, source_id: str, source_type: str) -> bool:
        """检查用户是否应该被排除（完全忽略其消息）

        Parameters
        ----------
        user_id : str
            用户QQ号
        source_id : str
            消息来源ID（群号或用户号）
        source_type : str
            消息来源类型（group 或 private）

        Returns
        -------
        bool
            True 表示应该排除此用户，False 表示不应该排除
        """
        # 1. 排除配置中指定的额外用户列表
        exclude_ids = self.connector.config.get_keys(["system", "bound_notice", "exclude_ids"], [])
        if user_id in [str(exclude_id) for exclude_id in exclude_ids if exclude_id]:
            self.logger.debug(f"用户 {user_id} 在排除列表中，忽略消息")
            return True

        return False
