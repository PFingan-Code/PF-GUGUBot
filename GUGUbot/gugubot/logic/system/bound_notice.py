# -*- coding: utf-8 -*-

from typing import Optional

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class BoundNoticeSystem(BasicSystem):
    """绑定提醒系统，用于提醒未绑定的玩家进行账号绑定。

    当玩家发送消息时，如果该玩家未在玩家管理器中绑定账号，
    则提醒其进行绑定。不会拦截消息，让其他系统继续处理。
    """

    def __init__(self, config: Optional[BotConfig] = None) -> None:
        """初始化绑定提醒系统。"""
        super().__init__("bound_notice", enable=False, config=config)
        self.bound_system = None

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        self.logger.debug("绑定提醒系统已初始化")

    def set_bound_system(self, bound_system) -> None:
        """设置绑定系统引用，用于访问玩家管理器"""
        self.bound_system = bound_system

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的消息。

        Parameters
        ----------
        broadcast_info: BroadcastInfo
            广播信息，包含消息内容
        """
        if broadcast_info.event_type != "message":
            return False

        message = broadcast_info.message

        if not message:
            return False

        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        # 如果系统未启用或没有绑定系统引用，不处理
        if not self.enable or not self.bound_system:
            return False

        return await self._check_and_notify(broadcast_info)

    async def _check_and_notify(self, broadcast_info: BroadcastInfo) -> bool:
        """检查玩家是否已绑定，如果未绑定则发送提醒"""
        # 只在有发送者ID的情况下检查
        if not broadcast_info.sender_id:
            return False

        # 排除管理员
        if broadcast_info.is_admin:
            return False

        # 排除管理群消息
        if broadcast_info.source_id:
            admin_group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "admin_group_ids"], []
            )
            if str(broadcast_info.source_id) in [
                str(gid) for gid in admin_group_ids if gid
            ]:
                return False

        # 检查玩家是否在玩家管理器中
        player = self.bound_system.player_manager.get_player(
            broadcast_info.sender_id, platform=broadcast_info.source.origin
        )

        # 如果玩家未绑定，发送提醒消息
        if not player:
            command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
            # 获取绑定系统的名称
            bound_name = self.bound_system.get_tr("name")

            notice_msg = self.get_tr(
                "notice_message", command_prefix=command_prefix, bound_name=bound_name
            )
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.at(broadcast_info.sender_id),
                    MessageBuilder.text(notice_msg),
                ],
            )

        # 不拦截消息，让其他系统继续处理
        return False
