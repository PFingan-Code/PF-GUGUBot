"""QQ 官方机器人（open-qq-bot）连接器。

将 QQ 官方机器人 WebSocket API 适配为
GUGUBot 的一个 connector，与 OneBot 版 QQWebSocketConnector 并行使用。

模块划分：

- :mod:`gugubot.connector.open_qq_bot.common`      -- 错误码/限流/分片/@ 标签等公共工具
- :mod:`gugubot.connector.open_qq_bot.api_client`   -- REST API 客户端（token/发消息/富媒体/撤回）
- :mod:`gugubot.connector.open_qq_bot.gateway`      -- WebSocket 网关（Identify/心跳/Resume）
- :mod:`gugubot.connector.open_qq_bot.parser`       -- 官方事件 → 内部 BroadcastInfo
- :mod:`gugubot.connector.open_qq_bot.connector`    -- BasicConnector 实现，接入 ConnectorManager
"""

from gugubot.connector.open_qq_bot.connector import OpenQQBotConnector

__all__ = ["OpenQQBotConnector"]
