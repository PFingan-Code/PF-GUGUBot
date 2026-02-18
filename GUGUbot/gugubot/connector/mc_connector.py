import logging
import traceback
from typing import Any, Optional

from mcdreforged.api.types import Info, PluginServerInterface

from gugubot.builder.mc_builder import McMessageBuilder
from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.parser.mc_parser import MCParser
from gugubot.utils.types import ProcessedInfo


class MCConnector(BasicConnector):
    """Minecraft服务器连接器。

    用于与Minecraft服务器进行消息交互。

    Attributes
    ----------
    server : Any
        MCDR服务器实例
    logger : logging.Logger
        日志记录器
    """

    def __init__(self, server: Any, config: BotConfig = None, logger: Optional[logging.Logger] = None) -> None:
        """初始化Minecraft连接器。

        Parameters
        ----------
        server : Any
            MCDR服务器实例
        logger : Optional[logging.Logger]
            日志记录器实例，如果未提供则创建新的
        """
        source_name = config.get_keys(["connector", "minecraft", "source_name"], "Minecraft")
        super().__init__(source=source_name, parser=MCParser, builder=McMessageBuilder, config=config)
        self.server = server
        self.logger = logger or server.logger

        # 存储日志前缀
        connector_basic_name = self.server.tr("gugubot.connector.name")
        self.log_prefix = f"[{connector_basic_name}{self.source}]"

    async def connect(self) -> None:
        """连接到Minecraft服务器。

        由于MCDR已经处理了服务器连接，此方法不需要执行任何操作。
        """
        self.logger.info(f"{self.log_prefix} 就绪 ~")

    async def disconnect(self) -> None:
        """断开与Minecraft服务器的连接。

        由于MCDR负责服务器连接的生命周期，此方法不需要执行任何操作。
        """
        self.logger.info(f"{self.log_prefix} 已断开 ~")

    async def send_message(self, processed_info: ProcessedInfo, **kwargs) -> None:
        """向Minecraft服务器发送消息。

        Parameters
        ----------
        processed_info : Any
            要发送的消息。如果是字符串，直接发送；
            如果是dict，应包含"content"键。

        Raises
        ------
        ValueError
            当消息格式无效时
        """
        if not self.enable:
            return

        if not self.server.is_server_running():
            return

        self.builder: McMessageBuilder

        message = processed_info.processed_message
        source = processed_info.source.origin  # 获取原始来源作为显示名称
        source_id = processed_info.source_id
        sender = processed_info.sender
        sender_id = processed_info.sender_id
        receiver = getattr(processed_info, 'receiver', None)

        use_chat_image = self.config.get_keys(["connector", "minecraft", "chat_image"], False)
        use_image_previewer = self.config.get_keys(["connector", "minecraft", "image_previewer"], False)

        try:
            game_version = self.server.get_server_information().version or ""
            game_version = game_version.lower() if game_version else ""
            is_low_version = self.builder.is_low_game_version(game_version)

            player_manager = getattr(self.connector_manager.system_manager.get_system("bound"), "player_manager", None)
            is_admin = await player_manager.is_admin(sender_id) if player_manager else False

            # 获取机器人QQ号，用于过滤对机器人的@
            bot_id = None
            qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")
            if qq_connector := self.connector_manager.get_connector(qq_source):
                bot_id = getattr(getattr(qq_connector, "bot", None), "self_id", None)

            rtext_content = self.builder.array_to_RText(
                message, sender_id=sender_id,
                low_game_version=is_low_version, chat_image=use_chat_image, image_previewer=use_image_previewer,
                player_manager=player_manager, is_admin=is_admin, bot_id=bot_id
            )

            if player_manager:
                sender_player = player_manager.get_player(str(sender_id))
                if sender_player:
                    # 优先使用 Java 或基岩版的第一个名字
                    sender = (sender_player.java_name[0] if sender_player.java_name
                              else sender_player.bedrock_name[0] if sender_player.bedrock_name
                    else sender_player.name) or sender

                if receiver:
                    receiver_player = player_manager.get_player(str(receiver))
                    if receiver_player:
                        # 优先使用 Java 或基岩版的第一个名字
                        receiver = (receiver_player.java_name[0] if receiver_player.java_name
                                    else receiver_player.bedrock_name[0] if receiver_player.bedrock_name
                        else receiver_player.name) or receiver

            custom_group_name = self.config.get_keys(["connector", "QQ", "permissions", "custom_group_name"], {})
            source = custom_group_name.get(source_id, source)

            main_content = self.builder.build(rtext_content,
                                              group_name=source,
                                              group_id=source_id,
                                              sender=sender,
                                              sender_id=sender_id,
                                              receiver=receiver)

            self.server.say(main_content)

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"{self.log_prefix} 发送消息失败: {error_msg}")
            raise

    async def on_message(self, server: PluginServerInterface, info: Info) -> None:
        """处理从Minecraft服务器接收的消息。

        Parameters
        ----------
        server : PluginServerInterface
            MCDR插件服务器接口实例
        info : Info
            接收到的信息对象
        """
        try:
            if not self.enable:
                return

            is_player = info.is_player

            if not is_player:
                return

            await self.parser(self).process_message(info, server=server)

        except Exception as e:
            self.logger.error(f"{self.log_prefix} 处理消息失败: {e}")
            raise

    async def _is_admin(self, sender_id) -> bool:
        """检查是否是管理员"""
        bound_system = self.connector_manager.system_manager.get_system("bound")

        if not bound_system:
            return False

        player_manager = bound_system.player_manager
        return await player_manager.is_admin(sender_id)
