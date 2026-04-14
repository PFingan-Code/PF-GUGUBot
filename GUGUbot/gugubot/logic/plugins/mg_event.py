# -*- coding: utf-8 -*-
"""Minecraft 事件系统模块。

该模块提供了处理 Minecraft 游戏事件的功能，包括成就获得和玩家死亡事件的广播。
"""
from typing import Dict, List, Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BotConfig
from gugubot.connector import ConnectorManager
from gugubot.utils.types import ProcessedInfo


def _build_notice_target(group_ids: List) -> Optional[Dict[str, str]]:
    groups = [g for g in (group_ids or []) if g]
    if not groups:
        return None
    target = {str(g): "group" for g in groups}
    if len(target) == 1:
        target["_"] = "group"  # 防止桥接连接器单目标过滤
    return target


# 转发死亡
def create_on_mc_death(config: BotConfig, connector_manager: ConnectorManager):
    notice_target = _build_notice_target(
        config.get_keys(["connector", "QQ", "permissions", "notice_forward_groups"], [])
    )

    def on_mc_death(server: PluginServerInterface, player, event, content):
        if not config.get_keys(["connector", "minecraft", "mc_death"], True):
            return

        player: str = player
        event: str = event  # death event
        for i in content:
            if i.locale != server.get_mcdr_language():  # get the correct language
                continue
            server.schedule_task(
                broadcast_msg(i.raw, config, server, connector_manager, notice_target)
            )

    return on_mc_death


# 转发成就
def create_on_mc_achievement(config: BotConfig, connector_manager: ConnectorManager):
    notice_target = _build_notice_target(
        config.get_keys(["connector", "QQ", "permissions", "notice_forward_groups"], [])
    )

    def on_mc_achievement(server: PluginServerInterface, player, event, content):
        if not config.get_keys(["connector", "minecraft", "mc_achievement"], True):
            return

        player: str = player
        event: str = event  # achievement event
        for i in content:
            if i.locale != server.get_mcdr_language():  # get the correct language
                continue
            server.schedule_task(
                broadcast_msg(i.raw, config, server, connector_manager, notice_target)
            )

    return on_mc_achievement


async def broadcast_msg(
        message: str,
        config: BotConfig,
        server: PluginServerInterface,
        connector_manager: ConnectorManager,
        forward_target: Optional[Dict[str, str]] = None,
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
            target=forward_target,
        ),
        exclude=[
            config.get_keys(["connector", "minecraft", "source_name"], "Minecraft")
        ],
    )
