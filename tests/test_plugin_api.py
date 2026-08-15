# -*- coding: utf-8 -*-
"""GUGUBot 外部插件 API 测试。

用 importlib 按文件加载，避免执行 gugubot/__init__.py（会导入 websocket）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


_ROOT = Path(__file__).resolve().parents[1] / "GUGUbot"
_PKG_DIR = _ROOT / "gugubot"
_API_PATH = _PKG_DIR / "api.py"
if not _API_PATH.exists():
    _API_PATH = _PKG_DIR / "API.py"
_PLUGIN_COMMANDS_PATH = _PKG_DIR / "logic" / "system" / "plugin_commands.py"


class _FakeConfig(dict):
    def get_keys(self, keys, default=None):
        current = self
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current


class _FakeServer:
    def __init__(self, plugin=None):
        self.logger = MagicMock()
        self.listeners = []
        self.plugin = plugin
        self.is_rcon_running = MagicMock(return_value=False)
        self.execute = MagicMock()
        self.execute_command = MagicMock()
        self.rcon_query = MagicMock(return_value="")

    def get_plugin_instance(self, name):
        if name == "gugubot":
            return self.plugin
        return None

    def register_event_listener(self, event, callback):
        self.listeners.append((event, callback))


class _Broadcast:
    def __init__(
        self,
        text,
        *,
        sender="Steve",
        sender_id="10001",
        source="QQ",
        source_id="123456",
        is_admin=False,
        event_type="message",
    ):
        self.event_type = event_type
        self.message = [{"type": "text", "data": {"text": text}}]
        self.sender = sender
        self.sender_id = sender_id
        self.source_id = source_id
        self.is_admin = is_admin
        self.source = SimpleNamespace(origin=source)


def _event_id(event):
    return getattr(event, "event_id", event)


def _install_stubs():
    if "gugubot.api" in sys.modules:
        return sys.modules["gugubot.api"], sys.modules["gugubot.logic.system.plugin_commands"]

    literal_mod = types.ModuleType("mcdreforged.api.event")

    class LiteralEvent:
        def __init__(self, event_id):
            self.event_id = event_id

        def __eq__(self, other):
            return isinstance(other, LiteralEvent) and other.event_id == self.event_id

        def __hash__(self):
            return hash(self.event_id)

    class MCDRPluginEvents:
        PLUGIN_UNLOADED = LiteralEvent("mcdr.plugin_unloaded")

    literal_mod.LiteralEvent = LiteralEvent
    literal_mod.MCDRPluginEvents = MCDRPluginEvents

    types_mod = types.ModuleType("mcdreforged.api.types")
    types_mod.PluginServerInterface = object

    api_pkg = types.ModuleType("mcdreforged.api")
    mcdreforged = types.ModuleType("mcdreforged")
    sys.modules["mcdreforged"] = mcdreforged
    sys.modules["mcdreforged.api"] = api_pkg
    sys.modules["mcdreforged.api.event"] = literal_mod
    sys.modules["mcdreforged.api.types"] = types_mod

    gugubot = types.ModuleType("gugubot")
    gugubot.__path__ = [str(_PKG_DIR)]
    sys.modules["gugubot"] = gugubot

    config_mod = types.ModuleType("gugubot.config")
    config_mod.BotConfig = _FakeConfig
    sys.modules["gugubot.config"] = config_mod

    utils_pkg = types.ModuleType("gugubot.utils")
    utils_pkg.__path__ = [str(_PKG_DIR / "utils")]
    sys.modules["gugubot.utils"] = utils_pkg

    rcon_mod = types.ModuleType("gugubot.utils.rcon_manager")

    class RconManager:
        def __init__(self, server):
            self.server = server

        def execute(self, command, use_mcdr_command=False):
            return f"RCON:{command}"

    rcon_mod.RconManager = RconManager
    sys.modules["gugubot.utils.rcon_manager"] = rcon_mod

    builder_mod = types.ModuleType("gugubot.builder")

    class MessageBuilder:
        @staticmethod
        def text(text):
            return {"type": "text", "data": {"text": text}}

    builder_mod.MessageBuilder = MessageBuilder
    sys.modules["gugubot.builder"] = builder_mod

    utils_types = types.ModuleType("gugubot.utils.types")
    utils_types.BroadcastInfo = _Broadcast
    sys.modules["gugubot.utils.types"] = utils_types

    logic_pkg = types.ModuleType("gugubot.logic")
    logic_pkg.__path__ = [str(_PKG_DIR / "logic")]
    sys.modules["gugubot.logic"] = logic_pkg
    system_pkg = types.ModuleType("gugubot.logic.system")
    system_pkg.__path__ = [str(_PKG_DIR / "logic" / "system")]
    sys.modules["gugubot.logic.system"] = system_pkg

    basic_mod = types.ModuleType("gugubot.logic.system.basic_system")

    class BasicSystem:
        GROUP_ADMIN_BYPASS_SYSTEMS = {"bound", "plugin_commands"}

        def __init__(self, name, enable=True, config=None):
            self.name = name
            self.enable = enable
            self.config = config
            self.logger = None
            self.system_manager = None
            self.replies = []

        def is_command(self, broadcast_info):
            if broadcast_info.event_type != "message":
                return False
            message = broadcast_info.message
            if not message or message[0].get("type") != "text":
                return False
            content = message[0].get("data", {}).get("text", "")
            prefix = "#"
            if self.config is not None:
                prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
            if not content.startswith(prefix):
                return False
            group_admin = False
            if self.config is not None:
                group_admin = self.config.get_keys(["GUGUBot", "group_admin"], False)
            if (
                group_admin
                and not broadcast_info.is_admin
                and self.name not in self.GROUP_ADMIN_BYPASS_SYSTEMS
            ):
                return False
            return True

        async def reply_to_source(self, broadcast_info, message):
            self.replies.append(message)

        def get_tr(self, key, global_key=False, **kwargs):
            if key == "no_permission":
                return "权限不足"
            return key

    basic_mod.BasicSystem = BasicSystem
    sys.modules["gugubot.logic.system.basic_system"] = basic_mod

    api_spec = importlib.util.spec_from_file_location("gugubot.api", _API_PATH)
    api_mod = importlib.util.module_from_spec(api_spec)
    sys.modules["gugubot.api"] = api_mod
    api_spec.loader.exec_module(api_mod)

    pcs_spec = importlib.util.spec_from_file_location(
        "gugubot.logic.system.plugin_commands", _PLUGIN_COMMANDS_PATH
    )
    pcs_mod = importlib.util.module_from_spec(pcs_spec)
    sys.modules["gugubot.logic.system.plugin_commands"] = pcs_mod
    pcs_spec.loader.exec_module(pcs_mod)

    return api_mod, pcs_mod


_api_mod, _pcs_mod = _install_stubs()
GUGUBotAPI = _api_mod.GUGUBotAPI
CommandContext = _api_mod.CommandContext
bind_plugin = _api_mod.bind_plugin
REGISTER_EVENT_ID = _api_mod.REGISTER_EVENT_ID
PluginCommandSystem = _pcs_mod.PluginCommandSystem


def _run(coro):
    return asyncio.run(coro)


class TestCommandContext(unittest.TestCase):
    def _ctx(self):
        return CommandContext(
            sender="Steve",
            sender_id="10001",
            source="QQ",
            source_id="123456",
            is_admin=False,
            args=["a", "b"],
            text="hello a b",
            rcon_fn=lambda cmd: f"RCON:{cmd}",
        )

    def test_reply_and_pop(self):
        ctx = self._ctx()
        ctx.reply("第一句")
        ctx.reply("")
        ctx.reply(None)
        ctx.reply("第二句")
        self.assertEqual(ctx.pop_replies(), ["第一句", "第二句"])
        self.assertEqual(ctx.pop_replies(), [])

    def test_rcon(self):
        ctx = self._ctx()
        self.assertEqual(ctx.rcon("seed"), "RCON:seed")


class TestGUGUBotAPI(unittest.TestCase):
    def setUp(self):
        self.server = _FakeServer()
        self.api = GUGUBotAPI(self.server)

    def test_default_prefix(self):
        self.assertEqual(self.api.command_prefix, "#")

    def test_custom_prefix(self):
        config = _FakeConfig({"GUGUBot": {"command_prefix": "!"}})
        api = GUGUBotAPI(self.server, config)
        self.assertEqual(api.command_prefix, "!")

    def test_register_and_lookup(self):
        def on_hello(ctx):
            return "hi"

        self.assertTrue(self.api.register_command("hello", on_hello, plugin_id="p1"))
        entry = self.api.lookup("hello")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.plugin_id, "p1")
        self.assertFalse(entry.admin_only)

    def test_reject_empty_and_non_callable(self):
        self.assertFalse(self.api.register_command("  ", lambda ctx: None, plugin_id="p1"))
        self.assertFalse(self.api.register_command("hello", "not-a-fn", plugin_id="p1"))
        self.assertIsNone(self.api.lookup("hello"))

    def test_conflict_keeps_first(self):
        def first(ctx):
            return "first"

        def second(ctx):
            return "second"

        self.assertTrue(self.api.register_command("hello", first, plugin_id="p1"))
        self.assertFalse(self.api.register_command("hello", second, plugin_id="p2"))
        self.assertEqual(self.api.lookup("hello").plugin_id, "p1")
        self.server.logger.warning.assert_called()

    def test_alias_conflict_keeps_primary(self):
        def one(ctx):
            return "1"

        def two(ctx):
            return "2"

        self.api.register_command("hello", one, plugin_id="p1")
        self.assertTrue(
            self.api.register_command("hi", two, aliases=("hello", "你好"), plugin_id="p2")
        )
        self.assertEqual(self.api.lookup("hello").plugin_id, "p1")
        self.assertEqual(self.api.lookup("hi").plugin_id, "p2")
        self.assertEqual(self.api.lookup("你好").plugin_id, "p2")

    def test_unregister_plugin_and_clear(self):
        self.api.register_command("hello", lambda ctx: "a", aliases=("hi",), plugin_id="p1")
        self.api.register_command("seed", lambda ctx: "b", plugin_id="p2")
        self.api.unregister_plugin("p1")
        self.assertIsNone(self.api.lookup("hello"))
        self.assertIsNone(self.api.lookup("hi"))
        self.assertIsNotNone(self.api.lookup("seed"))
        self.api.clear()
        self.assertIsNone(self.api.lookup("seed"))

    def test_for_plugin_fills_plugin_id(self):
        bound = self.api.for_plugin("hello_gugu")
        bound.register_command("hello", lambda ctx: "hi")
        self.assertEqual(self.api.lookup("hello").plugin_id, "hello_gugu")
        bound.unregister_plugin()
        self.assertIsNone(self.api.lookup("hello"))

    def test_rcon_without_context(self):
        self.assertEqual(self.api.rcon("list"), "RCON:list")


class TestBindPlugin(unittest.TestCase):
    def test_setup_immediately_when_gugubot_loaded(self):
        server = _FakeServer()
        api = GUGUBotAPI(server)
        server.plugin = SimpleNamespace(api=api)
        seen = []

        def setup(bound):
            seen.append(bound)
            bound.register_command("hello", lambda ctx: "hi")

        unbind = bind_plugin(server, "hello_gugu", setup)
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(api.lookup("hello"))
        event_ids = [_event_id(event) for event, _ in server.listeners]
        self.assertIn(REGISTER_EVENT_ID, event_ids)
        self.assertIn("mcdr.plugin_unloaded", event_ids)

        unbind()
        self.assertIsNone(api.lookup("hello"))
        unbind()

    def test_waits_for_register_event(self):
        server = _FakeServer()
        seen = []

        def setup(bound):
            seen.append(True)
            bound.register_command("hello", lambda ctx: "hi")

        bind_plugin(server, "hello_gugu", setup)
        self.assertEqual(seen, [])

        api = GUGUBotAPI(server)
        server.plugin = SimpleNamespace(api=api)
        callback = next(
            cb for event, cb in server.listeners if _event_id(event) == REGISTER_EVENT_ID
        )
        callback(server, api)
        self.assertEqual(seen, [True])
        self.assertEqual(api.lookup("hello").plugin_id, "hello_gugu")

    def test_reload_reregisters(self):
        server = _FakeServer()
        api = GUGUBotAPI(server)
        server.plugin = SimpleNamespace(api=api)

        def setup(bound):
            bound.register_command("hello", lambda ctx: "hi")

        bind_plugin(server, "hello_gugu", setup)
        api.clear()
        self.assertIsNone(api.lookup("hello"))

        callback = next(
            cb for event, cb in server.listeners if _event_id(event) == REGISTER_EVENT_ID
        )
        callback(server, api)
        self.assertIsNotNone(api.lookup("hello"))


class TestPluginCommandSystem(unittest.TestCase):
    def setUp(self):
        self.server = _FakeServer()
        self.config = _FakeConfig({"GUGUBot": {"command_prefix": "#"}})
        self.api = GUGUBotAPI(self.server, self.config)
        self.system = PluginCommandSystem(self.server, self.api, config=self.config)

    def test_unknown_command_not_consumed(self):
        consumed = _run(self.system.process_broadcast_info(_Broadcast("#unknown")))
        self.assertFalse(consumed)
        self.assertEqual(self.system.replies, [])

    def test_non_command_ignored(self):
        consumed = _run(self.system.process_broadcast_info(_Broadcast("hello")))
        self.assertFalse(consumed)

    def test_return_str_auto_reply(self):
        self.api.register_command(
            "hello", lambda ctx: f"你好，{ctx.sender}", plugin_id="p1"
        )
        consumed = _run(self.system.process_broadcast_info(_Broadcast("#hello")))
        self.assertTrue(consumed)
        self.assertEqual(
            self.system.replies,
            [[{"type": "text", "data": {"text": "你好，Steve"}}]],
        )

    def test_ctx_reply_and_args(self):
        captured = {}

        def on_hello(ctx):
            captured["args"] = list(ctx.args)
            captured["text"] = ctx.text
            captured["source"] = ctx.source
            ctx.reply("手动回复")

        self.api.register_command("hello", on_hello, plugin_id="p1")
        consumed = _run(self.system.process_broadcast_info(_Broadcast("#hello a b")))
        self.assertTrue(consumed)
        self.assertEqual(captured["args"], ["a", "b"])
        self.assertEqual(captured["text"], "hello a b")
        self.assertEqual(captured["source"], "QQ")
        self.assertEqual(
            self.system.replies,
            [[{"type": "text", "data": {"text": "手动回复"}}]],
        )

    def test_admin_only_denied(self):
        self.api.register_command(
            "种子", lambda ctx: ctx.rcon("seed"), admin_only=True, plugin_id="p1"
        )
        consumed = _run(
            self.system.process_broadcast_info(_Broadcast("#种子", is_admin=False))
        )
        self.assertTrue(consumed)
        self.assertEqual(
            self.system.replies,
            [[{"type": "text", "data": {"text": "权限不足"}}]],
        )

    def test_admin_only_allowed_uses_rcon(self):
        self.api.register_command(
            "种子", lambda ctx: ctx.rcon("seed"), admin_only=True, plugin_id="p1"
        )
        consumed = _run(
            self.system.process_broadcast_info(_Broadcast("#种子", is_admin=True))
        )
        self.assertTrue(consumed)
        self.assertEqual(
            self.system.replies,
            [[{"type": "text", "data": {"text": "RCON:seed"}}]],
        )

    def test_async_handler(self):
        async def on_hello(ctx):
            return "async-hi"

        self.api.register_command("hello", on_hello, plugin_id="p1")
        consumed = _run(self.system.process_broadcast_info(_Broadcast("#hello")))
        self.assertTrue(consumed)
        self.assertEqual(
            self.system.replies,
            [[{"type": "text", "data": {"text": "async-hi"}}]],
        )

    def test_handler_error_is_consumed(self):
        def boom(ctx):
            raise RuntimeError("boom")

        self.api.register_command("hello", boom, plugin_id="p1")
        consumed = _run(self.system.process_broadcast_info(_Broadcast("#hello")))
        self.assertTrue(consumed)
        self.assertEqual(self.system.replies, [])
        self.server.logger.error.assert_called()

    def test_alias_dispatch(self):
        self.api.register_command(
            "hello", lambda ctx: "hi", aliases=("你好",), plugin_id="p1"
        )
        consumed = _run(self.system.process_broadcast_info(_Broadcast("#你好")))
        self.assertTrue(consumed)
        self.assertEqual(
            self.system.replies,
            [[{"type": "text", "data": {"text": "hi"}}]],
        )


if __name__ == "__main__":
    unittest.main()
