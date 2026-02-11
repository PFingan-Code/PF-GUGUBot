# -*- coding: utf-8 -*-
"""Minecraft 事件系统模块。

该模块提供了处理 Minecraft 游戏事件的功能，包括成就获得和玩家死亡事件的广播。
"""
from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.connector.connector_manager import ConnectorManager
from gugubot.utils.types import ProcessedInfo


# 转发死亡
def create_on_mc_death(config: BotConfig, connector_manager: ConnectorManager):
    def on_mc_death(server: PluginServerInterface, player, event, content):
        if not config.get_keys(["connector", "minecraft", "mc_death"], True):
            return

        player: str = player
        event: str = event  # death event
        for i in content:
            if i.locale != server.get_mcdr_language():  # get the correct language
                continue
            server.schedule_task(
                broadcast_msg(i.raw, config, server, connector_manager)
            )

    return on_mc_death


# 转发成就
def create_on_mc_achievement(config: BotConfig, connector_manager: ConnectorManager):
    def on_mc_achievement(server: PluginServerInterface, player, event, content):
        if not config.get_keys(["connector", "minecraft", "mc_achievement"], True):
            return

        player: str = player
        event: str = event  # achievement event
        for i in content:
            if i.locale != server.get_mcdr_language():  # get the correct language
                continue
            server.schedule_task(
                broadcast_msg(i.raw, config, server, connector_manager)
            )

    return on_mc_achievement


async def broadcast_msg(
        message: str,
        config: BotConfig,
        server: PluginServerInterface,
        connector_manager: ConnectorManager,
):
    await connector_manager.broadcast_processed_info(
        ProcessedInfo(
            processed_message=[MessageBuilder.text(message)],
            _source=config.get_keys(  # 使用 _source 参数
                ["connector", "minecraft", "source_name"], "Minecraft"
            ),
            source_id="",
            sender="",
            raw=None,
            server=server,
            logger=server.logger,
            event_sub_type="group",
        ),
        exclude=[
            config.get_keys(["connector", "minecraft", "source_name"], "Minecraft")
        ],
    )
