"""Test connector for debugging message broadcasts."""

import logging
from typing import Any, Optional

from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.utils.types import ProcessedInfo


class TestConnector(BasicConnector):
    """Test connector for debugging message broadcasts.

    Attributes
    ----------
    server : Any
        MCDR server instance.
    logger : logging.Logger
        Logger instance.
    """

    def __init__(
        self,
        server: Any,
        config: Optional[BotConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the test connector.

        Parameters
        ----------
        server : Any
            MCDR server instance.
        logger : logging.Logger, optional
            Logger instance.  Falls back to ``server.logger`` when omitted.
        """
        super().__init__(
            source="test", server=server, logger=logger or server.logger, config=config
        )
        # Reuse show_message_in_console as the master toggle for TestConnector
        self.enable = config.get_keys(["GUGUBot", "show_message_in_console"], True)
        self.enable_send = self.enable
        self.enable_receive = self.enable

    async def connect(self) -> None:
        """Establish the connection (no-op since MCDR manages the lifecycle)."""
        self.logger.info("TEST连接器就绪")

    async def disconnect(self) -> None:
        """Tear down the connection (no-op since MCDR manages the lifecycle)."""
        self.logger.info("TEST连接器已断开")

    async def send_message(self, processed_info: ProcessedInfo) -> None:
        """Send a message by logging it to the console.

        Parameters
        ----------
        processed_info : ProcessedInfo
            The processed message to send.
        """
        if not self.enable:
            return

        self.logger.info(f"[GUGUBot]发送消息: {processed_info}")

    async def on_message(self, raw: Any) -> None:
        """Handle an incoming raw message by logging it.

        Parameters
        ----------
        raw : Any
            Raw message data, typically a dict with player and message info.
        """
        if not self.enable:
            return

        self.logger.debug(f"[GUGUBot]接收消息: {raw}")
