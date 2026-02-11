# API 文档

本文档介绍如何使用 GUGUBot 的 API 接口进行二次开发。

---

## 概述

GUGUBot 提供了灵活的 API 接口，允许你：

- 开发自定义系统模块
- 与 GUGUBot 交互发送消息
- 监听和处理各种事件
- 扩展连接器功能

---

## 架构概览

### 核心组件

```
GUGUBot
├── Connector（连接器）
│   ├── QQ Connector - QQ 消息收发
│   ├── Minecraft Connector - MC 消息处理
│   └── Bridge Connector - 多服互联
├── Parser（解析器）
│   ├── QQ Parser - 解析 QQ 消息
│   └── MC Parser - 解析 MC 消息
├── System（功能系统）
│   ├── Basic System - 基础系统类
│   ├── Bound System - 绑定系统
│   ├── Whitelist System - 白名单系统
│   └── ...（其他系统）
└── Utils（工具类）
    ├── Message Builder - 消息构建
    ├── Player Manager - 玩家管理
    └── ...（其他工具）
```

### 消息流程

```
QQ消息 → QQ Connector → QQ Parser → BroadcastInfo → System Manager → Systems → Response
MC消息 → MC Connector → MC Parser → BroadcastInfo → System Manager → Systems → Response
```

---

## 数据结构

### BroadcastInfo

广播信息，包含接收到的消息和相关信息。

```python
class BroadcastInfo:
    def __init__(
        self,
        message: List[Dict],           # 消息内容（CQ码格式）
        source: str,                   # 消息来源（如 "QQ", "Minecraft"）
        source_id: str,                # 来源ID（群号、服务器名）
        sender: str,                   # 发送者昵称
        sender_id: str,                # 发送者ID（QQ号、玩家UUID）
        raw: str,                      # 原始消息
        server: PluginServerInterface, # MCDR服务器接口
        logger: logging.Logger,        # 日志记录器
        event_sub_type: str = "group", # 事件子类型
        receiver: str = ""             # 接收者
    ):
        pass
```

**示例**：

```python
broadcast_info = BroadcastInfo(
    message=[{"type": "text", "data": {"text": "你好"}}],
    source="QQ",
    source_id="123456789",  # 群号
    sender="张三",
    sender_id="987654321",  # QQ号
    raw="你好",
    server=server,
    logger=logger,
    event_sub_type="group"
)
```

### ProcessedInfo

处理后的信息，用于发送消息。

```python
class ProcessedInfo:
    def __init__(
        self,
        processed_message: List[Dict],  # 处理后的消息
        source: str,                    # 消息来源
        source_id: str,                 # 来源ID
        sender: str,                    # 发送者
        sender_id: str,                 # 发送者ID
        raw: str,                       # 原始消息
        server: PluginServerInterface,  # MCDR服务器接口
        logger: logging.Logger,         # 日志记录器
        event_sub_type: str = "group",  # 事件子类型
        receiver: str = "",             # 接收者
        target: Dict[str, str] = None   # 目标（群号/玩家等）
    ):
        pass
```

---

## 开发自定义系统

### 创建系统模块

创建一个继承自 `BasicSystem` 的类：

```python
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.utils.types import BroadcastInfo
from gugubot.builder import MessageBuilder


class MyCustomSystem(BasicSystem):
    """自定义系统"""

    def __init__(self, server, config=None):
        # 系统名称和是否启用
        BasicSystem.__init__(self, "my_custom", enable=True, config=config)
        self.server = server
        self.logger = server.logger

    def initialize(self):
        """初始化系统"""
        self.logger.info("自定义系统已初始化")

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理接收到的消息
        
        Parameters
        ----------
        broadcast_info : BroadcastInfo
            广播信息
        
        Returns
        -------
        bool
            是否已处理该消息（True表示已处理，不传递给其他系统）
        """
        # 检查是否是命令
        if not self.is_command(broadcast_info):
            return False

        message = broadcast_info.message
        if not message or message[0].get("type") != "text":
            return False

        content = message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")

        # 解析命令
        if content.startswith(f"{command_prefix}hello"):
            await self._handle_hello(broadcast_info)
            return True

        return False

    async def _handle_hello(self, broadcast_info: BroadcastInfo):
        """处理 hello 命令"""
        # 构建回复消息
        reply_msg = [MessageBuilder.text("你好！这是自定义系统的回复")]

        # 发送回复
        await self.reply(broadcast_info, reply_msg)
```

### 注册系统

在 `system_manager.py` 中注册你的系统：

```python
from gugubot.logic.system.my_custom import MyCustomSystem

# 在 SystemManager 的 initialize_systems 方法中
self.systems.append(MyCustomSystem(self.server, self.config))
```

---

## 消息构建

### MessageBuilder

`MessageBuilder` 提供了构建各种类型消息的静态方法。

#### 文本消息

```python
from gugubot.builder import MessageBuilder

# 纯文本
msg = [MessageBuilder.text("这是一条文本消息")]

# 多段文本
msg = [
    MessageBuilder.text("第一段"),
    MessageBuilder.text("第二段")
]
```

#### @消息

```python
# @某人
msg = [
    MessageBuilder.at(123456789),  # QQ号
    MessageBuilder.text(" 你好！")
]

# @全体成员
msg = [MessageBuilder.at("all")]
```

#### 图片消息

```python
# 通过URL
msg = [MessageBuilder.image("https://example.com/image.jpg")]

# 通过本地文件
msg = [MessageBuilder.image("file:///path/to/image.jpg")]

# Base64编码
msg = [MessageBuilder.image("base64://iVBORw0KGgoAAAANSUhEUg...")]
```

#### 表情

```python
# QQ表情
msg = [MessageBuilder.face(178)]  # 表情ID
```

#### 组合消息

```python
msg = [
    MessageBuilder.at(123456789),
    MessageBuilder.text(" "),
    MessageBuilder.text("看这张图片："),
    MessageBuilder.image("https://example.com/pic.jpg")
]
```

---

## 发送消息

### 通过 System 发送

在自定义系统中，使用 `reply` 方法：

```python
async def _handle_command(self, broadcast_info: BroadcastInfo):
    # 构建消息
    message = [MessageBuilder.text("回复内容")]
    
    # 发送到原消息来源
    await self.reply(broadcast_info, message)
```

### 通过 Connector 发送

#### 发送到 QQ

```python
from gugubot.utils.types import ProcessedInfo
from gugubot.builder import MessageBuilder

# 构建 ProcessedInfo
processed_info = ProcessedInfo(
    processed_message=[MessageBuilder.text("消息内容")],
    source="Minecraft",
    source_id="server_name",
    sender="System",
    sender_id="",
    raw="消息内容",
    server=server,
    logger=logger,
    target={"123456789": "group"}  # 群号: group/private
)

# 通过 connector_manager 发送
await connector_manager.broadcast_processed_info(processed_info)
```

#### 发送到 Minecraft

```python
processed_info = ProcessedInfo(
    processed_message=[MessageBuilder.text("消息内容")],
    source="QQ",
    source_id="123456789",
    sender="张三",
    sender_id="987654321",
    raw="消息内容",
    server=server,
    logger=logger,
    target={"Minecraft": "group"}
)

await connector_manager.broadcast_processed_info(processed_info)
```

---

## 数据存储

### 使用 BasicConfig

`BasicConfig` 提供了简单的 JSON 数据存储功能。

```python
from gugubot.config import BasicConfig
from pathlib import Path

class MySystem(BasicConfig, BasicSystem):
    def __init__(self, server, config=None):
        BasicSystem.__init__(self, "my_system", enable=True, config=config)
        
        # 数据文件路径
        data_path = Path(server.get_data_folder()) / "system" / "my_data.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        
        BasicConfig.__init__(self, data_path)
        
        # 加载数据
        self.load()
    
    def save_data(self, key, value):
        """保存数据"""
        self.config_dict[key] = value
        self.save()
    
    def get_data(self, key, default=None):
        """读取数据"""
        return self.config_dict.get(key, default)
```

### 数据文件位置

```
config/GUGUbot/
└── system/
    ├── key_words.json
    ├── bound.json
    ├── whitelist.json
    └── my_data.json
```

---

## 权限检查

### 检查管理员权限

```python
def _is_admin(self, sender_id: str) -> bool:
    """检查是否是管理员"""
    # 从配置读取管理员列表
    admin_ids = self.config.get("connector", {}).get("QQ", {}).get("permissions", {}).get("admin_ids", [])
    
    # 检查是否在管理员列表中
    return str(sender_id) in [str(id) for id in admin_ids]

# 使用
async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
    if not self._is_admin(broadcast_info.sender_id):
        await self.reply(broadcast_info, [MessageBuilder.text("权限不足")])
        return True
    
    # 执行管理员操作
    ...
```

---

## 事件监听

### 监听玩家事件

GUGUBot 使用 `mg_events` 插件监听游戏事件。

```python
from mcdreforged.api.types import PluginServerInterface

def on_player_joined(server: PluginServerInterface, player: str, info):
    """玩家加入事件"""
    # 处理玩家加入
    pass

def on_player_left(server: PluginServerInterface, player: str):
    """玩家离开事件"""
    # 处理玩家离开
    pass

def on_load(server: PluginServerInterface, prev_module):
    """插件加载时注册事件监听"""
    server.register_event_listener("mg_events.player_joined", on_player_joined)
    server.register_event_listener("mg_events.player_left", on_player_left)
```

---

## 多语言支持

### 获取翻译文本

```python
def get_tr(self, key: str, **kwargs) -> str:
    """获取翻译文本
    
    Parameters
    ----------
    key : str
        翻译键，如 "add_success"
    **kwargs
        格式化参数
    
    Returns
    -------
    str
        翻译后的文本
    """
    # 完整的翻译键
    full_key = f"gugubot.system.{self.name}.{key}"
    
    # 获取翻译
    text = self.server.tr(full_key, **kwargs)
    
    return text

# 使用
success_msg = self.get_tr("add_success", player="Steve")
```

### 添加自定义翻译

在 `GUGUbot/lang/zh_cn.yml` 中添加：

```yaml
gugubot:
  system:
    my_custom:
      name: "自定义系统"
      hello: "你好，{name}！"
      success: "操作成功"
```

---

## 工具类

### PlayerManager

玩家管理器，用于查询和管理玩家绑定信息。

```python
from gugubot.utils.player_manager import PlayerManager

# 创建实例
player_manager = PlayerManager(server)

# 查询玩家绑定
bound_info = player_manager.get_bound_by_qq(qq_id)
bound_info = player_manager.get_bound_by_player(player_name)

# 添加绑定
player_manager.add_bound(qq_id, player_name, is_bedrock=False)

# 删除绑定
player_manager.remove_bound(qq_id, player_name)
```

### RconManager

RCON 管理器，用于执行服务器命令。

```python
from gugubot.utils.rcon_manager import RconManager

# 创建实例
rcon_manager = RconManager(server)

# 执行命令
result = await rcon_manager.send_command("list")

# 获取在线玩家
players = await rcon_manager.get_online_players()
```

---

## 完整示例

### 自定义签到系统

```python
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.config import BasicConfig
from gugubot.utils.types import BroadcastInfo
from gugubot.builder import MessageBuilder
from pathlib import Path
from datetime import datetime


class CheckInSystem(BasicConfig, BasicSystem):
    """签到系统"""

    def __init__(self, server, config=None):
        BasicSystem.__init__(self, "checkin", enable=True, config=config)

        # 初始化数据存储
        data_path = Path(server.get_data_folder()) / "system" / "checkin.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        BasicConfig.__init__(self, data_path)

        self.server = server
        self.logger = server.logger

    def initialize(self):
        """初始化系统"""
        self.load()
        if "check_in_data" not in self.config_dict:
            self.config_dict["check_in_data"] = {}
        self.logger.info("签到系统已初始化")

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        """处理消息"""
        if not self.is_command(broadcast_info):
            return False

        message = broadcast_info.message
        if not message or message[0].get("type") != "text":
            return False

        content = message[0].get("data", {}).get("text", "")
        command_prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")

        # 签到命令
        if content.startswith(f"{command_prefix}签到"):
            await self._handle_checkin(broadcast_info)
            return True

        # 查询签到
        if content.startswith(f"{command_prefix}签到记录"):
            await self._handle_checkin_record(broadcast_info)
            return True

        return False

    async def _handle_checkin(self, broadcast_info: BroadcastInfo):
        """处理签到"""
        user_id = broadcast_info.sender_id
        today = datetime.now().strftime("%Y-%m-%d")

        # 获取用户签到数据
        if user_id not in self.config_dict["check_in_data"]:
            self.config_dict["check_in_data"][user_id] = {
                "days": 0,
                "last_date": ""
            }

        user_data = self.config_dict["check_in_data"][user_id]

        # 检查今天是否已签到
        if user_data["last_date"] == today:
            msg = [MessageBuilder.text("你今天已经签到过了！")]
        else:
            # 更新签到数据
            user_data["days"] += 1
            user_data["last_date"] = today
            self.save()

            msg = [
                MessageBuilder.at(user_id),
                MessageBuilder.text(f" 签到成功！已连续签到 {user_data['days']} 天")
            ]

        await self.reply(broadcast_info, msg)

    async def _handle_checkin_record(self, broadcast_info: BroadcastInfo):
        """查询签到记录"""
        user_id = broadcast_info.sender_id

        if user_id in self.config_dict["check_in_data"]:
            user_data = self.config_dict["check_in_data"][user_id]
            msg = [
                MessageBuilder.text(f"你已连续签到 {user_data['days']} 天\n"),
                MessageBuilder.text(f"上次签到: {user_data['last_date']}")
            ]
        else:
            msg = [MessageBuilder.text("你还没有签到记录")]

        await self.reply(broadcast_info, msg)
```

### 注册系统

在 `system_manager.py` 中：

```python
from gugubot.logic.system.checkin import CheckInSystem

# 在 initialize_systems 方法中添加
self.systems.append(CheckInSystem(self.server, self.config))
```

---

## 调试技巧

### 日志记录

```python
# 不同级别的日志
self.logger.debug("调试信息")
self.logger.info("普通信息")
self.logger.warning("警告信息")
self.logger.error("错误信息")

# 带异常追踪的日志
try:
    # 代码
    pass
except Exception as e:
    import traceback
    self.logger.error(f"错误: {e}\n{traceback.format_exc()}")
```

### 消息调试

启用详细消息输出：

```yaml
GUGUBot:
  show_message_in_console: true
```

---

## 最佳实践

### 1. 异常处理

始终使用 try-except 包裹可能出错的代码：

```python
async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
    try:
        # 处理逻辑
        pass
    except Exception as e:
        self.logger.error(f"处理消息失败: {e}\n{traceback.format_exc()}")
        return False
```

### 2. 配置验证

在初始化时验证配置：

```python
def initialize(self):
    required_config = self.config.get("system", {}).get(self.name, {})
    if not required_config:
        self.logger.warning(f"{self.name} 系统未配置，使用默认设置")
```

### 3. 权限检查

敏感操作前检查权限：

```python
if not self._is_admin(broadcast_info.sender_id):
    await self.reply(broadcast_info, [MessageBuilder.text("权限不足")])
    return True
```

### 4. 数据持久化

定期保存数据：

```python
def save_data(self):
    try:
        self.save()
    except Exception as e:
        self.logger.error(f"保存数据失败: {e}")
```

---

## 参考资源

- [MCDReforged 文档](https://mcdreforged.readthedocs.io/)
- [GUGUBot GitHub](https://github.com/PFingan-Code/PF-GUGUBot)
- [CQ 码格式说明](https://docs.go-cqhttp.org/cqcode/)

---

## 需要帮助？

如果在开发过程中遇到问题：

- 查看源代码中的其他系统实现
- 加入 QQ 交流群：[726741344](https://qm.qq.com/q/TqmRHmTmcU)
- 提交 [GitHub Issue](https://github.com/PFingan-Code/PF-GUGUBot/issues)

