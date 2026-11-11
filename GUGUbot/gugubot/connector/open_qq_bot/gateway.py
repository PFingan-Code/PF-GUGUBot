"""QQ 官方机器人 WebSocket 网关（open-qq-bot 连接器）。

由 demo 的 Gateway 拆分而来：所有依赖改为构造注入。负责：
- 获取网关地址并建立 WSS 连接（websocket-client，独立线程）
- Identify / 心跳 / Resume / 断线指数退避重连
- 事件分发：op=0 事件通过 ``on_event(t, d, event_id)`` 回调交给 connector

线程模型：与 GUGUBot 其他 connector 的 ws_client 一致——
``run_forever`` 阻塞在独立线程中；回调线程只做轻量分发，
重活由 connector 通过 ``server.schedule_task`` 抛回 MCDR 事件循环。
"""

import json
import logging
import threading
import time

import websocket

from gugubot.connector.open_qq_bot.common import INTENTS

logger = logging.getLogger("gugubot.open_qq_bot")

# WebSocket 关闭码处理（起步指南/websocket.md 错误码表）
RESUME_CLOSE_CODES = {None, 1000, 1001, 1006, 4008, 4009}  # 可尝试 Resume 重连
FATAL_CLOSE_CODES = {4914, 4915}  # 机器人已下架/封禁，不可恢复
RECONNECT_BACKOFF_MAX = 60


class GatewayStopped(Exception):
    """网关因不可恢复原因（下架/封禁/手动停止）退出。"""


class Gateway:
    """QQ 官方机器人事件网关连接。

    Parameters
    ----------
    gateway_url_getter : Callable[[], str]
        返回网关 WSS 地址（内部刷新 access_token 并请求 /gateway）。
    token_getter : Callable[[], str]
        返回当前 access_token（Identify/Resume 鉴权用）。
    on_event : Callable[[str, dict, str | None], None]
        事件回调 ``(t, d, event_id)``；由 connector 包装后调度到 MCDR 事件循环。
    on_ready : Callable[[dict], None], optional
        鉴权成功回调，入参为 READY 事件的 ``d.user``。
    intents : int
        订阅的事件位掩码（默认取自 :data:`gugubot.connector.open_qq_bot.common.INTENTS`）。
    """

    def __init__(self, gateway_url_getter, token_getter, on_event,
                 on_ready=None, intents: int = INTENTS):
        self._get_url = gateway_url_getter
        self._get_token = token_getter
        self._on_event = on_event
        self._on_ready = on_ready
        self.intents = intents

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

    # ---- 内部 ----

    def _send(self, payload):
        if self.ws:
            self.ws.send(json.dumps(payload))

    def _on_message(self, ws, raw):
        payload = json.loads(raw)
        op = payload.get("op")
        level = logging.DEBUG if op in (1, 11) else logging.INFO
        logger.log(level, "收到网关消息：op=%s t=%s s=%s", op, payload.get("t"), payload.get("s"))
        if op == 10:
            self._heartbeat_interval = payload["d"]["heartbeat_interval"] / 1000
            self._hello.set()
            if self.session_id and self.last_seq is not None:
                logger.info("发送 Resume（session=%s, seq=%s）", self.session_id, self.last_seq)
                self._send({"op": 6, "d": {
                    "token": f"QQBot {self._get_token()}",
                    "session_id": self.session_id, "seq": self.last_seq,
                }})
            else:
                logger.info("发送 Identify（intents=%s）", self.intents)
                self._send({"op": 2, "d": {
                    "token": f"QQBot {self._get_token()}", "intents": self.intents,
                    "shard": [0, 1],
                    "properties": {"$os": "linux", "$browser": "gugubot", "$device": "gugubot"},
                }})
        elif op == 0:
            self.last_seq = payload.get("s", self.last_seq)
            t = payload.get("t")
            if t == "READY":
                self.session_id = payload["d"]["session_id"]
                self._backoff = 1
                self._ready.set()
                logger.info("鉴权成功：%s", payload["d"]["user"]["username"])
                if self._on_ready:
                    self._on_ready(payload["d"]["user"])
            elif t == "RESUMED":
                self._backoff = 1
                self._ready.set()
                logger.info("Session 恢复成功，遗漏事件补发完毕")
            else:
                try:
                    self._on_event(t, payload.get("d") or {}, payload.get("id"))
                except Exception:
                    logger.exception("处理事件 %s 失败", t)
        elif op == 11:
            self._ack.set()
        elif op == 7:
            logger.info("服务端要求重连（op 7）")
            ws.close()
        elif op == 9:
            logger.warning("Invalid Session（op 9），将重新 Identify")
            self.session_id = None
            self.last_seq = None
            ws.close()

    def _on_close(self, ws, code, msg):
        logger.info("连接关闭：code=%s msg=%s", code, msg)
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
            logger.debug("发送心跳 op=1 seq=%s", self.last_seq)
            ws.send(json.dumps({"op": 1, "d": self.last_seq}))
            if not self._ack.wait(timeout=10):
                logger.warning("心跳 ACK 超时，断开重连")
                ws.close()
                return
            time.sleep(self._heartbeat_interval)

    # ---- 对外 ----

    def run(self):
        """阻塞运行网关连接循环（应在独立线程中调用）。

        Raises
        ------
        GatewayStopped
            机器人已下架/封禁（4914/4915）或调用方请求停止。
        """
        while not self._stop:
            self._hello.clear()
            self._ready.clear()
            self._reidentify = False
            url = self._get_url()
            logger.info("连接网关：%s", url)
            self.ws = websocket.WebSocketApp(
                url, on_message=self._on_message, on_close=self._on_close,
                on_error=lambda ws, e: logger.error("WS 错误：%s", e),
            )
            threading.Thread(target=self._heartbeat_loop, args=(self.ws,),
                             daemon=True).start()
            self.ws.run_forever()
            if self._stop:
                break
            if self._fatal:
                raise GatewayStopped("机器人已下架/封禁（关闭码 4914/4915）")
            if self._reidentify:
                self.session_id = None
                self.last_seq = None
            logger.info("%ss 后重连", self._backoff)
            time.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, RECONNECT_BACKOFF_MAX)

    def connect(self):
        """在独立 daemon 线程中启动网关循环（非阻塞，供 connector.connect 调用）。"""
        threading.Thread(target=self._run_guarded, daemon=True).start()

    def _run_guarded(self):
        try:
            self.run()
        except GatewayStopped as e:
            logger.error("%s", e)
        except Exception:
            logger.exception("网关线程异常退出")

    def stop(self):
        """请求停止网关循环并断开当前连接。"""
        self._stop = True
        if self.ws:
            self.ws.close()
