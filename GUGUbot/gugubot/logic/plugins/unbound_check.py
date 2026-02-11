# -*- coding: utf-8 -*-
"""未绑定用户检查插件模块。

该模块提供检查QQ群中未绑定用户的功能，支持定时自动检查和手动命令触发。
"""

import asyncio
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BasicConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class UnboundCheckSystem(BasicConfig, BasicSystem):
    """未绑定用户检查系统，用于检查和提醒QQ群中未绑定的用户。

    提供定时自动检查和手动触发检查功能。
    """

    def __init__(self, server: PluginServerInterface, config=None) -> None:
        """初始化未绑定用户检查系统。"""
        BasicSystem.__init__(self, "unbound_check", enable=False, config=config)
        self.server = server

        # 设置数据文件路径
        data_path = Path(server.get_data_folder()) / "plugins" / "unbound_check.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, data_path)

        # 系统依赖
        self.bound_system = None
        self.qq_connector = None

        # 检查状态
        self._checking = False
        self._schedule_task_running = True  # 控制定时任务的运行

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        # 从配置文件加载数据
        self.load()

        # 如果没有上次检查时间，初始化为0
        if "last_check_time" not in self:
            self["last_check_time"] = 0
            self.save()

        last_check_time = self.get("last_check_time", 0)
        if last_check_time > 0:
            last_check_str = datetime.fromtimestamp(last_check_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self.logger.info(f"未绑定检查系统已加载，上次检查时间: {last_check_str}")
        else:
            self.logger.info("未绑定检查系统已加载，尚未进行过检查")

        # 启动定时检查任务
        self.server.schedule_task(self._schedule_check())

    def set_bound_system(self, bound_system) -> None:
        """设置绑定系统引用"""
        self.bound_system = bound_system

    def set_qq_connector(self, qq_connector) -> None:
        """设置QQ连接器引用"""
        self.qq_connector = qq_connector

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
        """处理未绑定检查相关命令"""

        if not broadcast_info.is_admin:
            return False

        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        valid_commands = [system_name, self.get_tr("check"), self.get_tr("next")]
        if not any(command.startswith(i) for i in valid_commands):
            return False

        command = command.replace(system_name, "", 1).strip()

        if command.startswith(self.get_tr("check")):
            return await self._handle_check(broadcast_info)
        elif command.startswith(self.get_tr("next")):
            return await self._handle_next(broadcast_info)

        return await self._handle_help(broadcast_info)

    async def _handle_check(self, broadcast_info: BroadcastInfo) -> bool:
        """处理手动检查命令（仅管理员）"""
        # 检查是否正在检查中
        if self._checking:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("checking"))]
            )
            return True

        # 检查依赖
        if not self.qq_connector:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("qq_connector_not_found"))],
            )
            return True

        if not self.bound_system:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("bound_system_not_found"))],
            )
            return True

        # 开始检查
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("check_start"))]
        )

        # 执行检查
        unbound_users_dict = await self._check_unbound_users()

        # 发送通知
        if unbound_users_dict:
            await self._send_notification(unbound_users_dict)

            # 统计总数
            total_count = sum(len(users) for users in unbound_users_dict.values())
            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr("check_complete", total_count=total_count)
                    )
                ],
            )
        else:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("no_unbound_users"))]
            )

        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("manual_check_success"))]
        )
        return True

    async def _handle_next(self, broadcast_info: BroadcastInfo) -> bool:
        """处理查看下次检查时间命令"""
        last_check_time = self.get("last_check_time", 0)
        check_interval = self.config.get_keys(
            ["system", "unbound_check", "check_interval"], 86400
        )
        next_check_time = last_check_time + check_interval

        next_check_str = datetime.fromtimestamp(next_check_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        await self.reply(
            broadcast_info,
            [MessageBuilder.text(self.get_tr("next_check_time", time=next_check_str))],
        )
        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """未绑定检查指令帮助"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        enable_cmd = self.get_tr("gugubot.enable", global_key=True)
        disable_cmd = self.get_tr("gugubot.disable", global_key=True)
        check_cmd = self.get_tr("check")
        next_cmd = self.get_tr("next")

        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=system_name,
            enable=enable_cmd,
            disable=disable_cmd,
            check=check_cmd,
            next=next_cmd,
        )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True

    async def _check_unbound_users(self) -> Dict[int, List[Dict]]:
        """检查未绑定用户的核心逻辑

        Returns
        -------
        Dict[int, List[Dict]]
            字典，key为群号，value为未绑定用户列表
        """
        self._checking = True
        unbound_users_dict = {}

        try:
            # 获取配置
            group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "group_ids"], []
            )
            timeout_days = self.config.get_keys(
                ["system", "unbound_check", "timeout_days"], 7
            )
            timeout_seconds = timeout_days * 86400
            current_time = time.time()
            QQ_connector_name = self.config.get_keys(
                ["connector", "QQ", "source_name"], "QQ"
            )

            # 获取管理员ID列表（用于跳过管理员）
            admin_ids = set(
                str(admin_id)
                for admin_id in self.config.get_keys(
                    ["connector", "QQ", "permissions", "admin_ids"], []
                )
            )

            # 获取管理群成员ID列表（通过API获取管理群的所有成员）
            admin_group_member_ids = set()
            admin_group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "admin_group_ids"], []
            )
            for admin_group_id in admin_group_ids:
                if not admin_group_id:
                    continue
                try:
                    member_list_result = (
                        await self.qq_connector.bot.get_group_member_list(
                            group_id=int(admin_group_id)
                        )
                    )
                    if member_list_result and member_list_result.get("status") == "ok":
                        members = member_list_result.get("data", [])
                        for member in members:
                            user_id = str(member.get("user_id", ""))
                            if user_id:
                                admin_group_member_ids.add(user_id)
                        self.logger.debug(
                            f"从管理群 {admin_group_id} 获取到 {len(members)} 名成员"
                        )
                except Exception as e:
                    self.logger.warning(
                        f"获取管理群 {admin_group_id} 成员列表失败: {e}"
                    )

            # 合并管理员ID和管理群成员ID
            skip_user_ids = admin_ids | admin_group_member_ids

            # 遍历每个群
            for group_id in group_ids:
                try:
                    # 获取群成员列表
                    member_list_result = (
                        await self.qq_connector.bot.get_group_member_list(
                            group_id=int(group_id)
                        )
                    )

                    if (
                            not member_list_result
                            or member_list_result.get("status") != "ok"
                    ):
                        self.logger.warning(f"获取群 {group_id} 成员列表失败")
                        continue

                    members = member_list_result.get("data", [])
                    unbound_users = []

                    # 检查每个成员
                    for member in members:
                        user_id = str(member.get("user_id", ""))
                        join_time = member.get("join_time", 0)
                        nickname = member.get("nickname", "未知")

                        # 检查是否是管理员或在管理群中，如果是则跳过
                        if user_id in skip_user_ids:
                            continue

                        # 检查是否超时
                        if current_time - join_time <= timeout_seconds:
                            continue

                        # 检查是否已绑定
                        player = self.bound_system.player_manager.get_player(
                            user_id, platform=QQ_connector_name
                        )
                        if not player:
                            # 未绑定且超时
                            days_ago = int((current_time - join_time) / 86400)
                            unbound_users.append(
                                {
                                    "user_id": user_id,
                                    "nickname": nickname,
                                    "join_time": join_time,
                                    "days_ago": days_ago,
                                }
                            )

                    if unbound_users:
                        unbound_users_dict[group_id] = unbound_users
                        self.logger.info(
                            f"群 {group_id} 发现 {len(unbound_users)} 名未绑定用户"
                        )

                except Exception as e:
                    error_msg = str(e) + "\n" + traceback.format_exc()
                    self.logger.error(f"检查群 {group_id} 时出错: {error_msg}")
                    continue

            # 更新最后检查时间
            self["last_check_time"] = int(current_time)
            self.save()

        finally:
            self._checking = False

        return unbound_users_dict

    async def _send_notification(
            self, unbound_users_dict: Dict[int, List[Dict]]
    ) -> None:
        """发送通知到配置的目标

        Parameters
        ----------
        unbound_users_dict : Dict[int, List[Dict]]
            未绑定用户字典，key为群号，value为用户列表
        """
        # 获取配置
        notify_targets = self.config.get_keys(
            ["system", "unbound_check", "notify_targets"], {}
        )
        admin_private = notify_targets.get("admin_private", True)
        admin_groups = notify_targets.get("admin_groups", True)
        origin_group = notify_targets.get("origin_group", False)

        timeout_days = self.config.get_keys(
            ["system", "unbound_check", "timeout_days"], 7
        )

        # 构建通知消息
        for group_id, unbound_users in unbound_users_dict.items():
            try:
                # 获取群信息
                group_info_result = await self.qq_connector.bot.get_group_info(
                    group_id=int(group_id)
                )
                group_name = "未知群"
                if group_info_result and group_info_result.get("status") == "ok":
                    group_name = group_info_result.get("data", {}).get(
                        "group_name", "未知群"
                    )

                # 构建用户列表
                user_list = []
                for user in unbound_users:
                    user_item = self.get_tr(
                        "user_item",
                        nickname=user["nickname"],
                        user_id=user["user_id"],
                        days_ago=user["days_ago"],
                    )
                    user_list.append(user_item)
                user_list_str = "\n".join(user_list)

                # 构建完整消息
                notification_msg = (
                        self.get_tr("notification_title")
                        + "\n"
                        + self.get_tr(
                    "notification_group",
                    group_name=group_name,
                    group_id=group_id,
                    count=len(unbound_users),
                    days=timeout_days,
                    user_list=user_list_str,
                )
                )

                # 发送到私聊管理员
                if admin_private:
                    admin_ids = self.config.get_keys(
                        ["connector", "QQ", "permissions", "admin_ids"], []
                    )
                    for admin_id in admin_ids:
                        if not admin_id:
                            continue
                        try:
                            await self.qq_connector.bot.send_private_msg(
                                user_id=int(admin_id),
                                message=[MessageBuilder.text(notification_msg)],
                            )
                        except Exception as e:
                            error_msg = str(e) + "\n" + traceback.format_exc()
                            self.logger.error(
                                f"发送私聊消息到管理员 {admin_id} 失败: {error_msg}"
                            )

                # 发送到管理群
                if admin_groups:
                    admin_group_ids = self.config.get_keys(
                        ["connector", "QQ", "permissions", "admin_group_ids"], []
                    )
                    for admin_group_id in admin_group_ids:
                        if not admin_group_id:
                            continue
                        try:
                            await self.qq_connector.bot.send_group_msg(
                                group_id=int(admin_group_id),
                                message=[MessageBuilder.text(notification_msg)],
                            )
                        except Exception as e:
                            error_msg = str(e) + "\n" + traceback.format_exc()
                            self.logger.error(
                                f"发送消息到管理群 {admin_group_id} 失败: {error_msg}"
                            )

                # 发送到原群
                if origin_group:
                    try:
                        await self.qq_connector.bot.send_group_msg(
                            group_id=int(group_id),
                            message=[MessageBuilder.text(notification_msg)],
                        )
                    except Exception as e:
                        error_msg = str(e) + "\n" + traceback.format_exc()
                        self.logger.error(
                            f"发送消息到原群 {group_id} 失败: {error_msg}"
                        )

            except Exception as e:
                error_msg = str(e) + "\n" + traceback.format_exc()
                self.logger.error(f"发送通知时出错: {error_msg}")

    async def _schedule_check(self) -> None:
        """定时检查任务"""
        self.logger.info("未绑定检查定时任务已启动")

        while self._schedule_task_running:
            try:
                # 读取配置
                last_check_time = self.get("last_check_time", 0)
                check_interval = self.config.get_keys(
                    ["system", "unbound_check", "check_interval"], 86400
                )

                # 计算下次检查时间
                next_check_time = last_check_time + check_interval
                current_time = time.time()
                wait_time = max(0, next_check_time - current_time)

                # 记录下次检查时间
                if wait_time > 0:
                    next_check_str = datetime.fromtimestamp(next_check_time).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.logger.debug(f"下次检查时间: {next_check_str}")

                # 等待到下次检查时间（分割成小段以便快速响应停止信号）
                while wait_time > 0 and self._schedule_task_running:
                    sleep_time = min(wait_time, 1.0)  # 每次最多睡眠1秒
                    await asyncio.sleep(sleep_time)
                    wait_time -= sleep_time

                if not self._schedule_task_running:
                    break

                # 检查系统是否已启用
                if not self.enable:
                    self.logger.debug("系统未启用，跳过本次检查")
                    # 更新检查时间，避免重复检查
                    self["last_check_time"] = int(time.time())
                    self.save()
                    continue

                # 检查依赖
                if not self.qq_connector or not self.bound_system:
                    self.logger.warning("依赖系统未初始化，跳过本次检查")
                    continue

                # 执行检查
                self.logger.info("开始定时检查未绑定用户...")
                unbound_users_dict = await self._check_unbound_users()

                # 发送通知
                if unbound_users_dict:
                    await self._send_notification(unbound_users_dict)
                    total_count = sum(
                        len(users) for users in unbound_users_dict.values()
                    )
                    self.logger.info(f"定时检查完成，共发现 {total_count} 名未绑定用户")
                else:
                    self.logger.info("定时检查完成，所有群成员均已绑定")

            except Exception as e:
                self.logger.error(f"定时检查任务出错: {e}")
                # 出错后等待一段时间再继续（分割成小段以便快速响应停止信号）
                for _ in range(60):
                    if not self._schedule_task_running:
                        break
                    await asyncio.sleep(1.0)

        self.logger.info("未绑定检查定时任务已停止")

    def stop_schedule_task(self) -> None:
        """停止定时检查任务"""
        self._schedule_task_running = False
        self.logger.info("正在停止未绑定检查定时任务...")
