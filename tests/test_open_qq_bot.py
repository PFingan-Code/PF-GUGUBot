"""open-qq-bot 连接器集成测试。

运行方式（需插件依赖，见 AGENTS.md；MCDR 事件循环以 FakeServer 桩替代）：

    PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot -v

    # 依赖未安装时可临时引入：
    uv run --with mcdreforged --with requests --with ruamel-yaml --with pyyaml \
        --with websocket-client --with websocket-server --with mcstatus \
        PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot -v

本文件不做任何 sys.path 硬编码 / 包别名注册：包路径统一由
PYTHONPATH=GUGUbot 提供（与 AGENTS.md 约定一致），保证 Linux/CI 可移植。
"""

try:
    from gugubot.connector import OpenQQBotConnector
    from gugubot.connector.open_qq_bot.parser import OpenQQBotParser
    from gugubot.connector.open_qq_bot.common import QuotaManager
    from gugubot.utils.types import ProcessedInfo, Source
except ModuleNotFoundError as _e:  # pragma: no cover
    raise RuntimeError(
        "无法导入 gugubot 包；请按项目约定设置 PYTHONPATH=GUGUbot 后运行：\n"
        "  PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot"
    ) from _e

import asyncio
import tempfile
import unittest
import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GROUP_OID = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
USER_OID = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
MEMBER_OID = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
BOT_OID = "1D9C431B7A590DD991BBB564DF11044D"

# build_connector 为每个用例创建独立临时数据目录；统一登记，tearDownModule
# 集中清理，避免依赖 GC 触发 ResourceWarning / 残留临时目录
_TEMP_DIRS = []


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
    data_folder = "."

    def tr(self, key, **kw):
        if not kw:
            return key
        # 测试桩：带参数时把 kwargs 附加在 key 后，便于用例断言回复内容
        return key + "|" + ",".join(f"{k}={v}" for k, v in kw.items())

    def schedule_task(self, coro):
        FakeServer.scheduled.append(coro)

    def get_data_folder(self):
        return self.data_folder


def drain_scheduled(run: bool = True) -> list:
    """取出 FakeServer.scheduled 中的协程。

    run=True 时逐个以独立事件循环执行（调试回复等需真正发送的任务）；
    run=False 时仅关闭（只统计调度次数的用例，避免 never-awaited 告警）。
    """
    pending = list(FakeServer.scheduled)
    FakeServer.scheduled.clear()
    for coro in pending:
        if run:
            asyncio.run(coro)
        else:
            coro.close()
    return pending


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
    server = FakeServer()
    # 数据目录隔离：QuotaManager 会把配额状态持久化到
    # <data_folder>/open_qq_bot_quota.json，落到 CWD 会让多次运行/多个
    # 测试进程共享计数，跑得越频繁越容易触发分钟/日限额，产生顺序相关
    # 的偶发失败；改为每次构建独立临时目录
    server._data_dir_ctx = tempfile.TemporaryDirectory(prefix="gugubot_test_")
    _TEMP_DIRS.append(server._data_dir_ctx)
    server.data_folder = server._data_dir_ctx.name
    conn = OpenQQBotConnector(server, config or default_config())
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
        # @机器人 自身的渲染前缀被剥离（M-7），@ 普通用户保留 @昵称
        self.assertEqual(info.message[0]["data"]["text"], "你好")

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

    async def test_face_with_description(self):
        """faceType=1 的系统表情：ext 的 text 是可提取的描述文本，直接加方括号。"""
        event = group_event(
            content='<faceType=1,faceId="13",ext="eyJ0ZXh0Ijoi5ZGy54mZIn0=">'
        )
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["text"], "[呲牙]")

    async def test_face_real_world_samples(self):
        """线上真实样本回归：多个 faceType 都要落成 [描述]，不出现 faceType 原文。"""
        cases = {
            '<faceType=1,faceId="86",ext="eyJ0ZXh0Ijoi5oCE54GrIn0=">': "[怄火]",
            '<faceType=3,faceId="342",ext="eyJ0ZXh0Ijoi6YW4USJ9">': "[酸Q]",
            '<faceType=4,faceId="",ext="eyJ0ZXh0IjoiW+S8pOW/g10ifQ==">': "[伤心]",
            '<faceType=1,faceId="277",ext="eyJ0ZXh0Ijoi5rGq5rGqIn0=">': "[汪汪]",
        }
        for content, expected in cases.items():
            with self.subTest(content=content):
                info = await self.parser.parse(group_event(content=content))
                text = info.message[0]["data"]["text"]
                self.assertEqual(text, expected)
                self.assertNotIn("faceType", text)

    async def test_face_sticker_without_description(self):
        """自定义大表情：ext 无 text，画面在同一事件的图片附件里。"""
        event = group_event(
            content='看这个 <faceType=6,faceId="0",ext="eyJ0ZXh0IjoiIn0=">'
        )
        event["d"]["attachments"] = [{"content_type": "image/gif",
                                      "url": "https://x/s.gif"}]
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["text"], "看这个 [表情包]")
        self.assertEqual(info.message[1]["type"], "image")

    async def test_face_description_already_bracketed(self):
        """部分表情描述自带方括号（如 [搓手]），不要出现双重括号。"""
        import base64
        import json
        ext = base64.b64encode(
            json.dumps({"text": "[搓手]"}, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        event = group_event(content=f'<faceType=4,faceId="",ext="{ext}">')
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["text"], "[搓手]")

    async def test_face_invalid_ext_falls_back(self):
        event = group_event(content='<faceType=6,faceId="0",ext="not-base64!!">')
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["text"], "[表情包]")

    async def test_bot_self_skipped(self):
        event = group_event()
        event["d"]["author"]["bot"] = True
        self.assertIsNone(await self.parser.parse(event))

    async def test_at_bot_prefix_stripped_for_command(self):
        """M-7：全量模式下 ``@机器人 #命令`` 的渲染前缀必须剥离，命令才可识别。"""
        event = group_event(
            content=f"<@{BOT_OID}> #绑定 Steve",
            mentions=[{"member_openid": BOT_OID, "id": BOT_OID,
                       "username": "林晚晴", "bot": True}],
        )
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["text"], "#绑定 Steve")

    async def test_at_bot_only_message_kept(self):
        """消息只有 @机器人 本身：剥离后为空则保留原文，不产生空消息段。"""
        event = group_event(
            content=f"<@{BOT_OID}>",
            mentions=[{"member_openid": BOT_OID, "id": BOT_OID,
                       "username": "林晚晴", "bot": True}],
        )
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["text"], "@林晚晴")

    async def test_at_other_user_prefix_not_stripped(self):
        """@ 普通用户（非机器人）不剥离前缀。"""
        event = group_event(
            content=f"<@{MEMBER_OID}> #hello",
            mentions=[{"member_openid": MEMBER_OID, "id": MEMBER_OID,
                       "username": "一梦", "bot": False}],
        )
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["text"], "@一梦 #hello")

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

    def test_group_at_openid_uses_markdown_mention(self):
        """MC 侧 CQ:at 转成 at 段后，群聊须渲染 <qqbot-at-user/> 并走 Markdown。"""
        p = ProcessedInfo(
            processed_message=[{"type": "at", "data": {"qq": MEMBER_OID}},
                               {"type": "text", "data": {"text": " hi"}}],
            _source=Source("Minecraft"), source_id="mc", sender="HAHH9527",
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        kind, group, content, _ = self.api.sent[0]
        self.assertEqual((kind, group), ("markdown", GROUP_OID))
        self.assertIn(f'<qqbot-at-user id="{MEMBER_OID}" />', content)
        self.assertNotIn(f"@{MEMBER_OID}", content)

    def test_group_at_all_not_rendered(self):
        """不支持从服务器 @全体：all 退化为纯文本，且不触发 Markdown。"""
        p = ProcessedInfo(
            processed_message=[{"type": "at", "data": {"qq": "all"}},
                               {"type": "text", "data": {"text": " hi"}}],
            _source=Source("Minecraft"), source_id="mc", sender="HAHH9527",
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        kind, _, content, _ = self.api.sent[0]
        self.assertEqual(kind, "text")
        self.assertIn("@all", content)
        self.assertNotIn("<qqbot-at-", content)

    def test_text_cannot_inject_mention_tags(self):
        """MC 聊天文本里伪造的 <qqbot-at-*> 必须被剥离，不能借 @成员触发 Markdown。"""
        p = ProcessedInfo(
            processed_message=[{"type": "text",
                                "data": {"text": "<qqbot-at-everyone /> 看招 "}},
                               {"type": "at", "data": {"qq": MEMBER_OID}}],
            _source=Source("Minecraft"), source_id="mc", sender="HAHH9527",
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        kind, _, content, _ = self.api.sent[0]
        self.assertEqual(kind, "markdown")  # 真 @ 成员仍生效
        self.assertNotIn("qqbot-at-everyone", content)
        self.assertNotIn("qqbot-at-all", content)

    def test_private_at_openid_stays_plain_text(self):
        """单聊不渲染 @ 标签，保持 @id 纯文本，且不能走 Markdown。"""
        p = ProcessedInfo(
            processed_message=[{"type": "at", "data": {"qq": USER_OID}},
                               {"type": "text", "data": {"text": " hi"}}],
            _source=Source("QQ"), source_id=USER_OID, sender="友",
        )
        p.target = {USER_OID: "private"}
        asyncio.run(self.conn.send_message(p))
        kind, _, content, _ = self.api.sent[0]
        self.assertEqual(kind, "c2c")
        self.assertIn(f"@{USER_OID}", content)
        self.assertNotIn("<qqbot-at-", content)

    def test_group_at_non_openid_stays_plain_text(self):
        """OneBot 的 QQ 号/昵称无法映射 OpenID，退化为纯文本 @。"""
        p = ProcessedInfo(
            processed_message=[{"type": "at", "data": {"qq": "123456"}},
                               {"type": "text", "data": {"text": " hi"}}],
            _source=Source("QQ"), source_id=GROUP_OID, sender="群友",
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        kind, _, content, _ = self.api.sent[0]
        self.assertEqual(kind, "text")
        self.assertIn("@123456", content)

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

    def test_midchunk_passive_expiry_no_duplicate_resend(self):
        """N1（端到端）：分片中途被动过期 → 仅告警，不整体降级重发已送达片。"""
        from gugubot.connector.open_qq_bot.api_client import ApiClient, TokenManager
        from gugubot.connector.open_qq_bot.common import ApiError

        client = ApiClient(TokenManager("a", "b"))
        client.max_message_length = 10
        passive, active = [], []

        def fake_call(method, path, body=None, timeout=10):
            if body.get("msg_id"):  # 被动回复：首片送达，其后窗口失效
                if not passive:
                    passive.append(body["content"])
                    return {"id": "R"}
                raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)
            active.append(body["content"])  # 主动降级（不应发生）
            return {"id": "R"}

        client._call = fake_call
        self.conn.api = client
        p = ProcessedInfo(
            processed_message=[{"type": "text", "data": {"text": "A" * 30}}],
            _source=Source("OpenQQBot"), source_id=GROUP_OID,
            sender="bot", raw=group_event()["d"],
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        self.assertEqual(passive, ["A" * 10])  # 仅首片送达
        self.assertEqual(active, [])  # 中途失败抛 PartialDelivery，无整体重发

    def test_passive_exhausted_falls_back_to_active(self):
        """SeqManager 次数耗尽时 send_* 返回 None 而非抛错：必须降级，不得静默丢弃。"""
        def exhausted_send(g, c, msg_id=None, event_id=None, reference=None):
            if msg_id:
                return None  # 被动回复次数耗尽（5 次上限）
            self.api.sent.append(("text", g, c, msg_id))
            return {"id": "RID"}

        self.api.send_group_text = exhausted_send
        p = ProcessedInfo(processed_message=[{"type": "text", "data": {"text": "hi"}}],
                          _source=Source("OpenQQBot"), source_id=GROUP_OID,
                          sender="bot", raw=group_event()["d"])
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        self.assertEqual(len(self.api.sent), 1)  # 降级为主动消息成功
        self.assertIsNone(self.api.sent[0][3])

    def test_passive_expired_markdown_fallback_no_duplicate_images(self):
        """M-1：Markdown 被动回复过期降级时，图片 URL 不得重复追加。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        def failing_markdown(g, c, msg_id=None, reference=None):
            if msg_id:  # 带锚点（被动）时模拟窗口失效
                raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)
            self.api.sent.append(("markdown", g, c, msg_id))
            return {"id": "RID"}

        self.api.send_group_markdown = failing_markdown
        p = ProcessedInfo(
            processed_message=[{"type": "text", "data": {"text": "看图"}},
                               {"type": "image", "data": {"file": "https://i/x.png"}}],
            _source=Source("OpenQQBot"), source_id=GROUP_OID,
            sender="bot", raw=group_event()["d"],
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        self.assertEqual(len(self.api.sent), 1)  # 仅降级后的主动消息
        kind, _, content, msg_id = self.api.sent[0]
        self.assertEqual((kind, msg_id), ("markdown", None))
        self.assertEqual(
            content.count("![图片](https://i/x.png)"), 1, "图片 URL 只能出现一次"
        )

    def test_private_images_get_placeholder(self):
        """单聊不支持富媒体下发：图片以 [图片] 占位并入文本，不得静默丢弃。"""
        p = ProcessedInfo(
            processed_message=[{"type": "image", "data": {"file": "https://i/x.png"}}],
            _source=Source("QQ"), source_id=USER_OID, sender="友",
        )
        p.target = {USER_OID: "private"}
        asyncio.run(self.conn.send_message(p))
        kind, _, content, _ = self.api.sent[0]
        self.assertEqual(kind, "c2c")
        self.assertIn("[图片]", content)


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
        drain_scheduled(run=False)

    def test_unknown_event_ignored(self):
        self.conn._on_gateway_event("SOMETHING_ELSE", {}, None)
        self.assertEqual(FakeServer.scheduled, [])

    def test_on_message_direct_injection(self):
        event = group_event(content="hello")
        asyncio.run(self.conn.on_message(event))
        self.assertEqual(len(FakeServer.scheduled), 1)
        drain_scheduled(run=False)


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

    def test_bot_global_minute_window(self):
        """L-2：Bot 全局滑动窗口限制所有群合计的主动消息速率。"""
        from gugubot.connector.open_qq_bot.common import QuotaManager
        q = QuotaManager(per_minute=2, per_day=100, bot_per_minute=3,
                         persist_path=self.path)
        assert q.allow("A")
        assert q.allow("A")  # A 的 key 级分钟窗口用尽（2/2）
        assert q.allow("B")
        assert not q.allow("B")  # 全局窗口用尽（3/3），即使 B 的 key 级未满

    def test_allow_many_counts_chunks(self):
        """分片发送按实际 API 请求数记账。"""
        from gugubot.connector.open_qq_bot.common import QuotaManager
        q = QuotaManager(per_minute=3, per_day=100, bot_per_minute=10,
                         persist_path=self.path)
        assert q.allow_many("A", 3)  # 3 片一次计入
        assert not q.allow("A")  # 分钟窗口已满（3/3）
        assert not q.allow_many("A", 1)

    def test_allow_many_all_or_nothing(self):
        """容量不足时整体拒绝，不做部分消费。"""
        from gugubot.connector.open_qq_bot.common import QuotaManager
        q = QuotaManager(per_minute=2, per_day=100, bot_per_minute=10,
                         persist_path=self.path)
        assert q.allow_many("A", 2)
        assert not q.allow_many("A", 1)
        st = q._state["A"]
        self.assertEqual(st["day"], 2)  # 拒绝时未多记
        self.assertEqual(len(st["minute"]), 2)


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

    async def test_member_remove_outside_whitelist_ignored(self):
        """未监听群的退群事件不进入管线：用户可能仍在监听群内，不应误解绑。"""
        event = {"t": "GROUP_MEMBER_REMOVE", "d": {
            "group_openid": "OTHEROTHEROTHEROTHEROTHEROTHEROTHER1",
            "member_openid": USER_OID, "timestamp": 1}}
        self.assertIsNone(await self.parser.parse(event))

    async def test_member_remove_without_whitelist_passes(self):
        """group_ids 为空 = 全量监听：任何群的退群事件都进入管线。"""
        config = default_config(permissions={
            "admin_ids": [], "group_ids": [], "forward_group_ids": []})
        parser = OpenQQBotParser(build_connector(config))
        event = {"t": "GROUP_MEMBER_REMOVE", "d": {
            "group_openid": "ANYGROUPANYGROUPANYGROUPANYGROUPANYGROUP12",
            "member_openid": USER_OID, "timestamp": 1}}
        info = await parser.parse(event)
        self.assertIsNotNone(info)

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
    """open-qq-bot 退群解绑（bound 系统官方分支）。

    使用真实 PlayerManager（临时目录持久化），绑定数据复现真实写入形态：
    平台键为连接器显示名 ``OpenQQBot``（与 ``_handle_bind`` 写入的
    ``source.origin`` 一致）。早前 fixture 用 ``"QQ"`` 键构造数据，
    掩盖了「退群按 QQ 查找、永远查不到官方绑定」的缺陷。
    """

    async def asyncSetUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    async def _run(self, accounts):
        from gugubot.logic.system.bound import BoundSystem
        from gugubot.utils.player_manager import Player
        from gugubot.utils.types import BroadcastInfo, Source as Src

        class FakeWhitelist:
            def __init__(self):
                self.removed = []

            def remove_player(self, names):
                if isinstance(names, str):
                    names = [names]
                self.removed.extend(names)

        fake_server = FakeServer()
        fake_server.data_folder = self._tmpdir.name
        config = FakeConfig({
            "system": {"bound": {"whitelist_remove_with_leave": True}},
            "connector": {
                "QQ": {"permissions": {"group_ids": [], "admin_group_ids": []}},
                "open-qq-bot": {"permissions": {"group_ids": [GROUP_OID]}},
            },
        })
        bs = BoundSystem(fake_server, config=config)
        bs.logger = FakeLogger()
        bs.whitelist = FakeWhitelist()
        bs.enable = True

        # 预置真实 PlayerManager 数据：平台键 = 连接器显示名（真实写入形态）
        pm = bs.player_manager
        pm._players["Steve"] = Player(
            name="Steve",
            java_name=["Steve"],
            accounts={k: list(v) for k, v in accounts.items()},
        )

        info = BroadcastInfo(
            event_type="notice", event_sub_type="group_decrease",
            message=[{"type": "text", "data": {"text": ""}}],
            raw={"group_openid": GROUP_OID, "member_openid": USER_OID},
            server=fake_server, logger=FakeLogger(),
            _source=Src("OpenQQBot"), source_id=GROUP_OID,
            sender=USER_OID, sender_id=USER_OID,
        )
        handled = await bs.process_broadcast_info(info)
        return handled, pm, bs

    async def test_official_quit_unbinds(self):
        handled, pm, bs = await self._run(accounts={"OpenQQBot": [USER_OID]})
        self.assertTrue(handled)
        self.assertIsNone(pm.get_player("Steve"))  # 绑定已整体清除
        self.assertEqual(bs.whitelist.removed, ["Steve"])  # 白名单同步移除

    async def test_official_quit_keeps_other_platform(self):
        handled, pm, bs = await self._run(
            accounts={"OpenQQBot": [USER_OID], "FPS": ["steve_fps"]})
        self.assertTrue(handled)
        self.assertIsNotNone(pm.get_player("Steve"))  # 其他平台绑定保留
        player = pm.get_player("Steve")
        self.assertEqual(player.accounts.get("OpenQQBot", []), [])  # 官方账户已删
        self.assertEqual(player.accounts.get("FPS"), ["steve_fps"])
        self.assertEqual(player.java_name, ["Steve"])  # 玩家名保留
        self.assertEqual(bs.whitelist.removed, ["Steve"])  # 白名单仍需移除

    async def test_official_quit_ignores_unbound_user(self):
        """未绑定用户退群：不产生任何清理动作。"""
        handled, pm, bs = await self._run(accounts={"OpenQQBot": ["OTHEROID"]})
        self.assertFalse(handled)
        self.assertIsNotNone(pm.get_player("Steve"))  # 不受影响
        self.assertEqual(bs.whitelist.removed, [])


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
        drain_scheduled()
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
        drain_scheduled()
        self.assertEqual(self.api.sent[0][1], GROUP_OID)
        self.assertEqual(self.conn.bot_openid, BOT_OID)

    def test_user_id_with_mention(self):
        t, d = self._d(
            "/userId @一梦",
            mentions=[{"member_openid": USER_OID, "username": "一梦"}],
        )
        self.assertTrue(self.conn._try_debug_command(t, d))
        drain_scheduled()
        self.assertIn(f"user_id={USER_OID}", self.api.sent[0][2])

    def test_user_id_usage_without_mention(self):
        t, d = self._d("/userId")
        self.assertTrue(self.conn._try_debug_command(t, d))
        drain_scheduled()
        self.assertIn("debug_user_id_usage", self.api.sent[0][2])

    def test_user_id_multi_mentions(self):
        t, d = self._d(
            "/userId @a @b",
            mentions=[{"member_openid": USER_OID, "username": "a"},
                      {"member_openid": MEMBER_OID, "username": "b"}],
        )
        self.assertTrue(self.conn._try_debug_command(t, d))
        drain_scheduled()
        self.assertIn("debug_user_id_multi", self.api.sent[0][2])

    def test_bot_id_unknown_then_learned(self):
        t, d = self._d("/botId")
        self.assertTrue(self.conn._try_debug_command(t, d))
        drain_scheduled()
        self.assertIn("debug_bot_id_unknown", self.api.sent[0][2])
        # 被 @ 后习得自身 OpenID，再次查询即回复
        self.conn._learn_bot_openid({"mentions": [
            {"id": BOT_OID, "bot": True, "username": "林晚晴"}]})
        t, d = self._d("/botId", msg_id="MSGD2")
        self.assertTrue(self.conn._try_debug_command(t, d))
        drain_scheduled()
        self.assertIn(f"bot_id={BOT_OID}", self.api.sent[1][2])

    def test_c2c_user_id_self(self):
        t, d = self._d("/userId", t="C2C_MESSAGE_CREATE")
        d["author"] = {"user_openid": USER_OID, "username": "一梦"}
        del d["group_openid"]
        self.assertTrue(self.conn._try_debug_command(t, d))
        drain_scheduled()
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
        drain_scheduled()
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
        drain_scheduled(run=False)

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
        drain_scheduled()  # 回复已异步调度，执行后才有「已发送」记录
        text = log.text()
        self.assertIn("调试命令", text)
        self.assertIn("/groupId", text)
        self.assertIn("调试命令回复已发送", text)


class TestSeqAccounting(unittest.TestCase):
    """去重重试换 msg_seq 后：成功不泄漏旧名额，失败全部回退。"""

    def _client(self):
        from gugubot.connector.open_qq_bot.api_client import ApiClient, TokenManager

        return ApiClient(TokenManager("a", "b"))

    def test_group_retry_failure_releases_seq(self):
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:  # 首次：命中去重（换 seq 重试）
                raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)
            raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_group_markdown("G", "hi", msg_id="M")
        self.assertEqual(calls["n"], 2)
        # 被动分配（seq=1）与重试分配（seq=2）均未被服务端接受，全部回退
        self.assertEqual(client.seq._seqs.get("M", 0), 0)

    def test_group_retry_success_no_leak(self):
        """去重重试成功：一条消息只消耗一个被动名额（旧 seq 回退）。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)
            return {"id": "R"}

        client._call = fake_call
        resp = client.send_group_text("G", "hi", msg_id="M")
        self.assertEqual(resp, {"id": "R"})
        self.assertEqual(calls["n"], 2)
        self.assertEqual(client.seq._seqs.get("M", 0), 1)

    def test_c2c_retry_failure_releases_seq(self):
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)
            raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_c2c_text("U", "hi", msg_id="M")
        self.assertEqual(calls["n"], 2)
        # 首次分配与去重重试分配均未被服务端接受，全部回退（不泄漏）
        self.assertEqual(client.seq._seqs.get("M", 0), 0)

    def test_c2c_first_failure_releases_seq(self):
        """首次发送因非去重错误失败：分配的 seq 必须回退（此前泄漏 1 个）。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 500, '{"err_code":500}', 500)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_c2c_text("U", "hi", msg_id="M")
        self.assertEqual(client.seq._seqs.get("M", 0), 0)

    def test_c2c_retry_success_no_leak(self):
        """去重重试成功：一条消息只消耗一个被动名额（旧 seq 回退）。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)
            return {"id": "R"}

        client._call = fake_call
        resp = client.send_c2c_text("U", "hi", msg_id="M")
        self.assertEqual(resp, {"id": "R"})
        self.assertEqual(client.seq._seqs.get("M", 0), 1)

    def test_network_error_releases_seq(self):
        """N2：网络层失败统一为 status=0 的 ApiError，seq 走同一回退路径。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 0, "connection reset", None, None)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_group_text("G", "hi", msg_id="M")
        self.assertEqual(client.seq._seqs.get("M", 0), 0)

    def test_group_double_dup_exhaust_no_leak(self):
        """N3：连续去重直至名额耗尽，重试分配的 seq 必须全部回退。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        client.seq._seqs["M"] = 3  # 预占 3 个名额（上限 5）

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_group_text("G", "hi", msg_id="M")
        # 被动分配 seq=4、重试 seq=5 均未被接受；耗尽时 retry_seqs 与初始 seq 全回退
        self.assertEqual(client.seq._seqs.get("M", 0), 3)

    def test_c2c_double_dup_exhaust_no_leak(self):
        """N3（单聊）：连续去重直至名额耗尽，不泄漏重试 seq。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        client.seq._seqs["M"] = 3

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_c2c_text("U", "hi", msg_id="M")
        self.assertEqual(client.seq._seqs.get("M", 0), 3)


class TestChunking(unittest.TestCase):
    """M-2 / L-1：Markdown 与单聊文本分片，split 防御非法长度。"""

    def _client(self):
        from gugubot.connector.open_qq_bot.api_client import ApiClient, TokenManager

        return ApiClient(TokenManager("a", "b"))

    def test_split_message_invalid_length(self):
        from gugubot.connector.open_qq_bot.common import split_message

        # <=0 会死循环；非整数会 TypeError —— 均需防御（非法值钳/回退默认值）
        self.assertEqual(len(split_message("hello", 0)), 5)  # 钳到 1，逐字符切不死循环
        self.assertEqual(len(split_message("a" * 10, 0)), 10)
        self.assertEqual(split_message("hello", None), ["hello"])  # 非法值回退默认 2000
        self.assertEqual(split_message("", 0), [])

    def test_split_markdown_basic(self):
        from gugubot.connector.open_qq_bot.common import split_markdown

        chunks = split_markdown("a" * 30, 10)
        self.assertEqual("".join(chunks), "a" * 30)
        self.assertTrue(all(len(c) <= 10 for c in chunks))

    def test_split_markdown_protects_tags_and_urls(self):
        from gugubot.connector.open_qq_bot.common import split_markdown

        tag = '<qqbot-at-user id="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" />'
        url = "https://example.com/aaaaaaaaaaaaaaaaaaaa"
        content = f"前缀\n{tag}\n中\n![图片]({url})\n尾"
        chunks = split_markdown(content, 60)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(any(tag in c for c in chunks))  # @ 标签不被切断
        self.assertTrue(any(f"![图片]({url})" in c for c in chunks))  # 图片不被切断

    def test_split_markdown_backtracks_across_protected_span(self):
        """切点默认落在受保护片段内部时，回退到片段起点之前。"""
        from gugubot.connector.open_qq_bot.common import split_markdown

        url = "https://e.com/" + "x" * 12  # 20 字符受保护片段
        content = "a" * 25 + url + "b" * 25
        chunks = split_markdown(content, 30)
        self.assertTrue(any(url in c for c in chunks))  # URL 完整保留
        self.assertEqual("".join(chunks), content)  # 内容不丢

    def test_split_markdown_protected_span_longer_than_limit(self):
        """单个受保护片段超长：放弃保护硬切，保证终止。"""
        from gugubot.connector.open_qq_bot.common import split_markdown

        url = "https://example.com/" + "a" * 100
        chunks = split_markdown(url, 10)
        self.assertEqual("".join(chunks), url)

    def test_api_markdown_and_c2c_chunked(self):
        """send_group_markdown / send_c2c_text 超长内容自动分片（M-2）。"""
        client = self._client()
        calls = []

        def fake_call(method, path, body=None, timeout=10):
            calls.append((path, body))
            return {"id": "R"}

        client._call = fake_call
        client.max_message_length = 20

        calls.clear()
        client.send_group_markdown("G", "x" * 45)
        self.assertEqual(len(calls), 3)
        contents = [b["markdown"]["content"] for _, b in calls]
        self.assertTrue(all(len(c) <= 20 for c in contents))
        self.assertEqual("".join(contents), "x" * 45)  # 内容不丢

        calls.clear()
        client.send_c2c_text("U", "y" * 45)
        self.assertEqual(len(calls), 3)
        contents = [b["content"] for _, b in calls]
        self.assertTrue(all(len(c) <= 20 for c in contents))
        self.assertEqual("".join(contents), "y" * 45)

    def test_api_partial_delivery(self):
        """M-3：一片未发出（被动次数耗尽）→ 返回 None，调用方可整体降级。"""
        client = self._client()
        sent = []

        def fake_call(method, path, body=None, timeout=10):
            sent.append(body["content"])
            return {"id": "R"}

        client._call = fake_call
        client.max_message_length = 10
        # 预耗 5 个被动名额（上限），发送 "z"*30（3 片）→ 首片即无法分配
        for _ in range(5):
            client.seq.allocate("M")
        self.assertIsNone(client.send_group_text("G", "z" * 30, msg_id="M"))
        self.assertEqual(len(sent), 0)

    def test_api_partial_delivery_after_success(self):
        """首片成功、后续片被动耗尽：抛 PartialDelivery（不再静默截断）。"""
        from gugubot.connector.open_qq_bot.api_client import PartialDelivery

        client = self._client()
        sent = []

        def fake_call(method, path, body=None, timeout=10):
            sent.append(body["content"])
            return {"id": "R"}

        client._call = fake_call
        client.max_message_length = 10
        # 先预耗 4 个名额：首片用第 5 个（成功），第二片无名额
        for _ in range(4):
            client.seq.allocate("M")
        with self.assertRaises(PartialDelivery) as ctx:
            client.send_group_text("G", "z" * 20, msg_id="M")
        self.assertEqual(ctx.exception.sent, 1)
        self.assertEqual(ctx.exception.remaining, 1)
        self.assertEqual(len(sent), 1)

    def test_group_text_midchunk_apierror_partial(self):
        """N1：分片中途 API 失败（非去重）→ PartialDelivery，不整体重发。"""
        from gugubot.connector.open_qq_bot.api_client import PartialDelivery
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"id": "R"}
            raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)

        client._call = fake_call
        client.max_message_length = 10
        with self.assertRaises(PartialDelivery) as ctx:
            client.send_group_text("G", "z" * 30, msg_id="M")
        self.assertEqual(ctx.exception.sent, 1)
        self.assertEqual(ctx.exception.remaining, 2)
        self.assertEqual(calls["n"], 2)
        # 首片已送达消耗 1 个名额；失败片回退，不泄漏
        self.assertEqual(client.seq._seqs.get("M", 0), 1)

    def test_group_markdown_midchunk_apierror_partial(self):
        """N1（Markdown）：中途失败抛 PartialDelivery，已送达片不重发。"""
        from gugubot.connector.open_qq_bot.api_client import PartialDelivery
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"id": "R"}
            raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)

        client._call = fake_call
        client.max_message_length = 10
        with self.assertRaises(PartialDelivery) as ctx:
            client.send_group_markdown("G", "z" * 30, msg_id="M")
        self.assertEqual(ctx.exception.sent, 1)
        self.assertEqual(ctx.exception.remaining, 2)
        self.assertEqual(client.seq._seqs.get("M", 0), 1)

    def test_c2c_midchunk_apierror_partial(self):
        """N1（单聊）：中途失败抛 PartialDelivery，已送达片不重发。"""
        from gugubot.connector.open_qq_bot.api_client import PartialDelivery
        from gugubot.connector.open_qq_bot.common import ApiError

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"id": "R"}
            raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)

        client._call = fake_call
        client.max_message_length = 10
        with self.assertRaises(PartialDelivery) as ctx:
            client.send_c2c_text("U", "z" * 30, msg_id="M")
        self.assertEqual(ctx.exception.sent, 1)
        self.assertEqual(ctx.exception.remaining, 2)
        self.assertEqual(client.seq._seqs.get("M", 0), 1)


class TestGatewayResilience(unittest.TestCase):
    """H-2：网关地址/token 获取失败须退避重试，凭据错误才终止线程。"""

    def _gateway(self, url_getter):
        from gugubot.connector.open_qq_bot.gateway import Gateway

        return Gateway(
            gateway_url_getter=url_getter, token_getter=lambda: "t",
            on_event=lambda *a: None,
        )

    def test_run_retries_when_url_getter_fails(self):
        """瞬时故障（网络超时/5xx）不抛异常，退避后重试。"""
        attempts = {"n": 0}

        def flaky_url():
            attempts["n"] += 1
            raise RuntimeError("network down")

        g = self._gateway(flaky_url)
        waits = {"n": 0}

        def fake_wait(timeout=None):
            waits["n"] += 1
            if waits["n"] >= 2:
                g.stop()  # 第二次重试等待时请求停止，结束测试循环
                return True
            return False

        g._stop_event.wait = fake_wait
        g.run()  # 不得抛出 RuntimeError：异常必须被重试逻辑消化
        self.assertEqual(attempts["n"], 2)  # 首次失败后确实重试了一次

    def test_credential_error_stops_gateway(self):
        """HTTP 401/403（凭据无效）：明确终止并抛 GatewayStopped，不无限重试。"""
        from gugubot.connector.open_qq_bot.common import ApiError
        from gugubot.connector.open_qq_bot.gateway import GatewayStopped

        def unauthorized():
            raise ApiError("GET", "u", 401, "invalid appid", None, None)

        g = self._gateway(unauthorized)
        with self.assertRaises(GatewayStopped):
            g.run()

    def test_transient_http_error_retried(self):
        """5xx 属可重试错误：不触发凭据终止。"""
        from gugubot.connector.open_qq_bot.common import ApiError

        attempts = {"n": 0}

        def server_error():
            attempts["n"] += 1
            raise ApiError("GET", "u", 502, "bad gateway", None, None)

        g = self._gateway(server_error)
        waits = {"n": 0}

        def fake_wait(timeout=None):
            waits["n"] += 1
            if waits["n"] >= 2:
                g.stop()
                return True
            return False

        g._stop_event.wait = fake_wait
        g.run()  # 不抛 GatewayStopped（凭据错误才终止）
        self.assertEqual(attempts["n"], 2)

    def test_alive_reports_thread_state(self):
        """alive 健康检查：线程死亡时连接器不应「看起来正常」。"""
        import threading

        g = self._gateway(lambda: "wss://example")
        self.assertFalse(g.alive)  # 未 connect
        gate = threading.Event()
        g._thread = threading.Thread(target=gate.wait, args=(1,), daemon=True)
        g._thread.start()
        self.assertTrue(g.alive)
        gate.set()
        g._thread.join(timeout=1)
        self.assertFalse(g.alive)

    def test_stop_during_url_fetch_skips_connect(self):
        """N5：_get_url 阻塞期间收到 stop()，返回后不得再新建 WS 连接。"""
        from unittest import mock

        import gugubot.connector.open_qq_bot.gateway as gw

        g = self._gateway(lambda: "wss://example")

        def url_then_stop():
            g._stop = True  # 模拟获取网关地址期间 stop() 被调用
            return "wss://example"

        g._get_url = url_then_stop
        with mock.patch.object(gw.websocket, "WebSocketApp") as ws_cls:
            g.run()
        ws_cls.assert_not_called()


class FakeGatewayWS:
    """网关 WS 桩：记录 send/close，可按需在发送后触发 ACK。"""

    def __init__(self, on_send=None):
        self.sent = []
        self.closed = False
        self.keep_running = True
        self._on_send = on_send

    def send(self, payload):
        self.sent.append(payload)
        if self._on_send:
            self._on_send(self)

    def close(self):
        self.closed = True


class TestGatewayHeartbeat(unittest.TestCase):
    """心跳日志方案：HELLO 时 INFO 一次正常间隔；正常心跳只留 DEBUG；
    ACK 超过一个心跳间隔才 WARNING。"""

    def _gateway(self):
        from gugubot.connector.open_qq_bot.gateway import Gateway

        return Gateway(
            gateway_url_getter=lambda: "wss://example", token_getter=lambda: "t",
            on_event=lambda *a: None,
        )

    def test_hello_logs_heartbeat_interval(self):
        """服务端下发的正常心跳间隔必须可见（此前只存内部字段，日志无迹可查）。"""
        import json

        g = self._gateway()
        ws = FakeGatewayWS()
        with self.assertLogs("gugubot.open_qq_bot", level="INFO") as logs:
            g._on_message(ws, json.dumps({
                "op": 10, "d": {"heartbeat_interval": 41250},
            }))
        self.assertEqual(g._heartbeat_interval, 41.25)
        self.assertTrue(any(
            "心跳间隔" in m and "服务端下发" in m for m in logs.output
        ))

    def test_normal_beat_not_warned(self):
        """正常心跳（ACK 在一个间隔内返回）：不产生 WARNING。"""
        g = self._gateway()
        g._heartbeat_interval = 0.2
        g._hello.set()
        g._ready.set()

        def ack_once(ws):
            g._ack.set()
            ws.keep_running = False  # 一拍后退出循环

        ws = FakeGatewayWS(on_send=ack_once)
        with self.assertLogs("gugubot.open_qq_bot", level="DEBUG") as logs:
            g._heartbeat_loop(ws)
        self.assertFalse(ws.closed)
        self.assertTrue(any("发送心跳" in m for m in logs.output))
        self.assertFalse(any("WARNING" in m for m in logs.output))

    def test_ack_exceeding_interval_warns(self):
        """ACK 超过正常间隔未返回：WARNING 带出实际等待与正常间隔。"""
        g = self._gateway()
        g._heartbeat_interval = 0.2
        g._hello.set()
        g._ready.set()
        ws = FakeGatewayWS()
        with self.assertLogs("gugubot.open_qq_bot", level="WARNING") as logs:
            g._heartbeat_loop(ws)
        self.assertTrue(ws.closed)
        self.assertIn("心跳 ACK 超过 0.2s 未返回", logs.output[0])
        self.assertIn("正常间隔 0.2s", logs.output[0])


class TestCrossBroadcastQQRouting(unittest.IsolatedAsyncioTestCase):
    """M-6：!!qq 路由到所有已启用的 QQ 类连接器，且不回落 echo。"""

    async def _run(self, enabled=("QQ",), group_ids=None, openids=None):
        from gugubot.logic.plugins.cross_broadcast import CrossBroadcastSystem
        from gugubot.utils.types import BroadcastInfo, Source as Src

        sent = []

        class FakeConnector:
            def __init__(self, source, enable):
                self.source = source
                self.enable = enable
                self.enable_send = True

        class FakeManager:
            def __init__(self, connectors):
                self.connectors = connectors

            def get_connector(self, source):
                return next((c for c in self.connectors if c.source == source), None)

            async def broadcast_processed_info(self, info, include=None, exclude=None):
                sent.append((tuple(include), info.target))

        connectors = [
            FakeConnector("QQ", "QQ" in enabled),
            FakeConnector("OpenQQBot", "OpenQQBot" in enabled),
        ]
        config = FakeConfig({
            "system": {"cross_broadcast": {
                "enable": True,
                "qq_forward_group_ids": group_ids or [],
                "qq_forward_openids": openids or [],
            }},
            "connector": {
                "QQ": {"source_name": "QQ"},
                "open-qq-bot": {"source_name": "OpenQQBot"},
                "minecraft": {"source_name": "Minecraft"},
                "minecraft_bridge": {"source_name": "Bridge"},
            },
            "GUGUBot": {"command_prefix": "#"},
        })
        system = CrossBroadcastSystem(config=config)
        system.system_manager = type(
            "SM", (), {"connector_manager": FakeManager(connectors)}
        )()
        system.logger = FakeLogger()

        info = BroadcastInfo(
            event_type="message", event_sub_type="group",
            message=[{"type": "text", "data": {"text": "!!qq 大家好"}}],
            raw=None, server=FakeServer(), logger=FakeLogger(),
            _source=Src("Minecraft"), source_id="mc",
            sender="Steve", sender_id="steve",
        )
        handled = await system.process_broadcast_info(info)
        return handled, sent

    async def test_routes_to_all_enabled_connectors(self):
        handled, sent = await self._run(enabled=("QQ", "OpenQQBot"))
        self.assertTrue(handled)
        self.assertEqual(len(sent), 2)
        includes = {include[0] for include, _ in sent}
        self.assertEqual(includes, {"QQ", "OpenQQBot"})

    async def test_openid_forward_target_passed_to_official(self):
        """qq_forward_openids 构建的目标只投给官方连接器。"""
        handled, sent = await self._run(
            enabled=("QQ", "OpenQQBot"), openids=[GROUP_OID])
        self.assertTrue(handled)
        official = [s for s in sent if s[0] == ("OpenQQBot",)]
        self.assertEqual(len(official), 1)
        self.assertEqual(official[0][1], {GROUP_OID: "group"})

    async def test_consumed_even_without_connector(self):
        """无任何已启用连接器：命令仍被消费（不回落 echo 泄漏 !!qq 原文）。"""
        handled, sent = await self._run(enabled=())
        self.assertTrue(handled)
        self.assertEqual(sent, [])

    async def test_official_only_deployment(self):
        """仅启用官方连接器时 !!qq 可用（此前只路由 OneBot，返回 False）。"""
        handled, sent = await self._run(enabled=("OpenQQBot",))
        self.assertTrue(handled)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], ("OpenQQBot",))


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


class TestReviewRegressions(unittest.TestCase):
    """N2/N4/N6：网络异常归一、降级配额通道预估、bot OpenID 取值优先级。"""

    def test_http_json_urlerror_becomes_apierror(self):
        """N2：URLError 等网络层失败 → status=0 的 ApiError（不再裸抛）。"""
        import urllib.error
        from unittest import mock

        from gugubot.connector.open_qq_bot import common

        with mock.patch.object(common.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("conn reset")):
            with self.assertRaises(common.ApiError) as ctx:
                common.http_json("GET", "https://example.com")
        self.assertEqual(ctx.exception.status, 0)

    def test_http_json_incomplete_read_becomes_apierror(self):
        """N2：IncompleteRead（HTTPException，非 OSError）同样归一为 status=0。"""
        import http.client
        from unittest import mock

        from gugubot.connector.open_qq_bot import common

        with mock.patch.object(common.urllib.request, "urlopen",
                               side_effect=http.client.IncompleteRead(b"partial")):
            with self.assertRaises(common.ApiError) as ctx:
                common.http_json("GET", "https://example.com")
        self.assertEqual(ctx.exception.status, 0)

    def test_active_fallback_passes_has_mention(self):
        """N4：降级配额预估须按是否含 @ 标签选择通道（has_mention 透传）。"""
        from unittest import mock

        conn = build_connector()
        conn.quota = mock.MagicMock()
        conn.quota.allow_many.return_value = True
        conn.api = FakeApi()

        plain = f'<qqbot-at-user id="{MEMBER_OID}" /> hi'
        with mock.patch.object(conn, "_chunk_count", return_value=1) as cc:
            conn._send_active_fallback(GROUP_OID, "group", plain, [])
        cc.assert_called_once_with("group", plain, [], has_mention=True)
        self.assertEqual(conn.api.sent[0][0], "markdown")  # 实发走 Markdown 通道

        conn.api = FakeApi()
        with mock.patch.object(conn, "_chunk_count", return_value=1) as cc:
            conn._send_active_fallback(GROUP_OID, "group", "plain hi", [])
        cc.assert_called_once_with("group", "plain hi", [], has_mention=False)
        self.assertEqual(conn.api.sent[0][0], "text")  # 无 @ 走文本通道

    def test_learn_bot_openid_prefers_member_openid(self):
        """N6：bot OpenID 取 member_openid（与 parser 一致），而非全局 id。"""
        conn = build_connector()
        conn.bot_openid = None
        conn._learn_bot_openid({"mentions": [
            {"bot": True, "id": "GLOBAL_ID", "member_openid": BOT_OID}
        ]})
        self.assertEqual(conn.bot_openid, BOT_OID)


def tearDownModule():
    for ctx in _TEMP_DIRS:
        ctx.cleanup()
    _TEMP_DIRS.clear()


if __name__ == "__main__":
    unittest.main()
