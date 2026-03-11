"""Bridge connector implementation for cross-server communication between Minecraft servers."""

import asyncio
import json
import time
import threading
from typing import Any, Dict, Optional

from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.parser.mc_parser import MCParser
from gugubot.utils.types import BroadcastInfo, ProcessedInfo, Source
from gugubot.ws import WebSocketFactory


class BridgeConnector(BasicConnector):
    """Bridge connector supporting both server and client modes.

    The operating mode is determined by the ``is_main_server`` config flag:

    * ``True`` -- start a WebSocket server and wait for other servers to
      connect.
    * ``False`` -- connect to the main server as a client.
    """

    def __init__(self, server, config: Optional[BotConfig] = None):
        source_name = config.get_keys(
            ["connector", "minecraft_bridge", "source_name"], "Bridge"
        )
        super().__init__(
            source=source_name, parser=MCParser, server=server, config=config
        )

        connector_basic_name = self.server.tr("gugubot.connector.name")
        self.log_prefix = f"[{connector_basic_name}{self.source}]"

        self._connect_count = 0
        self._client_id = f"{source_name}_{int(time.time() * 1000)}"
        self._is_reconnecting = False  # guards against concurrent reconnect threads

        self.is_main_server = config.get_keys(
            ["connector", "minecraft_bridge", "is_main_server"], True
        )

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

        self.ws_server = None
        self.ws_client = None

    async def connect(self) -> None:
        """Establish the bridge connection (server or client, per config)."""
        if self.is_main_server and self.enable:
            self._start_server()
        elif not self.is_main_server and self.enable:
            self._connect_to_server()

    def _start_server(self) -> None:
        """Start the WebSocket bridge server in a daemon thread."""
        self.logger.info(f"{self.log_prefix} 正在启动桥接服务器")

        self.ws_server = WebSocketFactory.create_bridge_server(
            self.config,
            on_message=self._handle_server_message,
            on_client_connect=self._on_client_connect,
            on_client_disconnect=self._on_client_disconnect,
            logger=self.logger,
        )

        self.ws_server.start(daemon=True)

        self.logger.info(f"{self.log_prefix} 桥接服务器就绪 ~")

    def _connect_to_server(self) -> None:
        """Connect to the main bridge server as a client."""
        if self.ws_client:
            try:
                if self.ws_client.is_connected():
                    self.ws_client.disconnect(timeout=1)
            except Exception:
                pass

        self._connect_count += 1

        if self._connect_count > 1:
            self.logger.info(
                f"{self.log_prefix} 正在重连桥接服务器 (第 {self._connect_count} 次连接)"
            )
        else:
            self.logger.info(f"{self.log_prefix} 正在连接到桥接服务器")

        self.ws_client = WebSocketFactory.create_bridge_client(
            self.config,
            on_message=self._handle_client_message,
            on_open=self._on_client_open,
            on_error=self._on_client_error,
            on_close=self._on_client_close,
            logger=self.logger,
        )

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

    def _on_client_connect(self, client: Dict, _: Any) -> None:
        """Handle a new client connecting to the bridge server."""
        client_address = client.get("address") if client else "unknown"
        client_count = self.ws_server.get_client_count() if self.ws_server else 0
        self.logger.info(
            f"{self.log_prefix} 新客户端连接: {client_address} (总数: {client_count})"
        )

    def _on_client_disconnect(self, client: Dict, _: Any) -> None:
        """Handle a client disconnecting from the bridge server."""
        client_address = client.get("address") if client else "unknown"
        client_count = self.ws_server.get_client_count() if self.ws_server else 0
        self.logger.info(
            f"{self.log_prefix} 客户端断开: {client_address} (剩余: {client_count})"
        )

    def _on_client_open(self, _: Any) -> None:
        """Handle the client WebSocket connection being established."""
        self.logger.info(f"{self.log_prefix} 连接成功 ~")

    def _on_client_error(self, _: Any, error: Exception) -> None:
        """Handle a client WebSocket connection error."""
        self.logger.error(
            f"{self.log_prefix} 连接错误: {type(error).__name__} - {error}"
        )

    def _on_client_close(self, ws, _: int, reason: str) -> None:
        """Handle the client WebSocket connection closing; schedule reconnect."""

        # Ignore stale close events from previous connections
        if self.ws_client and self.ws_client.ws and self.ws_client.ws != ws:
            return

        reason_text = f"({reason})" if reason else ""
        self.logger.info(f"{self.log_prefix} 连接已断开 {reason_text}")

        # Schedule a persistent reconnect loop in a background thread
        if self.reconnect > 0 and self.enable and not self._is_reconnecting:
            self._is_reconnecting = True
            self.logger.info(f"{self.log_prefix} 将在 {self.reconnect} 秒后重连...")

            def delayed_reconnect():
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

    def _handle_server_message(self, client: Dict, _: Any, message: str) -> None:
        """Process a message received on the server side and relay it."""
        try:
            message_data = json.loads(message) if isinstance(message, str) else message

            # Relay to other connected clients
            if self.ws_server and self.ws_server.get_client_count() > 1:
                message_data["bridge_source"] = client.get("address", ["unknown", 0])[0]
                sender_id = message_data.get("sender_id", None)
                message_data["is_admin"] = asyncio.run(self._is_admin(sender_id))

                for other_client in self.ws_server.get_clients():
                    if other_client["id"] != client["id"]:
                        self.ws_server.send_message(other_client, message_data)

            asyncio.run(self._process_bridge_message(message_data))

        except Exception as e:
            self.logger.error(f"{self.log_prefix} 消息处理失败: {e}")

    def _handle_client_message(self, _: Any, message: str) -> None:
        """Process a message received on the client side."""
        try:
            message_data = json.loads(message) if isinstance(message, str) else message

            if (
                isinstance(message_data, dict)
                and message_data.get("type") == "server_shutdown"
            ):
                return

            asyncio.run(self._process_bridge_message(message_data))

        except Exception as e:
            self.logger.error(f"{self.log_prefix} 消息处理失败: {e}")

    async def _process_bridge_message(self, message_data: Dict) -> None:
        """Reconstruct a ``BroadcastInfo`` from bridge data and dispatch it."""
        try:
            target = message_data.get("target", {}) or {}
            if target and self.source not in target and len(target) == 1:
                return

            source_data = message_data.get("source")
            source = Source.from_any(source_data)
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
        """Serialize and send a message over the bridge."""
        if not self.enable:
            return

        # Serialize Source as a list for WebSocket transport
        source_list = processed_info.source.to_list() if processed_info.source else []

        message_data = {
            "sender": processed_info.sender
            or self.config.get_keys(
                ["connector", "minecraft_bridge", "source_name"], "System"
            ),
            "sender_id": processed_info.sender_id,
            "event_sub_type": processed_info.event_sub_type,
            "receiver": processed_info.receiver,
            "source": source_list,
            "source_id": processed_info.source_id,
            "raw": processed_info.raw,
            "processed_message": processed_info.processed_message,
            "target": processed_info.target,
            "is_admin": (
                await self._is_admin(processed_info.sender_id)
                if self.is_main_server
                else None
            ),
        }

        if self.is_main_server:
            # Server mode: broadcast to all connected clients
            if self.ws_server and self.ws_server.is_running():
                count = self.ws_server.broadcast(message_data)
                self.logger.debug(f"{self.log_prefix} 广播消息给 {count} 个客户端")
        else:
            # Client mode: send to the server
            if self.ws_client and self.ws_client.is_connected():
                if self.ws_client.send(message_data):
                    self.logger.debug(f"{self.log_prefix} 发送消息到服务器")
                else:
                    self.logger.warning(f"{self.log_prefix} 发送消息失败")

    async def disconnect(self) -> None:
        """Disconnect the bridge (server or client)."""
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

    async def on_message(self, raw: Any) -> None:
        """Handle an incoming raw message via the parser."""
        if not self.enable:
            return None

        if self.parser:
            return await self.parser(self).parse(raw)
        return None

    async def _is_admin(self, sender_id) -> bool:
        """Return whether *sender_id* is an admin."""
        bound_system = self.connector_manager.system_manager.get_system("bound")

        if not bound_system:
            return False

        player_manager = bound_system.player_manager
        return await player_manager.is_admin(sender_id)
