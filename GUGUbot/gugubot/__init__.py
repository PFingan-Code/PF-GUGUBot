# -*- coding: utf-8 -*-
# +---------------------------------------------------------------------+
from pathlib import Path

from mcdreforged.api.types import Info, PluginServerInterface

from gugubot.config import BotConfig
# from gugubot.logic.bot_core import GUGUBotCore
from gugubot.connector import (BridgeConnector, ConnectorManager, MCConnector, QQWebSocketConnector, TestConnector)
from gugubot.logic.plugins import (ActiveWhiteListSystem, CrossBroadcastSystem, InactiveCheckSystem, UnboundCheckSystem)
from gugubot.logic.system import (BanWordSystem, BoundNoticeSystem, BoundSystem, EchoSystem, ExecuteSystem,
                                  GeneralHelpSystem, KeyWordSystem, PlayerListSystem, StartupCommandSystem, StyleSystem,
                                  SystemManager, TodoSystem, WhitelistSystem)
from gugubot.utils import (StyleManager, check_plugin_version, help_msg_register, migrate_config_v1_to_v2)

connector_manager: ConnectorManager = None
mc_connector: MCConnector = None
gugubot_config: BotConfig = None
startup_command_system: StartupCommandSystem = None
style_manager: StyleManager = None
unbound_check_system: UnboundCheckSystem = None
inactive_check_system: InactiveCheckSystem = None


# +---------------------------------------------------------------------+
async def on_load(server: PluginServerInterface, old) -> None:
    global connector_manager
    global mc_connector
    global gugubot_config
    global startup_command_system
    global style_manager
    global unbound_check_system
    global inactive_check_system

    # 尝试迁移旧版本配置
    config_path = Path(server.get_data_folder()) / "config.yml"
    if config_path.exists():
        try:
            with server.open_bundled_file(
                    "gugubot/config/defaults/default_config.yml"
            ) as file_handler:
                default_config_content = file_handler.read().decode("utf-8")
            migrate_config_v1_to_v2(
                config_path, default_config_content, logger=server.logger
            )
        except Exception as e:
            server.logger.error(f"迁移配置失败: {e}")

    gugubot_config = BotConfig(config_path)
    gugubot_config.add_new_config(server)

    is_main_server = gugubot_config.get_keys(
        ["connector", "minecraft_bridge", "is_main_server"], True
    )

    connector_manager = ConnectorManager(server, gugubot_config)

    mc_connector = MCConnector(server, gugubot_config)
    connectors = [
        mc_connector,
        TestConnector(server, gugubot_config),
        BridgeConnector(server, gugubot_config),
    ]

    if is_main_server:
        connectors.append(QQWebSocketConnector(server, gugubot_config))

    for connector in connectors:
        await connector_manager.register_connector(connector)

    # 初始化风格管理器
    style_manager = StyleManager(server, gugubot_config)
    style_manager.scan_styles()

    # 注册系统管理器
    system_manager = SystemManager(
        server, connector_manager=connector_manager, config=gugubot_config
    )
    system_manager.style_manager = style_manager

    # 创建系统实例，enable状态在各系统__init__中从config自动读取
    systems = [EchoSystem(enable=True, config=gugubot_config)]

    # Execute 系统在所有服务器上都需要创建，以便处理从 bridge 收到的命令
    execute_system = ExecuteSystem(server, config=gugubot_config)
    systems.insert(0, execute_system)

    # PlayerList 系统 (需要在所有服务器上运行)
    player_list_system = PlayerListSystem(server, config=gugubot_config)
    systems.insert(1, player_list_system)

    if is_main_server:
        general_help_system = GeneralHelpSystem(server, config=gugubot_config)
        ban_word_system = BanWordSystem(server, config=gugubot_config)
        key_word_system = KeyWordSystem(server, config=gugubot_config)
        whitelist_system = WhitelistSystem(server, config=gugubot_config)
        bound_system = BoundSystem(server, config=gugubot_config)
        bound_notice_system = BoundNoticeSystem(config=gugubot_config)
        startup_command_system = StartupCommandSystem(server, config=gugubot_config)
        style_system = StyleSystem(server, style_manager, config=gugubot_config)
        todo_system = TodoSystem(server, config=gugubot_config)

        # 创建活跃白名单系统
        active_whitelist_system = ActiveWhiteListSystem(server, config=gugubot_config)

        # 创建未绑定检查系统
        unbound_check_system = UnboundCheckSystem(server, config=gugubot_config)

        # 创建不活跃检查系统
        inactive_check_system = InactiveCheckSystem(server, config=gugubot_config)

        # 设置白名单系统引用
        bound_system.set_whitelist_system(whitelist_system)
        # 设置绑定提醒系统对绑定系统的引用
        bound_notice_system.set_bound_system(bound_system)
        # 设置未绑定检查系统的依赖
        unbound_check_system.set_bound_system(bound_system)
        # 设置不活跃检查系统的依赖
        inactive_check_system.set_bound_system(bound_system)
        inactive_check_system.set_whitelist_system(whitelist_system)
        inactive_check_system.set_active_whitelist_system(active_whitelist_system)

        systems.insert(0, general_help_system)
        systems.insert(1, ban_word_system)
        systems.insert(2, bound_system)
        systems.insert(3, bound_notice_system)
        systems.insert(1, key_word_system)
        systems.insert(5, whitelist_system)
        systems.insert(6, startup_command_system)
        systems.insert(7, style_system)
        systems.insert(8, todo_system)
        systems.insert(9, unbound_check_system)
        systems.insert(10, inactive_check_system)
        systems.insert(11, active_whitelist_system)

    # 跨平台强制广播（#mc / !!qq），放在 echo 前以便处理后可拦截不再走 echo）
    cross_broadcast_system = CrossBroadcastSystem(config=gugubot_config)
    systems.insert(len(systems) - 1, cross_broadcast_system)

    for system in systems:
        system_manager.register_system(system)

    connector_manager.register_system_manager(system_manager)

    # 为未绑定检查系统设置 QQ 连接器（仅在主服务器）
    if is_main_server:
        qq_connector = connector_manager.get_connector("QQ")
        if qq_connector:
            unbound_check_system.set_qq_connector(qq_connector)
            inactive_check_system.set_qq_connector(qq_connector)

    # 检查插件版本
    server.schedule_task(check_plugin_version(server))

    # 注册帮助消息
    command_prefix = gugubot_config.get_keys(["GUGUBot", "command_prefix"], "#")
    help_name = server.tr("gugubot.system.general_help.name")
    main_help_msg = f"GUGUBot {help_name}"
    server.register_help_message(f"{command_prefix}{help_name}", main_help_msg)

    # 注册 !!gugubot 命令
    help_msg_register(server, gugubot_config)

    # # 注册监听任务
    from gugubot.logic.plugins.mg_event import (
        create_on_mc_achievement,
        create_on_mc_death,
    )

    server.register_event_listener(
        "PlayerAdvancementEvent",
        create_on_mc_achievement(gugubot_config, connector_manager),
    )
    server.register_event_listener(
        "PlayerDeathEvent", create_on_mc_death(gugubot_config, connector_manager)
    )


# +---------------------------------------------------------------------+
# # 防止初始化报错
# qq_bot = None

from gugubot.logic.plugins.player_notice import (
    create_on_player_join,
    create_on_player_left,
)


async def on_info(server: PluginServerInterface, info: Info) -> None:
    if connector_manager is not None:
        on_player_join = create_on_player_join(connector_manager, gugubot_config)
        on_player_left = create_on_player_left(connector_manager, gugubot_config)
        await on_player_join(server, info)
        await on_player_left(server, info)


#     # 玩家上线显示群公告
#     if qq_bot.config["forward"].get("show_group_notice", False):
#         player_name = "[".join(info.content.split(" logged in with entity id")[0].split("[")[:-1])
#
#         latest_notice = get_latest_group_notice(qq_bot, logger=server.logger)

#         if latest_notice:

#             latest_notice_json = {
#                 "text": f"群公告：{latest_notice}",
#                 "color": "gray",
#                 "italic": False
#             }
#             server.execute(f'tellraw {player_name} {json.dumps(latest_notice_json)}')


async def on_user_info(server: PluginServerInterface, info: Info) -> None:
    if mc_connector is not None:
        await mc_connector.on_message(server, info)


# 卸载
async def on_unload(server: PluginServerInterface) -> None:
    try:
        # 停止未绑定检查定时任务
        if unbound_check_system:
            unbound_check_system.stop_schedule_task()

        # 停止不活跃检查定时任务
        if inactive_check_system:
            inactive_check_system.stop_schedule_task()

        if connector_manager:
            await connector_manager.disconnect_all()
    except:
        pass


# +---------------------------------------------------------------------+
# 服务器启动和停止通知
from gugubot.logic.plugins import broadcast_server_start, broadcast_server_stop


async def on_server_startup(server: PluginServerInterface) -> None:
    """服务器启动时的回调函数。"""
    try:
        if startup_command_system:
            await startup_command_system.execute_all_commands()

        if connector_manager:
            # 广播服务器启动消息
            await broadcast_server_start(server, connector_manager, gugubot_config)
    except Exception as e:
        server.logger.error(f"[GUGUBot] 服务器启动通知失败: {e}")


async def on_server_stop(
        server: PluginServerInterface, server_return_code: int
) -> None:
    """服务器停止时的回调函数。"""
    try:
        if connector_manager:
            # 广播服务器停止消息
            await broadcast_server_stop(server, connector_manager, gugubot_config)
    except Exception as e:
        server.logger.error(f"[GUGUBot] 服务器停止通知失败: {e}")

# +---------------------------------------------------------------------+
