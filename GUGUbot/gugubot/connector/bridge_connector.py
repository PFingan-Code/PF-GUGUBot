import asyncio
import json
from typing import Any, Dict

from gugubot.config.BotConfig import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.parser.mc_parser import MCParser
from gugubot.utils.types import BroadcastInfo, ProcessedInfo, Source
from gugubot.ws import WebSocketFactory


class BridgeConnector(BasicConnector):
    """桥接连接器，支持服务器模式和客户端模式

    根据配置中的is_main_server决定运行模式：
    - True: 启动WebSocket服务器，等待其他服务器连接
    - False: 作为客户端连接到主服务器
    """

    def __init__(self, server, config: BotConfig = None):
        source_name = config.get_keys(
            ["connector", "minecraft_bridge", "source_name"], "Bridge"
        )
        super().__init__(source=source_name, parser=MCParser, config=config)
        self.server = server

        # 存储日志前缀和唯一标识
        connector_basic_name = self.server.tr("gugubot.connector.name")
        self.log_prefix = f"[{connector_basic_name}{self.source}]"

        # 添加连接计数器和状态标志
        import time

        self._connect_count = 0
        self._client_id = f"{source_name}_{int(time.time() * 1000)}"
        self._is_reconnecting = False  # 防止多个重连线程同时运行

        # 判断是否为服务器模式
        self.is_main_server = config.get_keys(
            ["connector", "minecraft_bridge", "is_main_server"], True
        )

        # 获取配置
        self.reconnect = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "reconnect"], 5
        )
        self.ping_interval = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "ping_interval"], 5
        )
        self.ping_timeout = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "ping_timeout"], 5
        )
        self.use_ssl = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "use_ssl"], False
        )
        self.verify = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "verify"], True
        )
        self.ca_certs = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "ca_certs"], None
        )
        self.extra_sslopt = config.get_keys(
            ["connector", "minecraft_bridge", "connection", "sslopt"], {}
        )

        # 创建WebSocket实例
        self.ws_server = None
        self.ws_client = None

    async def connect(self) -> None:
        """建立连接"""
        if self.is_main_server and self.enable:
            self._start_server()
        elif not self.is_main_server and self.enable:
            self._connect_to_server()

    def _start_server(self) -> None:
        """启动WebSocket服务器"""
        self.logger.info(f"{self.log_prefix} 正在启动桥接服务器")

        # 创建服务器并传递回调函数
        self.ws_server = WebSocketFactory.create_bridge_server(
            self.config,
            on_message=self._handle_server_message,
            on_client_connect=self._on_client_connect,
            on_client_disconnect=self._on_client_disconnect,
            logger=self.logger,
        )

        # 启动服务器（守护线程）
        self.ws_server.start(daemon=True)

        self.logger.info(f"{self.log_prefix} 桥接服务器就绪 ~")

    def _connect_to_server(self) -> None:
        """连接到主服务器"""
        # 清理旧连接
        if self.ws_client:
            try:
                if self.ws_client.is_connected():
                    self.ws_client.disconnect(timeout=1)
            except:
                pass

        self._connect_count += 1

        if self._connect_count > 1:
            self.logger.info(
                f"{self.log_prefix} 正在重连桥接服务器 (第 {self._connect_count} 次连接)"
            )
        else:
            self.logger.info(f"{self.log_prefix} 正在连接到桥接服务器")

        # 创建客户端
        self.ws_client = WebSocketFactory.create_bridge_client(
            self.config,
            on_message=self._handle_client_message,
            on_open=self._on_client_open,
            on_error=self._on_client_error,
            on_close=self._on_client_close,
            logger=self.logger,
        )

        # 连接到服务器
        self.ws_client.connect(
            reconnect=self.reconnect,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
            use_ssl=self.use_ssl,
            verify=self.verify,
            ca_certs=self.ca_certs,
            extra_sslopt=self.extra_sslopt,
            thread_name=f"[GUGUBot]Bridge_{self._client_id}",
        )

    def _on_client_connect(self, client: Dict, server: Any) -> None:
        """新客户端连接到服务器时"""
        client_address = client.get("address") if client else "unknown"
        client_count = self.ws_server.get_client_count() if self.ws_server else 0
        self.logger.info(
            f"{self.log_prefix} 新客户端连接: {client_address} (总数: {client_count})"
        )

    def _on_client_disconnect(self, client: Dict, server: Any) -> None:
        """客户端从服务器断开时"""
        client_address = client.get("address") if client else "unknown"
        client_count = self.ws_server.get_client_count() if self.ws_server else 0
        self.logger.info(
            f"{self.log_prefix} 客户端断开: {client_address} (剩余: {client_count})"
        )

    def _on_client_open(self, ws) -> None:
        """客户端连接建立时"""
        self.logger.info(f"{self.log_prefix} 连接成功 ~")

    def _on_client_error(self, ws, error: Exception) -> None:
        """客户端连接错误时"""
        self.logger.error(
            f"{self.log_prefix} 连接错误: {type(error).__name__} - {error}"
        )

    def _on_client_close(self, ws, status_code: int, reason: str) -> None:
        """客户端连接关闭时"""
        import threading

        # 检查是否是当前活动的连接
        if self.ws_client and self.ws_client.ws and self.ws_client.ws != ws:
            return

        reason_text = f"({reason})" if reason else ""
        self.logger.info(f"{self.log_prefix} 连接已断开 {reason_text}")

        # 实现持续重连
        if self.reconnect > 0 and self.enable and not self._is_reconnecting:
            self._is_reconnecting = True
            self.logger.info(f"{self.log_prefix} 将在 {self.reconnect} 秒后重连...")

            def delayed_reconnect():
                import time

                attempt = 0

                try:
                    while self.enable:
                        attempt += 1
                        time.sleep(self.reconnect)

                        if not self.enable or (
                                self.ws_client and self.ws_client.is_connected()
                        ):
                            return

                        if attempt > 1:
                            self.logger.info(
                                f"{self.log_prefix} 尝试重连 (第 {attempt} 次)..."
                            )
                        else:
                            self.logger.info(f"{self.log_prefix} 开始重连...")

                        try:
                            self._connect_to_server()
                            return
                        except Exception as e:
                            self.logger.error(f"{self.log_prefix} 重连失败: {e}")
                finally:
                    self._is_reconnecting = False

            threading.Thread(
                target=delayed_reconnect,
                name=f"[GUGUBot]Reconnect_{self._client_id}",
                daemon=True,
            ).start()

    def _handle_server_message(self, client: Dict, server: Any, message: str) -> None:
        """处理服务器端接收到的消息"""
        try:
            message_data = json.loads(message) if isinstance(message, str) else message

            # 广播给其他客户端
            if self.ws_server and self.ws_server.get_client_count() > 1:
                message_data["bridge_source"] = client.get("address", ["unknown", 0])[0]
                sender_id = message_data.get("sender_id", None)
                message_data["is_admin"] = asyncio.run(self._is_admin(sender_id))

                for other_client in self.ws_server.get_clients():
                    if other_client["id"] != client["id"]:
                        self.ws_server.send_message(other_client, message_data)

            # 处理消息并传递给本地系统
            asyncio.run(self._process_bridge_message(message_data))

        except Exception as e:
            self.logger.error(f"{self.log_prefix} 消息处理失败: {e}")

    def _handle_client_message(self, ws, message: str) -> None:
        """处理客户端接收到的消息"""
        try:
            message_data = json.loads(message) if isinstance(message, str) else message

            if (
                    isinstance(message_data, dict)
                    and message_data.get("type") == "server_shutdown"
            ):
                return

            # 处理消息并传递给本地系统
            asyncio.run(self._process_bridge_message(message_data))

        except Exception as e:
            self.logger.error(f"{self.log_prefix} 消息处理失败: {e}")

    async def _process_bridge_message(self, message_data: Dict) -> None:
        """处理桥接消息"""
        try:
            target = message_data.get("target", {}) or {}
            if target and self.source not in target and len(target) == 1:
                return

            # 从消息数据中恢复 Source 对象
            source_data = message_data.get("source")
            source = Source.from_any(source_data)
            # 添加当前 connector 作为接收来源
            source.add(self.source)

            processed_info = BroadcastInfo(
                event_type="message",
                event_sub_type=message_data.get("event_sub_type", "group"),
                message=message_data.get("processed_message", []),
                sender=message_data.get("sender", "System"),
                sender_id=message_data.get("sender_id", None),
                _source=source,
                source_id=message_data.get("source_id", ""),
                raw=message_data.get("raw", message_data),
                server=self.server,
                logger=self.logger,
                is_admin=(
                    message_data.get("is_admin")
                    if message_data.get("is_admin") is not None
                    else await self._is_admin(message_data.get("sender_id"))
                ),
                target=target,
            )

            await self.parser(self).system_manager.broadcast_command(processed_info)

        except Exception as e:
            self.logger.error(f"{self.log_prefix} 处理桥接消息失败: {e}")

    async def send_message(self, processed_info: ProcessedInfo) -> None:
        """发送消息"""
        if not self.enable:
            return

        # 将 Source 序列化为列表以便通过 WebSocket 传输
        source_list = processed_info.source.to_list() if processed_info.source else []

        message_data = {
            "sender": processed_info.sender or "System",
            "sender_id": processed_info.sender_id,
            "event_sub_type": processed_info.event_sub_type,
            "receiver": processed_info.receiver,
            "source": source_list,  # 使用列表格式传输完整的来源链
            "source_id": processed_info.source_id,
            "raw": processed_info.raw,
            "processed_message": processed_info.processed_message,
            "target": processed_info.target,
            "is_admin": await self._is_admin(processed_info.sender_id) if self.is_main_server else None,
        }

        if self.is_main_server:
            # 服务器模式：广播给所有连接的客户端
            if self.ws_server and self.ws_server.is_running():
                count = self.ws_server.broadcast(message_data)
                self.logger.debug(f"{self.log_prefix} 广播消息给 {count} 个客户端")
        else:
            # 客户端模式：发送给服务器
            if self.ws_client and self.ws_client.is_connected():
                if self.ws_client.send(message_data):
                    self.logger.debug(f"{self.log_prefix} 发送消息到服务器")
                else:
                    self.logger.warning(f"{self.log_prefix} 发送消息失败")

    async def disconnect(self) -> None:
        """断开连接"""
        try:
            self.enable = False

            if self.is_main_server:
                if self.ws_server and self.ws_server.is_running():
                    self.ws_server.stop()
            else:
                if self.ws_client:
                    self.ws_client.disconnect()

            self.logger.info(f"{self.log_prefix} 已断开 ~")
        except Exception as e:
            self.logger.warning(f"{self.log_prefix} 断开连接时出错: {e}")

    async def on_message(self, raw: Any) -> BroadcastInfo:
        """处理接收到的消息"""
        if not self.enable:
            return None

        if self.parser:
            return await self.parser(self).parse(raw)
        return None

    async def _is_admin(self, sender_id) -> bool:
        """检查是否是管理员"""
        bound_system = self.connector_manager.system_manager.get_system("bound")

        if not bound_system:
            return False

        player_manager = bound_system.player_manager
        return await player_manager.is_admin(sender_id)
