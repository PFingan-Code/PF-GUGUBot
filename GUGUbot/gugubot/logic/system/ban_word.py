# -*- coding: utf-8 -*-

from pathlib import Path
from typing import List, Optional, Tuple

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BasicConfig, BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class BanWordSystem(BasicConfig, BasicSystem):
    """违禁词系统，用于管理和检测违禁词。

    提供添加、删除、显示违禁词，以及违禁词检测等功能。
    """

    def __init__(
            self, server: PluginServerInterface, config: Optional[BotConfig] = None
    ) -> None:
        """初始化违禁词系统。"""
        BasicSystem.__init__(self, "ban_words", enable=False, config=config)
        data_path = Path(server.get_data_folder()) / "system" / "ban_words.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, data_path)

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        # 从配置文件加载违禁词
        self.load()
        self.logger.debug(f"已加载 {len(self)} 个违禁词")

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的命令和消息。

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

        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        if not self.enable:
            return False

        return await self._handle_msg(broadcast_info)

    async def _handle_msg(self, broadcast_info: BroadcastInfo) -> bool:
        """处理消息"""
        messages = broadcast_info.message
        is_admin = broadcast_info.is_admin

        # 检查消息中是否包含违禁词
        ban_check = self._check_ban(messages)
        if ban_check and not is_admin and self.enable:
            ban_word, reason = ban_check
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr(
                            "ban_word_detected", ban_word=ban_word, reason=reason
                        )
                    )
                ],
            )
            return True

        # 处理命令
        if is_admin and self.is_command(broadcast_info):
            return await self._handle_command(broadcast_info)

        return False

    def _check_ban(self, messages: List[dict]) -> Optional[Tuple[str, str]]:
        """检查消息中是否包含违禁词

        Parameters
        ----------
        messages : List[dict]
            要检查的消息

        Returns
        -------
        tuple or None
            如果包含违禁词，返回 [违禁词, 理由]，否则返回 None
        """
        for message in messages:
            for ban_word, reason in self.items():
                if ban_word in message.get("data", {}).get("text", ""):
                    return ban_word, reason
        return None

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        """处理命令"""
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
        """处理添加违禁词命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_command = self.get_tr("add")

        for i in [command_prefix, system_name, add_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr(
                            "add_format_error",
                            command_prefix=command_prefix,
                            name=system_name,
                            add=add_command,
                        )
                    )
                ],
            )
            return True

        parts = command.split(maxsplit=1)
        if len(parts) != 2:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_instruction"))]
            )
            return True

        ban_word = parts[0]
        reason = parts[1]

        self[ban_word] = reason
        self.save()
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("add_success"))]
        )

        return True

    async def _handle_remove(self, broadcast_info: BroadcastInfo) -> bool:
        """处理删除违禁词命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        remove_command = self.get_tr("remove")

        for i in [command_prefix, system_name, remove_command]:
            command = command.replace(i, "", 1).strip()

        if command not in self:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_not_exist"))]
            )
            return True

        del self[command]
        self.save()
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("remove_success"))]
        )
        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理显示违禁词列表命令"""

        if len(self) == 0:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
            )
            return True

        ban_word_list = []
        for word, reason in self.items():
            ban_word_list.append(f"{word}: {reason}")
        ban_word_list = "\n".join(ban_word_list)
        await self.reply(
            broadcast_info,
            [
                MessageBuilder.text(
                    self.get_tr("ban_word_list", ban_word_list=ban_word_list)
                )
            ],
        )
        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """违禁词指令帮助"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        enable_cmd = self.get_tr("gugubot.enable", global_key=True)
        disable_cmd = self.get_tr("gugubot.disable", global_key=True)
        add_cmd = self.get_tr("add")
        remove_cmd = self.get_tr("remove")
        list_cmd = self.get_tr("list")
        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=system_name,
            enable=enable_cmd,
            disable=disable_cmd,
            add=add_cmd,
            remove=remove_cmd,
            list=list_cmd,
        )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True
