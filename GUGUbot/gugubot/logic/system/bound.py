# -*- coding: utf-8 -*-
import re
from typing import List, Optional, Union

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.logic.system.whitelist import WhitelistSystem
from gugubot.utils.player_manager import Player, PlayerManager
from gugubot.utils.types import BroadcastInfo


class BoundSystem(BasicSystem):
    """绑定系统，用于管理QQ账号与游戏玩家的绑定关系。

    提供绑定、解绑、查询绑定信息等功能。
    """

    def __init__(
            self, server: PluginServerInterface, config: Optional[BotConfig] = None
    ) -> None:
        """初始化绑定系统。"""
        super().__init__("bound", enable=False, config=config)
        self.server = server
        self.player_manager = PlayerManager(server, self)
        self.whitelist: Optional[WhitelistSystem] = None

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        self.player_manager.load()
        self.logger.debug(
            f"已加载 {len(self.player_manager.get_all_players())} 个玩家绑定信息"
        )

    def set_whitelist_system(self, whitelist: WhitelistSystem) -> None:
        """设置白名单系统引用"""
        self.whitelist = whitelist

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

        if not self.enable:
            return False

        # 处理退群事件
        if (
                broadcast_info.event_type == "notice"
                and broadcast_info.event_sub_type == "group_decrease"
        ):
            if broadcast_info.source.is_from("QQ"):
                return await self._handle_quit_member(broadcast_info)
            return False

        # 处理消息类型事件
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

    @staticmethod
    def _starts_with_command(text: str, cmd: str) -> bool:
        """判断 text 是否以 cmd 作为完整命令前缀开头。

        确保 cmd 后面紧跟空格或到达字符串末尾，
        避免 "绑定提醒" 被 "绑定" 错误匹配。
        """
        if not text.startswith(cmd):
            return False
        remaining = text[len(cmd):]
        return not remaining or remaining[0] == " "

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        """处理绑定相关命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        valid_commands = [
            system_name,
            self.get_tr("bind"),
            self.get_tr("unbind"),
            self.get_tr("search"),
        ]
        if not any(self._starts_with_command(command, i) for i in valid_commands):
            return False

        command = command.replace(system_name, "", 1).strip()

        if command.strip() == "" and len(broadcast_info.message) == 1:
            return await self._handle_help(broadcast_info)
        elif command.startswith(self.get_tr("unbind")):
            return await self._handle_unbind(broadcast_info)
        elif command.startswith(self.get_tr("list")):
            return await self._handle_list(broadcast_info)
        elif broadcast_info.is_admin:
            # 管理员专属命令
            if command in ["白名单检查", "whitelist_check"]:
                return await self._handle_check_whitelist(broadcast_info)
            elif command in ["移除未绑定白名单", "remove_unbound_whitelist"]:
                return await self._handle_remove_unbound_whitelist(broadcast_info)
            elif command in ["多余绑定检查", "extra_bound_check"]:
                return await self._handle_check_extra_bound(broadcast_info)
            elif command in ["移除多余绑定", "remove_extra_bound"]:
                return await self._handle_remove_extra_bound(broadcast_info)

        return await self._handle_bind(broadcast_info)

    async def _handle_bind(self, broadcast_info: BroadcastInfo) -> bool:
        """处理绑定命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        bind_cmd = self.get_tr("bind")

        for i in [command_prefix, system_name]:
            command = command.replace(i, "", 1).strip()

        if not command and len(broadcast_info.message) == 1:
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr(
                            "bind_instruction",
                            command_prefix=command_prefix,
                            name=system_name,
                            bind=bind_cmd,
                        )
                    )
                ],
            )
            return True

        # 解析消息段
        source = broadcast_info.source.origin  # 获取原始来源作为平台标识
        target_id = broadcast_info.sender_id  # 默认绑定到发送者
        player_name = ""
        is_bedrock = False

        # 检查是否有@消息段，如果有就更新要绑定的平台账户
        for message_segment in broadcast_info.message:
            if message_segment.get("type") == "at":
                target_id = message_segment.get("data", {}).get(
                    "qq", broadcast_info.sender_id
                )
                break

        # 使用最后一个消息段来处理玩家名和基岩版标识
        last_text_message = [
            message
            for message in broadcast_info.message
            if message.get("type") == "text"
        ][-1]
        last_text = last_text_message.get("data", {}).get("text", "")
        for i in [command_prefix, system_name]:
            last_text = last_text.replace(i, "", 1).strip()
        parts = last_text.split(maxsplit=1)
        if parts:
            player_name = parts[0]

        is_bedrock = is_offline = is_online = False
        if len(parts) > 1:
            is_bedrock = parts[1].lower() in ["bedrock", "基岩", "be"]
            is_offline = parts[1].lower() in ["offline", "离线", "off"]
            is_online = parts[1].lower() in ["online", "在线", "on"]

        if not player_name:
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr(
                            "bind_instruction",
                            command_prefix=command_prefix,
                            name=system_name,
                            bind=bind_cmd,
                        )
                    )
                ],
            )
            return True

        # 验证玩家名是否符合正则表达式
        player_name_pattern = (
            self.config.get("system", {})
            .get("bound", {})
            .get("player_name_pattern", "")
        )
        if player_name_pattern:
            try:
                if not re.match(player_name_pattern, player_name):
                    await self.reply(
                        broadcast_info,
                        [
                            MessageBuilder.text(
                                self.get_tr(
                                    "bind_invalid_name",
                                    player_name=player_name,
                                    pattern=player_name_pattern,
                                )
                            )
                        ],
                    )
                    return True
            except re.error as e:
                self.logger.error(f"正则表达式 '{player_name_pattern}' 格式错误: {e}")
                await self.reply(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("bind_pattern_error"))],
                )
                return True

        # 检查是否达到绑定上限
        player = self.player_manager.get_player(
            target_id or player_name, platform=source
        )

        exceeded_platform_bound = exceeded_bedrock_bound = exceeded_java_bound = False
        if player:
            exceeded_platform_bound = len(
                player.accounts.get(source, [])
            ) >= self.config.get("system", {}).get("bound", {}).get(
                "max_platform_bound", 1
            )
            exceeded_bedrock_bound = len(player.bedrock_name) >= self.config.get(
                "system", {}
            ).get("bound", {}).get("max_bedrock_bound", 1)
            exceeded_java_bound = len(player.java_name) >= self.config.get(
                "system", {}
            ).get("bound", {}).get("max_java_bound", 1)

        # 到达所有绑定上限
        if (
                player
                and exceeded_platform_bound
                and exceeded_bedrock_bound
                and exceeded_java_bound
        ):
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("max_bound_reached"))]
            )
            return True

        elif (not is_bedrock and exceeded_platform_bound and exceeded_java_bound) or (
                is_bedrock and exceeded_platform_bound and exceeded_bedrock_bound
        ):
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("max_bound_reached"))]
            )
            return True

        # 直接执行绑定
        bound_result = await self._bind_player(
            broadcast_info,
            player_name,
            source,
            is_bedrock,
            is_offline,
            is_online,
            target_id,
        )
        if bound_result:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("bind_success"))]
            )
        else:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("bind_existed"))]
            )

        return True

    async def _bind_player(
            self,
            broadcast_info: BroadcastInfo,
            player_name: str,
            platform: str,
            is_bedrock: bool = False,
            is_offline: bool = False,
            is_online: bool = False,
            target_id: str = None,
    ) -> bool:
        """执行玩家绑定"""
        try:
            # 如果用户未指定任何选项，则使用系统默认模式
            if not any([is_bedrock, is_online, is_offline]):
                is_offline = not self.whitelist.online_mode
                is_online = self.whitelist.online_mode

            # 检查玩家名是否已被其他用户绑定
            if self.player_manager.is_name_bound_by_other_user(
                    player_name, target_id, platform
            ):
                return False

            def _bound_whitelist(
                    player_name: str, is_offline: bool, is_online: bool, is_bedrock: bool
            ):
                if (
                        self.config.get("system", {})
                                .get("bound", {})
                                .get("whitelist_add_with_bound", False)
                        and self.whitelist
                ):
                    self.whitelist.add_player(
                        player_name,
                        force_offline=is_offline,
                        force_online=is_online,
                        force_bedrock=is_bedrock,
                    )

            async def _set_group_card_if_qq(
                    player_name: str,
                    platform: str,
                    broadcast_info: BroadcastInfo,
                    target_id: str,
            ):
                """如果是QQ来源，则设置群名片"""
                if platform == "QQ" and self.config.get_keys(
                        ["connector", "QQ", "others", "change_group_card"], True
                ):
                    await self.system_manager.connector_manager.get_connector(
                        "QQ"
                    ).bot.set_group_card(
                        group_id=int(broadcast_info.source_id),
                        user_id=int(target_id),
                        card=player_name,
                    )

            # 检查是否已存在该玩家
            existing_player = self.player_manager.get_player(
                target_id, platform=platform
            )
            if existing_player:
                # 将列表中的元素转换为字符串进行比较
                bedrock_names_str = [str(name) for name in existing_player.bedrock_name]
                java_names_str = [str(name) for name in existing_player.java_name]
                if (is_bedrock and player_name not in bedrock_names_str) or (
                        not is_bedrock and player_name not in java_names_str
                ):
                    existing_player.add_name(player_name, is_bedrock)
                    self.player_manager.save()
                    _bound_whitelist(player_name, is_offline, is_online, is_bedrock)
                    await _set_group_card_if_qq(
                        player_name, platform, broadcast_info, target_id
                    )
                    return True

                elif player_name not in existing_player.accounts.get(platform, []):
                    existing_player.add_account(platform, target_id)
                    self.player_manager.save()
                    _bound_whitelist(player_name, is_offline, is_online, is_bedrock)
                    await _set_group_card_if_qq(
                        player_name, platform, broadcast_info, target_id
                    )
                    return True

                return False

            # 添加新玩家绑定
            self.player_manager.add_player_account(
                player_name,
                platform=platform,
                account_id=target_id,
                is_bedrock=is_bedrock,
            )
            self.player_manager.save()
            _bound_whitelist(player_name, is_offline, is_online, is_bedrock)
            await _set_group_card_if_qq(
                player_name, platform, broadcast_info, target_id
            )

            return True
        except Exception as e:
            self.logger.error(f"绑定玩家失败: {e}")
            return False

    async def _handle_unbind(self, broadcast_info: BroadcastInfo) -> bool:
        """处理解绑命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        unbind_command = self.get_tr("unbind")

        for i in [command_prefix, system_name, unbind_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            # 解绑当前用户的所有绑定
            return await self._unbind_current_user(broadcast_info)
        else:
            # 检查是否是基岩版独立命令
            if command.lower() in ["bedrock", "基岩", "be"]:
                return await self._unbind_bedrock_only(broadcast_info)

            # 解析玩家名和基岩版参数
            parts = command.split(maxsplit=1)
            player_name = parts[0]
            is_bedrock = False

            if len(parts) > 1:
                is_bedrock = parts[1].lower() in ["bedrock", "基岩", "be"]

            # 解绑指定玩家
            return await self._unbind_specific_player(
                broadcast_info, player_name, is_bedrock
            )

    async def _unbind_current_user(self, broadcast_info: BroadcastInfo) -> bool:
        """解绑当前用户的Java版玩家名（默认行为）"""
        player = self.player_manager.get_player(
            str(broadcast_info.sender_id), platform=broadcast_info.source.origin
        )
        if not player:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_bindings"))]
            )
            return True

        # 检查是否有Java版玩家名
        if not player.java_name:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_bindings"))]
            )
            return True

        # 从白名单中删除玩家名（转换为字符串）
        self._remove_from_whitelist([str(name) for name in player.java_name])

        # 清空Java版玩家名列表
        player.java_name.clear()
        self.player_manager.save()
        await self._clean_bound(player, self.player_manager)
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("unbind_success"))]
        )
        return True

    async def _unbind_bedrock_only(self, broadcast_info: BroadcastInfo) -> bool:
        """解绑当前用户的所有基岩版玩家名"""
        player = self.player_manager.get_player(broadcast_info.sender_id)
        if not player:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_bindings"))]
            )
            return True

        # 检查是否有基岩版玩家名
        if not player.bedrock_name:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_bindings"))]
            )
            return True

        # 从白名单中删除玩家名（转换为字符串）
        self._remove_from_whitelist([str(name) for name in player.bedrock_name])

        # 清空基岩版玩家名列表
        player.bedrock_name.clear()
        self.player_manager.save()
        await self._clean_bound(player, self.player_manager)
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("unbind_success"))]
        )
        return True

    async def _unbind_specific_player(
            self, broadcast_info: BroadcastInfo, player_name: str, is_bedrock: bool = False
    ) -> bool:
        """解绑指定玩家"""
        player = self.player_manager.get_player(player_name)
        if not player:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("player_not_found"))]
            )
            return True

        is_admin = broadcast_info.is_admin
        # 检查是否是绑定玩家
        if not is_admin and broadcast_info.sender_id not in player.accounts.get(
                broadcast_info.source.origin, []
        ):
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_bindings"))]
            )
            return True

        # 根据基岩版参数选择性解绑
        if is_bedrock:
            # 只解绑基岩版玩家名（转换为字符串进行比较）
            bedrock_names_str = [str(name) for name in player.bedrock_name]
            if player_name in bedrock_names_str:
                # 从白名单中删除玩家名
                self._remove_from_whitelist(player_name)

                player.bedrock_name.remove(player_name)
                await self._clean_bound(player, self.player_manager)
                await self.reply(
                    broadcast_info, [MessageBuilder.text(self.get_tr("unbind_success"))]
                )
                return True
            else:
                await self.reply(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("player_not_found"))],
                )
                return True
        else:
            # 只解绑Java版玩家名（转换为字符串进行比较）
            java_names_str = [str(name) for name in player.java_name]
            if player_name in java_names_str:
                # 从白名单中删除玩家名
                self._remove_from_whitelist(player_name)

                player.java_name.remove(player_name)
                await self._clean_bound(player, self.player_manager)
                await self.reply(
                    broadcast_info, [MessageBuilder.text(self.get_tr("unbind_success"))]
                )
                return True
            else:
                await self.reply(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("player_not_found"))],
                )
                return True

    def _remove_from_whitelist(self, player_names: Union[str, List[str]]) -> None:
        """从白名单中删除玩家名的辅助函数

        Parameters
        ----------
        player_names : Union[str, List[str]]
            要删除的玩家名，可以是单个字符串或字符串列表
        """
        if (
                not self.config.get("system", {})
                        .get("bound", {})
                        .get("whitelist_remove_with_leave", False)
                or not self.whitelist
        ):
            return

        # 统一转换为列表处理
        if isinstance(player_names, str):
            player_names = [player_names]

        for name in player_names:
            self.whitelist.remove_player(name)

    async def _get_member_in_all_groups(self) -> set:
        """获取所有群（包括普通群和管理群）中的成员ID集合

        Returns
        -------
        set
            所有群成员的QQ ID集合
        """
        member_id_set = set()

        # 获取配置中的群ID列表
        group_ids = self.config.get_keys(
            ["connector", "QQ", "permissions", "group_ids"], []
        )
        admin_group_ids = self.config.get_keys(
            ["connector", "QQ", "permissions", "admin_group_ids"], []
        )

        # 合并所有群ID
        all_group_ids = set(group_ids + admin_group_ids)

        if not all_group_ids:
            return member_id_set

        # 获取QQ连接器
        try:
            qq_connector = self.system_manager.connector_manager.get_connector("QQ")
            if not qq_connector or not qq_connector.bot:
                return member_id_set

            # 遍历所有群，获取成员列表
            for group_id in all_group_ids:
                if not group_id:
                    continue
                try:
                    member_list_result = await qq_connector.bot.get_group_member_list(
                        group_id=int(group_id)
                    )
                    if member_list_result and member_list_result.get("status") == "ok":
                        members = member_list_result.get("data", [])
                        for member in members:
                            user_id = str(member.get("user_id", ""))
                            if user_id:
                                member_id_set.add(user_id)
                except Exception as e:
                    self.logger.error(f"获取群 {group_id} 成员列表失败: {e}")
                    continue
        except Exception as e:
            self.logger.error(f"获取群成员列表失败: {e}")

        return member_id_set

    async def _send_quit_notification_to_admin_groups(
            self, user_id: str, group_id: str, player: Optional[Player] = None
    ) -> None:
        """向管理群发送退群通知

        Parameters
        ----------
        user_id : str
            退群用户的QQ号
        group_id : str
            退群的群号
        player : Optional[Player]
            退群用户的绑定信息，如果为None则不包含绑定信息
        """
        try:
            # 获取管理群ID列表
            admin_group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "admin_group_ids"], []
            )
            if not admin_group_ids:
                return

            # 构建通知消息
            notification_parts = [f"群 {group_id} 有成员退群"]
            notification_parts.append(f"QQ号: {user_id}")

            if player:
                # 获取所有绑定的玩家名，并区分 Java 与基岩
                java_names = [str(name) for name in player.java_name]
                bedrock_names = [str(name) for name in player.bedrock_name]
                if java_names or bedrock_names:
                    if java_names:
                        java_str = "Java: " + ", ".join(java_names)
                        notification_parts.append(f"绑定玩家({java_str})")
                    if bedrock_names:
                        bedrock_str = "基岩: " + ", ".join(bedrock_names)
                        notification_parts.append(f"绑定玩家({bedrock_str})")
                else:
                    notification_parts.append("未绑定玩家")
            else:
                notification_parts.append("未绑定玩家")

            notification_msg = "\n".join(notification_parts)

            # 获取QQ连接器
            qq_connector = self.system_manager.connector_manager.get_connector("QQ")
            if not qq_connector or not qq_connector.bot:
                return

            # 向所有管理群发送通知
            for admin_group_id in admin_group_ids:
                if not admin_group_id:
                    continue
                try:
                    await qq_connector.bot.send_group_msg(
                        group_id=int(admin_group_id),
                        message=[MessageBuilder.text(notification_msg)],
                    )
                except Exception as e:
                    self.logger.error(
                        f"发送退群通知到管理群 {admin_group_id} 失败: {e}"
                    )
        except Exception as e:
            self.logger.error(f"发送退群通知失败: {e}")

    async def _handle_quit_member(self, broadcast_info: BroadcastInfo) -> bool:
        """处理退群事件

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            退群事件信息

        Returns
        -------
        bool
            是否处理了该事件
        """
        try:
            # 从 raw 中获取退群用户信息
            raw_data = broadcast_info.raw
            if not isinstance(raw_data, dict):
                return False

            user_id = str(raw_data.get("user_id", ""))
            group_id = str(raw_data.get("group_id", ""))

            if not user_id or not group_id:
                return False

            # 判断退群的群是否是普通群（不是管理群）
            group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "group_ids"], []
            )
            admin_group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "admin_group_ids"], []
            )

            is_normal_group = str(group_id) in [str(gid) for gid in group_ids if gid]
            is_admin_group = str(group_id) in [
                str(gid) for gid in admin_group_ids if gid
            ]

            # 获取该用户的绑定信息
            player = self.player_manager.get_player(user_id, platform="QQ")

            # 如果退群的是普通群，发送通知到管理群
            if is_normal_group and not is_admin_group:
                await self._send_quit_notification_to_admin_groups(
                    user_id, group_id, player
                )

            # 检查该用户是否还在其他群中
            all_member_ids = await self._get_member_in_all_groups()

            # 如果用户不在任何群中，执行清理
            if user_id not in all_member_ids and player:
                # 获取所有玩家名（转换为字符串）
                all_player_names = [str(name) for name in player.java_name] + [
                    str(name) for name in player.bedrock_name
                ]

                # 从白名单中移除玩家名
                if all_player_names:
                    self._remove_from_whitelist(all_player_names)

                # 检查该用户是否还有其他平台的账户绑定
                has_other_platform_accounts = False
                for platform, accounts in player.accounts.items():
                    if platform != "QQ" and accounts:
                        has_other_platform_accounts = True
                        break

                # 从绑定数据中删除该用户的QQ账户绑定
                if "QQ" in player.accounts and user_id in player.accounts["QQ"]:
                    player.accounts["QQ"].remove(user_id)
                    # 如果QQ账户列表为空，删除该平台
                    if not player.accounts["QQ"]:
                        del player.accounts["QQ"]

                # 如果该用户没有其他平台的账户绑定，删除整个 Player（包括所有玩家名）
                # 参考 bound_system.py 的逻辑：退群时删除整个绑定
                if not has_other_platform_accounts:
                    self.player_manager.remove_player(player.name)
                else:
                    # 如果还有其他平台的账户，只删除QQ账户绑定，保留玩家名和其他平台绑定
                    self.player_manager.save()

                self.logger.info(f"已清理退群用户 {user_id} 的绑定信息")
                return True

            return False
        except Exception as e:
            self.logger.error(f"处理退群事件失败: {e}")
            return False

    async def _clean_bound(self, player: Player, player_manager: PlayerManager) -> bool:
        """清理绑定"""
        if not player.java_name and not player.bedrock_name:
            player_manager.remove_player(player.name)

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理显示绑定列表命令"""
        # 管理员查看所有人的绑定列表
        if broadcast_info.is_admin:
            return await self._handle_list_all(broadcast_info)

        player = self.player_manager.get_player(broadcast_info.sender_id)
        if not player:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_bindings"))]
            )
            return True

        # 获取所有绑定的玩家名
        bound_players = []
        for platform, accounts in player.accounts.items():
            if platform == "qq":
                continue
            bound_players.extend(accounts)

        if not bound_players:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_bindings"))]
            )
            return True

        player_list = "\n".join(
            f"{i + 1}. {name}" for i, name in enumerate(bound_players)
        )
        await self.reply(
            broadcast_info,
            [MessageBuilder.text(self.get_tr("bind_list", player_list=player_list))],
        )
        return True

    async def _handle_list_all(self, broadcast_info: BroadcastInfo) -> bool:
        """管理员查看所有玩家的绑定列表"""
        all_players = self.player_manager.get_all_players()
        if not all_players:
            await self.reply(
                broadcast_info, [MessageBuilder.text("当前没有任何绑定信息")]
            )
            return True

        reply_lines = [f"绑定列表 (共{len(all_players)}人):"]
        for i, player in enumerate(all_players, 1):
            # 收集玩家名
            java_names = [str(name) for name in player.java_name]
            bedrock_names = [str(name) for name in player.bedrock_name]

            # 收集平台账号
            account_parts = []
            for platform, accounts in player.accounts.items():
                account_ids = ", ".join(str(a) for a in accounts)
                account_parts.append(f"{platform}: {account_ids}")

            # 拼接每行信息
            line = f"{i}. "
            name_parts = []
            if java_names:
                name_parts.append("Java: " + ", ".join(java_names))
            if bedrock_names:
                name_parts.append("基岩: " + ", ".join(bedrock_names))
            line += " | ".join(name_parts) if name_parts else "无游戏名"

            if account_parts:
                line += f" [{' | '.join(account_parts)}]"

            reply_lines.append(line)

        await self.reply(
            broadcast_info, [MessageBuilder.text("\n".join(reply_lines))]
        )
        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """绑定指令帮助"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        bind_cmd = self.get_tr("bind")
        unbind_cmd = self.get_tr("unbind")
        list_cmd = self.get_tr("list")

        # 根据用户权限选择不同的帮助信息
        if broadcast_info.is_admin:
            enable_cmd = self.get_tr("gugubot.enable", global_key=True)
            disable_cmd = self.get_tr("gugubot.disable", global_key=True)
            help_msg = self.get_tr(
                "help_msg",
                command_prefix=command_prefix,
                name=system_name,
                enable=enable_cmd,
                disable=disable_cmd,
                bind=bind_cmd,
                unbind=unbind_cmd,
                list=list_cmd,
            )
        else:
            help_msg = self.get_tr(
                "user_help_msg",
                command_prefix=command_prefix,
                name=system_name,
                bind=bind_cmd,
                unbind=unbind_cmd,
                list=list_cmd,
            )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True

    def get_player_by_qq_id(self, qq_id: str) -> Optional[Player]:
        """通过QQ ID获取玩家信息"""
        return self.player_manager.get_player(qq_id)

    def get_player_by_name(self, player_name: str) -> Optional[Player]:
        """通过玩家名获取玩家信息"""
        return self.player_manager.get_player(player_name)

    ############################################################## 白名单检查 ##############################################################

    def _get_unbound_whitelist(self) -> List[tuple]:
        """获取白名单中未绑定的玩家

        Returns
        -------
        List[tuple]
            未绑定的玩家列表，元组格式: (uuid, player_name)
        """
        if not self.whitelist:
            return []

        result = []

        # 获取所有已绑定的玩家名（转小写以便比较）
        all_bound_player_names = set()
        for player in self.player_manager.get_all_players():
            all_bound_player_names.update(
                [str(name).lower() for name in player.java_name]
            )
            all_bound_player_names.update(
                [str(name).lower() for name in player.bedrock_name]
            )

        # 检查白名单中的玩家是否在绑定列表中
        for whitelist_player in self.whitelist._api.get_whitelist():
            if whitelist_player.name.lower() not in all_bound_player_names:
                result.append((whitelist_player.uuid, whitelist_player.name))

        return result

    async def _handle_check_whitelist(self, broadcast_info: BroadcastInfo) -> bool:
        """处理白名单检查命令

        检查白名单中有哪些玩家未绑定
        """
        if not self.whitelist:
            await self.reply(broadcast_info, [MessageBuilder.text("白名单系统未启用")])
            return True

        result = self._get_unbound_whitelist()

        if not result:
            await self.reply(
                broadcast_info, [MessageBuilder.text("白名单检查: 所有玩家都已绑定~")]
            )
            return True

        reply_msg = ["白名单检查:"]
        for uuid, player_name in result:
            reply_msg.append(f"{player_name}({uuid}) 未绑定")

        await self.reply(broadcast_info, [MessageBuilder.text("\n".join(reply_msg))])
        return True

    async def _handle_remove_unbound_whitelist(
            self, broadcast_info: BroadcastInfo
    ) -> bool:
        """处理移除未绑定白名单命令

        从白名单中移除所有未绑定的玩家
        """
        if not self.whitelist:
            await self.reply(broadcast_info, [MessageBuilder.text("白名单系统未启用")])
            return True

        result = self._get_unbound_whitelist()

        if not result:
            await self.reply(
                broadcast_info, [MessageBuilder.text("没有未绑定的白名单成员~")]
            )
            return True

        reply_msg = ["已将未绑定的白名单成员移除:"]
        for uuid, player_name in result:
            self.whitelist.remove_player(player_name)
            reply_msg.append(f"{player_name}({uuid}) 已从白名单中移除")

        await self.reply(broadcast_info, [MessageBuilder.text("\n".join(reply_msg))])
        return True

    ############################################################## 多余绑定检查 ##############################################################

    async def _get_extra_bound_member(self) -> List[tuple]:
        """获取不在群里的多余绑定成员

        Returns
        -------
        List[tuple]
            多余绑定成员列表，元组格式: (qq_id, player_names)
        """
        extra_bound_members = []

        # 获取所有群成员ID
        all_member_ids = await self._get_member_in_all_groups()

        # 检查每个绑定的QQ账号是否还在群中
        for player in self.player_manager.get_all_players():
            qq_accounts = player.accounts.get("QQ", [])
            for qq_id in qq_accounts:
                if qq_id not in all_member_ids:
                    # 获取该QQ绑定的所有玩家名（转换为字符串）
                    player_names = [str(name) for name in player.java_name] + [
                        str(name) for name in player.bedrock_name
                    ]
                    extra_bound_members.append((qq_id, player_names))

        return extra_bound_members

    async def _handle_check_extra_bound(self, broadcast_info: BroadcastInfo) -> bool:
        """处理多余绑定检查命令

        检查有哪些绑定的用户不在群里
        """
        result = await self._get_extra_bound_member()

        if not result:
            await self.reply(
                broadcast_info, [MessageBuilder.text("多余绑定检查: 绑定成员都在群里~")]
            )
            return True

        reply_msg = ["多余绑定检查:"]
        for qq_id, player_names in result:
            player_name_str = ", ".join(player_names)
            reply_msg.append(f"{qq_id}({player_name_str}) 未在群里")

        await self.reply(broadcast_info, [MessageBuilder.text("\n".join(reply_msg))])
        return True

    async def _handle_remove_extra_bound(self, broadcast_info: BroadcastInfo) -> bool:
        """处理移除多余绑定命令

        移除所有不在群里的绑定成员
        """
        result = await self._get_extra_bound_member()

        if not result:
            await self.reply(broadcast_info, [MessageBuilder.text("绑定成员都在群里~")])
            return True

        reply_msg = ["已将多余已绑定成员移除:"]
        for qq_id, player_names in result:
            # 从白名单中移除玩家名
            if player_names:
                self._remove_from_whitelist(player_names)

            # 从绑定数据中移除该QQ账号
            # 由于新架构中是以玩家为中心，需要找到对应的玩家并移除QQ账号绑定
            for player in self.player_manager.get_all_players():
                if "QQ" in player.accounts and qq_id in player.accounts["QQ"]:
                    player.accounts["QQ"].remove(qq_id)
                    # 如果QQ账户列表为空，删除该平台
                    if not player.accounts["QQ"]:
                        del player.accounts["QQ"]

                    # 如果该玩家没有任何平台绑定了，删除整个玩家
                    has_any_account = any(
                        accounts for accounts in player.accounts.values() if accounts
                    )
                    if not has_any_account:
                        self.player_manager.remove_player(player.name)
                    break

            self.player_manager.save()

            player_name_str = ", ".join(player_names)
            reply_msg.append(f"{qq_id}({player_name_str}) 已从绑定中移除")

        await self.reply(broadcast_info, [MessageBuilder.text("\n".join(reply_msg))])
        return True
