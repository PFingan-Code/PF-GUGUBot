"""服务器通知插件模块。

该模块提供服务器启动和停止时的广播通知功能。
"""

from typing import Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.builder import MessageBuilder
from gugubot.config.BotConfig import BotConfig
from gugubot.utils.types import ProcessedInfo


async def broadcast_server_start(
        server: PluginServerInterface,
        connector_manager,
        config: BotConfig,
        message: Optional[str] = None,
        exclude_sources: Optional[list] = None,
) -> None:
    """广播服务器启动消息。

    Parameters
    ----------
    server : PluginServerInterface
        MCDR服务器接口实例
    connector_manager : ConnectorManager
        连接器管理器实例
    config : BotConfig
        配置对象
    message : Optional[str]
        自定义启动消息，如果为None则使用配置文件中的消息
    exclude_sources : Optional[list]
        不发送通知的连接器源列表，默认从配置文件读取Minecraft的source_name

    Example
    -------
    >>> await broadcast_server_start(server, connector_manager, config)
    >>> await broadcast_server_start(server, connector_manager, config, "服务器已启动！", exclude_sources=["MyServer", "Bridge"])
    """
    # 检查是否启用服务器启动通知
    if not config.get_keys(["connector", "minecraft", "server_start_notice"], True):
        return

    # 从配置文件读取Minecraft的source_name作为默认排除项
    minecraft_source_name = config.get_keys(
        ["connector", "minecraft", "source_name"], "Minecraft"
    )
    exclude_sources = exclude_sources or [minecraft_source_name]

    # 从配置文件获取启动消息
    if message is None:
        message = server.tr("gugubot.notice.server_start")

    try:
        # 构建消息
        processed_info = ProcessedInfo(
            processed_message=[MessageBuilder.text(message)],
            _source=minecraft_source_name,  # 使用 _source 参数
            source_id="",
            sender=server.tr("gugubot.bot_name"),
            raw=None,
            server=server,
            logger=server.logger,
            event_sub_type="group",
        )

        # 广播消息（排除Minecraft等平台）
        await connector_manager.broadcast_processed_info(
            processed_info, exclude=exclude_sources
        )

        server.logger.info(f"[服务器通知] 已广播启动消息")

    except Exception as e:
        server.logger.error(f"[服务器通知] 广播启动消息失败: {e}")


async def broadcast_server_stop(
        server: PluginServerInterface,
        connector_manager,
        config: BotConfig,
        message: Optional[str] = None,
        exclude_sources: Optional[list] = None,
) -> None:
    """广播服务器停止消息。

    Parameters
    ----------
    server : PluginServerInterface
        MCDR服务器接口实例
    connector_manager : ConnectorManager
        连接器管理器实例
    config : BotConfig
        配置对象
    message : Optional[str]
        自定义停止消息，如果为None则使用配置文件中的消息
    exclude_sources : Optional[list]
        不发送通知的连接器源列表，默认从配置文件读取Minecraft的source_name

    Example
    -------
    >>> await broadcast_server_stop(server, connector_manager, config)
    >>> await broadcast_server_stop(server, connector_manager, config, "服务器维护中...", exclude_sources=["MyServer"])
    """
    # 检查是否启用服务器停止通知
    if not config.get_keys(["connector", "minecraft", "server_stop_notice"], True):
        return

    # 从配置文件读取Minecraft的source_name作为默认排除项
    minecraft_source_name = config.get_keys(
        ["connector", "minecraft", "source_name"], "Minecraft"
    )
    exclude_sources = exclude_sources or [minecraft_source_name]

    # 从配置文件获取停止消息
    if message is None:
        message = server.tr("gugubot.notice.server_stop")

    try:
        # 构建消息
        processed_info = ProcessedInfo(
            processed_message=[MessageBuilder.text(message)],
            _source=minecraft_source_name,  # 使用 _source 参数
            source_id="",
            sender=server.tr("gugubot.bot_name"),
            raw=None,
            server=server,
            logger=server.logger,
            event_sub_type="group",
        )

        # 广播消息（排除Minecraft等平台）
        await connector_manager.broadcast_processed_info(
            processed_info, exclude=exclude_sources
        )

        server.logger.info(f"[服务器通知] 已广播停止消息")

    except Exception as e:
        server.logger.error(f"[服务器通知] 广播停止消息失败: {e}")
