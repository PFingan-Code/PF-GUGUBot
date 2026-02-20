import asyncio
import logging
import re
import traceback
from typing import Dict, List, Optional

from gugubot.config.BotConfig import BotConfig
from gugubot.connector.basic_connector import BasicConnector
from gugubot.utils.types import ProcessedInfo


class ConnectorManager:
    """管理多个连接器实例的管理器。

    提供添加、移除连接器和消息广播功能。

    Attributes
    ----------
    connectors : List[BasicConnector]
        当前管理的所有连接器实例
    logger : logging.Logger
        日志记录器实例
    """

    def __init__(
            self, server, bot_config: BotConfig, logger: Optional[logging.Logger] = None
    ) -> None:
        """初始化连接器管理器。

        Parameters
        ----------
        logger : logging.Logger, optional
            用于日志记录的Logger实例。如果未提供，将创建一个新的。
        """
        self.connectors: List[BasicConnector] = []

        self.server = server
        self.config = bot_config
        self.logger = logger or server.logger

        self.system_manager = None  # gugubot.logic.system.system_manager.SystemManager

    def register_system_manager(self, system_manager) -> None:
        """注册系统管理器实例。

        Parameters
        ----------
        system_manager : SystemManager
            系统管理器实例
        """
        self.system_manager = system_manager

    def get_connector(self, source: str) -> Optional[BasicConnector]:
        """根据源标识获取连接器实例。

        Parameters
        ----------
        source : str
            连接器的源标识

        Returns
        -------
        Optional[BasicConnector]
            如果找到对应的连接器实例则返回，否则返回None
        """
        for connector in self.connectors:
            if connector.source == source:
                return connector
        return None

    async def register_connector(self, connector: BasicConnector) -> None:
        """添加一个新的连接器实例。

        Parameters
        ----------
        connector : BasicConnector
            要添加的连接器实例

        Raises
        ------
        ValueError
            如果连接器已经存在于管理器中
        """
        if connector in self.connectors:
            raise ValueError(f"连接器 {connector.source} 已经存在")

        try:
            connector.connector_manager = self
            connector.logger = self.logger
            connector.config = self.config

            await connector.connect()
            self.connectors.append(connector)

            self.logger.info(f"已添加并连接到连接器: {connector.source}")
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"连接到 {connector.source} 失败: {error_msg}")
            raise

    async def remove_connector(self, connector: BasicConnector) -> None:
        """移除一个连接器实例。

        Parameters
        ----------
        connector : BasicConnector
            要移除的连接器实例

        Raises
        ------
        ValueError
            如果连接器不在管理器中
        """
        if connector not in self.connectors:
            raise ValueError(f"连接器 {connector.source} 不存在")

        try:
            await connector.disconnect()
            self.connectors.remove(connector)
            self.logger.info(f"已断开并移除连接器: {connector.source}")
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"断开 {connector.source} 失败: {error_msg}")
            # 仍然从列表中移除，即使断开连接失败
            self.connectors.remove(connector)
            raise

    async def broadcast_processed_info(
            self,
            processed_info: ProcessedInfo,
            include: Optional[List[str]] = None,
            exclude: Optional[List[str]] = None,
    ) -> Dict[str, Exception]:
        """向所有连接器广播消息。

        Parameters
        ----------
        processed_info : Any
            要广播的消息
        include : Optional[List[str]]
            仅向这些源的连接器发送消息（如果为None，则发送给所有连接器）
        exclude : Optional[List[str]]
            不向这些源的连接器发送消息

        Returns
        -------
        Dict[str, Exception]
            发送失败的连接器及其对应的异常信息
        """
        failures: Dict[str, Exception] = {}
        tasks = []
        to_connectors = self.connectors

        # 使用 re.escape 将来源名按字面匹配，避免 source_name 中的正则特殊字符（如 [ ]）导致排除/包含失效
        if include is not None:
            to_connectors = [
                c for c in to_connectors if any(re.match(re.escape(p), c.source) for p in include)
            ]

        if exclude is not None:
            to_connectors = [
                c
                for c in to_connectors
                if not any(re.match(re.escape(p), c.source) for p in exclude)
            ]

        connector_info = f"广播消息到连接器: {to_connectors}"
        message_info = f"消息内容: {processed_info}"
        debug_msg = connector_info + "\n" + message_info
        self.logger.debug(debug_msg)

        # 创建所有发送任务
        for connector in to_connectors:
            task = asyncio.create_task(self._safe_send(connector, processed_info))
            tasks.append((connector, task))

        # 等待所有任务完成
        for connector, task in tasks:
            try:
                await task
            except Exception as e:
                failures[connector.source] = e

        return failures

    async def _safe_send(
            self, connector: BasicConnector, processed_info: ProcessedInfo
    ) -> None:
        """安全地向单个连接器发送消息。

        Parameters
        ----------
        connector : BasicConnector
            目标连接器
        processed_info : Any
            要发送的消息

        Raises
        ------
        Exception
            如果发送失败
        """
        try:
            await connector.send_message(processed_info)
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"发送消息到 {connector.source} 失败: {error_msg}")
            raise

    async def disconnect_all(self) -> Dict[str, Exception]:
        """断开所有连接器的连接。

        Returns
        -------
        Dict[str, Exception]
            断开连接失败的连接器及其对应的异常信息
        """
        tasks = []

        # 创建所有断开连接的任务
        for connector in self.connectors[:]:  # 使用切片创建副本，因为我们会修改列表
            task = asyncio.create_task(self.remove_connector(connector))
            tasks.append((connector, task))

        # 等待所有任务完成
        for connector, task in tasks:
            try:
                await task
            except Exception as e:
                error_msg = str(e) + "\n" + traceback.format_exc()
                self.logger.error(f"[gugubot]断开 {connector.source} 失败: {error_msg}")
