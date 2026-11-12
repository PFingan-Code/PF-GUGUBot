"""QQ 官方机器人 WebSocket 独立 Demo。

对照 GUGUBot（OneBot/NapCat 版）的功能清单（devDocs/proj/），在官方机器人 API 上演示：
- 网关接入：Identify / 心跳 / Resume / 断线重连（参照 起步指南/websocket.md）
- 被动回复管理：同一 msg_id 最多回复 5 次、5 分钟有效；msg_seq 自动分配与去重重试
- 关键词回复 / 违禁词撤回（需群主授权撤回能力，且机器人有群管理员身份）
- 富媒体收发：图片（Markdown 图文/转存）、视频/语音/文件（URL 上传）、本地文件分片上传
- 单聊：图片/文件发送、机器人回复撤回（2 分钟内）
- 群管理查询：群信息、机器人群内状态、群成员列表（白名单接口）+ 活跃统计对账
- 引用回复（message_reference）、群白名单与主动消息群分离配置
- 成员事件：入群欢迎 / 退群告别（主动消息，受频控限制）
- 长消息分片 + 多片间随机 0.5~1.5s 限速（对照 GUGUBot 发送层行为）

官方 API 文档见 devDocs/open-qq-bot/（起步指南、事件、消息、群管理）。
"""

import hashlib
import json
import logging
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from logging.handlers import RotatingFileHandler
from pathlib import Path

import websocket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qq-demo")

API_BASE = "https://api.bot.qq.com"
SANDBOX_API_BASE = "https://sandbox.api.bot.qq.com"
INTENTS = (1 << 25) | (1 << 24)  # GROUP_AND_C2C_EVENT | GROUP_MEMBER_EVENT
RESUME_CLOSE_CODES = {None, 1000, 1001, 1006, 4008, 4009}
FATAL_CLOSE_CODES = {4914, 4915}

# 被动消息规则（消息/group-messages-post.md）：有效时间 5 分钟，每个 msg_id 最多回复 5 次
PASSIVE_REPLY_MAX = 5
PASSIVE_REPLY_TTL = 10 * 60  # 稍大于 5 分钟窗口，便于清理过期记录

# 官方错误码（group-messages-post.md 错误码表）
ERR_DUPLICATED = 40054005        # 消息被去重：相同 msg_id + msg_seq 重复发送
ERR_PASSIVE_EXPIRED = {304103, 40034005, 40034128}  # 被动回复过期/超次


class ApiError(RuntimeError):
    """带官方错误码的 API 调用异常，便于按错误码做重试/降级。

    官方响应里 err_code 与 code 含义不总是一致（如成员列表接口
    code=11253 无权限、err_code=40012010），两个字段都保留供判断。
    """

    def __init__(self, method, url, status, message, err_code=None, api_code=None):
        super().__init__(f"{method} {url} -> HTTP {status}: {message}")
        self.err_code = err_code
        self.api_code = api_code


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


def http_json(method, url, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"QQBot {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    log.info("[HTTP →] %s %s body=%s", method, url, _safe_body(body))
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            cost = int((time.monotonic() - start) * 1000)
            log.info("[HTTP ←] %s %s %sms resp=%s", method, url, cost,
                     _safe_resp(raw.decode(errors="replace")))
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        cost = int((time.monotonic() - start) * 1000)
        log.warning("[HTTP ←] %s %s -> HTTP %s (%sms) resp=%s", method, url, e.code, cost,
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


class TokenManager:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            # 官方建议：到期前 60 秒内刷新，旧 token 在这 60 秒内仍有效
            if time.time() >= self._expires_at - 60:
                resp = http_json("POST", f"{API_BASE}/app/getAppAccessToken", body={
                    "appId": self.app_id, "clientSecret": self.app_secret,
                })
                if "access_token" not in resp:
                    raise RuntimeError(f"获取 access_token 失败: {resp}")
                self._token = resp["access_token"]
                self._expires_at = time.time() + int(resp["expires_in"])
                log.info("access_token 已刷新，%ss 后过期", resp["expires_in"])
            return self._token


class SeqManager:
    """被动回复 msg_seq 分配器（对照 GUGUBot 对 OneBot 回显的管理思路）。

    官方规则：相同 msg_id + msg_seq 会被去重拒绝（40054005）；同一 msg_id 最多回复 5 次。
    """

    def __init__(self):
        self._seqs = {}
        self._seen_at = {}
        self._lock = threading.Lock()

    def allocate(self, msg_id):
        with self._lock:
            seq = self._seqs.get(msg_id, 0) + 1
            if seq > PASSIVE_REPLY_MAX:
                log.warning("msg_id=%s 被动回复已达 %s 次上限，跳过", msg_id, PASSIVE_REPLY_MAX)
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

    官方说明（group-at-message-create.md）：相同 msg_id 可能重复推送，需自行去重。
    """

    def __init__(self, maxsize=4096):
        self._items = OrderedDict()
        self._maxsize = maxsize

    def seen(self, key):
        if key in self._items:
            return True
        self._items[key] = True
        while len(self._items) > self._maxsize:
            self._items.popitem(last=False)
        return False


def split_message(content, max_length):
    """长消息分片：优先在换行边界切分，退化为硬切（对照 GUGUBot 发送层 max_message_length）。"""
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


def at_user_tag(member_openid):
    """出站 @ 成员的官方内嵌格式，嵌入 content 发送。

    群聊场景 id=member_openid；文字子频道场景 id=user_openid。
    实测（2026-11-10 正式环境）：标签仅在 Markdown 消息（msg_type=2）中渲染为
    可点击标签；纯文本（msg_type=0）API 接受但客户端原样显示，旧 <@user_id>
    格式在纯文本下同样不渲染。请经 send_group_markdown 发送。
    """
    return f'<qqbot-at-user id="{member_openid}" />'


def at_everyone_tag():
    """出站 @全体成员（<qqbot-at-everyone />）。

    群聊场景文本消息、Markdown 消息均支持；机器人需为该群管理员，
    且每个群每天仅可发送 1 次（官方文档限制，2026-11-11）。
    """
    return "<qqbot-at-everyone />"


class ApiClient:
    def __init__(self, tokens: TokenManager, api_base: str = API_BASE, max_message_length: int = 2000):
        self.tokens = tokens
        self.api_base = api_base
        self.max_message_length = max_message_length
        self.seq = SeqManager()

    def _call(self, method, path, body=None):
        return http_json(method, self.api_base + path, token=self.tokens.get(), body=body)

    def gateway_url(self):
        return self._call("GET", "/gateway")["url"]

    # ---- 发送层：分片 + msg_seq 管理 + 去重重试（对照 GUGUBot QQWebSocketConnector.send_message）----

    def _post_group_message(self, group_openid, body, msg_id=None):
        """POST 单片群消息；命中 40054005 时换一个 msg_seq 重试（最多 2 次）。"""
        attempts = 0
        while True:
            attempts += 1
            try:
                return self._call("POST", f"/v2/groups/{group_openid}/messages", body)
            except ApiError as e:
                if e.err_code == ERR_DUPLICATED and msg_id and attempts <= 2:
                    new_seq = self.seq.allocate(msg_id)
                    if new_seq is None:
                        raise
                    body["msg_seq"] = new_seq
                    log.warning("群消息被去重，换 msg_seq=%s 重试", new_seq)
                    continue
                if e.err_code in ERR_PASSIVE_EXPIRED:
                    log.warning("被动回复窗口失效（msg_id 过期或超次），如需继续请改用主动消息：%s", e)
                raise

    def send_group_text(self, group_openid, content, msg_id=None, event_id=None, reference=None):
        """发送群文本（自动分片限速），返回最后一个成功响应（含消息 id，供撤回/引用）。"""
        chunks = split_message(content, self.max_message_length)
        last_resp = None
        for i, chunk in enumerate(chunks):
            body = {"msg_type": 0, "content": chunk}
            if reference and i == 0:
                # 引用回复：msg_idx 来自入站事件 message_scene.ext（仅第一片携带）
                body["message_reference"] = {"message_id": reference}
            if msg_id:
                seq = self.seq.allocate(msg_id)
                if seq is None:
                    log.warning("分片 %s/%s 因被动回复次数耗尽未发送", i + 1, len(chunks))
                    break
                body["msg_id"] = msg_id
                body["msg_seq"] = seq
            elif event_id:
                body["event_id"] = event_id
            try:
                last_resp = self._post_group_message(group_openid, body, msg_id=msg_id)
            except ApiError:
                if msg_id:
                    self.seq.release(msg_id)
                raise
            # 多片之间随机 0.5~1.5s，避免触发平台频率限制（对照 GUGUBot 发送层限速）
            if i < len(chunks) - 1:
                time.sleep(random.uniform(0.5, 1.5))
        return last_resp

    def send_group_image(self, group_openid, file_info, msg_id=None):
        body = {"msg_type": 7, "media": {"file_info": file_info}}
        if msg_id:
            seq = self.seq.allocate(msg_id)
            if seq is None:
                return None
            body["msg_id"] = msg_id
            body["msg_seq"] = seq
        return self._post_group_message(group_openid, body, msg_id=msg_id)

    def send_group_markdown(self, group_openid, content, msg_id=None, reference=None):
        """msg_type=2 自定义 Markdown（markdown.md：群聊已开放全部机器人，无需申请模板）。

        注意：传 markdown 后 content 字段必须为空（group-messages-post.md）。
        可能的错误：304036/40034127=无 Markdown 权限；40034124=参数错误。
        """
        body = {"msg_type": 2, "markdown": {"content": content}}
        if reference:
            body["message_reference"] = {"message_id": reference}
        if msg_id:
            seq = self.seq.allocate(msg_id)
            if seq is None:
                return None
            body["msg_id"] = msg_id
            body["msg_seq"] = seq
        return self._post_group_message(group_openid, body, msg_id=msg_id)

    def upload_group_image(self, group_openid, url):
        # srv_send_msg=False：只上传拿 file_info，不直接发出（消息/rich-media.md）
        return self.upload_group_media(group_openid, 1, url)

    def upload_group_media(self, group_openid, file_type, url):
        """URL 方式上传群聊富媒体（消息/rich-media.md，file_type: 1=图 2=视频 3=语音 4=文件）。

        单聊/群聊上传接口相互隔离（rich-media.md），互不通用。
        """
        resp = self._call("POST", f"/v2/groups/{group_openid}/files",
                          {"file_type": file_type, "url": url, "srv_send_msg": False})
        file_info = resp.get("file_info")
        if not file_info:
            raise RuntimeError(f"富媒体上传未返回 file_info: {resp}")
        return file_info

    def send_group_media(self, group_openid, file_type, url, msg_id=None):
        """上传 + msg_type=7 发送一条群富媒体消息。"""
        file_info = self.upload_group_media(group_openid, file_type, url)
        return self.send_group_image(group_openid, file_info, msg_id=msg_id)

    def recall_group_message(self, group_openid, message_id):
        # 撤回要求：机器人有群管理员身份 + 消息发送未超 2 分钟 + 群主授权「撤回成员消息」
        return self._call("DELETE", f"/v2/groups/{group_openid}/messages/{message_id}")

    # ---- 群管理查询（群管理/*.md；11253=应用无接口访问权限，成员类接口为白名单内邀）----

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

    # ---- 单聊富媒体与撤回（消息/user-files-post.md、user-messages-delete.md）----

    def upload_c2c_media(self, user_openid, file_type, url):
        resp = self._call("POST", f"/v2/users/{user_openid}/files",
                          {"file_type": file_type, "url": url, "srv_send_msg": False})
        file_info = resp.get("file_info")
        if not file_info:
            raise RuntimeError(f"单聊富媒体上传未返回 file_info: {resp}")
        return file_info

    def send_c2c_media(self, user_openid, file_info, msg_id=None):
        body = {"msg_type": 7, "media": {"file_info": file_info}}
        if msg_id:
            seq = self.seq.allocate(msg_id)
            if seq is None:
                return None
            body["msg_id"] = msg_id
            body["msg_seq"] = seq
        return self._call("POST", f"/v2/users/{user_openid}/messages", body)

    def recall_c2c_message(self, user_openid, message_id):
        # 仅能撤回机器人发给该用户的消息；发送超 2 分钟报 40064004
        return self._call("DELETE", f"/v2/users/{user_openid}/messages/{message_id}")

    # ---- 本地文件分片上传（消息/rich-media.md、分片上传/*.md）----

    def send_group_file_chunked(self, group_openid, file_path, file_type=4, msg_id=None):
        """本地文件分片上传到群并发送：prepare → 逐片 PUT+part_finish → files 合并 → msg_type=7。"""
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
        log.info("分片上传准备完成：%s（%s 字节，%s 片）", path.name, size, len(parts))
        for part in parts:
            idx = part["index"]
            block = int(part.get("block_size") or prepare.get("block_size") or 0)
            chunk = data[idx * block:idx * block + block]
            # 直传 COS 预签名 URL：普通 PUT，不带机器人鉴权头（http_json 仅用于官方 API）
            req = urllib.request.Request(part["presigned_url"], method="PUT", data=chunk)
            with urllib.request.urlopen(req, timeout=60):
                pass
            self._call("POST", f"/v2/groups/{group_openid}/upload_part_finish", {
                "upload_id": upload_id, "part_index": idx,
                "block_size": str(len(chunk)), "md5": hashlib.md5(chunk).hexdigest(),
            })
            log.info("分片 %s/%s 上传完成", idx + 1, len(parts))
        merged = self._call("POST", f"/v2/groups/{group_openid}/files", {
            "file_type": file_type, "srv_send_msg": False,
            "file_name": path.name, "upload_id": upload_id,
        })
        file_info = merged.get("file_info")
        if not file_info:
            raise RuntimeError(f"分片合并未返回 file_info: {merged}")
        return self.send_group_image(group_openid, file_info, msg_id=msg_id)

    def send_c2c_text(self, user_openid, content, msg_id=None):
        body = {"msg_type": 0, "content": content}
        if msg_id:
            seq = self.seq.allocate(msg_id)
            if seq is None:
                return None
            body["msg_id"] = msg_id
            body["msg_seq"] = seq
        attempts = 0
        while True:
            attempts += 1
            try:
                return self._call("POST", f"/v2/users/{user_openid}/messages", body)
            except ApiError as e:
                if e.err_code == ERR_DUPLICATED and msg_id and attempts <= 2:
                    new_seq = self.seq.allocate(msg_id)
                    if new_seq is None:
                        raise
                    body["msg_seq"] = new_seq
                    log.warning("单聊消息被去重，换 msg_seq=%s 重试", new_seq)
                    continue
                if e.err_code in ERR_PASSIVE_EXPIRED:
                    log.warning("单聊被动回复窗口失效：%s", e)
                raise


class Gateway:
    def __init__(self, api: ApiClient, tokens: TokenManager, on_event, on_ready=None):
        self.api = api
        self.tokens = tokens
        self.on_event = on_event
        self.on_ready = on_ready
        self.session_id = None
        self.last_seq = None
        self.ws = None
        self._hello = threading.Event()
        self._ready = threading.Event()
        self._ack = threading.Event()
        self._heartbeat_interval = 45.0
        self._stop = False
        self._fatal = False
        self._reidentify = False
        self._backoff = 1

    def _send(self, payload):
        if self.ws:
            self.ws.send(json.dumps(payload))

    def _on_message(self, ws, raw):
        payload = json.loads(raw)
        op = payload.get("op")
        level = logging.DEBUG if op in (1, 11) else logging.INFO
        log.log(level, "收到网关消息：op=%s t=%s s=%s", op, payload.get("t"), payload.get("s"))
        if op == 10:
            self._heartbeat_interval = payload["d"]["heartbeat_interval"] / 1000
            self._hello.set()
            if self.session_id and self.last_seq is not None:
                log.info("发送 Resume（session=%s, seq=%s）", self.session_id, self.last_seq)
                self._send({"op": 6, "d": {
                    "token": f"QQBot {self.tokens.get()}",
                    "session_id": self.session_id, "seq": self.last_seq,
                }})
            else:
                log.info("发送 Identify（intents=%s）", INTENTS)
                self._send({"op": 2, "d": {
                    "token": f"QQBot {self.tokens.get()}", "intents": INTENTS,
                    "shard": [0, 1],
                    "properties": {"$os": "linux", "$browser": "qq-demo", "$device": "qq-demo"},
                }})
        elif op == 0:
            self.last_seq = payload.get("s", self.last_seq)
            t = payload.get("t")
            if t == "READY":
                self.session_id = payload["d"]["session_id"]
                self._backoff = 1
                self._ready.set()
                log.info("鉴权成功：%s", payload["d"]["user"]["username"])
                if self.on_ready:
                    self.on_ready(payload["d"]["user"])
            elif t == "RESUMED":
                self._backoff = 1
                self._ready.set()
                log.info("Session 恢复成功，遗漏事件补发完毕")
            else:
                try:
                    self.on_event(t, payload.get("d") or {}, payload.get("id"))
                except Exception:
                    log.exception("处理事件 %s 失败", t)
        elif op == 11:
            self._ack.set()
        elif op == 7:
            log.info("服务端要求重连（op 7）")
            ws.close()
        elif op == 9:
            log.warning("Invalid Session（op 9），将重新 Identify")
            self.session_id = None
            self.last_seq = None
            ws.close()

    def _on_close(self, ws, code, msg):
        log.info("连接关闭：code=%s msg=%s", code, msg)
        if code in FATAL_CLOSE_CODES:
            self._fatal = True
        elif code not in RESUME_CLOSE_CODES:
            self._reidentify = True

    def _heartbeat_loop(self, ws):
        # 必须等鉴权完成（READY/RESUMED）再发心跳，网关不回未鉴权连接的 ACK
        if not self._hello.wait(timeout=10) or not self._ready.wait(timeout=15):
            return
        while ws.keep_running and not self._stop:
            self._ack.clear()
            log.debug("发送心跳 op=1 seq=%s", self.last_seq)
            ws.send(json.dumps({"op": 1, "d": self.last_seq}))
            if not self._ack.wait(timeout=10):
                log.warning("心跳 ACK 超时，断开重连")
                ws.close()
                return
            time.sleep(self._heartbeat_interval)

    def run(self):
        while not self._stop:
            self._hello.clear()
            self._ready.clear()
            self._reidentify = False
            url = self.api.gateway_url()
            log.info("连接网关：%s", url)
            self.ws = websocket.WebSocketApp(
                url, on_message=self._on_message, on_close=self._on_close,
                on_error=lambda ws, e: log.error("WS 错误：%s", e),
            )
            threading.Thread(target=self._heartbeat_loop, args=(self.ws,), daemon=True).start()
            self.ws.run_forever()
            if self._fatal:
                log.error("机器人已下架/封禁，退出")
                return
            if self._reidentify:
                self.session_id = None
                self.last_seq = None
            log.info("%ss 后重连", self._backoff)
            time.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, 60)


HELP_TEXT = (
    "可用演示功能：\n"
    "· 帮助 —— 查看本说明\n"
    "· 图片 / 视频 / 语音 / 文件 —— 发送对应演示富媒体（需配置 demo_*_url）\n"
    "· 直接发图片 —— 回显并附文件名说明\n"
    "· 成员列表 —— 群成员清点 + 活跃统计（接口需白名单）\n"
    "· 群信息 —— 群名称/人数/标签\n"
    "· 机器人状态 —— 群内角色/主动推送/消息接收设置\n"
    "· 公告 内容 —— 群主/管理员 @全体发公告（每群每天限 1 次）\n"
    "· 撤回 —— 撤回机器人最近一条群消息（限 2 分钟内）\n"
    "· 发本地文件 <文件名> —— 管理员分片上传 demo 目录内文件\n"
    "· /groupId /userId @某人 /botId —— 获取群/用户/机器人 ID\n"
    "· 关键词回复 / 违禁词撤回由配置驱动（未命中的消息不做回复）\n"
    "单聊支持：图片 / 撤回（撤回机器人最近一条回复，限 2 分钟内）"
)


class DemoHandlers:
    """对照 GUGUBot 功能清单：关键词回复、违禁词撤回、图片收发、成员事件、群命令。"""

    def __init__(self, api: ApiClient, config: dict):
        self.api = api
        self.keywords = config.get("keywords", {})
        self.ban_words = config.get("ban_words", [])
        self.image_echo = config.get("image_echo_enable", True)
        self.member_notice = config.get("member_notice_enable", True)
        self.welcome_text = config.get("welcome_text", "欢迎入群！发送「帮助」查看机器人功能。")
        self.farewell_text = config.get("farewell_text", "有成员离开了群聊。")
        self.demo_image_url = config.get("demo_image_url", "")
        self.demo_video_url = config.get("demo_video_url", "")
        self.demo_voice_url = config.get("demo_voice_url", "")
        self.demo_file_url = config.get("demo_file_url", "")
        # 群白名单与收发分离（对照 GUGUBot permissions：group_ids 监听群 ≠ forward_group_ids 发送群）
        self.listen_groups = [g for g in config.get("listen_groups", []) if g]   # 空=响应所有群
        self.send_groups = [g for g in config.get("send_groups", []) if g]      # 空=主动消息回事件来源群
        self.quote_reply = config.get("quote_reply_enable", True)               # 群文本回复带引用
        self._seen = DedupSet()
        self._last_c2c_reply = {}  # user_openid -> 机器人最后一条单聊回复的消息 ID（供「撤回」）
        self._last_group_reply = {}  # group_openid -> 机器人最后一条群消息 ID（供群聊「撤回」）
        self._activity_path = Path(__file__).with_name("activity.json")
        self._activity = self._load_activity()
        self._activity_last_flush = 0.0  # 上次落盘时间（monotonic），写盘节流用
        self.bot_id = None        # READY 事件的数字 id
        self.bot_username = None  # 用于剔除命令消息里的 "@机器人" 前缀
        self.bot_openid = None    # 从 mentions 学到的机器人 openid（消息标记里用的是它）

    # ---- 活跃度跟踪（GUGUBot 群成员对账的 demo 版：按群/成员计数发言）----

    def _load_activity(self):
        try:
            return json.loads(self._activity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _track_activity(self, group, member_openid, username):
        if not group or not member_openid:
            return
        entry = self._activity.setdefault(group, {}).setdefault(
            member_openid, {"count": 0, "username": ""})
        entry["count"] = entry.get("count", 0) + 1
        if username:
            entry["username"] = username
        # 网关线程内避免每条消息同步写盘（高负载时阻塞心跳 ACK 触发误重连）：
        # 计数在内存累加，最多每 30 秒落盘一次（demo 场景可接受少量丢失）
        now = time.monotonic()
        if now - self._activity_last_flush < 30:
            return
        self._activity_last_flush = now
        try:
            self._activity_path.write_text(
                json.dumps(self._activity, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _parse_msg_idx(d):
        """从入站事件 message_scene.ext 提取 msg_idx，用作出站引用回复的 message_id。"""
        for item in (d.get("message_scene") or {}).get("ext") or []:
            if isinstance(item, str) and item.startswith("msg_idx="):
                return item[len("msg_idx="):]
        return None

    def on_ready(self, user):
        self.bot_id = user.get("id")
        self.bot_username = user.get("username")
        log.info("机器人身份：id=%s username=%s", self.bot_id, self.bot_username)

    def __call__(self, t, d, event_id):
        if t in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"):
            self._group_message(t, d)
        elif t == "C2C_MESSAGE_CREATE":
            self._c2c_message(d)
        elif t == "GROUP_MEMBER_ADD":
            self._member_join(d)
        elif t == "GROUP_MEMBER_REMOVE":
            self._member_leave(d)
        elif t == "GROUP_ADD_ROBOT":
            self._robot_added(d, event_id)
        else:
            # GROUP_DEL_ROBOT / FRIEND_ADD / FRIEND_DEL 等：记录事件即可
            log.info("[事件] %s: %s", t, json.dumps(d, ensure_ascii=False))

    # ---- 群消息（对照 GUGUBot：违禁词 → 关键词 → 命令 的系统消费顺序）----

    def _group_message(self, t, d):
        msg_id = d.get("id")
        if not msg_id:
            return
        if d.get("author", {}).get("bot"):
            return  # 跳过机器人自己的消息，防止消息回环
        # 完全空的消息（无文本无附件）不占用去重名额：官方可能对同一 msg_id
        # 先推空消息、再推完整内容，提前消耗去重会吞掉真实消息
        if not (d.get("content") or "").strip() and not d.get("attachments"):
            log.debug("[%s] 忽略空消息（不占用去重）", t)
            return
        if self._seen.seen(msg_id):
            return
        group = d.get("group_openid", "")
        author = d.get("author", {})
        # 群白名单（对照 GUGUBot permissions.group_ids）：非空时仅响应白名单内的群
        if self.listen_groups and group not in self.listen_groups:
            log.info("群 %s 不在 listen_groups 白名单，忽略消息", group)
            return
        raw = d.get("content", "")
        # 「被@」识别：仅 @ 模式下 AT 事件即被@；全量模式下优先看 mentions 的 bot 标志
        # （实测消息里的 @ 标记 id 与 READY 的数字 id 不一致，需以 mentions 为准），
        # 再兜底比对 READY id / 学到的 bot openid 两种标记形态。
        mentions = d.get("mentions") or []
        bot_mention = next((u for u in mentions if u.get("bot")), None)
        if bot_mention and not self.bot_openid:
            self.bot_openid = bot_mention.get("member_openid") or bot_mention.get("id")
            log.info("记录机器人 openid=%s（来自 mentions）", self.bot_openid)
        at_me = (
            t == "GROUP_AT_MESSAGE_CREATE"
            or bot_mention is not None
            or any(self.bot_id and (u.get("member_openid") or u.get("id")) == self.bot_id for u in mentions)
            or (self.bot_id and f"<@{self.bot_id}>" in raw)
            or (self.bot_openid and f"<@{self.bot_openid}>" in raw)
        )
        content = self._render_content(d)
        # 被 @ 时统一剔除渲染出的 "@机器人名" 前缀（全量模式标记替换而来），
        # 保证命令/关键词拿到的都是净文本（对照 GUGUBot：at 段先解析再分发）
        if at_me and self.bot_username and content.startswith(f"@{self.bot_username}"):
            content = content[len(self.bot_username) + 1:].strip() or content
        self._track_activity(group, author.get("member_openid"), author.get("username"))
        reference = self._parse_msg_idx(d) if self.quote_reply else None
        log.info("[%s] %s(%s, %s) at_me=%s raw=%r", t, author.get("username"),
                 author.get("member_openid"), author.get("member_role"), at_me, raw)

        if self._ban_word_check(group, msg_id, author, content, reference):
            return
        if self._image_message(group, msg_id, d):
            return
        if self._command(group, msg_id, author, content, reference, mentions):
            return
        if self._keyword_reply(group, msg_id, content, reference):
            return
        # 未命中任何规则的普通消息不做回复（连接验证阶段的调试 echo 已移除）

    @staticmethod
    def _render_content(d):
        """把 content 里的 @ 标记替换为可读文本（对照 GUGUBot at 段渲染）。

        入站两种形态都处理：<@member_openid>（全量模式文本标记）、
        <qqbot-at-user id="..." />（官方内嵌标签，双向通用）。
        """
        content = d.get("content", "").strip()
        mentions = {}
        for user in d.get("mentions") or []:
            openid = user.get("member_openid") or user.get("id") or ""
            if openid:
                mentions[openid] = user.get("username", openid)

        def repl(match):
            return f"@{mentions.get(match.group(1), match.group(1))}"

        content = content.replace("<@all>", "@全体成员")
        content = re.sub(r"<@([^>]+)>", repl, content)
        content = re.sub(r'<qqbot-at-user\s+id="([^"]+)"\s*/?>', repl, content)
        return content

    def _ban_word_check(self, group, msg_id, author, content, reference=None):
        hit = next((w for w in self.ban_words if w and w in content), None)
        if not hit:
            return False
        # 管理员/群主豁免（对照 GUGUBot 违禁词的权限模型）：
        # 返回 False 表示「未处理」，让消息继续走命令/关键词流程——
        # 若返回 True 会被调用方当作「已处理并终止」，吞掉含违禁词的管理命令
        if author.get("member_role") in ("admin", "owner"):
            log.info("违禁词命中但发送者为 %s，豁免", author.get("member_role"))
            return False
        try:
            self.api.recall_group_message(group, msg_id)
            log.info("已撤回违禁消息（命中：%s）", hit)
        except ApiError as e:
            log.warning("撤回失败（需机器人有管理员身份、消息未超 2 分钟、群主已授权撤回能力）：%s", e)
        self._reply_text(group, msg_id, f"消息包含违禁词「{hit}」，请勿发送。", reference=reference)
        return True

    def _image_message(self, group, msg_id, d):
        """收到图片：Markdown 图文回显（附文件名说明）；失败回退为纯图片转存。"""
        images = [a for a in d.get("attachments") or []
                  if str(a.get("content_type", "")).startswith("image")]
        if not images:
            return False
        if not self.image_echo:
            return True
        for att in images:
            url = att.get("url")
            if not url:
                continue
            filename = att.get("filename", "图片")
            try:
                # 图片+文字说明走 Markdown 图文（msg_type=7 不支持 caption，见 README）
                caption = f"收到图片：{filename}\n\n![图片]({url})"
                self.api.send_group_markdown(group, caption, msg_id=msg_id)
                log.info("图片回显完成（Markdown 图文）：%s", filename)
            except ApiError as e:
                log.warning("Markdown 图文回显失败，回退纯图片转存：%s", e)
                try:
                    file_info = self.api.upload_group_image(group, url)
                    self.api.send_group_image(group, file_info, msg_id=msg_id)
                    log.info("图片回显完成（纯图片）：%s", filename)
                except ApiError as e2:
                    log.warning("图片回显失败：%s", e2)
        return True

    def _reply_text(self, group, msg_id, content, reference=None):
        """群纯文本回复的统一入口（带引用回复，异常只记日志）。"""
        try:
            resp = self.api.send_group_text(group, content, msg_id=msg_id, reference=reference)
            self._remember_group_reply(group, resp)
        except ApiError as e:
            log.warning("群文本发送失败：%s", e)

    def _remember_group_reply(self, group, resp):
        """记录机器人发出的群消息 ID，供群聊「撤回」命令使用（发送响应含 id）。"""
        if isinstance(resp, dict) and resp.get("id"):
            self._last_group_reply[group] = resp["id"]

    def _command(self, group, msg_id, author, content, reference=None, mentions=None):
        text = content.strip()
        if text == "帮助":
            self._reply_text(group, msg_id, HELP_TEXT, reference=reference)
            return True
        if text == "图片":
            return self._send_demo_media(group, msg_id, 1, self.demo_image_url, "图片", "demo_image_url")
        if text == "视频":
            return self._send_demo_media(group, msg_id, 2, self.demo_video_url, "视频", "demo_video_url")
        if text == "语音":
            return self._send_demo_media(group, msg_id, 3, self.demo_voice_url, "语音", "demo_voice_url")
        if text == "文件":
            return self._send_demo_media(group, msg_id, 4, self.demo_file_url, "文件", "demo_file_url")
        if text == "成员列表":
            self._cmd_members(group, msg_id, reference)
            return True
        if text == "群信息":
            self._cmd_group_info(group, msg_id, reference)
            return True
        if text == "机器人状态":
            self._cmd_bot_state(group, msg_id, reference)
            return True
        if text == "/groupId" or text.startswith("/groupId "):
            self._reply_text(group, msg_id, f"群 OpenID：\n{group}", reference=reference)
            return True
        if text == "/botId":
            oid = self.bot_openid or self.bot_id or "?"
            self._reply_text(group, msg_id,
                             f"机器人 OpenID：\n{oid}\n（READY 数字 ID：{self.bot_id or '?'}）",
                             reference=reference)
            return True
        if text == "/userId" or text.startswith("/userId "):
            # 查询目标：mention 的昵称出现在命令参数（rest）里才算目标。
            # 这样「@机器人」作为调用前缀（其昵称不在参数中）自动跳过，
            # 显式 @机器人 查询、@其他成员（无论 mentions 的 bot 标志如何）都能命中。
            rest = text[len("/userId"):].strip()
            log.debug("/userId mentions=%s rest=%r", mentions or [], rest)
            target = None
            for u in mentions or []:
                oid = u.get("member_openid") or u.get("id")
                if not oid or oid == author.get("member_openid"):
                    continue  # 跳过发送者自己
                if u.get("bot") and f"@{u.get('username')}" not in rest:
                    continue  # 仅作为调用前缀的机器人不算查询目标
                target = u
                break
            unresolved = re.search(r"@([0-9A-Fa-f]{32})", rest)
            if target:
                label = "机器人" if target.get("bot") else "用户"
                oid = target.get("member_openid") or target.get("id") or "?"
                self._reply_text(group, msg_id,
                                 f"被 @ {label}「{target.get('username', '?')}」的 OpenID：\n{oid}",
                                 reference=reference)
            elif unresolved and unresolved.group(1) not in (self.bot_openid, self.bot_id):
                self._reply_text(group, msg_id,
                                 f"警告：该 OpenID 未在 mentions 中匹配到（可能已退群或 QQ 未解析）。\n"
                                 f"OpenID：{unresolved.group(1)}",
                                 reference=reference)
            else:
                # 实测（2026-11-11）：同一用户群聊 member_openid 与单聊 user_openid 一致，
                # 故 /userId 群聊、单聊通用
                self._reply_text(group, msg_id,
                                 f"你的用户 OpenID：\n{author.get('member_openid') or author.get('id', '?')}",
                                 reference=reference)
            return True
        if text.startswith("公告"):
            return self._announce(group, msg_id, author, text[len("公告"):].strip())
        if text == "撤回":
            return self._recall_group_last(group, msg_id, reference)
        if text.startswith("发本地文件"):
            return self._cmd_local_file(group, msg_id, author, text[len("发本地文件"):].strip())
        return False

    def _send_demo_media(self, group, msg_id, file_type, url, label, config_key):
        """「图片/视频/语音/文件」命令：URL 上传 + msg_type=7 发送。"""
        if not url:
            self._reply_text(group, msg_id, f"请先在 config.json 配置 {config_key}。")
            return True
        try:
            resp = self.api.send_group_media(group, file_type, url, msg_id=msg_id)
            self._remember_group_reply(group, resp)
            log.info("%s 发送完成（file_type=%s）", label, file_type)
        except ApiError as e:
            log.warning("%s 发送失败：%s", label, e)
            self._reply_text(group, msg_id, f"{label}发送失败（{e.err_code}），详见日志。")
        return True

    def _recall_group_last(self, group, msg_id, reference=None):
        """群聊「撤回」：撤回机器人自己最近一条群消息（官方限制 2 分钟内，超时报 40064004）。"""
        last = self._last_group_reply.get(group)
        if not last:
            self._reply_text(group, msg_id, "没有可撤回的机器人消息。", reference=reference)
            return True
        try:
            self.api.recall_group_message(group, last)
            self._last_group_reply.pop(group, None)
            log.info("群消息已撤回：%s", last)
        except ApiError as e:
            if e.err_code == 40064004:
                self._last_group_reply.pop(group, None)
            log.warning("群消息撤回失败：%s", e)
            tip = {40064004: "消息发送已超 2 分钟",
                   40062003: "机器人无撤回权限"}.get(e.err_code, "撤回失败，详见日志")
            self._reply_text(group, msg_id, f"撤回失败：{tip}（{e.err_code}）。")
        return True

    def _no_permission(self, e):
        """群管理接口白名单外报 11253（位于 code 字段）或 40012010（err_code 字段）。"""
        return 11253 in (e.err_code, e.api_code) or 40012010 in (e.err_code, e.api_code)

    def _cmd_members(self, group, msg_id, reference=None):
        """「成员列表」：群成员清点（白名单接口）+ 本机活跃统计（GUGUBot 对账的 demo 版）。"""
        try:
            members = self.api.get_group_members(group)
        except ApiError as e:
            tip = "接口需白名单权限，请联系平台运营申请" if self._no_permission(e) else "拉取失败"
            log.warning("成员列表拉取失败：%s", e)
            self._reply_text(group, msg_id, f"成员列表获取失败：{tip}（{e.err_code or e.api_code}）。", reference=reference)
            return
        roles = {"owner": "群主", "admin": "管理", "member": "成员"}
        lines = [f"群成员共 {len(members)} 人："]
        for m in members[:20]:
            role = roles.get(m.get("member_role"), m.get("member_role", "?"))
            lines.append(f"· [{role}] {m.get('username', '?')}（{str(m.get('member_openid', ''))[:8]}…）")
        if len(members) > 20:
            lines.append(f"…其余 {len(members) - 20} 人略")
        stats = self._activity.get(group) or {}
        if stats:
            lines.append(f"—— 活跃统计（本机跟踪 {len(stats)} 人有发言）TOP5 ——")
            top = sorted(stats.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:5]
            lines.extend(
                f"· {v.get('username') or k[:8]}：{v.get('count', 0)} 条" for k, v in top)
        self._reply_text(group, msg_id, "\n".join(lines), reference=reference)

    def _cmd_group_info(self, group, msg_id, reference=None):
        try:
            info = self.api.get_group_info(group)
        except ApiError as e:
            tip = "接口需白名单权限" if self._no_permission(e) else "获取失败"
            log.warning("群信息获取失败：%s", e)
            self._reply_text(group, msg_id, f"群信息获取失败：{tip}（{e.err_code or e.api_code}）。", reference=reference)
            return
        tags = "、".join(info.get("group_tags") or [])
        lines = [
            f"群名称：{info.get('group_name', '?')}",
            f"群人数：{info.get('group_member_num', '?')}",
            f"群分类：{info.get('group_class_text', '-')}",
        ]
        if tags:
            lines.append(f"群标签：{tags}")
        if info.get("group_finger_memo"):
            lines.append(f"群简介：{info['group_finger_memo']}")
        self._reply_text(group, msg_id, "\n".join(lines), reference=reference)

    def _cmd_bot_state(self, group, msg_id, reference=None):
        try:
            state = self.api.get_group_bot_state(group)
        except ApiError as e:
            tip = "接口需白名单权限" if self._no_permission(e) else "获取失败"
            log.warning("机器人状态获取失败：%s", e)
            self._reply_text(group, msg_id, f"机器人状态获取失败：{tip}（{e.err_code or e.api_code}）。", reference=reference)
            return
        settings = {"all": "全量消息", "only_mention": "仅@消息", "mention_and_context": "@及上下文"}
        lines = [
            f"群内角色：{state.get('member_role', '?')}",
            f"入群时间：{state.get('joined_at', '?')}",
            f"允许主动推送：{'是' if state.get('allow_proactive_msg') else '否'}",
            f"消息接收设置：{settings.get(state.get('recv_msg_setting'), state.get('recv_msg_setting', '?'))}",
        ]
        self._reply_text(group, msg_id, "\n".join(lines), reference=reference)

    def _cmd_local_file(self, group, msg_id, author, name):
        """「发本地文件 <文件名>」：分片上传 demo 目录内的文件（仅管理员，限制目录防穿越）。"""
        if author.get("member_role") not in ("admin", "owner"):
            self._reply_text(group, msg_id, "只有群主/管理员可以使用「发本地文件」。")
            return True
        if not name:
            self._reply_text(group, msg_id, "用法：发本地文件 <demo 目录下的文件名>")
            return True
        base = Path(__file__).parent.resolve()
        target = (base / name).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            self._reply_text(group, msg_id, f"demo 目录下找不到文件：{name}")
            return True
        try:
            self.api.send_group_file_chunked(group, target, file_type=4, msg_id=msg_id)
            log.info("本地文件分片上传完成：%s", target.name)
        except ApiError as e:
            log.warning("本地文件上传失败：%s", e)
            self._reply_text(group, msg_id, f"上传失败（{e.err_code}），详见日志。")
        return True

    def _announce(self, group, msg_id, author, body):
        """「公告 内容」：@全体成员广播。

        <qqbot-at-everyone /> 要求机器人有群管理员身份，且每群每天仅 1 次。
        """
        if author.get("member_role") not in ("admin", "owner"):
            log.info("公告被拒绝：发送者角色=%s", author.get("member_role"))
            try:
                self.api.send_group_text(group, "只有群主/管理员可以使用「公告」命令。", msg_id=msg_id)
            except ApiError as e:
                log.warning("公告权限提示发送失败：%s", e)
            return True
        if not body:
            try:
                self.api.send_group_text(group, "用法：公告 内容", msg_id=msg_id)
            except ApiError as e:
                log.warning("公告用法提示发送失败：%s", e)
            return True
        try:
            self.api.send_group_markdown(group, f"{at_everyone_tag()} {body}", msg_id=msg_id)
            log.info("公告已发送（@全体）：%r", body)
        except ApiError as e:
            log.warning("公告发送失败（需机器人有群管理员身份；@全体 每群每天 1 次）：%s", e)
        return True

    def _keyword_reply(self, group, msg_id, content, reference=None):
        for word, reply in self.keywords.items():
            if word in content:
                self._reply_text(group, msg_id, reply, reference=reference)
                return True
        return False

    # ---- 单聊 ----

    def _c2c_message(self, d):
        msg_id = d.get("id")
        if not msg_id:
            return
        author = d.get("author", {})
        if author.get("bot"):
            return
        # 空消息不占用去重名额（原因同群消息，C2C 文档明确相同 msg_id 可能重复推送）
        if not (d.get("content") or "").strip() and not d.get("attachments"):
            log.info("[单聊] 忽略空消息 message_type=%s（不占用去重）", d.get("message_type"))
            return
        if self._seen.seen(msg_id):
            return
        user = author.get("user_openid") or author.get("id")
        content = d.get("content", "").strip()
        log.info("[单聊] %s(%s): %r", author.get("username") or "?", user, content)
        if not user:
            return
        text = content.strip()
        if text == "/userId":
            self._c2c_reply(user, msg_id, f"你的用户 OpenID（user_openid）：\n{user}")
            return
        if text == "/groupId":
            self._c2c_reply(user, msg_id, "单聊场景无群 ID。")
            return
        if text == "图片":
            self._c2c_send_image(user, msg_id)
            return
        if text == "撤回":
            self._c2c_recall_last(user)
            return
        # 未命中的普通单聊消息不做回复（连接验证阶段的调试 echo 已移除）

    def _c2c_send_image(self, user, msg_id):
        """单聊「图片」命令：URL 上传（单聊/群聊媒体隔离，须用 /v2/users 端点）+ 发送。"""
        if not self.demo_image_url:
            self._c2c_reply(user, msg_id, "请先在 config.json 配置 demo_image_url。")
            return
        try:
            file_info = self.api.upload_c2c_media(user, 1, self.demo_image_url)
            resp = self.api.send_c2c_media(user, file_info, msg_id=msg_id)
            if resp and resp.get("id"):
                self._last_c2c_reply[user] = resp["id"]
            log.info("单聊图片发送完成")
        except ApiError as e:
            log.warning("单聊图片发送失败：%s", e)
            self._c2c_reply(user, msg_id, f"图片发送失败（{e.err_code}），详见日志。")

    def _c2c_recall_last(self, user):
        """单聊「撤回」命令：撤回机器人最近一条回复（官方限制 2 分钟内，超时报 40064004）。"""
        last = self._last_c2c_reply.get(user)
        if not last:
            self._c2c_reply(user, None, "没有可撤回的回复。")
            return
        try:
            self.api.recall_c2c_message(user, last)
            self._last_c2c_reply.pop(user, None)
            log.info("单聊消息已撤回：%s", last)
        except ApiError as e:
            if e.err_code == 40064004:
                self._last_c2c_reply.pop(user, None)
            log.warning("单聊撤回失败：%s", e)
            self._c2c_reply(user, None, "撤回失败：消息发送已超 2 分钟。" if e.err_code == 40064004 else "撤回失败，详见日志。")

    def _c2c_reply(self, user, msg_id, content):
        try:
            resp = self.api.send_c2c_text(user, content, msg_id=msg_id)
            if resp and resp.get("id"):
                self._last_c2c_reply[user] = resp["id"]
        except ApiError as e:
            log.warning("单聊发送失败：%s", e)

    # ---- 成员/机器人事件 ----

    def _member_join(self, d):
        group = d.get("group_openid", "")
        member = d.get("member_openid") or ""
        log.info("[入群] member=%s group=%s", member, group)
        if not (self.member_notice and self.welcome_text):
            return
        # 注意：入群事件没有被动回复锚点，这里是主动消息（受频控：单群 1000 条/天）；
        # send_groups 非空时欢迎发往指定群（收发分离，对照 GUGUBot forward_group_ids）
        for target in self.send_groups or [group]:
            try:
                if member:
                    # @ 标签仅在 Markdown 消息中渲染，欢迎语须走 msg_type=2
                    self.api.send_group_markdown(target, f"{at_user_tag(member)} {self.welcome_text}")
                else:
                    self.api.send_group_text(target, self.welcome_text)
            except ApiError as e:
                log.warning("欢迎消息发送失败（%s）：%s", target, e)

    def _member_leave(self, d):
        group = d.get("group_openid", "")
        log.info("[退群] member=%s group=%s", d.get("member_openid"), group)
        if not (self.member_notice and self.farewell_text):
            return
        for target in self.send_groups or [group]:
            try:
                self.api.send_group_text(target, self.farewell_text)
            except ApiError as e:
                log.warning("告别消息发送失败（%s）：%s", target, e)

    def _robot_added(self, d, event_id):
        group = d.get("group_openid", "")
        log.info("[机器人入群] group=%s", group)
        # GROUP_ADD_ROBOT 支持 event_id 被动回复（group-messages-post.md event_id 说明）
        if event_id:
            try:
                self.api.send_group_text(group, "大家好，发送「帮助」查看我能做什么！", event_id=event_id)
            except ApiError as e:
                log.warning("入群致谢发送失败：%s", e)


def setup_file_logging(config):
    log_file = config.get("log_file")
    if not log_file:
        return
    handler = RotatingFileHandler(Path(__file__).with_name(log_file),
                                  maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)  # 文件日志含 DEBUG（如心跳），控制台仍为 INFO
    handler.setLevel(logging.DEBUG)
    for h in logging.getLogger().handlers:
        h.setLevel(logging.INFO)


def main():
    config_path = Path(__file__).with_name("config.json")
    if not config_path.exists():
        raise SystemExit("请先复制 config.example.json 为 config.json 并填入 AppID/AppSecret")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    setup_file_logging(config)
    tokens = TokenManager(config["app_id"], config["app_secret"])
    api_base = SANDBOX_API_BASE if config.get("sandbox") else API_BASE
    log.info("使用环境：%s", api_base)
    api = ApiClient(tokens, api_base, max_message_length=config.get("max_message_length", 2000))
    handlers = DemoHandlers(api, config)
    gateway = Gateway(api, tokens, handlers, on_ready=handlers.on_ready)
    log.info("实例启动 pid=%s（同一时间应只有一个实例在运行）", os.getpid())
    try:
        gateway.run()
    except KeyboardInterrupt:
        log.info("手动停止")


if __name__ == "__main__":
    main()
