import logging
import re
import traceback
from typing import List, Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.config.BotConfig import BotConfig
from gugubot.connector.connector_manager import ConnectorManager
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo


class SystemManager:
    """管理多个系统实例的管理器。

    提供添加、移除系统和命令广播功能。

    Attributes
    ----------
    systems : List[BasicSystem]
        当前管理的所有系统实例
    logger : logging.Logger
        日志记录器实例
    """

    def __init__(
            self,
            server: PluginServerInterface,
            logger: Optional[logging.Logger] = None,
            connector_manager: Optional[ConnectorManager] = None,
            config: Optional[BotConfig] = None,
    ) -> None:
        """初始化系统管理器。

        Parameters
        ----------
        server : PluginServerInterface
            MCDR插件服务器接口实例
        logger : logging.Logger. optional
            用于日志记录的Logger实例。如果未提供，将创建一个新的。
        connector_manager : ConnectorManager
            连接管理器实例
        config : BotConfig
            配置实例
        """
        self.systems: List[BasicSystem] = []
        self.server: PluginServerInterface = server
        self.logger = logger or server.logger
        self.connector_manager = connector_manager
        self.config = config

    def get_system(self, name: str) -> Optional[BasicSystem]:
        for system in self.systems:
            if system.name == name:
                return system
        return None

    def register_system(
            self,
            system: BasicSystem,
            before: Optional[List[str]] = None,
            after: Optional[List[str]] = None,
    ) -> None:
        """添加一个新的系统实例。

        Parameters
        ----------
        system : BasicSystem
            要添加的系统实例

        Raises
        ------
        ValueError
            如果系统已经存在于管理器中
        """
        if system.name in [s.name for s in self.systems]:
            raise ValueError(f"系统 {system.name} 已经存在")

        try:
            system.system_manager = self
            system.logger = self.logger
            system.config = self.config

            system.initialize()

            # Check for circular dependencies
            if before and after:
                duplicate = set(before or []) & set(after or [])
                if duplicate:
                    raise ValueError(
                        f"Circular dependency: {system.name} cannot be both before and after {duplicate}"
                    )

            # Insert the system based on before and after dependencies
            if before or after:
                insert_pos = 0
                for i, existing_system in enumerate(self.systems):
                    if before and existing_system.name in before:
                        break
                    if after and existing_system.name in after:
                        insert_pos = i + 1
                    insert_pos = i + 1
                self.systems.insert(insert_pos, system)
            else:
                self.systems.append(system)

            self.logger.info(f"已添加并初始化系统: {system.name}")
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"初始化 {system.name} 失败: {error_msg}")
            raise

    def remove_system(self, system_name: str) -> bool:
        """移除一个系统实例。

        Parameters
        ----------
        system_name : str
            要移除的系统名称

        Returns
        -------
        bool
            如果系统被成功移除则返回True，否则返回False
        """

        for system in self.systems:
            if system.name == system_name:
                self.systems.remove(system)
                self.logger.info(f"已移除系统: {system_name}")
                return True
        return False

    async def broadcast_command(
            self,
            broadcast_info: BroadcastInfo,
            include: Optional[List[str]] = None,
            exclude: Optional[List[str]] = None,
    ) -> bool:
        """向所有系统广播命令。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            要广播的命令信息
        include : List[str], optional
            仅向这些名称的系统发送命令（如果为None，则发送给所有系统）
        exclude : List[str], optional
            不向这些名称的系统发送命令

        Returns
        -------
        bool
            是否所有系统都成功处理了命令
        """
        to_systems = self.systems

        if include is not None:
            to_systems = [
                s for s in to_systems if any(re.match(p, s.name) for p in include)
            ]

        if exclude is not None:
            to_systems = [
                s for s in to_systems if not any(re.match(p, s.name) for p in exclude)
            ]

        system_info = f"广播命令到系统: {to_systems}"
        command_info = f"命令内容: {broadcast_info}"
        debug_msg = system_info + "\n" + command_info
        self.logger.debug(debug_msg)

        # 创建处理任务
        result = False
        for system in to_systems:
            result = await self._safe_process_broadcast_info(system, broadcast_info)

            if result:
                break

        # 判断是否有系统成功处理了命令
        return result

    async def _safe_process_broadcast_info(
            self, system: BasicSystem, broadcast_info: BroadcastInfo
    ) -> bool:
        """安全地向单个系统发送命令。

        Parameters
        ----------
        system : BasicSystem
            目标系统
        broadcast_info : BroadcastInfo
            要处理的命令信息

        Returns
        -------
        bool
            命令是否成功处理
        """
        try:
            result = await system.process_broadcast_info(broadcast_info)
            return result if isinstance(result, bool) else False
        except Exception as e:
            error_msg = str(e) + "\n" + traceback.format_exc()
            self.logger.error(f"系统 {system.name} 处理命令失败: {error_msg}")
            return False
