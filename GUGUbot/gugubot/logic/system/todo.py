# -*- coding: utf-8 -*-
from datetime import datetime
from pathlib import Path
from typing import Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config import BasicConfig
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class TodoSystem(BasicConfig, BasicSystem):
    """待办系统，用于管理待办事项。

    提供添加、删除、查询待办事项等功能。
    """

    def __init__(
            self, server: PluginServerInterface, config: Optional[BotConfig] = None
    ) -> None:
        """初始化待办系统。"""
        BasicSystem.__init__(self, "todo", enable=True, config=config)
        data_path = Path(server.get_data_folder()) / "system" / "todos.yml"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, str(data_path), default_content={}, yaml_format=True)
        self.server = server
        self._next_id: int = 1

    def initialize(self) -> None:
        """初始化系统，加载待办数据"""
        # 从配置文件加载待办数据
        self.load()

        # 初始化next_id
        if "next_id" in self:
            self._next_id = int(self.get("next_id", 1))
        else:
            # 如果已有待办项，找到最大ID
            todos = self.get("todos", {})
            if todos:
                try:
                    max_id = max(int(k) for k in todos.keys() if k.isdigit())
                    self._next_id = max_id + 1
                except (ValueError, TypeError):
                    self._next_id = 1
            else:
                self._next_id = 1
            # 保存next_id到配置文件
            self["next_id"] = self._next_id

        # 确保todos字典存在
        if "todos" not in self:
            self["todos"] = {}

        self.logger.debug(f"已加载 {len(self.get('todos', {}))} 个待办事项")

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
        if first_message.get("type") != "text":
            return False

        return await self._handle_msg(broadcast_info)

    async def _handle_msg(self, broadcast_info: BroadcastInfo) -> bool:
        """处理消息"""
        if self.is_command(broadcast_info):
            return await self._handle_command(broadcast_info)

        return False

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        """处理待办相关命令"""
        # 所有用户都可以使用，不检查is_admin权限

        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        if not command.startswith(system_name):
            return False

        command = command.replace(system_name, "", 1).strip()

        if command.startswith(self.get_tr("add")):
            return await self._handle_add(broadcast_info)
        elif command.startswith(self.get_tr("remove")):
            return await self._handle_remove(broadcast_info)
        elif command.startswith(self.get_tr("complete")):
            return await self._handle_complete(broadcast_info)
        elif command.startswith(self.get_tr("undo")):
            return await self._handle_undo(broadcast_info)
        elif command.startswith(self.get_tr("list")):
            return await self._handle_list(broadcast_info)

        return await self._handle_help(broadcast_info)

    async def _handle_add(self, broadcast_info: BroadcastInfo) -> bool:
        """处理添加待办命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_command = self.get_tr("add")

        for i in [command_prefix, system_name, add_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("add_instruction"))]
            )
            return True

        # 创建待办项
        todo_id = str(self._next_id)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        created_by = broadcast_info.sender or self.get_tr("unknown")

        # 确保todos字典存在
        if "todos" not in self:
            self["todos"] = {}

        todos = self.get("todos", {})
        todos[todo_id] = {
            "id": todo_id,
            "content": command,
            "created_at": created_at,
            "created_by": created_by,
            "completed": False,
            "completed_at": None,
        }
        self["todos"] = todos
        self["next_id"] = self._next_id + 1
        self._next_id += 1
        self.save()

        await self.reply(
            broadcast_info,
            [
                MessageBuilder.text(
                    self.get_tr("add_success", id=todo_id, content=command)
                )
            ],
        )
        return True

    async def _handle_remove(self, broadcast_info: BroadcastInfo) -> bool:
        """处理删除待办命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        remove_command = self.get_tr("remove")

        for i in [command_prefix, system_name, remove_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("remove_instruction"))]
            )
            return True

        # 获取待办列表
        todos = self.get("todos", {})

        if command not in todos:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("remove_not_exist", id=command))],
            )
            return True

        # 删除待办项
        del todos[command]
        self["todos"] = todos
        self.save()

        await self.reply(
            broadcast_info,
            [MessageBuilder.text(self.get_tr("remove_success", id=command))],
        )
        return True

    async def _handle_complete(self, broadcast_info: BroadcastInfo) -> bool:
        """处理完成待办命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        complete_command = self.get_tr("complete")

        for i in [command_prefix, system_name, complete_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("complete_instruction"))],
            )
            return True

        # 获取待办列表
        todos = self.get("todos", {})

        if command not in todos:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("complete_not_exist", id=command))],
            )
            return True

        todo = todos[command]

        # 检查是否已完成
        if todo.get("completed", False):
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("complete_already", id=command))],
            )
            return True

        # 标记为已完成
        todo["completed"] = True
        todo["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        todos[command] = todo
        self["todos"] = todos
        self.save()

        await self.reply(
            broadcast_info,
            [MessageBuilder.text(self.get_tr("complete_success", id=command))],
        )
        return True

    async def _handle_undo(self, broadcast_info: BroadcastInfo) -> bool:
        """处理撤回完成命令"""
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        undo_command = self.get_tr("undo")

        for i in [command_prefix, system_name, undo_command]:
            command = command.replace(i, "", 1).strip()

        if not command:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("undo_instruction"))]
            )
            return True

        # 获取待办列表
        todos = self.get("todos", {})

        if command not in todos:
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("undo_not_exist", id=command))],
            )
            return True

        todo = todos[command]

        # 检查是否未完成
        if not todo.get("completed", False):
            await self.reply(
                broadcast_info,
                [MessageBuilder.text(self.get_tr("undo_not_completed", id=command))],
            )
            return True

        # 撤回完成状态
        todo["completed"] = False
        todo["completed_at"] = None
        todos[command] = todo
        self["todos"] = todos
        self.save()

        await self.reply(
            broadcast_info,
            [MessageBuilder.text(self.get_tr("undo_success", id=command))],
        )
        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理显示待办列表命令"""
        todos = self.get("todos", {})

        if not todos:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
            )
            return True

        # 构建待办列表，区分已完成和未完成
        pending_list = []
        completed_list = []

        for todo_id in sorted(todos.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            todo = todos[todo_id]
            is_completed = todo.get("completed", False)
            status_mark = (
                self.get_tr("status_completed")
                if is_completed
                else self.get_tr("status_pending")
            )
            unknown = self.get_tr("unknown")
            creator_label = self.get_tr("creator_label")
            time_label = self.get_tr("time_label")
            completed_time_label = self.get_tr("completed_time_label")

            todo_info = (
                f"{status_mark} {todo_id}. {todo.get('content', '')} "
                f"({creator_label} {todo.get('created_by', unknown)}, "
                f"{time_label} {todo.get('created_at', unknown)}"
            )

            if is_completed and todo.get("completed_at"):
                todo_info += f"{completed_time_label}{todo.get('completed_at')}"

            todo_info += ")"

            if is_completed:
                completed_list.append(todo_info)
            else:
                pending_list.append(todo_info)

        # 组合列表
        todo_list_parts = []
        if pending_list:
            todo_list_parts.append(
                self.get_tr("list_pending", todo_list="\n".join(pending_list))
            )
        if completed_list:
            todo_list_parts.append(
                self.get_tr("list_completed", todo_list="\n".join(completed_list))
            )

        if not todo_list_parts:
            await self.reply(
                broadcast_info, [MessageBuilder.text(self.get_tr("list_empty"))]
            )
            return True

        todo_list_text = "\n\n".join(todo_list_parts)
        await self.reply(
            broadcast_info,
            [
                MessageBuilder.text(
                    self.get_tr("list_content", todo_list=todo_list_text)
                )
            ],
        )
        return True

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """待办指令帮助"""
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        add_cmd = self.get_tr("add")
        remove_cmd = self.get_tr("remove")
        complete_cmd = self.get_tr("complete")
        undo_cmd = self.get_tr("undo")
        list_cmd = self.get_tr("list")
        help_msg = self.get_tr(
            "help_msg",
            command_prefix=command_prefix,
            name=system_name,
            add=add_cmd,
            remove=remove_cmd,
            complete=complete_cmd,
            undo=undo_cmd,
            list=list_cmd,
        )
        await self.reply(broadcast_info, [MessageBuilder.text(help_msg)])
        return True
