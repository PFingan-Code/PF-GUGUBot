# -*- coding: utf-8 -*-
"""投票管理器模块

该模块提供独立的投票功能，支持：
- 可配置的同意百分比
- 可调用自定义回调函数
- 自动超时取消
- 多种投票类型支持
- 投票类型注册器，允许动态扩展投票类型
"""

import time
from typing import Optional, Callable, Dict, Set, List, Awaitable
from enum import Enum
from dataclasses import dataclass
from mcdreforged.api.types import PluginServerInterface



class VoteStatus(Enum):
    """投票状态枚举"""
    PENDING = "pending"      # 进行中
    PASSED = "passed"        # 通过
    REJECTED = "rejected"    # 否决
    CANCELLED = "cancelled"  # 取消
    TIMEOUT = "timeout"      # 超时
    ERROR = "error"          # 错误


@dataclass
class VoteTypeConfig:
    """投票类型配置

    Attributes
    ----------
    vote_type : str
        投票类型标识符（唯一），如 "shutdown"
    name_key : str
        投票名称的翻译键，如 "shutdown_name"
    description_key : str
        投票描述的翻译键，如 "shutdown_description"
    required_percentage : float
        需要的同意百分比 (0.0-1.0)，默认1.0
    timeout : float
        超时时间（秒），默认300秒
    callback : Optional[Callable[[], Awaitable[None]]]
        投票通过后的回调函数
    start_keywords : Optional[list[str]]
        触发投票的关键词列表（精确匹配）
    consult_keywords : Optional[list[str]]
        触发征求模式投票的关键词列表（模糊匹配）
    """
    vote_type: str
    name_key: str
    description_key: str
    required_percentage: float = 1.0
    timeout: float = 300.0
    callback: Optional[Callable[[], Awaitable[None]]] = None
    start_keywords: Optional[list[str]] = None
    consult_keywords: Optional[list[str]] = None

    def __post_init__(self):
        """初始化默认值"""
        if self.start_keywords is None:
            self.start_keywords = []
        if self.consult_keywords is None:
            self.consult_keywords = []


class VoteTypeRegistry:
    """投票类型注册器

    管理所有已注册的投票类型配置。支持注册、注销和查询投票类型。
    """

    def __init__(self):
        """初始化投票类型注册器"""
        self._registry: Dict[str, VoteTypeConfig] = {}
        self._keyword_map: Dict[str, str] = {}  # 关键词到投票类型的映射

    def register(self, config: VoteTypeConfig) -> bool:
        """注册投票类型"""
        if config.vote_type in self._registry:
            return False

        self._registry[config.vote_type] = config

        # 注册关键词映射
        for keyword in config.start_keywords:
            self._keyword_map[keyword] = config.vote_type
        for keyword in config.consult_keywords:
            self._keyword_map[keyword] = config.vote_type

        return True

    def unregister(self, vote_type: str) -> bool:
        """注销投票类型"""
        if vote_type not in self._registry:
            return False

        config = self._registry[vote_type]

        # 移除关键词映射
        for keyword in config.start_keywords + config.consult_keywords:
            self._keyword_map.pop(keyword, None)

        del self._registry[vote_type]
        return True

    def get_config(self, vote_type: str) -> Optional[VoteTypeConfig]:
        """获取投票类型配置"""
        return self._registry.get(vote_type)

    def get_by_keyword(self, keyword: str) -> Optional[tuple[VoteTypeConfig, bool]]:
        """根据关键词获取投票类型配置

        Returns
        -------
        Optional[tuple[VoteTypeConfig, bool]]
            (投票类型配置, 是否为征求模式)，如果关键词未注册则返回None
        """
        vote_type = self._keyword_map.get(keyword)
        if vote_type is None:
            return None

        config = self._registry[vote_type]
        is_consult = keyword in config.consult_keywords
        return config, is_consult

    def get_all_configs(self) -> Dict[str, VoteTypeConfig]:
        """获取所有已注册的投票类型配置"""
        return self._registry.copy()

    def is_registered(self, vote_type: str) -> bool:
        """检查投票类型是否已注册"""
        return vote_type in self._registry

    def get_all_keywords(self) -> list[str]:
        """获取所有已注册的关键词"""
        return list(self._keyword_map.keys())

    def clear(self):
        """清空所有已注册的投票类型"""
        self._registry.clear()
        self._keyword_map.clear()


class Vote:
    """投票实例类

    Attributes
    ----------
    vote_id : str
        投票唯一ID
    vote_type : str
        投票类型（字符串）
    initiator : str
        发起人
    initiator_id : str
        发起人ID
    eligible_voters : Set[str]
        有资格投票的用户ID集合
    required_percentage : float
        需要的同意百分比 (0.0-1.0)
    timeout : float
        超时时间（秒）
    callback : Optional[Callable]
        投票通过后的回调函数
    yes_votes : Set[str]
        赞成票用户ID集合
    no_votes : Set[str]
        反对票用户ID集合
    status : VoteStatus
        投票状态
    start_time : float
        开始时间
    description : str
        投票描述
    index : int
        投票序号
    """

    def __init__(
        self,
        vote_id: str,
        vote_type: str,
        initiator: str,
        initiator_id: str,
        eligible_voters: Set[str],
        required_percentage: float = 1.0,
        timeout: float = 300.0,
        callback: Optional[Callable[[], Awaitable[None]]] = None,
        description: str = "",
        index: int = 1
    ):
        """初始化投票实例

        Parameters
        ----------
        vote_id : str
            投票唯一ID
        vote_type : str
            投票类型（字符串）
        initiator : str
            发起人名称
        initiator_id : str
            发起人ID
        eligible_voters : Set[str]
            有资格投票的用户ID集合
        required_percentage : float
            需要的同意百分比，默认1.0（100%）
        timeout : float
            超时时间（秒），默认300秒
        callback : Optional[Callable]
            投票通过后的回调函数
        description : str
            投票描述
        index : int
            投票序号
        """
        self.vote_id = vote_id
        self.vote_type = vote_type
        self.initiator = initiator
        self.initiator_id = initiator_id
        self.eligible_voters = eligible_voters.copy()
        self.required_percentage = max(0.0, min(1.0, required_percentage))
        self.timeout = timeout
        self.callback = callback
        self.description = description
        self.index = index

        self.yes_votes: Set[str] = set()
        self.no_votes: Set[str] = set()
        self.status = VoteStatus.PENDING
        self.start_time = time.time()

    def cast_vote(self, voter_id: str, vote_yes: bool) -> tuple[bool, bool]:
        """投票

        Parameters
        ----------
        voter_id : str
            投票者ID
        vote_yes : bool
            True为赞成，False为反对

        Returns
        -------
        tuple[bool, bool]
            第一个bool表示是否投票成功，第二个bool表示是否为新投票（True=新投票，False=改票）
        """
        if self.status != VoteStatus.PENDING:
            return False, False

        if voter_id not in self.eligible_voters:
            return False, False

        # 检查是否已经投过票（用于判断是新投票还是改票）
        is_new_vote = voter_id not in self.yes_votes and voter_id not in self.no_votes

        # 移除之前的投票
        self.yes_votes.discard(voter_id)
        self.no_votes.discard(voter_id)

        # 记录新投票
        if vote_yes:
            self.yes_votes.add(voter_id)
        else:
            self.no_votes.add(voter_id)

        return True, is_new_vote

    def withdraw_vote(self, voter_id: str) -> bool:
        """撤回投票（弃票）

        Parameters
        ----------
        voter_id : str
            投票者ID

        Returns
        -------
        bool
            是否撤回成功
        """
        if self.status != VoteStatus.PENDING:
            return False

        if voter_id not in self.eligible_voters:
            return False

        # 检查是否已投票
        if voter_id not in self.yes_votes and voter_id not in self.no_votes:
            return False

        # 移除投票
        self.yes_votes.discard(voter_id)
        self.no_votes.discard(voter_id)

        return True

    def check_result(self) -> Optional[VoteStatus]:
        """检查投票结果

        Returns
        -------
        Optional[VoteStatus]
            如果投票有结果则返回状态，否则返回None
        """
        if self.status != VoteStatus.PENDING:
            return self.status

        total_voters = len(self.eligible_voters)
        if total_voters == 0:
            return None

        yes_count = len(self.yes_votes)
        no_count = len(self.no_votes)
        voted_count = yes_count + no_count

        # 计算当前同意比例
        current_percentage = yes_count / total_voters if total_voters > 0 else 0.0

        # 检查是否已达到通过条件
        if current_percentage >= self.required_percentage:
            self.status = VoteStatus.PASSED
            return self.status

        # 检查是否不可能通过（剩余票数不足）
        remaining = total_voters - voted_count
        max_possible = (yes_count + remaining) / total_voters if total_voters > 0 else 0.0
        if max_possible < self.required_percentage:
            self.status = VoteStatus.REJECTED
            return self.status

        # 检查是否超时
        if time.time() - self.start_time > self.timeout:
            self.status = VoteStatus.TIMEOUT
            return self.status

        # 投票仍在进行中
        return None

    def cancel(self) -> bool:
        """取消投票

        Returns
        -------
        bool
            是否取消成功
        """
        if self.status != VoteStatus.PENDING:
            return False

        self.status = VoteStatus.CANCELLED
        return True

    def get_progress(self) -> Dict:
        """获取投票进度

        Returns
        -------
        Dict
            包含投票进度信息的字典
        """
        total = len(self.eligible_voters)
        yes_count = len(self.yes_votes)
        no_count = len(self.no_votes)
        voted_count = yes_count + no_count
        remaining = total - voted_count

        current_percentage = (yes_count / total * 100) if total > 0 else 0.0
        required_yes = int(total * self.required_percentage)

        elapsed = time.time() - self.start_time
        remaining_time = max(0, self.timeout - elapsed)

        return {
            "vote_id": self.vote_id,
            "type": self.vote_type,
            "status": self.status.value,
            "description": self.description,
            "initiator": self.initiator,
            "total_voters": total,
            "yes_votes": yes_count,
            "no_votes": no_count,
            "not_voted": remaining,
            "voted_count": voted_count,
            "current_percentage": current_percentage,
            "required_percentage": self.required_percentage * 100,
            "required_yes": required_yes,
            "elapsed_time": elapsed,
            "remaining_time": remaining_time,
            "timeout": self.timeout
        }


class VoteManager:
    """投票管理器

    管理所有进行中的投票实例

    Attributes
    ----------
    active_votes : Dict[str, Vote]
        当前活动的投票字典
    logger : Any
        日志记录器
    """

    def __init__(self, server: PluginServerInterface):
        """初始化投票管理器

        """
        self.active_votes: Dict[str, Vote] = {}
        self.logger = server.logger
        self._vote_counter = 0

    def create_vote(
        self,
        vote_type: str,
        initiator: str,
        initiator_id: str,
        eligible_voters: Set[str],
        required_percentage: float = 1.0,
        timeout: float = 300.0,
        callback: Optional[Callable[[], Awaitable[None]]] = None,
        description: str = ""
    ) -> Optional[Vote]:
        """创建新投票

        Parameters
        ----------
        vote_type : str
            投票类型（字符串）
        initiator : str
            发起人名称
        initiator_id : str
            发起人ID
        eligible_voters : Set[str]
            有资格投票的用户ID集合
        required_percentage : float
            需要的同意百分比，默认1.0
        timeout : float
            超时时间（秒），默认300秒
        callback : Optional[Callable]
            投票通过后的回调函数
        description : str
            投票描述

        Returns
        -------
        Optional[Vote]
            创建的投票实例，如果已存在同类型投票则返回None
        """
        # 检查是否已有相同类型的进行中投票
        for vote in self.active_votes.values():
            if vote.vote_type == vote_type and vote.status == VoteStatus.PENDING:
                if self.logger:
                    self.logger.warning(
                        f"[VoteManager] 已存在进行中的 {vote_type} 投票"
                    )
                return None

        # 生成唯一ID
        self._vote_counter += 1
        vote_id = f"{vote_type}_{self._vote_counter}_{int(time.time())}"

        # 计算当前投票的索引序号（基于当前进行中的投票数量）
        pending_count = len(self.get_all_pending_votes())
        index = pending_count + 1

        # 创建投票实例
        vote = Vote(
            vote_id=vote_id,
            vote_type=vote_type,
            initiator=initiator,
            initiator_id=initiator_id,
            eligible_voters=eligible_voters,
            required_percentage=required_percentage,
            timeout=timeout,
            callback=callback,
            description=description,
            index=index
        )

        self.active_votes[vote_id] = vote

        if self.logger:
            self.logger.info(
                f"[VoteManager] 创建投票: {vote_id}, 类型: {vote_type}, "
                f"发起人: {initiator}, 序号: {index}"
            )

        return vote

    def get_vote(self, vote_id: str) -> Optional[Vote]:
        """获取投票实例

        Parameters
        ----------
        vote_id : str
            投票ID

        Returns
        -------
        Optional[Vote]
            投票实例，不存在则返回None
        """
        return self.active_votes.get(vote_id)

    def get_vote_by_index(self, index: int) -> Optional[Vote]:
        """根据索引获取进行中的投票

        Parameters
        ----------
        index : int
            投票序号

        Returns
        -------
        Optional[Vote]
            进行中的投票实例，不存在则返回None
        """
        for vote in self.active_votes.values():
            if vote.status == VoteStatus.PENDING and vote.index == index:
                return vote
        return None

    def get_pending_vote_by_type(self, vote_type: str) -> Optional[Vote]:
        """根据类型获取进行中的投票

        Parameters
        ----------
        vote_type : str
            投票类型（字符串）

        Returns
        -------
        Optional[Vote]
            进行中的投票实例，不存在则返回None
        """
        for vote in self.active_votes.values():
            if vote.vote_type == vote_type and vote.status == VoteStatus.PENDING:
                return vote
        return None

    def cast_vote(self, vote_id: str, voter_id: str, vote_yes: bool) -> tuple[bool, bool]:
        """投票

        Parameters
        ----------
        vote_id : str
            投票ID
        voter_id : str
            投票者ID
        vote_yes : bool
            True为赞成，False为反对

        Returns
        -------
        tuple[bool, bool]
            第一个bool表示是否投票成功，第二个bool表示是否为新投票（True=新投票，False=改票）
        """
        vote = self.get_vote(vote_id)
        if not vote:
            return False, False

        success, is_new_vote = vote.cast_vote(voter_id, vote_yes)

        if success and self.logger:
            self.logger.debug(
                f"[VoteManager] 用户 {voter_id} 对投票 {vote_id} "
                f"投了{'赞成' if vote_yes else '反对'}票{'（新投票）' if is_new_vote else '（改票）'}"
            )

        return success, is_new_vote

    def delete_vote(self, vote_id: str) -> bool:
        """取消投票

        Parameters
        ----------
        vote_id : str
            投票ID

        Returns
        -------
        bool
            是否取消成功
        """
        vote = self.get_vote(vote_id)
        if not vote:
            return False

        success = vote.cancel()

        if success and self.logger:
            self.logger.info(f"[VoteManager] 投票 {vote_id} 已取消")

        return success

    def check_and_finalize_vote(self, vote_id: str) -> Optional[VoteStatus]:
        """检查并结束投票

        Parameters
        ----------
        vote_id : str
            投票ID

        Returns
        -------
        Optional[VoteStatus]
            投票最终状态，如果投票未结束则返回None
        """
        vote = self.get_vote(vote_id)
        if not vote:
            return None

        result = vote.check_result()

        if result and self.logger:
            self.logger.info(
                f"[VoteManager] 投票 {vote_id} 结束，结果: {result.value}"
            )

        return result

    def get_all_pending_votes(self) -> List[Vote]:
        """获取所有进行中的投票

        Returns
        -------
        List[Vote]
            进行中的投票列表
        """
        return [
            vote for vote in self.active_votes.values()
            if vote.status == VoteStatus.PENDING
        ]

    def cleanup_finished_votes(self, keep_recent_minutes: int = 10) -> int:
        """清理已结束的投票

        Parameters
        ----------
        keep_recent_minutes : int
            保留最近N分钟内的已结束投票，默认10分钟

        Returns
        -------
        int
            清理的投票数量
        """
        if keep_recent_minutes < 0:
            keep_recent_minutes = 0

        current_time = time.time()
        cutoff_time = current_time - (keep_recent_minutes * 60)

        to_remove = []
        for vote_id, vote in self.active_votes.items():
            if vote.status != VoteStatus.PENDING:
                if vote.start_time < cutoff_time:
                    to_remove.append(vote_id)

        for vote_id in to_remove:
            del self.active_votes[vote_id]

        if to_remove and self.logger:
            self.logger.debug(
                f"[VoteManager] 清理了 {len(to_remove)} 个已结束的投票"
            )

        return len(to_remove)

