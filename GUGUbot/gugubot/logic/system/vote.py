# -*- coding: utf-8 -*-
"""投票系统模块

现阶段该模块提供服务器关闭投票功能。
"""

import asyncio
import time
import traceback
from typing import Optional, Set, List

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.player_manager import PlayerManager
from gugubot.utils.types import BroadcastInfo
from gugubot.utils.vote_manager import VoteManager, VoteStatus, Vote, VoteTypeRegistry, VoteTypeConfig


class VoteSystem(BasicSystem):
    """投票系统

    提供服务器关闭投票功能。

    Attributes
    ----------
    name : str
        系统名称
    enable : bool
        系统是否启用
    server : PluginServerInterface
        MCDR 服务器接口。
    vote_manager : VoteManager
        投票管理器实例
    vote_type_registry : VoteTypeRegistry
        投票类型注册器，管理所有已注册的投票类型配置。
    player_manager : PlayerManager
        玩家管理器实例
    debug_enabled : bool
        是否开启调试日志输出，由配置项 ``GUGUBot.show_message_in_console`` 控制。
    """

    def __init__(
            self,
            server: PluginServerInterface,
            config: Optional[BotConfig] = None,
    ) -> None:
        """初始化投票系统

        Parameters
        ----------
        server : PluginServerInterface
            MCDR 服务器接口
        config : Optional[BotConfig]
            配置对象
        """
        super().__init__("vote", enable=False, config=config)
        self.server = server
        self.player_manager = PlayerManager(server, self)
        self.player_manager.load()
        self.vote_manager = VoteManager(server)
        self.vote_type_registry = VoteTypeRegistry()

        # 从配置读取设置
        self._load_config()

        # 获取调试配置
        self.debug_enabled = self.config.get_keys(["GUGUBot", "show_message_in_console"], False)

        # 当前投票监控任务（vote_id -> Task，支持多个并发投票）
        self._monitor_tasks: dict[str, asyncio.Task] = {}

    def debug_log(self, message: str) -> None:
        """输出调试日志（仅在debug_enabled为True时）

        Parameters
        ----------
        message : str
            调试消息
        """
        if self.debug_enabled:
            self.logger.debug(message)

    def _load_config(self) -> None:
        """从配置文件加载投票关键词设置。

        Notes
        -----
        读取 ``system.vote.keywords`` 配置节，分别设置
        ``yes_keywords``、``no_keywords``、``withdraw_keywords``、``delete_keywords``
        四个实例属性；缺失时使用内置默认值。
        """
        # 加载全局投票关键词
        vote_keywords_config = self.config.get_keys(["system", "vote", "keywords"], {})
        self.yes_keywords = vote_keywords_config.get("yes", ["111", "同意", "赞成", "yes"])
        self.no_keywords = vote_keywords_config.get("no", ["222", "反对", "拒绝", "no"])
        self.withdraw_keywords = vote_keywords_config.get("withdraw", ["弃票", "撤回", "abstain", "withdraw"])
        self.delete_keywords = vote_keywords_config.get("delete", ["删除投票", "delete_vote"])

    def _register_default_vote_types(self) -> None:
        """注册内置的默认投票类型。

        Notes
        -----
        目前仅注册关服投票（``shutdown``）。
        可通过 :meth:`register_vote_type` 在外部追加自定义类型。
        """
        # 注册关服投票
        self._register_shutdown_vote_type()

    def _register_shutdown_vote_type(self) -> None:
        """根据配置注册关服投票类型（``shutdown``）。

        Notes
        -----
        从 ``system.vote.shutdown`` 配置节读取参数，
        若该类型已被禁用（``enable: false``）则跳过注册并记录日志。
        """
        shutdown_config_dict = self.config.get_keys(["system", "vote", "shutdown"], {})
        shutdown_keywords = shutdown_config_dict.get("keywords", {})
        shutdown_config = VoteTypeConfig(
            vote_type="shutdown",
            name_key="shutdown_name",
            description_key="shutdown_description",
            required_percentage=shutdown_config_dict.get("required_percentage", 1.0),
            timeout=shutdown_config_dict.get("timeout", 300),
            callback=self._shutdown_server_callback,
            start_keywords=shutdown_keywords.get("start", ["关服", "关闭服务器", "shutdown"]),
            consult_keywords=shutdown_keywords.get("consult", ["坏了坏了", "要不要关服"]),
            enabled=shutdown_config_dict.get("enable", True)
        )
        success = self.vote_type_registry.register(shutdown_config)
        if success:
            self.logger.info("[VoteSystem] 已注册默认投票类型: shutdown")
        elif not shutdown_config.enabled:
            self.logger.info("[VoteSystem] 默认投票类型 shutdown 已在配置中禁用，跳过注册")
        else:
            self.logger.warning("[VoteSystem] 注册默认投票类型失败: shutdown 已存在")

    def register_vote_type(self, config: VoteTypeConfig) -> bool:
        """注册新的投票类型（供外部插件调用）。

        Parameters
        ----------
        config : VoteTypeConfig
            要注册的投票类型配置。

        Returns
        -------
        bool
            注册成功返回 ``True``；已禁用或已存在则返回 ``False``。
        """
        if not config.enabled:
            self.logger.info(f"[VoteSystem] 投票类型 {config.vote_type} 已禁用，跳过注册")
            return False
        success = self.vote_type_registry.register(config)
        if success:
            self.logger.info(f"[VoteSystem] 已注册投票类型: {config.vote_type}")
        else:
            self.logger.warning(f"[VoteSystem] 注册投票类型失败: {config.vote_type} 已存在")
        return success

    def unregister_vote_type(self, vote_type: str) -> bool:
        """注销投票类型（供外部插件调用）。

        Parameters
        ----------
        vote_type : str
            要注销的投票类型标识符。

        Returns
        -------
        bool
            注销成功返回 ``True``；类型不存在则返回 ``False``。
        """
        success = self.vote_type_registry.unregister(vote_type)
        if success:
            self.logger.info(f"[VoteSystem] 已注销投票类型: {vote_type}")
        else:
            self.logger.warning(f"[VoteSystem] 注销投票类型失败: {vote_type} 不存在")
        return success

    def initialize(self) -> None:
        """初始化投票系统。

        Notes
        -----
        - 将服务器日志记录器注入 :attr:`vote_manager`。
        - 调用 :meth:`_register_default_vote_types` 注册内置投票类型。
        """
        self.vote_manager.logger = self.logger

        # 注册默认的投票类型
        self._register_default_vote_types()

        self.logger.debug("投票系统已初始化")

    async def _handle_command(self, broadcast_info: BroadcastInfo) -> bool:
        """解析并分发投票相关命令（以命令前缀开头的消息）。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息，其中 ``message[0]`` 应为文本类型的命令字符串。

        Returns
        -------
        bool
            命令被识别并处理返回 ``True``，否则返回 ``False``。
        """
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        if not command.startswith(system_name):
            return False

        command = command.replace(system_name, "", 1).strip()

        # 如果命令为空，显示帮助
        if not command:
            return await self._handle_help(broadcast_info)

        # 管理员命令
        if broadcast_info.is_admin:
            # 检查 enable/disable 命令
            enable_cmd = self.get_tr("gugubot.enable", global_key=True)
            disable_cmd = self.get_tr("gugubot.disable", global_key=True)

            if command == enable_cmd:
                return await self._handle_switch(True, broadcast_info)
            elif command == disable_cmd:
                return await self._handle_switch(False, broadcast_info)
            elif command.startswith(self.get_tr("removeAll")):
                # 处理删除所有投票命令
                return await self._handle_remove_all(broadcast_info)
            elif command.startswith(self.get_tr("remove")):
                # 处理删除投票命令
                return await self._handle_remove(broadcast_info)

        # 所有用户都可以使用的命令
        if command.startswith(self.get_tr("list")):
            # 处理列出所有投票命令
            return await self._handle_list(broadcast_info)
        elif command.startswith(self.get_tr("types")):
            # 处理列出投票类型命令
            return await self._handle_types(broadcast_info)
        elif command.startswith(self.get_tr("withdraw")):
            # 处理弃票命令
            return await self._handle_withdraw(broadcast_info)

        # 未识别的命令，显示帮助
        return await self._handle_help(broadcast_info)

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的消息

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息

        Returns
        -------
        bool
            消息是否被处理
        """

        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(broadcast_info):
            return True

        if not self.enable:
            return False

        if broadcast_info.event_type != "message":
            return False

        message = broadcast_info.message
        if not message:
            return False

        first_message = message[0]
        if first_message.get("type") != "text":
            return False

        # 先检查是否是命令（如 #投票）
        if self.is_command(broadcast_info):
            return await self._handle_command(broadcast_info)

        # 如果不是命令，再检查投票关键词
        message_text = self._extract_text_from_message(message)
        self.debug_log(f"[VoteSystem Debug] 提取的消息文本: '{message_text}'")

        if message_text:
            # 检查是否是投票相关关键词
            self.debug_log(f"[VoteSystem Debug] 开始检查关键词")
            if await self._handle_keywords(broadcast_info, message_text):
                return True
        else:
            self.debug_log("[VoteSystem Debug] 消息文本为空")

        return False

    def _extract_text_from_message(self, message: list) -> str:
        """从消息中提取文本内容

        Parameters
        ----------
        message : list
            消息列表

        Returns
        -------
        str
            提取的文本内容
        """
        text_parts = []
        for segment in message:
            if segment.get("type") == "text":
                text_parts.append(segment.get("data", {}).get("text", ""))
        return "".join(text_parts).strip()

    async def _handle_keywords(
            self, broadcast_info: BroadcastInfo, message_text: str
    ) -> bool:
        """检测消息文本中的投票关键词并执行对应操作。

        检测顺序：弃票关键词 → 删除关键词（仅管理员）→ 开始投票关键词（精确）→
        征求模式关键词（模糊）→ 赞成票关键词 → 反对票关键词。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息。
        message_text : str
            从消息中提取的纯文本内容。

        Returns
        -------
        bool
            任意关键词匹配并处理返回 ``True``，否则返回 ``False``。
        """
        self.debug_log(f"[VoteSystem Debug] _handle_keywords 被调用，消息: '{message_text}'")

        # 检查弃票关键词（所有用户）
        self.debug_log(f"[VoteSystem Debug] 检查弃票关键词: {self.withdraw_keywords}")
        for keyword in self.withdraw_keywords:
            if message_text.startswith(keyword):
                self.debug_log(f"[VoteSystem Debug] 匹配到弃票关键词: '{keyword}'")
                # 提取序号（如果有）
                index = self._extract_vote_index(message_text, keyword)
                await self._handle_withdraw_keyword(broadcast_info, index)
                return True

        # 检查取消投票关键词（仅管理员，用于删除整个投票）
        self.debug_log(f"[VoteSystem Debug] 检查取消投票关键词（管理员）: {self.delete_keywords}")
        for keyword in self.delete_keywords:
            if keyword == message_text:
                self.debug_log(f"[VoteSystem Debug] 匹配到取消投票关键词: '{keyword}'")
                if broadcast_info.is_admin:
                    await self._handle_delete(broadcast_info)
                    return True
                else:
                    self.debug_log("[VoteSystem Debug] 发送者不是管理员，忽略取消投票请求")

        # 先尝试精确匹配（用于 start_keywords）
        result = self.vote_type_registry.get_by_keyword(message_text)
        if result:
            vote_config, is_consult = result
            self.debug_log(f"[VoteSystem Debug] 精确匹配到投票关键词: '{message_text}', "
                           f"类型: {vote_config.vote_type}, 征求模式: {is_consult}")
            await self._handle_start_vote_with_config(broadcast_info, vote_config, is_consult)
            return True

        # 模糊匹配（用于 consult_keywords）
        # 仅当消息包含关键词且不完全相等时触发（完全相等已由上方精确匹配处理）
        for keyword in self.vote_type_registry.get_all_keywords():
            if keyword not in message_text:
                # 关键词不在消息中，跳过
                continue
            if keyword == message_text:
                # 完全相等的情况已由精确匹配处理，此处跳过避免重复触发
                continue
            result = self.vote_type_registry.get_by_keyword(keyword)

            if not result:
                continue

            vote_config, is_consult = result

            if is_consult:
                self.debug_log(f"[VoteSystem Debug] 模糊匹配到征求模式关键词: '{keyword}'")
                await self._handle_start_vote_with_config(broadcast_info, vote_config, True)
                return True

        # 检查投赞成票关键词
        self.debug_log(f"[VoteSystem Debug] 检查赞成票关键词: {self.yes_keywords}")
        for keyword in self.yes_keywords:
            if message_text.startswith(keyword):
                self.debug_log(f"[VoteSystem Debug] 匹配到赞成票关键词: '{keyword}'")
                # 提取序号（如果有）
                index = self._extract_vote_index(message_text, keyword)
                await self._handle_vote(broadcast_info, vote_yes=True, index=index)
                return True

        # 检查投反对票关键词
        self.debug_log(f"[VoteSystem Debug] 检查反对票关键词: {self.no_keywords}")
        for keyword in self.no_keywords:
            if message_text.startswith(keyword):
                self.debug_log(f"[VoteSystem Debug] 匹配到反对票关键词: '{keyword}'")
                # 提取序号（如果有）
                index = self._extract_vote_index(message_text, keyword)
                await self._handle_vote(broadcast_info, vote_yes=False, index=index)
                return True

        self.debug_log("[VoteSystem Debug] 没有匹配到任何关键词")
        return False

    def _extract_vote_index(self, message_text: str, keyword: str) -> Optional[int]:
        """从消息中提取投票序号

        Parameters
        ----------
        message_text : str
            完整消息文本
        keyword : str
            匹配的关键词

        Returns
        -------
        int, optional
            投票序号，如果没有则返回 None
        """
        # 移除关键词，获取剩余部分
        remaining = message_text[len(keyword):].strip()

        if remaining.isdigit():
            return int(remaining)

        return None

    def _get_vote_name(self, vote: Vote) -> str:
        """获取投票显示名称

        Parameters
        ----------
        vote : Vote
            投票实例

        Returns
        -------
        str
            投票显示名称
        """
        config = self.vote_type_registry.get_config(vote.vote_type)
        if config:
            return self.get_tr(config.name_key)
        return vote.vote_type  # 如果找不到配置，返回类型标识符

    async def _handle_remove(self, broadcast_info: BroadcastInfo) -> bool:
        """处理删除指定投票的命令（仅管理员）。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息，命令中应包含目标投票序号。

        Returns
        -------
        bool
            始终返回 ``True``（已处理该命令）。
        """
        if not broadcast_info.is_admin:
            msg = self.get_tr("admin_only")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_pending_votes")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        # 从命令中提取序号
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        remove_command = self.get_tr("remove")

        for i in [command_prefix, system_name, remove_command]:
            command = command.replace(i, "", 1).strip()

        if not command or not command.isdigit():
            # 没有指定序号，显示列表
            vote_list = []
            for v in pending_votes:
                vote_list.append(f"[{v.index}] {v.description}")

            msg = self.get_tr(
                "specify_vote_index",
                vote_list="\n".join(vote_list),
                command_prefix=command_prefix,
                name=system_name,
                remove=remove_command
            )
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        index = int(command)
        vote = self.vote_manager.get_vote_by_index(index)

        if not vote:
            msg = self.get_tr("vote_not_found", index=index)
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        success = self.vote_manager.delete_vote(vote.vote_id)
        if success:
            # 取消该投票的监控任务
            task = self._monitor_tasks.pop(vote.vote_id, None)
            if task:
                task.cancel()
            msg = self.get_tr(
                "vote_removed",
                admin=broadcast_info.sender,
                index=index,
                description=vote.description
            )
            await self._broadcast_to_all(msg)

        return True

    async def _handle_remove_all(self, broadcast_info: BroadcastInfo) -> bool:
        """处理删除所有进行中投票的命令（仅管理员）。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息。

        Returns
        -------
        bool
            始终返回 ``True``（已处理该命令）。
        """
        if not broadcast_info.is_admin:
            msg = self.get_tr("admin_only")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_pending_votes")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        count = 0
        for vote in pending_votes:
            if self.vote_manager.delete_vote(vote.vote_id):
                count += 1
                task = self._monitor_tasks.pop(vote.vote_id, None)
                if task:
                    task.cancel()

        msg = self.get_tr(
            "all_votes_removed",
            admin=broadcast_info.sender,
            count=count
        )
        await self._broadcast_to_all(msg)

        return True

    async def _handle_list(self, broadcast_info: BroadcastInfo) -> bool:
        """处理列出所有进行中投票的命令。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息。

        Returns
        -------
        bool
            始终返回 ``True``（已处理该命令）。
        """
        pending_votes = self.vote_manager.get_all_pending_votes()

        if not pending_votes:
            msg = self.get_tr("no_pending_votes")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        # 构建投票列表消息
        vote_items = []
        for vote in pending_votes:
            progress = vote.get_progress()
            remaining_time = int(progress["remaining_time"])

            item = self.get_tr(
                "vote_list_item",
                index=vote.index,
                description=vote.description,
                initiator=vote.initiator,
                yes_votes=progress["yes_votes"],
                total_voters=progress["total_voters"],
                current_percentage=f"{progress['current_percentage']:.1f}%",
                required_percentage=f"{progress['required_percentage']}%",
                remaining_time=remaining_time
            )
            vote_items.append(item)

        header = self.get_tr("current_votes", count=len(pending_votes))
        msg = header + "\n" + "\n\n".join(vote_items)

        await self.reply(broadcast_info, [MessageBuilder.text(msg)])
        return True

    async def _handle_types(self, broadcast_info: BroadcastInfo) -> bool:
        """处理列出投票类型的命令，仅显示序号与名称；若附带类型名则显示详情。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息，命令末尾可附带投票类型名称以查询详情。

        Returns
        -------
        bool
            始终返回 ``True``（已处理该命令）。
        """
        # 从命令中提取可能的类型名
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        types_command = self.get_tr("types")

        for i in [command_prefix, system_name, types_command]:
            command = command.replace(i, "", 1).strip()

        # 如果提供了类型名，显示该类型的详情
        if command:
            return await self._handle_type_detail(broadcast_info, command)

        # 获取所有已注册的投票类型
        all_configs = self.vote_type_registry.get_all_configs()

        if not all_configs:
            msg = self.get_tr("no_vote_types")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        # 仅显示序号+类型名
        vote_configs_list = list(all_configs.values())
        type_lines = []
        for i, config in enumerate(vote_configs_list, start=1):
            name = self.get_tr(config.name_key)
            type_lines.append(f"{i}. {name}")

        header = self.get_tr("available_vote_types_simple", count=len(vote_configs_list))
        tip = self.get_tr(
            "vote_type_detail_tip",
            command_prefix=command_prefix,
            name=system_name,
            types=types_command
        )
        msg = header + "\n" + "\n".join(type_lines) + "\n\n" + tip

        await self.reply(broadcast_info, [MessageBuilder.text(msg)])
        return True

    async def _handle_type_detail(self, broadcast_info: BroadcastInfo, type_name: str) -> bool:
        """显示特定投票类型的详细信息。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息。
        type_name : str
            投票类型的显示名称或类型标识符。

        Returns
        -------
        bool
            始终返回 ``True``（已处理该命令）。
        """
        all_configs = self.vote_type_registry.get_all_configs()

        # 按翻译名称匹配
        matched_config = None
        for config in all_configs.values():
            name = self.get_tr(config.name_key)
            if name == type_name or config.vote_type == type_name:
                matched_config = config
                break

        if not matched_config:
            msg = self.get_tr("vote_type_not_found", type_name=type_name)
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        name = self.get_tr(matched_config.name_key)
        description = self.get_tr(matched_config.description_key)
        start_keywords = ", ".join(matched_config.start_keywords) if matched_config.start_keywords else self.get_tr("none")
        consult_keywords = ", ".join(matched_config.consult_keywords) if matched_config.consult_keywords else self.get_tr("none")

        msg = self.get_tr(
            "vote_type_item",
            name=name,
            description=description,
            required_percentage=f"{int(matched_config.required_percentage * 100)}%",
            timeout=int(matched_config.timeout),
            start_keywords=start_keywords,
            consult_keywords=consult_keywords
        )

        await self.reply(broadcast_info, [MessageBuilder.text(msg)])
        return True

    async def _handle_withdraw(self, broadcast_info: BroadcastInfo) -> bool:
        """处理通过命令（``#投票 弃票 [序号]``）发起的弃票请求。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息，命令末尾可附带投票序号。

        Returns
        -------
        bool
            始终返回 ``True``（已处理该命令）。
        """
        # 从命令中提取序号
        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        withdraw_command = self.get_tr("withdraw")

        for i in [command_prefix, system_name, withdraw_command]:
            command = command.replace(i, "", 1).strip()

        # 解析序号
        index = None
        if command and command.isdigit():
            index = int(command)

        return await self._handle_withdraw_keyword(broadcast_info, index)

    async def _handle_withdraw_keyword(self, broadcast_info: BroadcastInfo, index: Optional[int] = None) -> bool:
        """处理弃票（通过关键词或命令）

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息
        index : Optional[int]
            投票序号，如果为 None 则自动选择

        Returns
        -------
        bool
            是否处理成功
        """
        # 获取进行中的投票
        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_active_vote")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        # 根据序号或数量选择投票
        vote = await self._select_vote_for_withdraw(broadcast_info, pending_votes, index)
        if not vote:
            return True

        # 获取投票者的QQ号
        actual_voter_id = await self._get_voter_id_from_broadcast(broadcast_info)

        if not actual_voter_id:
            msg = self.get_tr("not_eligible")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        # 检查是否有投票资格
        if actual_voter_id not in vote.eligible_voters:
            msg = self.get_tr("not_eligible")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return True

        # 执行弃票
        success = vote.withdraw_vote(actual_voter_id)
        if success:
            # 广播弃票消息
            msg = self.get_tr(
                "withdraw_success",
                voter=broadcast_info.sender,
                vote_name=self._get_vote_name(vote)
            )
            await self._broadcast_to_all(msg)
        else:
            # 还没有投票，无法弃票
            msg = self.get_tr("not_voted_yet")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])

        return True

    async def _select_vote_for_withdraw(
            self,
            broadcast_info: BroadcastInfo,
            pending_votes: List[Vote],
            index: Optional[int]
    ) -> Optional[Vote]:
        """为弃票操作选择投票实例

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息
        pending_votes : List[Vote]
            进行中的投票列表
        index : int, optional
            指定的投票序号

        Returns
        -------
        Vote, optional
            选中的投票实例，如果无法选择则返回 None
        """
        if index is not None:
            # 指定了序号，根据序号查找
            vote = self.vote_manager.get_vote_by_index(index)
            if not vote:
                msg = self.get_tr("vote_not_found", index=index)
                await self.reply(broadcast_info, [MessageBuilder.text(msg)])
                return None
            return vote

        if len(pending_votes) == 1:
            # 只有一个投票，直接使用
            return pending_votes[0]

        # 有多个投票但没指定序号，提示用户
        vote_list = [f"[{v.index}] {v.description}" for v in pending_votes]
        withdraw_example = f"{self.withdraw_keywords[0]} 1" if self.withdraw_keywords else "弃票 1"

        msg = self.get_tr(
            "multiple_votes_specify_withdraw",
            count=len(pending_votes),
            vote_list="\n".join(vote_list),
            withdraw_example=withdraw_example
        )
        await self.reply(broadcast_info, [MessageBuilder.text(msg)])
        return None

    async def _handle_help(self, broadcast_info: BroadcastInfo) -> bool:
        """向用户回复帮助消息。

        管理员与普通用户会收到不同内容的帮助文本。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息。

        Returns
        -------
        bool
            始终返回 ``True``（已处理该命令）。
        """
        # 获取配置的命令前缀和命令名称
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        # 获取子命令翻译
        enable_command = self.get_tr("gugubot.enable", global_key=True)
        disable_command = self.get_tr("gugubot.disable", global_key=True)
        list_command = self.get_tr("list")
        types_command = self.get_tr("types")
        withdraw_command = self.get_tr("withdraw")
        remove_command = self.get_tr("remove")
        remove_all_command = self.get_tr("removeAll")

        # 获取关键词模板
        yes_example = self.extract_keyword_example(self.yes_keywords)
        no_example = self.extract_keyword_example(self.no_keywords)
        yes_example_single = self.extract_keyword_example(self.yes_keywords, 1)
        no_example_single = self.extract_keyword_example(self.no_keywords, 1)
        withdraw_example = self.extract_keyword_example(self.withdraw_keywords)
        delete_example = self.extract_keyword_example(self.delete_keywords)

        # 根据用户权限选择不同的帮助消息
        if broadcast_info.is_admin:
            msg = self.get_tr(
                "help_msg",
                command_prefix=command_prefix,
                name=system_name,
                enable=enable_command,
                disable=disable_command,
                list=list_command,
                types=types_command,
                withdraw=withdraw_command,
                vote_name_example=self.extract_keyword_example(self.vote_type_registry.get_all_keywords(), 2),
                yes_example=yes_example,
                no_example=no_example,
                yes_example_single=yes_example_single,
                no_example_single=no_example_single,
                remove=remove_command,
                removeAll=remove_all_command,
                delete_example=delete_example,
                withdraw_example=withdraw_example
            )
        else:
            msg = self.get_tr(
                "user_help_msg",
                command_prefix=command_prefix,
                name=system_name,
                types=types_command,
                yes_example=yes_example,
                no_example=no_example,
                yes_example_single=yes_example_single,
                no_example_single=no_example_single,
                withdraw_example=withdraw_example
            )

        await self.reply(broadcast_info, [MessageBuilder.text(msg)])
        return True

    async def _handle_start_vote_with_config(self, broadcast_info: BroadcastInfo, vote_config: VoteTypeConfig,
                                             consult_mode: bool) -> None:
        """根据投票类型配置发起一次新投票。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息，``sender`` 将成为投票发起人。
        vote_config : VoteTypeConfig
            目标投票类型的配置对象。
        consult_mode : bool
            ``True`` 为征求模式（发起人不自动投赞成票）；
            ``False`` 为普通模式（发起人自动投赞成票）。
        """
        self.debug_log(f"[VoteSystem Debug] 收到{vote_config.vote_type}类型的投票请求，发起人: {broadcast_info.sender}, "
                       f"征求模式: {consult_mode}")

        # 发起投票前从磁盘重新加载最新绑定数据，确保资格名单是最新的。
        self.player_manager.load()

        # 获取所有在线玩家的绑定信息
        eligible_voters = await self._get_eligible_voters()

        # 获取发起者的QQ号
        initiator_voter_id = await self._get_voter_id_from_broadcast(broadcast_info)

        # 检查发起者资格（管理员可以绕过）
        if not broadcast_info.is_admin:
            if not initiator_voter_id:
                # 无法获取发起人的QQ号，无投票资格
                msg = self.get_tr("not_eligible_initiator")
                await self.reply(broadcast_info, [MessageBuilder.text(msg)])
                return

            if initiator_voter_id not in eligible_voters:
                # 发起人无投票资格
                msg = self.get_tr("not_eligible_initiator")
                await self.reply(broadcast_info, [MessageBuilder.text(msg)])
                return

        # 检查是否已有进行中的投票
        existing_vote = self.vote_manager.get_pending_vote_by_type(vote_config.vote_type)
        if existing_vote:
            msg = self.get_tr("vote_already_exists")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        # 检查是否有足够的合格的投票者
        # 征求模式下，即使是管理员也不能在无人可投票时发起（没有人可以响应）
        # 非征求模式下，管理员可以绕过此限制（管理员会将自己加入投票者并自动投赞成票）
        if not eligible_voters and (consult_mode or not broadcast_info.is_admin):
            msg = self.get_tr("no_eligible_voters")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        # 创建投票
        vote = self.vote_manager.create_vote(
            vote_type=vote_config.vote_type,
            initiator=broadcast_info.sender,
            initiator_id=broadcast_info.sender_id,
            eligible_voters=eligible_voters,
            required_percentage=vote_config.required_percentage,
            timeout=vote_config.timeout,
            callback=vote_config.callback,
            description=self.get_tr(vote_config.description_key)
        )

        if not vote:
            msg = self.get_tr("vote_create_failed")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        # 根据模式决定是否自动投票
        if not consult_mode:
            # 非征求模式下，发起人自动投赞成票
            # 如果发起人有投票资格，使用其QQ号投票
            # 如果是管理员绕过的情况，使用 sender_id 作为虚拟投票者ID
            self.debug_log(f"[VoteSystem Debug] 非征求模式，准备自动投票")
            self.debug_log(f"[VoteSystem Debug] 发起人已解析: {initiator_voter_id is not None}, "
                           f"合格投票人数: {len(eligible_voters)}, is_admin: {broadcast_info.is_admin}")

            if initiator_voter_id and initiator_voter_id in eligible_voters:
                self.debug_log(f"[VoteSystem Debug] ✓ 发起人({broadcast_info.sender})有投票资格，投赞成票")
                success, is_new, _ = vote.cast_vote(initiator_voter_id, True)
                self.debug_log(f"[VoteSystem Debug] cast_vote返回值: success={success}, is_new={is_new}")
                self.debug_log(f"[VoteSystem Debug] 投票后 yes={vote.get_progress()['yes_votes']}, no={vote.get_progress()['no_votes']}")
            elif broadcast_info.is_admin:
                # 管理员绕过：将管理员的 sender_id 临时添加到投票资格中并自动投赞成票
                self.debug_log(f"[VoteSystem Debug] ✓ 管理员({broadcast_info.sender})绕过在线限制，直接发起投票并投赞成票")
                vote.eligible_voters.add(broadcast_info.sender_id)
                success, is_new, _ = vote.cast_vote(broadcast_info.sender_id, True)
                self.debug_log(f"[VoteSystem Debug] 管理员cast_vote返回值: success={success}, is_new={is_new}")
            else:
                self.debug_log(f"[VoteSystem Debug] ✗ 发起人({broadcast_info.sender})无法自动投票")

        # 检查投票在开始就被满足（例如可投票成员只有一位）
        if self.vote_manager.check_and_finalize_vote(vote.vote_id) == VoteStatus.PASSED:
            await self._handle_vote_result(vote, VoteStatus.PASSED)
            return

        # 检查是否有多个投票
        pending_votes = self.vote_manager.get_all_pending_votes()
        has_multiple_votes = len(pending_votes) > 1

        # 广播投票开始消息
        self.debug_log(f"[VoteSystem Debug] 准备获取投票进度")
        progress = vote.get_progress()
        self.debug_log(f"[VoteSystem Debug] 进度: yes={progress['yes_votes']}, no={progress['no_votes']}, total={progress['total_voters']}")

        # 获取投票名称
        vote_name = self.get_tr(vote_config.name_key)
        # 获取关键词模板
        yes_example = self.extract_keyword_example(self.yes_keywords)
        no_example = self.extract_keyword_example(self.no_keywords)
        delete_example = self.extract_keyword_example(self.delete_keywords, 1)
        withdraw_example = self.extract_keyword_example(self.withdraw_keywords, 1)

        if consult_mode:
            msg = self.get_tr(
                "vote_started_consult",
                initiator=broadcast_info.sender,
                vote_name=vote_name,
                description=vote.description,
                total_voters=progress["total_voters"],
                required_percentage=f"{progress['required_percentage']}%",
                timeout=int(progress["timeout"]),
                yes_example=yes_example,
                no_example=no_example,
                delete_example=delete_example,
                withdraw_example=withdraw_example,
                yes_votes=progress["yes_votes"],
                no_votes=progress["no_votes"],
                current_percentage=f"{progress['current_percentage']:.1f}%"
            )
        else:
            msg = self.get_tr(
                "vote_started",
                initiator=broadcast_info.sender,
                vote_name=vote_name,
                description=vote.description,
                total_voters=progress["total_voters"],
                required_percentage=f"{progress['required_percentage']}%",
                timeout=int(progress["timeout"]),
                yes_example=yes_example,
                no_example=no_example,
                delete_example=delete_example,
                withdraw_example=withdraw_example,
                yes_votes=progress["yes_votes"],
                no_votes=progress["no_votes"],
                current_percentage=f"{progress['current_percentage']:.1f}%"
            )

        await self._broadcast_to_all(msg)

        # 如果有多个投票，提醒使用序号格式
        if has_multiple_votes:
            vote_list = []
            for v in pending_votes:
                vote_list.append(f"[{v.index}] {v.description}")

            # 获取关键词示例
            yes_keywords = self.yes_keywords
            no_keywords = self.no_keywords
            yes_example = f"{yes_keywords[0]} {vote.index}" if yes_keywords else f"yes {vote.index}"
            no_example = f"{no_keywords[0]} {vote.index}" if no_keywords else f"no {vote.index}"

            msg = self.get_tr(
                "multiple_votes_reminder",
                count=len(pending_votes),
                vote_list="\n".join(vote_list),
                yes_example=yes_example,
                no_example=no_example
            )
            await self._broadcast_to_all(msg)

        # 启动投票监控任务
        self._monitor_tasks[vote.vote_id] = asyncio.create_task(self._monitor_vote(vote.vote_id))

    async def _handle_vote(self, broadcast_info: BroadcastInfo, vote_yes: bool, index: Optional[int] = None) -> None:
        """处理投票（赞成或反对）

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息
        vote_yes : bool
            True为投赞成票，False为投反对票
        index : Optional[int]
            投票序号，如果为 None 则自动选择
        """
        # 获取进行中的投票
        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_active_vote")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        # 根据序号或数量选择投票
        if index is not None:
            # 指定了序号，根据序号查找
            vote = self.vote_manager.get_vote_by_index(index)
            if not vote:
                msg = self.get_tr("vote_not_found", index=index)
                await self.reply(broadcast_info, [MessageBuilder.text(msg)])
                return
        elif len(pending_votes) == 1:
            # 只有一个投票，直接使用
            vote = pending_votes[0]
        else:
            # 有多个投票但没指定序号，提示用户
            vote_list = []
            for v in pending_votes:
                vote_list.append(f"[{v.index}] {v.description}")

            if vote_yes:
                example_keywords = self.yes_keywords
                tr_key = "multiple_votes_specify_yes"
            else:
                example_keywords = self.no_keywords
                tr_key = "multiple_votes_specify_no"

            example = f"{example_keywords[0]} 1" if example_keywords else ("yes 1" if vote_yes else "no 1")
            if vote_yes:
                msg = self.get_tr(
                    tr_key,
                    count=len(pending_votes),
                    vote_list="\n".join(vote_list),
                    yes_example=example
                )
            else:
                msg = self.get_tr(
                    tr_key,
                    count=len(pending_votes),
                    vote_list="\n".join(vote_list),
                    no_example=example
                )
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        # 获取投票者的QQ号（统一使用QQ号作为投票者ID）
        actual_voter_id = await self._get_voter_id_from_broadcast(broadcast_info)

        if not actual_voter_id:
            self.debug_log(f"[VoteSystem Debug] 无法解析投票者 {broadcast_info.sender} 的身份标识")
            msg = self.get_tr("not_eligible")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        self.debug_log(f"[VoteSystem Debug] 投票者 {broadcast_info.sender} 身份已解析，来源: {broadcast_info.source.origin}")

        # 检查是否有投票资格
        if actual_voter_id not in vote.eligible_voters:
            self.debug_log(f"[VoteSystem Debug] {broadcast_info.sender} 不在投票资格列表中（共 {len(vote.eligible_voters)} 人有资格）")
            msg = self.get_tr("not_eligible")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        # 投票
        self.debug_log(f"[VoteSystem Debug] {broadcast_info.sender} 准备投{'赞成' if vote_yes else '反对'}票")
        self.debug_log(f"[VoteSystem Debug] 投票前 yes={vote.get_progress()['yes_votes']}, no={vote.get_progress()['no_votes']}")
        success, is_new_vote, is_same_vote = vote.cast_vote(actual_voter_id, vote_yes)
        self.debug_log(f"[VoteSystem Debug] 投票后 yes={vote.get_progress()['yes_votes']}, no={vote.get_progress()['no_votes']}")
        if success:
            # 如果投的是和之前一样的票，只提示本人，不广播
            if is_same_vote:
                vote_type_tr = self.get_tr("vote_yes" if vote_yes else "vote_no")
                msg = self.get_tr(
                    "vote_already_same",
                    vote_type=vote_type_tr
                )
                await self.reply(broadcast_info, [MessageBuilder.text(msg)])
                return

            progress = vote.get_progress()
            vote_type_tr = self.get_tr("vote_yes" if vote_yes else "vote_no")
            # 根据是新票还是改票使用不同的翻译键
            tr_key = "vote_new" if is_new_vote else "vote_changed"
            msg = self.get_tr(
                tr_key,
                voter=broadcast_info.sender,
                vote_name=self._get_vote_name(vote),
                vote_type=vote_type_tr,
                yes_votes=progress["yes_votes"],
                no_votes=progress["no_votes"],
                total_voters=progress["total_voters"],
                current_percentage=f"{progress['current_percentage']:.1f}%"
            )
            await self._broadcast_to_all(msg)

            # 立即检查投票结果
            result = self.vote_manager.check_and_finalize_vote(vote.vote_id)
            if result and result != VoteStatus.PENDING:
                # 投票已结束，处理结果
                await self._handle_vote_result(vote, result)
                # 取消该投票的监控任务
                task = self._monitor_tasks.pop(vote.vote_id, None)
                if task:
                    task.cancel()

    async def _handle_delete(self, broadcast_info: BroadcastInfo) -> None:
        """处理通过关键词触发的删除投票操作（仅管理员）。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息。
        """
        # 获取进行中的投票
        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_active_vote")
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        # 如果只有一个投票，直接取消
        if len(pending_votes) == 1:
            vote = pending_votes[0]
        else:
            # 有多个投票，提示管理员指定序号
            vote_list = []
            for v in pending_votes:
                vote_list.append(f"[{v.index}] {v.description}")

            command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
            msg = self.get_tr(
                "multiple_votes_cancel",
                count=len(pending_votes),
                vote_list="\n".join(vote_list),
                command_prefix=command_prefix,
                name=self.get_tr("name"),
                remove=self.get_tr("remove")
            )
            await self.reply(broadcast_info, [MessageBuilder.text(msg)])
            return

        success = self.vote_manager.delete_vote(vote.vote_id)
        if success:
            msg = self.get_tr(
                "vote_deleted",
                admin=broadcast_info.sender,
                vote_name=self._get_vote_name(vote)
            )
            await self._broadcast_to_all(msg)

            # 取消该投票的监控任务
            task = self._monitor_tasks.pop(vote.vote_id, None)
            if task:
                task.cancel()

    async def _monitor_vote(self, vote_id: str) -> None:
        """监控投票超时，超时后自动结束并处理结果。

        Parameters
        ----------
        vote_id : str
            要监控的投票 ID。

        Notes
        -----
        赞成/反对票在投票发起/触发时已由 ``check_and_finalize_vote`` 立即检查；
        本方法只负责在投票到达超时时间后触发最终判定。
        任务被取消时（投票提前结束），会静默忽略 ``asyncio.CancelledError``。
        """
        try:

            vote = self.vote_manager.get_vote(vote_id)
            if not vote:
                return

            # 计算距离超时还剩多少时间
            elapsed = time.time() - vote.start_time
            remaining_time = max(1, vote.timeout - elapsed)

            # 等待到超时
            await asyncio.sleep(remaining_time)

            # 超时后检查投票是否还在进行中
            vote = self.vote_manager.get_vote(vote_id)
            if not vote:
                return

            result = self.vote_manager.check_and_finalize_vote(vote_id)
            if result and result == VoteStatus.TIMEOUT:
                # 投票已超时
                await self._handle_vote_result(vote, result)

        except asyncio.CancelledError:
            self.logger.debug(f"[VoteSystem] 投票 {vote_id} 监控任务被取消")
        finally:
            # 无论如何都清理任务引用
            await self._monitor_tasks.pop(vote_id, None)

    async def _handle_vote_result(self, vote: Vote, result: VoteStatus) -> None:
        """处理投票结果

        Parameters
        ----------
        vote : Vote
            投票实例
        result : VoteStatus
            投票结果
        """
        progress = vote.get_progress()
        vote_name = self._get_vote_name(vote)

        if result == VoteStatus.PASSED:
            # 投票通过
            msg = self.get_tr(
                "vote_passed",
                initiator=vote.initiator,
                vote_name=vote_name,
                yes_votes=progress["yes_votes"],
                total_voters=progress["total_voters"],
                current_percentage=f"{progress['current_percentage']:.1f}%"
            )
            await self._broadcast_to_all(msg)

            # 执行回调
            if vote.callback:
                try:
                    self.logger.debug(f"[VoteSystem] {vote.initiator}发起的{vote.vote_type}投票（ID："
                                      f"{vote.vote_id}）通过，正在执行投票回调…")
                    await vote.callback()
                except Exception as e:
                    self.logger.error(f"[VoteSystem] 执行投票回调失败: {e}")

        elif result == VoteStatus.REJECTED:
            # 投票被否决
            msg = self.get_tr(
                "vote_rejected",
                initiator=vote.initiator,
                vote_name=vote_name,
                yes_votes=progress["yes_votes"],
                no_votes=progress["no_votes"],
                total_voters=progress["total_voters"]
            )
            await self._broadcast_to_all(msg)

        elif result == VoteStatus.TIMEOUT:
            # 投票超时
            msg = self.get_tr(
                "vote_timeout",
                initiator=vote.initiator,
                vote_name=vote_name,
                yes_votes=progress["yes_votes"],
                total_voters=progress["total_voters"],
                required_percentage=f"{progress['required_percentage']}%"
            )
            await self._broadcast_to_all(msg)

    async def _get_eligible_voters(self) -> Set[str]:
        """获取当前有投票资格的用户 QQ 号集合。

        资格判定规则：玩家在线 **且** 已在 :class:`PlayerManager` 中绑定 QQ 账号。

        Returns
        -------
        Set[str]
            有投票资格的 QQ 号集合；获取失败时返回空集合。
        """
        eligible = set()

        try:

            # 获取在线玩家列表
            online_players = self._get_online_players()
            self.debug_log(f"[VoteSystem Debug] 在线玩家列表: {online_players}")
            self.debug_log(f"[VoteSystem Debug] 在线玩家数量: {len(online_players)}")

            # 获取QQ连接器的source_name
            qq_source = self.config.get_keys(
                ["connector", "QQ", "source_name"], "QQ"
            )
            self.debug_log(f"[VoteSystem Debug] QQ source_name: {qq_source}")

            # 获取每个玩家的绑定QQ
            for player_name in online_players:
                self.debug_log(f"[VoteSystem Debug] 正在查询玩家 '{player_name}' 的绑定信息...")

                # 通过PlayerManager获取玩家对象
                player = self.player_manager.get_player(player_name)

                if not player:
                    self.debug_log(f"[VoteSystem Debug] 在PlayerManager中找不到玩家 '{player_name}'")
                    self.debug_log(f"[VoteSystem Debug] 找不到玩家 {player_name} 的绑定信息")
                    return set()  # 无法获取玩家信息，返回空集合

                self.debug_log(f"[VoteSystem Debug] 找到玩家对象: {player.name}")
                # 获取该玩家的QQ账号列表
                qq_ids = player.accounts.get(qq_source, [])
                self.debug_log(f"[VoteSystem Debug] 玩家 '{player_name}' 绑定账号数: {len(qq_ids)}")

                if qq_ids:
                    eligible.update([qq_id for qq_id in qq_ids])
                    self.debug_log(f"[VoteSystem Debug] {player_name} 已绑定，有投票资格")
                else:
                    self.debug_log(f"[VoteSystem Debug] 玩家 '{player_name}' 没有绑定QQ")
                    self.debug_log(f"[VoteSystem Debug] {player_name} 未绑定QQ，无投票资格")

            self.debug_log(f"[VoteSystem Debug] 有投票资格的人数: {len(eligible)}")

        except Exception as e:
            self.logger.error(f"[VoteSystem] 获取投票资格用户失败: {e}")
            self.logger.error(f"[VoteSystem Debug] 异常堆栈:\n{traceback.format_exc()}")

        return eligible

    async def _get_voter_ids(self, sender_name: str) -> List[str]:
        """获取投票者的QQ号列表（从MC玩家名查询）

        玩家名从PlayerManager查询

        Parameters
        ----------
        sender_name : str
            发送者名称（MC玩家名）

        Returns
        -------
        List[str]
            QQ号列表
        """
        # 获取QQ source_name
        qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")

        # 从PlayerManager查询（使用sender_name作为玩家名）
        # 投票进行中新增的绑定不应影响当前投票的资格名单。
        player = self.player_manager.get_player(sender_name)

        if player:
            qq_ids = player.accounts.get(qq_source, [])
            self.debug_log(f"[VoteSystem Debug] 玩家 '{sender_name}' 绑定账号数: {len(qq_ids)}")
            return [str(qq_id) for qq_id in qq_ids] if qq_ids else []
        else:
            self.debug_log(f"[VoteSystem Debug] 在PlayerManager中找不到玩家 '{sender_name}'")
            return []

    async def _get_voter_id_from_broadcast(self, broadcast_info: BroadcastInfo) -> Optional[str]:
        """从BroadcastInfo获取唯一的投票者ID（QQ号）

        根据消息来源判断：
        - 如果来自QQ connector，sender_id就是QQ号，直接使用
        - 如果来自其他connector（MC等），sender_id是玩家名，从PlayerManager查询玩家绑定的QQ号

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息

        Returns
        -------
        str, optional
            投票者的QQ号，如果无法获取则返回None
        """
        # 获取QQ connector的source_name（用户可能自定义了名称）
        qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")

        # 获取消息的原始来源
        message_source = broadcast_info.source.origin
        sender_id = str(broadcast_info.sender_id)

        self.debug_log(f"[VoteSystem Debug] 消息来源: {message_source}, QQ source配置: {qq_source}")

        # 判断消息是否来自QQ connector
        if message_source == qq_source:
            # 来自QQ connector，sender_id就是QQ号
            self.debug_log(f"[VoteSystem Debug] ✓ 消息来自QQ connector，直接使用sender_id")
            return sender_id

        # 来自其他connector（MC等），sender_id是玩家名，需要查询绑定的QQ号
        self.debug_log(f"[VoteSystem Debug] ✗ 消息不是来自QQ connector，识别为玩家名: {sender_id}")
        voter_ids = await self._get_voter_ids(sender_id)
        if voter_ids:
            voter_id = voter_ids[0]  # 使用第一个绑定的QQ号
            self.debug_log(f"[VoteSystem Debug] ✓ 查询到玩家 '{sender_id}' 的绑定账号")
            return voter_id
        else:
            self.debug_log(f"[VoteSystem Debug] ✗ 无法获取玩家 {sender_id} 的绑定账号")
            return None

    def _get_online_players(self) -> list:
        """获取在线玩家列表

        Returns
        -------
        List
            在线玩家名称列表
        """
        self.debug_log("[VoteSystem Debug] 开始获取在线玩家列表...")

        # 使用online_player_api
        try:
            self.debug_log("[VoteSystem Debug] 尝试使用 online_player_api 插件获取玩家列表...")
            player_api = self.server.get_plugin_instance("online_player_api")
            if player_api:
                players = player_api.get_player_list()
                self.debug_log(f"[VoteSystem Debug] online_player_api 返回的玩家: {players}")
                return players
            else:
                self.debug_log("[VoteSystem Debug] online_player_api 插件不存在")
        except Exception as e:
            self.debug_log(f"[VoteSystem Debug] 使用 online_player_api 失败: {e}")

        self.debug_log("[VoteSystem Debug] 获取在线玩家列表失败，返回空列表")
        return []

    async def _shutdown_server_callback(self) -> None:
        """关服投票通过后的回调：倒计时结束后关闭服务器。

        Notes
        -----
        - 当在线玩家中存在无投票资格者，或同时还有其他进行中的投票时，
          会在配置的基础倒计时之上叠加额外准备时间（``extra_countdown``）。
        - 倒计时结束后调用 ``server.stop()`` 执行关闭。
        """
        try:
            self.logger.info(f"[VoteSystem] 执行关闭服务器")

            # 当服务器中有其他不存在投票资格的玩家或存在其他投票议程时，赋予额外的准备时间
            extra_countdown_time = self.config.get_keys(["system", "vote", "shutdown", "extra_countdown"], 0)

            if len(self._get_online_players()) - len(await self._get_eligible_voters()) > 0 \
                    or len(self.vote_manager.get_all_pending_votes()) - 1 > 0:
                extra_countdown = extra_countdown_time
            else:
                extra_countdown = 0

            # 计算关服最终实际的倒计时时间
            countdown_total_time = self.config.get_keys(["system", "vote", "shutdown", "countdown"],
                                                        10) + extra_countdown

            # 发送关闭通知
            msg = self.get_tr("server_shutting_down",
                              countdown=countdown_total_time,
                              extra_countdown_info=self.get_tr(
                                  "extra_countdown_info") if extra_countdown_time > 0 else "")
            await self._broadcast_to_all(msg)

            # 等待倒计时结束
            await asyncio.sleep(countdown_total_time)

            # 执行关闭命令
            self.server.stop()
            # self.server.say("[测试] 服务器已收到关闭指令，但不执行（测试模式）")

        except Exception as e:
            self.logger.error(f"[VoteSystem] 关闭服务器失败: {e}")

    async def _broadcast_to_all(self, message: str) -> None:
        """向所有连接器广播消息

        这个方法会将投票消息广播到当前 MC 服务器和连接的 QQ 群，排除 bridge connector，避免跨服重复广播

        Parameters
        ----------
        message : str
            要广播的消息
        """
        try:
            from gugubot.utils.types import ProcessedInfo

            # 获取当前服务器的标识符
            server_name = self.config.get_keys(
                ["connector", "minecraft", "source_name"], "Minecraft"
            )

            # 获取 bridge connector 的 source_name，用于排除跨服转发
            bridge_source_name = self.config.get_keys(
                ["connector", "minecraft_bridge", "source_name"], "Bridge"
            )

            # 构造ProcessedInfo用于广播
            processed_info = ProcessedInfo(
                processed_message=[MessageBuilder.text(message)],
                _source=server_name,
                source_id=server_name,
                sender=self.server.tr("gugubot.bot_name"),
                sender_id=None,
                raw=message,
                server=self.server,
                logger=self.logger,
                event_sub_type="group",
                target={}
            )

            if self.system_manager and self.system_manager.connector_manager:
                await self.system_manager.connector_manager.broadcast_processed_info(
                    processed_info,
                    exclude=[bridge_source_name]
                )

        except Exception as e:
            self.logger.error(f"[VoteSystem] 广播消息失败: {e}")

    def extract_keyword_example(self, keywords: Optional[List[str]] = None, count: int = 2) -> str:
        """提取关键词列表中的前若干项，用"或"连接后作为帮助消息的示例文本。

        Parameters
        ----------
        keywords : Optional[List[str]]
            关键词列表
        count : int
            提取的关键词数量，默认2

        Returns
        -------
        str
            关键词模板字符串
        """
        if not keywords:
            return ""
        return f" {self.get_tr('or')} ".join(keywords[:count]) if len(keywords) > 1 else keywords[0]
