# -*- coding: utf-8 -*-
"""不活跃用户检查插件模块。

该模块提供检查QQ绑定玩家长期未登录游戏的功能，支持定时自动检查和手动命令触发。
同时检查群名片是否为第一个Java或基岩版游戏名，并支持自动修复不匹配的群名片。
"""

import asyncio
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BasicConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class InactiveCheckSystem(BasicConfig, BasicSystem):
    """不活跃用户检查系统，用于检查和提醒QQ绑定玩家长期未登录。

    提供定时自动检查和手动触发检查功能。
    同时检查群名片是否为第一个Java或基岩版游戏名，支持自动修复不匹配的群名片。
    """

    def __init__(self, server: PluginServerInterface, config=None) -> None:
        """初始化不活跃用户检查系统。"""
        BasicSystem.__init__(self, "inactive_check", enable=False, config=config)
        self.server = server
        self.logger = server.logger

        # 设置数据文件路径
        data_path = Path(server.get_data_folder()) / "plugins" / "inactive_check.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, data_path)

        # 系统依赖
        self.bound_system = None
        self.qq_connector = None
        self.whitelist_system = None
        self.active_whitelist_system = None  # 活跃白名单系统，用于过滤玩家

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

        # 初始化基岩版玩家 API 数据缓存
        if "bedrock_cache" not in self:
            self["bedrock_cache"] = {}

        # 初始化 QQ号 -> 最后游玩时间的映射（用于追踪改ID的玩家）
        if "qq_last_play_time" not in self:
            self["qq_last_play_time"] = {}

        self.save()

        last_check_time = self.get("last_check_time", 0)
        if last_check_time > 0:
            last_check_str = datetime.fromtimestamp(last_check_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self.logger.info(f"不活跃检查系统已加载，上次检查时间: {last_check_str}")
        else:
            self.logger.info("不活跃检查系统已加载，尚未进行过检查")

        # 统计缓存数据
        cache_count = len(self.get("bedrock_cache", {}))
        if cache_count > 0:
            self.logger.debug(f"已加载 {cache_count} 个基岩版玩家的 API 缓存数据")

        # 启动定时检查任务
        self.server.schedule_task(self._schedule_check())

    def set_bound_system(self, bound_system) -> None:
        """设置绑定系统引用"""
        self.bound_system = bound_system

    def set_qq_connector(self, qq_connector) -> None:
        """设置QQ连接器引用"""
        self.qq_connector = qq_connector

    def set_whitelist_system(self, whitelist_system) -> None:
        """设置白名单系统引用"""
        self.whitelist_system = whitelist_system

    def set_active_whitelist_system(self, active_whitelist_system) -> None:
        """设置活跃白名单系统引用"""
        self.active_whitelist_system = active_whitelist_system

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
        """处理不活跃检查相关命令"""

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

        if not self.whitelist_system or not self.whitelist_system._api:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("whitelist_not_found"))],
            )
            return True

        # 开始检查
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("check_start"))]
        )

        # 执行检查
        inactive_players_dict = await self._check_inactive_players()

        # 发送通知
        if inactive_players_dict:
            await self._send_notification(inactive_players_dict)

            # 统计总数（包括不活跃和从未进入游戏的玩家）
            total_inactive = sum(
                len(data.get("inactive", [])) for data in inactive_players_dict.values()
            )
            total_never_played = sum(
                len(data.get("never_played", []))
                for data in inactive_players_dict.values()
            )
            total_count = total_inactive + total_never_played

            await self.reply(
                broadcast_info,
                [
                    MessageBuilder.text(
                        self.get_tr(
                            "check_complete",
                            total_count=total_count,
                            inactive_count=total_inactive,
                            never_played_count=total_never_played,
                        )
                    )
                ],
            )
        else:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("no_inactive_players"))],
            )

        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("manual_check_success"))]
        )
        return True

    async def _handle_next(self, broadcast_info: BroadcastInfo) -> bool:
        """处理查看下次检查时间命令"""
        last_check_time = self.get("last_check_time", 0)
        check_interval = self.config.get_keys(
            ["system", "inactive_check", "check_interval"], 86400
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
        """不活跃检查指令帮助"""
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

    def _get_player_uuid(self, player_name: str) -> Optional[str]:
        """通过玩家名获取UUID

        Parameters
        ----------
        player_name : str
            玩家名

        Returns
        -------
        Optional[str]
            玩家UUID，如果未找到则返回None
        """
        if not self.whitelist_system or not self.whitelist_system._api:
            return None

        try:
            whitelist = self.whitelist_system._api.get_whitelist()
            for player_info in whitelist:
                if player_info.name.lower() == player_name.lower():
                    return player_info.uuid
        except Exception as e:
            self.logger.error(f"获取玩家 {player_name} 的UUID失败: {e}")

        return None

    def _get_bedrock_player_uuid(self, player_name: str) -> Optional[str]:
        """通过 MCProfile.io API 获取基岩版玩家的 UUID（XUID 或 Floodgate UUID）

        使用缓存机制，避免频繁调用 API。

        Parameters
        ----------
        player_name : str
            基岩版玩家名 (gamertag)

        Returns
        -------
        Optional[str]
            玩家 UUID（优先返回 Floodgate UUID，如果没有则返回 XUID），如果获取失败则返回None
        """
        # 获取缓存配置（默认缓存 6 个月，因为 UUID 不会经常变化）
        # 6 个月 = 180 天 = 15,552,000 秒
        cache_ttl = self.config.get_keys(
            ["system", "inactive_check", "bedrock_cache_ttl"], 15552000
        )

        # 检查缓存
        bedrock_cache = self.get("bedrock_cache", {})
        player_name_lower = player_name.lower()

        if player_name_lower in bedrock_cache:
            cache_data = bedrock_cache[player_name_lower]
            cached_at = cache_data.get("cached_at", 0)
            current_time = time.time()

            # 检查缓存是否过期
            if (current_time - cached_at) < cache_ttl:
                # 缓存有效，直接返回
                uuid = cache_data.get("uuid")
                if uuid:
                    self.logger.debug(
                        f"使用缓存的基岩版玩家 {player_name} 的 UUID: {uuid}"
                    )
                    return uuid
                else:
                    # 缓存中标记为 None（之前查询失败），也直接返回 None
                    self.logger.debug(
                        f"使用缓存的基岩版玩家 {player_name} 的查询结果（无 UUID）"
                    )
                    return None
            else:
                # 缓存已过期，删除旧缓存
                self.logger.debug(f"基岩版玩家 {player_name} 的缓存已过期，将重新获取")
                del bedrock_cache[player_name_lower]
                # 更新缓存字典以触发保存
                self["bedrock_cache"] = bedrock_cache
                self.save()

        # 缓存不存在或已过期，调用 API
        url = f"https://mcprofile.io/api/v1/bedrock/gamertag/{player_name}"

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # 优先使用 Floodgate UUID（用于 Floodgate 服务器）
                uuid = None
                if "floodgateuid" in data and data["floodgateuid"]:
                    uuid = data["floodgateuid"]
                    self.logger.debug(
                        f"获取到基岩版玩家 {player_name} 的 Floodgate UUID: {uuid}"
                    )
                else:
                    self.logger.debug(
                        f"基岩版玩家 {player_name} 的 API 响应中未找到有效的 Floodgate UUID"
                    )
                    return None

                # 保存到缓存
                bedrock_cache[player_name_lower] = {
                    "uuid": uuid,
                    "cached_at": time.time(),
                    "player_name": player_name,  # 保存原始玩家名（大小写）
                }
                self["bedrock_cache"] = bedrock_cache
                self.save()
                if uuid:
                    self.logger.debug(f"已缓存基岩版玩家 {player_name} 的 UUID")
                else:
                    self.logger.debug(
                        f"基岩版玩家 {player_name} 的 API 响应中未找到有效的 UUID"
                    )

                return uuid

            elif response.status_code == 404:
                # 玩家不存在，也记录到缓存（避免重复查询）
                bedrock_cache[player_name_lower] = {
                    "uuid": None,
                    "cached_at": time.time(),
                    "player_name": player_name,
                }
                self["bedrock_cache"] = bedrock_cache
                self.save()
                self.logger.debug(f"基岩版玩家 {player_name} 不存在于 MCProfile.io")
                return None
            else:
                self.logger.warning(
                    f"查询基岩版玩家 {player_name} 信息失败: HTTP {response.status_code}"
                )
                return None

        except requests.exceptions.Timeout:
            self.logger.warning(f"查询基岩版玩家 {player_name} 信息超时")
            return None
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"查询基岩版玩家 {player_name} 信息出错: {e}")
            return None
        except Exception as e:
            self.logger.warning(f"解析基岩版玩家 {player_name} 信息时出错: {e}")
            return None

    async def _check_inactive_players(self) -> Dict[int, Dict[str, List[Dict]]]:
        """检查不活跃玩家的核心逻辑

        Returns
        -------
        Dict[int, Dict[str, List[Dict]]]
            字典，key为群号，value为包含 'inactive' 和 'never_played' 两个键的字典
            'inactive': 进过游戏但长时间未登录的玩家列表
            'never_played': 已绑定但从未进入游戏的玩家列表
        """
        self._checking = True
        inactive_players_dict = {}

        try:
            # 获取配置
            group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "group_ids"], []
            )
            inactive_days = self.config.get_keys(
                ["system", "inactive_check", "inactive_days"], 30
            )
            never_played_days = self.config.get_keys(
                ["system", "inactive_check", "never_played_days"], 7
            )
            inactive_seconds = inactive_days * 86400
            never_played_seconds = never_played_days * 86400
            current_time = time.time()
            QQ_connector_name = self.config.get_keys(
                ["connector", "QQ", "source_name"], "QQ"
            )

            # 获取playerdata目录
            player_data_dir = Path("server/world/playerdata")

            if not player_data_dir.exists():
                self.logger.warning(f"playerdata目录不存在: {player_data_dir}")
                return {}

            # 获取所有玩家
            all_players = self.bound_system.player_manager.get_all_players()

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

            # 遍历每个群，收集该群的不活跃玩家
            for group_id in group_ids:
                inactive_players = []  # 进过游戏但长时间未登录的玩家
                never_played_players = []  # 从未进入游戏的玩家

                # 先获取该群的成员列表（避免重复调用API）
                group_members = {}  # key: user_id, value: member info (包含join_time)
                try:
                    member_list_result = (
                        await self.qq_connector.bot.get_group_member_list(
                            group_id=int(group_id)
                        )
                    )
                    if member_list_result and member_list_result.get("status") == "ok":
                        members = member_list_result.get("data", [])
                        for member in members:
                            user_id = str(member.get("user_id", ""))
                            if user_id:
                                group_members[user_id] = member
                except Exception as e:
                    self.logger.error(f"获取群 {group_id} 成员列表失败: {e}")
                    continue

                # 检查每个玩家
                for player in all_players:
                    # 只检查有QQ绑定的玩家
                    qq_accounts = player.accounts.get(QQ_connector_name, [])
                    if not qq_accounts:
                        continue

                    # 检查玩家是否是管理员或在管理群中，如果是则跳过
                    if any(
                            str(qq_account) in skip_user_ids for qq_account in qq_accounts
                    ):
                        self.logger.debug(
                            f"玩家 {player.name} 是管理员或在管理群中，跳过不活跃检查"
                        )
                        continue

                    # 检查玩家是否在活跃白名单中，如果是则跳过
                    if self.active_whitelist_system:
                        # 检查玩家的所有名称（Java和Bedrock）是否在活跃白名单中
                        player_names = player.java_name + player.bedrock_name
                        if any(
                                self.active_whitelist_system.is_in_whitelist(name)
                                for name in player_names
                        ):
                            self.logger.debug(
                                f"玩家 {player.name} 在活跃白名单中，跳过不活跃检查"
                            )
                            continue

                    # 检查该玩家是否在当前群，并获取进群时间和群名片
                    player_in_group = False
                    join_time = None
                    group_card = None

                    # 检查玩家的任一QQ账号是否在该群
                    for qq_account in qq_accounts:
                        qq_str = str(qq_account)
                        if qq_str in group_members:
                            player_in_group = True
                            # 获取进群时间
                            join_time = group_members[qq_str].get("join_time", 0)
                            # 获取群名片
                            group_card = group_members[qq_str].get("card", "")
                            break

                    if not player_in_group:
                        continue

                    # 检查群名片是否为第一个Java或基岩名字，并自动修改
                    expected_name = None
                    if player.java_name:
                        expected_name = player.java_name[0]
                    elif player.bedrock_name:
                        expected_name = player.bedrock_name[0]

                    # 如果有预期名字，且群名片不匹配，自动修改
                    if expected_name and group_card != expected_name:
                        auto_fix_enabled = self.config.get_keys(
                            ["system", "inactive_check", "auto_fix_card"], True
                        )
                        change_group_card = self.config.get_keys(
                            ["connector", "QQ", "others", "change_group_card"], True
                        )
                        if auto_fix_enabled and change_group_card:
                            try:
                                await self.qq_connector.bot.set_group_card(
                                    group_id=int(group_id),
                                    user_id=int(qq_str),
                                    card=expected_name,
                                )
                            except Exception:
                                pass

                    # 检查玩家的所有UUID对应的playerdata文件，找最新的修改时间
                    latest_mtime = 0
                    found_any_file = False

                    # 先检查基岩版玩家，通过 API 获取 UUID 然后检查本地存档
                    for bedrock_name in player.bedrock_name:
                        uuid = self._get_bedrock_player_uuid(bedrock_name)

                        if uuid:
                            self.logger.debug(
                                f"基岩版玩家 {bedrock_name} 的 UUID: {uuid}"
                            )
                            player_file = player_data_dir / f"{uuid}.dat"
                            if player_file.exists():
                                found_any_file = True
                                mtime = player_file.stat().st_mtime
                                latest_mtime = max(latest_mtime, mtime)
                                self.logger.debug(
                                    f"找到基岩版玩家 {bedrock_name} (UUID: {uuid}) 的存档文件，修改时间: {datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')}"
                                )

                    # 检查 Java 版玩家，使用文件修改时间
                    for java_name in player.java_name:
                        uuid = self._get_player_uuid(java_name)
                        if uuid:
                            player_file = player_data_dir / f"{uuid}.dat"
                            if player_file.exists():
                                found_any_file = True
                                mtime = player_file.stat().st_mtime
                                latest_mtime = max(latest_mtime, mtime)

                    # 从历史记录中获取该QQ号的最后游玩时间（处理改ID的情况）
                    qq_last_play_time = self.get("qq_last_play_time", {})
                    for qq_account in qq_accounts:
                        qq_str = str(qq_account)
                        if qq_str in qq_last_play_time:
                            latest_mtime = max(latest_mtime, qq_last_play_time[qq_str])
                            found_any_file = True  # 标记为找到记录

                    # 如果从 playerdata 获取到了新的时间，更新 QQ 的最后游玩时间记录
                    if found_any_file and latest_mtime > 0:
                        for qq_account in qq_accounts:
                            qq_str = str(qq_account)
                            # 更新或创建该 QQ 的游玩时间记录
                            current_recorded_time = qq_last_play_time.get(qq_str, 0)
                            if latest_mtime > current_recorded_time:
                                qq_last_play_time[qq_str] = latest_mtime
                                self.logger.debug(
                                    f"更新 QQ {qq_str} 的游玩时间记录: {datetime.fromtimestamp(latest_mtime).strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                        # 保存更新
                        self["qq_last_play_time"] = qq_last_play_time

                    # 区分两种情况
                    if not found_any_file:
                        # 从未进入过游戏，使用进群时间作为参考
                        # 如果有进群时间且超过阈值
                        if join_time and join_time > 0:
                            days_since_join = int((current_time - join_time) / 86400)
                            if (current_time - join_time) > never_played_seconds:
                                never_played_players.append(
                                    {
                                        "player_name": player.name,
                                        "qq_accounts": qq_accounts,
                                        "days_since_bind": days_since_join,
                                    }
                                )
                                self.logger.debug(
                                    f"玩家 {player.name} 进群 {days_since_join} 天后仍未进入游戏"
                                )
                        else:
                            # 如果没有进群时间记录，也加入列表（向后兼容或无法获取进群时间的情况）
                            never_played_players.append(
                                {
                                    "player_name": player.name,
                                    "qq_accounts": qq_accounts,
                                    "days_since_bind": None,
                                }
                            )
                            self.logger.debug(
                                f"玩家 {player.name} 已绑定但从未进入游戏（无进群时间记录）"
                            )
                    elif (current_time - latest_mtime) > inactive_seconds:
                        # 进过游戏但长时间未登录
                        days_inactive = int((current_time - latest_mtime) / 86400)
                        inactive_players.append(
                            {
                                "player_name": player.name,
                                "qq_accounts": qq_accounts,
                                "days_inactive": days_inactive,
                            }
                        )
                        self.logger.debug(
                            f"玩家 {player.name} 已不活跃 {days_inactive} 天"
                        )

                # 如果有任何不活跃玩家，保存到字典中
                if inactive_players or never_played_players:
                    inactive_players_dict[group_id] = {
                        "inactive": inactive_players,
                        "never_played": never_played_players,
                    }
                    self.logger.info(
                        f"群 {group_id} 发现 {len(inactive_players)} 名不活跃玩家，"
                        f"{len(never_played_players)} 名从未进入游戏的玩家"
                    )

            # 更新最后检查时间并保存所有数据（包括 qq_last_play_time 的更新）
            self["last_check_time"] = int(current_time)
            self.save()

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"检查不活跃玩家时出错: {error_msg}")
        finally:
            self._checking = False

        return inactive_players_dict

    async def _send_notification(
            self, inactive_players_dict: Dict[int, Dict[str, List[Dict]]]
    ) -> None:
        """发送通知到配置的目标

        Parameters
        ----------
        inactive_players_dict : Dict[int, Dict[str, List[Dict]]]
            不活跃玩家字典，key为群号，value为包含 'inactive' 和 'never_played' 的字典
        """
        # 获取配置
        notify_targets = self.config.get_keys(
            ["system", "inactive_check", "notify_targets"], {}
        )
        admin_private = notify_targets.get("admin_private", True)
        admin_groups = notify_targets.get("admin_groups", True)
        origin_group = notify_targets.get("origin_group", False)

        inactive_days = self.config.get_keys(
            ["system", "inactive_check", "inactive_days"], 30
        )

        # 构建通知消息
        for group_id, players_data in inactive_players_dict.items():
            try:
                inactive_players = players_data.get("inactive", [])
                never_played_players = players_data.get("never_played", [])

                # 如果两类玩家都没有，跳过
                if not inactive_players and not never_played_players:
                    continue

                # 获取群信息
                group_info_result = await self.qq_connector.bot.get_group_info(
                    group_id=int(group_id)
                )
                group_name = "未知群"
                if group_info_result and group_info_result.get("status") == "ok":
                    group_name = group_info_result.get("data", {}).get(
                        "group_name", "未知群"
                    )

                # 构建消息的各个部分
                notification_parts = [self.get_tr("notification_title")]

                # 1. 不活跃玩家部分
                if inactive_players:
                    player_list = []
                    for player in inactive_players:
                        qq_accounts_str = ", ".join(
                            str(qq) for qq in player["qq_accounts"]
                        )
                        player_item = self.get_tr(
                            "player_item",
                            player_name=player["player_name"],
                            qq_accounts=qq_accounts_str,
                            days_inactive=player["days_inactive"],
                        )
                        player_list.append(player_item)
                    player_list_str = "\n".join(player_list)

                    inactive_section = self.get_tr(
                        "notification_content",
                        group_name=group_name,
                        group_id=group_id,
                        count=len(inactive_players),
                        days=inactive_days,
                        player_list=player_list_str,
                    )
                    notification_parts.append(inactive_section)

                # 2. 从未进入游戏玩家部分
                if never_played_players:
                    never_played_list = []
                    never_played_days_config = self.config.get_keys(
                        ["system", "inactive_check", "never_played_days"], 7
                    )
                    for player in never_played_players:
                        qq_accounts_str = ", ".join(
                            str(qq) for qq in player["qq_accounts"]
                        )
                        days_since_bind = player.get("days_since_bind")

                        if days_since_bind is not None:
                            player_item = self.get_tr(
                                "never_played_player_item",
                                player_name=player["player_name"],
                                qq_accounts=qq_accounts_str,
                                days_since_bind=days_since_bind,
                            )
                        else:
                            # 向后兼容：没有绑定时间记录的情况
                            player_item = self.get_tr(
                                "never_played_player_item_no_time",
                                player_name=player["player_name"],
                                qq_accounts=qq_accounts_str,
                            )

                        never_played_list.append(player_item)
                    never_played_list_str = "\n".join(never_played_list)

                    never_played_section = self.get_tr(
                        "never_played_content",
                        group_name=group_name,
                        group_id=group_id,
                        count=len(never_played_players),
                        days=never_played_days_config,
                        player_list=never_played_list_str,
                    )
                    notification_parts.append(never_played_section)

                # 组合完整消息
                notification_msg = "\n\n".join(notification_parts)

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
        self.logger.info("不活跃检查定时任务已启动")

        while self._schedule_task_running:
            try:
                # 读取配置
                last_check_time = self.get("last_check_time", 0)
                check_interval = self.config.get_keys(
                    ["system", "inactive_check", "check_interval"], 86400
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
                if (
                        not self.qq_connector
                        or not self.bound_system
                        or not self.whitelist_system
                ):
                    self.logger.warning("依赖系统未初始化，跳过本次检查")
                    continue

                # 执行检查
                self.logger.info("开始定时检查不活跃玩家...")
                inactive_players_dict = await self._check_inactive_players()

                # 发送通知
                if inactive_players_dict:
                    await self._send_notification(inactive_players_dict)
                    total_inactive = sum(
                        len(data.get("inactive", []))
                        for data in inactive_players_dict.values()
                    )
                    total_never_played = sum(
                        len(data.get("never_played", []))
                        for data in inactive_players_dict.values()
                    )
                    self.logger.info(
                        f"定时检查完成，共发现 {total_inactive} 名不活跃玩家，"
                        f"{total_never_played} 名从未进入游戏的玩家"
                    )
                else:
                    self.logger.info("定时检查完成，所有玩家均活跃")

            except Exception as e:
                error_msg = str(e) + "\n" + traceback.format_exc()
                self.logger.error(f"定时检查任务出错: {error_msg}")
                # 出错后等待一段时间再继续（分割成小段以便快速响应停止信号）
                for _ in range(60):
                    if not self._schedule_task_running:
                        break
                    await asyncio.sleep(1.0)

        self.logger.info("不活跃检查定时任务已停止")

    def stop_schedule_task(self) -> None:
        """停止定时检查任务"""
        self._schedule_task_running = False
        self.logger.info("正在停止不活跃检查定时任务...")
