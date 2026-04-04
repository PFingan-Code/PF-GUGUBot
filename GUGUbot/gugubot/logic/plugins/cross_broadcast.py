# -*- coding: utf-8 -*-
"""跨平台强制广播插件。

在 QQ 端发送 #mc <消息> 可突破 enable_send 限制，将消息仅广播到 MC；
在 MC 端发送 !!qq <消息> 可将消息仅广播到 QQ。
支持回复图片消息时使用 #mc 将被回复的图片转发到 MC。
"""

import copy

from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo, ProcessedInfo

_EMPTY_TEXT = [{"type": "text", "data": {"text": " "}}]
_IMAGE_TYPES = frozenset(("image", "mface"))


def _seg_text(seg: dict) -> str:
    """提取消息段中的文本内容。"""
    return (seg.get("data") or {}).get("text", "")


class CrossBroadcastSystem(BasicSystem):
    """跨平台强制广播系统。

    - QQ 端: #mc <消息> -> 仅发送到 MC（不受 QQ enable_send 限制）
    - QQ 端: 回复图片消息 + #mc -> 将被回复的图片转发到 MC
    - MC 端: !!qq <消息> -> 仅发送到 QQ
    """

    def __init__(self, config=None) -> None:
        super().__init__(name="cross_broadcast", enable=True, config=config)

    def initialize(self) -> None:
        pass

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        if (broadcast_info.event_type != "message"
                or not broadcast_info.message
                or not self.enable):
            return False

        text_idx, text = self._find_first_text(broadcast_info.message)
        if text_idx < 0:
            return False

        source_name = broadcast_info.receiver_source or broadcast_info.source.origin

        qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")
        mc_source = self.config.get_keys(["connector", "minecraft", "source_name"], "Minecraft")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        mc_cmd = self.config.get_keys(["system", "cross_broadcast", "mc_command"], "mc")

        # QQ 端: #mc <消息> -> 仅广播到 MC（支持回复图片消息）
        if source_name == qq_source and text.startswith(command_prefix + mc_cmd):
            remaining = self._strip_reply_command(
                broadcast_info.message, text_idx, command_prefix + mc_cmd
            )
            if reply_images := await self._get_reply_images(broadcast_info.message):
                remaining = remaining + reply_images
            return await self._broadcast_to(broadcast_info, remaining, mc_source)

        # MC 端: !!qq <消息> -> 仅广播到 QQ
        qq_cmd = self.config.get_keys(["system", "cross_broadcast", "qq_command"], "!!qq")
        if source_name == mc_source and text.startswith(qq_cmd):
            remaining = self._strip_command(broadcast_info.message, qq_cmd)
            target = self._build_qq_forward_target()
            return await self._broadcast_to(broadcast_info, remaining, qq_source, target=target)

        return False

    @staticmethod
    def _find_first_text(message: list) -> tuple[int, str]:
        """找到第一个 text 段，跳过 reply/at 等前置段。返回 (index, stripped_text) 或 (-1, "")。"""
        return next(
            ((i, _seg_text(seg).strip())
             for i, seg in enumerate(message)
             if seg.get("type") == "text"),
            (-1, ""),
        )

    @staticmethod
    def _strip_reply_command(message: list, text_idx: int, command: str) -> list:
        """从 text_idx 处的文本段移除命令前缀，同时去掉回复自动插入的 reply/at 段。"""
        result = []
        for i, seg in enumerate(copy.deepcopy(message)):
            seg_type = seg.get("type")
            if seg_type == "reply" or (seg_type == "at" and i < text_idx):
                continue
            if i == text_idx:
                if remaining := _seg_text(seg)[len(command):].strip():
                    result.append({"type": "text", "data": {**seg.get("data", {}), "text": remaining}})
                continue
            result.append(seg)
        return result or list(_EMPTY_TEXT)

    async def _get_reply_images(self, message: list) -> list:
        """若消息中包含 reply 段，通过 get_msg 拉取被回复消息并提取其中的图片段。"""
        reply_seg = next((seg for seg in message if seg.get("type") == "reply"), None)
        if not reply_seg:
            return []

        try:
            reply_msg_id = int(reply_seg.get("data", {}).get("id", 0))
        except (ValueError, TypeError):
            return []
        if not reply_msg_id:
            return []

        qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")
        qq_connector = self.system_manager.connector_manager.get_connector(qq_source)
        if not qq_connector or not hasattr(qq_connector, "bot"):
            return []

        try:
            replied_msg = await qq_connector.bot.get_msg(message_id=reply_msg_id)
            if not replied_msg or replied_msg.get("status") != "ok":
                return []

            msg_segments = replied_msg.get("data", {}).get("message", [])
            if isinstance(msg_segments, str):
                from gugubot.builder import CQHandler
                msg_segments = CQHandler.parse(msg_segments)

            return [
                seg for seg in msg_segments
                if isinstance(seg, dict) and seg.get("type") in _IMAGE_TYPES
            ]
        except Exception:
            return []

    @staticmethod
    def _strip_command(message: list, command: str) -> list:
        """从消息段列表的第一个文本段中移除命令前缀，返回剩余的完整消息段列表。"""
        result = copy.deepcopy(message)
        if remaining_text := _seg_text(result[0])[len(command):].strip():
            result[0] = {**result[0], "data": {**result[0].get("data", {}), "text": remaining_text}}
        else:
            result.pop(0)
        return result or list(_EMPTY_TEXT)

    def _build_qq_forward_target(self) -> dict | None:
        """构建 !!qq 自定义转发目标群字典，留空则由 QQ connector 自行决定。"""
        group_ids = self.config.get_keys(
            ["system", "cross_broadcast", "qq_forward_group_ids"], []
        )
        if group_ids and any(group_ids):
            return {str(gid): "group" for gid in group_ids if gid}
        return None

    async def _broadcast_to(
            self, broadcast_info: BroadcastInfo, message: list,
            dest: str, *, target: dict | None = None,
    ) -> bool:
        """将消息广播到指定目标 connector。"""
        connector = self.system_manager.connector_manager.get_connector(dest)
        if not connector or not connector.enable:
            return False
        processed_info = ProcessedInfo(
            processed_message=message,
            _source=broadcast_info.source,
            source_id=broadcast_info.source_id,
            sender=broadcast_info.sender,
            raw=broadcast_info.raw,
            server=broadcast_info.server,
            logger=broadcast_info.logger,
            event_sub_type=broadcast_info.event_sub_type,
            sender_id=broadcast_info.sender_id,
            target=target,
        )
        await self.system_manager.connector_manager.broadcast_processed_info(
            processed_info, include=[dest]
        )
        return True
