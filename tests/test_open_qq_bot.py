"""open-qq-bot 连接器集成测试。

运行方式（需插件依赖，见 AGENTS.md；MCDR 事件循环以 FakeServer 桩替代）：

    uv run --with mcdreforged --with requests --with ruamel-yaml --with pyyaml \
        --with websocket-client --with websocket-server --with mcstatus \
        PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot -v
"""

import asyncio
import unittest
import yaml
from pathlib import Path

from gugubot.connector import OpenQQBotConnector
from gugubot.connector.open_qq_bot.parser import OpenQQBotParser
from gugubot.utils.types import ProcessedInfo, Source

REPO = Path(__file__).resolve().parent.parent
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


if __name__ == "__main__":
    unittest.main()
