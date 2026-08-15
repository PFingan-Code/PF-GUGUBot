# -*- coding: utf-8 -*-
"""外部插件命令分发系统。

在 EchoSystem 之前处理已通过 ``gugubot.api`` 注册的 ``#命令``。
"""
from __future__ import annotations

import inspect
import traceback
from typing import Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.api import CommandContext, GUGUBotAPI
from gugubot.builder import MessageBuilder
from gugubot.config import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class PluginCommandSystem(BasicSystem):
    """把外部插件注册的命令接到 QQ / MC 消息上。"""

    def __init__(
        self,
        server: PluginServerInterface,
        api: GUGUBotAPI,
        config: Optional[BotConfig] = None,
    ) -> None:
        BasicSystem.__init__(self, "plugin_commands", enable=True, config=config)
        self.server = server
        self.api = api
        self.logger = server.logger

    def initialize(self) -> None:
        self.logger.debug("插件命令系统已初始化")

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        if not self.is_command(broadcast_info):
            return False

        message = broadcast_info.message
        content = message[0].get("data", {}).get("text", "")
        prefix = self.api.command_prefix
        if not content.startswith(prefix):
            return False

        rest = content[len(prefix):].strip()
        if not rest:
            return False

        parts = rest.split()
        command_name = parts[0]
        args = parts[1:]
        entry = self.api.lookup(command_name)
        if entry is None:
            return False

        if entry.admin_only and not broadcast_info.is_admin:
            await self.reply_to_source(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("no_permission"))],
            )
            return True

        ctx = CommandContext(
            sender=broadcast_info.sender or "",
            sender_id="" if broadcast_info.sender_id is None else str(broadcast_info.sender_id),
            source=broadcast_info.source.origin or str(broadcast_info.source),
            source_id="" if broadcast_info.source_id is None else str(broadcast_info.source_id),
            is_admin=bool(broadcast_info.is_admin),
            args=args,
            text=rest,
            rcon_fn=self.api.rcon,
        )

        try:
            result = entry.handler(ctx)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            self.logger.error(
                f"[GUGUBot API] 命令 {prefix}{command_name} "
                f"(插件 {entry.plugin_id}) 执行失败:\n{traceback.format_exc()}"
            )
            return True

        if isinstance(result, str) and result:
            ctx.reply(result)

        for reply_text in ctx.pop_replies():
            await self.reply_to_source(
                broadcast_info,
                [MessageBuilder.text(reply_text)],
            )
        return True
