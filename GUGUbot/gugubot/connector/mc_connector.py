"""Connector for a Minecraft server via MCDR."""

import logging
import traceback
from typing import Any, Optional

from gugubot.builder import McMessageBuilder
from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.parser.mc_parser import MCParser
from gugubot.utils.types import ProcessedInfo


class MCConnector(BasicConnector):
    """Connector for a Minecraft server via MCDR.

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
        """Initialize the Minecraft connector.

        Parameters
        ----------
        server : Any
            MCDR server instance.
        logger : logging.Logger, optional
            Logger instance.  Falls back to ``server.logger`` when omitted.
        """
        source_name = config.get_keys(
            ["connector", "minecraft", "source_name"], "Minecraft"
        )
        super().__init__(
            source=source_name,
            parser=MCParser,
            builder=McMessageBuilder,
            server=server,
            logger=logger or server.logger,
            config=config,
        )

        connector_basic_name = self.server.tr("gugubot.connector.name")
        self.log_prefix = f"[{connector_basic_name}{self.source}]"

    async def connect(self) -> None:
        """Establish the connection (no-op since MCDR manages the lifecycle)."""
        self.logger.info(f"{self.log_prefix} 就绪 ~")

    async def disconnect(self) -> None:
        """Tear down the connection (no-op since MCDR manages the lifecycle)."""
        self.logger.info(f"{self.log_prefix} 已断开 ~")

    async def send_message(self, processed_info: ProcessedInfo) -> None:
        """Build and broadcast a message to the Minecraft server chat.

        Parameters
        ----------
        processed_info : ProcessedInfo
            The processed message to send.
        """
        if not self.enable:
            return

        if not self.server.is_server_running():
            return

        self.builder: McMessageBuilder

        message = processed_info.processed_message
        source = processed_info.source.origin
        source_id = processed_info.source_id
        sender = processed_info.sender
        sender_id = processed_info.sender_id
        receiver = getattr(processed_info, "receiver", None)

        use_chat_image = self.config.get_keys(
            ["connector", "minecraft", "chat_image"], False
        )
        use_image_previewer = self.config.get_keys(
            ["connector", "minecraft", "image_previewer"], False
        )

        try:
            game_version = self.server.get_server_information().version or ""
            game_version = game_version.lower() if game_version else ""
            is_low_version = self.builder.is_low_game_version(game_version)

            bound_system = self.connector_manager.system_manager.get_system("bound")
            player_manager = getattr(bound_system, "player_manager", None)

            # Retrieve the bot's QQ ID so @-mentions targeting the bot can be filtered
            bot_id = None
            qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")
            if qq_connector := self.connector_manager.get_connector(qq_source):
                bot_id = getattr(getattr(qq_connector, "bot", None), "self_id", None)

            rtext_content = self.builder.array_to_rtext(
                message,
                low_game_version=is_low_version,
                chat_image=use_chat_image,
                image_previewer=use_image_previewer,
                player_manager=player_manager,
                bot_id=bot_id,
            )

            if player_manager:
                sender_player = player_manager.get_player(str(sender_id))
                if sender_player:
                    # Prefer the first Java name, then Bedrock name, then display name
                    sender = (
                        sender_player.java_name[0]
                        if sender_player.java_name
                        else (
                            sender_player.bedrock_name[0]
                            if sender_player.bedrock_name
                            else sender_player.name
                        )
                    ) or sender

                if receiver:
                    receiver_player = player_manager.get_player(str(receiver))
                    if receiver_player:
                        receiver = (
                            receiver_player.java_name[0]
                            if receiver_player.java_name
                            else (
                                receiver_player.bedrock_name[0]
                                if receiver_player.bedrock_name
                                else receiver_player.name
                            )
                        ) or receiver

            custom_group_name = self.config.get_keys(
                ["connector", "QQ", "permissions", "custom_group_name"], {}
            )
            source = custom_group_name.get(source_id, source)

            main_content = self.builder.build(
                rtext_content,
                group_name=source,
                group_id=source_id,
                sender=sender,
                sender_id=sender_id,
                receiver=receiver,
            )

            self.server.say(main_content)

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"{self.log_prefix} 发送消息失败: {error_msg}")
            raise

    async def on_message(self, raw: Any) -> None:
        """Handle an incoming Minecraft chat message.

        Parameters
        ----------
        raw : Info
            The MCDR ``Info`` object for the received message.
        """
        try:
            if not self.enable:
                return

            if not raw.is_player:
                return

            await self.parser(self).process_message(raw, server=self.server)

        except Exception as e:
            self.logger.error(f"{self.log_prefix} 处理消息失败: {e}")
            raise

    async def _is_admin(self, sender_id) -> bool:
        """Return whether *sender_id* is an admin."""
        bound_system = self.connector_manager.system_manager.get_system("bound")

        if not bound_system:
            return False

        player_manager = bound_system.player_manager
        return await player_manager.is_admin(sender_id)
