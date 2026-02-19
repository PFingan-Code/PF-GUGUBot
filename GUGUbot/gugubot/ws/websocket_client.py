import json
import logging
import ssl
import threading
import traceback
from typing import Any, Callable, Dict, Optional

import websocket

logging.getLogger("websocket").setLevel(logging.WARNING)


class WebSocketClient:
    """WebSocket客户端基类

    封装了websocket连接的基本功能，包括连接、断开、发送消息等。

    Attributes
    ----------
    url : str
        WebSocket服务器的URL
    headers : Optional[Dict[str, str]]
        连接时的HTTP头信息
    ws : Optional[websocket.WebSocketApp]
        WebSocket应用实例
    listener_thread : Optional[threading.Thread]
        监听线程
    logger : logging.Logger
        日志记录器
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
    ):
        """初始化WebSocket客户端

        Parameters
        ----------
        url : str
            WebSocket服务器URL
        headers : Dict[str, str], optional
            HTTP请求头
        on_message : Callable, optional
            消息接收回调函数
        on_open : Callable, optional
            连接建立回调函数
        on_error : Callable, optional
            错误处理回调函数
        on_close : Callable. optional
            连接关闭回调函数
        logger : logging.Logger, optional
            日志记录器
        """
        self.url = url
        self.headers = headers
        self.ws: Optional[websocket.WebSocketApp] = None
        self.listener_thread: Optional[threading.Thread] = None
        self.logger = logger or logging.getLogger(__name__)

        # 回调函数
        self._on_message_callback = on_message
        self._on_open_callback = on_open
        self._on_error_callback = on_error
        self._on_close_callback = on_close

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
    ) -> None:
        """建立WebSocket连接

        Parameters
        ----------
        reconnect : int, optional
            重连间隔时间（秒），默认 ``5`` 秒
        ping_interval : int, optional
            心跳间隔时间（秒），默认 ``20`` 秒
        ping_timeout : int, optional
            心跳超时时间（秒），默认 ``10`` 秒
        use_ssl : bool, optional
            是否使用 SSL/TLS 加密连接
        verify : bool, optional
            是否验证 SSL 证书
        ca_certs : str, optional
            CA 证书文件路径
        extra_sslopt : Dict[str, Any], optional
            额外的 SSL 选项
        thread_name : str, optional
            监听线程名称
        suppress_origin : bool, optional
            是否抑制 WebSocket 握手中的 Origin 头，默认 ``True``
        """
        self.logger.debug(f"正在连接到WebSocket服务器: {self.url}")

        self.ws = websocket.WebSocketApp(
            self.url,
            header=self.headers,
            on_message=self._on_message_callback,
            on_open=self._on_open_callback,
            on_error=self._on_error_callback,
            on_close=self._on_close_callback,
        )

        # 构建run_forever参数
        run_kwargs = {}

        if reconnect > 0:
            run_kwargs["reconnect"] = reconnect

        if ping_interval > 0:
            run_kwargs["ping_interval"] = ping_interval
            if ping_timeout > 0:
                run_kwargs["ping_timeout"] = ping_timeout

        # 配置SSL选项
        if use_ssl:
            sslopt = {}
            if not verify:
                sslopt["cert_reqs"] = ssl.CERT_NONE
            else:
                sslopt["cert_reqs"] = ssl.CERT_REQUIRED
                if ca_certs:
                    sslopt["ca_certs"] = ca_certs

            # 应用额外的SSL选项
            if extra_sslopt:
                sslopt.update(extra_sslopt)

            run_kwargs["sslopt"] = sslopt

        if suppress_origin:
            run_kwargs["suppress_origin"] = True

        # 启动监听线程
        self.listener_thread = threading.Thread(
            target=self.ws.run_forever, name=thread_name, kwargs=run_kwargs
        )
        self.listener_thread.daemon = True
        self.listener_thread.start()

    def send(self, message: Any) -> bool:
        """发送消息

        Parameters
        ----------
        message : Any
            要发送的消息（会自动转换为JSON字符串）

        Returns
        -------
        bool
            是否发送成功
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
                self.logger.error(f"发送消息失败: {error_msg}")
                return False
        else:
            self.logger.warning("WebSocket未连接，无法发送消息")
            return False

    def disconnect(self, timeout: int = 5) -> None:
        """断开WebSocket连接

        Parameters
        ----------
        timeout : int
            等待线程关闭的超时时间（秒）
        """
        try:
            if self.ws:
                self.ws.close()
            if self.listener_thread and self.listener_thread.is_alive():
                self.listener_thread.join(timeout=timeout)
            self.logger.info("WebSocket连接已关闭")
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.warning(f"关闭WebSocket连接时发生错误: {error_msg}")
            raise

    def is_connected(self) -> bool:
        """检查连接状态

        Returns
        -------
        bool
            是否已连接
        """
        return (
                self.ws is not None and self.ws.sock is not None and self.ws.sock.connected
        )
