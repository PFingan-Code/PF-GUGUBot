"""回声系统模块。

该模块提供了回声功能，可以将一个平台的消息转发到其他平台。
"""

from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class EchoSystem(BasicSystem):
    """回声系统，负责消息的跨平台转发。

    将从一个平台收到的消息转发到其他已连接的平台。

    Attributes
    ----------
    name : str
        系统名称
    enable : bool
        系统是否启用
    """

    def __init__(self, enable: bool = True, config: BotConfig = None) -> None:
        """初始化回声系统。"""
        super().__init__(name="echo", enable=enable, config=config)

    def initialize(self) -> None:
        return

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理传入的消息。

        将收到的消息转发到除了源平台以外的其他平台。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            接收到的广播信息

        Returns
        -------
        bool
            是否成功处理了消息
        """
        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        if not self.enable:
            return False

        # 检查是否是QQ私聊消息，如果是则不广播
        if broadcast_info.source.is_from("QQ") and broadcast_info.event_sub_type == "private":
            return False

        # 检查是否是QQ管理群的消息，如果是则不广播
        if broadcast_info.source.is_from("QQ") and broadcast_info.event_sub_type == "group":
            admin_group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "admin_group_ids"], []
            )
            if broadcast_info.source_id and str(broadcast_info.source_id) in [
                str(i) for i in admin_group_ids if i
            ]:
                # 管理群消息不广播，直接返回False
                return False

        if broadcast_info.event_type != "message":
            return False

        # 若消息来源 connector 的 enable_send=False，直接不转发（return），而不是仅从目标里排除
        source_name = broadcast_info.receiver_source or broadcast_info.source.origin
        source_connector = self.system_manager.connector_manager.get_connector(source_name)
        if source_connector is not None and not source_connector.enable_send:
            return False

        try:
            # 准备转发的消息
            processed_info = self.create_processed_info(broadcast_info)

            # 转发到其他平台（排除：来源 connector、enable_receive=False、enable_send=False 的目标）
            exclude_sources = [source_name]
            for c in self.system_manager.connector_manager.connectors:
                if not c.enable_receive:
                    exclude_sources.append(c.source)
            await self.system_manager.connector_manager.broadcast_processed_info(
                processed_info, exclude=exclude_sources
            )

            return True

        except Exception as e:
            self.logger.error(f"Echo系统处理消息失败: {str(e)}", exc_info=True)
            return False
