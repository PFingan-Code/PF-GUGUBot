# -*- coding: utf-8 -*-
"""跨平台强制广播插件。

在 QQ 端发送 #mc <消息> 可突破 enable_send 限制，将消息仅广播到 MC；
在 MC 端发送 !!qq <消息> 可将消息仅广播到 QQ。
"""

import copy

from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo, ProcessedInfo


class CrossBroadcastSystem(BasicSystem):
    """跨平台强制广播系统。

    - QQ 端: #mc <消息> -> 仅发送到 MC（不受 QQ enable_send 限制）
    - MC 端: !!qq <消息> -> 仅发送到 QQ
    """

    def __init__(self, config=None) -> None:
        super().__init__(name="cross_broadcast", enable=True, config=config)

    def initialize(self) -> None:
        return

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        if broadcast_info.event_type != "message":
            return False
        if not broadcast_info.message or broadcast_info.message[0].get("type") != "text":
            return False
        if not self.enable:
            return False

        text = (broadcast_info.message[0].get("data") or {}).get("text", "").strip()
        source_name = broadcast_info.receiver_source or broadcast_info.source.origin

        # QQ 端: #mc <消息> -> 仅广播到 MC
        qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")
        mc_source = self.config.get_keys(["connector", "minecraft", "source_name"], "Minecraft")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        mc_cmd = self.config.get_keys(["system", "cross_broadcast", "mc_command"], "mc")

        if source_name == qq_source and text.startswith(command_prefix + mc_cmd):
            remaining = self._strip_command(broadcast_info.message, command_prefix + mc_cmd)
            return await self._broadcast_to_mc(broadcast_info, remaining)

        # MC 端: !!qq <消息> -> 仅广播到 QQ
        qq_cmd = self.config.get_keys(["system", "cross_broadcast", "qq_command"], "!!qq")
        if source_name == mc_source and text.startswith(qq_cmd):
            remaining = self._strip_command(broadcast_info.message, qq_cmd)
            return await self._broadcast_to_qq(broadcast_info, remaining)

        return False

    @staticmethod
    def _strip_command(message: list, command: str) -> list:
        """从消息段列表的第一个文本段中移除命令前缀，返回剩余的完整消息段列表。"""
        result = copy.deepcopy(message)
        first_text = (result[0].get("data") or {}).get("text", "")
        remaining_text = first_text[len(command):].strip()
        if remaining_text:
            result[0] = {**result[0], "data": {**result[0].get("data", {}), "text": remaining_text}}
        else:
            result.pop(0)
        if not result:
            result = [{"type": "text", "data": {"text": " "}}]
        return result

    async def _broadcast_to_mc(
            self, broadcast_info: BroadcastInfo, message: list
    ) -> bool:
        mc_source = self.config.get_keys(["connector", "minecraft", "source_name"], "Minecraft")
        connector = self.system_manager.connector_manager.get_connector(mc_source)
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
        )
        await self.system_manager.connector_manager.broadcast_processed_info(
            processed_info, include=[mc_source]
        )
        return True

    async def _broadcast_to_qq(
            self, broadcast_info: BroadcastInfo, message: list
    ) -> bool:
        qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")
        connector = self.system_manager.connector_manager.get_connector(qq_source)
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
        )
        await self.system_manager.connector_manager.broadcast_processed_info(
            processed_info, include=[qq_source]
        )
        return True
