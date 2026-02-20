from dataclasses import dataclass, field
from logging import Logger
from typing import Any, List, Optional, Union

from mcdreforged.api.types import PluginServerInterface

from gugubot.utils.types.source import Source


@dataclass
class ProcessedInfo:
    """处理后的消息信息类，用于发送消息。

    Attributes
    ----------
    processed_message : List[dict]
        处理后的消息内容列表
    source_id : str
        来源ID（如QQ群号、服务器名）
    sender : str
        发送者名称
    raw : Any
        原始消息数据
    server : PluginServerInterface
        MCDR 服务器接口
    logger : Logger
        日志记录器
    sender_id : str, optional
        发送者ID
    receiver : str, optional
        消息接收者
    event_sub_type : str
        事件子类型
    target : dict, optional
        目标字典
    """

    processed_message: List[dict]

    _source: Source = field(default_factory=Source)
    source_id: str = ""

    sender: str = ""

    raw: Any = None
    server: PluginServerInterface = None
    logger: Logger = None

    sender_id: Optional[str] = None
    receiver: Optional[str] = None
    event_sub_type: str = "group"

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
