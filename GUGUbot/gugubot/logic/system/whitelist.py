from typing import Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class WhitelistSystem(BasicSystem):
    """白名单系统，用于管理服务器白名单。

    提供添加、删除、查询白名单玩家等功能。
    """

    def __init__(
            self, server: PluginServerInterface, config: Optional[BotConfig] = None
    ) -> None:
        """初始化白名单系统。"""
        super().__init__("whitelist", enable=False, config=config)
        self.server = server
        self._api: Optional[object] = None
        self.online_mode: bool = False  # 默认离线模式

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        try:
            self._api = self.server.get_plugin_instance("whitelist_api")
            if self._api:
                self.online_mode = self._api.whitelist_api().online_mode
                self.logger.debug("白名单API已加载")
            else:
                self.logger.warning("未找到白名单API插件")
        except Exception as e:
            self.logger.error(f"初始化白名单API失败: {e}")
            self._api = None

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的命令。

        Parameters
        ----------
        broadcast_info: BroadcastInfo
            广播信息，包含消息内容
        """
        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        if broadcast_info.event_type != "message":
            return False

        message = broadcast_info.message

        if not message:
            return False

        first_message = message[0]
        if first_message.get("type") != "text":
            return False

        return await self._handle_msg(broadcast_info)

    async def _handle_msg(self, broadcast_info: BroadcastInfo) -> bool:
        """处理消息"""
        content = broadcast_info.message[0].get("data", {}).get("text", "")

        if self.is_command(broadcast_info):
            return await self._handle_command(broadcast_info)

        return False

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        """处理白名单相关命令"""
        is_admin = broadcast_info.is_admin

        if not is_admin:
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
        elif command.startswith(self.get_tr("gugubot.enable", global_key=True)):
            return await self._handle_enable(broadcast_info)
        elif command.startswith(self.get_tr("gugubot.disable", global_key=True)):
            return await self._handle_disable(broadcast_info)

        return await self._handle_help(broadcast_info)

    def add_player(
            self,
            player_name: str,
            force_online: bool = False,
            force_offline: bool = False,
            force_bedrock: bool = False,
    ) -> bool:
        """添加玩家到白名单

        Args:
            player_name (str): 玩家名称
            force_online (bool): 强制在线模式
            force_offline (bool): 强制离线模式
            force_bedrock (bool): 强制基岩版模式

        Returns:
            bool: 是否成功添加
        """
        if not self._api:
            self.logger.error("白名单API未初始化")
            return False

        try:
            whitelist = self._api.get_whitelist_names()

            if force_bedrock:
                self._api.add_floodgate_player(player_name, "")
                return True

            if player_name not in whitelist:
                # 自动模式
                if not any([force_online, force_offline, force_bedrock]):
                    self._api.add_player(player_name)
                elif force_online:
                    self._api.add_online_player(player_name)
                elif force_offline:
                    self._api.add_offline_player(player_name)

                return True

            return False
        except Exception as e:
            self.logger.error(f"添加玩家到白名单失败: {e}")
            return False

    def remove_player(self, player_name: str) -> bool:
        """从白名单移除玩家

        Args:
            player_name (str): 玩家名称

        Returns:
            bool: 是否成功移除
        """
        if not self._api:
            self.logger.error("白名单API未初始化")
            return False

        try:
            whitelist = self._api.get_whitelist_names()

            for player in whitelist:
                if player_name.lower() == player.lower():
                    self._api.remove_player(player, force_offline=True)
                    return True

            return False
        except Exception as e:
            self.logger.error(f"从白名单移除玩家失败: {e}")
            return False

    async def _handle_add(self, broadcast_info: BroadcastInfo) -> bool:
        """处理添加玩家命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_command = self.get_tr("add")

        for i in [command_prefix, system_name, add_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_instruction"))]
            )
            return True

        # 解析参数
        parts = command.split()
        player_name = parts[0]

        # 解析模式参数
        force_online = False
        force_offline = False
        force_bedrock = False

        if len(parts) > 1:
            mode = parts[1].lower()
            online_keywords = ["online", "在线", "正版", "true", "1"]
            offline_keywords = ["offline", "离线", "false", "0"]
            bedrock_keywords = ["bedrock", "基岩", "be"]

            force_online = mode in online_keywords
            force_offline = mode in offline_keywords
            force_bedrock = mode in bedrock_keywords

        success = self.add_player(
            player_name, force_online, force_offline, force_bedrock
        )
        if success:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_success"))]
            )
        else:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_existed"))]
            )

        return True

    async def _handle_remove(self, broadcast_info: BroadcastInfo) -> bool:
        """处理移除玩家命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        remove_command = self.get_tr("remove")

        for i in [command_prefix, system_name, remove_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_instruction"))]
            )
            return True

        success = self.remove_player(command)
        if success:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_success"))]
            )
        else:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_not_exist"))]
            )

        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理显示白名单列表命令"""
        if not self._api:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("api_not_available"))]
            )
            return True

        try:
            whitelist = self._api.get_whitelist_names()
            if not whitelist:
                await self.reply(
                    broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
                )
                return True

            player_list = "\n".join(
                f"{i + 1}. {name}" for i, name in enumerate(sorted(whitelist))
            )
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr("list_content", player_list=player_list)
                    )
                ],
            )
        except Exception as e:
            self.logger.error(f"获取白名单列表失败: {e}")
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("list_failed"))]
            )

        return True

    async def _handle_enable(self, broadcast_info: BroadcastInfo) -> bool:
        """处理启用白名单命令"""
        if not self._api:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("api_not_available"))]
            )
            return True

        try:
            self._api.enable_whitelist()
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("enable_success"))]
            )
        except Exception as e:
            self.logger.error(f"启用白名单失败: {e}")
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("enable_failed"))]
            )

        return True

    async def _handle_disable(self, broadcast_info: BroadcastInfo) -> bool:
        """处理禁用白名单命令"""
        if not self._api:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("api_not_available"))]
            )
            return True

        try:
            self._api.disable_whitelist()
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("disable_success"))]
            )
        except Exception as e:
            self.logger.error(f"禁用白名单失败: {e}")
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("disable_failed"))]
            )

        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """白名单指令帮助"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_command = self.get_tr("add")
        remove_command = self.get_tr("remove")
        list_command = self.get_tr("list")
        enable_command = self.get_tr("gugubot.enable", global_key=True)
        disable_command = self.get_tr("gugubot.disable", global_key=True)
        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=system_name,
            add=add_command,
            remove=remove_command,
            list=list_command,
            enable=enable_command,
            disable=disable_command,
        )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True
