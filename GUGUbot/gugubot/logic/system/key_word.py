# -*- coding: utf-8 -*-
import asyncio
import copy
import hashlib
from pathlib import Path
from typing import Dict, Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import McMessageBuilder, MessageBuilder
from gugubot.config import BasicConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo, ProcessedInfo


class KeyWordSystem(BasicConfig, BasicSystem):
    """关键词系统，用于管理和响应关键词。

    提供添加、删除、显示关键词，以及添加图片回复等功能。
    """

    def __init__(self, server: PluginServerInterface, config=None) -> None:
        """初始化关键词系统。"""
        BasicSystem.__init__(self, "key_words", enable=True, config=config)
        data_path = Path(server.get_data_folder()) / "system" / "key_words.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, data_path)
        self.adding_request_dict: Dict[str, str] = {}
        self.image_cache_dir = data_path.parent / "key_words_images"
        self.image_cache_dir.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        """初始化系统，加载配置等"""
        # 从配置文件加载关键词
        self.load()
        self.logger.debug(f"已加载 {len(self)} 个关键词")

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的命令。

        Parameters
        ----------
        broadcast_info: BroadcastInfo
            广播信息，包含消息内容
        """
        if broadcast_info.event_type != "message":
            return False

        message = broadcast_info.message

        if not message:
            return False

        first_message = message[0]
        ACCEPTABLE_TYPES = ["text", "image"]

        if first_message.get("type") not in ACCEPTABLE_TYPES:
            return False

        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        return await self._handle_msg(broadcast_info)

    async def _handle_msg(self, broadcast_info: BroadcastInfo) -> bool:
        """处理消息"""
        content = broadcast_info.message[0].get("data", {}).get("text", "")

        if not self.enable:
            return False

        if self.is_command(broadcast_info):
            return await self._handle_command(broadcast_info)

        if broadcast_info.sender_id in self.adding_request_dict:
            command = self.adding_request_dict[broadcast_info.sender_id]
            del self.adding_request_dict[broadcast_info.sender_id]
            cache_image = self.config.get_keys(
                ["system", "key_words", "cache_image"], False
            )
            if cache_image:
                message = await self._cache_images(
                    copy.deepcopy(broadcast_info.message)
                )
            else:
                message = broadcast_info.message
            self[command] = message
            self.save()
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_success"))]
            )
            return True

        if content in self:
            # 与 echo 一致：来源 connector enable_send=False 则不转发到任何其他渠道
            source_name = broadcast_info.receiver_source or broadcast_info.source.origin
            source_connector = self.system_manager.connector_manager.get_connector(source_name)
            if source_connector is not None and not source_connector.enable_send:
                return False

            # 是否转发到其他连接器
            forward_to_other = self.config.get_keys(
                ["system", "key_words", "forward_to_other_connector"], True
            )

            if forward_to_other:
                original_processed_info = self.create_processed_info(broadcast_info)

                # 排除来源、enable_receive=False（不接收转发的端）；enable_send 已在上方按来源判断
                exclude_source = source_name
                exclude_for_echo = [exclude_source]
                exclude_receive_only = [
                    c.source for c in self.system_manager.connector_manager.connectors
                    if not c.enable_receive
                ]
                exclude_for_echo.extend(exclude_receive_only)

                # 原文转发：排除来源 + 未开启的 connector
                await self.system_manager.connector_manager.broadcast_processed_info(
                    original_processed_info, exclude=exclude_for_echo
                )

            # 关键词回复：reply 只发到当前触发的群/会话，避免 QQ 多群时发到别的群
            await self.reply(broadcast_info, self[content])

            if forward_to_other:
                # 再广播到其他 connector（MC、bridge 等），排除来源端和未开启的 connector
                keyword_processed_info = ProcessedInfo(
                    processed_message=self[content],
                    _source=broadcast_info.source,
                    source_id=broadcast_info.source_id,
                    sender=self.get_tr("gugubot.bot_name", global_key=True),
                    raw=broadcast_info.raw,
                    server=broadcast_info.server,
                    logger=broadcast_info.logger,
                    event_sub_type=broadcast_info.event_sub_type,
                )
                await self.system_manager.connector_manager.broadcast_processed_info(
                    keyword_processed_info, exclude=exclude_for_echo
                )

            return True

        return False

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        valid_commands = [
            system_name,
            self.get_tr("add"),
            self.get_tr("remove"),
            self.get_tr("list"),
            self.get_tr("cancel"),
        ]
        if not any(command.startswith(i) for i in valid_commands):
            return False

        # 检查是否仅管理员可用
        admin_only = self.config.get_keys(["system", "key_words", "admin_only"], False)
        if admin_only and not broadcast_info.is_admin:
            return False

        command = command.replace(system_name, "", 1).strip()

        if command.startswith(self.get_tr("add")):
            return await self._handle_add(broadcast_info)
        elif command.startswith(self.get_tr("remove")):
            return await self._handle_remove(broadcast_info)
        elif command.startswith(self.get_tr("list")):
            return await self._handle_list(broadcast_info)
        elif command.startswith(self.get_tr("cancel")):
            return await self._handle_cancel(broadcast_info)

        return await self._handle_help(broadcast_info)

    async def _handle_add(self, broadcast_info: BroadcastInfo) -> bool:
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_command = self.get_tr("add")

        for i in [command_prefix, system_name, add_command]:
            command = command.replace(i, "", 1).strip()

        if command in self:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_existed"))]
            )
            return True

        self.adding_request_dict[broadcast_info.sender_id] = command
        self._add_task_timeout(broadcast_info.sender_id, broadcast_info)
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("add_instruction"))]
        )

        return True

    def _add_task_timeout(self, sender_id: str, broadcast_info: BroadcastInfo):
        """任务超时回调函数"""
        max_add_time = (
            self.config.get("system", {}).get("key_words", {}).get("max_add_time", 30)
        )

        async def task():
            if sender_id not in self.adding_request_dict:
                return

            await asyncio.sleep(max_add_time)
            if sender_id in self.adding_request_dict:
                command = self.adding_request_dict[sender_id]
                del self.adding_request_dict[sender_id]
                await self.reply(
                    broadcast_info,
                    [MessageBuilder.text(self.get_tr("add_timeout", command=command))],
                )

        self.system_manager.server.schedule_task(task)

    def _download_image(self, url: str) -> Optional[Path]:
        """下载图片并返回本地缓存路径（同步，在线程池中运行）。"""
        import requests as req

        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            response = req.get(url, timeout=15)
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "jpeg" in content_type or "jpg" in content_type:
                ext = ".jpg"
            elif "gif" in content_type:
                ext = ".gif"
            elif "webp" in content_type:
                ext = ".webp"
            else:
                ext = ".png"

            filepath = (self.image_cache_dir / f"{url_hash}{ext}").resolve()
            filepath.write_bytes(response.content)
            return filepath
        except Exception as e:
            self.logger.warning(f"缓存图片失败: {e}")
            return None

    async def _cache_images(self, message: list) -> list:
        """下载并缓存消息中的图片，将 url 替换为本地文件路径。"""
        loop = asyncio.get_running_loop()
        for segment in message:
            if segment.get("type") not in ("image", "mface"):
                continue
            data = segment.get("data", {})
            # 优先取 url，其次取 file（部分框架把链接放在 file 里）
            download_url = data.get("url", "")
            if not download_url or not download_url.startswith("http"):
                download_url = data.get("file", "")
                if not download_url or not download_url.startswith("http"):
                    continue

            filepath = await loop.run_in_executor(
                None, self._download_image, download_url
            )
            if filepath:
                data["file"] = str(filepath)
                # 移除即将过期的 url，保留原始地址供调试
                if "url" in data:
                    data["original_url"] = data.pop("url")
        return message

    def _cleanup_cached_images(self, message: list) -> None:
        """清理关键词关联的缓存图片文件。"""
        if not isinstance(message, list):
            return
        for segment in message:
            if not isinstance(segment, dict):
                continue
            if segment.get("type") not in ("image", "mface"):
                continue
            filepath_str = segment.get("data", {}).get("file", "")
            if not filepath_str:
                continue
            filepath = Path(filepath_str)
            try:
                if filepath.parent.resolve() == self.image_cache_dir.resolve():
                    filepath.unlink(missing_ok=True)
            except Exception:
                pass

    async def _handle_remove(self, broadcast_info: BroadcastInfo) -> bool:
        """处理删除关键词命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        remove_command = self.get_tr("remove")

        for i in [command_prefix, system_name, remove_command]:
            command = command.replace(i, "", 1).strip()

        if command not in self:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_not_exist"))]
            )
            return True

        cache_image = self.config.get_keys(
            ["system", "key_words", "cache_image"], False
        )
        if cache_image:
            self._cleanup_cached_images(self[command])
        del self[command]
        self.save()
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("remove_success"))]
        )
        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理显示关键词列表命令"""

        if len(self) == 0:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
            )
            return True

        keyword_list = []
        for k, v in self.items():
            keyword_list.append(f"{k}: {McMessageBuilder.array_to_RText(v)}")
        keyword_list = "\n".join(keyword_list)
        await self.reply(
            broadcast_info,
            [
                MessageBuilder.text(
                    self.get_tr("keyword_list", keyword_list=keyword_list)
                )
            ],
        )
        return True

    async def _handle_cancel(self, broadcast_info: BroadcastInfo) -> bool:
        """处理取消添加图片命令"""
        sender_id = broadcast_info.sender_id

        if sender_id not in self.adding_request_dict:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("cancel_not_exist"))]
            )
            return True

        del self.adding_request_dict[sender_id]
        await self.reply(
            broadcast_info, [MessageBuilder.text(self.get_tr("cancel_success"))]
        )
        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """关键词指令帮助"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_cmd = self.get_tr("add")
        remove_cmd = self.get_tr("remove")
        list_cmd = self.get_tr("list")
        cancel_cmd = self.get_tr("cancel")

        # 根据用户权限选择不同的帮助信息
        if broadcast_info.is_admin:
            enable_cmd = self.get_tr("gugubot.enable", global_key=True)
            disable_cmd = self.get_tr("gugubot.disable", global_key=True)
            help_msg = self.get_tr(
                "help_msg",
                command_prefix=command_prefix,
                name=system_name,
                enable=enable_cmd,
                disable=disable_cmd,
                add=add_cmd,
                remove=remove_cmd,
                list=list_cmd,
                cancel=cancel_cmd,
            )
        else:
            help_msg = self.get_tr(
                "user_help_msg",
                command_prefix=command_prefix,
                name=system_name,
                add=add_cmd,
                remove=remove_cmd,
                list=list_cmd,
                cancel=cancel_cmd,
            )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True
