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
from gugubet.utils.types import ProcessedInfo, Source

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
        if not kw:
            return key
        # 测试桩：带参数时把 kwargs 附加在 key 后，便于用例断言回复内容
        return key + "|" + ",".join(f"{k}={v}" for k, v in kw.items())

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
        self.assertNotIn("intents", section["connection"])  # 订阅位掩码固定在代码中
        self.assertIn("group_ids", section["permissions"])

    def test_intents_fixed_in_code(self):
        """配置里写了 intents 也不生效：位掩码由代码常量决定。"""
        from gugubot.connector.open_qq_bot.common import INTENTS

        self.assertEqual(INTENTS, (1 << 25) | (1 << 24))
        config = default_config(
            connection={"app_id": "a", "app_secret": "b",
                        "sandbox": True, "intents": 1}
        )
        conn = build_connector(config)
        self.assertEqual(conn.intents, INTENTS)
        self.assertEqual(conn.gateway.intents, INTENTS)

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
        event = group_event(content="hello")
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
        event = group_event(content="hello")
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


class TestDebugCommands(unittest.TestCase):
    """/groupId /userId /botId 连接器级调试命令（广播管线前拦截）。"""

    def setUp(self):
        self.conn = build_connector()
        self.api = FakeApi()
        self.conn.api = self.api

    def _d(self, content="/groupId", mentions=None, t="GROUP_MESSAGE_CREATE",
           msg_id="MSGD", group=GROUP_OID):
        return t, {
            "id": msg_id,
            "group_openid": group,
            "author": {"member_openid": MEMBER_OID, "username": "一梦"},
            "content": content,
            "mentions": mentions or [],
        }

    def test_group_id(self):
        t, d = self._d("/groupId")
        self.assertTrue(self.conn._try_debug_command(t, d))
        self.assertEqual(len(self.api.sent), 1)
        kind, chat, text, msg_id = self.api.sent[0]
        self.assertEqual((kind, chat, msg_id), ("text", GROUP_OID, "MSGD"))
        self.assertIn(f"group_id={GROUP_OID}", text)

    def test_group_id_with_at_prefix(self):
        t, d = self._d(
            f"<@{BOT_OID}> /groupId ",
            mentions=[{"id": BOT_OID, "bot": True, "username": "林晚晴"}],
        )
        # 真实链路中 _on_gateway_event 先习得 OpenID 再尝试拦截
        self.conn._learn_bot_openid(d)
        self.assertTrue(self.conn._try_debug_command(t, d))
        self.assertEqual(self.api.sent[0][1], GROUP_OID)
        self.assertEqual(self.conn.bot_openid, BOT_OID)

    def test_user_id_with_mention(self):
        t, d = self._d(
            "/userId @一梦",
            mentions=[{"member_openid": USER_OID, "username": "一梦"}],
        )
        self.assertTrue(self.conn._try_debug_command(t, d))
        self.assertIn(f"user_id={USER_OID}", self.api.sent[0][2])

    def test_user_id_usage_without_mention(self):
        t, d = self._d("/userId")
        self.assertTrue(self.conn._try_debug_command(t, d))
        self.assertIn("debug_user_id_usage", self.api.sent[0][2])

    def test_user_id_multi_mentions(self):
        t, d = self._d(
            "/userId @a @b",
            mentions=[{"member_openid": USER_OID, "username": "a"},
                      {"member_openid": MEMBER_OID, "username": "b"}],
        )
        self.assertTrue(self.conn._try_debug_command(t, d))
        self.assertIn("debug_user_id_multi", self.api.sent[0][2])

    def test_bot_id_unknown_then_learned(self):
        t, d = self._d("/botId")
        self.assertTrue(self.conn._try_debug_command(t, d))
        self.assertIn("debug_bot_id_unknown", self.api.sent[0][2])
        # 被 @ 后习得自身 OpenID，再次查询即回复
        self.conn._learn_bot_openid({"mentions": [
            {"id": BOT_OID, "bot": True, "username": "林晚晴"}]})
        t, d = self._d("/botId", msg_id="MSGD2")
        self.assertTrue(self.conn._try_debug_command(t, d))
        self.assertIn(f"bot_id={BOT_OID}", self.api.sent[1][2])

    def test_c2c_user_id_self(self):
        t, d = self._d("/userId", t="C2C_MESSAGE_CREATE")
        d["author"] = {"user_openid": USER_OID, "username": "一梦"}
        del d["group_openid"]
        self.assertTrue(self.conn._try_debug_command(t, d))
        kind, chat, text, msg_id = self.api.sent[0]
        self.assertEqual((kind, chat), ("c2c", USER_OID))
        self.assertIn(f"user_id={USER_OID}", text)

    def test_plain_text_not_consumed(self):
        t, d = self._d("随便聊聊")
        self.assertFalse(self.conn._try_debug_command(t, d))
        self.assertEqual(self.api.sent, [])

    def test_whitelist_exempt(self):
        # 白名单指向其他群时，新群里的 /groupId 仍可用（部署引导场景）
        config = default_config(permissions={
            "admin_ids": [],
            "group_ids": ["OTHERGROUPOTHERGROUPOTHERGROUP01"],
            "forward_group_ids": [],
        })
        conn = build_connector(config)
        conn.api = self.api
        t, d = self._d("/groupId", group="NEWGROUP1NEWGROUP1NEWGROUP1NEWGROUP1")
        self.assertTrue(conn._try_debug_command(t, d))
        self.assertEqual(self.api.sent[0][1], "NEWGROUP1NEWGROUP1NEWGROUP1NEWGROUP1")


class RecordingLogger(FakeLogger):
    """记录 DEBUG 调用，用于断言诊断日志（不影响 FakeLogger 其他行为）。"""

    def __init__(self):
        self.debugs = []

    def debug(self, *a, **k):
        self.debugs.append((a, k))

    def text(self):
        return " ".join(str(x) for a, _ in self.debugs for x in a)


class TestDiagnosticLogging(unittest.TestCase):
    """回归：入站内容 / 出站结果需在 DEBUG 级留痕，便于真机排障。

    真机上回复成功是静默的（被动回复不写 INFO），曾导致「命令是否生效」
    无法从日志判断；这些 DEBUG 记录配合 MCDR ``debug.all`` 可完整还原链路。
    """

    def test_inbound_message_logged(self):
        conn = build_connector()
        log = RecordingLogger()
        conn.verbose = True
        conn._diag_logger = log
        conn._on_gateway_event(
            "GROUP_MESSAGE_CREATE", group_event("hello 你好")["d"], None
        )
        text = log.text()
        self.assertIn("入站", text)
        self.assertIn("hello 你好", text)
        self.assertIn(GROUP_OID, text)

    def test_outbound_send_logged(self):
        conn = build_connector()
        conn.api = FakeApi()
        log = RecordingLogger()
        conn.verbose = True
        conn._diag_logger = log
        p = ProcessedInfo(
            processed_message=[{"type": "text", "data": {"text": "hi"}}],
            _source=Source("OpenQQBot"), source_id=GROUP_OID,
            sender="bot", raw=group_event()["d"],
        )
        p.target = {"OpenQQBot": "group"}
        asyncio.run(conn.send_message(p))
        text = log.text()
        self.assertIn("发送成功", text)
        self.assertIn("被动", text)  # 同会话 → 被动回复锚点

    def test_debug_command_logged(self):
        conn = build_connector()
        conn.api = FakeApi()
        log = RecordingLogger()
        conn.verbose = True
        conn._diag_logger = log
        conn._try_debug_command(
            "GROUP_MESSAGE_CREATE", group_event("/groupId")["d"]
        )
        text = log.text()
        self.assertIn("调试命令", text)
        self.assertIn("/groupId", text)
        self.assertIn("调试命令回复已发送", text)


class TestQQConnectorEnableGuard(unittest.TestCase):
    """回归：OneBot QQ 连接器 enable=false 时不得发起连接（WinError 10061）。"""

    def _build(self, enable):
        from gugubot.connector.qq_connector import QQWebSocketConnector
        config = FakeConfig({"connector": {"QQ": {
            "enable": enable,
            "source_name": "QQ",
            "connection": {"host": "127.0.0.1", "port": 8777, "reconnect": 5},
        }}})
        conn = QQWebSocketConnector(FakeServer(), config)
        conn.logger = FakeLogger()
        return conn

    def test_disabled_connector_never_connects(self):
        conn = self._build(enable=False)
        self.assertFalse(conn.enable)
        asyncio.run(conn.connect())
        self.assertIsNone(conn.ws_client)  # 未创建任何 WebSocket 客户端

    def test_enabled_connector_creates_client(self):
        conn = self._build(enable=True)
        # 拦截工厂：不真正建连，仅验证守卫放行
        from unittest import mock
        with mock.patch(
            "gugubot.connector.qq_connector.WebSocketFactory.create_client"
        ) as factory:
            fake_client = mock.MagicMock()
            factory.return_value = fake_client
            asyncio.run(conn.connect())
            factory.assert_called_once()
            fake_client.connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
