"""玩家通知插件模块。

该模块提供玩家加入和离开时的广播通知功能。
"""

import asyncio
import re
import time
import traceback
from typing import Callable, Dict, List, Optional, Set

from mcdreforged.api.types import Info, PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BotConfig
from gugubot.connector import ConnectorManager
from gugubot.utils.types import ProcessedInfo

# on_info 每次都会重新创建 handler，冷却状态必须放在模块级
_pending_leaves: Dict[str, asyncio.Task] = {}
_leave_at: Dict[str, float] = {}
_join_announced: Set[str] = set()


def _build_notice_target(group_ids: List) -> Optional[Dict[str, str]]:
    groups = [g for g in (group_ids or []) if g]
    if not groups:
        return None
    target = {str(g): "group" for g in groups}
    if len(target) == 1:
        target["_"] = "group"  # 防止桥接连接器单目标过滤
    return target


def _get_cooldown(config: BotConfig) -> float:
    try:
        value = config.get_keys(
            ["connector", "minecraft", "player_notice_cooldown"], 0
        )
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_duration(seconds: float) -> str:
    """将秒数格式化为中文时长，如 5分钟、1分30秒、30秒。"""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        if secs or hours:
            parts.append(f"{minutes}分")
        else:
            parts.append(f"{minutes}分钟")
    if secs or not parts:
        parts.append(f"{secs}秒")
    return "".join(parts)


def _match_player_name(content: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        if match := re.search(pattern, content):
            name = match.group(1) if match.groups() else match.group(0)
            return name.strip() if name else None
    return None


def _cancel_pending_leave(player_name: str) -> bool:
    """取消该玩家未发出的离开通知。返回是否取消了尚未完成的任务。"""
    task = _pending_leaves.pop(player_name, None)
    if task is not None and not task.done():
        task.cancel()
        return True
    return False


def _in_leave_cooldown(player_name: str, cooldown: float) -> bool:
    if cooldown <= 0:
        return False
    left_at = _leave_at.get(player_name)
    if left_at is None:
        return False
    return (time.monotonic() - left_at) < cooldown


def cancel_all_pending_notices() -> None:
    """取消所有未发出的延迟离开通知（插件卸载时调用）。"""
    for player_name in list(_pending_leaves):
        _cancel_pending_leave(player_name)


async def _broadcast_notice(
        server: PluginServerInterface,
        connector_manager: ConnectorManager,
        minecraft_source_name: str,
        exclude_sources: List[str],
        notice_target: Optional[Dict[str, str]],
        message: str,
) -> None:
    try:
        processed_info = ProcessedInfo(
            processed_message=[MessageBuilder.text(message)],
            _source=minecraft_source_name,
            source_id="",
            sender="",
            raw=None,
            server=server,
            logger=server.logger,
            event_sub_type="group",
            target=notice_target,
        )
        await connector_manager.broadcast_processed_info(
            processed_info, exclude=exclude_sources
        )
        server.logger.debug(message)
    except Exception as e:
        server.logger.error(
            server.tr(
                "gugubot.notice.player_notice_error",
                error=str(e) + "\n" + traceback.format_exc(),
            )
        )


def _notice_enabled(
        player_name: str, config: BotConfig, player_key: str, bot_key: str
) -> bool:
    is_player = not is_bot(player_name, config)
    if is_player:
        return bool(config.get_keys(["connector", "minecraft", player_key], True))
    return bool(config.get_keys(["connector", "minecraft", bot_key], True))


def create_on_player_join(
        connector_manager: ConnectorManager, config: BotConfig
) -> Callable[[PluginServerInterface, Info], None]:
    minecraft_source_name = config.get_keys(
        ["connector", "minecraft", "source_name"], "Minecraft"
    )
    exclude_sources = [minecraft_source_name]
    notice_target = _build_notice_target(
        config.get_keys(["connector", "QQ", "permissions", "notice_forward_groups"], [])
    )

    async def on_player_join(server: PluginServerInterface, info: Info) -> None:
        join_patterns = config.get_keys(
            ["connector", "minecraft", "player_join_patterns"], []
        )
        player_name = _match_player_name(info.content, join_patterns)
        if player_name is None:
            return

        cooldown = _get_cooldown(config)
        _cancel_pending_leave(player_name)

        # 刚离开又重进：不发加入通知（冷却期内多条加入日志也会被挡住）
        if _in_leave_cooldown(player_name, cooldown):
            return
        # 已经发过加入通知：忽略 logged in / joined the game 等重复日志
        if player_name in _join_announced:
            return

        if not _notice_enabled(
                player_name, config, "player_join_notice", "bot_join_notice"
        ):
            return

        message = server.tr("gugubot.notice.player_join", player=player_name)
        await _broadcast_notice(
            server,
            connector_manager,
            minecraft_source_name,
            exclude_sources,
            notice_target,
            message,
        )
        _join_announced.add(player_name)

    return on_player_join


def create_on_player_left(
        connector_manager: ConnectorManager, config: BotConfig
) -> Callable[[PluginServerInterface, Info], None]:
    minecraft_source_name = config.get_keys(
        ["connector", "minecraft", "source_name"], "Minecraft"
    )
    exclude_sources = [minecraft_source_name]
    notice_target = _build_notice_target(
        config.get_keys(["connector", "QQ", "permissions", "notice_forward_groups"], [])
    )

    async def on_player_left(server: PluginServerInterface, info: Info) -> None:
        left_patterns = config.get_keys(
            ["connector", "minecraft", "player_left_patterns"], []
        )
        player_name = _match_player_name(info.content, left_patterns)
        if player_name is None:
            return

        if not _notice_enabled(
                player_name, config, "player_left_notice", "bot_left_notice"
        ):
            _join_announced.discard(player_name)
            return

        cooldown = _get_cooldown(config)
        _leave_at[player_name] = time.monotonic()
        if player_name in _pending_leaves:
            return

        if cooldown <= 0:
            message = server.tr("gugubot.notice.player_left", player=player_name)
            await _broadcast_notice(
                server,
                connector_manager,
                minecraft_source_name,
                exclude_sources,
                notice_target,
                message,
            )
            _join_announced.discard(player_name)
            return

        async def _delayed_leave() -> None:
            try:
                await asyncio.sleep(cooldown)
                message = server.tr(
                    "gugubot.notice.player_left_delayed",
                    player=player_name,
                    duration=_format_duration(cooldown),
                )
                await _broadcast_notice(
                    server,
                    connector_manager,
                    minecraft_source_name,
                    exclude_sources,
                    notice_target,
                    message,
                )
                _join_announced.discard(player_name)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_delayed_leave())
        _pending_leaves[player_name] = task

        def _cleanup(done: asyncio.Task) -> None:
            if _pending_leaves.get(player_name) is done:
                _pending_leaves.pop(player_name, None)

        task.add_done_callback(_cleanup)

    return on_player_left


def is_bot(player_name: str, config: BotConfig) -> bool:
    """判断玩家是否为机器人。

    Parameters
    ----------
    player_name : str
        玩家名称
    config : BotConfig
        配置对象

    Returns
    -------
    bool
        如果是机器人返回True，否则返回False
    """
    bot_patterns = config.get_keys(["connector", "minecraft", "bot_names_pattern"], [])

    for pattern in bot_patterns:
        try:
            if re.match(pattern, player_name, re.IGNORECASE):
                return True
        except re.error:
            continue

    return False
