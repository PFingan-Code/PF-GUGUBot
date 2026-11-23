"""QQ 官方机器人 REST API 客户端（open-qq-bot 连接器）。

由 demo 的 ApiClient / TokenManager 拆分而来：所有参数改为构造注入，
不再读取 config.json。核心发送层覆盖群聊/单聊文本与 Markdown（自动分片、
被动回复 msg_seq 记账与去重重试）；富媒体、撤回、群管理查询与分片上传
为**实验性接口**（见对应 section 注释）。被动回复由
:class:`~.common.SeqManager` 统一管理。

线程模型：本类全部为**同步阻塞**实现（HTTP + 分片间 sleep），
connector 侧通过 ``asyncio.to_thread`` 包装调用，避免阻塞 MCDR 事件循环。
"""

import hashlib
import logging
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from gugubot.connector.open_qq_bot.common import (
    ERR_DUPLICATED,
    ERR_PASSIVE_EXPIRED,
    ApiError,
    SeqManager,
    http_json,
    logger,
    random_send_delay,
    split_markdown,
    split_message,
)

API_BASE = "https://api.bot.qq.com"
SANDBOX_API_BASE = "https://sandbox.api.bot.qq.com"


class PartialDelivery(RuntimeError):
    """分片消息部分送达：``sent`` 片已发出，剩余 ``remaining`` 片未发出。

    与「一片未发」（返回 ``None``，调用方可整体降级重发）不同，部分送达时
    整体重发会造成已送达内容重复，调用方只能告警，不得补发全文。
    """

    def __init__(self, sent: int, remaining: int):
        super().__init__(f"已发送 {sent} 片，剩余 {remaining} 片未发出")
        self.sent = sent
        self.remaining = remaining


class PassiveSeqExhausted(RuntimeError):
    """被动回复 msg_seq 名额耗尽，且服务端刚以 duplicate（40054005）拒绝。

    与 :class:`PartialDelivery` 同族的发送层异常：首片（i == 0）由 send_*
    捕获并返回 ``None``（调用方可整体降级为主动消息重发），后续片转为
    PartialDelivery。注意：此路径**不得回退基 seq**——duplicate 拒绝说明
    服务端已消费该 seq，回退会使下次分配撞上已用过的 seq，令该 msg_id
    的后续回复持续命中 40054005（本地配额账本也会与服务端错位）。
    """

    def __init__(self, msg_id):
        super().__init__(f"msg_id={msg_id} 被动回复名额耗尽（去重重试后仍被拒绝）")
        self.msg_id = msg_id


class _ReservedSeqCursor:
    """预留 msg_seq 块游标：按序产出块内未使用的 seq，耗尽返回 None。

    池化被动回复的**基 seq 与去重重试 seq 共享同一游标**：去重重试消费
    块内下一个预留位而不是跳到整块之上，后续分片因此不会拿到比已发
    retry 更小的预留值——一次发送实际用掉的 msg_seq 严格递增（Qodo PR
    评审「Pooled replies lose sequence order」）。
    """

    __slots__ = ("_seqs", "_pos")

    def __init__(self, seqs):
        self._seqs = list(seqs or [])
        self._pos = 0

    def next(self):
        """产出下一个未使用的预留 seq；块已耗尽时返回 None。"""
        if self._pos >= len(self._seqs):
            return None
        seq = self._seqs[self._pos]
        self._pos += 1
        return seq


class TokenManager:
    """access_token 管理：到期前 60 秒自动刷新（官方建议，旧 token 短暂有效）。

    注意：内部含网络调用，跨线程使用时请自行保证串行（或加锁）。
    """

    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if time.time() >= self._expires_at - 60:
                resp = http_json("POST", f"{API_BASE}/app/getAppAccessToken", body={
                    "appId": self.app_id, "clientSecret": self.app_secret,
                })
                if "access_token" not in resp:
                    raise RuntimeError(f"获取 access_token 失败: {resp}")
                self._token = resp["access_token"]
                self._expires_at = time.time() + int(resp["expires_in"])
                logger.info("access_token 已刷新，%ss 后过期", resp["expires_in"])
            return self._token


class ApiClient:
    """QQ 官方机器人 REST API 封装（全同步实现）。

    Parameters
    ----------
    tokens : TokenManager
        access_token 管理器。
    sandbox : bool
        是否使用沙箱环境。
    max_message_length : int
        文本消息分片长度上限（官方 40054007 超限报错）。
    """

    def __init__(self, tokens: TokenManager, sandbox: bool = False,
                 max_message_length: int = 2000):
        self.tokens = tokens
        self.api_base = SANDBOX_API_BASE if sandbox else API_BASE
        self.max_message_length = max_message_length
        self.seq = SeqManager()
        self.logger = logging.getLogger("gugubot.open_qq_bot")

    def _call(self, method, path, body=None, timeout=10):
        return http_json(method, self.api_base + path,
                         token=self.tokens.get(), body=body, timeout=timeout)

    def gateway_url(self):
        return self._call("GET", "/gateway")["url"]

    # ---- 发送层：msg_seq 管理 + 去重重试 ----

    def _release_seqs(self, msg_id, seqs):
        """倒序精确回退 msg_id 的一组 msg_seq（发送失败清理专用）。

        约束：seq 严格递增，仅**未被服务端接受**的预留可回退；经
        :meth:`~.common.SeqManager.release` 校验、仅当该 seq 仍是该
        msg_id 当前栈顶时生效，防止并发场景误放其他调用方预留的名额。
        """
        for seq in reversed(seqs or []):
            self.seq.release(msg_id, seq)

    def _post_group_message(self, group_openid, body, msg_id=None, retry_seq=None):
        """POST 单片群消息；命中 40054005 时换一个 msg_seq 重试（最多 2 次）。

        msg_seq 记账（所有权：本方法只负责**去重重试 seq** 的预留与清理，
        初始基 seq 由 send_* 管理）：seq 一旦发出即严格递增、永不回退——
        换 seq 重试成功时旧 seq **不释放**（服务端已消费，回退会令下次
        分配撞上已用过的 seq，后续回复持续命中 40054005）；重试仍失败时
        本次预留未被服务端接受，倒序精确回退防泄漏；名额耗尽抛
        :class:`PassiveSeqExhausted`（基 seq 不回退：duplicate 拒绝 =
        服务端已消费该 seq）。

        Parameters
        ----------
        retry_seq : callable, optional
            池化路径的去重重试 seq 来源（零参数调用，返回预留块内下一个
            未使用 seq，块耗尽返回 None）。提供时重试 seq 与基 seq 同源，
            已发 msg_seq 严格递增，且本方法不做任何回退——预留块归调用方
            所有；缺省时经 ``SeqManager.allocate`` 在整块之上分配（逐片
            分配路径），保持原有回退策略。
        """
        retry_seqs = []  # 去重重试额外分配的 msg_seq（栈，失败时倒序回退）
        pooled_block = retry_seq is not None
        while True:
            try:
                return self._call("POST", f"/v2/groups/{group_openid}/messages", body)
            except ApiError as e:
                if e.has_code(ERR_DUPLICATED) and msg_id and len(retry_seqs) < 2:
                    new_seq = retry_seq() if pooled_block else self.seq.allocate(msg_id)
                    if new_seq is None:
                        # 名额耗尽且服务端刚拒绝 duplicate：倒序回退本次预留
                        # 的 retry seq（池路径预留块归调用方，不在此回退）；
                        # 基 seq 不回退（见 PassiveSeqExhausted）
                        if not pooled_block:
                            self._release_seqs(msg_id, retry_seqs)
                        raise PassiveSeqExhausted(msg_id) from e
                    body["msg_seq"] = new_seq
                    retry_seqs.append(new_seq)
                    self.logger.warning("群消息被去重，换 msg_seq=%s 重试", new_seq)
                    continue
                if retry_seqs and not pooled_block:
                    # 换 seq 重试仍失败：本次预留未被服务端接受，倒序精确回退
                    # （池路径预留块的回退归调用方）
                    self._release_seqs(msg_id, retry_seqs)
                if e.has_code(*ERR_PASSIVE_EXPIRED):
                    self.logger.warning("被动回复窗口失效（msg_id 过期或超次）：%s", e)
                raise

    def _post_c2c_message(self, user_openid, body, msg_id=None):
        """POST 单片单聊消息；去重重试与 seq 记账同 :meth:`_post_group_message`。"""
        retry_seqs = []  # 去重重试额外分配的 msg_seq（栈，失败时倒序回退）
        while True:
            try:
                return self._call("POST", f"/v2/users/{user_openid}/messages", body)
            except ApiError as e:
                if e.has_code(ERR_DUPLICATED) and msg_id and len(retry_seqs) < 2:
                    new_seq = self.seq.allocate(msg_id)
                    if new_seq is None:
                        # 名额耗尽且服务端刚拒绝 duplicate：倒序回退本次预留
                        # 的 retry seq；基 seq 不回退（见 PassiveSeqExhausted）
                        self._release_seqs(msg_id, retry_seqs)
                        raise PassiveSeqExhausted(msg_id) from e
                    body["msg_seq"] = new_seq
                    retry_seqs.append(new_seq)
                    self.logger.warning("单聊消息被去重，换 msg_seq=%s 重试", new_seq)
                    continue
                if retry_seqs:
                    # 换 seq 重试仍失败：本次预留未被服务端接受，倒序精确回退
                    self._release_seqs(msg_id, retry_seqs)
                raise

    def _alloc_passive(self, body, msg_id):
        """为被动回复分配 msg_seq；返回分配的 seq，次数耗尽返回 None。

        返回的 seq 由调用方（send_*）持有：仅在非 duplicate 失败时精确
        回退，duplicate 拒绝（服务端已消费）后永不回退。
        """
        seq = self.seq.allocate(msg_id)
        if seq is None:
            return None
        body["msg_id"] = msg_id
        body["msg_seq"] = seq
        return seq

    def send_group_text(self, group_openid, content, msg_id=None,
                        event_id=None, reference=None, seqs=None):
        """发送群文本（自动分片，片间随机 0.5~1.5s 限速）。

        返回最后一个成功响应（含消息 id，可记录用于「撤回」）；
        一片未发出（被动回复次数耗尽，含去重重试后名额耗尽且服务端刚
        拒绝 duplicate 的情形）返回 ``None``，调用方可整体降级为主动消息
        重发；部分分片送达后中断则抛 :class:`PartialDelivery`
        （此时整体重发会重复已送达内容）。名额耗尽的 duplicate 路径
        不回退已被服务端消费的 seq（见 :class:`PassiveSeqExhausted`）。

        Parameters
        ----------
        reference : str, optional
            引用回复的 message_id（来自入站事件 message_scene.ext 的 msg_idx），
            仅随第一片发送。
        seqs : list[int], optional
            :meth:`SeqManager.reserve` 预分配的整块 msg_seq（被动消息池
            路径），经与去重重试共享的游标按序消费，替代逐片 allocate——
            预留即占用，并发发送不再重复计数或被抢占；去重重试消费块内
            下一个未使用 seq，已发 msg_seq 严格递增（不跳到整块之上）。
            此时失败回退由调用方负责，本方法不做基 seq 回退。
        """
        chunks = split_message(content, self.max_message_length)
        cursor = _ReservedSeqCursor(seqs) if seqs is not None else None
        last_resp = None
        for i, chunk in enumerate(chunks):
            body = {"msg_type": 0, "content": chunk}
            if reference and i == 0:
                body["message_reference"] = {"message_id": reference}
            base_seq = None  # 本片基 seq：由 send_* 管理，_post_* 只管重试 seq
            if msg_id:
                if cursor is not None:
                    # 预留块按序消费；后续名额可能已被前片去重重试占用，
                    # 由游标统一保证已发 msg_seq 严格递增
                    base_seq = cursor.next()
                    if base_seq is not None:
                        body["msg_id"] = msg_id
                        body["msg_seq"] = base_seq
                else:
                    base_seq = self._alloc_passive(body, msg_id)
                if base_seq is None:
                    self.logger.warning("分片 %s/%s 因被动回复次数耗尽未发送",
                                        i + 1, len(chunks))
                    if i > 0:
                        # 已有分片送达：整体降级重发会重复，显式抛错告警
                        # （显式因果链：allocate 耗尽或 seqs 预留超界，
                        # 供调用方区分「非过期导致的部分送达」）
                        raise PartialDelivery(i, len(chunks) - i) \
                            from PassiveSeqExhausted(msg_id)
                    return None  # 一片未发：调用方可整体降级为主动消息
            elif event_id:
                body["event_id"] = event_id
            try:
                last_resp = self._post_group_message(
                    group_openid, body, msg_id=msg_id,
                    retry_seq=cursor.next if cursor is not None else None,
                )
            except PassiveSeqExhausted as e:
                # 名额耗尽且服务端刚拒绝 duplicate：基 seq 已被服务端消费，
                # 不回退（回退会复发持续 40054005）；按「一片未发」返回 None
                self.logger.warning("分片 %s/%s 被动回复名额耗尽（去重后仍被拒绝）",
                                    i + 1, len(chunks))
                if i > 0:
                    raise PartialDelivery(i, len(chunks) - i) from e
                return None  # 一片未发：调用方可整体降级为主动消息
            except ApiError as e:
                # 非 duplicate 失败：本片基 seq 未被服务端接受，精确回退防泄漏
                # （seqs 预留块的回退归调用方，见 seqs 参数说明）
                if seqs is None:
                    self._release_seqs(msg_id, [base_seq])
                if i > 0:
                    raise PartialDelivery(i, len(chunks) - i) from e
                raise
            if i < len(chunks) - 1:
                time.sleep(random_send_delay())
        return last_resp

    def send_group_markdown(self, group_openid, content, msg_id=None, reference=None,
                            seqs=None):
        """msg_type=2 自定义 Markdown（群聊已开放全部机器人，无需申请模板）。

        @ 标签（<qqbot-at-user/> 等）仅在此通道渲染。超长内容自动分片，
        分片边界不切断 @ 标签 / 图片 / URL。返回值与部分失败语义同
        :meth:`send_group_text`；``seqs`` 参数语义亦同（被动消息池的
        预分配整块 msg_seq，经与去重重试共享的游标按序消费、失败回退
        归调用方，已发 msg_seq 严格递增）。
        可能的错误：304036/40034127=无 Markdown 权限；40034124=参数错误。
        """
        chunks = split_markdown(content, self.max_message_length)
        cursor = _ReservedSeqCursor(seqs) if seqs is not None else None
        last_resp = None
        for i, chunk in enumerate(chunks):
            body = {"msg_type": 2, "markdown": {"content": chunk}}
            if reference and i == 0:
                body["message_reference"] = {"message_id": reference}
            base_seq = None  # 本片基 seq：由 send_* 管理，_post_* 只管重试 seq
            if msg_id:
                if cursor is not None:
                    # 预留块按序消费；后续名额可能已被前片去重重试占用，
                    # 由游标统一保证已发 msg_seq 严格递增
                    base_seq = cursor.next()
                    if base_seq is not None:
                        body["msg_id"] = msg_id
                        body["msg_seq"] = base_seq
                else:
                    base_seq = self._alloc_passive(body, msg_id)
                if base_seq is None:
                    self.logger.warning("分片 %s/%s 因被动回复次数耗尽未发送",
                                        i + 1, len(chunks))
                    if i > 0:
                        # 已有分片送达：整体降级重发会重复，显式抛错告警
                        # （显式因果链：allocate 耗尽或 seqs 预留超界，
                        # 供调用方区分「非过期导致的部分送达」）
                        raise PartialDelivery(i, len(chunks) - i) \
                            from PassiveSeqExhausted(msg_id)
                    return None
            try:
                last_resp = self._post_group_message(
                    group_openid, body, msg_id=msg_id,
                    retry_seq=cursor.next if cursor is not None else None,
                )
            except PassiveSeqExhausted as e:
                # 名额耗尽且服务端刚拒绝 duplicate：基 seq 已被服务端消费，
                # 不回退（回退会复发持续 40054005）；按「一片未发」返回 None
                self.logger.warning("分片 %s/%s 被动回复名额耗尽（去重后仍被拒绝）",
                                    i + 1, len(chunks))
                if i > 0:
                    raise PartialDelivery(i, len(chunks) - i) from e
                return None
            except ApiError as e:
                # 非 duplicate 失败：本片基 seq 未被服务端接受，精确回退防泄漏
                # （seqs 预留块的回退归调用方，见 seqs 参数说明）
                if seqs is None:
                    self._release_seqs(msg_id, [base_seq])
                if i > 0:
                    raise PartialDelivery(i, len(chunks) - i) from e
                raise
            if i < len(chunks) - 1:
                time.sleep(random_send_delay())
        return last_resp

    # ---- 实验性接口 ----
    # 以下方法覆盖官方 REST 的富媒体/撤回/群管理/分片上传能力，尚未接入
    # 出站管线（如单聊图片仍以 [图片] 占位下发），也没有测试覆盖。
    # 接入前请先在沙箱验证行为；长期未接入应考虑删除，避免与文档漂移。

    def send_group_media(self, group_openid, file_type, url, msg_id=None):
        """URL 上传富媒体（file_type: 1=图 2=视频 3=语音 4=文件）并以 msg_type=7 发送。"""
        file_info = self.upload_group_media(group_openid, file_type, url)
        body = {"msg_type": 7, "media": {"file_info": file_info}}
        if msg_id and not self._alloc_passive(body, msg_id):
            return None
        return self._post_group_message(group_openid, body, msg_id=msg_id)

    def upload_group_media(self, group_openid, file_type, url):
        """URL 方式上传群聊富媒体，返回 file_info（单聊/群聊上传接口相互隔离）。"""
        resp = self._call("POST", f"/v2/groups/{group_openid}/files",
                          {"file_type": file_type, "url": url, "srv_send_msg": False})
        file_info = resp.get("file_info")
        if not file_info:
            raise RuntimeError(f"富媒体上传未返回 file_info: {resp}")
        return file_info

    def recall_group_message(self, group_openid, message_id):
        """撤回群消息：管理员可撤自己与成员消息，超 2 分钟报 40064004。"""
        return self._call("DELETE", f"/v2/groups/{group_openid}/messages/{message_id}")

    # ---- 单聊（单聊/群聊上传接口相互隔离）----

    def send_c2c_text(self, user_openid, content, msg_id=None):
        """发送单聊文本（自动分片，片间随机 0.5~1.5s 限速）。

        返回值与部分失败语义同 :meth:`send_group_text`；msg_seq 记账：
        seq 严格递增、服务端已消费的 seq 永不回退——基 seq 由本方法管理
        （仅非 duplicate 失败时精确回退）；去重重试 seq 由 ``_post_*``
        管理，重试成功不回退；去重后名额耗尽返回 ``None``（一片未发），
        基 seq 不回退（duplicate 拒绝 = 服务端已消费该 seq）。
        """
        chunks = split_message(content, self.max_message_length)
        last_resp = None
        for i, chunk in enumerate(chunks):
            body = {"msg_type": 0, "content": chunk}
            base_seq = None  # 本片基 seq：由 send_* 管理，_post_* 只管重试 seq
            if msg_id:
                base_seq = self._alloc_passive(body, msg_id)
                if base_seq is None:
                    self.logger.warning("分片 %s/%s 因被动回复次数耗尽未发送",
                                        i + 1, len(chunks))
                    if i > 0:
                        # 显式因果链：名额耗尽（非过期）导致的部分送达
                        raise PartialDelivery(i, len(chunks) - i) \
                            from PassiveSeqExhausted(msg_id)
                    return None
            try:
                last_resp = self._post_c2c_message(user_openid, body, msg_id=msg_id)
            except PassiveSeqExhausted as e:
                # 名额耗尽且服务端刚拒绝 duplicate：基 seq 已被服务端消费，
                # 不回退（回退会复发持续 40054005）；按「一片未发」返回 None
                self.logger.warning("分片 %s/%s 被动回复名额耗尽（去重后仍被拒绝）",
                                    i + 1, len(chunks))
                if i > 0:
                    raise PartialDelivery(i, len(chunks) - i) from e
                return None
            except ApiError as e:
                # 非 duplicate 失败：本片基 seq 未被服务端接受，精确回退防泄漏
                self._release_seqs(msg_id, [base_seq])
                if e.has_code(*ERR_PASSIVE_EXPIRED):
                    self.logger.warning("单聊被动回复窗口失效：%s", e)
                if i > 0:
                    raise PartialDelivery(i, len(chunks) - i) from e
                raise
            if i < len(chunks) - 1:
                time.sleep(random_send_delay())
        return last_resp

    def upload_c2c_media(self, user_openid, file_type, url):
        resp = self._call("POST", f"/v2/users/{user_openid}/files",
                          {"file_type": file_type, "url": url, "srv_send_msg": False})
        file_info = resp.get("file_info")
        if not file_info:
            raise RuntimeError(f"单聊富媒体上传未返回 file_info: {resp}")
        return file_info

    def recall_c2c_message(self, user_openid, message_id):
        """撤回机器人发给该用户的单聊消息；超 2 分钟报 40064004。"""
        return self._call("DELETE", f"/v2/users/{user_openid}/messages/{message_id}")

    # ---- 群管理查询（11253/40012010 = 白名单内邀接口无权限）----

    def get_group_info(self, group_openid):
        """群基本信息：名称/简介/分类/标签/成员人数。"""
        return self._call("GET", f"/v2/groups/{group_openid}/info")

    def get_group_bot_state(self, group_openid):
        """机器人群内状态：角色/入群时间/是否允许主动推送/消息接收设置。"""
        return self._call("GET", f"/v2/groups/{group_openid}/bot_state")

    def get_group_members(self, group_openid, max_pages=4):
        """分页拉取群成员列表（每页 ≤30 条，接口 60 QPM）。白名单外报 11253。"""
        members, cursor = [], ""
        for _ in range(max_pages):
            path = f"/v2/groups/{group_openid}/members"
            if cursor:
                path += f"?cursor={urllib.parse.quote(cursor)}"
            resp = self._call("GET", path)
            members.extend(resp.get("members") or [])
            cursor = resp.get("next_cursor") or ""
            if not cursor:
                break
        return members

    # ---- 本地文件分片上传（消息/rich-media.md、分片上传/*.md）----

    def send_group_file_chunked(self, group_openid, file_path, file_type=4, msg_id=None):
        """本地文件分片上传到群并发送：prepare → 逐片 PUT+part_finish → files 合并。"""
        path = Path(file_path)
        data = path.read_bytes()
        size = len(data)
        if size > 200 * 1024 * 1024:
            raise RuntimeError(f"文件超过 200MB 硬限制：{size}")
        prepare = self._call("POST", f"/v2/groups/{group_openid}/upload_prepare", {
            "file_type": file_type, "file_size": str(size), "file_name": path.name,
            "md5": hashlib.md5(data).hexdigest(),
            "sha1": hashlib.sha1(data).hexdigest(),
            "md5_10m": hashlib.md5(data[:10002432]).hexdigest(),
        })
        upload_id = prepare.get("upload_id")
        parts = prepare.get("parts") or []
        self.logger.info("分片上传准备完成：%s（%s 字节，%s 片）", path.name, size, len(parts))
        for part in parts:
            idx = part["index"]
            block = int(part.get("block_size") or prepare.get("block_size") or 0)
            chunk = data[idx * block:idx * block + block]
            # 直传 COS 预签名 URL：普通 PUT，不带机器人鉴权头
            req = urllib.request.Request(part["presigned_url"], method="PUT", data=chunk)
            with urllib.request.urlopen(req, timeout=60):
                pass
            self._call("POST", f"/v2/groups/{group_openid}/upload_part_finish", {
                "upload_id": upload_id, "part_index": idx,
                "block_size": str(len(chunk)), "md5": hashlib.md5(chunk).hexdigest(),
            })
            self.logger.info("分片 %s/%s 上传完成", idx + 1, len(parts))
        merged = self._call("POST", f"/v2/groups/{group_openid}/files", {
            "file_type": file_type, "srv_send_msg": False,
            "file_name": path.name, "upload_id": upload_id,
        })
        file_info = merged.get("file_info")
        if not file_info:
            raise RuntimeError(f"分片合并未返回 file_info: {merged}")
        body = {"msg_type": 7, "media": {"file_info": file_info}}
        if msg_id and not self._alloc_passive(body, msg_id):
            return None
        return self._post_group_message(group_openid, body, msg_id=msg_id)
