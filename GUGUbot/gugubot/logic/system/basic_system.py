import logging
from typing import List, Optional, TYPE_CHECKING

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.utils.types import BroadcastInfo, ProcessedInfo

if TYPE_CHECKING:
    from gugubot.logic.system.system_manager import SystemManager


class BasicSystem:
    """基础系统类，所有系统都应该继承此类。

    提供系统的基本功能和接口。

    Attributes
    ----------
    name : str
        系统名称
    system_manager : SystemManager
        系统管理器的引用
    logger : logging.Logger
        日志记录器实例
    """

    def __init__(self, name: str, enable: bool = True, config: Optional[BotConfig] = None) -> None:
        """初始化基础系统。

        Parameters
        ----------
        name : str
            系统名称
        enable : bool
            默认启用状态，如果 config 中有配置则使用 config 的值
        config : BotConfig, optional
            配置对象，用于读取 enable 状态
        """
        self.name = name
        self.system_manager: Optional[SystemManager] = None
        self.logger: Optional[logging.Logger] = None
        self.config: Optional[BotConfig] = config

        # 从配置读取enable状态，如果没有配置则使用传入的enable参数
        if config:
            self.enable = config.get_keys(["system", name, "enable"], enable)
        else:
            self.enable = enable

    def initialize(self) -> None:
        """初始化系统。

        在系统被注册到系统管理器时调用。
        子类应该重写此方法以实现自己的初始化逻辑。
        """
        pass

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的命令。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            命令信息

        Returns
        -------
        bool
            命令是否成功处理

        子类必须重写此方法以实现命令处理逻辑。
        """
        raise NotImplementedError("子类必须实现process_broadcast_info方法")

    def is_command(self, broadcast_info: BroadcastInfo) -> bool:
        """判断是否是命令

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息

        Returns
        -------
        bool
            是否是命令
        """
        if broadcast_info.event_type != "message":
            return False

        message = broadcast_info.message
        if not message:
            return False

        first_message = message[0]
        if first_message.get("type") != "text":
            return False

        content = first_message.get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")

        if not content.startswith(command_prefix):
            return False

        group_admin = self.config.get_keys(["GUGUBot", "group_admin"], False)
        if group_admin and not broadcast_info.is_admin:
            return False

        return True

    @staticmethod
    def create_processed_info(broadcast_info: BroadcastInfo) -> ProcessedInfo:
        """创建用于转发的处理后消息对象。

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            原始广播信息

        Returns
        -------
        ProcessedInfo
            处理后的消息对象
        """
        # 构造转发消息的格式

        return ProcessedInfo(
            processed_message=broadcast_info.message,
            _source=broadcast_info.source,  # 传递完整的 Source 对象
            source_id=broadcast_info.source_id,
            sender=broadcast_info.sender,
            sender_id=broadcast_info.sender_id,
            receiver=broadcast_info.receiver,
            raw=broadcast_info.raw,
            server=broadcast_info.server,
            logger=broadcast_info.logger,
            event_sub_type=broadcast_info.event_sub_type,
            target=broadcast_info.target
        )

    async def reply(self, broadcast_info: BroadcastInfo, message: List[dict]) -> None:
        # 构造基础 target - 使用原始来源作为 target key
        origin_source = broadcast_info.source.origin
        target_source = broadcast_info.source_id if broadcast_info.source_id and broadcast_info.source_id.isdigit() else origin_source
        target = {target_source: broadcast_info.event_sub_type}

        # 检查是否是 bridge 回复（receiver_source 是 Bridge，但原始来源不是 Bridge）
        bridge_name = self.config.get_keys(
            ["connector", "minecraft_bridge", "source_name"],
            "Bridge"
        )

        if broadcast_info.receiver_source == bridge_name and not broadcast_info.source.is_from(bridge_name):
            # 如果 receiver_source 是 Bridge，但原始来源不是 Bridge, 则将 target 设置为 source
            target[broadcast_info.receiver_source] = broadcast_info.event_sub_type

        respond = ProcessedInfo(
            processed_message=message,
            _source=broadcast_info.source,  # 传递完整的 Source 对象
            source_id=broadcast_info.source_id,
            sender=self.system_manager.server.tr("gugubot.bot_name"),
            sender_id=None,
            raw=broadcast_info.raw,
            server=broadcast_info.server,
            logger=broadcast_info.logger,
            event_sub_type=broadcast_info.event_sub_type,
            target=target
        )

        # 使用当前接收来源或原始来源
        receiver_source = broadcast_info.receiver_source or origin_source
        await self.system_manager.connector_manager.broadcast_processed_info(
            respond,
            include=[receiver_source]
        )

    def get_tr(self, key: str, global_key: bool = False, **kwargs) -> str:
        server = self.system_manager.server
        full_key = key if global_key else f"gugubot.system.{self.name}.{key}"

        # 优先从风格管理器获取翻译
        if getattr(self.system_manager, 'style_manager', None):
            custom_translation = self.system_manager.style_manager.get_translation(full_key, **kwargs)
            if custom_translation is not None:
                return custom_translation

        # 回退到默认翻译
        return server.tr(full_key, **kwargs)

    async def handle_enable_disable(self, broadcast_info: BroadcastInfo) -> bool:
        """处理开启/关闭命令

        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息

        Returns
        -------
        bool
            是否处理了命令
        """
        if not self.is_command(broadcast_info):
            return False

        if not broadcast_info.is_admin:
            return False

        command = broadcast_info.message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        system_name = self.get_tr("name")

        command = command.replace(command_prefix, "", 1).strip()

        if not command.startswith(system_name):
            return False

        command = command.replace(system_name, "", 1).strip()

        enable_cmd = self.get_tr("gugubot.enable", global_key=True)
        disable_cmd = self.get_tr("gugubot.disable", global_key=True)

        if command in [enable_cmd, disable_cmd]:
            return await self._handle_switch(command == enable_cmd, broadcast_info)

        return False

    async def _handle_switch(self, enable: bool, broadcast_info: BroadcastInfo) -> bool:
        """处理开启系统命令"""
        self.enable = enable
        self._save_enable_state()
        await self.reply(broadcast_info, [MessageBuilder.text(
            self.get_tr(f"gugubot.enable_success" if enable else "gugubot.disable_success", global_key=True))])
        return True

    def _save_enable_state(self) -> None:
        """保存enable状态到配置文件"""
        if self.config:
            system_config = self.config.get("system", {})
            if self.name in system_config:
                system_config[self.name]["enable"] = self.enable
                self.config.save()
