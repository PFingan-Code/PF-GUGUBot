# -*- coding: utf-8 -*-
"""命令执行系统模块。

该模块提供了命令执行功能，允许管理员执行 MC 原生命令和 MCDR 命令。
"""

import re
import traceback
from typing import Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.rcon_manager import RconManager
from gugubot.utils.types import BroadcastInfo, ProcessedInfo


class ExecuteSystem(BasicSystem):
    """命令执行系统，允许管理员执行服务器命令。

    提供执行 MC 原生命令和 MCDR 命令的功能。

    Attributes
    ----------
    name : str
        系统名称
    enable : bool
        系统是否启用
    server : PluginServerInterface
        MCDR 服务器接口实例
    rcon_manager : RconManager
        RCON 管理器实例
    """

    def __init__(self, server: PluginServerInterface, config: Optional[BotConfig] = None) -> None:
        """初始化命令执行系统。"""
        BasicSystem.__init__(self, "execute", enable=True, config=config)
        self.server = server
        self.rcon_manager = RconManager(server)
        self.logger = server.logger

    def initialize(self) -> None:
        """初始化系统。"""
        self.logger.debug("命令执行系统已初始化")

    def _should_ignore_command(self, command: str) -> bool:
        """检查命令是否应该被忽略。

        Parameters
        ----------
        command : str
            要检查的命令

        Returns
        -------
        bool
            如果命令应该被忽略，返回 True
        """
        ignore_patterns = self.config.get_keys(
            ["system", "execute", "ignore_execute_command_patterns"],
            []
        )

        if not ignore_patterns:
            return False

        for pattern in ignore_patterns:
            try:
                if re.match(pattern, command):
                    return True
            except re.error:
                self.logger.warning(f"无效的正则表达式模式: {pattern}")

        return False

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

        message = broadcast_info.message
        if not message:
            return False

        first_message = message[0]
        if first_message.get("type") != "text":
            return False

        content = first_message.get("data", {}).get("text", "").strip()
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        bridge_name = self.config.get_keys(
            ["connector", "minecraft_bridge", "source_name"],
            "Bridge"
        )

        # 检查是否是 #执行 命令
        execute_cmd = self.get_tr("execute")
        mcdr_cmd = self.get_tr("mcdr")
        help_cmd = self.get_tr("gugubot.system.general_help.help_command", global_key=True)

        if content.startswith(f"{command_prefix}{execute_cmd}"):
            # 提取命令内容
            command = content.replace(f"{command_prefix}{execute_cmd}", "", 1).strip()
            if not command:
                # 如果没有命令内容，显示帮助信息
                return await self._handle_help(broadcast_info)

            # 检查是否是帮助命令
            if command == help_cmd or command == "帮助" or command.lower() == "help":
                return await self._handle_help(broadcast_info)

            # 检查是否包含 @<服务器名> 格式
            bridge_match = re.match(r'^@([\w\-_]+)\s+(.+)$', command)
            if bridge_match:
                target_server = bridge_match.group(1)
                command = bridge_match.group(2)

            # 检查是否应该忽略
            if self._should_ignore_command(command):
                await self.reply(broadcast_info, [MessageBuilder.text(self.get_tr("command_ignored"))])
                return True

            # 如果包含 @<服务器名> 格式，则通过 bridge 发送命令
            if bridge_match and target_server and target_server not in [bridge_name]:
                return await self._send_command_via_bridge(
                    command,
                    broadcast_info,
                    target_server=target_server,
                    use_mcdr=False
                )

            if not self.is_command(broadcast_info) or \
                    (not await self._is_admin(broadcast_info.sender_id) and not broadcast_info.is_admin):
                return False

            # 执行 MC 原生命令
            return await self._handle_execute_command(command, broadcast_info, use_mcdr=False)

        elif content.startswith(f"{command_prefix}{mcdr_cmd}"):
            # 提取命令内容
            command = content.replace(f"{command_prefix}{mcdr_cmd}", "", 1).strip()
            if not command:
                await self.reply(broadcast_info, [MessageBuilder.text(
                    self.get_tr("mcdr_instruction", command_prefix=command_prefix, mcdr=mcdr_cmd))])
                return True

            # 检查是否包含 @<服务器名> 格式
            bridge_match = re.match(r'^@([\w\-_]+)\s+(.+)$', command)
            if bridge_match:
                target_server = bridge_match.group(1)
                command = bridge_match.group(2)

            # 检查是否应该忽略
            if self._should_ignore_command(command):
                await self.reply(broadcast_info, [MessageBuilder.text(self.get_tr("command_ignored"))])
                return True

            # 如果包含 @<服务器名> 格式，则通过 bridge 发送命令
            if bridge_match and target_server and target_server != bridge_name:
                return await self._send_command_via_bridge(
                    command,
                    broadcast_info,
                    target_server=target_server,
                    use_mcdr=True
                )

            if not self.is_command(broadcast_info) or \
                    (not await self._is_admin(broadcast_info.sender_id) and not broadcast_info.is_admin):
                return False

            # 执行 MCDR 命令
            return await self._handle_execute_command(command, broadcast_info, use_mcdr=True)

        # 检查是否是系统名称命令（显示帮助）
        system_name = self.get_tr("name")
        if content == f"{command_prefix}{system_name}" or content == f"{command_prefix}{system_name} {help_cmd}":
            return await self._handle_help(broadcast_info)

        return False

    async def _handle_execute_command(
            self,
            command: str,
            broadcast_info: BroadcastInfo,
            use_mcdr: bool = False
    ) -> bool:
        """处理命令执行。

        Parameters
        ----------
        command : str
            要执行的命令
        broadcast_info : BroadcastInfo
            广播信息
        use_mcdr : bool
            是否使用 MCDR 命令执行方式

        Returns
        -------
        bool
            是否成功处理
        """
        try:
            # 如果是 MCDR 命令且没有 !! 前缀，自动添加
            if use_mcdr and not command.startswith("!!"):
                command = f"!!{command}"

            result = self.rcon_manager.execute(command, use_mcdr_command=use_mcdr)

            if result:
                await self.reply(broadcast_info, [MessageBuilder.text(result)])
            else:
                await self.reply(broadcast_info, [MessageBuilder.text(self.get_tr("execute_success"))])

            return True
        except Exception as e:
            self.logger.error(f"执行命令失败: {command}, 错误: {str(e)}")
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("execute_failed", error=str(e)))]
            )
            return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """处理帮助命令。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息

        Returns
        -------
        bool
            是否成功处理
        """
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        execute_cmd = self.get_tr("execute")
        mcdr_cmd = self.get_tr("mcdr")

        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=system_name,
            execute=execute_cmd,
            mcdr=mcdr_cmd
        )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True

    async def _send_command_via_bridge(
            self,
            command: str,
            broadcast_info: BroadcastInfo,
            target_server: str,
            use_mcdr: bool = False
    ) -> bool:
        """通过 bridge 发送命令到指定服务器。

        Parameters
        ----------
        command : str
            要执行的命令
        broadcast_info : BroadcastInfo
            广播信息
        target_server : str
            目标服务器名称
        use_mcdr : bool
            是否使用 MCDR 命令执行方式

        Returns
        -------
        bool
            是否成功处理
        """
        try:
            # 检查是否允许通过 bridge 执行命令
            allow_bridge_execute = self.config.get_keys(
                ["system", "execute", "allow_bridge_execute"],
                True
            )
            if not allow_bridge_execute:
                await self.reply(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("bridge_execute_disabled"))]
                )
                return True

            # 获取 bridge 连接器
            bridge_source = self.config.get_keys(
                ["connector", "minecraft_bridge", "source_name"],
                "Bridge"
            )
            bridge_connector = self.system_manager.connector_manager.get_connector(bridge_source)

            if not bridge_connector:
                await self.reply(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("bridge_not_found"))]
                )
                return True

            # 构造要发送的命令消息
            command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
            execute_cmd = self.get_tr("execute")
            mcdr_cmd = self.get_tr("mcdr")

            if use_mcdr:
                command_text = f"{command_prefix}{mcdr_cmd} {command}"
            else:
                command_text = f"{command_prefix}{execute_cmd} {command}"

            # 构造 ProcessedInfo，保持 source 为原始发送渠道
            processed_info = ProcessedInfo(
                processed_message=[MessageBuilder.text(command_text)],
                _source=broadcast_info.source,  # 传递完整的 Source 对象
                source_id=broadcast_info.source_id,
                sender=broadcast_info.sender,
                sender_id=broadcast_info.sender_id,
                raw=broadcast_info.raw,
                server=broadcast_info.server,
                logger=broadcast_info.logger,
                event_sub_type=broadcast_info.event_sub_type,
                target={target_server: broadcast_info.event_sub_type}  # 指定目标服务器
            )

            # 通过 bridge 发送消息
            await self.system_manager.connector_manager.broadcast_processed_info(
                processed_info,
                include=[bridge_source]
            )

            # 发送成功提示
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("bridge_execute_success", target=target_server))]
            )
            return True

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"通过 bridge 发送命令失败: {command}, 错误: {error_msg}")
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("bridge_execute_failed", error=str(e)))]
            )
            return True

    async def _is_admin(self, sender_id) -> bool:
        """检查是否是管理员"""
        bound_system = self.system_manager.get_system("bound")

        if not bound_system:
            return False

        player_manager = bound_system.player_manager
        return await player_manager.is_admin(sender_id)
