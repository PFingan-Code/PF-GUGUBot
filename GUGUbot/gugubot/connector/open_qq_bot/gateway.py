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

from gugubot.connector.open_qq_bot.common import INTENTS, ApiError

logger = logging.getLogger("gugubot.open_qq_bot")

# WebSocket 关闭码处理（起步指南/websocket.md 错误码表）
RESUME_CLOSE_CODES = {None, 1000, 1001, 1006, 4008, 4009}  # 可尝试 Resume 重连
FATAL_CLOSE_CODES = {4914, 4915}  # 机器人已下架/封禁，不可恢复
# 不可 Resume 且不可重新 Identify 的关闭码（官方逐码表两项均为"否"）：
# 4001/4002 参数无效、4010 应用未上线、4011 权限不足、4012 无效版本号、
# 4013 无效 intents、4014 intents 权限不足。此类属于配置/审核问题，
# 盲目重连无法恢复，还会耗尽 /gateway 的 session_start_limit（1000 次/天）。
# 注意：官方页面结尾"其他错误请重新 identify"的笼统说法与逐码表自相矛盾，
# 此处以逐码表为准。
NON_RETRYABLE_CLOSE_CODES = {4001, 4002, 4010, 4011, 4012, 4013, 4014}
# 其中 4013/4014 与 intents 配置直接相关，终止时提示排查方向
INTENT_CLOSE_CODES = {4013, 4014}
RECONNECT_BACKOFF_MAX = 60

# 凭据类 HTTP 状态码：重试无意义，应停止并给出明确告警
CREDENTIAL_HTTP_CODES = {401, 403}


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
        self._stop_event = threading.Event()
        self._fatal = False
        self._reidentify = False
        self._close_code = None
        self._backoff = 1
        self._thread = None

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
            logger.info("心跳间隔：%.1fs（服务端下发）", self._heartbeat_interval)
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
            self._close_code = code
        elif code in NON_RETRYABLE_CLOSE_CODES:
            # 不可 Resume 也不可重新 Identify（官方逐码表双"否"）：记录实际
            # 关闭码交由 run() 终止，不再静默重新 Identify 无限重连
            self._close_code = code
            logger.warning(
                "关闭码 %s 不可重试（不可 Resume 也不可重新 Identify），停止网关",
                code,
            )
        elif code not in RESUME_CLOSE_CODES:
            self._reidentify = True

    def _heartbeat_loop(self, ws):
        # 必须等鉴权完成（READY/RESUMED）再发心跳，网关不回未鉴权连接的 ACK
        if not self._hello.wait(timeout=10) or not self._ready.wait(timeout=15):
            return
        # 日志方案：正常心跳只留 DEBUG（发送 + ACK 各一条），不按拍刷 INFO；
        # 间隔以 HELLO 下发值为准（INFO 打印一次），ACK 超过一个间隔才 WARNING。
        interval = self._heartbeat_interval
        last_beat = None
        while ws.keep_running and not self._stop:
            now = time.monotonic()
            if last_beat is not None:
                gap = now - last_beat
                # 线程被 GIL/系统挂起拖慢时，实际间隔会明显超过下发值
                if gap > interval * 1.5:
                    logger.warning(
                        "心跳间隔 %.1fs，超过正常间隔 %.1fs", gap, interval
                    )
            last_beat = now
            self._ack.clear()
            send_at = time.monotonic()
            logger.debug("发送心跳 op=1 seq=%s（间隔 %.1fs）", self.last_seq, interval)
            try:
                ws.send(json.dumps({"op": 1, "d": self.last_seq}))
            except Exception as e:
                # 连接已在 run_forever 退出过程中关闭：结束心跳线程即可，
                # 重连由 run() 中 run_forever 的返回逻辑统一处理
                logger.debug("心跳发送失败（连接已关闭）：%s", e)
                return
            if not self._ack.wait(timeout=interval):
                logger.warning(
                    "心跳 ACK 超过 %.1fs 未返回（正常间隔 %.1fs），断开重连",
                    interval, interval,
                )
                ws.close()
                return
            # ACK 到手后只补足剩余间隔：节拍从发送时刻起算，避免漂移累计
            # （原实现 ACK 返回后再无条件 sleep(interval)，实际节拍 =
            # interval + ACK 往返耗时）。remaining ≤ 0 时不等待直接进下一拍，
            # stop() 请求会经由 _stop_event.wait 立即打断。
            remaining = interval - (time.monotonic() - send_at)
            self._stop_event.wait(max(0.0, remaining))

    # ---- 对外 ----

    @staticmethod
    def _is_credential_error(e: Exception) -> bool:
        """凭据类错误（HTTP 401/403）：重试无意义，应停止并明确告警。"""
        return isinstance(e, ApiError) and e.status in CREDENTIAL_HTTP_CODES

    def run(self):
        """阻塞运行网关连接循环（应在独立线程中调用）。

        网关地址 / access_token 的获取同样纳入指数退避重试——启动瞬时
        故障（网络超时、QQ 接口 5xx 等）不再让异常逃出线程导致永久离线；
        凭据类错误（HTTP 401/403）视为不可恢复，直接终止并提示检查配置。

        Raises
        ------
        GatewayStopped
            机器人已下架/封禁（4914/4915）、凭据无效或调用方请求停止。
        """
        while not self._stop:
            self._hello.clear()
            self._ready.clear()
            self._reidentify = False
            try:
                url = self._get_url()
            except GatewayStopped:
                raise
            except Exception as e:
                if self._is_credential_error(e):
                    raise GatewayStopped(
                        f"获取网关地址失败（HTTP {e.status}，凭据无效）："
                        "请检查 connector.open-qq-bot.connection.app_id / app_secret"
                    ) from e
                logger.warning(
                    "获取网关地址失败（%s: %s），%ss 后重试",
                    type(e).__name__, e, self._backoff,
                )
                if self._stop_event.wait(self._backoff):
                    break  # stop() 被调用，立即退出
                self._backoff = min(self._backoff * 2, RECONNECT_BACKOFF_MAX)
                continue
            if self._stop:
                break
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
                raise GatewayStopped(
                    f"机器人已下架/封禁（关闭码 {self._close_code}）"
                )
            if self._close_code in NON_RETRYABLE_CLOSE_CODES:
                hint = (
                    "；请到 QQ 开放平台检查机器人 intent/权限配置"
                    if self._close_code in INTENT_CLOSE_CODES else ""
                )
                raise GatewayStopped(
                    f"网关关闭码 {self._close_code} 不可重试"
                    f"（不可 Resume 也不可重新 Identify），停止重连{hint}"
                )
            if self._reidentify:
                self.session_id = None
                self.last_seq = None
            logger.info("%ss 后重连", self._backoff)
            if self._stop_event.wait(self._backoff):
                break
            self._backoff = min(self._backoff * 2, RECONNECT_BACKOFF_MAX)

    def connect(self):
        """在独立 daemon 线程中启动网关循环（非阻塞，供 connector.connect 调用）。"""
        if self._thread and self._thread.is_alive():
            # 旧线程可能正在退避等待或阻塞在 _get_url（token 刷新 + /gateway
            # 各 10s 超时，最坏约 20s）：先请求停止再等待退出，避免下面把
            # _stop 复位后旧线程复活，与新线程双写 self.ws / session_id。
            # 旧线程若在退避 wait 中，stop_event 触发后 join 毫秒级返回。
            self.stop()
            self._thread.join(timeout=25)
            if self._thread.is_alive():
                # 失败安全：保持 _stop 状态、不清 stop_event、不启新线程，
                # 避免旧线程稍后退出时与新线程竞争共享状态
                logger.error("旧网关线程 25s 内未退出，跳过本次 connect() 重启")
                return
        self._stop = False
        self._stop_event.clear()
        self._fatal = False
        # 必须在旧线程 join 之后复位：旧线程终止时可能刚写入实际关闭码
        self._close_code = None
        self._thread = threading.Thread(
            target=self._run_guarded, daemon=True, name="open-qq-bot-gateway"
        )
        self._thread.start()

    @property
    def alive(self) -> bool:
        """网关线程是否存活（健康检查：线程死亡即离线，供连接器探测）。"""
        return bool(self._thread and self._thread.is_alive())

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
        self._stop_event.set()
        if self.ws:
            self.ws.close()
