import json
import logging
import ssl
import threading
import traceback
from typing import Any, Callable, Dict, Optional

import websocket

logging.getLogger("websocket").setLevel(logging.WARNING)


class WebSocketClient:
    """WebSocket client base class.

    Encapsulates basic WebSocket connection functionality including
    connecting, disconnecting, and sending messages.

    Attributes
    ----------
    url : str
        WebSocket server URL.
    headers : Optional[Dict[str, str]]
        HTTP headers sent during connection.
    ws : Optional[websocket.WebSocketApp]
        WebSocket application instance.
    listener_thread : Optional[threading.Thread]
        Listener thread.
    logger : logging.Logger
        Logger instance.
    """

    def __init__(
            self,
            url: str,
            headers: Optional[Dict[str, str]] = None,
            on_message: Optional[Callable] = None,
            on_open: Optional[Callable] = None,
            on_error: Optional[Callable] = None,
            on_close: Optional[Callable] = None,
            logger: Optional[logging.Logger] = None,
            on_reconnect: Optional[Callable] = None,
    ):
        """Initialize the WebSocket client.

        Parameters
        ----------
        url : str
            WebSocket server URL.
        headers : Dict[str, str], optional
            HTTP request headers.
        on_message : Callable, optional
            Message received callback.
        on_open : Callable, optional
            Connection opened callback.
        on_error : Callable, optional
            Error handling callback.
        on_close : Callable. optional
            Connection closed callback.
        logger : logging.Logger, optional
            Logger instance.
        on_reconnect : Callable, optional
            Callback invoked after a successful reconnection.
        """
        self.url = url
        self.headers = headers
        self.ws: Optional[websocket.WebSocketApp] = None
        self.listener_thread: Optional[threading.Thread] = None
        self.logger = logger or logging.getLogger(__name__)

        # Callbacks
        self._on_message_callback = on_message
        self._on_open_callback = on_open
        self._on_error_callback = on_error
        self._on_close_callback = on_close
        self._on_reconnect_callback = on_reconnect
        self._stop_event = threading.Event()

    def connect(
            self,
            reconnect: int = 5,
            ping_interval: int = 20,
            ping_timeout: int = 10,
            use_ssl: bool = False,
            verify: bool = True,
            ca_certs: Optional[str] = None,
            extra_sslopt: Optional[Dict[str, Any]] = None,
            thread_name: str = "WebSocketClient",
            suppress_origin: bool = True,
            reconnect_attempts: int = 0,
    ) -> None:
        """Establish a WebSocket connection.

        Parameters
        ----------
        reconnect : int, optional
            Reconnect interval in seconds, default ``5``.
        reconnect_attempts : int, optional
            Maximum number of retries after the initial connection. ``0``
            means unlimited retries.
        ping_interval : int, optional
            Ping interval in seconds, default ``20``.
        ping_timeout : int, optional
            Ping timeout in seconds, default ``10``.
        use_ssl : bool, optional
            Whether to use SSL/TLS encrypted connection.
        verify : bool, optional
            Whether to verify SSL certificates.
        ca_certs : str, optional
            CA certificate file path.
        extra_sslopt : Dict[str, Any], optional
            Additional SSL options.
        thread_name : str, optional
            Listener thread name.
        suppress_origin : bool, optional
            Whether to suppress the Origin header in the WebSocket
            handshake, default ``True``.
        """
        self.logger.debug(f"正在连接到WebSocket服务器: {self.url}")

        self._stop_event.clear()
        has_connected = False

        def on_open(ws):
            nonlocal has_connected
            callback = self._on_open_callback
            if has_connected and self._on_reconnect_callback:
                callback = self._on_reconnect_callback
            has_connected = True
            if callback:
                callback(ws)

        self.ws = websocket.WebSocketApp(
            self.url,
            header=self.headers,
            on_message=self._on_message_callback,
            on_open=on_open,
            on_error=self._on_error_callback,
            on_close=self._on_close_callback,
        )

        run_kwargs = {}

        if ping_interval > 0:
            run_kwargs["ping_interval"] = ping_interval
            if ping_timeout > 0:
                run_kwargs["ping_timeout"] = ping_timeout

        # Configure SSL options
        if use_ssl:
            sslopt = {}
            if not verify:
                sslopt["cert_reqs"] = ssl.CERT_NONE
            else:
                sslopt["cert_reqs"] = ssl.CERT_REQUIRED
                if ca_certs:
                    sslopt["ca_certs"] = ca_certs

            if extra_sslopt:
                sslopt.update(extra_sslopt)

            run_kwargs["sslopt"] = sslopt

        if suppress_origin:
            run_kwargs["suppress_origin"] = True

        def run():
            retries = 0
            while not self._stop_event.is_set():
                self.ws.run_forever(**run_kwargs)
                if self._stop_event.is_set() or reconnect <= 0:
                    return
                if reconnect_attempts > 0 and retries >= reconnect_attempts:
                    self.logger.error(
                        "WebSocket 重连次数已达上限（%s），停止重连；"
                        "修复配置后可执行 !!MCDR plugin reloadall 重新连接",
                        reconnect_attempts,
                    )
                    return
                retries += 1
                self.logger.warning(
                    "WebSocket 连接断开，%ss 后进行第 %s 次重连%s",
                    reconnect,
                    retries,
                    f"/{reconnect_attempts}" if reconnect_attempts > 0 else "",
                )
                if self._stop_event.wait(reconnect):
                    return

        # Start listener thread
        self.listener_thread = threading.Thread(
            target=run, name=thread_name
        )
        self.listener_thread.daemon = True
        self.listener_thread.start()

    def send(self, message: Any) -> bool:
        """Send a message.

        Parameters
        ----------
        message : Any
            Message to send (automatically serialized to JSON string).

        Returns
        -------
        bool
            Whether the message was sent successfully.
        """
        if self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                if isinstance(message, (dict, list)):
                    message = json.dumps(message)
                self.ws.send(message)
                self.logger.debug(f"发送消息: {message}")
                return True
            except Exception as e:
                error_msg = str(e) + "\n" + traceback.format_exc()
                self.logger.error("发送消息失败: %s", error_msg)
                return False
        else:
            self.logger.warning("WebSocket未连接，无法发送消息")
            return False

    def disconnect(self, timeout: int = 5) -> None:
        """Disconnect the WebSocket connection.

        Parameters
        ----------
        timeout : int
            Timeout in seconds for waiting the thread to close.
        """
        try:
            self._stop_event.set()
            if self.ws:
                self.ws.close()
            if self.listener_thread and self.listener_thread.is_alive():
                self.listener_thread.join(timeout=timeout)
            self.logger.info("WebSocket连接已关闭")
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.warning("关闭WebSocket连接时发生错误: %s", error_msg)
            raise

    def is_connected(self) -> bool:
        """Check connection status.

        Returns
        -------
        bool
            Whether the client is connected.
        """
        return (
                self.ws is not None and self.ws.sock is not None and self.ws.sock.connected
        )
