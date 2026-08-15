# -*- coding: utf-8 -*-
"""服务器 TPS / MSPT 查询系统。

通过 RCON 执行原版 ``/tick query``，解析 getTickTime 样本得到的
平均 MSPT 与 P50/P95/P99，并换算实时 TPS。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.rcon_manager import RconManager
from gugubot.utils.tick_query import TickStats, parse_tick_query
from gugubot.utils.types import BroadcastInfo

DEFAULT_TRIGGERS = ("tps", "mspt", "tick", "卡顿", "性能")


def _format_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _parse_number(value: str) -> Optional[float]:
    if not value or value in {"-", "error"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class TpsSystem(BasicSystem):
    """服务器 TPS / MSPT 查询系统。"""

    def __init__(
        self, server: PluginServerInterface, config: Optional[BotConfig] = None
    ) -> None:
        super().__init__("tps", enable=True, config=config)
        self.server = server
        self.rcon_manager = RconManager(server)
        self.bridge_query_cmd = "bridge_tps_query_internal_cmd"
        self.bridge_response_cmd = "bridge_tps_response_internal_cmd"
        self._pending_queries: Dict[str, Dict[str, Any]] = {}

    def initialize(self) -> None:
        self.logger.debug("TPS / MSPT 查询系统已初始化")

    def _get_triggers(self) -> set:
        triggers = set(DEFAULT_TRIGGERS)
        for key in ("name", "tps"):
            value = self.get_tr(key)
            if value and not value.startswith("gugubot."):
                triggers.add(value)
                if value.isascii():
                    triggers.add(value.lower())
        return triggers

    def _is_tps_command(self, command: str) -> bool:
        if not command:
            return False
        first = command.split()[0]
        triggers = self._get_triggers()
        if first in triggers:
            return True
        return first.isascii() and first.lower() in triggers

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
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

        if self.bridge_response_cmd in content:
            inner = content[content.index(self.bridge_response_cmd) :]
            await self._handle_bridge_response(inner)
            return True

        if self.bridge_query_cmd in content:
            inner = content[content.index(self.bridge_query_cmd) :]
            await self._handle_bridge_query(broadcast_info, inner)
            return True

        if not self.is_command(broadcast_info):
            return False

        if not self._is_tps_command(command):
            return False

        rest = command.split(None, 1)[1] if len(command.split()) > 1 else ""
        help_cmd = self.get_tr(
            "gugubot.system.general_help.help_command", global_key=True
        )
        if rest in {help_cmd, "帮助", "help"}:
            return await self._handle_help(broadcast_info)

        await self._handle_user_tps_command(broadcast_info)
        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        await self.reply_to_source(
            broadcast_info,
            [
                MessageBuilder.text(
                    self.get_tr(
                        "help_msg",
                        command_prefix=command_prefix,
                        name=self.get_tr("name"),
                        tps=self.get_tr("tps"),
                        enable=self.get_tr("gugubot.enable", global_key=True),
                        disable=self.get_tr("gugubot.disable", global_key=True),
                    )
                )
            ],
        )
        return True

    async def _handle_user_tps_command(self, broadcast_info: BroadcastInfo) -> None:
        merge_results = self.config.get_keys(
            ["system", "tps", "merge_bridge_results"], True
        )

        if merge_results and self.is_bridge_enabled() and self.is_main_server():
            await self._handle_merged_tps_command(broadcast_info)
            return

        await self._handle_tps_command_local(broadcast_info)
        if self.is_bridge_enabled() and self.is_main_server():
            await self._broadcast_query_to_bridge(broadcast_info)

    def _query_local_stats(self) -> Optional[TickStats]:
        if not self.server.is_rcon_running():
            return None
        result = self.server.rcon_query("tick query")
        return parse_tick_query(result or "")

    def _status_text(self, status: str) -> str:
        key = f"status_{status}"
        translated = self.get_tr(key)
        if translated and not translated.startswith("gugubot."):
            return translated
        return self.get_tr("status_unknown")

    def _format_stats(self, stats: TickStats, server_name: Optional[str] = None) -> str:
        ticktime = self.get_tr("ticktime_unavailable")
        if stats.p50 is not None and stats.p95 is not None and stats.p99 is not None:
            ticktime = self.get_tr(
                "ticktime_content",
                p50=_format_number(stats.p50, 1),
                p95=_format_number(stats.p95, 1),
                p99=_format_number(stats.p99, 1),
            )

        name = server_name or self.get_server_name()
        return self.get_tr(
            "server_content",
            server_name=name,
            title=self.get_tr("title"),
            status=self._status_text(stats.status),
            tps=_format_number(stats.tps, 2),
            target=_format_number(stats.target, 1),
            mspt=_format_number(stats.average, 2),
            target_mspt=_format_number(stats.target_mspt, 2),
            ticktime=ticktime,
        )

    def _format_error(self, server_name: Optional[str] = None) -> str:
        return self.get_tr(
            "server_query_failed",
            server_name=server_name or self.get_server_name(),
        )

    async def _handle_tps_command_local(self, broadcast_info: BroadcastInfo) -> None:
        try:
            if not self.server.is_rcon_running():
                self.logger.warning(self.get_tr("rcon_not_running"))
                await self.reply_to_source(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("rcon_not_running"))],
                )
                return

            stats = self._query_local_stats()
            if stats is None:
                await self.reply_to_source(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("parse_failed"))],
                )
                return

            await self.reply_to_source(
                broadcast_info,
                [MessageBuilder.text(self._format_stats(stats))],
            )
        except Exception as e:
            self.logger.error(f"查询 TPS 失败: {e}")
            await self.reply_to_source(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("query_failed", error=str(e)))],
            )

    async def _handle_merged_tps_command(self, broadcast_info: BroadcastInfo) -> None:
        try:
            query_id = f"{broadcast_info.sender_id}_{int(time.time() * 1000)}"
            server_name = self.get_server_name()
            stats = self._query_local_stats() if self.server.is_rcon_running() else None

            self._pending_queries[query_id] = {
                "broadcast_info": broadcast_info,
                "responses": {
                    server_name: stats.to_dict()
                    if stats is not None
                    else {"error": True, "status": "error"}
                },
                "start_time": time.time(),
            }

            await self._broadcast_query_to_bridge_with_id(broadcast_info, query_id)
            timeout = self.config.get_keys(["system", "tps", "bridge_timeout"], 3)
            await asyncio.sleep(timeout)
            await self._send_merged_result(query_id)
        except Exception as e:
            self.logger.error(f"处理合并 TPS 查询失败: {e}")
            await self.reply_to_source(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("query_failed", error=str(e)))],
            )

    async def _broadcast_query_to_bridge(self, broadcast_info: BroadcastInfo) -> None:
        await self._broadcast_query_to_bridge_with_id(broadcast_info, "")

    async def _broadcast_query_to_bridge_with_id(
        self, broadcast_info: BroadcastInfo, query_id: str
    ) -> None:
        command_text = (
            f"{self.bridge_query_cmd}|{query_id}"
            if query_id
            else self.bridge_query_cmd
        )
        try:
            await self.send_to_bridge(broadcast_info, command_text)
        except Exception as e:
            self.logger.error(f"广播 TPS 查询命令失败: {e}")

    async def _handle_bridge_query(
        self, broadcast_info: BroadcastInfo, command: str
    ) -> None:
        try:
            query_id = ""
            if "|" in command:
                parts = command.split("|")
                if len(parts) >= 2:
                    query_id = parts[1]
            await self._send_response_to_bridge(broadcast_info, query_id)
        except Exception as e:
            self.logger.error(f"处理 bridge TPS 查询失败: {e}")

    async def _send_response_to_bridge(
        self, broadcast_info: BroadcastInfo, query_id: str
    ) -> None:
        try:
            server_name = self.get_server_name()
            stats = self._query_local_stats() if self.server.is_rcon_running() else None
            if stats is None:
                response_text = "|".join(
                    [self.bridge_response_cmd, query_id, server_name, "error"]
                )
            else:
                response_text = "|".join(
                    [
                        self.bridge_response_cmd,
                        query_id,
                        server_name,
                        _format_number(stats.tps, 2),
                        _format_number(stats.target, 1),
                        _format_number(stats.average, 2),
                        _format_number(stats.p50, 1),
                        _format_number(stats.p95, 1),
                        _format_number(stats.p99, 1),
                        stats.status,
                    ]
                )
            await self.send_to_bridge(broadcast_info, response_text)
        except Exception as e:
            self.logger.error(f"发送 TPS 响应到 bridge 失败: {e}")

    async def _handle_bridge_response(self, command: str) -> None:
        try:
            parts = command.split("|")
            if len(parts) < 4:
                return

            query_id = parts[1]
            server_name = parts[2]
            if query_id not in self._pending_queries:
                return

            if parts[3] == "error" or len(parts) < 10:
                self._pending_queries[query_id]["responses"][server_name] = {
                    "error": True,
                    "status": "error",
                }
                return

            self._pending_queries[query_id]["responses"][server_name] = {
                "tps": _parse_number(parts[3]),
                "target": _parse_number(parts[4]),
                "mspt": _parse_number(parts[5]),
                "p50": _parse_number(parts[6]),
                "p95": _parse_number(parts[7]),
                "p99": _parse_number(parts[8]),
                "status": parts[9] or "unknown",
                "error": False,
            }
        except Exception as e:
            self.logger.error(f"处理 bridge TPS 响应失败: {e}")

    def _stats_from_response(self, data: Dict[str, Any]) -> Optional[TickStats]:
        if data.get("error") or data.get("target") is None or data.get("mspt") is None:
            return None
        return TickStats(
            target=float(data["target"]),
            average=float(data["mspt"]),
            p50=data.get("p50"),
            p95=data.get("p95"),
            p99=data.get("p99"),
            status=data.get("status") or "unknown",
        )

    async def _send_merged_result(self, query_id: str) -> None:
        try:
            if query_id not in self._pending_queries:
                return

            query_data = self._pending_queries.pop(query_id)
            broadcast_info = query_data["broadcast_info"]
            responses = query_data["responses"]

            result_parts = []
            for server_name, data in sorted(responses.items()):
                stats = self._stats_from_response(data)
                if stats is None:
                    result_parts.append(self._format_error(server_name))
                else:
                    result_parts.append(self._format_stats(stats, server_name))

            merged_message = self.get_tr(
                "merged_content",
                server_count=len(responses),
                details="\n\n".join(result_parts),
            )
            await self.reply_to_source(
                broadcast_info, [MessageBuilder.text(merged_message)]
            )
        except Exception as e:
            self.logger.error(f"发送合并 TPS 结果失败: {e}")
