# -*- coding: utf-8 -*-
"""投票系统模块

该模块提供服务器关闭投票功能。
"""

import asyncio
from typing import Optional, Set, List

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.player_manager import PlayerManager
from gugubot.utils.types import BoardcastInfo
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
    vote_manager : VoteManager
        投票管理器实例
    player_manager : PlayerManager
        玩家管理器实例
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
        self.player_manager.load()  # 加载玩家数据
        self.vote_manager = VoteManager(server)
        self.vote_type_registry = VoteTypeRegistry()

        # 从配置读取设置
        self._load_config()

        # 获取调试配置
        self.debug_enabled = self.config.get_keys(["GUGUBot", "show_message_in_console"], False)

        # 当前投票监控任务
        self._monitor_task: Optional[asyncio.Task] = None

    def debug_log(self, message: str, to_server: bool = False) -> None:
        """输出调试日志（仅在debug_enabled为True时）

        Parameters
        ----------
        message : str
            调试消息
        to_server : bool
            是否同时输出到游戏服务器
        """
        if self.debug_enabled:
            self.logger.info(message)
            if to_server:
                self.server.say(message)

    def _load_config(self) -> None:
        """从配置文件加载投票设置"""
        # 加载全局投票关键词
        vote_keywords_config = self.config.get_keys(["system", "vote", "keywords"], {})
        self.yes_keywords = vote_keywords_config.get("yes", ["111", "同意", "赞成", "yes"])
        self.no_keywords = vote_keywords_config.get("no", ["222", "反对", "拒绝", "no"])
        self.withdraw_keywords = vote_keywords_config.get("withdraw", ["弃票", "撤回", "abstain", "withdraw"])
        self.delete_keywords = vote_keywords_config.get("delete", ["删除投票", "delete_vote"])

    def _register_default_vote_types(self) -> None:
        """注册默认的投票类型"""
        # 注册关服投票
        self._register_shutdown_vote_type()

    def _register_shutdown_vote_type(self) -> None:
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
            consult_keywords=shutdown_keywords.get("consult", ["坏了坏了", "要不要关服"])
        )
        success = self.vote_type_registry.register(shutdown_config)
        if success:
            self.logger.info("[VoteSystem] 已注册默认投票类型: shutdown")
        else:
            self.logger.warning("[VoteSystem] 注册默认投票类型失败: shutdown 已存在")

    def register_vote_type(self, config: VoteTypeConfig) -> bool:
        """注册新的投票类型（供外部调用）"""
        success = self.vote_type_registry.register(config)
        if success:
            self.logger.info(f"[VoteSystem] 已注册投票类型: {config.vote_type}")
        else:
            self.logger.warning(f"[VoteSystem] 注册投票类型失败: {config.vote_type} 已存在")
        return success

    def unregister_vote_type(self, vote_type: str) -> bool:
        """注销投票类型（供外部调用）"""
        success = self.vote_type_registry.unregister(vote_type)
        if success:
            self.logger.info(f"[VoteSystem] 已注销投票类型: {vote_type}")
        else:
            self.logger.warning(f"[VoteSystem] 注销投票类型失败: {vote_type} 不存在")
        return success

    def initialize(self) -> None:
        """初始化系统"""
        self.vote_manager.logger = self.logger

        # 注册默认的投票类型
        self._register_default_vote_types()

        self.logger.debug("投票系统已初始化")

    async def _handle_command(self, boardcast_info: BoardcastInfo) -> bool:
        """处理投票相关命令"""
        command = boardcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        if not command.startswith(system_name):
            return False

        command = command.replace(system_name, "", 1).strip()

        # 如果命令为空，显示帮助
        if not command:
            return await self._handle_help(boardcast_info)

        # 管理员命令
        if boardcast_info.is_admin:
            # 检查 enable/disable 命令
            enable_cmd = self.get_tr("gugubot.enable", global_key=True)
            disable_cmd = self.get_tr("gugubot.disable", global_key=True)

            if command == enable_cmd:
                return await self._handle_switch(True, boardcast_info)
            elif command == disable_cmd:
                return await self._handle_switch(False, boardcast_info)
            elif command.startswith(self.get_tr("remove")):
                # 处理删除投票命令
                return await self._handle_remove(boardcast_info)
            elif command.startswith(self.get_tr("removeAll")):
                # 处理删除所有投票命令
                return await self._handle_remove_all(boardcast_info)

        # 所有用户都可以使用的命令
        if command.startswith(self.get_tr("list")):
            # 处理列出所有投票命令
            return await self._handle_list(boardcast_info)
        elif command.startswith(self.get_tr("types")):
            # 处理列出投票类型命令
            return await self._handle_types(boardcast_info)
        elif command.startswith(self.get_tr("abstain")):
            # 处理弃票命令
            return await self._handle_abstain(boardcast_info)

        # 未识别的命令，显示帮助
        return await self._handle_help(boardcast_info)

    async def process_boardcast_info(self, boardcast_info: BoardcastInfo) -> bool:
        """处理接收到的消息

        Parameters
        ----------
        boardcast_info : BoardcastInfo
            广播信息

        Returns
        -------
        bool
            消息是否被处理
        """

        # 先检查是否是开启/关闭命令
        if await self.handle_enable_disable(boardcast_info):
            return True

        if not self.enable:
            return False

        if boardcast_info.event_type != "message":
            return False

        message = boardcast_info.message
        if not message:
            return False

        first_message = message[0]
        if first_message.get("type") != "text":
            return False

        # 先检查是否是命令（如 #投票）
        if self.is_command(boardcast_info):
            return await self._handle_command(boardcast_info)

        # 如果不是命令，再检查投票关键词
        message_text = self._extract_text_from_message(message)
        self.debug_log(f"[VoteSystem Debug] 提取的消息文本: '{message_text}'")

        if message_text:
            # 检查是否是投票相关关键词
            self.debug_log(f"[VoteSystem Debug] 开始检查关键词")
            if await self._handle_keywords(boardcast_info, message_text):
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
            self, boardcast_info: BoardcastInfo, message_text: str
    ) -> bool:
        """处理关键词检测"""
        self.debug_log(f"[VoteSystem Debug] _handle_keywords 被调用，消息: '{message_text}'")

        # 检查弃票关键词（所有用户）
        self.debug_log(f"[VoteSystem Debug] 检查弃票关键词: {self.withdraw_keywords}")
        for keyword in self.withdraw_keywords:
            if message_text.startswith(keyword):
                self.debug_log(f"[VoteSystem Debug] 匹配到弃票关键词: '{keyword}'")
                # 提取序号（如果有）
                index = self._extract_vote_index(message_text, keyword)
                await self._handle_abstain_keyword(boardcast_info, index)
                return True

        # 检查取消投票关键词（仅管理员，用于删除整个投票）
        self.debug_log(f"[VoteSystem Debug] 检查取消投票关键词（管理员）: {self.delete_keywords}")
        for keyword in self.delete_keywords:
            if keyword == message_text:
                self.debug_log(f"[VoteSystem Debug] 匹配到取消投票关键词: '{keyword}'")
                if boardcast_info.is_admin:
                    await self._handle_delete(boardcast_info)
                    return True
                else:
                    self.debug_log("[VoteSystem Debug] 发送者不是管理员，忽略取消投票请求")

        # 先尝试精确匹配（用于 start_keywords）
        result = self.vote_type_registry.get_by_keyword(message_text)
        if result:
            vote_config, is_consult = result
            self.debug_log(f"[VoteSystem Debug] 精确匹配到投票关键词: '{message_text}', "
                           f"类型: {vote_config.vote_type}, 征求模式: {is_consult}")
            await self._handle_start_vote_with_config(boardcast_info, vote_config, is_consult)
            return True

        # 模糊匹配（用于 consult_keywords）
        for keyword in self.vote_type_registry.get_all_keywords():
            if keyword in message_text and keyword != message_text:
                result = self.vote_type_registry.get_by_keyword(keyword)
                if result:
                    vote_config, is_consult = result
                    if is_consult:
                        self.debug_log(f"[VoteSystem Debug] 模糊匹配到征求模式关键词: '{keyword}'")
                        await self._handle_start_vote_with_config(boardcast_info, vote_config, True)
                        return True

        # 检查投赞成票关键词
        self.debug_log(f"[VoteSystem Debug] 检查赞成票关键词: {self.yes_keywords}")
        for keyword in self.yes_keywords:
            if message_text.startswith(keyword):
                self.debug_log(f"[VoteSystem Debug] 匹配到赞成票关键词: '{keyword}'")
                # 提取序号（如果有）
                index = self._extract_vote_index(message_text, keyword)
                await self._handle_vote(boardcast_info, vote_yes=True, index=index)
                return True

        # 检查投反对票关键词
        self.debug_log(f"[VoteSystem Debug] 检查反对票关键词: {self.no_keywords}")
        for keyword in self.no_keywords:
            if message_text.startswith(keyword):
                self.debug_log(f"[VoteSystem Debug] 匹配到反对票关键词: '{keyword}'")
                # 提取序号（如果有）
                index = self._extract_vote_index(message_text, keyword)
                await self._handle_vote(boardcast_info, vote_yes=False, index=index)
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
        Optional[int]
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

    async def _handle_remove(self, boardcast_info: BoardcastInfo) -> bool:
        """处理删除投票命令（管理员）"""
        if not boardcast_info.is_admin:
            msg = self.get_tr("admin_only")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_pending_votes")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        # 从命令中提取序号
        command = boardcast_info.message[0].get("data", {}).get("text", "")
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
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        index = int(command)
        vote = self.vote_manager.get_vote_by_index(index)

        if not vote:
            msg = self.get_tr("vote_not_found", index=index)
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        success = self.vote_manager.delete_vote(vote.vote_id)
        if success:
            msg = self.get_tr(
                "vote_removed",
                admin=boardcast_info.sender,
                index=index,
                description=vote.description
            )
            await self._broadcast_to_all(msg)

        return True

    async def _handle_remove_all(self, boardcast_info: BoardcastInfo) -> bool:
        """处理删除所有投票命令（管理员）"""
        if not boardcast_info.is_admin:
            msg = self.get_tr("admin_only")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_pending_votes")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        count = 0
        for vote in pending_votes:
            if self.vote_manager.delete_vote(vote.vote_id):
                count += 1

        msg = self.get_tr(
            "all_votes_removed",
            admin=boardcast_info.sender,
            count=count
        )
        await self._broadcast_to_all(msg)

        return True

    async def _handle_list(self, boardcast_info: BoardcastInfo) -> bool:
        """处理列出所有投票命令"""
        pending_votes = self.vote_manager.get_all_pending_votes()

        if not pending_votes:
            msg = self.get_tr("no_pending_votes")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
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
                required_percentage=f"{progress["required_percentage"]}%",
                remaining_time=remaining_time
            )
            vote_items.append(item)

        header = self.get_tr("current_votes", count=len(pending_votes))
        msg = header + "\n" + "\n\n".join(vote_items)

        await self.reply(boardcast_info, [MessageBuilder.text(msg)])
        return True

    async def _handle_types(self, boardcast_info: BoardcastInfo) -> bool:
        """处理列出投票类型命令，支持分页显示"""
        # 从命令中提取页码
        command = boardcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        types_command = self.get_tr("types")

        for i in [command_prefix, system_name, types_command]:
            command = command.replace(i, "", 1).strip()

        # 解析页码
        page = 1
        if command and command.isdigit():
            page = int(command)

        # 获取所有已注册的投票类型
        all_configs = self.vote_type_registry.get_all_configs()

        if not all_configs:
            msg = self.get_tr("no_vote_types")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        # 分页配置：每页显示3个
        items_per_page = 3
        total_items = len(all_configs)
        total_pages = (total_items + items_per_page - 1) // items_per_page

        # 验证页码
        if page < 1 or page > total_pages:
            msg = self.get_tr("invalid_page_number", total_pages=total_pages)
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        # 计算当前页的起始和结束索引
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)

        # 构建投票类型列表
        vote_type_items = []
        vote_configs_list = list(all_configs.values())

        for i in range(start_idx, end_idx):
            config = vote_configs_list[i]

            # 获取翻译后的名称和描述
            name = self.get_tr(config.name_key)
            description = self.get_tr(config.description_key)

            # 格式化关键词列表
            start_keywords = ", ".join(config.start_keywords) if config.start_keywords else "无"
            consult_keywords = ", ".join(config.consult_keywords) if config.consult_keywords else "无"

            # 构建单个投票类型的信息
            item = self.get_tr(
                "vote_type_item",
                name=name,
                description=description,
                required_percentage=f"{int(config.required_percentage * 100)}%",
                timeout=int(config.timeout),
                start_keywords=start_keywords,
                consult_keywords=consult_keywords
            )
            vote_type_items.append(item)

        # 构建头部信息
        header = self.get_tr(
            "available_vote_types",
            page=page,
            total_pages=total_pages,
            count=total_items
        )

        # 构建分页导航提示
        navigation = ""
        if total_pages > 1:
            navigation = self.get_tr(
                "page_navigation",
                command_prefix=command_prefix,
                name=system_name,
                types=types_command
            )

        # 组合消息
        msg = header + "\n\n" + "\n\n".join(vote_type_items) + navigation

        await self.reply(boardcast_info, [MessageBuilder.text(msg)])
        return True

    async def _handle_abstain(self, boardcast_info: BoardcastInfo) -> bool:
        """处理弃票命令（通过命令：#投票 弃票 [序号]）"""
        # 从命令中提取序号
        command = boardcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")
        abstain_command = self.get_tr("abstain")

        for i in [command_prefix, system_name, abstain_command]:
            command = command.replace(i, "", 1).strip()

        # 解析序号
        index = None
        if command and command.isdigit():
            index = int(command)

        return await self._handle_abstain_keyword(boardcast_info, index)

    async def _handle_abstain_keyword(self, boardcast_info: BoardcastInfo, index: Optional[int] = None) -> bool:
        """处理弃票（通过关键词或命令）

        Parameters
        ----------
        boardcast_info : BoardcastInfo
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
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        # 根据序号或数量选择投票
        vote = await self._select_vote_for_abstain(boardcast_info, pending_votes, index)
        if not vote:
            return True

        # 获取投票者的QQ号
        actual_voter_id = await self._get_voter_id_from_boardcast(boardcast_info)

        if not actual_voter_id:
            msg = self.get_tr("not_eligible")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        # 检查是否有投票资格
        if actual_voter_id not in vote.eligible_voters:
            msg = self.get_tr("not_eligible")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return True

        # 执行弃票
        success = vote.withdraw_vote(actual_voter_id)
        if success:
            # 广播弃票消息
            msg = self.get_tr(
                "abstain_success",
                voter=boardcast_info.sender,
                vote_name=self._get_vote_name(vote)
            )
            await self._broadcast_to_all(msg)
        else:
            # 还没有投票，无法弃票
            msg = self.get_tr("not_voted_yet")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])

        return True

    async def _select_vote_for_abstain(
            self,
            boardcast_info: BoardcastInfo,
            pending_votes: List[Vote],
            index: Optional[int]
    ) -> Optional[Vote]:
        """为弃票操作选择投票实例

        Parameters
        ----------
        boardcast_info : BoardcastInfo
            广播信息
        pending_votes : List[Vote]
            进行中的投票列表
        index : Optional[int]
            指定的投票序号

        Returns
        -------
        Optional[Vote]
            选中的投票实例，如果无法选择则返回 None
        """
        if index is not None:
            # 指定了序号，根据序号查找
            vote = self.vote_manager.get_vote_by_index(index)
            if not vote:
                msg = self.get_tr("vote_not_found", index=index)
                await self.reply(boardcast_info, [MessageBuilder.text(msg)])
                return None
            return vote

        if len(pending_votes) == 1:
            # 只有一个投票，直接使用
            return pending_votes[0]

        # 有多个投票但没指定序号，提示用户
        vote_list = [f"[{v.index}] {v.description}" for v in pending_votes]
        abstain_example = f"{self.withdraw_keywords[0]} 1" if self.withdraw_keywords else "弃票 1"

        msg = self.get_tr(
            "multiple_votes_specify_abstain",
            count=len(pending_votes),
            vote_list="\n".join(vote_list),
            abstain_example=abstain_example
        )
        await self.reply(boardcast_info, [MessageBuilder.text(msg)])
        return None

    async def _handle_help(self, boardcast_info: BoardcastInfo) -> bool:
        """处理帮助命令"""
        # 获取配置的命令前缀和命令名称
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        # 获取子命令翻译
        enable_command = self.get_tr("gugubot.enable", global_key=True)
        disable_command = self.get_tr("gugubot.disable", global_key=True)
        list_command = self.get_tr("list")
        types_command = self.get_tr("types")
        abstain_command = self.get_tr("abstain")
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
        if boardcast_info.is_admin:
            msg = self.get_tr(
                "help_msg",
                command_prefix=command_prefix,
                name=system_name,
                enable=enable_command,
                disable=disable_command,
                list=list_command,
                types=types_command,
                abstain=abstain_command,
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
                withdraw_example=withdraw_example
            )

        await self.reply(boardcast_info, [MessageBuilder.text(msg)])
        return True

    async def _handle_start_vote_with_config(self, boardcast_info: BoardcastInfo, vote_config: VoteTypeConfig,
                                             consult_mode: bool) -> None:
        """使用配置处理开始投票"""
        self.debug_log(f"[VoteSystem Debug] 收到{vote_config.vote_type}类型的投票请求，发起人: {boardcast_info.sender}, "
                       f"ID: {boardcast_info.sender_id}, "
                       f"征求模式: {consult_mode}")

        # 获取所有在线玩家的绑定信息
        eligible_voters = await self._get_eligible_voters()

        # 获取发起者的QQ号
        initiator_voter_id = await self._get_voter_id_from_boardcast(boardcast_info)

        # 检查发起者资格（管理员可以绕过）
        if not boardcast_info.is_admin:
            if not initiator_voter_id:
                # 无法获取发起人的QQ号，无投票资格
                msg = self.get_tr("not_eligible_initiator")
                await self.reply(boardcast_info, [MessageBuilder.text(msg)])
                return

            if initiator_voter_id not in eligible_voters:
                # 发起人无投票资格
                msg = self.get_tr("not_eligible_initiator")
                await self.reply(boardcast_info, [MessageBuilder.text(msg)])
                return

        # 检查是否已有进行中的投票
        existing_vote = self.vote_manager.get_pending_vote_by_type(vote_config.vote_type)
        if existing_vote:
            msg = self.get_tr("vote_already_exists")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return

        # 检查是否有足够的合格的投票者
        if not eligible_voters:
            msg = self.get_tr("no_eligible_voters")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return

        # 创建投票
        vote = self.vote_manager.create_vote(
            vote_type=vote_config.vote_type,
            initiator=boardcast_info.sender,
            initiator_id=boardcast_info.sender_id,
            eligible_voters=eligible_voters,
            required_percentage=vote_config.required_percentage,
            timeout=vote_config.timeout,
            callback=vote_config.callback,
            description=self.get_tr(vote_config.description_key)
        )

        if not vote:
            msg = self.get_tr("vote_create_failed")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return

        # 根据模式决定是否自动投票
        if not consult_mode:
            # 非征求模式下，发起人自动投赞成票
            # 如果发起人有投票资格，使用其QQ号投票
            # 如果是管理员绕过的情况，使用 sender_id 作为虚拟投票者ID
            self.debug_log(f"[VoteSystem Debug] 非征求模式，准备自动投票")
            self.debug_log(f"[VoteSystem Debug] initiator_voter_id: {initiator_voter_id}")
            self.debug_log(f"[VoteSystem Debug] eligible_voters: {eligible_voters}")
            self.debug_log(f"[VoteSystem Debug] is_admin: {boardcast_info.is_admin}")

            if initiator_voter_id and initiator_voter_id in eligible_voters:
                self.debug_log(f"[VoteSystem Debug] ✓ 发起人有投票资格，投赞成票: {initiator_voter_id}")
                success, is_new = vote.cast_vote(initiator_voter_id, True)
                self.debug_log(f"[VoteSystem Debug] cast_vote返回值: success={success}, is_new={is_new}")
                self.debug_log(f"[VoteSystem Debug] 投票后yes_votes: {vote.yes_votes}")
                self.debug_log(f"[VoteSystem Debug] 投票后no_votes: {vote.no_votes}")
            elif boardcast_info.is_admin:
                # 管理员绕过：将管理员的 sender_id 临时添加到投票资格中
                self.debug_log(f"[VoteSystem Debug] ✓ 管理员绕过在线限制，直接发起投票并投赞成票: {boardcast_info.sender_id}")
                vote.eligible_voters.add(boardcast_info.sender_id)
                success, is_new = vote.cast_vote(boardcast_info.sender_id, True)
            else:
                self.debug_log(f"[VoteSystem Debug] ✗ 发起人无法自动投票")

        # 检查投票在开始就被满足（例如可投票成员只有一位）
        if self.vote_manager.check_and_finalize_vote(vote.vote_id) == VoteStatus.PASSED:
            await self._handle_vote_result(vote, VoteStatus.PASSED)
            return

        # 检查是否有多个投票
        pending_votes = self.vote_manager.get_all_pending_votes()
        has_multiple_votes = len(pending_votes) > 1

        # 广播投票开始消息
        self.debug_log(f"[VoteSystem Debug] 准备获取投票进度，当前yes_votes: {vote.yes_votes}")
        progress = vote.get_progress()
        self.debug_log(f"[VoteSystem Debug] get_progress返回: {progress}")

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
                initiator=boardcast_info.sender,
                vote_name=vote_name,
                description=vote.description,
                total_voters=progress["total_voters"],
                required_percentage=f"{progress["required_percentage"]}%",
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
                initiator=boardcast_info.sender,
                vote_name=vote_name,
                description=vote.description,
                total_voters=progress["total_voters"],
                required_percentage=f"{progress["required_percentage"]}%",
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
        self._monitor_task = asyncio.create_task(self._monitor_vote(vote.vote_id))

    async def _handle_vote(self, boardcast_info: BoardcastInfo, vote_yes: bool, index: Optional[int] = None) -> None:
        """处理投票（赞成或反对）

        Parameters
        ----------
        boardcast_info : BoardcastInfo
            广播信息
        vote_yes : bool
            True为投赞成票，False为投反对票
        index : Optional[int]
            投票序号，如果为 None 则自动选择
        """
        # 获取进行中的投票
        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            return

        # 根据序号或数量选择投票
        if index is not None:
            # 指定了序号，根据序号查找
            vote = self.vote_manager.get_vote_by_index(index)
            if not vote:
                msg = self.get_tr("vote_not_found", index=index)
                await self.reply(boardcast_info, [MessageBuilder.text(msg)])
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
            msg = self.get_tr(
                tr_key,
                count=len(pending_votes),
                vote_list="\n".join(vote_list),
                yes_example=example if vote_yes else None,
                no_example=example if not vote_yes else None
            )
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return

        # 获取投票者的QQ号（统一使用QQ号作为投票者ID）
        actual_voter_id = await self._get_voter_id_from_boardcast(boardcast_info)

        if not actual_voter_id:
            self.debug_log(f"[VoteSystem Debug] 无法获取投票者 {boardcast_info.sender} 的QQ号")
            msg = self.get_tr("not_eligible")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            self.debug_log(f"§c[投票调试] {boardcast_info.sender} 无法获取QQ号", to_server=True)
            return

        self.debug_log(f"[VoteSystem Debug] 投票者 {boardcast_info.sender} (sender_id: {boardcast_info.sender_id}) -> QQ: {actual_voter_id}")
        self.debug_log(f"§e[投票调试] {boardcast_info.sender} 的QQ: {actual_voter_id}", to_server=True)

        # 检查是否有投票资格
        if actual_voter_id not in vote.eligible_voters:
            self.debug_log(f"[VoteSystem Debug] QQ {actual_voter_id} 不在投票资格列表中")
            self.debug_log(f"§c[投票调试] QQ {actual_voter_id} 不在投票资格列表中", to_server=True)
            self.debug_log(f"§c[投票调试] 资格列表: {vote.eligible_voters}", to_server=True)
            msg = self.get_tr("not_eligible")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return

        # 投票
        self.debug_log(f"[VoteSystem Debug] 准备投票，voter_id: {actual_voter_id}, vote_yes: {vote_yes}")
        self.debug_log(f"[VoteSystem Debug] 投票前yes_votes: {vote.yes_votes}")
        self.debug_log(f"[VoteSystem Debug] 投票前no_votes: {vote.no_votes}")
        success, is_new_vote = vote.cast_vote(actual_voter_id, vote_yes)
        self.debug_log(f"[VoteSystem Debug] 投票后yes_votes: {vote.yes_votes}")
        self.debug_log(f"[VoteSystem Debug] 投票后no_votes: {vote.no_votes}")
        if success:
            progress = vote.get_progress()
            vote_type_tr = self.get_tr("vote_yes" if vote_yes else "vote_no")
            # 根据是新票还是改票使用不同的翻译键
            tr_key = "vote_new" if is_new_vote else "vote_changed"
            msg = self.get_tr(
                tr_key,
                voter=boardcast_info.sender,
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
                # 取消监控任务
                if self._monitor_task:
                    self._monitor_task.cancel()

    async def _handle_delete(self, boardcast_info: BoardcastInfo) -> None:
        """处理取消投票（仅管理员）"""
        # 获取进行中的投票
        pending_votes = self.vote_manager.get_all_pending_votes()
        if not pending_votes:
            msg = self.get_tr("no_active_vote")
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
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
            await self.reply(boardcast_info, [MessageBuilder.text(msg)])
            return

        success = self.vote_manager.delete_vote(vote.vote_id)
        if success:
            msg = self.get_tr(
                "vote_deleted",
                admin=boardcast_info.sender,
                vote_name=self._get_vote_name(vote)
            )
            await self._broadcast_to_all(msg)

            # 取消监控任务
            if self._monitor_task:
                self._monitor_task.cancel()

    async def _monitor_vote(self, vote_id: str) -> None:
        """监控投票超时

        参数
        ----------
        vote_id : str
            投票ID

        说明
        ----
        赞成/反对票在投票发起/触发时已立即检查（check_and_finalize_vote），
        本方法只负责监控投票超时。
        """
        try:
            import time

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
                current_percentage=f"{progress['current_percentage']:.1f}"
            )
            await self._broadcast_to_all(msg)

            # 执行回调
            if vote.callback:
                try:
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
                required_percentage=f"{progress["required_percentage"]}%"
            )
            await self._broadcast_to_all(msg)

    async def _get_eligible_voters(self) -> Set[str]:
        """获取有投票资格的用户ID集合

        Returns
        -------
        Set[str]
            有投票资格的用户ID集合
        """
        eligible = set()

        try:
            # 获取在线玩家列表
            online_players = self._get_online_players()
            self.debug_log(f"[VoteSystem Debug] 在线玩家列表: {online_players}")
            self.debug_log(f"[VoteSystem Debug] 在线玩家数量: {len(online_players)}")
            self.debug_log(f"§e[投票调试] 在线玩家: {', '.join(online_players) if online_players else '无'}",
                           to_server=True)

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

                if player:
                    self.debug_log(f"[VoteSystem Debug] 找到玩家对象: {player.name}")

                    # 获取该玩家的QQ账号列表
                    qq_ids = player.accounts.get(qq_source, [])
                    self.debug_log(f"[VoteSystem Debug] 玩家 '{player_name}' 绑定的QQ: {qq_ids}")

                    if qq_ids:
                        eligible.update([qq_id for qq_id in qq_ids])
                        self.debug_log(f"§a[投票调试] {player_name} 已绑定QQ，有投票资格", to_server=True)
                    else:
                        self.debug_log(f"[VoteSystem Debug] 玩家 '{player_name}' 没有绑定QQ")
                        self.debug_log(f"§c[投票调试] {player_name} 未绑定QQ，无投票资格", to_server=True)
                else:
                    self.debug_log(f"[VoteSystem Debug] 在PlayerManager中找不到玩家 '{player_name}'")
                    self.debug_log(f"§c[投票调试] 找不到玩家 {player_name} 的绑定信息", to_server=True)

            self.debug_log(f"[VoteSystem Debug] 最终有投票资格的QQ号集合: {eligible}")
            self.debug_log(f"[VoteSystem Debug] 有投票资格的人数: {len(eligible)}")
            self.debug_log(f"§e[投票调试] 总共 {len(eligible)} 人有投票资格", to_server=True)

        except Exception as e:
            self.logger.error(f"[VoteSystem] 获取投票资格用户失败: {e}")
            import traceback
            self.logger.error(f"[VoteSystem Debug] 异常堆栈:\n{traceback.format_exc()}")
            self.debug_log(f"§c[投票调试] 获取投票资格失败: {e}", to_server=True)

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
        player = self.player_manager.get_player(sender_name)

        if player:
            qq_ids = player.accounts.get(qq_source, [])
            self.debug_log(f"[VoteSystem Debug] 玩家 '{sender_name}' 的QQ号: {qq_ids}")
            return [str(qq_id) for qq_id in qq_ids] if qq_ids else []
        else:
            self.debug_log(f"[VoteSystem Debug] 在PlayerManager中找不到玩家 '{sender_name}'")
            return []

    async def _get_voter_id_from_boardcast(self, boardcast_info: BoardcastInfo) -> Optional[str]:
        """从BoardcastInfo获取唯一的投票者ID（QQ号）

        根据消息来源判断：
        - 如果来自QQ connector，sender_id就是QQ号，直接使用
        - 如果来自其他connector（MC等），sender_id是玩家名，从PlayerManager查询玩家绑定的QQ号

        Parameters
        ----------
        boardcast_info : BoardcastInfo
            广播信息

        Returns
        -------
        Optional[str]
            投票者的QQ号，如果无法获取则返回None
        """
        # 获取QQ connector的source_name（用户可能自定义了名称）
        qq_source = self.config.get_keys(["connector", "QQ", "source_name"], "QQ")

        # 获取消息的原始来源
        message_source = boardcast_info.source.origin
        sender_id = str(boardcast_info.sender_id)

        self.debug_log(f"[VoteSystem Debug] 消息来源: {message_source}, QQ source配置: {qq_source}, sender_id: {sender_id}")

        # 判断消息是否来自QQ connector
        if message_source == qq_source:
            # 来自QQ connector，sender_id就是QQ号
            self.debug_log(f"[VoteSystem Debug] ✓ 消息来自QQ connector，直接使用sender_id作为QQ号: {sender_id}")
            return sender_id

        # 来自其他connector（MC等），sender_id是玩家名，需要查询绑定的QQ号
        self.debug_log(f"[VoteSystem Debug] ✗ 消息不是来自QQ connector，识别为玩家名: {sender_id}")
        voter_ids = await self._get_voter_ids(sender_id)
        if voter_ids:
            voter_id = voter_ids[0]  # 使用第一个绑定的QQ号
            self.debug_log(f"[VoteSystem Debug] ✓ 查询到玩家 '{sender_id}' 的QQ号: {voter_id}")
            return voter_id
        else:
            self.debug_log(f"[VoteSystem Debug] ✗ 无法获取玩家 {sender_id} 的绑定QQ号")
            return None

    def _get_online_players(self) -> list:
        """获取在线玩家列表

        Returns
        -------
        list
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
        """关闭服务器的回调函数"""
        try:
            self.logger.info("[VoteSystem] 执行关闭服务器")

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

        这个方法会将投票消息广播到当前 MC 服务器和连接的 QQ 群，
        但不会转发到其他服务器（避免跨服务器冲突）

        Parameters
        ----------
        message : str
            要广播的消息
        """
        try:
            from gugubot.utils.types import ProcessedInfo, Source

            # 获取当前服务器的标识符
            server_name = self.config.get_keys(
                ["connector", "minecraft", "source_name"], "Minecraft"
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
                    processed_info
                )

        except Exception as e:
            self.logger.error(f"[VoteSystem] 广播消息失败: {e}")

    def extract_keyword_example(self, keywords: Optional[List[str]] = None, count: int = 2) -> str:
        """提取关键词中的前两位作为例子，用于帮助消息显示
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
        return f" {self.get_tr("or")} ".join(keywords[:count]) if len(keywords) > 1 else keywords[0]


