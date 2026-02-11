"""WebSocket服务器类

基于 websocket-server 库的简单 WebSocket 服务器实现
不使用 asyncio，适合在 MCDR 环境下运行
"""

import json
import logging
import threading
import traceback
from typing import Any, Callable, Dict, List, Optional

try:
    from websocket_server import WebsocketServer
except ImportError:
    WebsocketServer = None


class WebSocketServer:
    """WebSocket服务器类

    用于接收来自客户端的WebSocket连接
    基于 websocket-server 库，使用线程而非 asyncio

    Attributes
    ----------
    host : str
        监听地址
    port : int
        监听端口
    server : Optional[WebsocketServer]
        WebSocket服务器实例
    server_thread : Optional[threading.Thread]
        服务器运行线程
    logger : logging.Logger
        日志记录器
    clients : List[Dict]
        已连接的客户端列表
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
        """初始化WebSocket服务器

        Parameters
        ----------
        host : str
            监听地址，默认 "0.0.0.0"
        port : int
            监听端口，默认 8787
        on_message : Optional[Callable]
            消息接收回调函数，签名: (client, server, message)
        on_client_connect : Optional[Callable]
            客户端连接回调函数，签名: (client, server)
        on_client_disconnect : Optional[Callable]
            客户端断开回调函数，签名: (client, server)
        logger : Optional[logging.Logger]
            日志记录器
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

        # 回调函数
        self._on_message_callback = on_message
        self._on_client_connect_callback = on_client_connect
        self._on_client_disconnect_callback = on_client_disconnect

    def _handle_new_client(self, client: Dict, server: Any) -> None:
        """处理新客户端连接

        Parameters
        ----------
        client : Dict
            客户端信息字典
        server : Any
            服务器实例
        """
        self.clients.append(client)
        self.logger.info(f"新客户端连接: {client['address']}")

        if self._on_client_connect_callback:
            try:
                self._on_client_connect_callback(client, server)
            except Exception as e:
                self.logger.error(f"客户端连接回调执行失败: {e}")

    def _handle_client_left(self, client: Dict, server: Any) -> None:
        """处理客户端断开连接

        Parameters
        ----------
        client : Dict
            客户端信息字典
        server : Any
            服务器实例
        """
        if client in self.clients:
            self.clients.remove(client)
        client_address = client.get("address") if client else "unknown"
        self.logger.info(f"客户端断开: {client_address}")

        if self._on_client_disconnect_callback:
            try:
                self._on_client_disconnect_callback(client, server)
            except Exception as e:
                self.logger.error(f"客户端断开回调执行失败: {e}")

    def _handle_message(self, client: Dict, server: Any, message: str) -> None:
        """处理接收到的消息

        Parameters
        ----------
        client : Dict
            客户端信息字典
        server : Any
            服务器实例
        message : str
            接收到的消息内容
        """
        client_address = client.get("address") if client else "unknown"
        self.logger.debug(f"收到来自 {client_address} 的消息: {message}")

        if self._on_message_callback:
            try:
                self._on_message_callback(client, server, message)
            except Exception as e:
                self.logger.error(f"消息处理回调执行失败: {e}")

    def start(self, daemon: bool = True) -> None:
        """启动WebSocket服务器

        Parameters
        ----------
        daemon : bool
            是否作为守护线程运行，默认 True
        """
        if self._is_running:
            self.logger.warning("服务器已经在运行中")
            return

        try:
            self.logger.info(f"正在启动WebSocket服务器: {self.host}:{self.port}")

            # 创建服务器实例
            self.server = WebsocketServer(
                host=self.host,
                port=self.port,
                loglevel=logging.WARNING,  # 减少websocket-server自身的日志输出
            )

            # 设置回调
            self.server.set_fn_new_client(self._handle_new_client)
            self.server.set_fn_client_left(self._handle_client_left)
            self.server.set_fn_message_received(self._handle_message)

            # 在新线程中运行服务器
            self.server_thread = threading.Thread(
                target=self._run_server, name="WebSocketServer", daemon=daemon
            )
            self.server_thread.start()
            self._is_running = True

            self.logger.info(f"WebSocket服务器已启动在 {self.host}:{self.port}")

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"启动WebSocket服务器失败: {error_msg}")
            raise

    def _run_server(self) -> None:
        """在线程中运行服务器"""
        try:
            self.server.run_forever()
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"WebSocket服务器运行出错: {error_msg}")
        finally:
            self._is_running = False

    def stop(self, timeout: int = 5) -> None:
        """停止WebSocket服务器

        Parameters
        ----------
        timeout : int
            等待线程关闭的超时时间（秒）
        """
        if not self._is_running:
            self.logger.warning("服务器未运行")
            return

        try:
            if self.server:
                client_count = len(self.clients)
                if client_count > 0:
                    self.logger.info(f"正在断开 {client_count} 个客户端...")

                    # 通知所有客户端服务器即将关闭
                    for client in self.clients.copy():
                        try:
                            self.server.send_message(
                                client, json.dumps({"type": "server_shutdown"})
                            )
                        except:
                            pass

                        # 尝试关闭连接
                        try:
                            if hasattr(self.server, "disconnect_client"):
                                self.server.disconnect_client(
                                    client, status=1000, reason="Server shutdown"
                                )
                            elif "handler" in client:
                                handler = client["handler"]
                                if hasattr(handler, "request"):
                                    handler.request.close()
                        except:
                            pass

                    # 等待关闭完成
                    import time

                    time.sleep(0.5)

                # 关闭服务器
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
            self.logger.error(f"停止WebSocket服务器时出错: {error_msg}")
            raise

    def send_message(self, client: Dict, message: Any) -> bool:
        """向指定客户端发送消息

        Parameters
        ----------
        client : Dict
            客户端信息字典
        message : Any
            要发送的消息（会自动转换为JSON字符串）

        Returns
        -------
        bool
            是否发送成功
        """
        if not self._is_running or not self.server:
            self.logger.warning("服务器未运行，无法发送消息")
            return False

        try:
            if isinstance(message, (dict, list)):
                message = json.dumps(message, ensure_ascii=False)

            self.server.send_message(client, message)
            self.logger.debug(f"向 {client['address']} 发送消息: {message}")
            return True

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"发送消息失败: {error_msg}")
            return False

    def broadcast(self, message: Any) -> int:
        """向所有已连接的客户端广播消息

        Parameters
        ----------
        message : Any
            要广播的消息（会自动转换为JSON字符串）

        Returns
        -------
        int
            成功发送的客户端数量
        """
        if not self._is_running or not self.server:
            self.logger.warning("服务器未运行，无法广播消息")
            return 0

        try:
            if isinstance(message, (dict, list)):
                message = json.dumps(message, ensure_ascii=False)

            self.server.send_message_to_all(message)
            count = len(self.clients)
            self.logger.debug(f"向 {count} 个客户端广播消息: {message}")
            return count

        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"广播消息失败: {error_msg}")
            return 0

    def is_running(self) -> bool:
        """检查服务器是否正在运行

        Returns
        -------
        bool
            服务器是否正在运行
        """
        return self._is_running

    def get_clients(self) -> List[Dict]:
        """获取已连接的客户端列表

        Returns
        -------
        List[Dict]
            客户端信息列表
        """
        return self.clients.copy()

    def get_client_count(self) -> int:
        """获取已连接的客户端数量

        Returns
        -------
        int
            客户端数量
        """
        return len(self.clients)
