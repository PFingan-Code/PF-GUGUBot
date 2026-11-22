"""open-qq-bot 连接器公共工具：错误码、限流、去重、分片、@ 标签、被动消息池。

行为与 QQ 开放平台官方文档对齐。
"""

import http.client
import json
import logging
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict, deque
from pathlib import Path

logger = logging.getLogger("gugubot.open_qq_bot")

# 被动消息规则（消息/group-messages-post.md）：有效时间 5 分钟，每个 msg_id 最多回复 5 次
PASSIVE_REPLY_MAX = 5
PASSIVE_REPLY_TTL = 10 * 60  # 稍大于 5 分钟窗口，便于清理过期记录

# 被动消息池：本地保守取 5 分钟 -10 秒，避免链路延迟导致发送时过期
PASSIVE_POOL_TTL = 5 * 60 - 10
PASSIVE_POOL_MAX_PER_GROUP = 10

# 订阅事件位掩码（协议常量，固定写在代码里，不开放配置）：
#   (1 << 25) GROUP_AND_C2C_EVENT   群聊 / 单聊消息
#   (1 << 24) GROUP_MEMBER_EVENT    群成员加入 / 移除
# 解析器只处理这两类事件：多加订阅位只会收到无法映射的事件，而网关对
# 无权限的 intents 会直接拒绝鉴权（websocket.md 错误码表），故不交给用户配置。
INTENTS = (1 << 25) | (1 << 24)

# 官方错误码（group-messages-post.md 错误码表 + 实测补充）
ERR_DUPLICATED = 40054005        # 消息被去重：相同 msg_id + msg_seq 重复发送
ERR_PASSIVE_EXPIRED = {304103, 40034005, 40034128}  # 被动回复过期/超次


class ApiError(RuntimeError):
    """带官方错误码的 API 调用异常，便于按错误码做重试/降级。

    官方响应里 ``err_code`` 与 ``code`` 含义不总是一致（如群成员列表接口
    ``code=11253`` 无权限、``err_code=40012010``），两个字段都保留供判断；
    ``status`` 为 HTTP 状态码（401/403 等凭据类错误供重试策略判断）。
    """

    def __init__(self, method, url, status, message, err_code=None, api_code=None):
        super().__init__(f"{method} {url} -> HTTP {status}: {message}")
        self.status = status
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
        HTTP 非 2xx 时抛出，携带 ``err_code`` / ``api_code``；
        网络层失败（超时/连接重置/URLError 等）抛出 ``status=0`` 的 ApiError，
        使发送层 seq 回退与网关重试策略与 HTTP 错误走同一路径。
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
    except (OSError, http.client.HTTPException) as e:
        # HTTPError 已是 URLError/OSError 子类并在上方处理；这里兜底其余网络层
        # 失败（URLError、超时、连接重置、IncompleteRead 等），统一为 status=0
        cost = int((time.monotonic() - start) * 1000)
        logger.warning("[HTTP ←] %s %s -> 网络错误 (%sms): %s", method, url, cost, e)
        raise ApiError(method, url, 0, str(e), None, None) from e


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

    def used(self, msg_id):
        """读取 msg_id 已分配（含未回退预留）的 msg_seq 数量，不分配、不清理。

        被动消息池用它计算剩余回复次数，避免另记一份额度造成双重计数。
        """
        with self._lock:
            return int(self._seqs.get(msg_id, 0))

    def release(self, msg_id, seq):
        """精确释放 msg_id 的指定 msg_seq 名额（发送失败回退用）。

        仅当 ``seq`` 是该 msg_id 当前栈顶（最后一次分配、且未被服务端
        接受）时生效，否则忽略——防止同一 msg_id 被并发/多系统同时回复
        时误放其他发送方预留的名额。约束：已发出的 seq 严格递增，服务端
        接受（或以 duplicate 拒绝，说明早已消费）的 seq 永不回退。
        """
        if seq is None:
            return
        with self._lock:
            if self._seqs.get(msg_id) == seq:
                self._seqs[msg_id] = seq - 1

    def _prune(self):
        now = time.time()
        expired = [k for k, t in self._seen_at.items() if now - t > PASSIVE_REPLY_TTL]
        for k in expired:
            self._seqs.pop(k, None)
            self._seen_at.pop(k, None)


class PassiveMsgPool:
    """群消息 msg_id 被动回复池。

    MC→QQ 广播没有同源事件 raw，原本只能走主动消息。本池记录最近收到的
    群消息 msg_id，出站时优先复用其中可用的 msg_id 以被动回复方式发送，
    减少主动配额消耗。

    - 每群最多 ``max_per_group`` 条，超过时淘汰最旧（左端）
    - 选**最旧且可用**的一条：过期（``expire_at <= now``）或已用完
      （``SeqManager.used(msg_id) >= PASSIVE_REPLY_MAX``）时移出池
    - ``pending`` 是进行中发送预留的次数，防止并发发送超额；发送结束由
      ``release()`` 释放（异常路径由调用方 try/finally 保证）
    - 只管理"用哪个 msg_id"，msg_seq 始终由 :class:`SeqManager` 分配
    """

    def __init__(self, seq_manager, ttl=PASSIVE_POOL_TTL,
                 max_per_group=PASSIVE_POOL_MAX_PER_GROUP):
        self._seq = seq_manager
        self.ttl = max(1, int(ttl))
        self.max_per_group = max(1, int(max_per_group))
        self._entries = {}  # group_openid -> deque([{msg_id, expire_at, pending}])
        self._lock = threading.Lock()

    def record(self, group, msg_id, now=None):
        """登记一条群消息 msg_id（幂等），记录其过期时刻。"""
        if not group or not msg_id:
            return
        now = time.time() if now is None else now
        with self._lock:
            entries = self._entries.setdefault(group, deque())
            self._prune(entries, now)
            if any(e["msg_id"] == msg_id for e in entries):
                return
            entries.append({
                "msg_id": msg_id,
                "expire_at": now + self.ttl,
                "pending": 0,
            })
            while len(entries) > self.max_per_group:
                entries.popleft()

    def acquire(self, group, needed, now=None):
        """取最旧的可用 msg_id，并为本次发送预留 ``needed`` 次回复额度。

        Returns
        -------
        str or None
            可用的 msg_id；池为空、全部过期/用尽或余额不足时返回 None。
        """
        needed = max(1, int(needed))
        now = time.time() if now is None else now
        with self._lock:
            entries = self._entries.get(group)
            if not entries:
                return None
            self._prune(entries, now)
            for entry in entries:
                remaining = PASSIVE_REPLY_MAX - self._seq.used(entry["msg_id"]) \
                    - entry["pending"]
                if remaining >= needed:
                    entry["pending"] += needed
                    return entry["msg_id"]
            return None

    def release(self, group, msg_id, needed):
        """释放预留；若该 msg_id 额度已用尽则移出池。"""
        needed = max(1, int(needed))
        with self._lock:
            for entry in list(self._entries.get(group) or []):
                if entry["msg_id"] == msg_id:
                    entry["pending"] = max(0, entry["pending"] - needed)
                    if self._seq.used(msg_id) >= PASSIVE_REPLY_MAX:
                        self._entries[group].remove(entry)
                    return

    def invalidate(self, group, msg_id):
        """被动回复过期/超次：立即把该 msg_id 移出池。"""
        with self._lock:
            for entry in list(self._entries.get(group) or []):
                if entry["msg_id"] == msg_id:
                    self._entries[group].remove(entry)
                    return

    def snapshot(self, group):
        """返回池内 msg_id 列表（最旧在前），供诊断与测试使用。"""
        with self._lock:
            return [e["msg_id"] for e in self._entries.get(group) or []]

    def _prune(self, entries, now):
        """移出过期或用尽的条目（原地操作，调用方持锁）。"""
        for entry in list(entries):
            expired = entry["expire_at"] <= now
            exhausted = self._seq.used(entry["msg_id"]) >= PASSIVE_REPLY_MAX
            if expired or exhausted:
                entries.remove(entry)


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


def _clamp_max_length(max_length) -> int:
    """分片长度防御：非整数回退默认值，<=0 修正为 1（避免死循环/TypeError）。"""
    try:
        max_length = int(max_length)
    except (TypeError, ValueError):
        max_length = 2000
    return max(1, max_length)


def split_message(content, max_length):
    """长消息分片：优先在换行边界切分，退化为硬切。

    ``max_length`` 非法（非整数 / <=0）时防御性修正，避免死循环。
    """
    max_length = _clamp_max_length(max_length)
    content = (content or "").strip()
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


# Markdown 受保护片段：@ 成员标签 / 图片语法 / URL，分片时不得切断
_MD_PROTECTED_RE = re.compile(
    r"<qqbot-at-[^>]*>|\[[^\]]*\]\([^)]*\)|https?://\S+", re.IGNORECASE
)


def split_markdown(content, max_length):
    """Markdown 长消息分片：优先换行边界，且不切断 @ 标签、图片与 URL。

    与 :func:`split_message` 的差异：@ 成员标签（``<qqbot-at-user .../>``）、
    图片语法（``![..](..)``）与 URL 被视为不可分割片段——切点落在其内部时
    向前回退；单个片段本身超过 ``max_length`` 时放弃保护硬切（保证终止）。
    """
    max_length = _clamp_max_length(max_length)
    content = (content or "").strip()
    if len(content) <= max_length:
        return [content] if content else []

    # 标记所有受保护字符区间
    protected = bytearray(len(content))
    for m in _MD_PROTECTED_RE.finditer(content):
        for i in range(m.start(), m.end()):
            protected[i] = 1

    chunks = []
    start, n = 0, len(content)
    while n - start > max_length:
        limit = start + max_length
        cut = content.rfind("\n", start + 1, limit + 1)
        if cut <= start:
            cut = limit
        # 切点把某个受保护片段一分为二（两侧都在片段内）时向前回退；
        # 紧贴片段边界的切点是干净的（片段完整落入某一侧）
        while cut > start and protected[cut - 1] and protected[cut]:
            cut -= 1
        if cut <= start:
            cut = limit  # 单个受保护片段超长：放弃保护，硬切防死循环
        chunk = content[start:cut].strip()
        if chunk:
            chunks.append(chunk)
        start = cut
        while start < n and content[start] in "\n\r \t":
            start += 1
    tail = content[start:].strip()
    if tail:
        chunks.append(tail)
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


class QuotaManager:
    """主动消息配额管理器（key 级 + Bot 全局两层滑动窗口）。

    官方限制（消息/group-messages-post.md）：单群 20 条/分钟、1000 条/天；
    Bot 维度 30~60 条/分钟。仅统计**主动消息**——被动回复（带 msg_id 锚点）
    不占分钟/天配额，由 :class:`SeqManager` 单独管理 5 次/5 分钟窗口。

    key 级状态持久化为 JSON（按 key 记录当日计数与分钟滑动窗口），
    重启不重置当日计数，避免配额被重启绕过；Bot 全局分钟窗口为进程内
    状态（短窗口，重启清零对平台侧限流无实质影响）。
    """

    def __init__(self, per_minute=20, per_day=1000, persist_path=None,
                 bot_per_minute=30):
        self.per_minute = max(1, int(per_minute))
        self.per_day = max(1, int(per_day))
        # Bot 维度全局限流（多群合计）；取 30 保守下限，防止多群同时广播
        # 触发平台级限流后消息仅剩 warning 日志
        self.bot_per_minute = max(1, int(bot_per_minute))
        self._persist_path = Path(persist_path) if persist_path else None
        self._lock = threading.Lock()
        self._state = {}  # key -> {"date": "YYYY-MM-DD", "day": int, "minute": [ts...]}
        self._global_minute = []  # Bot 维度分钟滑动窗口
        self._load()

    def _load(self):
        if not self._persist_path or not self._persist_path.is_file():
            return
        try:
            self._state = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._state = {}

    def _save(self):
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(self._state, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def allow(self, key):
        """记录一次主动消息并判断 key（群/用户 OpenID）当前是否允许发送。"""
        return self.allow_many(key, 1)

    def allow_many(self, key, count):
        """按实际 API 请求数（分片数）记账并判断是否允许发送。

        分片发送一次可能产生多个 API 请求，应按 ``count`` 计入两个窗口，
        否则多群广播时会低估用量、绕过平台全局限流。

        Returns
        -------
        bool
            任一窗口（key 级分钟/日、Bot 全局分钟）容量不足即整体拒绝，
            不做部分消费。
        """
        count = max(1, int(count))
        with self._lock:
            now = time.time()
            self._global_minute = [
                t for t in self._global_minute if now - t < 60
            ]
            if len(self._global_minute) + count > self.bot_per_minute:
                return False

            today = time.strftime("%Y-%m-%d")
            st = self._state.setdefault(key, {"date": today, "day": 0, "minute": []})
            if st.get("date") != today:
                st["date"] = today
                st["day"] = 0
            window = [t for t in st.get("minute", []) if now - t < 60]
            st["minute"] = window
            if st.get("day", 0) + count > self.per_day:
                self._save()
                return False
            if len(window) + count > self.per_minute:
                self._save()
                return False
            st["minute"] = window + [now] * count
            st["day"] = st.get("day", 0) + count
            self._global_minute.extend([now] * count)
            self._save()
            return True
