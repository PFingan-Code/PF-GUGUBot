"""插件模块。

提供各种扩展功能的插件。
"""

from gugubot.logic.plugins.active_whitelist import ActiveWhiteListSystem
from gugubot.logic.plugins.cross_broadcast import CrossBroadcastSystem
from gugubot.logic.plugins.inactive_check import InactiveCheckSystem
from gugubot.logic.plugins.player_notice import (
    create_on_player_join,
    create_on_player_left,
)
from gugubot.logic.plugins.server_notice import (
    broadcast_server_start,
    broadcast_server_stop
)
from gugubot.logic.plugins.unbound_check import UnboundCheckSystem

__all__ = [
    'broadcast_server_start',
    'broadcast_server_stop',
    'create_on_player_join',
    'create_on_player_left',
    'UnboundCheckSystem',
    'InactiveCheckSystem',
    'ActiveWhiteListSystem',
    'CrossBroadcastSystem',
]
