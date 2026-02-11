import logging
from typing import Any, Optional

from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector, BroadcastInfo


class TestConnector(BasicConnector):
    """TEST服务器连接器。

    用于与TEST服务器进行消息交互。

    Attributes
    ----------
    server : Any
        MCDR服务器实例
    logger : logging.Logger
        日志记录器
    """

    def __init__(
            self,
            server: Any,
            config: BotConfig = None,
            logger: Optional[logging.Logger] = None,
    ) -> None:
        """初始化TEST连接器。

        Parameters
        ----------
        server : Any
            MCDR服务器实例
        logger : Optional[logging.Logger]
            日志记录器实例，如果未提供则创建新的
        """
        super().__init__(source="test", config=config)
        self.server = server
        self.logger = logger or server.logger
        self.enable = config.get_keys(["GUGUBot", "show_message_in_console"], True)
        # TestConnector 使用 show_message_in_console 配置作为开关
        self.enable_send = self.enable
        self.enable_receive = self.enable

    async def connect(self) -> None:
        """连接到TEST服务器。

        由于MCDR已经处理了服务器连接，此方法不需要执行任何操作。
        """
        self.logger.info("TEST连接器就绪")

    async def disconnect(self) -> None:
        """断开与TEST服务器的连接。

        由于MCDR负责服务器连接的生命周期，此方法不需要执行任何操作。
        """
        self.logger.info("TEST连接器已断开")

    async def send_message(self, broadcast_info: BroadcastInfo) -> None:
        """向TEST服务器发送消息。

        Parameters
        ----------
        message : Any
            要发送的消息。如果是字符串，直接发送；
            如果是dict，应包含"content"键。

        Raises
        ------
        ValueError
            当消息格式无效时
        """
        if not self.enable:
            return

        self.logger.info(f"[GUGUBot]发送消息: {broadcast_info}")
        # self.logger.info(f"[GUGUBot]发送消息: {getattr(broadcast_info, 'processed_message', '')}")

    async def on_message(self, raw: Any) -> None:
        """处理从TEST服务器接收的消息。

        Parameters
        ----------
        raw : Any
            原始消息数据，应该是一个包含玩家和消息信息的字典

        Example
        -------
        消息格式示例：
        {
            'player': 'Steve',
            'content': 'Hello, world!',
            'type': 'chat'  # 或其他消息类型
        }
        """
        if not self.enable:
            return

        self.logger.debug(f"[GUGUBot]接收消息: {raw}")
