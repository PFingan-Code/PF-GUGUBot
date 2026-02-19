# -*- coding: utf-8 -*-
"""风格系统模块

该模块提供风格切换功能，允许用户在运行时切换自定义翻译风格。
"""

from typing import Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class StyleSystem(BasicSystem):
    """风格系统，用于管理和切换翻译风格。

    提供查看当前风格、列出所有风格、切换风格等功能。

    Attributes
    ----------
    name : str
        系统名称
    enable : bool
        系统是否启用
    style_manager : StyleManager
        风格管理器实例
    """

    def __init__(
            self,
            server: PluginServerInterface,
            style_manager,
            config: Optional[BotConfig] = None,
    ) -> None:
        """初始化风格系统。

        Parameters
        ----------
        server : PluginServerInterface
            MCDR 服务器接口
        style_manager : StyleManager
            风格管理器实例
        config : BotConfig, optional
            配置对象
        """
        super().__init__("style", enable=True, config=config)
        self.server = server
        self.style_manager = style_manager

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        return

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的命令。

        Parameters
        ----------
        broadcast_info: BroadcastInfo
            广播信息，包含消息内容

        Returns
        -------
        bool
            是否处理了该消息
        """
        if broadcast_info.event_type != "message":
            return False

        if not self.is_command(broadcast_info):
            return False

        return await self._handle_command(broadcast_info)

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        """处理风格命令

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息

        Returns
        -------
        bool
            是否处理了命令
        """
        message = broadcast_info.message
        if not message or message[0].get("type") != "text":
            return False

        content = message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        # 移除命令前缀和系统名称
        command = content.replace(command_prefix, "", 1).strip()
        if not command.startswith(system_name):
            return False

        command = command.replace(system_name, "", 1).strip()

        # 处理不同的命令
        if not command:
            # 显示帮助
            await self._handle_help(broadcast_info)
            return True

        # 获取命令关键词翻译
        list_cmd = self.get_tr("list")
        reload_cmd = self.get_tr("reload")
        help_cmd = self.get_tr("help")

        if command == list_cmd:
            # 列出所有风格
            await self._handle_list(broadcast_info)
            return True
        elif command == reload_cmd:
            # 重新加载风格
            await self._handle_reload(broadcast_info)
            return True
        elif command == help_cmd:
            # 显示帮助
            await self._handle_help(broadcast_info)
            return True

        # 切换到指定风格
        await self._handle_switch(broadcast_info, command)
        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> None:
        """列出所有可用风格"""
        styles = self.style_manager.list_styles()
        current_style = self.style_manager.get_current_style()

        if not styles:
            msg = self.get_tr("list_empty")
        else:
            # 构建风格列表，标记当前风格
            style_list = []
            for style in styles:
                if style == current_style:
                    style_list.append(f"• {style} [当前]")
                else:
                    style_list.append(f"• {style}")

            msg = self.get_tr("style_list", style_list="\n".join(style_list))

        await self.reply(broadcast_info, [MessageBuilder.text(msg)])

    async def _handle_switch(
            self, broadcast_info: BroadcastInfo, style_name: str
    ) -> None:
        """切换到指定风格

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息
        style_name : str
            要切换到的风格名称
        """
        success, reason, remaining = self.style_manager.set_current_style(style_name)

        if success:
            msg = self.get_tr("switch_success", style_name=style_name)
        else:
            if reason == "cooldown":
                # 将剩余时间格式化为易读的形式
                if remaining >= 60:
                    time_str = f"{int(remaining // 60)} 分 {int(remaining % 60)} 秒"
                else:
                    time_str = f"{int(remaining)} 秒"
                msg = self.get_tr("switch_cooldown", remaining=time_str)
            elif reason == "not_found":
                msg = self.get_tr("switch_failed", style_name=style_name)
            else:
                msg = self.get_tr("switch_failed", style_name=style_name)

        await self.reply(broadcast_info, [MessageBuilder.text(msg)])

    async def _handle_reload(self, broadcast_info: BroadcastInfo) -> None:
        """重新加载所有风格文件"""
        try:
            self.style_manager.reload_styles()
            msg = self.get_tr(
                "reload_success", count=len(self.style_manager.list_styles())
            )
        except Exception as e:
            msg = self.get_tr("reload_failed", error=str(e))

        await self.reply(broadcast_info, [MessageBuilder.text(msg)])

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> None:
        """显示帮助信息"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")

        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=self.get_tr("name"),
            list=self.get_tr("list"),
            reload=self.get_tr("reload"),
            help=self.get_tr("help"),
        )

        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
