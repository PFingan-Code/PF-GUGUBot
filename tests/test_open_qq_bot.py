"""open-qq-bot 连接器集成测试。

运行方式（需插件依赖；MCDR 事件循环以 FakeServer 桩替代）：

    PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot -v

    # 依赖未安装时可临时引入：
    uv run --with mcdreforged --with requests --with ruamel-yaml --with pyyaml \
        --with websocket-client --with websocket-server --with mcstatus \
        PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot -v

本文件不做任何 sys.path 硬编码 / 包别名注册：包路径统一由
PYTHONPATH=GUGUbot 提供，保证 Linux/CI 可移植。
"""

import importlib.machinery
import sys


def _is_stub_module(m):
    """ModuleType 桩（无 __file__）判定，用于识别其他测试文件注册的假模块。"""
    return getattr(m, "__file__", None) is None


# 记录导入前已注册的 mcdreforged 模块（可能来自其他测试文件如 test_plugin_api
# 的桩注册），供模块末尾恢复，确保本文件不在 sys.modules 留下痕迹。
_SAVED_MCDR_MODULES = {
    k: sys.modules[k]
    for k in list(sys.modules)
    if k == "mcdreforged" or k.startswith("mcdreforged.")
}

# 其他测试文件（test_plugin_api）可能已向 sys.modules 注册 gugubot/mcdreforged
# 桩模块；先清除，保证本文件始终导入真实的 gugubot 包。
for _k in [
    k
    for k in list(sys.modules)
    if k == "gugubot"
    or k.startswith("gugubot.")
    or (
        (k == "mcdreforged" or k.startswith("mcdreforged."))
        and _is_stub_module(sys.modules[k])
    )
]:
    del sys.modules[_k]

try:
    from gugubot.connector import OpenQQBotConnector
    from gugubot.connector.open_qq_bot import common
    from gugubot.connector.open_qq_bot.api_client import (
        ApiClient,
        PassiveSeqExhausted,
        PartialDelivery,
        TokenManager,
    )
    from gugubot.connector.open_qq_bot.common import (
        INTENTS,
        ApiError,
        PassiveMsgPool,
        QuotaManager,
        SeqManager,
        split_markdown,
        split_message,
    )
    from gugubot.connector.open_qq_bot.connector import _MCDRForwardHandler
    from gugubot.connector.open_qq_bot.gateway import Gateway, GatewayStopped
    import gugubot.connector.open_qq_bot.gateway as gw
    from gugubot.connector.open_qq_bot.parser import OpenQQBotParser
    from gugubot.connector.qq_connector import (
        QQWebSocketConnector,
        WebSocketFactory,
    )
    from gugubot.logic.plugins.cross_broadcast import CrossBroadcastSystem
    from gugubot.logic.system.bound import BoundSystem
    from gugubot.logic.system.vote import VoteSystem
    from gugubot.utils.player_manager import Player
    from gugubot.utils.types import (
        BroadcastInfo,
        ProcessedInfo,
        Source,
        Source as Src,
    )
    from gugubot.utils.vote_manager import Vote
except ModuleNotFoundError as _e:  # pragma: no cover
    raise RuntimeError(
        "无法导入 gugubot 包；请按项目约定设置 PYTHONPATH=GUGUbot 后运行：\n"
        "  PYTHONPATH=GUGUbot python -m unittest tests.test_open_qq_bot"
    ) from _e

import asyncio
import logging
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
    """MCDR logger 桩。

    连接器的 _MCDRForwardHandler 会把子包日志转发到
    ``logger.log(levelno, ...)`` / ``logger.mdebug(..., no_check=True)``；
    桩缺这两个方法时 logging 内部走 handleError，向 stderr 打
    "Logging error" 噪音。这里记录调用，供 TestLogForwarding 断言。
    """

    def __init__(self):
        self.log_calls = []
        self.mdebug_calls = []

    def log(self, level, msg, *args, **kwargs):
        self.log_calls.append((level, msg))

    def mdebug(self, msg, no_check=False, *args, **kwargs):
        self.mdebug_calls.append((msg, no_check))

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

    def send_group_text(self, g, c, msg_id=None, event_id=None, reference=None,
                        seqs=None):
        self.sent.append(("text", g, c, msg_id))
        return {"id": "RID"}

    def send_group_markdown(self, g, c, msg_id=None, reference=None, seqs=None):
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
        # @机器人 自身的渲染前缀被剥离（M-7）
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

    async def test_at_other_user_becomes_at_segment(self):
        """@ 普通用户产出 at 段（OpenID + 昵称），游戏内才能渲染高亮/点击@。"""
        event = group_event(
            content=f"<@{MEMBER_OID}> #hello",
            mentions=[{"member_openid": MEMBER_OID, "id": MEMBER_OID,
                       "username": "一梦", "bot": False}],
        )
        info = await self.parser.parse(event)
        self.assertEqual(
            info.message[0],
            {"type": "at", "data": {"qq": MEMBER_OID, "name": "一梦"}},
        )
        self.assertEqual(info.message[1]["data"]["text"], " #hello")

    async def test_at_segment_keeps_order_between_text(self):
        """@ 段按 content 中的位置插入，前后文本不被压平。"""
        event = group_event(
            content=f"看 <@{MEMBER_OID}> 打游戏",
            mentions=[{"member_openid": MEMBER_OID, "id": MEMBER_OID,
                       "username": "一梦", "bot": False}],
        )
        info = await self.parser.parse(event)
        self.assertEqual([s["type"] for s in info.message],
                         ["text", "at", "text"])
        self.assertEqual(info.message[0]["data"]["text"], "看 ")
        self.assertEqual(info.message[1]["data"]["qq"], MEMBER_OID)
        self.assertEqual(info.message[2]["data"]["text"], " 打游戏")

    async def test_at_display_prefers_group_nickname(self):
        """群聊显示兜底优先用群内昵称（member_nickname），再退回全局昵称。"""
        event = group_event(
            content=f"<@{MEMBER_OID}> hi",
            mentions=[{"member_openid": MEMBER_OID, "id": MEMBER_OID,
                       "username": "一梦", "member_nickname": "群名片一梦",
                       "bot": False}],
        )
        info = await self.parser.parse(event)
        self.assertEqual(info.message[0]["data"]["name"], "群名片一梦")

    async def test_at_bot_not_emitted_as_segment(self):
        """@机器人 不产 at 段：否则 bound 系统会把机器人当成绑定目标。"""
        event = group_event(
            content=f"<@{BOT_OID}> #绑定 Steve <@{MEMBER_OID}>",
            mentions=[
                {"member_openid": BOT_OID, "id": BOT_OID,
                 "username": "林晚晴", "bot": True},
                {"member_openid": MEMBER_OID, "id": MEMBER_OID,
                 "username": "一梦", "bot": False},
            ],
        )
        info = await self.parser.parse(event)
        self.assertEqual([s["type"] for s in info.message], ["text", "at"])
        self.assertEqual(info.message[0]["data"]["text"], "#绑定 Steve ")
        self.assertEqual(info.message[1]["data"]["qq"], MEMBER_OID)

    async def test_hand_typed_at_tag_not_misidentified(self):
        """手打的 <@xxx> 不在 mentions 中，必须原样保留为文本。"""
        event = group_event(content=f"<@{MEMBER_OID}> 只是打字")
        info = await self.parser.parse(event)
        self.assertEqual([s["type"] for s in info.message], ["text"])
        self.assertEqual(info.message[0]["data"]["text"],
                         f"<@{MEMBER_OID}> 只是打字")

    async def test_hand_typed_at_text_not_misidentified(self):
        """手打的 @昵称 纯文本不产 at 段。"""
        event = group_event(content="@一梦 只是打字")
        info = await self.parser.parse(event)
        self.assertEqual([s["type"] for s in info.message], ["text"])
        self.assertEqual(info.message[0]["data"]["text"], "@一梦 只是打字")

    async def test_at_all_requires_scope_all(self):
        """<@all> 只有 mentions 标记 scope=all 时才视为 @全体成员。"""
        real = group_event(
            content="<@all> 集合",
            mentions=[{"scope": "all", "bot": False}],
        )
        info = await self.parser.parse(real)
        self.assertEqual([s["type"] for s in info.message], ["text"])
        self.assertEqual(info.message[0]["data"]["text"], "@全体成员 集合")

        fake = group_event(content="<@all> 集合")
        info = await self.parser.parse(fake)
        self.assertEqual(info.message[0]["data"]["text"], "<@all> 集合")

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

        def failing_send(g, c, msg_id=None, event_id=None, reference=None, seqs=None):
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

    def test_midchunk_passive_expiry_resends_suffix_actively(self):
        """N1（端到端）：分片中途被动过期 → 已送达片不重复，剩余片转主动补发。"""
        client = ApiClient(TokenManager("a", "b"))
        client.max_message_length = 10
        self.conn.max_message_length = 10  # 与 ApiClient 保持同源分片长度（生产构造即一致）
        passive, active = [], []

        def fake_call(method, path, body=None, timeout=10):
            if body.get("msg_id"):  # 被动回复：首片送达，其后窗口失效
                if not passive:
                    passive.append(body["content"])
                    return {"id": "R"}
                raise ApiError("POST", "u", 400, '{"err_code":40034005}', 40034005)
            active.append(body["content"])  # 主动通道：未送达后缀补发
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
        self.assertEqual(passive, ["A" * 10])  # 仅首片走被动
        self.assertEqual(active, ["A" * 10, "A" * 10])  # 后缀主动补发

    def test_passive_exhausted_falls_back_to_active(self):
        """SeqManager 次数耗尽时 send_* 返回 None 而非抛错：必须降级，不得静默丢弃。"""
        def exhausted_send(g, c, msg_id=None, event_id=None, reference=None, seqs=None):
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

        def failing_markdown(g, c, msg_id=None, reference=None, seqs=None):
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

    def test_malicious_image_url_rejected_as_placeholder(self):
        """#3 图片 URL 注入：CQ image 段 URL 含 `)` 与伪造 mention 标签。

        URL 出站时降级为 [图片] 文本（走纯文本通道），Markdown 通道不出现
        可提前闭合的 `![图片](...)`，也不得出现活的 <qqbot-at-user/> 标签。
        """
        url = f"https://i/x.png) <qqbot-at-user id=\"{MEMBER_OID}\" />"
        p = ProcessedInfo(
            processed_message=[{"type": "image", "data": {"file": url}}],
            _source=Source("Minecraft"), source_id="mc", sender="HAHH9527",
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        kind, _, content, _ = self.api.sent[0]
        self.assertEqual(kind, "text")  # 无合法图片、无真 @ → 纯文本通道
        self.assertIn("[图片]", content)
        self.assertNotIn("<qqbot-at-user", content)  # 无活 mention 标签
        self.assertNotIn("![图片](", content)  # 未进 Markdown 语法

    def test_image_url_rejects_backslash_and_fullwidth_space(self):
        """反斜杠结尾（转义收尾括号吞段）与全角空格 URL 同样拒绝。"""
        bad_urls = [
            "https://i/x.png\\",  # 尾反斜杠可转义收尾 `)`，吞掉后续内容
            "https://i/x\u3000.png",  # 全角空格可拆分注入片段
        ]
        for url in bad_urls:
            with self.subTest(url=url):
                self.api.sent.clear()
                p = ProcessedInfo(
                    processed_message=[{"type": "image", "data": {"file": url}}],
                    _source=Source("Minecraft"), source_id="mc", sender="HAHH9527",
                )
                p.target = {GROUP_OID: "group"}
                asyncio.run(self.conn.send_message(p))
                kind, _, content, _ = self.api.sent[0]
                self.assertEqual(kind, "text")
                self.assertIn("[图片]", content)
                self.assertNotIn("![图片](", content)

    def test_valid_image_url_still_embedded_in_markdown(self):
        """合法 URL（无 Markdown 语法字符）不受白名单影响，照常嵌入。"""
        p = ProcessedInfo(
            processed_message=[
                {"type": "image", "data": {"file": "https://i.example/x.png"}}],
            _source=Source("Minecraft"), source_id="mc", sender="HAHH9527",
        )
        p.target = {GROUP_OID: "group"}
        asyncio.run(self.conn.send_message(p))
        kind, _, content, _ = self.api.sent[0]
        self.assertEqual(kind, "markdown")
        self.assertIn("![图片](https://i.example/x.png)", content)


class TestPassiveMsgPool(unittest.IsolatedAsyncioTestCase):
    """群 msg_id 被动回复池：入站登记、最旧优先、额度/过期、出站优先与降级。"""

    def setUp(self):
        self.conn = build_connector()
        FakeServer.scheduled.clear()
        # 保留真实 SeqManager（池按它计算剩余额度），仅把 HTTP 层换成记录桩
        self._seq = self.conn.api.seq
        fake = FakeApi()
        fake.seq = self._seq
        self.conn.api = fake

    class SeqAwareApi(FakeApi):
        """模拟真实 api_client 的被动回复 seq 分配（含耗尽返回 None）。"""

        def send_group_text(self, g, c, msg_id=None, event_id=None, reference=None,
                            seqs=None):
            # 池路径的整块名额已由 SeqManager.reserve 预分配，不再 allocate
            if msg_id and seqs is None and self.seq.allocate(msg_id) is None:
                return None
            return super().send_group_text(g, c, msg_id, event_id, reference)

    @staticmethod
    def _mc_to_group(text="hi"):
        p = ProcessedInfo(
            processed_message=[{"type": "text", "data": {"text": text}}],
            _source=Source("Minecraft"), source_id="mc", sender="Steve",
        )
        p.target = {GROUP_OID: "group"}
        return p

    def test_inbound_group_event_records_msg_id(self):
        self.conn._on_gateway_event(
            "GROUP_MESSAGE_CREATE", group_event(msg_id="ANCHOR")["d"], None)
        self.assertEqual(self.conn.passive_pool.snapshot(GROUP_OID), ["ANCHOR"])
        drain_scheduled(run=False)

    def test_inbound_c2c_not_recorded(self):
        self.conn._on_gateway_event("C2C_MESSAGE_CREATE", {
            "id": "C1", "author": {"user_openid": USER_OID, "id": USER_OID},
            "content": "hi",
        }, None)
        self.assertEqual(self.conn.passive_pool.snapshot(GROUP_OID), [])
        drain_scheduled(run=False)

    def test_cap_evicts_oldest_and_acquire_oldest_first(self):
        pool = PassiveMsgPool(SeqManager())
        for i in range(10):
            pool.record(GROUP_OID, f"M{i}", now=1000 + i)
        self.assertEqual(pool.snapshot(GROUP_OID), [f"M{i}" for i in range(10)])
        pool.record(GROUP_OID, "M10", now=1010)
        self.assertEqual(len(pool.snapshot(GROUP_OID)), 10)
        self.assertEqual(pool.snapshot(GROUP_OID)[0], "M1")
        self.assertEqual(pool.acquire(GROUP_OID, 1, now=1010), ("M1", [1]))

    def test_expired_entries_removed_at_send_time(self):
        pool = PassiveMsgPool(SeqManager())
        pool.record(GROUP_OID, "OLD", now=0)       # expire_at = 290
        pool.record(GROUP_OID, "NEW", now=1000)
        self.assertEqual(pool.acquire(GROUP_OID, 1, now=1000)[0], "NEW")
        self.assertEqual(pool.snapshot(GROUP_OID), ["NEW"])
        self.assertIsNone(pool.acquire(GROUP_OID, 1, now=1300))
        self.assertEqual(pool.snapshot(GROUP_OID), [])

    def test_exhausted_removed_and_insufficient_skipped(self):
        seq = SeqManager()
        pool = PassiveMsgPool(seq)
        for _ in range(5):
            seq.allocate("M0")
        pool.record(GROUP_OID, "M0", now=1000)
        pool.record(GROUP_OID, "M1", now=1001)
        # 已用完的 M0 登记时即被清理
        self.assertEqual(pool.snapshot(GROUP_OID), ["M1"])
        for _ in range(4):
            seq.allocate("M1")
        pool.record(GROUP_OID, "M2", now=1002)
        # M1 只剩 1 次，本次需要 2 次 → 跳过但保留给更小的消息
        self.assertEqual(pool.acquire(GROUP_OID, 2, now=1002), ("M2", [1, 2]))
        self.assertEqual(pool.snapshot(GROUP_OID), ["M1", "M2"])

    def test_reservation_is_atomic_allocation_not_double_counted(self):
        """评审修复 #1：预留即分配，并发获取按 used 精确看到剩余名额。

        旧实现把「已分配（used）」与「池内预留（pending）」同时扣除：
        两片发送预留并分配 2 个 seq 后，第二个两片发送本应看到 3 个剩余
        名额，实际只看到 1 个而误降级走主动配额。
        """
        seq = SeqManager()
        pool = PassiveMsgPool(seq)
        pool.record(GROUP_OID, "M0", now=1000)
        msg_id, seqs = pool.acquire(GROUP_OID, 2, now=1000)
        self.assertEqual((msg_id, seqs), ("M0", [1, 2]))
        self.assertEqual(seq.used("M0"), 2)
        # 第二个两片发送：精确看到剩余 3 个名额并连续预留
        msg_id, seqs = pool.acquire(GROUP_OID, 2, now=1000)
        self.assertEqual((msg_id, seqs), ("M0", [3, 4]))
        self.assertIsNone(pool.acquire(GROUP_OID, 2, now=1000))  # 仅剩 1 个

    def test_reservation_binds_against_same_source_replies(self):
        """评审修复 #3：整块预留对同源回复/去重重试具约束力。"""
        seq = SeqManager()
        pool = PassiveMsgPool(seq)
        pool.record(GROUP_OID, "M0", now=1000)
        _, seqs = pool.acquire(GROUP_OID, 3, now=1000)
        self.assertEqual(seqs, [1, 2, 3])
        # 同源命令回复只能在整块之上分配剩余名额，无法挤占已预留的块
        self.assertEqual(seq.allocate("M0"), 4)
        self.assertEqual(seq.allocate("M0"), 5)
        self.assertIsNone(seq.allocate("M0"))
        self.assertEqual(seqs, [1, 2, 3])  # 预留块不受影响，按序消费即可

    def test_acquire_skips_anchor_without_lifetime_for_chunks(self):
        """评审修复 #2：剩余寿命不足以发完全部分片的锚点跳过，留给更小消息。"""
        seq = SeqManager()
        pool = PassiveMsgPool(seq)
        pool.record(GROUP_OID, "OLD", now=1000)    # expire_at = 1290
        # 3 片 → 门槛 5s 余量 + 2s×2 片间 = 9s；剩余寿命仅 3s → 跳过
        self.assertIsNone(pool.acquire(GROUP_OID, 3, now=1287))
        # 1 片门槛 5s 同样不足
        self.assertIsNone(pool.acquire(GROUP_OID, 1, now=1287))
        # 未过期不淘汰，留给寿命窗口内的小消息/新锚点
        self.assertEqual(pool.snapshot(GROUP_OID), ["OLD"])
        pool.record(GROUP_OID, "NEW", now=1288)    # expire_at = 1578
        self.assertEqual(pool.acquire(GROUP_OID, 3, now=1288)[0], "NEW")

    def test_send_end_evicts_exhausted_entry(self):
        seq = SeqManager()
        pool = PassiveMsgPool(seq)
        pool.record(GROUP_OID, "M0", now=1000)
        _, seqs = pool.acquire(GROUP_OID, 5, now=1000)
        self.assertEqual(seqs, [1, 2, 3, 4, 5])
        pool.release(GROUP_OID, "M0")
        self.assertEqual(pool.snapshot(GROUP_OID), [])  # 额度用尽即淘汰
        pool.release(GROUP_OID, "M0")  # 幂等：再次释放无害

    async def test_mc_broadcast_uses_pool_without_active_quota(self):
        api = self.SeqAwareApi()
        api.seq = self._seq
        self.conn.api = api
        self.conn._on_gateway_event(
            "GROUP_MESSAGE_CREATE", group_event(msg_id="ANCHOR")["d"], None)
        drain_scheduled(run=False)
        await self.conn.send_message(self._mc_to_group())
        kind, group, _, msg_id = self.conn.api.sent[0]
        self.assertEqual((kind, group, msg_id), ("text", GROUP_OID, "ANCHOR"))
        self.assertEqual(self.conn.api.seq.used("ANCHOR"), 1)
        self.assertNotIn(GROUP_OID, self.conn.quota._state)

    async def test_pool_empty_uses_active_message(self):
        await self.conn.send_message(self._mc_to_group())
        self.assertIsNone(self.conn.api.sent[0][3])
        self.assertIn(GROUP_OID, self.conn.quota._state)

    async def test_seq_increments_then_exhausted_falls_back_active(self):
        api = self.SeqAwareApi()
        api.seq = self._seq
        self.conn.api = api
        self.conn.passive_pool.record(GROUP_OID, "ANCHOR")
        for i in range(5):
            await self.conn.send_message(self._mc_to_group(f"m{i}"))
        self.assertEqual(self.conn.api.seq.used("ANCHOR"), 5)
        self.assertEqual([s[3] for s in self.conn.api.sent], ["ANCHOR"] * 5)
        self.assertEqual(self.conn.passive_pool.snapshot(GROUP_OID), [])
        await self.conn.send_message(self._mc_to_group("m5"))
        self.assertIsNone(self.conn.api.sent[-1][3])

    async def test_passive_expiry_invalidates_and_falls_back_active(self):
        class ExpiringApi(FakeApi):
            def send_group_text(self, g, c, msg_id=None, event_id=None, reference=None,
                                seqs=None):
                if msg_id:
                    raise ApiError("POST", "u", 400, "expired", err_code=40034005)
                return super().send_group_text(g, c, msg_id, event_id, reference)

        api = ExpiringApi()
        api.seq = self._seq
        self.conn.api = api
        self.conn.passive_pool.record(GROUP_OID, "ANCHOR")
        await self.conn.send_message(self._mc_to_group())
        self.assertEqual(self.conn.passive_pool.snapshot(GROUP_OID), [])
        self.assertEqual([s[3] for s in self.conn.api.sent], [None])

    async def test_seq_exhaustion_invalidates_and_falls_back_active(self):
        class ExhaustedApi(FakeApi):
            def send_group_text(self, g, c, msg_id=None, event_id=None, reference=None,
                                seqs=None):
                if msg_id:
                    return None
                return super().send_group_text(g, c, msg_id, event_id, reference)

        api = ExhaustedApi()
        api.seq = self._seq
        self.conn.api = api
        self.conn.passive_pool.record(GROUP_OID, "ANCHOR")
        await self.conn.send_message(self._mc_to_group())
        self.assertEqual(self.conn.passive_pool.snapshot(GROUP_OID), [])
        self.assertEqual([s[3] for s in self.conn.api.sent], [None])

    def test_debug_reply_shares_seq_budget(self):
        self.conn.passive_pool.record(GROUP_OID, "ANCHOR")
        self.conn.api.seq.allocate("ANCHOR")  # 调试回复消耗一次（api_client 记账）
        self.assertEqual(self.conn.api.seq.used("ANCHOR"), 1)
        self.assertIsNone(self.conn.passive_pool.acquire(GROUP_OID, 5))
        self.assertEqual(self.conn.passive_pool.acquire(GROUP_OID, 4),
                         ("ANCHOR", [2, 3, 4, 5]))

    async def test_pool_disabled_uses_active_message(self):
        conn = build_connector(default_config(passive_pool={"enable": False}))
        conn.api = FakeApi()
        conn._on_gateway_event(
            "GROUP_MESSAGE_CREATE", group_event(msg_id="ANCHOR")["d"], None)
        drain_scheduled(run=False)
        self.assertIsNone(conn.passive_pool)
        await conn.send_message(self._mc_to_group())
        self.assertIsNone(conn.api.sent[0][3])


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
        q = QuotaManager(per_minute=2, per_day=3, persist_path=self.path)
        assert q.allow("G")
        assert q.allow("G")
        assert not q.allow("G")  # 分钟窗口耗尽
        q._state["G"]["minute"] = []  # 手动放行分钟窗口（模拟时间流逝）
        assert q.allow("G")
        assert not q.allow("G")  # 日配额耗尽（3/3）

    def test_day_reset_and_persistence(self):
        import time
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
        q = QuotaManager(per_minute=1, per_day=10, persist_path=self.path)
        assert q.allow("A")
        assert not q.allow("A")
        assert q.allow("B")

    def test_bot_global_minute_window(self):
        """L-2：Bot 全局滑动窗口限制所有群合计的主动消息速率。"""
        q = QuotaManager(per_minute=2, per_day=100, bot_per_minute=3,
                         persist_path=self.path)
        assert q.allow("A")
        assert q.allow("A")  # A 的 key 级分钟窗口用尽（2/2）
        assert q.allow("B")
        assert not q.allow("B")  # 全局窗口用尽（3/3），即使 B 的 key 级未满

    def test_allow_many_counts_chunks(self):
        """分片发送按实际 API 请求数记账。"""
        q = QuotaManager(per_minute=3, per_day=100, bot_per_minute=10,
                         persist_path=self.path)
        assert q.allow_many("A", 3)  # 3 片一次计入
        assert not q.allow("A")  # 分钟窗口已满（3/3）
        assert not q.allow_many("A", 1)

    def test_allow_many_all_or_nothing(self):
        """容量不足时整体拒绝，不做部分消费。"""
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
            def send_group_text(self, g, c, msg_id=None, event_id=None, reference=None,
                                seqs=None):
                sent.append(("text", g, msg_id))
                return {"id": "R"}

            def send_group_markdown(self, g, c, msg_id=None, reference=None, seqs=None):
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

    async def _run(self, accounts, monitored_groups=None, logger=None):
        """构建 BoundSystem、写入绑定数据并投递一次退群事件。

        monitored_groups / logger 供多群跳过与告警断言类用例覆写：
        ``monitored_groups=None`` 保持默认单群（正常清理路径）。
        """
        bs = self._build_system(
            monitored_groups=monitored_groups, logger=logger)

        # 预置真实 PlayerManager 数据：平台键 = 连接器显示名（真实写入形态）
        pm = bs.player_manager
        pm._players["Steve"] = Player(
            name="Steve",
            java_name=["Steve"],
            accounts={k: list(v) for k, v in accounts.items()},
        )

        handled = await bs.process_broadcast_info(self._make_quit_info())
        return handled, pm, bs

    def _build_system(self, monitored_groups=None, logger=None):
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
                "open-qq-bot": {"permissions": {
                    "group_ids": [GROUP_OID] if monitored_groups is None
                    else monitored_groups}},
            },
        })
        bs = BoundSystem(fake_server, config=config)
        bs.logger = logger or FakeLogger()
        bs.whitelist = FakeWhitelist()
        bs.enable = True
        return bs

    def _make_quit_info(self):
        return BroadcastInfo(
            event_type="notice", event_sub_type="group_decrease",
            message=[{"type": "text", "data": {"text": ""}}],
            raw={"group_openid": GROUP_OID, "member_openid": USER_OID},
            server=FakeServer(), logger=FakeLogger(),
            _source=Src("OpenQQBot"), source_id=GROUP_OID,
            sender=USER_OID, sender_id=USER_OID,
        )

    async def test_official_quit_unbinds(self):
        handled, pm, bs = await self._run(accounts={"OpenQQBot": [USER_OID]})
        self.assertTrue(handled)
        self.assertIsNone(pm.get_player("Steve"))  # 绑定已整体清除
        self.assertEqual(bs.whitelist.removed, ["Steve"])  # 白名单同步移除

    async def test_official_quit_keeps_other_platform(self):
        """有 FPS 平台剩余绑定：白名单保留，仅删官方账户绑定。"""
        handled, pm, bs = await self._run(
            accounts={"OpenQQBot": [USER_OID], "FPS": ["steve_fps"]})
        self.assertTrue(handled)
        self.assertIsNotNone(pm.get_player("Steve"))  # 其他平台绑定保留
        player = pm.get_player("Steve")
        self.assertEqual(player.accounts.get("OpenQQBot", []), [])  # 官方账户已删
        self.assertEqual(player.accounts.get("FPS"), ["steve_fps"])
        self.assertEqual(player.java_name, ["Steve"])  # 玩家名保留
        self.assertEqual(bs.whitelist.removed, [])  # 有剩余绑定：白名单一并保留

    async def test_official_quit_ignores_unbound_user(self):
        """未绑定用户退群：不产生任何清理动作。"""
        handled, pm, bs = await self._run(accounts={"OpenQQBot": ["OTHEROID"]})
        self.assertFalse(handled)
        self.assertIsNotNone(pm.get_player("Steve"))  # 不受影响
        self.assertEqual(bs.whitelist.removed, [])

    async def test_official_quit_keeps_onebot_platform(self):
        """跨平台残留：OneBot 账户 + 官方同名账户双绑，官方退群只删官方账户。

        OneBot 绑定、Player、白名单全部保留（对照组：所有平台均无剩余时
        白名单+Player 照删，见 test_official_quit_unbinds）。
        """
        handled, pm, bs = await self._run(
            accounts={"QQ": ["123456"], "OpenQQBot": [USER_OID]})
        self.assertTrue(handled)
        player = pm.get_player("Steve")
        self.assertIsNotNone(player)  # Player 保留
        self.assertEqual(player.accounts.get("OpenQQBot", []), [])  # 官方账户已删
        self.assertEqual(player.accounts.get("QQ"), ["123456"])  # OneBot 账户保留
        self.assertEqual(player.java_name, ["Steve"])  # 玩家名保留
        self.assertEqual(bs.whitelist.removed, [])  # 有剩余绑定：白名单不动

    class _WarnLogger(FakeLogger):
        """记录 warning 调用的桩：断言退群跳过告警及其限频。"""

        def __init__(self):
            self.warnings = []

        def warning(self, *a, **k):
            self.warnings.append((a, k))

    async def test_official_quit_multi_group_skips_cleanup(self):
        """多群监听：退群事件无法证明退出全部监听群 → 不解绑并告警一次。"""
        log = self._WarnLogger()
        handled, pm, bs = await self._run(
            accounts={"OpenQQBot": [USER_OID]},
            monitored_groups=[GROUP_OID, "OTHERGROUP1OTHERGROUP1"],
            logger=log,
        )
        self.assertTrue(handled)  # 事件被消费（跳过语义），不落回广播管线
        player = pm.get_player("Steve")
        self.assertIsNotNone(player)
        self.assertEqual(player.accounts.get("OpenQQBot"), [USER_OID])  # 绑定未动
        self.assertEqual(player.java_name, ["Steve"])
        self.assertEqual(bs.whitelist.removed, [])
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("跳过", log.warnings[0][0][0])

    async def test_official_quit_multi_group_warn_rate_limited(self):
        """同群 1 小时内第二次退群：告警限频，仍只 1 条。"""
        log = self._WarnLogger()
        bs = self._build_system(
            monitored_groups=[GROUP_OID, "OTHERGROUP1OTHERGROUP1"], logger=log)
        pm = bs.player_manager
        pm._players["Steve"] = Player(
            name="Steve", java_name=["Steve"],
            accounts={"OpenQQBot": [USER_OID]})
        for _ in range(2):
            handled = await bs.process_broadcast_info(self._make_quit_info())
            self.assertTrue(handled)
        self.assertEqual(len(log.warnings), 1)  # 第二次限频，不再刷屏
        self.assertIsNotNone(pm.get_player("Steve"))  # 两次均未清理
        self.assertEqual(bs.whitelist.removed, [])

    async def test_official_quit_without_monitored_groups_skips(self):
        """group_ids 为空（全量监听形态）：无法枚举监听群 → 同样跳过清理。"""
        handled, pm, bs = await self._run(
            accounts={"OpenQQBot": [USER_OID]}, monitored_groups=[])
        self.assertTrue(handled)
        player = pm.get_player("Steve")
        self.assertIsNotNone(player)
        self.assertEqual(player.accounts.get("OpenQQBot"), [USER_OID])
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


class TestLogForwarding(unittest.TestCase):
    """子包日志转发 handler：INFO+ 走 log(levelno)，DEBUG 走 mdebug(no_check=True)。

    FakeLogger 补齐 .log/.mdebug 桩后，转发不再产生 "Logging error" stderr
    噪音，且可对转发行为做断言。注意 _diag_logger 是模块级共享 logger，
    handler 全局仅挂一个，重复构建连接器只重新指向最新实例。
    """

    def setUp(self):
        self.diag_logger = logging.getLogger("gugubot.open_qq_bot")
        self.conn = build_connector(default_config(verbose=True))

    def test_verbose_true_debug_goes_to_mdebug(self):
        """verbose=True：logger 级别 DEBUG，DEBUG 记录经 mdebug(no_check=True) 转发。"""
        self.assertEqual(self.diag_logger.level, logging.DEBUG)
        handler = self.diag_logger._mcdr_forward_handler
        self.assertEqual(handler.level, logging.DEBUG)
        self.conn._diag_logger.debug("verbose 调试内容")
        self.assertEqual(len(self.conn.logger.mdebug_calls), 1)
        msg, no_check = self.conn.logger.mdebug_calls[0]
        self.assertIn("verbose 调试内容", msg)
        self.assertTrue(no_check)
        self.assertEqual(self.conn.logger.log_calls, [])

    def test_info_goes_to_log_with_levelno(self):
        """INFO 记录走 log(levelno) 转发，不经 mdebug。"""
        self.conn._diag_logger.info("信息内容")
        self.assertEqual(len(self.conn.logger.log_calls), 1)
        level, msg = self.conn.logger.log_calls[0]
        self.assertEqual(level, logging.INFO)
        self.assertIn("信息内容", msg)
        self.assertEqual(self.conn.logger.mdebug_calls, [])

    def test_verbose_false_info_only(self):
        """verbose=False：级别 INFO，DEBUG 被级别门拦下，只有 INFO 转发。"""
        conn = build_connector()  # 默认无 verbose 配置
        self.assertEqual(conn._diag_logger.level, logging.INFO)
        handler = conn._diag_logger._mcdr_forward_handler
        self.assertEqual(handler.level, logging.INFO)
        conn._diag_logger.debug("被级别门拦下的调试")
        self.assertEqual(conn.logger.mdebug_calls, [])
        conn._diag_logger.info("放行的信息")
        self.assertEqual(len(conn.logger.log_calls), 1)

    def test_rebuild_reuses_single_handler(self):
        """重复构建连接器不重复 attach handler，且指向最新连接器实例。"""
        conn2 = build_connector(default_config(verbose=True))
        forward_handlers = [
            h for h in self.diag_logger.handlers
            if isinstance(h, _MCDRForwardHandler)
        ]
        self.assertEqual(len(forward_handlers), 1)
        self.assertIs(
            self.diag_logger._mcdr_forward_handler,
            conn2._diag_logger._mcdr_forward_handler,
        )
        # 重载（重复构建）后弱引用重定向：新连接器的日志才被转发
        self.assertIs(
            self.diag_logger._mcdr_forward_handler._connector_ref(), conn2)

    def test_exc_info_appends_traceback_text(self):
        """带 exc_info 的记录：转发消息附加格式化堆栈文本。"""
        try:
            raise ValueError("boom")
        except ValueError:
            self.conn._diag_logger.warning("发送失败", exc_info=True)
        level, msg = self.conn.logger.log_calls[0]
        self.assertEqual(level, logging.WARNING)
        self.assertIn("发送失败", msg)
        self.assertIn("Traceback", msg)
        self.assertIn("ValueError: boom", msg)


class TestSeqAccounting(unittest.TestCase):
    """msg_seq 记账：seq 严格递增不回退，未被服务端接受的 seq 精确回退；
    被动名额耗尽（duplicate 拒绝）返回 None 供降级，本地与服务端账本对齐。"""

    def _client(self):
        return ApiClient(TokenManager("a", "b"))

    def test_group_retry_failure_releases_seq(self):

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

    def test_group_retry_success_ledger_aligned(self):
        """去重重试成功：seq 严格递增不回退，本地与服务端账本对齐（消费 2 个）。"""

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
        # 基 seq=1 与重试 seq=2 均已被服务端消费：账本对齐，不回退
        self.assertEqual(client.seq._seqs.get("M", 0), 2)

    def test_c2c_retry_failure_releases_seq(self):

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

        client = self._client()

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 500, '{"err_code":500}', 500)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_c2c_text("U", "hi", msg_id="M")
        self.assertEqual(client.seq._seqs.get("M", 0), 0)

    def test_c2c_retry_success_ledger_aligned(self):
        """去重重试成功：seq 严格递增不回退，本地与服务端账本对齐（消费 2 个）。"""

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
        self.assertEqual(calls["n"], 2)
        # 基 seq=1 与重试 seq=2 均已被服务端消费：账本对齐，不回退
        self.assertEqual(client.seq._seqs.get("M", 0), 2)

    def test_network_error_releases_seq(self):
        """N2：网络层失败统一为 status=0 的 ApiError，seq 走同一回退路径。"""

        client = self._client()

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 0, "connection reset", None, None)

        client._call = fake_call
        with self.assertRaises(ApiError):
            client.send_group_text("G", "hi", msg_id="M")
        self.assertEqual(client.seq._seqs.get("M", 0), 0)

    def test_group_double_dup_exhaust_returns_none_base_seq_kept(self):
        """连续 duplicate 耗尽名额：首片 PassiveSeqExhausted → 返回 None
        （主动消息降级信号，不再抛 ApiError）；基 seq 已被服务端消费不回退。"""

        client = self._client()
        client.seq._seqs["M"] = 3  # 预占 3 个名额（上限 5）

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)

        client._call = fake_call
        self.assertIsNone(client.send_group_text("G", "hi", msg_id="M"))
        # 基 seq=4 被 duplicate 拒绝（服务端已消费）不回退；重试 seq=5 名额
        # 耗尽未发出，精确回退 → 账本停在 4
        self.assertEqual(client.seq._seqs.get("M", 0), 4)

    def test_c2c_double_dup_exhaust_returns_none_base_seq_kept(self):
        """连续 duplicate 耗尽名额（单聊）：返回 None 降级信号；基 seq 不回退。"""

        client = self._client()
        client.seq._seqs["M"] = 3

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)

        client._call = fake_call
        self.assertIsNone(client.send_c2c_text("U", "hi", msg_id="M"))
        # 基 seq=4 被 duplicate 拒绝（服务端已消费）不回退；重试 seq=5 名额
        # 耗尽未发出，精确回退 → 账本停在 4
        self.assertEqual(client.seq._seqs.get("M", 0), 4)

    def test_retry_success_next_allocate_increments(self):
        """换 seq 重试成功后，下一次 allocate 返回递增 seq（不复用已接受值）。"""

        client = self._client()
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)
            return {"id": "R"}

        client._call = fake_call
        client.send_group_text("G", "hi", msg_id="M")
        # 已接受 seq=1/2，下一次分配必须跳到 3；复用旧值会再次命中去重
        self.assertEqual(client.seq.allocate("M"), 3)

    def test_release_ignores_non_top_seq(self):
        """release 按 seq 精确释放：非栈顶忽略，栈顶生效，None 直接忽略。"""

        client = self._client()
        first = client.seq.allocate("M")  # seq=1
        second = client.seq.allocate("M")  # seq=2（栈顶）
        self.assertEqual((first, second), (1, 2))
        client.seq.release("M", first)  # 非栈顶：不误放其他发送方预留的名额
        self.assertEqual(client.seq._seqs.get("M", 0), 2)
        client.seq.release("M", None)  # 无 seq（主动消息等）：直接忽略
        self.assertEqual(client.seq._seqs.get("M", 0), 2)
        client.seq.release("M", second)  # 栈顶：生效
        self.assertEqual(client.seq._seqs.get("M", 0), 1)

    def test_passive_seq_exhausted_first_chunk_returns_none_not_apierror(self):
        """基 seq 被 duplicate 拒绝后名额耗尽：首片返回 None（降级信号）。

        PassiveSeqExhausted 不是 ApiError：connector 的 ``except ApiError``
        不得误捕它（误捕会把降级信号当错误吞掉/重复回退 seq）。
        """
        self.assertFalse(issubclass(PassiveSeqExhausted, ApiError))

        client = self._client()
        client.seq._seqs["M"] = 4  # 基 seq=5 是最后一个名额

        def fake_call(method, path, body=None, timeout=10):
            raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)

        client._call = fake_call
        self.assertIsNone(client.send_group_text("G", "hi", msg_id="M"))
        # 基 seq=5 被 duplicate 拒绝 = 服务端已消费，不回退
        self.assertEqual(client.seq._seqs.get("M", 0), 5)

    def test_passive_seq_exhausted_midchunk_raises_partial_delivery(self):
        """名额耗尽发生在中段：转 PartialDelivery（同一异常族语义，不混入 ApiError）。"""

        client = self._client()
        client.seq._seqs["M"] = 3
        client.max_message_length = 10
        calls = {"n": 0}

        def fake_call(method, path, body=None, timeout=10):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"id": "R"}  # 首片（seq=4）成功
            raise ApiError("POST", "u", 400, '{"err_code":40054005}', 40054005)

        client._call = fake_call
        with self.assertRaises(PartialDelivery) as ctx:
            client.send_group_text("G", "z" * 20, msg_id="M")
        self.assertEqual((ctx.exception.sent, ctx.exception.remaining), (1, 1))
        # 第二片基 seq=5 被 duplicate 拒绝 = 服务端已消费，不回退
        self.assertEqual(client.seq._seqs.get("M", 0), 5)


class TestChunking(unittest.TestCase):
    """M-2 / L-1：Markdown 与单聊文本分片，split 防御非法长度。"""

    def _client(self):
        return ApiClient(TokenManager("a", "b"))

    def test_split_message_invalid_length(self):
        # <=0 会死循环；非整数会 TypeError —— 均需防御（非法值钳/回退默认值）
        self.assertEqual(len(split_message("hello", 0)), 5)  # 钳到 1，逐字符切不死循环
        self.assertEqual(len(split_message("a" * 10, 0)), 10)
        self.assertEqual(split_message("hello", None), ["hello"])  # 非法值回退默认 2000
        self.assertEqual(split_message("", 0), [])

    def test_split_markdown_basic(self):
        chunks = split_markdown("a" * 30, 10)
        self.assertEqual("".join(chunks), "a" * 30)
        self.assertTrue(all(len(c) <= 10 for c in chunks))

    def test_split_markdown_protects_tags_and_urls(self):
        tag = '<qqbot-at-user id="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" />'
        url = "https://example.com/aaaaaaaaaaaaaaaaaaaa"
        content = f"前缀\n{tag}\n中\n![图片]({url})\n尾"
        chunks = split_markdown(content, 60)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(any(tag in c for c in chunks))  # @ 标签不被切断
        self.assertTrue(any(f"![图片]({url})" in c for c in chunks))  # 图片不被切断

    def test_split_markdown_backtracks_across_protected_span(self):
        """切点默认落在受保护片段内部时，回退到片段起点之前。"""
        url = "https://e.com/" + "x" * 12  # 20 字符受保护片段
        content = "a" * 25 + url + "b" * 25
        chunks = split_markdown(content, 30)
        self.assertTrue(any(url in c for c in chunks))  # URL 完整保留
        self.assertEqual("".join(chunks), content)  # 内容不丢

    def test_split_markdown_protected_span_longer_than_limit(self):
        """单个受保护片段超长：放弃保护硬切，保证终止。"""
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
        def unauthorized():
            raise ApiError("GET", "u", 401, "invalid appid", None, None)

        g = self._gateway(unauthorized)
        with self.assertRaises(GatewayStopped):
            g.run()

    def test_transient_http_error_retried(self):
        """5xx 属可重试错误：不触发凭据终止。"""

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

        g = self._gateway(lambda: "wss://example")

        def url_then_stop():
            g._stop = True  # 模拟获取网关地址期间 stop() 被调用
            return "wss://example"

        g._get_url = url_then_stop
        with mock.patch.object(gw.websocket, "WebSocketApp") as ws_cls:
            g.run()
        ws_cls.assert_not_called()

    def test_connect_joins_stale_thread_before_restart(self):
        """connect join：旧网关线程存活时先 stop+join 再启新线程，不双写状态。"""
        import threading
        from unittest import mock

        g = self._gateway(lambda: "wss://example")
        # 旧线程阻塞在网关自身的 stop_event 上（模拟退避等待/阻塞在 _get_url）
        old = threading.Thread(target=g._stop_event.wait, args=(30,), daemon=True)
        g._thread = old
        old.start()
        self.assertTrue(g.alive)

        # 新线程 run() 的重连等待改桩：wait 返回 True 视为收到停止请求，
        # 新线程一拍即退，只验证线程交接与「仅一个活跃循环」
        g._stop_event.wait = lambda timeout=None: True
        g._heartbeat_loop = lambda ws: None  # 心跳线程桩：本用例不涉及心跳

        with mock.patch.object(gw.websocket, "WebSocketApp") as ws_cls:
            g.connect()
            self.assertIsNot(g._thread, old)
            self.assertFalse(old.is_alive())  # 旧线程已被 join 退出
            new_thread = g._thread
            new_thread.join(timeout=5)
            self.assertFalse(new_thread.is_alive())  # 新循环也正常结束
            self.assertEqual(ws_cls.call_count, 1)  # 仅新线程建连一次

    def test_connect_join_timeout_fails_safe(self):
        """join 超时分支：旧线程超时未退出 → 记 ERROR，不启新线程，_stop 保持。"""
        from unittest import mock

        g = self._gateway(lambda: "wss://example")

        class StuckThread:
            def is_alive(self):
                return True

            def join(self, timeout=None):
                pass  # 模拟旧线程阻塞在 _get_url，25s 内未退出

        stuck = StuckThread()
        g._thread = stuck
        with mock.patch.object(gw.websocket, "WebSocketApp") as ws_cls:
            g.connect()
        self.assertIs(g._thread, stuck)  # 未启动新线程
        self.assertTrue(g._stop)  # 保持停止状态（不清 stop_event、不复位标志）
        ws_cls.assert_not_called()

    def test_close_code_4014_stops_with_intent_hint(self):
        """4014（intents 权限不足）：记录关闭码并终止，消息含码与 intent 提示。"""
        from unittest import mock

        g = self._gateway(lambda: "wss://example")
        g._on_close(None, 4014, "invalid intents")
        self.assertEqual(g._close_code, 4014)
        g._heartbeat_loop = lambda ws: None  # 心跳线程桩：本用例不涉及心跳
        with mock.patch.object(gw.websocket, "WebSocketApp"):
            with self.assertRaises(GatewayStopped) as ctx:
                g.run()  # 不得静默重新 Identify 无限重连
        self.assertIn("4014", str(ctx.exception))
        self.assertIn("intent", str(ctx.exception))

    def test_close_code_4002_stops_without_intent_hint(self):
        """4002（参数无效）：同样终止，但消息不含 intent 排查提示。"""
        from unittest import mock

        g = self._gateway(lambda: "wss://example")
        g._on_close(None, 4002, "invalid params")
        self.assertEqual(g._close_code, 4002)
        self.assertFalse(g._reidentify)
        g._heartbeat_loop = lambda ws: None
        with mock.patch.object(gw.websocket, "WebSocketApp"):
            with self.assertRaises(GatewayStopped) as ctx:
                g.run()
        self.assertIn("4002", str(ctx.exception))
        self.assertNotIn("intent", str(ctx.exception))

    def test_close_code_4008_4009_keep_resume_reconnect(self):
        """4008/4009 仍是可重连码：不终止、不记录终止码、session 保持（Resume）。"""
        g = self._gateway(lambda: "wss://example")
        g._on_close(None, 4008, "rate limited")
        g._on_close(None, 4009, "session timeout")
        self.assertIsNone(g._close_code)
        self.assertFalse(g._reidentify)  # 走 Resume 保 session，而非重新 Identify
        g.stop()
        g.run()  # 不抛 GatewayStopped：可重试码不终止重连循环

        # 既有行为保持：未知码（非 RESUME 集）仍走重新 Identify
        g2 = self._gateway(lambda: "wss://example")
        g2._on_close(None, 4999, "unknown")
        self.assertTrue(g2._reidentify)
        self.assertIsNone(g2._close_code)


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

    def test_ack_delay_does_not_drift_beat_interval(self):
        """心跳基准：ACK 往返延迟不累计进节拍，相邻两拍间隔 ≈ interval。

        节拍从发送时刻起算（剩余间隔补足等待），而非 ACK 返回后再睡满
        interval（后者实际节拍 = interval + 延迟，逐拍漂移累计）。
        """
        import types
        from unittest import mock

        interval = 1.0
        clock = {"t": 0.0}

        def fake_monotonic():
            return clock["t"]

        g = self._gateway()
        g._heartbeat_interval = interval
        g._hello.set()
        g._ready.set()

        sends = []

        def on_send(ws):
            sends.append(clock["t"])
            if len(sends) >= 2:
                ws.keep_running = False  # 两拍后退出循环

        ws = FakeGatewayWS(on_send=on_send)

        def fake_ack_wait(timeout=None):
            clock["t"] += 0.1 * interval  # 模拟 ACK 往返耗时
            return True

        def fake_stop_wait(timeout=None):
            clock["t"] += timeout or 0.0  # 补足剩余间隔的等待推进假时钟
            return False

        g._ack.wait = fake_ack_wait
        g._stop_event.wait = fake_stop_wait

        # 只替换 gateway 命名空间里的 time 引用（不全局 patch time.monotonic）：
        # 其他线程（如残留的心跳守护线程经 threading 内部计时）不受影响
        fake_time = types.SimpleNamespace(monotonic=fake_monotonic)
        with mock.patch.object(gw, "time", fake_time), \
                self.assertLogs("gugubot.open_qq_bot", level="DEBUG") as logs:
            g._heartbeat_loop(ws)

        self.assertEqual(len(sends), 2)
        # 实际节拍 = interval（含 0.1×interval 的 ACK 延迟被补足吸收）
        self.assertAlmostEqual(sends[1] - sends[0], interval, places=6)
        self.assertNotEqual(sends[1] - sends[0], interval + 0.1 * interval)
        # 间隔未超 1.5×interval：不触发漂移 WARNING
        self.assertFalse(any("WARNING" in m for m in logs.output))


class TestCrossBroadcastQQRouting(unittest.IsolatedAsyncioTestCase):
    """M-6：!!qq 路由到所有已启用的 QQ 类连接器，且不回落 echo。"""

    async def _run(self, enabled=("QQ",), group_ids=None, openids=None):
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


class TestCrossBroadcastSubServerGuard(unittest.IsolatedAsyncioTestCase):
    """子服守卫：子服本机 MC 来源的 !!qq 让路给 echo→Bridge，不在子服消费。

    子服通常不持有 QQ 连接器：此处若消费会短路 echo 转发路径，!!qq 永远
    到不了主服。bridge 来源（已在主服消费过）在子服不放行，避免 !!qq 原文
    被喷进子服聊天。
    """

    def _build(self, is_main=True):
        class FakeConnector:
            def __init__(self, source, enable):
                self.source = source
                self.enable = enable
                self.enable_send = True

        class FakeManager:
            def __init__(self, connectors):
                self.connectors = connectors

            def get_connector(self, source):
                return next(
                    (c for c in self.connectors if c.source == source), None)

        connectors = [
            FakeConnector("QQ", True),
            FakeConnector("OpenQQBot", True),
        ]
        config = FakeConfig({
            "system": {"cross_broadcast": {
                "enable": True,
                "qq_forward_group_ids": [],
                "qq_forward_openids": [],
            }},
            "connector": {
                "QQ": {"source_name": "QQ"},
                "open-qq-bot": {"source_name": "OpenQQBot"},
                "minecraft": {"source_name": "Minecraft"},
                "minecraft_bridge": {"source_name": "Bridge",
                                     "is_main_server": is_main},
            },
            "GUGUBot": {"command_prefix": "#"},
        })
        system = CrossBroadcastSystem(config=config)
        system.system_manager = type(
            "SM", (), {"connector_manager": FakeManager(connectors)}
        )()
        system.logger = FakeLogger()
        return system

    def _info(self, source_origin):
        return BroadcastInfo(
            event_type="message", event_sub_type="group",
            message=[{"type": "text", "data": {"text": "!!qq 大家好"}}],
            raw=None, server=FakeServer(), logger=FakeLogger(),
            _source=Src(source_origin), source_id="mc",
            sender="Steve", sender_id="steve",
        )

    async def _process(self, system, info):
        calls = []

        async def spy_forward(broadcast_info, message, **kw):
            calls.append((broadcast_info.source.origin, message))
            return True

        system._broadcast_to_qq_connectors = spy_forward
        handled = await system.process_broadcast_info(info)
        return handled, calls

    async def test_sub_server_mc_source_not_consumed(self):
        """子服 MC 来源 !!qq：守卫让路（返回 False），不进入 QQ 投递。"""
        system = self._build(is_main=False)
        handled, calls = await self._process(system, self._info("Minecraft"))
        self.assertFalse(handled)  # 落回 echo → Bridge 转发到主服
        self.assertEqual(calls, [])

    async def test_sub_server_bridge_source_still_consumed(self):
        """子服收到 bridge 转发的 !!qq：不放行给 echo，仍被消费防原文泄漏。"""
        system = self._build(is_main=False)
        handled, calls = await self._process(system, self._info("Bridge"))
        self.assertTrue(handled)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "Bridge")

    async def test_main_server_mc_source_still_consumed(self):
        """主服 MC 来源 !!qq：照常消费并投递（防 !!qq 原文经 echo 泄漏）。"""
        system = self._build(is_main=True)
        handled, calls = await self._process(system, self._info("Minecraft"))
        self.assertTrue(handled)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "Minecraft")


class TestVotePlatformKeys(unittest.IsolatedAsyncioTestCase):
    """投票平台键：官方连接器（OpenQQBot source）绑定与 OneBot 绑定同具资格。

    官方绑定账号是 32 位 OpenID，与 OneBot 数字 QQ 号属不相交字符串空间，
    两个平台键下的绑定都计入资格集合，OpenID 可直接作为投票者身份。
    """

    OFFICIAL_OID = "D" * 32

    async def asyncSetUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def _build(self, accounts):
        fake_server = FakeServer()
        fake_server.data_folder = self._tmpdir.name
        config = FakeConfig({
            "system": {"vote": {"enable": False}},
            "connector": {
                "QQ": {"source_name": "QQ"},
                "open-qq-bot": {"source_name": "OpenQQBot"},
            },
            "GUGUBot": {"show_message_in_console": False},
        })
        system = VoteSystem(fake_server, config)
        system.logger = FakeLogger()
        system.player_manager._players["Steve"] = Player(
            name="Steve", java_name=["Steve"],
            accounts=dict(accounts))
        # online_player_api 桩：返回固定的在线玩家列表
        system._get_online_players = lambda: ["Steve"]
        return system

    async def test_official_bound_player_eligible(self):
        """经官方连接器（OpenQQBot source）绑定的玩家出现在资格集合。"""
        system = self._build({"OpenQQBot": [self.OFFICIAL_OID]})
        eligible = await system._get_eligible_voters()
        self.assertEqual(eligible, {self.OFFICIAL_OID})

    async def test_onebot_bound_player_eligible_unchanged(self):
        """OneBot 绑定玩家路径不变（既有行为回归保护）。"""
        system = self._build({"QQ": ["123456"]})
        eligible = await system._get_eligible_voters()
        self.assertEqual(eligible, {"123456"})

    async def test_official_openid_casts_valid_vote(self):
        """OpenID 作为投票者身份：从官方来源消息解析身份并投出有效票。"""
        system = self._build({"OpenQQBot": [self.OFFICIAL_OID]})
        eligible = await system._get_eligible_voters()
        info = BroadcastInfo(
            event_type="message", event_sub_type="group",
            message=[{"type": "text", "data": {"text": "111"}}],
            raw=None, server=FakeServer(), logger=FakeLogger(),
            _source=Src("OpenQQBot"), source_id=GROUP_OID,
            sender="官方用户", sender_id=self.OFFICIAL_OID,
        )
        voter_id = await system._get_voter_id_from_broadcast(info)
        self.assertEqual(voter_id, self.OFFICIAL_OID)
        vote = Vote(
            vote_id="v1", vote_type="shutdown", initiator="Steve",
            initiator_id=self.OFFICIAL_OID, eligible_voters=eligible,
            required_percentage=1.0,
        )
        success, is_new_vote, is_same_vote = vote.cast_vote(voter_id, True)
        self.assertTrue(success)
        self.assertEqual(vote.yes_votes, {self.OFFICIAL_OID})

    async def test_platform_keys_order_and_dedup(self):
        """平台键：OneBot 在前（默认投票身份向后兼容），重名配置去重。"""
        system = self._build({})
        self.assertEqual(system._qq_platform_keys(), ("QQ", "OpenQQBot"))
        # 用户把两个来源名配成同一个值：去重，不产生重复资格键
        system.config["connector"]["open-qq-bot"]["source_name"] = "QQ"
        self.assertEqual(system._qq_platform_keys(), ("QQ",))


class TestQQConnectorEnableGuard(unittest.TestCase):
    """回归：OneBot QQ 连接器 enable=false 时不得发起连接（WinError 10061）。"""

    def _build(self, enable):
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
        with mock.patch.object(WebSocketFactory, "create_client") as factory:
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

        with mock.patch.object(common.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("conn reset")):
            with self.assertRaises(common.ApiError) as ctx:
                common.http_json("GET", "https://example.com")
        self.assertEqual(ctx.exception.status, 0)

    def test_http_json_incomplete_read_becomes_apierror(self):
        """N2：IncompleteRead（HTTPException，非 OSError）同样归一为 status=0。"""
        import http.client
        from unittest import mock

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


# 将 gugubot.* 从 sys.modules 摘除：本文件通过模块级名称直接引用真实对象，
# 同时避免污染 sys.modules，影响依赖桩注册的测试文件（test_plugin_api）。
for _k in [
    k for k in list(sys.modules) if k == "gugubot" or k.startswith("gugubot.")
]:
    del sys.modules[_k]

# mcdreforged：摘除导入真实 gugubot 时连带引入的子模块，并恢复导入前已存在
# 的注册项（可能是 test_plugin_api 的桩）。若不恢复，plugin_api 测试中的
# 函数级 `from mcdreforged.api.event import MCDRPluginEvents` 会解析到真实
# 库（其 PLUGIN_UNLOADED 是 MCDREvent 对象而非桩提供的字符串 id），破坏其断言。
for _k in [
    k
    for k in list(sys.modules)
    if (k == "mcdreforged" or k.startswith("mcdreforged."))
    and k not in _SAVED_MCDR_MODULES
]:
    del sys.modules[_k]
sys.modules.update(_SAVED_MCDR_MODULES)


# 其他测试文件（test_config / test_parser）的过期导入在收集阶段失败时，
# 仍会重新执行真实的 gugubot/__init__，把 gugubot.api 与
# gugubot.logic.system.plugin_commands 残留在 sys.modules；这会让
# test_plugin_api 的 _install_stubs 守卫（"gugubot.api" in sys.modules）
# 提前返回真实模块，桩注册失效。此钩子在真实 gugubot 包每次从磁盘导入
# 完成后立即摘除这两个键，确保桩守卫永远不误判。gugubot 包自身及其余
# 子模块照常保留（test_websocket 等仍可正常导入真实 gugubot.ws）。
class _GuardKeyScrubbingFinder:
    """sys.meta_path 钩子：真实导入 gugubot 包后摘除桩守卫键。"""

    _GUARD_KEYS = (
        "gugubot.logic.system.plugin_commands",
        "gugubot.api",
    )

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "gugubot" or "gugubot" in sys.modules:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        real_loader = spec.loader

        class _ScrubbingLoader:
            def __getattr__(self, name):
                return getattr(real_loader, name)

            def create_module(self, s):
                return real_loader.create_module(s)

            def exec_module(self, module):
                real_loader.exec_module(module)
                for _k in _GuardKeyScrubbingFinder._GUARD_KEYS:
                    sys.modules.pop(_k, None)

        spec.loader = _ScrubbingLoader()
        return spec


sys.meta_path.insert(0, _GuardKeyScrubbingFinder())


def tearDownModule():
    for ctx in _TEMP_DIRS:
        ctx.cleanup()
    _TEMP_DIRS.clear()


if __name__ == "__main__":
    unittest.main()
