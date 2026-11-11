"""open-qq-bot 连接器集成测试。

运行方式（需插件依赖，见 AGENTS.md；MCDR 事件循环以 FakeServer 桩替代）：

    uv run --with mcdreforged --with requests --with ruamel-yaml --with pyyaml \
        --with websocket-client --with websocket-server --with mcstatus \
        PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot -v
"""

import sys
import os
import importlib.util

# 防护：Windows 下目录枚举可能瞬时失败（杀软/同步扫描新写入文件），
# 导致该路径的 FileFinder 缓存被污染为空、进程内该路径导入持续失败。
# 直接以文件位置注册 gugubet 包（绕过 finder 缓存），子模块走包 __path__ 正常解析。
_GUGUBOT_SRC = r"E:\Project\PF-GUGUBot\GUGUbot"
if _GUGUBOT_SRC not in sys.path:
    sys.path.insert(0, _GUGUBOT_SRC)


def _force_register_gugubet():
    init_path = os.path.join(_GUGUBOT_SRC, "gugubot", "__init__.py")
    spec = importlib.util.spec_from_file_location("gugubet", init_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gugubet"] = module
    spec.loader.exec_module(module)
    importlib.invalidate_caches()
    return module


try:
    from gugubet.connector import OpenQQBotConnector as _probe  # noqa: F401
except ModuleNotFoundError:
    _force_register_gugubet()
    from gugubet.connector import OpenQQBotConnector as _probe  # noqa: F401

import asyncio
import unittest
import yaml
from pathlib import Path

from gugubot.connector import OpenQQBotConnector
from gugubet.connector.open_qq_bot.parser import OpenQQBotParser
from gugubet.connector.open_qq_bot.common import QuotaManager
from gugubet.utils.types import BroadcastInfo, ProcessedInfo, Source

REPO = Path(__file__).resolve().parent.parent
import sys as _sys
print("DEBUG sys.path[0:3]:", _sys.path[:3], flush=True)
print("DEBUG gugubet in sys.modules:", "gugubet" in _sys.modules, flush=True)
GROUP_OID = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
USER_OID = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
MEMBER_OID = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
BOT_OID = "1D9C431B7A590DD991BBB564DF11044D"


class FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        print("LOG-ERROR:", a, k)

    def debug(self, *a, **k):
        pass


class FakeServer:
    logger = FakeLogger()
    scheduled = []

    def tr(self, key, **kw):
        return key

    def schedule_task(self, coro):
        FakeServer.scheduled.append(coro)
        coro.close()


class FakeManager:
    def __init__(self):
        self.system_manager = object()


class FakeConfig(dict):
    def get_keys(self, keys, default=None):
        result = self
        for k in keys[:-1]:
            result = result.get(k, {})
        return result.get(keys[-1], default)


class FakeApi:
    """记录发送调用的 API 桩；send 对被动过期场景由用例自行注入异常。"""

    def __init__(self):
        self.sent = []

    def send_group_text(self, g, c, msg_id=None, event_id=None, reference=None):
        self.sent.append(("text", g, c, msg_id))
        return {"id": "RID"}

    def send_group_markdown(self, g, c, msg_id=None, reference=None):
        self.sent.append(("markdown", g, c, msg_id))
        return {"id": "RID"}

    def send_c2c_text(self, u, c, msg_id=None):
        self.sent.append(("c2c", u, c, msg_id))
        return {"id": "RID"}


def default_config(**overrides):
    section = {
        "enable": True,
        "source_name": "OpenQQBot",
        "connection": {"app_id": "a", "app_secret": "b", "sandbox": True},
        "permissions": {"admin_ids": [], "group_ids": [GROUP_OID],
                        "forward_group_ids": []},
    }
    section.update(overrides)
    return FakeConfig({"connector": {"open-qq-bot": section}})


def build_connector(config=None):
    conn = OpenQQBotConnector(FakeServer(), config or default_config())
    conn.connector_manager = FakeManager()
    conn.logger = FakeLogger()
    return conn


def group_event(content="/userId", mentions=None, member=MEMBER_OID, msg_id="MSG1"):
    return {
        "t": "GROUP_MESSAGE_CREATE",
        "d": {
            "id": msg_id,
            "group_openid": GROUP_OID,
            "author": {"bot": False, "member_openid": member, "id": member,
                       "username": "昏暗槐花", "member_role": "owner"},
            "content": content,
            "mentions": mentions or [],
            "attachments": [],
            "message_scene": {"ext": []},
        },
        "event_id": None,
    }


class TestConfig(unittest.TestCase):
    def test_default_config_yaml_valid(self):
        path = REPO / "GUGUbot" / "gugubot" / "config" / "defaults" / "default_config.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        section = data["connector"]["open-qq-bot"]
        self.assertIs(section["enable"], False)
        self.assertEqual(section["connection"]["app_id"], "")
        self.assertIn("group_ids", section["permissions"])

    def test_lang_files_symmetric(self):
        for name in ("zh_cn.yml", "en_us.yml"):
            path = REPO / "GUGUbot" / "lang" / name
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            connector = data["gugubot"]["connector"]
            self.assertIn("name", connector)  # en_us 曾缺失
            block = connector["open-qq-bot"]
            for key in ("try_connect", "connect_success", "closed", "disabled",
                        "not_configured"):
                self.assertIn(key, block)


class TestParser(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn = build_connector()
        self.parser = OpenQQBotParser(self.conn)

    async def test_group_event_to_broadcast_info(self):
        event = group_event(
            content=f"<@{BOT_OID}> 你好",
            mentions=[{"member_openid": BOT_OID, "id": BOT_OID,
                       "username": "林晚晴", "bot": True}],
        )
        info = await self.parser.parse(event)
        self.assertIsNotNone(info)
        self.assertEqual(info.event_sub_type, "group")
        self.assertEqual(info.source_id, GROUP_OID)
        self.assertTrue(info.is_admin)  # member_role=owner
        self.assertEqual(info._source.origin, "OpenQQBot")
        self.assertIn("@林晚晴", info.message[0]["data"]["text"])

    async def test_whitelist_filter(self):
        config = default_config(permissions={"admin_ids": [], "group_ids": ["OTHER"],
                                             "forward_group_ids": []})
        parser = OpenQQBotParser(build_connector(config))
        self.assertIsNone(await parser.parse(group_event()))

    async def test_image_attachment_segment(self):
        event = group_event(content="")
        event["d"]["attachments"] = [{"content_type": "image/jpeg",
                                      "url": "https://x/y.jpg"}]
        info = await self.parser.parse(event)
        self.assertEqual([s["type"] for s in info.message], ["image"])

    async def test_bot_self_skipped(self):
        event = group_event()
        event["d"]["author"]["bot"] = True
        self.assertIsNone(await self.parser.parse(event))

    async def test_c2c_event(self):
        event = {"t": "C2C_MESSAGE_CREATE", "d": {
            "id": "C1",
            "author": {"bot": False, "user_openid": USER_OID, "id": USER_OID,
                       "username": "好友"},
            "content": "hi",
        }, "event_id": None}
        info = await self.parser.parse(event)
        self.assertEqual(info.event_sub_type, "private")
        self.assertEqual(info.source_id, USER_OID)


class TestOutbound(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn = build_connector()
        self.api = FakeApi()
        self.conn.api = self.api

    def test_markdown_with_prefix_and_images(self):
        p = ProcessedInfo(
            processed_message=[{"type": "text", "data": {"text": "§ahello"}},
                               {"type": "image", "data": {"file": "https://i/x.png"}}],
            _source=Source("QQ"), source_id="whatever", sender="Steve",
        )
        asyncio.run(self.conn.send_message(p))
        kind, group, content, _ = self.api.sent[0]
        self.assertEqual((kind, group), ("markdown", GROUP_OID))
        self.assertIn("hello", content)
        self.assertNotIn("§a", content)
        self.assertIn("![图片](https://i/x.png)", content)
        self.assertIn("Steve", content)  # 跨源前缀

    def test_digit_target_skipped(self):
        p = ProcessedInfo(processed_message=[{"type": "text", "data": {"text": "hi"}}],
                          _source=Source("MC"), source_id="mc", sender="mc")
        p.target = {"123456": "group"}  # OneBot 领地
        asyncio.run(self.conn.send_message(p))
        self.assertEqual(self.api.sent, [])

    def test_reply_origin_keyed_target_mapped_to_source_id(self):
        """BasicSystem.reply 对非数字 source_id 用显示名做 target key，
        必须映射回触发消息的来源群（否则命令回复全部丢失）。"""
        p = ProcessedInfo(processed_message=[{"type": "text", "data": {"text": "回复"}}],
                          _source=Source("OpenQQBot"), source_id=GROUP_OID,
                          sender="bot", raw=group_event()["d"])
        p.target = {"OpenQQBot": "group"}  # reply() 的回退形态
        asyncio.run(self.conn.send_message(p))
        kind, group, content, msg_id = self.api.sent[0]
        self.assertEqual(group, GROUP_OID)
        self.assertEqual(msg_id, "MSG1")  # 同会话 → 被动回复锚点生效

    def test_passive_expired_falls_back_to_active(self):
        from gugubot.connector.open_qq_bot.common import ApiError

        def failing_send(g, c, msg_id=None, event_id=None, reference=None):
            if msg_id:  # 带锚点（被动）时模拟窗口失效
                raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)
            self.api.sent.append(("text", g, c, msg_id))
            return {"id": "RID"}

        self.api.send_group_text = failing_send
        p = ProcessedInfo(processed_message=[{"type": "text", "data": {"text": "hi"}}],
                          _source=Source("OpenQQBot"), source_id=GROUP_OID,
                          sender="bot", raw=group_event()["d"])
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        self.assertEqual(len(self.api.sent), 1)  # 降级为主动消息成功
        self.assertIsNone(self.api.sent[0][3])


class TestEventEntry(unittest.TestCase):
    def setUp(self):
        self.conn = build_connector()
        FakeServer.scheduled.clear()

    def test_dedup_and_bot_self_skip(self):
        event = group_event()
        self.conn._on_gateway_event(event["t"], event["d"], None)
        self.conn._on_gateway_event(event["t"], event["d"], None)  # 重复推送
        self.conn._on_gateway_event(
            "C2C_MESSAGE_CREATE",
            {"id": "m2", "author": {"bot": True, "user_openid": "B"}, "content": "x"},
            None,
        )
        self.assertEqual(len(FakeServer.scheduled), 1)

    def test_unknown_event_ignored(self):
        self.conn._on_gateway_event("SOMETHING_ELSE", {}, None)
        self.assertEqual(FakeServer.scheduled, [])

    def test_on_message_direct_injection(self):
        event = group_event()
        asyncio.run(self.conn.on_message(event))
        self.assertEqual(len(FakeServer.scheduled), 1)


class TestQuota(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "quota.json"

    def test_minute_and_day_limits(self):
        from gugubot.connector.open_qq_bot.common import QuotaManager
        q = QuotaManager(per_minute=2, per_day=3, persist_path=self.path)
        assert q.allow("G")
        assert q.allow("G")
        assert not q.allow("G")  # 分钟窗口耗尽
        q._state["G"]["minute"] = []  # 手动放行分钟窗口（模拟时间流逝）
        assert q.allow("G")
        assert not q.allow("G")  # 日配额耗尽（3/3）

    def test_day_reset_and_persistence(self):
        import time
        from gugubot.connector.open_qq_bot.common import QuotaManager
        q = QuotaManager(per_minute=5, per_day=1, persist_path=self.path)
        q.allow("G")
        assert not q.allow("G")
        # 模拟跨天：改写持久化日期
        st = q._state["G"]
        st["date"] = "2000-01-01"
        q._save()
        q2 = QuotaManager(per_minute=5, per_day=1, persist_path=self.path)
        assert q2.allow("G")  # 跨天重置 + 持久化恢复
        assert q2._state["G"]["day"] == 1

    def test_per_key_isolation(self):
        from gugubot.connector.open_qq_bot.common import QuotaManager
        q = QuotaManager(per_minute=1, per_day=10, persist_path=self.path)
        assert q.allow("A")
        assert not q.allow("A")
        assert q.allow("B")


class TestNoticeAndUnbind(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn = build_connector()
        self.parser = OpenQQBotParser(self.conn)

    async def test_member_remove_to_group_decrease(self):
        event = {"t": "GROUP_MEMBER_REMOVE", "d": {
            "group_openid": GROUP_OID, "member_openid": USER_OID, "timestamp": 1}}
        info = await self.parser.parse(event)
        self.assertIsNotNone(info)
        self.assertEqual(info.event_type, "notice")
        self.assertEqual(info.event_sub_type, "group_decrease")
        self.assertEqual(info.sender_id, USER_OID)

    async def test_quota_enforced_for_active_only(self):
        sent = []

        class OneShotApi(FakeApi):
            def send_group_text(self, g, c, msg_id=None, event_id=None, reference=None):
                sent.append(("text", g, msg_id))
                return {"id": "R"}

            def send_group_markdown(self, g, c, msg_id=None, reference=None):
                sent.append(("markdown", g, msg_id))
                return {"id": "R"}

        conn = build_connector()
        conn.api = OneShotApi()
        # 配额只允许 1 条主动消息（被动回复不占配额）
        conn.quota = QuotaManager(per_minute=1, per_day=100)

        def active(msg_id=None):
            p = ProcessedInfo(processed_message=[{"type": "text", "data": {"text": "hi"}}],
                              _source=Source("MC"), source_id="mc", sender="mc",
                              raw={"id": msg_id, "group_openid": GROUP_OID} if msg_id else None)
            p.target = {GROUP_OID: "group"}
            return conn.send_message(p)

        # 1) 带锚点 → 被动回复，不占配额，正常发送
        await active("MSG1")
        self.assertEqual(len(sent), 1)
        # 2) 被动过期 → 降级主动，占最后 1 个配额（day=99<100）
        import time as _t
        conn.quota._state[GROUP_OID] = {
            "date": _t.strftime("%Y-%m-%d"), "day": 99, "minute": [],
        }

        def expiring_send(g, c, msg_id=None, *a, **k):
            from gugubot.connector.open_qq_bot.common import ApiError
            if msg_id:
                raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)
            sent.append(("active-fallback", g, msg_id))
            return {"id": "R"}

        conn.api.send_group_markdown = expiring_send
        conn.api.send_group_text = expiring_send
        await active("MSG2")
        self.assertEqual(len(sent), 2)
        # 3) 无锚点且配额耗尽（day=100>=100）→ 丢弃
        await active(None)
        self.assertEqual(len(sent), 2)


class TestBoundOfficialQuit(unittest.IsolatedAsyncioTestCase):
    """open-qq-bot 退群解绑（bound 系统官方分支）。"""

    async def _run(self, accounts, player_name=" Steve "):
        from gugubot.logic.system.bound import BoundSystem
        from gugubot.utils.types import BroadcastInfo, Source as Src

        saved = {}

        class FakePlayers(dict):
            def __init__(self, players):
                super().__init__(players)

            def load(self):
                pass

            def save(self):
                saved.update(self)

            def get_player(self, key, platform="QQ"):
                # 真实 PlayerManager 支持按玩家名或平台账号反查
                if key in self:
                    return self[key]
                for player in self.values():
                    if key in player.accounts.get(platform, []):
                        return player
                return None

            def remove_player(self, name):
                self.pop(name, None)

        class FakePlayer:
            def __init__(self, accounts):
                self.name = "Steve"
                self.accounts = accounts
                self.java_name = ["Steve"]
                self.bedrock_name = []

        class FakeWhitelist:
            def __init__(self): self.removed = []
            def remove_player(self, names): self.removed.extend(names)
            def has_player(self, name): return False
            def __call__(self, name): return False

        players = FakePlayers({"Steve": FakePlayer(accounts)})
        conn = build_connector()
        fake_server = FakeServer()
        bs = BoundSystem.__new__(BoundSystem)
        bs.server = fake_server
        bs.logger = FakeLogger()
        bs.config = FakeConfig({
            "system": {"bound": {"whitelist_remove_with_leave": True}},
            "connector": {
                "QQ": {"permissions": {"group_ids": [], "admin_group_ids": []}},
                "open-qq-bot": {"permissions": {"group_ids": [GROUP_OID]}},
            },
        })
        bs.player_manager = players
        bs.whitelist = FakeWhitelist()
        bs.enable = True
        bs.name = "bound"
        bs.style_manager = None

        # 直接触发官方分支判定所需的条件
        info = BroadcastInfo(
            event_type="notice", event_sub_type="group_decrease",
            message=[{"type": "text", "data": {"text": ""}}],
            raw={"group_openid": GROUP_OID, "member_openid": USER_OID},
            server=fake_server, logger=FakeLogger(),
            _source=Src("OpenQQBot"), source_id=GROUP_OID,
            sender=USER_OID, sender_id=USER_OID,
        )
        handled = await bs.process_broadcast_info(info)
        return handled, players, bs

    async def test_official_quit_unbinds(self):
        handled, players, bs = await self._run(accounts={"QQ": [USER_OID]})
        self.assertTrue(handled)
        self.assertNotIn("Steve", players)  # 绑定已清除

    async def test_official_quit_keeps_other_platform(self):
        handled, players, bs = await self._run(accounts={"QQ": [USER_OID], "FPS": ["steve_fps"]})
        self.assertTrue(handled)
        self.assertIn("Steve", players)  # 其他平台绑定保留
        self.assertEqual(players["Steve"].accounts.get("QQ", []), [])


class TestKeyWordSkip(unittest.IsolatedAsyncioTestCase):
    """open-qq-bot 来源消息不做关键词回复（KeyWordSystem 跳过）。"""

    def _build(self, source_origin):
        import tempfile
        from gugubot.logic.system.key_word import KeyWordSystem
        tmp = tempfile.mkdtemp()
        server = FakeServer()
        server.get_data_folder = lambda: tmp
        config = FakeConfig({
            "connector": {"open-qq-bot": {"source_name": "OpenQQBot"}},
            "system": {"key_words": {"cache_image": False}},
        })
        system = KeyWordSystem(server, config)
        system.connector_manager = FakeManager()
        system.logger = FakeLogger()
        info = BroadcastInfo(
            event_type="message", event_sub_type="group",
            message=[{"type": "text", "data": {"text": "签到"}}],
            raw={}, server=server, logger=FakeLogger(),
            _source=Source(source_origin), source_id=GROUP_OID,
            sender="x", sender_id=USER_OID,
        )
        return system, info

    async def test_open_qq_bot_source_skipped(self):
        system, info = self._build("OpenQQBot")
        self.assertFalse(await system.process_broadcast_info(info))

    async def test_section_name_source_skipped(self):
        system, info = self._build("open-qq-bot")
        self.assertFalse(await system.process_broadcast_info(info))

    async def test_qq_source_still_processed(self):
        # QQ 来源：原逻辑不变（空关键词库 → 无命中返回 False，未误伤）
        system, info = self._build("QQ")
        self.assertFalse(await system.process_broadcast_info(info))


if __name__ == "__main__":
    unittest.main()
