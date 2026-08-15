# -*- coding: utf-8 -*-
"""GUGUBot 对外公开 API。

独立 MCDR 插件通过本模块注册 ``#命令``、回复原渠道、执行 RCON，
无需继承 BasicSystem 或改 GUGUBot 源码。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from mcdreforged.api.event import LiteralEvent
from mcdreforged.api.types import PluginServerInterface

from gugubot.config import BotConfig
from gugubot.utils.rcon_manager import RconManager

REGISTER_EVENT_ID = "gugubot.register"
REGISTER_EVENT = LiteralEvent(REGISTER_EVENT_ID)

CommandHandler = Callable[["CommandContext"], Any]


class CommandContext:
    """命令处理函数的唯一入参。"""

    def __init__(
        self,
        *,
        sender: str,
        sender_id: str,
        source: str,
        source_id: str,
        is_admin: bool,
        args: List[str],
        text: str,
        rcon_fn: Callable[[str], str],
    ) -> None:
        self.sender = sender
        self.sender_id = sender_id
        self.source = source
        self.source_id = source_id
        self.is_admin = is_admin
        self.args = args
        self.text = text
        self._rcon_fn = rcon_fn
        self._replies: List[str] = []

    def reply(self, text: str) -> None:
        """回复到消息原渠道（QQ 群/私聊或游戏聊天）。"""
        if text is None:
            return
        message = str(text)
        if message:
            self._replies.append(message)

    def rcon(self, command: str) -> str:
        """通过 RCON（或降级策略）执行服务器命令，返回结果文本。"""
        return self._rcon_fn(command)

    def pop_replies(self) -> List[str]:
        replies = self._replies
        self._replies = []
        return replies


class _CommandEntry:
    __slots__ = ("name", "handler", "aliases", "admin_only", "plugin_id")

    def __init__(
        self,
        name: str,
        handler: CommandHandler,
        aliases: Tuple[str, ...],
        admin_only: bool,
        plugin_id: str,
    ) -> None:
        self.name = name
        self.handler = handler
        self.aliases = aliases
        self.admin_only = admin_only
        self.plugin_id = plugin_id


class GUGUBotAPI:
    """稳定公开 API。不要把 connector_manager / SystemManager 当成对外接口。"""

    def __init__(
        self,
        server: PluginServerInterface,
        config: Optional[BotConfig] = None,
    ) -> None:
        self._server = server
        self._config = config
        self._rcon = RconManager(server)
        self._commands: Dict[str, _CommandEntry] = {}

    @property
    def command_prefix(self) -> str:
        if self._config is None:
            return "#"
        return self._config.get_keys(["GUGUBot", "command_prefix"], "#")

    def rcon(self, command: str) -> str:
        """无 CommandContext 时也可执行 RCON。"""
        return self._rcon.execute(command)

    def register_command(
        self,
        name: str,
        handler: CommandHandler,
        aliases: Union[str, Iterable[str]] = (),
        admin_only: bool = False,
        plugin_id: Optional[str] = None,
    ) -> bool:
        """注册一条 ``#命令``。

        命令名冲突时打 warning，保留先注册的处理函数。

        Returns
        -------
        bool
            主命令名注册成功为 True；主命令名已占用为 False。
        """
        command_name = (name or "").strip()
        if not command_name:
            self._server.logger.warning("[GUGUBot API] 忽略空命令名")
            return False
        if not callable(handler):
            self._server.logger.warning(
                f"[GUGUBot API] 命令 {self.command_prefix}{command_name} 的 handler 不可调用"
            )
            return False

        owner = plugin_id or "<unknown>"
        alias_tuple = _normalize_aliases(aliases)

        if command_name in self._commands:
            existing = self._commands[command_name]
            self._server.logger.warning(
                f"[GUGUBot API] 命令 {self.command_prefix}{command_name} 已被 "
                f"{existing.plugin_id} 注册，忽略来自 {owner} 的注册"
            )
            return False

        accepted_aliases: List[str] = []
        for alias in alias_tuple:
            if not alias or alias == command_name:
                continue
            if alias in self._commands:
                existing = self._commands[alias]
                self._server.logger.warning(
                    f"[GUGUBot API] 命令 {self.command_prefix}{alias} 已被 "
                    f"{existing.plugin_id} 注册，忽略来自 {owner} 的别名"
                )
                continue
            accepted_aliases.append(alias)

        entry = _CommandEntry(
            name=command_name,
            handler=handler,
            aliases=tuple(accepted_aliases),
            admin_only=admin_only,
            plugin_id=owner,
        )
        self._commands[command_name] = entry
        for alias in accepted_aliases:
            self._commands[alias] = entry
        return True

    def unregister_plugin(self, plugin_id: str) -> None:
        """注销某插件注册的全部命令。"""
        if not plugin_id:
            return
        stale = [key for key, entry in self._commands.items() if entry.plugin_id == plugin_id]
        for key in stale:
            self._commands.pop(key, None)

    def lookup(self, name: str) -> Optional[_CommandEntry]:
        return self._commands.get(name)

    def clear(self) -> None:
        self._commands.clear()

    def for_plugin(self, plugin_id: str) -> "_BoundGUGUBotAPI":
        return _BoundGUGUBotAPI(self, plugin_id)


class _BoundGUGUBotAPI:
    """给外部插件用的代理：自动填上 plugin_id。"""

    def __init__(self, api: GUGUBotAPI, plugin_id: str) -> None:
        self._api = api
        self._plugin_id = plugin_id

    def register_command(
        self,
        name: str,
        handler: CommandHandler,
        aliases: Union[str, Iterable[str]] = (),
        admin_only: bool = False,
        plugin_id: Optional[str] = None,
    ) -> bool:
        return self._api.register_command(
            name,
            handler,
            aliases=aliases,
            admin_only=admin_only,
            plugin_id=plugin_id or self._plugin_id,
        )

    def unregister_plugin(self, plugin_id: Optional[str] = None) -> None:
        self._api.unregister_plugin(plugin_id or self._plugin_id)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._api, item)


def _normalize_aliases(aliases: Union[str, Iterable[str]]) -> Tuple[str, ...]:
    if not aliases:
        return ()
    if isinstance(aliases, str):
        name = aliases.strip()
        return (name,) if name else ()
    result: List[str] = []
    for alias in aliases:
        name = str(alias).strip()
        if name:
            result.append(name)
    return tuple(result)


def _get_api(server: PluginServerInterface) -> Optional[GUGUBotAPI]:
    instance = server.get_plugin_instance("gugubot")
    if instance is None:
        return None
    api = getattr(instance, "api", None)
    return api if isinstance(api, GUGUBotAPI) else None


def bind_plugin(
    server: PluginServerInterface,
    plugin_id: str,
    setup: Callable[[GUGUBotAPI], None],
) -> Callable[[], None]:
    """把外部插件挂到 GUGUBot API 上。

    1. GUGUBot 已加载则立刻 ``setup(api)``
    2. 监听 ``gugubot.register``，以便 GUGUBot 后加载或热重载时再注册
    3. 本插件卸载时自动注销命令

    Returns
    -------
    Callable[[], None]
        可在 ``on_unload`` 中调用的清理函数（重复调用安全）。
    """

    def apply(api: Optional[GUGUBotAPI] = None) -> None:
        target = api if isinstance(api, GUGUBotAPI) else _get_api(server)
        if target is None:
            return
        target.unregister_plugin(plugin_id)
        setup(target.for_plugin(plugin_id))

    def unbind() -> None:
        target = _get_api(server)
        if target is not None:
            target.unregister_plugin(plugin_id)

    apply()
    server.register_event_listener(REGISTER_EVENT, lambda _s, event_api: apply(event_api))
    try:
        from mcdreforged.api.event import MCDRPluginEvents

        server.register_event_listener(MCDRPluginEvents.PLUGIN_UNLOADED, lambda *_args: unbind())
    except Exception:
        server.register_event_listener("mcdr.plugin_unloaded", lambda *_args: unbind())

    return unbind


__all__ = [
    "CommandContext",
    "GUGUBotAPI",
    "REGISTER_EVENT",
    "REGISTER_EVENT_ID",
    "bind_plugin",
]
