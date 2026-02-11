"""WebSocket工厂类

用于创建和管理WebSocket客户端和服务器实例
"""

import logging
from typing import Any, Callable, Optional

from .websocket_client import WebSocketClient
from .websocket_server import WebSocketServer


class WebSocketFactory:
    """WebSocket工厂类

    提供统一的接口来创建WebSocket客户端和服务器实例
    """

    @staticmethod
    def create_client(
            url: str,
            token: Optional[str] = None,
            on_message: Optional[Callable] = None,
            on_open: Optional[Callable] = None,
            on_error: Optional[Callable] = None,
            on_close: Optional[Callable] = None,
            logger: Optional[logging.Logger] = None,
    ) -> WebSocketClient:
        """创建WebSocket客户端

        Parameters
        ----------
        url : str
            WebSocket服务器URL
        token : Optional[str]
            认证令牌
        on_message : Optional[Callable]
            消息接收回调
        on_open : Optional[Callable]
            连接建立回调
        on_error : Optional[Callable]
            错误处理回调
        on_close : Optional[Callable]
            连接关闭回调
        logger : Optional[logging.Logger]
            日志记录器

        Returns
        -------
        WebSocketClient
            WebSocket客户端实例
        """
        headers = {"Authorization": f"Bearer {token}"} if token else None

        return WebSocketClient(
            url=url,
            headers=headers,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close,
            logger=logger,
        )

    @staticmethod
    def create_server(
            host: str = "0.0.0.0",
            port: int = 8787,
            on_message: Optional[Callable] = None,
            on_client_connect: Optional[Callable] = None,
            on_client_disconnect: Optional[Callable] = None,
            logger: Optional[logging.Logger] = None,
    ) -> WebSocketServer:
        """创建WebSocket服务器

        Parameters
        ----------
        host : str
            监听地址
        port : int
            监听端口
        on_message : Optional[Callable]
            消息接收回调
        on_client_connect : Optional[Callable]
            客户端连接回调
        on_client_disconnect : Optional[Callable]
            客户端断开回调
        logger : Optional[logging.Logger]
            日志记录器

        Returns
        -------
        WebSocketServer
            WebSocket服务器实例
        """
        return WebSocketServer(
            host=host,
            port=port,
            on_message=on_message,
            on_client_connect=on_client_connect,
            on_client_disconnect=on_client_disconnect,
            logger=logger,
        )

    @staticmethod
    def create_bridge_server(
            config: Any,
            on_message: Optional[Callable] = None,
            on_client_connect: Optional[Callable] = None,
            on_client_disconnect: Optional[Callable] = None,
            logger: Optional[logging.Logger] = None,
    ) -> WebSocketServer:
        """根据配置创建桥接服务器

        Parameters
        ----------
        config : Any
            配置对象
        on_message : Optional[Callable]
            消息接收回调
        on_client_connect : Optional[Callable]
            客户端连接回调
        on_client_disconnect : Optional[Callable]
            客户端断开回调
        logger : Optional[logging.Logger]
            日志记录器

        Returns
        -------
        WebSocketServer
            配置好的桥接服务器实例
        """
        host = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "host"], "0.0.0.0"
        )
        port = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "port"], 8787
        )

        return WebSocketServer(
            host=host,
            port=port,
            on_message=on_message,
            on_client_connect=on_client_connect,
            on_client_disconnect=on_client_disconnect,
            logger=logger,
        )

    @staticmethod
    def create_bridge_client(
            config: Any,
            on_message: Optional[Callable] = None,
            on_open: Optional[Callable] = None,
            on_error: Optional[Callable] = None,
            on_close: Optional[Callable] = None,
            logger: Optional[logging.Logger] = None,
    ) -> WebSocketClient:
        """根据配置创建桥接客户端

        Parameters
        ----------
        config : Any
            配置对象
        on_message : Optional[Callable]
            消息接收回调
        on_open : Optional[Callable]
            连接建立回调
        on_error : Optional[Callable]
            错误处理回调
        on_close : Optional[Callable]
            连接关闭回调
        logger : Optional[logging.Logger]
            日志记录器

        Returns
        -------
        WebSocketClient
            配置好的桥接客户端实例
        """
        host = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "host"], "127.0.0.1"
        )
        port = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "port"], 8787
        )
        use_ssl = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "use_ssl"], False
        )

        scheme = "wss" if use_ssl else "ws"
        url = f"{scheme}://{host}:{port}"

        token = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "token"], None
        )

        return WebSocketFactory.create_client(
            url=url,
            token=token,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close,
            logger=logger,
        )
