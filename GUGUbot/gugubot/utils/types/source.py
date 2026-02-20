"""消息来源类模块。

该模块提供了 Source 类，用于追踪消息经过的来源链。
例如：消息从 QQ 发出，经过 Bridge 转发，则来源链为 ["QQ", "Bridge"]。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class Source:
    """消息来源类，用于追踪消息的来源链。

    Attributes
    ----------
    chain : List[str]
        来源链列表，按时间顺序记录消息经过的所有来源。
        例如：["QQ", "Bridge"] 表示消息从 QQ 发出，经过 Bridge 转发。

    Examples
    --------
    >>> source = Source("QQ")
    >>> source.origin
    'QQ'
    >>> source.current
    'QQ'
    >>> source.add("Bridge")
    >>> source.chain
    ['QQ', 'Bridge']
    >>> source.origin
    'QQ'
    >>> source.current
    'Bridge'
    >>> source.is_from("QQ")
    True
    >>> "Bridge" in source
    True
    """

    chain: List[str] = field(default_factory=list)

    def __init__(self, source: Optional[Union[str, List[str], "Source"]] = None):
        """初始化 Source 对象。

        Parameters
        ----------
        source : Union[str, List[str], Source], optional
            初始来源，可以是：
            - str: 单个来源名称
            - List[str]: 来源链列表
            - Source: 另一个 Source 对象（会复制其 chain）
            - None: 空来源链
        """
        if source is None:
            self.chain = []
        elif isinstance(source, str):
            self.chain = [source] if source else []
        elif isinstance(source, Source):
            self.chain = source.chain.copy()
        elif isinstance(source, list):
            self.chain = [s for s in source if s]  # 过滤空字符串
        else:
            self.chain = []

    @property
    def origin(self) -> str:
        """获取原始来源（链中的第一个元素）。

        Returns
        -------
        str
            原始来源名称，如果链为空则返回空字符串。
        """
        return self.chain[0] if self.chain else ""

    @property
    def current(self) -> str:
        """获取当前来源（链中的最后一个元素）。

        Returns
        -------
        str
            当前来源名称，如果链为空则返回空字符串。
        """
        return self.chain[-1] if self.chain else ""

    def add(self, source: str) -> "Source":
        """添加新来源到链末尾。

        Parameters
        ----------
        source : str
            要添加的来源名称

        Returns
        -------
        Source
            返回 self，支持链式调用
        """
        if source and source not in self.chain:
            self.chain.append(source)
        return self

    def copy(self) -> "Source":
        """创建当前 Source 的副本。

        Returns
        -------
        Source
            新的 Source 对象，包含相同的 chain
        """
        return Source(self.chain.copy())

    def with_added(self, source: str) -> "Source":
        """返回添加新来源后的副本（不修改原对象）。

        Parameters
        ----------
        source : str
            要添加的来源名称

        Returns
        -------
        Source
            新的 Source 对象
        """
        new_source = self.copy()
        new_source.add(source)
        return new_source

    def is_from(self, source: str) -> bool:
        """检查消息是否来自指定来源（检查原始来源）。

        Parameters
        ----------
        source : str
            要检查的来源名称

        Returns
        -------
        bool
            如果原始来源匹配则返回 True
        """
        return self.origin == source

    def is_current(self, source: str) -> bool:
        """检查当前来源是否是指定来源。

        Parameters
        ----------
        source : str
            要检查的来源名称

        Returns
        -------
        bool
            如果当前来源匹配则返回 True
        """
        return self.current == source

    def contains(self, source: str) -> bool:
        """检查来源链中是否包含指定来源。

        Parameters
        ----------
        source : str
            要检查的来源名称

        Returns
        -------
        bool
            如果链中包含该来源则返回 True
        """
        return source in self.chain

    def passed_through(self, source: str) -> bool:
        """检查消息是否经过了指定来源（不包括原始来源）。

        Parameters
        ----------
        source : str
            要检查的来源名称

        Returns
        -------
        bool
            如果消息经过了该来源则返回 True
        """
        return source in self.chain[1:] if len(self.chain) > 1 else False

    def __contains__(self, source: str) -> bool:
        """支持 `in` 操作符。

        Parameters
        ----------
        source : str
            要检查的来源名称

        Returns
        -------
        bool
            如果链中包含该来源则返回 True
        """
        return self.contains(source)

    def __eq__(self, other: object) -> bool:
        """比较两个 Source 对象是否相等。

        支持与 Source、str、List[str] 比较：
        - Source: 比较 chain 是否相等
        - str: 比较 origin 是否等于该字符串（向后兼容）
        - List[str]: 比较 chain 是否相等
        """
        if isinstance(other, Source):
            return self.chain == other.chain
        elif isinstance(other, str):
            # 向后兼容：与字符串比较时，比较 origin
            return self.origin == other
        elif isinstance(other, list):
            return self.chain == other
        return False

    def __str__(self) -> str:
        """返回字符串表示。

        Returns
        -------
        str
            如果只有一个元素，返回该元素；否则返回 "origin->current" 格式
        """
        if not self.chain:
            return ""
        if len(self.chain) == 1:
            return self.chain[0]
        return f"{self.origin}->{self.current}"

    def __repr__(self) -> str:
        """返回详细的字符串表示。"""
        return f"Source({self.chain})"

    def __len__(self) -> int:
        """返回来源链的长度。"""
        return len(self.chain)

    def __bool__(self) -> bool:
        """检查来源链是否非空。"""
        return bool(self.chain)

    def __hash__(self) -> int:
        """返回哈希值，使 Source 可以用作字典键。"""
        return hash(tuple(self.chain))

    def to_list(self) -> List[str]:
        """转换为列表格式（用于序列化）。

        Returns
        -------
        List[str]
            来源链列表
        """
        return self.chain.copy()

    def to_dict(self) -> dict:
        """转换为字典格式（用于序列化）。

        Returns
        -------
        dict
            包含 chain 的字典
        """
        return {"chain": self.chain.copy()}

    @classmethod
    def from_list(cls, data: List[str]) -> "Source":
        """从列表创建 Source 对象。

        Parameters
        ----------
        data : List[str]
            来源链列表

        Returns
        -------
        Source
            新的 Source 对象
        """
        return cls(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        """从字典创建 Source 对象。

        Parameters
        ----------
        data : dict
            包含 chain 键的字典

        Returns
        -------
        Source
            新的 Source 对象
        """
        return cls(data.get("chain", []))

    @classmethod
    def from_any(cls, data: Optional[Union[str, List[str], dict, "Source"]]) -> "Source":
        """从任意格式创建 Source 对象（用于反序列化）。

        Parameters
        ----------
        data : Union[str, List[str], dict, Source], optional
            可以是字符串、列表、字典或 Source 对象

        Returns
        -------
        Source
            新的 Source 对象
        """
        if data is None:
            return cls()
        if isinstance(data, Source):
            return data.copy()
        if isinstance(data, str):
            return cls(data)
        if isinstance(data, list):
            return cls.from_list(data)
        if isinstance(data, dict):
            return cls.from_dict(data)
        return cls()
