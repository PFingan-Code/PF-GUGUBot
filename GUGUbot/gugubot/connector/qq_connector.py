"""QQ WebSocket connector."""

import asyncio
import json
import random
import re
import time
import traceback
import uuid
from typing import Any, Optional

from gugubot.builder import CQHandler
from gugubot.config import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.parser.qq_parser import QQParser
from gugubot.utils.types import ProcessedInfo
from gugubot.ws import WebSocketFactory


def strip_minecraft_color_codes(text: str) -> str:
    """Strip Minecraft colour / formatting codes (e.g. ``§a``, ``§l``).

    Parameters
    ----------
    text : str
        Text that may contain Minecraft colour codes.

    Returns
    -------
    str
        The text with all colour codes removed.
    """
    return re.sub(r"§[0-9a-fk-or]", "", text, flags=re.IGNORECASE)


class Bot:
    """OneBot API client."""

    def __init__(self, send_message, max_wait_time: int = 9) -> None:
        self.send_message = send_message
        self.max_wait_time = max_wait_time if 0 < max_wait_time <= 9 else 9
        self.function_return = {}
        self.pending_requests = {}
        self.self_id = None  # bot's own QQ ID

    @staticmethod
    def format_request(action: str, params: dict = None):
        """Format a request for the OneBot API."""
        if params is None:
            params = {}
        return {"action": action, "params": params, "echo": params.get("echo", "")}

    def _cleanup_pending_requests(self) -> None:
        now = time.time()
        stale_keys = [
            k
            for k, t in self.pending_requests.items()
            if now - t > self.max_wait_time + 5
        ]
        for k in stale_keys:
            if k in self.function_return:
                del self.function_return[k]
            if k in self.pending_requests:
                del self.pending_requests[k]

    def __getattr__(self, name):
        if (
            name.startswith("get_")
            or name.startswith("can_")
            or name.startswith("_get")
        ):

            async def handler(**kwargs):
                # For methods that are expected to return a value,
                # automatically add an echo id to track the response.

                self._cleanup_pending_requests()
                function_return_id = str(uuid.uuid4())
                kwargs["echo"] = function_return_id
                command_request = self.format_request(name, kwargs)
                await self.send_message(command_request)

                start_time = time.time()
                self.pending_requests[function_return_id] = start_time

                try:
                    while True:
                        if function_return_id in self.function_return:
                            return self.function_return[function_return_id]

                        await asyncio.sleep(0.2)
                        if time.time() - start_time >= self.max_wait_time:
                            return None
                finally:
                    self.function_return.pop(function_return_id, None)
                    self.pending_requests.pop(function_return_id, None)

        else:

            async def handler(**kwargs):
                command_request = self.format_request(name, kwargs)
                await self.send_message(command_request)

        return handler


class QQWebSocketConnector(BasicConnector):
    """QQ WebSocket connector."""

    def __init__(self, server, config: Optional[BotConfig] = None):
        source_name = config.get_keys(["connector", "QQ", "source_name"], "QQ")
        super().__init__(
            source=source_name, parser=QQParser, server=server, config=config
        )
        self.ws_client = None

        connector_basic_name = self.server.tr("gugubot.connector.name")
        self.log_prefix = f"[{connector_basic_name}{self.source}]"

        # determine scheme using single parameter 'use_ssl' (boolean)
        self.use_ssl = config.get_keys(
            ["connector", "QQ", "connection", "use_ssl"], False
        )
        self.scheme = "wss" if self.use_ssl else "ws"
        self.url = self._build_url(config)

        self.token = config.get_keys(["connector", "QQ", "connection", "token"], None)
        self.reconnect = config.get_keys(
            ["connector", "QQ", "connection", "reconnect"], 5
        )
        self.ping_interval = config.get_keys(
            ["connector", "QQ", "connection", "ping_interval"], 20
        )
        self.ping_timeout = config.get_keys(
            ["connector", "QQ", "connection", "ping_timeout"], 10
        )
        self.verify = config.get_keys(["connector", "QQ", "connection", "verify"], True)
        self.ca_certs = config.get_keys(
            ["connector", "QQ", "connection", "ca_certs"], None
        )
        self.extra_sslopt = config.get_keys(
            ["connector", "QQ", "connection", "sslopt"], {}
        )

        self.bot = Bot(
            self._send_message,
            max_wait_time=config.get_keys(
                ["connector", "QQ", "connection", "max_wait_time"], 5
            ),
        )

    def _build_url(self, config):
        host = config.get_keys(["connector", "QQ", "connection", "host"], "127.0.0.1")
        port = config.get_keys(["connector", "QQ", "connection", "port"], 8080)
        post_path = config.get_keys(["connector", "QQ", "connection", "post_path"], "")
        url = f"{self.scheme}://{host}:{port}"
        if post_path:
            url += f"/{post_path}"

        return url

    async def connect(self) -> None:
        """Establish the WebSocket connection to the QQ (OneBot) server."""
        self.logger.info(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.try_connect', url=self.url)}"
        )

        self.ws_client = WebSocketFactory.create_client(
            url=self.url,
            token=self.token,
            on_message=self._on_ws_message,
            on_open=self._on_open,
            on_error=self._on_error,
            on_close=self._on_close,
            logger=self.logger,
        )

        # Disable ping/pong; the OneBot server does not require it.
        self.ws_client.connect(
            reconnect=self.reconnect,
            ping_interval=0,
            ping_timeout=0,
            use_ssl=self.use_ssl,
            verify=self.verify,
            ca_certs=self.ca_certs,
            extra_sslopt=self.extra_sslopt,
            thread_name="[GUGUBot]QQ_Connector",
        )

        self.logger.info(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.start_connect')}"
        )

    def _on_open(self, _):
        self.logger.info(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.connect_success')}"
        )

    def _on_error(self, _: Any, error: Exception) -> None:
        """Handle a WebSocket error.

        Parameters
        ----------
        _ : Any
            WebSocket instance (unused).
        error : Exception
            The error that occurred.
        """
        self.logger.error(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.error_connect', error=error)}"
        )

    def _on_close(
        self, _: Any, status_code: Optional[int], reason: Optional[str]
    ) -> None:
        """Handle WebSocket connection close.

        Parameters
        ----------
        _ : Any
            WebSocket instance (unused).
        status_code : int or None
            The close status code.
        reason : str or None
            The close reason.
        """
        close_info = self.server.tr(
            "gugubot.connector.QQ.close_connect", status_code=status_code, reason=reason
        )
        self.logger.debug(f"{self.log_prefix} {close_info}")

    async def _send_message(self, message: Any) -> None:
        """Send a raw message through the WebSocket connection."""
        if self.ws_client and self.ws_client.is_connected():
            if self.ws_client.send(message):
                self.logger.debug(
                    self.server.tr("gugubot.connector.QQ.send_message", message=message)
                )
            else:
                self.logger.error(
                    self.server.tr(
                        "gugubot.connector.QQ.send_message_failed", error="发送失败"
                    )
                )
        else:
            self.logger.warning(self.server.tr("gugubot.connector.QQ.retry_connect"))

    def _strip_color_codes_from_message(self, message: list) -> list:
        """Strip Minecraft colour codes from text segments in a message list.

        Parameters
        ----------
        message : list
            Message segment list; each element is a dict with ``type`` and
            ``data`` keys.

        Returns
        -------
        list
            A new list with colour codes removed from ``text`` segments.
        """
        result = []
        for item in message:
            if isinstance(item, dict) and item.get("type") == "text":
                new_item = item.copy()
                new_data = item.get("data", {}).copy()
                if "text" in new_data:
                    new_data["text"] = strip_minecraft_color_codes(new_data["text"])
                new_item["data"] = new_data
                result.append(new_item)
            else:
                result.append(item)
        return result

    # Estimated lengths for non-text segment types
    _TYPE_LENGTHS = {"image": 100, "default": 20}

    def _get_item_length(self, item: dict) -> int:
        """Return the estimated character length of a single message segment."""
        if item.get("type") == "text":
            return len(item.get("data", {}).get("text", ""))
        return self._TYPE_LENGTHS.get(item.get("type"), self._TYPE_LENGTHS["default"])

    def _split_message(self, message: list, max_length: int = 2000) -> list[list]:
        """Split a message into parts that each fit within *max_length*."""
        total = sum(self._get_item_length(m) for m in message if isinstance(m, dict))
        if total <= max_length:
            return [message]

        result, current_part, current_len = [], [], 0

        def flush():
            nonlocal current_part, current_len
            if current_part:
                result.append(current_part)
                current_part, current_len = [], 0

        for item in message:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "text":
                item_len = self._get_item_length(item)
                if current_len + item_len > max_length:
                    flush()
                current_part.append(item)
                current_len += item_len
                continue

            # Text segment — may need splitting across parts
            text = item.get("data", {}).get("text", "")
            while text:
                space = max_length - current_len
                if space <= 0:
                    flush()
                    space = max_length

                if len(text) <= space:
                    current_part.append({"type": "text", "data": {"text": text}})
                    current_len += len(text)
                    break

                # Prefer splitting at a newline boundary
                chunk = text[:space]
                if (pos := chunk.rfind("\n")) > space // 2:
                    chunk = text[: pos + 1]

                current_part.append({"type": "text", "data": {"text": chunk}})
                current_len += len(chunk)
                text = text[len(chunk) :]

        flush()
        return result

    async def send_message(self, processed_info: ProcessedInfo) -> None:
        if not self.enable:
            return

        # Prefer forward_group_ids; fall back to group_ids for backwards compat
        forward_group_ids = self.config.get_keys(
            ["connector", "QQ", "permissions", "forward_group_ids"], []
        )
        if not forward_group_ids or not any(forward_group_ids):
            forward_group_ids = self.config.get_keys(
                ["connector", "QQ", "permissions", "group_ids"], []
            )
        forward_group_target = {
            str(group_id): "group" for group_id in forward_group_ids if group_id
        }
        target = processed_info.target or forward_group_target

        message = processed_info.processed_message
        source = processed_info.source

        message = self._strip_color_codes_from_message(message)

        # Prepend a source prefix when the message originates outside QQ
        if not source.is_from("QQ") and source.origin and processed_info.sender:
            chat_templates = self.config.get_keys(
                ["connector", "QQ", "chat_templates"], []
            )

            # Pick a chat template (weighted random) or fall back to default
            if chat_templates and isinstance(chat_templates, list):
                if isinstance(chat_templates[0], dict):
                    # Format like: [{"template_string": weight}, ...]
                    templates = []
                    weights = []
                    for item in chat_templates:
                        for template_str, weight in item.items():
                            templates.append(template_str)
                            weights.append(
                                weight if isinstance(weight, (int, float)) else 1
                            )
                    # Weighted random selection
                    template = random.choices(templates, weights=weights, k=1)[0]
                else:
                    # Legacy format: auto-migrate to weighted dict format
                    new_templates = [{tmpl: 1} for tmpl in chat_templates]
                    self.config["connector"]["QQ"]["chat_templates"] = new_templates
                    self.config.save()
                    if self.logger:
                        self.logger.info(
                            "已自动将 chat_templates 从旧格式更新为新格式（默认权重为1）"
                        )
                    # Select from the (pre-migration) plain string list
                    template = random.choice(chat_templates)

                # {display_name} → source origin, {sender} → sender name
                formatted_text = template.format(
                    display_name=source.origin, sender=processed_info.sender
                )
            else:
                # Default format (backwards compatible)
                formatted_text = f"[{source.origin}] {processed_info.sender}: "

            source_message = CQHandler.parse(formatted_text)
            message = source_message + message

        # Join/leave messages have an empty sender — only show the source tag
        elif not source.is_from("QQ") and source.origin and processed_info.sender == "":
            message = CQHandler.parse(f"[{source.origin}] ") + message

        # Max message length before splitting (configurable, default 2000)
        max_message_length = self.config.get_keys(
            ["connector", "QQ", "max_message_length"], 2000
        )

        message_parts = self._split_message(message, max_length=max_message_length)

        for target_id, target_type in target.items():
            if not target_id.isdigit():
                continue

            for part in message_parts:
                if target_type == "group":
                    await self.bot.send_group_msg(group_id=int(target_id), message=part)
                elif target_type == "private":
                    await self.bot.send_private_msg(
                        user_id=int(target_id), message=part
                    )
                else:
                    await self.bot.send_temp_msg(
                        group_id=int(target_type), user_id=int(target_id), message=part
                    )

                # Throttle multi-part sends to avoid rate limiting
                if len(message_parts) > 1:
                    random_time = random.uniform(0.5, 1.5)
                    await asyncio.sleep(random_time)

    async def disconnect(self) -> None:
        """Disconnect from the QQ WebSocket server."""
        try:
            if self.ws_client:
                self.ws_client.disconnect(timeout=5)
            self.logger.info(
                f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.close_info')}"
            )
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            error_close_template = self.server.tr(
                "gugubot.connector.QQ.error_close", error=error_msg
            )
            self.logger.warning(f"{self.log_prefix} {error_close_template}")
            raise

    async def on_message(self, raw: Any) -> None:
        """Handle a raw incoming message (base-class interface).

        Delegates to :meth:`_on_ws_message` which contains the actual
        processing logic shared with the WebSocket callback.
        """
        self._on_ws_message(None, raw)

    def _on_ws_message(self, _, raw_message: str) -> None:
        """Dispatch an incoming WebSocket message.

        This method is used as the WebSocket ``on_message`` callback and
        is also called by :meth:`on_message`.

        Processing flow:

        1. Parse the raw JSON string.
        2. If it is an API response (contains ``echo``), store it in
           ``function_return`` for the waiting coroutine.
        3. Otherwise schedule the event for processing on the MCDR event
           loop.

        Parameters
        ----------
        raw_message : str
            JSON-encoded message received from the WebSocket.
        """
        if not self.enable:
            return

        try:

            # Fast path: handle API responses (echo) directly in this thread
            try:
                message_data = json.loads(raw_message)
                echo = message_data.get("echo")
                if echo:
                    if echo in self.bot.pending_requests:
                        # API response — store for the awaiting coroutine
                        self.bot.function_return[echo] = message_data
                    return
            except Exception:
                pass

            # Event messages are scheduled on the MCDR event loop
            self.server.schedule_task(self.parser(self).process_message(raw_message))

        except Exception as e:
            # Log with translation key and include the full traceback
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(
                self.server.tr(
                    "gugubot.connector.QQ.message_handle_failed", error=error_msg
                )
            )
