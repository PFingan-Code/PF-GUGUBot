# -*- coding: utf-8 -*-
"""在线玩家列表查询系统。"""
import asyncio
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.rcon_manager import RconManager
from gugubot.utils.types import BroadcastInfo, ProcessedInfo


class ListType(Enum):
    """列表类型枚举"""

    PLAYERS = "players"  # 只显示真实玩家
    BOTS = "bots"  # 只显示假人
    ALL = "all"  # 显示全部（服务器状态）


class PlayerListSystem(BasicSystem):
    """在线玩家列表系统。"""

    def __init__(
            self, server: PluginServerInterface, config: Optional[BotConfig] = None
    ) -> None:
        super().__init__("list", enable=True, config=config)
        self.server = server
        self.rcon_manager = RconManager(server)
        self.bridge_query_cmd = "bridge_list_query_internal_cmd"
        self.bridge_response_cmd = "bridge_list_response_internal_cmd"

        # 用于收集多服务器响应
        self._pending_queries: Dict[str, Dict[str, Any]] = {}

    def initialize(self) -> None:
        self.logger.debug("在线玩家列表系统已初始化")

    def _is_bot(self, player_name: str) -> bool:
        """检查玩家名称是否匹配假人模式"""
        bot_patterns = self.config.get_keys(
            ["connector", "minecraft", "bot_names_pattern"], []
        )

        for pattern in bot_patterns:
            try:
                if re.match(pattern, player_name, re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

    def _separate_players_and_bots(
            self, all_players: List[str]
    ) -> Tuple[List[str], List[str]]:
        """将玩家列表分离为真实玩家和假人"""
        # 有人绑定 -> 识别假人
        ip_logger = self.server.get_plugin_instance("player_ip_logger")

        real_players = []
        bots = []

        for player in all_players:
            # 先检查名称模式
            if self._is_bot(player):
                bots.append(player)
            # 再使用插件辅助判断
            elif ip_logger and not ip_logger.is_player(player):
                bots.append(player)
            else:
                real_players.append(player)

        return real_players, bots

    def _get_list_type_from_command(self, command: str) -> Optional[ListType]:
        """根据命令确定列表类型"""
        list_cmd = self.get_tr("list")
        bot_cmd = self.get_tr("bot")
        server_cmd = self.get_tr("server")

        # 玩家列表触发词
        player_triggers = ["player", "玩家", "在线", "online"]
        if (
                list_cmd
                and not list_cmd.startswith("gugubot.")
                and list_cmd not in player_triggers
        ):
            player_triggers.append(list_cmd)

        # 假人列表触发词
        bot_triggers = ["bot", "假人", "机器人"]
        if (
                bot_cmd
                and not bot_cmd.startswith("gugubot.")
                and bot_cmd not in bot_triggers
        ):
            bot_triggers.append(bot_cmd)

        # 服务器状态触发词（显示全部）
        server_triggers = ["server", "服务器", "status", "状态", "all", "全部", "list"]
        if (
                server_cmd
                and not server_cmd.startswith("gugubot.")
                and server_cmd not in server_triggers
        ):
            server_triggers.append(server_cmd)

        if command in player_triggers:
            return ListType.PLAYERS
        elif command in bot_triggers:
            return ListType.BOTS
        elif command in server_triggers:
            return ListType.ALL

        return None

    async def _reply_to_source(
            self, broadcast_info: BroadcastInfo, message: List[dict]
    ) -> None:
        """专用回复方法：只回复到原始消息来源，不转发到 Bridge

        这个方法确保玩家列表查询的回复只发送到发起查询的连接器（如 QQ），
        而不会通过 Bridge 转发到其他服务器（如 Minecraft）。
        """
        # 确定回复目标：使用原始来源的连接器名称
        reply_target = broadcast_info.source.current

        # 构造 target
        target_source = (
            broadcast_info.source_id
            if broadcast_info.source.origin and str(broadcast_info.source_id).isdigit()
            else reply_target
        )
        target = {target_source: broadcast_info.event_sub_type}

        respond = ProcessedInfo(
            processed_message=message,
            _source=broadcast_info.source,  # 传递完整的 Source 对象
            source_id=broadcast_info.source_id,
            sender=self.system_manager.server.tr("gugubot.bot_name"),
            sender_id=None,
            raw=broadcast_info.raw,
            server=broadcast_info.server,
            logger=broadcast_info.logger,
            event_sub_type=broadcast_info.event_sub_type,
            target=target,
        )

        await self.system_manager.connector_manager.broadcast_processed_info(
            respond, include=[reply_target]
        )

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        if not self.enable:
            return False

        if broadcast_info.event_type != "message":
            return False

        message = broadcast_info.message

        if not message or message[0].get("type") != "text":
            return False

        content = message[0].get("data", {}).get("text", "").strip()
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")

        command = content.replace(command_prefix, "", 1).strip()

        # 1. Check for internal bridge response command
        if command.startswith(self.bridge_response_cmd):
            await self._handle_bridge_response(broadcast_info, command)
            return True

        # 2. Check for internal bridge query command
        if command.startswith(self.bridge_query_cmd):
            await self._handle_bridge_query(broadcast_info, command)
            return True

        if not self.is_command(broadcast_info):
            return False

        # 3. Check for normal user command
        list_type = self._get_list_type_from_command(command)

        if list_type is not None:
            await self._handle_user_list_command(broadcast_info, list_type)
            return True

        return False

    async def _handle_user_list_command(
            self, broadcast_info: BroadcastInfo, list_type: ListType
    ) -> None:
        """处理用户的玩家列表查询命令"""
        merge_results = self.config.get_keys(
            ["system", "list", "merge_bridge_results"], True
        )
        bridge_enabled = self.config.get_keys(
            ["connector", "minecraft_bridge", "enable"], False
        )
        is_main_server = self.config.get_keys(
            ["connector", "minecraft_bridge", "is_main_server"], True
        )

        if merge_results and bridge_enabled and is_main_server:
            await self._handle_merged_list_command(broadcast_info, list_type)
        else:
            await self._handle_list_command_local(broadcast_info, list_type)

            if bridge_enabled and is_main_server:
                await self._broadcast_query_to_bridge(broadcast_info, list_type)

    async def _handle_merged_list_command(
            self, broadcast_info: BroadcastInfo, list_type: ListType
    ) -> None:
        """处理合并多服务器结果的列表查询"""
        try:
            query_id = f"{broadcast_info.sender_id}_{int(time.time() * 1000)}"
            server_name = self._get_server_name()

            real_players, bots = self._get_local_players_and_bots()

            self._pending_queries[query_id] = {
                "broadcast_info": broadcast_info,
                "list_type": list_type,
                "responses": {server_name: {"players": real_players, "bots": bots}},
                "start_time": time.time(),
            }

            await self._broadcast_query_to_bridge_with_id(
                broadcast_info, query_id, list_type
            )

            timeout = self.config.get_keys(["system", "list", "bridge_timeout"], 3)
            await asyncio.sleep(timeout)

            await self._send_merged_result(query_id)

        except Exception as e:
            self.logger.error(f"处理合并列表查询失败: {e}")
            await self._reply_to_source(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("query_failed", error=str(e)))],
            )

    def _get_local_players(self) -> List[str]:
        """获取本地服务器的玩家列表（不包含假人，如果启用了 use_bot_list）"""
        try:
            if self.server.is_rcon_running():
                result = self.server.rcon_query("list")
                colon_separator = self.config.get_keys(
                    ["system", "list", "colon_separator"], ":"
                )
                comma_separator = self.config.get_keys(
                    ["system", "list", "comma_separator"], ","
                )
                return self.parse_player_list(result, colon_separator, comma_separator)
        except Exception as e:
            self.logger.warning(f"获取本地玩家列表失败: {e}")
        return []

    def _get_local_bots(self) -> List[str]:
        """获取本地服务器的假人列表（通过 /bot list 命令）

        返回格式示例:
            Total number: (1/10)
            world_the_end(0):
            world(1): sese
            world_nether(0):
        """
        try:
            if self.server.is_rcon_running():
                result = self.server.rcon_query("bot list")
                if not result:
                    return []
                return self._parse_bot_list(result)
        except Exception as e:
            self.logger.warning(f"获取本地假人列表失败: {e}")
        return []

    def _parse_bot_list(self, raw_result: str) -> List[str]:
        """解析 /bot list 返回的假人列表

        格式:
            Total number: (1/10)
            world_the_end(0):
            world(1): bot1, bot2
            world_nether(0):
        """
        bots = []
        comma_separator = self.config.get_keys(
            ["system", "list", "comma_separator"], ","
        )

        for line in raw_result.strip().split("\n"):
            line = line.strip()
            # 跳过总数行和空行
            if not line or line.startswith("Total number"):
                continue
            # 解析维度行: world(1): bot1, bot2
            # 查找冒号后的假人列表
            if "):" in line:
                parts = line.split("):", 1)
                if len(parts) == 2 and parts[1].strip():
                    bot_names = [
                        b.strip()
                        for b in re.split(comma_separator, parts[1])
                        if b.strip()
                    ]
                    bots.extend(bot_names)

        return bots

    def _get_local_players_and_bots(self) -> Tuple[List[str], List[str]]:
        """获取本地服务器的玩家和假人列表

        Returns:
            Tuple[List[str], List[str]]: (真实玩家列表, 假人列表)
        """
        use_bot_list = self.config.get_keys(["system", "list", "use_bot_list"], False)

        if use_bot_list:
            # leaves/lophine 端：使用 /list 获取玩家，使用 /bot list 获取假人
            all_players = self._get_local_players()
            bots = self._get_local_bots()
            # /list 在这些端只返回真实玩家，不需要额外分离
            return all_players, bots
        else:
            # 其他端：使用 /list 获取所有，然后通过名称模式分离
            all_players = self._get_local_players()
            return self._separate_players_and_bots(all_players)

    def _get_server_name(self) -> str:
        """获取当前服务器名称"""
        return self.config.get_keys(
            ["connector", "minecraft_bridge", "source_name"], "Server"
        )

    async def _handle_bridge_query(
            self, broadcast_info: BroadcastInfo, command: str
    ) -> None:
        """处理来自 bridge 的查询请求"""
        try:
            if "|" in command:
                parts = command.split("|")
                if len(parts) >= 3:
                    query_id = parts[1]
                    list_type_str = parts[2]
                    list_type = (
                        ListType(list_type_str)
                        if list_type_str in [lt.value for lt in ListType]
                        else ListType.PLAYERS
                    )
                    await self._send_response_to_bridge(
                        broadcast_info, query_id, list_type
                    )
                    return

            # 旧版本行为：直接回复
            await self._handle_list_command_local(broadcast_info, ListType.PLAYERS)
        except Exception as e:
            self.logger.error(f"处理 bridge 查询失败: {e}")

    async def _handle_bridge_response(
            self, broadcast_info: BroadcastInfo, command: str
    ) -> None:
        """处理来自其他服务器的响应"""  # broadcast_info 未使用
        try:
            parts = command.split("|")

            if len(parts) < 4:
                return

            query_id = parts[1]
            server_name = parts[2]
            players_str = parts[3] if len(parts) > 3 else ""
            bots_str = parts[4] if len(parts) > 4 else ""

            players = (
                [p.strip() for p in players_str.split(",") if p.strip()]
                if players_str
                else []
            )
            bots = (
                [b.strip() for b in bots_str.split(",") if b.strip()]
                if bots_str
                else []
            )

            if query_id in self._pending_queries:
                self._pending_queries[query_id]["responses"][server_name] = {
                    "players": players,
                    "bots": bots,
                }

        except Exception as e:
            self.logger.error(f"处理 bridge 响应失败: {e}")

    async def _send_merged_result(self, query_id: str) -> None:
        """发送合并后的结果"""
        try:
            if query_id not in self._pending_queries:
                return

            query_data = self._pending_queries.pop(query_id)
            broadcast_info = query_data["broadcast_info"]
            responses = query_data["responses"]
            list_type = query_data.get("list_type", ListType.PLAYERS)

            result_parts = []
            total_player_count = 0
            total_bot_count = 0

            for server_name, data in sorted(responses.items()):
                players = data.get("players", [])
                bots = data.get("bots", [])

                total_player_count += len(players)
                total_bot_count += len(bots)

                if list_type == ListType.PLAYERS:
                    if players:
                        players.sort()
                        players_list = [f"  {i + 1}. {p}" for i, p in enumerate(players)]
                        result_parts.append(
                            self.get_tr(
                                "server_players_count",
                                server_name=server_name,
                                count=len(players),
                                player_list="\n".join(players_list),
                            )
                        )
                    else:
                        result_parts.append(
                            self.get_tr("server_no_players", server_name=server_name)
                        )

                elif list_type == ListType.BOTS:
                    if bots:
                        bots.sort()
                        bots_list = [f"  {i + 1}. {b}" for i, b in enumerate(bots)]
                        result_parts.append(
                            self.get_tr(
                                "server_bots_count",
                                server_name=server_name,
                                count=len(bots),
                                player_list="\n".join(bots_list),
                            )
                        )
                    else:
                        result_parts.append(
                            self.get_tr("server_no_bots", server_name=server_name)
                        )

                else:  # ListType.ALL
                    server_result = self.get_tr("server_label", server_name=server_name)
                    sub_parts = []

                    if players:
                        players.sort()
                        players_list = [
                            f"    {i + 1}. {p}" for i, p in enumerate(players)
                        ]
                        sub_parts.append(
                            self.get_tr(
                                "merged_players_label",
                                count=len(players),
                                player_list="\n".join(players_list),
                            )
                        )
                    else:
                        sub_parts.append(self.get_tr("merged_no_players"))

                    if bots:
                        bots.sort()
                        bots_list = [f"    {i + 1}. {b}" for i, b in enumerate(bots)]
                        sub_parts.append(
                            self.get_tr(
                                "merged_bots_label",
                                count=len(bots),
                                player_list="\n".join(bots_list),
                            )
                        )
                    else:
                        sub_parts.append(self.get_tr("merged_no_bots"))

                    result_parts.append(server_result + "\n" + "\n".join(sub_parts))

            # 使用专用回复方法，确保只发送到原始来源
            if list_type == ListType.PLAYERS:
                if total_player_count == 0:
                    await self._reply_to_source(
                        broadcast_info,
                        [MessageBuilder.text(self.get_tr("players_empty"))],
                    )
                else:
                    merged_message = self.get_tr(
                        "merged_players_content",
                        total_count=total_player_count,
                        server_count=len(responses),
                        details="\n\n".join(result_parts),
                    )
                    await self._reply_to_source(
                        broadcast_info, [MessageBuilder.text(merged_message)]
                    )

            elif list_type == ListType.BOTS:
                if total_bot_count == 0:
                    await self._reply_to_source(
                        broadcast_info, [MessageBuilder.text(self.get_tr("bots_empty"))]
                    )
                else:
                    merged_message = self.get_tr(
                        "merged_bots_content",
                        total_count=total_bot_count,
                        server_count=len(responses),
                        details="\n\n".join(result_parts),
                    )
                    await self._reply_to_source(
                        broadcast_info, [MessageBuilder.text(merged_message)]
                    )

            else:  # ListType.ALL
                total_count = total_player_count + total_bot_count
                if total_count == 0:
                    await self._reply_to_source(
                        broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
                    )
                else:
                    merged_message = self.get_tr(
                        "merged_server_content",
                        player_count=total_player_count,
                        bot_count=total_bot_count,
                        server_count=len(responses),
                        details="\n\n".join(result_parts),
                    )
                    await self._reply_to_source(
                        broadcast_info, [MessageBuilder.text(merged_message)]
                    )

        except Exception as e:
            self.logger.error(f"发送合并结果失败: {e}")

    async def _broadcast_query_to_bridge_with_id(
            self, broadcast_info: BroadcastInfo, query_id: str, list_type: ListType
    ) -> None:
        """广播带查询ID的查询命令到其他服务器"""
        try:
            if not self.config.get_keys(
                    ["connector", "minecraft_bridge", "enable"], False
            ):
                return

            bridge_source = self.config.get_keys(
                ["connector", "minecraft_bridge", "source_name"], "Bridge"
            )
            bridge_connector = self.system_manager.connector_manager.get_connector(
                bridge_source
            )

            if not bridge_connector:
                return

            command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
            command_text = (
                f"{command_prefix}{self.bridge_query_cmd}|{query_id}|{list_type.value}"
            )

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
            )

            await self.system_manager.connector_manager.broadcast_processed_info(
                processed_info, include=[bridge_source]
            )

        except Exception as e:
            self.logger.error(f"广播带ID的查询命令失败: {e}")

    async def _handle_list_command_local(
            self, broadcast_info: BroadcastInfo, list_type: ListType
    ) -> None:
        """处理本地列表命令"""
        try:
            if self.server.is_rcon_running():
                use_bot_list = self.config.get_keys(
                    ["system", "list", "use_bot_list"], False
                )

                if use_bot_list:
                    # leaves/lophine 端：使用专门的方法获取分离的玩家和假人列表
                    real_players, bots = self._get_local_players_and_bots()
                    formatted_result = self._format_separated_list(
                        real_players, bots, list_type
                    )
                else:
                    # 其他端：使用传统方式，从 /list 结果中分离
                    result = self.server.rcon_query("list")
                    formatted_result = self._format_player_list(result, list_type)

                if formatted_result:
                    await self._reply_to_source(
                        broadcast_info, [MessageBuilder.text(formatted_result)]
                    )
                    return

            self.logger.warning(self.get_tr("rcon_not_running"))
            await self._reply_to_source(
                broadcast_info, [MessageBuilder.text(self.get_tr("rcon_not_running"))]
            )

        except Exception as e:
            self.logger.error(f"Query player list failed: {e}")
            await self._reply_to_source(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("query_failed", error=str(e)))],
            )

    async def _send_response_to_bridge(
            self, broadcast_info: BroadcastInfo, query_id: str, list_type: ListType
    ) -> None:
        """发送响应给主服务器"""
        try:
            if not self.config.get_keys(
                    ["connector", "minecraft_bridge", "enable"], False
            ):
                return

            bridge_source = self.config.get_keys(
                ["connector", "minecraft_bridge", "source_name"], "Bridge"
            )
            bridge_connector = self.system_manager.connector_manager.get_connector(
                bridge_source
            )

            if not bridge_connector:
                return

            server_name = self._get_server_name()
            real_players, bots = self._get_local_players_and_bots()

            players_str = ",".join(real_players) if real_players else ""
            bots_str = ",".join(bots) if bots else ""

            command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
            response_text = f"{command_prefix}{self.bridge_response_cmd}|{query_id}|{server_name}|{players_str}|{bots_str}"

            processed_info = ProcessedInfo(
                processed_message=[MessageBuilder.text(response_text)],
                _source=broadcast_info.source,  # 传递完整的 Source 对象
                source_id=broadcast_info.source_id,
                sender=broadcast_info.sender,
                sender_id=broadcast_info.sender_id,
                raw=broadcast_info.raw,
                server=broadcast_info.server,
                logger=broadcast_info.logger,
                event_sub_type=broadcast_info.event_sub_type,
            )

            await self.system_manager.connector_manager.broadcast_processed_info(
                processed_info, include=[bridge_source]
            )

        except Exception as e:
            self.logger.error(f"发送响应到 bridge 失败: {e}")

    def _format_separated_list(
            self,
            real_players: List[str],
            bots: List[str],
            list_type: ListType = ListType.PLAYERS,
    ) -> str:
        """格式化已分离的玩家和假人列表输出（用于 leaves/lophine 端）"""
        try:
            if list_type == ListType.PLAYERS:
                if not real_players:
                    return self.get_tr("players_empty")
                real_players.sort()
                players_list = [f"{i + 1}. {p}" for i, p in enumerate(real_players)]
                return self.get_tr(
                    "players_content",
                    count=len(real_players),
                    players="\n" + "\n".join(players_list),
                )

            elif list_type == ListType.BOTS:
                if not bots:
                    return self.get_tr("bots_empty")
                bots.sort()
                bots_list = [f"{i + 1}. {b}" for i, b in enumerate(bots)]
                return self.get_tr(
                    "bots_content", count=len(bots), bots="\n" + "\n".join(bots_list)
                )

            else:  # ListType.ALL
                result_parts = []

                if real_players:
                    real_players.sort()
                    players_list = [f"  {i + 1}. {p}" for i, p in enumerate(real_players)]
                    result_parts.append(
                        self.get_tr(
                            "local_players_label",
                            count=len(real_players),
                            player_list="\n".join(players_list),
                        )
                    )
                else:
                    result_parts.append(self.get_tr("local_no_players"))

                if bots:
                    bots.sort()
                    bots_list = [f"  {i + 1}. {b}" for i, b in enumerate(bots)]
                    result_parts.append(
                        self.get_tr(
                            "local_bots_label",
                            count=len(bots),
                            player_list="\n".join(bots_list),
                        )
                    )
                else:
                    result_parts.append(self.get_tr("local_no_bots"))

                return self.get_tr(
                    "server_content",
                    player_count=len(real_players),
                    bot_count=len(bots),
                    details="\n\n".join(result_parts),
                )

        except Exception as e:
            self.logger.warning(f"Failed to format separated list: {e}")
            return ""

    def _format_player_list(
            self, raw_result: str, list_type: ListType = ListType.PLAYERS
    ) -> str:
        """格式化玩家列表输出"""
        try:
            colon_separator = self.config.get_keys(
                ["system", "list", "colon_separator"], ":"
            )
            comma_separator = self.config.get_keys(
                ["system", "list", "comma_separator"], ","
            )

            all_players = self.parse_player_list(
                raw_result, colon_separator, comma_separator
            )

            if len(all_players) == 0:
                if " 0 " in raw_result or "0/" in raw_result:
                    if list_type == ListType.PLAYERS:
                        return self.get_tr("players_empty")
                    elif list_type == ListType.BOTS:
                        return self.get_tr("bots_empty")
                    else:
                        return self.get_tr("list_empty")
                return raw_result

            real_players, bots = self._separate_players_and_bots(all_players)

            if list_type == ListType.PLAYERS:
                if not real_players:
                    return self.get_tr("players_empty")
                real_players.sort()
                players_list = [f"{i + 1}. {p}" for i, p in enumerate(real_players)]
                return self.get_tr(
                    "players_content",
                    count=len(real_players),
                    players="\n" + "\n".join(players_list),
                )

            elif list_type == ListType.BOTS:
                if not bots:
                    return self.get_tr("bots_empty")
                bots.sort()
                bots_list = [f"{i + 1}. {b}" for i, b in enumerate(bots)]
                return self.get_tr(
                    "bots_content", count=len(bots), bots="\n" + "\n".join(bots_list)
                )

            else:  # ListType.ALL
                result_parts = []

                if real_players:
                    real_players.sort()
                    players_list = [f"  {i + 1}. {p}" for i, p in enumerate(real_players)]
                    result_parts.append(
                        self.get_tr(
                            "local_players_label",
                            count=len(real_players),
                            player_list="\n".join(players_list),
                        )
                    )
                else:
                    result_parts.append(self.get_tr("local_no_players"))

                if bots:
                    bots.sort()
                    bots_list = [f"  {i + 1}. {b}" for i, b in enumerate(bots)]
                    result_parts.append(
                        self.get_tr(
                            "local_bots_label",
                            count=len(bots),
                            player_list="\n".join(bots_list),
                        )
                    )
                else:
                    result_parts.append(self.get_tr("local_no_bots"))

                return self.get_tr(
                    "server_content",
                    player_count=len(real_players),
                    bot_count=len(bots),
                    details="\n\n".join(result_parts),
                )

        except Exception as e:
            self.logger.warning(f"Failed to format player list: {e}")
            return raw_result

    def parse_player_list(
            self, player_list: str, colon_separator: str = ":", comma_separator: str = ","
    ) -> List[str]:
        """解析玩家列表字符串"""
        if not player_list:
            return []

        try:
            parts = re.split(colon_separator, player_list)
            if len(parts) < 2:
                return []

            players_part = parts[-1].strip()

            if not players_part:
                return []

            players = [
                p.strip() for p in re.split(comma_separator, players_part) if p.strip()
            ]

            return players

        except Exception:
            return []

    async def _broadcast_query_to_bridge(
            self, broadcast_info: BroadcastInfo, list_type: ListType
    ) -> None:
        """Broadcast query command to other servers via bridge."""
        try:
            if not self.config.get_keys(
                    ["connector", "minecraft_bridge", "enable"], False
            ):
                return

            bridge_source = self.config.get_keys(
                ["connector", "minecraft_bridge", "source_name"], "Bridge"
            )
            bridge_connector = self.system_manager.connector_manager.get_connector(
                bridge_source
            )

            if not bridge_connector:
                return

            command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
            command_text = f"{command_prefix}{self.bridge_query_cmd}"

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
            )

            await self.system_manager.connector_manager.broadcast_processed_info(
                processed_info, include=[bridge_source]
            )

        except Exception as e:
            self.logger.error(f"Failed to broadcast list query to bridge: {e}")
