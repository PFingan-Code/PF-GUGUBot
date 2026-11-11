"""open-qq-bot 连接器公共工具：错误码、限流、去重、分片、@ 标签。

由 devDocs/open-qq-bot/demo/qq_official_demo.py 的公共部分拆分而来，
行为与官方文档（devDocs/open-qq-bot/消息、起步指南）对齐。
"""

import json
import logging
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict

logger = logging.getLogger("gugubot.open_qq_bot")

# 被动消息规则（消息/group-messages-post.md）：有效时间 5 分钟，每个 msg_id 最多回复 5 次
PASSIVE_REPLY_MAX = 5
PASSIVE_REPLY_TTL = 10 * 60  # 稍大于 5 分钟窗口，便于清理过期记录

# 官方错误码（group-messages-post.md 错误码表 + 实测补充）
ERR_DUPLICATED = 40054005        # 消息被去重：相同 msg_id + msg_seq 重复发送
ERR_PASSIVE_EXPIRED = {304103, 40034005, 40034128}  # 被动回复过期/超次
ERR_AT_EVERYONE_LIMIT = 40034142  # @全体成员次数超限（每群每天 1 次，实测补充）


class ApiError(RuntimeError):
    """带官方错误码的 API 调用异常，便于按错误码做重试/降级。

    官方响应里 ``err_code`` 与 ``code`` 含义不总是一致（如群成员列表接口
    ``code=11253`` 无权限、``err_code=40012010``），两个字段都保留供判断。
    """

    def __init__(self, method, url, status, message, err_code=None, api_code=None):
        super().__init__(f"{method} {url} -> HTTP {status}: {message}")
        self.err_code = err_code
        self.api_code = api_code

    def has_code(self, *codes) -> bool:
        """判断响应中任一错误码字段是否命中给定码值。"""
        return any(c in (self.err_code, self.api_code) for c in codes)


def _preview(text, limit=300):
    """日志用：超长内容截断。"""
    text = text or ""
    return text if len(text) <= limit else f"{text[:limit]}...(共{len(text)}字符)"


def _safe_resp(text):
    """日志用：响应体脱敏（access_token 不落盘）+ 截断。"""
    text = re.sub(r'("access_token"\s*:\s*")[^"]+(")', r"\1***\2", text or "")
    return _preview(text)


def _safe_body(body):
    """日志用：请求体脱敏（clientSecret 不落盘）+ 截断。"""
    if body is None:
        return "-"
    if isinstance(body, dict):
        body = {k: ("***" if "secret" in k.lower() else v) for k, v in body.items()}
    return _preview(json.dumps(body, ensure_ascii=False))


def http_json(method, url, token=None, body=None, timeout=10):
    """调用官方 REST API 并记录请求/响应日志（凭证脱敏）。

    Raises
    ------
    ApiError
        HTTP 非 2xx 时抛出，携带 ``err_code`` / ``api_code``。
    """
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"QQBot {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    logger.debug("[HTTP →] %s %s body=%s", method, url, _safe_body(body))
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            cost = int((time.monotonic() - start) * 1000)
            logger.debug("[HTTP ←] %s %s %sms resp=%s", method, url, cost,
                         _safe_resp(raw.decode(errors="replace")))
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        cost = int((time.monotonic() - start) * 1000)
        logger.warning("[HTTP ←] %s %s -> HTTP %s (%sms) resp=%s", method, url, e.code, cost,
                       _safe_resp(text))
        err_code = None
        api_code = None
        try:
            payload = json.loads(text)
            err_code = payload.get("err_code")
            api_code = payload.get("code")
        except json.JSONDecodeError:
            pass
        raise ApiError(method, url, e.code, text, err_code, api_code) from e


class SeqManager:
    """被动回复 msg_seq 分配器。

    官方规则（消息/group-messages-post.md）：相同 msg_id + msg_seq 会被去重
    拒绝（40054005）；同一 msg_id 被动回复最多 5 次、5 分钟内有效。
    """

    def __init__(self):
        self._seqs = {}
        self._seen_at = {}
        self._lock = threading.Lock()

    def allocate(self, msg_id):
        """为 msg_id 分配下一个可用 msg_seq；超限返回 None。"""
        with self._lock:
            seq = self._seqs.get(msg_id, 0) + 1
            if seq > PASSIVE_REPLY_MAX:
                logger.warning("msg_id=%s 被动回复已达 %s 次上限，跳过", msg_id, PASSIVE_REPLY_MAX)
                return None
            self._seqs[msg_id] = seq
            self._seen_at[msg_id] = time.time()
            self._prune()
            return seq

    def release(self, msg_id):
        """发送失败时回退一次配额，避免白白消耗 5 次机会。"""
        with self._lock:
            if self._seqs.get(msg_id, 0) > 0:
                self._seqs[msg_id] -= 1

    def _prune(self):
        now = time.time()
        expired = [k for k, t in self._seen_at.items() if now - t > PASSIVE_REPLY_TTL]
        for k in expired:
            self._seqs.pop(k, None)
            self._seen_at.pop(k, None)


class DedupSet:
    """有界消息 ID 去重集合。

    官方说明（事件/group-at-message-create.md、c2c-message-create.md）：
    相同 msg_id 可能重复推送，需自行去重。
    """

    def __init__(self, maxsize=4096):
        self._items = OrderedDict()
        self._maxsize = maxsize

    def seen(self, key):
        """记录 key 并返回是否重复。"""
        if key in self._items:
            return True
        self._items[key] = True
        while len(self._items) > self._maxsize:
            self._items.popitem(last=False)
        return False


def split_message(content, max_length):
    """长消息分片：优先在换行边界切分，退化为硬切。"""
    content = content.strip()
    if len(content) <= max_length:
        return [content] if content else []
    chunks = []
    rest = content
    while len(rest) > max_length:
        cut = rest.rfind("\n", 0, max_length)
        if cut <= 0:
            cut = max_length
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return chunks


def random_send_delay():
    """多片发送之间的随机间隔（秒），对照 GUGUBot 发送层限速。"""
    return random.uniform(0.5, 1.5)


def at_user_tag(member_openid):
    """出站 @ 成员的官方内嵌格式，嵌入 Markdown 消息 content 发送。

    群聊场景 id=member_openid；文字子频道场景 id=user_openid。
    实测（2026-11-10 正式环境）：标签仅在 Markdown 消息（msg_type=2）中渲染；
    纯文本（msg_type=0）API 接受但客户端原样显示。
    """
    return f'<qqbot-at-user id="{member_openid}" />'


def at_everyone_tag():
    """出站 @全体成员（<qqbot-at-everyone />）。

    群聊文本、Markdown 消息均支持；机器人需为该群管理员，每群每天仅 1 次。
    """
    return "<qqbot-at-everyone />"
