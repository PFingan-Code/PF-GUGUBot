"""WebSocket factory module.

Provides factory methods for creating and managing WebSocket client
and server instances.
"""

import logging
from typing import Any, Callable, Optional

from .websocket_client import WebSocketClient
from .websocket_server import WebSocketServer


class WebSocketFactory:
    """WebSocket factory class.

    Provides a unified interface for creating WebSocket client and
    server instances.
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
        """Create a WebSocket client.

        Parameters
        ----------
        url : str
            WebSocket server URL.
        token : Optional[str]
            Authentication token.
        on_message : Optional[Callable]
            Message received callback.
        on_open : Optional[Callable]
            Connection opened callback.
        on_error : Optional[Callable]
            Error handling callback.
        on_close : Optional[Callable]
            Connection closed callback.
        logger : Optional[logging.Logger]
            Logger instance.

        Returns
        -------
        WebSocketClient
            A WebSocket client instance.
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
        """Create a WebSocket server.

        Parameters
        ----------
        host : str
            Listening address.
        port : int
            Listening port.
        on_message : Optional[Callable]
            Message received callback.
        on_client_connect : Optional[Callable]
            Client connected callback.
        on_client_disconnect : Optional[Callable]
            Client disconnected callback.
        logger : Optional[logging.Logger]
            Logger instance.

        Returns
        -------
        WebSocketServer
            A WebSocket server instance.
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
        """Create a bridge server from configuration.

        Parameters
        ----------
        config : Any
            Configuration object.
        on_message : Optional[Callable]
            Message received callback.
        on_client_connect : Optional[Callable]
            Client connected callback.
        on_client_disconnect : Optional[Callable]
            Client disconnected callback.
        logger : Optional[logging.Logger]
            Logger instance.

        Returns
        -------
        WebSocketServer
            A configured bridge server instance.
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
        """Create a bridge client from configuration.

        Parameters
        ----------
        config : Any
            Configuration object.
        on_message : Optional[Callable]
            Message received callback.
        on_open : Optional[Callable]
            Connection opened callback.
        on_error : Optional[Callable]
            Error handling callback.
        on_close : Optional[Callable]
            Connection closed callback.
        logger : Optional[logging.Logger]
            Logger instance.

        Returns
        -------
        WebSocketClient
            A configured bridge client instance.
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
