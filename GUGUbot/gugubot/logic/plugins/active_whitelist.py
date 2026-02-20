# -*- coding: utf-8 -*-
"""活跃白名单系统

用于管理活跃白名单玩家，这些玩家在 inactive_check 时会被过滤掉，不会被标记为不活跃。
"""

from pathlib import Path
from typing import List

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BasicConfig
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class ActiveWhiteListSystem(BasicConfig, BasicSystem):
    """活跃白名单系统

    用于管理活跃白名单玩家，这些玩家在 inactive_check 时会被过滤掉。
    """

    def __init__(self, server: PluginServerInterface, config: BotConfig = None) -> None:
        """初始化活跃白名单系统

        Parameters
        ----------
        server : PluginServerInterface
            MCDR 服务器实例
        config : BotConfig
            机器人配置
        """
        BasicSystem.__init__(self, "active_whitelist", enable=True, config=config)
        self.server = server

        # 设置数据文件路径
        data_path = Path(server.get_data_folder()) / "plugins" / "active_whitelist.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, data_path)

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        # 从配置文件加载数据
        self.load()
        self.logger.info("活跃白名单系统已加载")

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的命令。

        Parameters
        ----------
        broadcast_info: BroadcastInfo
            广播信息，包含消息内容
        """
        if broadcast_info.event_type != "message":
            return False

        message = broadcast_info.message

        if not message:
            return False

        first_message = message[0]
        if first_message.get("type") != "text":
            return False

        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        return await self._handle_msg(broadcast_info)

    async def _handle_msg(self, broadcast_info: BroadcastInfo) -> bool:
        """处理消息"""
        if not self.enable:
            return False

        if self.is_command(broadcast_info):
            return await self._handle_command(broadcast_info)

        return False

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        """处理活跃白名单相关命令"""

        if not broadcast_info.is_admin:
            return False

        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        if not command.startswith(system_name):
            return False

        command = command.replace(system_name, "", 1).strip()

        if command.startswith(self.get_tr("add")):
            return await self._handle_add(broadcast_info)
        elif command.startswith(self.get_tr("remove")):
            return await self._handle_remove(broadcast_info)
        elif command.startswith(self.get_tr("list")):
            return await self._handle_list(broadcast_info)

        return await self._handle_help(broadcast_info)

    async def _handle_add(self, broadcast_info: BroadcastInfo) -> bool:
        """处理添加玩家命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()
        command = command.replace(system_name, "", 1).strip()
        command = command.replace(self.get_tr("add"), "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_usage"))]
            )
            return True

        player = command.split()[0]  # 获取第一个参数作为玩家名

        if player in self:
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr("player_already_in_list", player_name=player)
                    )
                ],
            )
            return True

        self[player] = True
        await self.reply(
            broadcast_info,
            [MessageBuilder.text(self.get_tr("player_added", player_name=player))],
        )
        return True

    async def _handle_remove(self, broadcast_info: BroadcastInfo) -> bool:
        """处理移除玩家命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()
        command = command.replace(system_name, "", 1).strip()
        command = command.replace(self.get_tr("remove"), "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_usage"))]
            )
            return True

        player = command.split()[0]  # 获取第一个参数作为玩家名

        if player not in self:
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr("player_not_in_list", player_name=player)
                    )
                ],
            )
            return True

        del self[player]
        await self.reply(
            broadcast_info,
            [MessageBuilder.text(self.get_tr("player_removed", player_name=player))],
        )
        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理查看列表命令"""
        if len(self) == 0:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
            )
            return True

        players = list(self.keys())
        players_str = "\n".join(players)
        await self.reply(
            broadcast_info,
            [
                MessageBuilder.text(
                    self.get_tr("list_content", count=len(players), players=players_str)
                )
            ],
        )
        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """处理帮助命令"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_cmd = self.get_tr("add")
        remove_cmd = self.get_tr("remove")
        list_cmd = self.get_tr("list")

        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=system_name,
            add=add_cmd,
            remove=remove_cmd,
            list=list_cmd,
        )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True

    def add_player(self, player: str) -> bool:
        """添加玩家到活跃白名单（程序调用接口）

        Parameters
        ----------
        player : str
            玩家名

        Returns
        -------
        bool
            是否成功添加（如果玩家已在列表中则返回 False）
        """
        if player not in self:
            self[player] = True
            return True
        return False

    def remove_player(self, player: str) -> bool:
        """从活跃白名单移除玩家（程序调用接口）

        Parameters
        ----------
        player : str
            玩家名

        Returns
        -------
        bool
            是否成功移除（如果玩家不在列表中则返回 False）
        """
        if player in self:
            del self[player]
            return True
        return False

    def is_in_whitelist(self, player: str) -> bool:
        """检查玩家是否在活跃白名单中

        Parameters
        ----------
        player : str
            玩家名

        Returns
        -------
        bool
            玩家是否在活跃白名单中
        """
        return player in self

    def get_all_players(self) -> List[str]:
        """获取所有活跃白名单玩家

        Returns
        -------
        List[str]
            活跃白名单玩家列表
        """
        return list(self.keys())

    def should_filter_player(self, player_name: str) -> bool:
        """检查是否应该过滤该玩家（在 inactive_check 时使用）

        Parameters
        ----------
        player_name : str
            玩家名

        Returns
        -------
        bool
            如果玩家在活跃白名单中，返回True（应该过滤掉）
        """
        return self.is_in_whitelist(player_name)
