# -*- coding: utf-8 -*-
"""启动指令系统模块。

该模块提供了启动指令管理功能，包括添加、删除、列表和执行启动指令。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BasicConfig import BasicConfig
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class StartupCommandSystem(BasicConfig, BasicSystem):
    """启动指令系统，管理服务器启动时执行的指令。

    提供添加、删除、列表和执行启动指令的功能。
    继承自 BasicConfig 和 BasicSystem，提供自动的数据持久化功能。

    Attributes
    ----------
    name : str
        系统名称
    enable : bool
        系统是否启用
    commands : List[str]
        存储的启动指令列表（通过 self["commands"] 访问）
    """

    def __init__(
            self, server: PluginServerInterface, config: Optional[BotConfig] = None
    ) -> None:
        """初始化启动指令系统。"""
        BasicSystem.__init__(self, "startup_command", enable=True, config=config)
        self.server = server

        # 设置数据文件路径
        data_path = Path(server.get_data_folder()) / "system" / "startup_commands.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, data_path)

        # 初始化默认数据结构
        if "commands" not in self:
            self["commands"] = []

    def initialize(self) -> None:
        """初始化系统，加载启动指令列表。"""
        # BasicConfig 会自动加载数据，这里只需要确保数据结构正确
        if "commands" not in self:
            self["commands"] = []
        self.logger.debug(f"已加载 {len(self['commands'])} 条启动指令")

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
        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        if not self.enable:
            return False

        if broadcast_info.event_type != "message":
            return False

        if not self.is_command(broadcast_info):
            return False

        if not broadcast_info.is_admin:
            return False

        message = broadcast_info.message
        if not message:
            return False

        first_message = message[0]
        if first_message.get("type") != "text":
            return False

        content = first_message.get("data", {}).get("text", "").strip()
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        # 移除命令前缀
        if not content.startswith(command_prefix):
            return False

        command = content.replace(command_prefix, "", 1).strip()

        # 检查是否是启动指令系统命令
        if not command.startswith(system_name):
            return False

        command = command.replace(system_name, "", 1).strip()

        # 处理各种子命令
        if command.startswith(self.get_tr("gugubot.enable", global_key=True)):
            return await self._handle_enable(broadcast_info)
        elif command.startswith(self.get_tr("gugubot.disable", global_key=True)):
            return await self._handle_disable(broadcast_info)
        elif command.startswith(self.get_tr("list")):
            return await self._handle_list(broadcast_info)
        elif command.startswith(self.get_tr("execute")):
            return await self._handle_execute(broadcast_info)
        elif command.startswith(self.get_tr("add")):
            return await self._handle_add(command, broadcast_info)
        elif command.startswith(self.get_tr("remove")):
            return await self._handle_remove(command, broadcast_info)

        return await self._handle_help(broadcast_info)

    async def _handle_enable(self, broadcast_info: BroadcastInfo) -> bool:
        """处理开启系统命令。"""
        self.enable = True
        self._save_enable_state()
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("enable_success"))]
        )
        return True

    async def _handle_disable(self, broadcast_info: BroadcastInfo) -> bool:
        """处理关闭系统命令。"""
        self.enable = False
        self._save_enable_state()
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("disable_success"))]
        )
        return True

    async def _handle_add(self, command: str, broadcast_info: BroadcastInfo) -> bool:
        """处理添加启动指令命令。"""
        add_cmd = self.get_tr("add")
        if not command.startswith(add_cmd):
            return False

        # 提取指令内容
        command_content = command.replace(add_cmd, "", 1).strip()
        if not command_content:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_instruction"))]
            )
            return True

        # 检查指令是否已存在
        if command_content in self["commands"]:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_existed"))]
            )
            return True

        # 添加指令
        self["commands"].append(command_content)
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("add_success"))]
        )
        self.save()
        return True

    async def _handle_remove(self, command: str, broadcast_info: BroadcastInfo) -> bool:
        """处理删除启动指令命令。"""
        remove_cmd = self.get_tr("remove")
        if not command.startswith(remove_cmd):
            return False

        # 提取指令内容
        command_content = command.replace(remove_cmd, "", 1).strip()
        if not command_content:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_instruction"))]
            )
            return True

        # 检查指令是否存在
        if command_content not in self["commands"]:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_not_exist"))]
            )
            return True

        # 删除指令
        self["commands"].remove(command_content)
        self.save()
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("remove_success"))]
        )
        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理列表命令。"""
        if not self["commands"]:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
            )
            return True

        # 构建指令列表
        command_list = []
        for i, cmd in enumerate(self["commands"], 1):
            command_list.append(f"{i}. {cmd}")

        list_content = "\n".join(command_list)
        await self.reply(
            broadcast_info,
            [
                MessageBuilder.text(
                    self.get_tr("list_content", command_list=list_content)
                )
            ],
        )
        return True

    async def _handle_execute(self, broadcast_info: BroadcastInfo) -> bool:
        """处理执行所有启动指令命令。"""
        if not self["commands"]:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("execute_empty"))]
            )
            return True

        # 执行所有指令
        executed_count = 0
        failed_count = 0

        for command in self["commands"]:
            try:
                self.server.execute(command)
                executed_count += 1
            except Exception as e:
                self.logger.error(f"执行启动指令失败: {command}, 错误: {str(e)}")
                failed_count += 1

        if failed_count == 0:
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr("execute_success", count=executed_count)
                    )
                ],
            )
        else:
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr(
                            "execute_partial",
                            executed=executed_count,
                            failed=failed_count,
                        )
                    )
                ],
            )

        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """处理帮助命令。"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=system_name,
            enable=self.get_tr("gugubot.enable", global_key=True),
            disable=self.get_tr("gugubot.disable", global_key=True),
            add=self.get_tr("add"),
            remove=self.get_tr("remove"),
            list=self.get_tr("list"),
            execute=self.get_tr("execute"),
        )

        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True

    async def execute_all_commands(self) -> Dict[str, Any]:
        """执行所有启动指令（供外部调用）。

        Returns
        -------
        Dict[str, Any]
            执行结果统计
        """
        if not self["commands"]:
            return {"executed": 0, "failed": 0, "total": 0}

        executed_count = 0
        failed_count = 0

        for command in self["commands"]:
            try:
                self.server.execute(command)
                executed_count += 1
            except Exception as e:
                self.logger.error(f"执行启动指令失败: {command}, 错误: {str(e)}")
                failed_count += 1

        return {
            "executed": executed_count,
            "failed": failed_count,
            "total": len(self["commands"]),
        }
