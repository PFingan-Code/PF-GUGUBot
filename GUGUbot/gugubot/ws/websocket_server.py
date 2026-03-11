"""WebSocket server module.

A simple WebSocket server implementation based on the websocket-server library.
"""

import json
import logging
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

try:
    from websocket_server import WebsocketServer
except ImportError:
    WebsocketServer = None


class WebSocketServer:
    """WebSocket server class.

    Accepts incoming WebSocket connections from clients.

    Attributes
    ----------
    host : str
        Listening address.
    port : int
        Listening port.
    server : Optional[WebsocketServer]
        WebSocket server instance.
    server_thread : Optional[threading.Thread]
        Server thread.
    logger : logging.Logger
        Logger instance.
    clients : List[Dict]
        List of connected clients.
    """

    def __init__(
            self,
            host: str = "0.0.0.0",
            port: int = 8787,
            on_message: Optional[Callable] = None,
            on_client_connect: Optional[Callable] = None,
            on_client_disconnect: Optional[Callable] = None,
            logger: Optional[logging.Logger] = None,
    ):
        """Initialize the WebSocket server.

        Parameters
        ----------
        host : str
            Listening address, default ``"0.0.0.0"``.
        port : int
            Listening port, default ``8787``.
        on_message : Callable, optional
            Message received callback, signature: ``(client, server, message)``.
        on_client_connect : Callable, optional
            Client connected callback, signature: ``(client, server)``.
        on_client_disconnect : Callable. optional
            Client disconnected callback, signature: ``(client, server)``.
        logger : logging.Logger, optional
            Logger instance.
        """
        if WebsocketServer is None:
            raise ImportError(
                "websocket-server 库未安装。请运行: pip install websocket-server"
            )

        self.host = host
        self.port = port
        self.logger = logger or logging.getLogger(__name__)
        self.server: Optional[WebsocketServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.clients: List[Dict] = []
        self._is_running = False

        # Callbacks
        self._on_message_callback = on_message
        self._on_client_connect_callback = on_client_connect
        self._on_client_disconnect_callback = on_client_disconnect

    def _handle_new_client(self, client: Dict, server: Any) -> None:
        """Handle a new client connection.

        Parameters
        ----------
        client : Dict
            Client information dictionary.
        server : Any
            Server instance.
        """
        self.clients.append(client)
        self.logger.info(f"新客户端连接: {client['address']}")

        if self._on_client_connect_callback:
            try:
                self._on_client_connect_callback(client, server)
            except Exception as e:
                self.logger.error("客户端连接回调执行失败: %s", e)

    def _handle_client_left(self, client: Dict, server: Any) -> None:
        """Handle a client disconnection.

        Parameters
        ----------
        client : Dict
            Client information dictionary.
        server : Any
            Server instance.
        """
        if client in self.clients:
            self.clients.remove(client)
        client_address = client.get("address") if client else "unknown"
        self.logger.info(f"客户端断开: {client_address}")

        if self._on_client_disconnect_callback:
            try:
                self._on_client_disconnect_callback(client, server)
            except Exception as e:
                self.logger.error("客户端断开回调执行失败: %s", e)

    def _handle_message(self, client: Dict, server: Any, message: str) -> None:
        """Handle a received message.

        Parameters
        ----------
        client : Dict
            Client information dictionary.
        server : Any
            Server instance.
        message : str
            Received message content.
        """
        client_address = client.get("address") if client else "unknown"
        self.logger.debug(f"收到来自 {client_address} 的消息: {message}")

        if self._on_message_callback:
            try:
                self._on_message_callback(client, server, message)
            except Exception as e:
                self.logger.error(f"消息处理回调执行失败: {e}")

    def start(self, daemon: bool = True) -> None:
        """Start the WebSocket server.

        Parameters
        ----------
        daemon : bool
            Whether to run as a daemon thread, default ``True``.
        """
        if self._is_running:
            self.logger.warning("服务器已经在运行中")
            return

        try:
            self.logger.info("正在启动WebSocket服务器: %s:%s", self.host, self.port)

            self.server = WebsocketServer(
                host=self.host,
                port=self.port,
                loglevel=logging.WARNING,
            )

            self.server.set_fn_new_client(self._handle_new_client)
            self.server.set_fn_client_left(self._handle_client_left)
            self.server.set_fn_message_received(self._handle_message)

            self.server_thread = threading.Thread(
                target=self._run_server, name="WebSocketServer", daemon=daemon
            )
            self.server_thread.start()
            self._is_running = True

            self.logger.info("WebSocket服务器已启动在 %s:%s", self.host, self.port)

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error("启动WebSocket服务器失败: %s", error_msg)
            raise

    def _run_server(self) -> None:
        """Run the server in a thread."""
        try:
            self.server.run_forever()
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"WebSocket服务器运行出错: {error_msg}")
        finally:
            self._is_running = False

    def stop(self, timeout: int = 5) -> None:
        """Stop the WebSocket server.

        Parameters
        ----------
        timeout : int
            Timeout in seconds for waiting the thread to close.
        """
        if not self._is_running:
            self.logger.warning("服务器未运行")
            return

        try:
            if self.server:
                client_count = len(self.clients)
                if client_count > 0:
                    self.logger.info("正在断开 %s 个客户端...", client_count)

                    for client in self.clients.copy():
                        try:
                            self.server.send_message(
                                client, json.dumps({"type": "server_shutdown"})
                            )
                        except Exception:
                            pass

                        try:
                            if hasattr(self.server, "disconnect_client"):
                                self.server.disconnect_client(
                                    client, status=1000, reason="Server shutdown"
                                )
                            elif "handler" in client:
                                handler = client["handler"]
                                if hasattr(handler, "request"):
                                    handler.request.close()
                        except Exception:
                            pass

                    time.sleep(0.5)

                if hasattr(self.server, "shutdown_gracefully"):
                    self.server.shutdown_gracefully()
                else:
                    self.server.shutdown_abruptly()

            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=timeout)

            self._is_running = False
            self.clients.clear()

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error("停止WebSocket服务器时出错: %s", error_msg)
            raise

    def send_message(self, client: Dict, message: Any) -> bool:
        """Send a message to the specified client.

        Parameters
        ----------
        client : Dict
            Client information dictionary.
        message : Any
            Message to send (automatically serialized to JSON string).

        Returns
        -------
        bool
            Whether the message was sent successfully.
        """
        if not self._is_running or not self.server:
            self.logger.warning("服务器未运行，无法发送消息")
            return False

        try:
            if isinstance(message, (dict, list)):
                message = json.dumps(message, ensure_ascii=False)

            self.server.send_message(client, message)
            self.logger.debug("向 %s 发送消息: %s", client['address'], message)
            return True

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error("发送消息失败: %s", error_msg)
            return False

    def broadcast(self, message: Any) -> int:
        """Broadcast a message to all connected clients.

        Parameters
        ----------
        message : Any
            Message to broadcast (automatically serialized to JSON string).

        Returns
        -------
        int
            Number of clients the message was sent to.
        """
        if not self._is_running or not self.server:
            self.logger.warning("服务器未运行，无法广播消息")
            return 0

        try:
            if isinstance(message, (dict, list)):
                message = json.dumps(message, ensure_ascii=False)

            self.server.send_message_to_all(message)
            count = len(self.clients)
            self.logger.debug("向 %s 个客户端广播消息: %s", count, message)
            return count

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error("广播消息失败: %s", error_msg)
            return 0

    def is_running(self) -> bool:
        """Check whether the server is running.

        Returns
        -------
        bool
            Whether the server is running.
        """
        return self._is_running

    def get_clients(self) -> List[Dict]:
        """Get the list of connected clients.

        Returns
        -------
        List[Dict]
            List of client information dictionaries.
        """
        return self.clients.copy()

    def get_client_count(self) -> int:
        """Get the number of connected clients.

        Returns
        -------
        int
            Number of connected clients.
        """
        return len(self.clients)
