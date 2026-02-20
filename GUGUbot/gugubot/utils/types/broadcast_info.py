from dataclasses import dataclass, field
from logging import Logger
from typing import Any, List, Literal, Optional, Union

from mcdreforged.api.types import PluginServerInterface

from gugubot.utils.types.source import Source


@dataclass
class BroadcastInfo:
    """广播信息类，用于在系统间传递消息。

    Attributes
    ----------
    event_type : Literal["message", "notice", "request"]
        事件类型
    event_sub_type : str
        事件子类型（如 "group", "private"）
    message : List[dict]
        消息内容列表
    raw : Any
        原始消息数据
    source_id : str
        来源ID（如QQ群号、服务器名）
    sender : str
        发送者名称
    sender_id : str
        发送者ID
    receiver : Optional[str]
        消息接收者（回复消息时的原发送者）
    is_admin : bool
        发送者是否是管理员
    target : Optional[dict]
        目标字典，指定消息发送的目标
    """

    event_type: Literal["message", "notice", "request"]
    event_sub_type: str
    message: List[dict]

    raw: Any

    server: Optional[PluginServerInterface] = None
    logger: Optional[Logger] = None

    _source: Source = field(default_factory=Source)
    source_id: str = ""
    sender: str = ""
    sender_id: str = ""
    receiver: Optional[str] = None  # 消息的接收者（例如回复消息时的原发送者）

    is_admin: bool = False

    target: Optional[dict] = (
        None  # e.g., {"123456789": "group", "987654321": "private"}
    )

    def __post_init__(self):
        """初始化后处理，确保 source 是 Source 对象。"""
        if not isinstance(self._source, Source):
            self._source = Source(self._source)

    @property
    def source(self) -> Source:
        """获取消息来源链。

        Returns
        -------
        Source
            消息来源链对象
        """
        return self._source

    @source.setter
    def source(self, value: Union[str, List[str], Source]):
        """设置消息来源链。

        Parameters
        ----------
        value : Union[str, List[str], Source]
            可以是字符串、列表或 Source 对象
        """
        if isinstance(value, Source):
            self._source = value
        else:
            self._source = Source(value)

    @property
    def receiver_source(self) -> str:
        """获取接收消息的本地 connector 的 source（当前来源）。

        这是一个兼容性属性，返回来源链的最后一个元素。

        Returns
        -------
        str
            当前来源名称
        """
        return self._source.current

    @receiver_source.setter
    def receiver_source(self, value: str):
        """设置接收消息的 connector（添加到来源链）。

        Parameters
        ----------
        value : str
            接收消息的 connector 名称
        """
        self._source.add(value)
