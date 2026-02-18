"""玩家通知插件模块。

该模块提供玩家加入和离开时的广播通知功能。
"""

import re
import traceback
from typing import Callable

from mcdreforged.api.types import Info, PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.connector.connector_manager import ConnectorManager
from gugubot.utils.types import ProcessedInfo


def create_on_player_join(
        connector_manager: ConnectorManager, config: BotConfig
) -> Callable[[PluginServerInterface, Info], None]:
    # 从配置文件读取Minecraft的source_name作为默认排除项
    minecraft_source_name = config.get_keys(
        ["connector", "minecraft", "source_name"], "Minecraft"
    )
    exclude_sources = [minecraft_source_name]

    async def on_player_join(server: PluginServerInterface, info: Info) -> None:
        # 从配置中获取玩家加入的正则表达式模式
        join_patterns = config.get_keys(
            ["connector", "minecraft", "player_join_patterns"], []
        )
        player_name = None

        # 尝试匹配玩家名称
        for pattern in join_patterns:
            if match := re.search(pattern, info.content):
                player_name = match.group(1) if match.groups() else match.group(0)
                break

        if player_name is None:
            return

        message = server.tr("gugubot.notice.player_join", player=player_name)

        is_player = not is_bot(player_name, config)

        if (
                is_player
                and not config.get_keys(
            ["connector", "minecraft", "player_join_notice"], True
        )
                or not is_player
                and not config.get_keys(["connector", "minecraft", "bot_join_notice"], True)
        ):
            return

        try:
            # 构建消息
            processed_info = ProcessedInfo(
                processed_message=[MessageBuilder.text(message)],
                _source=minecraft_source_name,  # 使用 _source 参数
                source_id="",
                sender="",
                raw=None,
                server=server,
                logger=server.logger,
                event_sub_type="group",
            )

            # 广播消息（排除Minecraft等平台）
            await connector_manager.broadcast_processed_info(
                processed_info, exclude=exclude_sources
            )

            server.logger.debug(
                server.tr("gugubot.notice.player_join", player=player_name)
            )

        except Exception as e:
            server.logger.error(
                server.tr(
                    "gugubot.notice.player_notice_error",
                    error=str(e) + "\n" + traceback.format_exc(),
                )
            )

    return on_player_join


def create_on_player_left(
        connector_manager: ConnectorManager, config: BotConfig
) -> Callable[[PluginServerInterface, Info], None]:
    # 从配置文件读取Minecraft的source_name作为默认排除项
    minecraft_source_name = config.get_keys(
        ["connector", "minecraft", "source_name"], "Minecraft"
    )
    exclude_sources = [minecraft_source_name]

    async def on_player_left(server: PluginServerInterface, info: Info) -> None:
        # 从配置中获取玩家离开的正则表达式模式
        left_patterns = config.get_keys(
            ["connector", "minecraft", "player_left_patterns"], []
        )
        player_name = None

        # 尝试匹配玩家名称
        for pattern in left_patterns:
            if match := re.search(pattern, info.content):
                player_name = match.group(1) if match.groups() else match.group(0)
                break

        if player_name is None:
            return

        message = server.tr("gugubot.notice.player_left", player=player_name)

        is_player = not is_bot(player_name, config)

        if (
                is_player
                and not config.get_keys(
            ["connector", "minecraft", "player_left_notice"], True
        )
                or not is_player
                and not config.get_keys(["connector", "minecraft", "bot_left_notice"], True)
        ):
            return

        try:
            # 构建消息
            processed_info = ProcessedInfo(
                processed_message=[MessageBuilder.text(message)],
                _source=minecraft_source_name,  # 使用 _source 参数
                source_id="",
                sender="",
                raw=None,
                server=server,
                logger=server.logger,
                event_sub_type="group",
            )

            # 广播消息（排除Minecraft等平台）
            await connector_manager.broadcast_processed_info(
                processed_info, exclude=exclude_sources
            )

            server.logger.debug(
                server.tr("gugubot.notice.player_left", player=player_name)
            )

        except Exception as e:
            server.logger.error(
                server.tr(
                    "gugubot.notice.player_notice_error",
                    error=str(e) + "\n" + traceback.format_exc(),
                )
            )

    return on_player_left


def is_bot(player_name: str, config: BotConfig) -> bool:
    """判断玩家是否为机器人。

    Parameters
    ----------
    player_name : str
        玩家名称
    config : BotConfig
        配置对象

    Returns
    -------
    bool
        如果是机器人返回True，否则返回False
    """
    # 获取机器人名称模式列表
    bot_patterns = config.get_keys(["connector", "minecraft", "bot_names_pattern"], [])

    # 检查玩家名称是否匹配任何机器人模式
    for pattern in bot_patterns:
        try:
            if re.match(pattern, player_name, re.IGNORECASE):
                return True
        except re.error:
            # 如果正则表达式无效，跳过该模式
            continue

    return False
