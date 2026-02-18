# -*- coding: utf-8 -*-
"""帮助消息注册工具模块。

该模块提供了注册 GUGUBot 帮助命令的功能。
"""

from typing import Optional

from mcdreforged.api.command import Literal
from mcdreforged.api.types import CommandSource, PluginServerInterface

from gugubot.config.BotConfig import BotConfig


def help_msg_register(
        server: PluginServerInterface, config: Optional[BotConfig] = None
) -> None:
    """注册 !!gugubot 命令，显示基本帮助信息。

    Parameters
    ----------
    server : PluginServerInterface
        MCDReforged 服务器接口实例
    config : BotConfig, optional
        GUGUBot 配置对象，如果为 None 则使用默认值
    """
    # 获取命令前缀
    if config:
        command_prefix = config.get_keys(["GUGUBot", "command_prefix"], "#")
    else:
        command_prefix = "#"

    # 获取帮助命令名称
    try:
        help_name = server.tr("gugubot.system.general_help.name")
    except Exception:
        help_name = "帮助"

    # 构建帮助信息
    help_message = f"在非控制台环境下使用 {command_prefix} 或 {command_prefix}{help_name} 查看详细帮助信息"

    def help_handler(source: CommandSource):
        """处理 !!gugubot 命令"""
        source.reply(help_message)

    # 注册命令
    server.register_command(Literal("!!gugubot").runs(help_handler))

    # 注册帮助消息
    server.register_help_message("!!gugubot", "GUGUBot 基本帮助信息")
