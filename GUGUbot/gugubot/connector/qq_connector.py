import asyncio
import random
import re
import time
import traceback
import uuid
from typing import Any, Optional

from gugubot.builder.qq_builder import CQHandler
from gugubot.config.BotConfig import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.parser.qq_parser import QQParser
from gugubot.utils.types import ProcessedInfo
from gugubot.ws import WebSocketFactory


def strip_minecraft_color_codes(text: str) -> str:
    """去除 Minecraft 颜色/格式代码（如 §a, §l, §r 等）

    Parameters
    ----------
    text : str
        可能包含 Minecraft 颜色代码的文本

    Returns
    -------
    str
        去除颜色代码后的文本
    """
    return re.sub(r"§[0-9a-fk-or]", "", text, flags=re.IGNORECASE)


class Bot:
    def __init__(self, send_message, max_wait_time: int = 9) -> None:
        self.send_message = send_message
        self.max_wait_time = max_wait_time if 0 < max_wait_time <= 9 else 9
        self.function_return = {}
        self.self_id = None  # 机器人自己的QQ号

    @staticmethod
    def format_request(action: str, params: dict = {}):
        return {"action": action, "params": params, "echo": params.get("echo", "")}

    def __getattr__(self, name):
        if (
                name.startswith("get_")
                or name.startswith("can_")
                or name.startswith("_get")
        ):

            async def handler(**kwargs):
                # For methods that are expected to return a value,
                # automatically add an echo id to track the response.

                function_return_id = str(uuid.uuid4())
                kwargs["echo"] = function_return_id
                command_request = self.format_request(name, kwargs)
                await self.send_message(command_request)

                start_time = time.time()
                import asyncio

                while True:
                    if function_return_id in self.function_return:
                        result = self.function_return[function_return_id]
                        del self.function_return[function_return_id]
                        return result

                    await asyncio.sleep(0.2)
                    if time.time() - start_time >= self.max_wait_time:
                        return None

        else:

            async def handler(**kwargs):
                command_request = self.format_request(name, kwargs)
                await self.send_message(command_request)

        return handler


class QQWebSocketConnector(BasicConnector):
    def __init__(self, server, config: BotConfig = None):
        source_name = config.get_keys(["connector", "QQ", "source_name"], "QQ")
        super().__init__(source=source_name, parser=QQParser, config=config)
        self.server = server
        self.ws_client = None

        # 存储日志前缀
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
        """建立到QQ WebSocket服务器的连接"""
        self.logger.info(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.try_connect', url=self.url)}"
        )

        # 使用WebSocketFactory创建客户端
        self.ws_client = WebSocketFactory.create_client(
            url=self.url,
            token=self.token,
            on_message=self.on_message,
            on_open=self._on_open,
            on_error=self._on_error,
            on_close=self._on_close,
            logger=self.logger,
        )

        # 连接到服务器（禁用 pingpong）
        self.ws_client.connect(
            reconnect=self.reconnect,
            ping_interval=0,  # 禁用 pingpong
            ping_timeout=0,  # 禁用 pingpong
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
        """处理WebSocket错误

        Parameters
        ----------
        _ : Any
            WebSocket实例（未使用）
        error : Exception
            发生的错误
        """
        self.logger.error(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.error_connect', error=error)}"
        )

    def _on_close(
            self, _: Any, status_code: Optional[int], reason: Optional[str]
    ) -> None:
        """处理WebSocket连接关闭

        Parameters
        ----------
        _ : Any
            WebSocket实例（未使用）
        status_code : Optional[int]
            关闭状态码
        reason : Optional[str]
            关闭原因
        """
        self.logger.debug(
            f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.close_connect', status_code=status_code, reason=reason)}"
        )

    async def _send_message(self, message: Any) -> None:
        """向QQ WebSocket服务器发送消息"""
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
        """去除消息列表中的 Minecraft 颜色代码

        Parameters
        ----------
        message : list
            消息列表，每个元素是包含 'type' 和 'data' 的字典

        Returns
        -------
        list
            处理后的消息列表
        """
        result = []
        for item in message:
            if isinstance(item, dict) and item.get("type") == "text":
                # 复制 item 以避免修改原始数据
                new_item = item.copy()
                new_data = item.get("data", {}).copy()
                if "text" in new_data:
                    new_data["text"] = strip_minecraft_color_codes(new_data["text"])
                new_item["data"] = new_data
                result.append(new_item)
            else:
                result.append(item)
        return result

    # 非文本消息类型的虚拟长度
    _TYPE_LENGTHS = {"image": 100, "default": 20}

    def _get_item_length(self, item: dict) -> int:
        """获取单个消息元素的长度"""
        if item.get("type") == "text":
            return len(item.get("data", {}).get("text", ""))
        return self._TYPE_LENGTHS.get(item.get("type"), self._TYPE_LENGTHS["default"])

    def _split_message(self, message: list, max_length: int = 2000) -> list[list]:
        """将消息分割成多个部分，每部分不超过指定长度"""
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

            # 处理文本：可能需要拆分
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

                # 优先在换行符处分割
                chunk = text[:space]
                if (pos := chunk.rfind('\n')) > space // 2:
                    chunk = text[:pos + 1]

                current_part.append({"type": "text", "data": {"text": chunk}})
                current_len += len(chunk)
                text = text[len(chunk):]

        flush()
        return result

    async def send_message(self, processed_info: ProcessedInfo) -> None:
        if not self.enable:
            return

        # 优先使用 forward_group_ids，如果未配置则回退到 group_ids（保持向后兼容）
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
        source = processed_info.source  # Source 对象
        source_id = processed_info.source_id

        # 去除消息中的 Minecraft 颜色代码
        message = self._strip_color_codes_from_message(message)

        # 检查原始来源是否不是 QQ（需要添加来源前缀）
        if not source.is_from("QQ") and source.origin and processed_info.sender:
            # 从config中获取聊天模板列表
            chat_templates = self.config.get_keys(
                ["connector", "QQ", "chat_templates"], []
            )

            # 如果配置了模板，根据权重随机选择一个；否则使用默认格式
            if (
                    chat_templates
                    and isinstance(chat_templates, list)
                    and len(chat_templates) > 0
            ):
                # 检查是否为字典格式（带权重）
                if isinstance(chat_templates[0], dict):
                    # 字典格式: {"模板字符串": 权重值}
                    templates = []
                    weights = []
                    for item in chat_templates:
                        for template_str, weight in item.items():
                            templates.append(template_str)
                            weights.append(
                                weight if isinstance(weight, (int, float)) else 1
                            )
                    # 使用权重随机选择
                    template = random.choices(templates, weights=weights, k=1)[0]
                else:
                    # 旧格式：转换为新格式并保存
                    new_templates = [{tmpl: 1} for tmpl in chat_templates]
                    self.config["connector"]["QQ"]["chat_templates"] = new_templates
                    self.config.save()  # 手动保存配置
                    if self.logger:
                        self.logger.info(
                            "已自动将 chat_templates 从旧格式更新为新格式（默认权重为1）"
                        )
                    # 从转换后的新格式中随机选择
                    template = random.choice(chat_templates)

                # 使用模板格式化消息，{display_name}对应source，{sender}对应processed_info.sender
                formatted_text = template.format(
                    display_name=source.origin, sender=processed_info.sender
                )
            else:
                # 默认格式（向后兼容）
                formatted_text = f"[{source.origin}] {processed_info.sender}: "

            source_message = CQHandler.parse(formatted_text)
            message = source_message + message

        # 如果是玩家进出服务器消息，不显示发送者
        elif not source.is_from("QQ") and source.origin and processed_info.sender == "":
            message = CQHandler.parse(f"[{source.origin}] ") + message

        # 获取消息最大长度配置，默认为 2000
        max_message_length = self.config.get_keys(
            ["connector", "QQ", "max_message_length"], 2000
        )

        # 分割消息（如果太长）
        message_parts = self._split_message(message, max_length=max_message_length)

        for target_id, target_type in target.items():

            if not target_id.isdigit():
                continue

            for part in message_parts:
                if target_type == "group":
                    await self.bot.send_group_msg(group_id=int(target_id), message=part)
                elif target_type == "private":
                    await self.bot.send_private_msg(user_id=int(target_id), message=part)
                else:
                    await self.bot.send_temp_msg(
                        group_id=int(target_type), user_id=int(target_id), message=part
                    )

                # 如果消息被分割成多段，每段之间稍微延迟，避免发送过快
                if len(message_parts) > 1:
                    random_time = random.uniform(0.5, 1.5)
                    await asyncio.sleep(random_time)

    async def disconnect(self) -> None:
        """断开与QQ WebSocket服务器的连接"""
        try:
            if self.ws_client:
                self.ws_client.disconnect(timeout=5)
            self.logger.info(
                f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.close_info')}"
            )
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.warning(
                f"{self.log_prefix} {self.server.tr('gugubot.connector.QQ.error_close', error=error_msg)}"
            )
            raise

    def on_message(self, _, raw_message: str) -> None:
        """处理并分发WebSocket消息。

        处理流程:
        1. 将原始JSON字符串解析为消息数据
        2. 如果是回调消息（包含echo），存储到function_return
        3. 如果是事件消息：
           - 更新机器人ID（如果包含）
           - 创建并处理QQ信息对象

        Parameters
        ----------
        raw_message : str
            WebSocket接收到的JSON格式消息

        注意:
            WebSocket 回调运行在独立线程中，需要将异步任务正确调度到事件循环
        """
        if not self.enable:
            return

        try:
            import json

            # 先快速检查是否是 API 响应（echo），直接在当前线程处理
            try:
                message_data = json.loads(raw_message)
                echo = message_data.get("echo")
                if echo:
                    # API 响应，直接存储到 function_return（线程安全）
                    self.bot.function_return[echo] = message_data
                    return
            except:
                pass

            # 对于事件消息，调度到 MCDR 主线程的事件循环
            # 使用 server.schedule_task 确保在正确的事件循环中执行
            self.server.schedule_task(self.parser(self).process_message(raw_message))

        except Exception as e:
            # 使用翻译条目并包含堆栈信息
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(
                self.server.tr(
                    "gugubot.connector.QQ.message_handle_failed", error=error_msg
                )
            )
