# API 文档

独立 MCDR 插件可以通过 **GUGUBot 公开 API** 注册 `#命令`、回复 QQ/游戏、执行 RCON，不必改 GUGUBot 源码，也不必继承 `BasicSystem`。

---

## 推荐：独立插件 + `bind_plugin`

依赖 `"gugubot": "*"`，在自己的插件里十几行即可挂上命令。

### `mcdreforged.plugin.json`

```json
{
  "id": "hello_gugu",
  "version": "1.0.0",
  "name": "Hello GUGU",
  "description": "GUGUBot 外部插件示例",
  "author": ["you"],
  "dependencies": {
    "gugubot": "*"
  }
}
```

### 插件代码

```python
PLUGIN_ID = "hello_gugu"

_unbind = None


def on_load(server, _):
    global _unbind
    from gugubot.api import bind_plugin
    _unbind = bind_plugin(server, PLUGIN_ID, setup)


def on_unload(_):
    if _unbind:
        _unbind()


def setup(api):
    api.register_command("hello", on_hello)
    api.register_command("种子", on_seed, admin_only=True)


def on_hello(ctx):
    return f"你好，{ctx.sender}"


def on_seed(ctx):
    return ctx.rcon("seed")
```

`bind_plugin` 会：

1. 若 GUGUBot **已经加载**，立刻调用 `setup(api)`
2. 监听 `gugubot.register`，以便 GUGUBot **后加载或热重载** 时再注册
3. 本插件卸载时注销已注册的命令（`on_unload` 里再调一次返回的清理函数也安全）

也可以不经过 `bind_plugin`，直接使用：

```python
api = server.get_plugin_instance("gugubot").api
api.register_command("hello", on_hello, plugin_id="hello_gugu")
```

GUGUBot 尚未加载时 `get_plugin_instance("gugubot")` 为 `None`，因此更推荐 `bind_plugin`。

---

## `gugubot.api` 表面

只把 [`gugubot/api.py`](https://github.com/PFingan-Code/PF-GUGUBot/blob/master/GUGUbot/gugubot/api.py) 当作稳定公开接口。  
`BroadcastInfo`、`SystemManager`、`connector_manager` **不是**稳定 API，升级时可能变动。

### `CommandContext`

处理函数的唯一入参。

| 属性 / 方法 | 说明 |
| --- | --- |
| `sender` | 发送者昵称 / 玩家名 |
| `sender_id` | 发送者 ID（QQ 号、玩家标识等） |
| `source` | 原始渠道名，如 `QQ`、`Minecraft` |
| `source_id` | 渠道 ID（群号、服务器名等） |
| `is_admin` | 是否为 GUGUBot 管理员 |
| `args` | 命令名之后的参数列表，如 `#hello a b` → `["a", "b"]` |
| `text` | 去掉命令前缀后的整段文本，如 `hello a b` |
| `reply(text)` | 回复到消息原渠道 |
| `rcon(command) -> str` | 执行服务器命令并返回结果 |

Handler 可以是普通函数：

- 返回 `str`：自动作为回复发出
- 返回 `None`：只发送你在函数里调用过的 `ctx.reply()`
- 返回 coroutine：会被 `await`

```python
def on_hello(ctx):
    ctx.reply(f"你好，{ctx.sender}")
    # 不再 return 也可以

async def on_status(ctx):
    return ctx.rcon("list")
```

### `GUGUBotAPI`

| 方法 / 属性 | 说明 |
| --- | --- |
| `register_command(name, handler, aliases=(), admin_only=False, plugin_id=None)` | 注册 `#命令`。`admin_only=True` 时非管理员会收到「权限不足」且消息被消费 |
| `unregister_plugin(plugin_id)` | 注销该插件的全部命令 |
| `command_prefix` | 当前命令前缀，默认 `#` |
| `rcon(command)` | 没有 `ctx` 时也能跑 RCON |

命令名（含别名）冲突时会打 warning，**先注册的保留**。

插件命令插在 Echo 之前处理：匹配成功后不会再被转发成普通聊天。

---

## 进阶：继承 `BasicSystem`

文件发送、关键词监听等复杂逻辑，仍可自己写一个系统并注册到 `SystemManager`。这是内部接口，**可能随版本变动**。

必须注册在 `echo` 之前，否则 Echo 会吃掉消息：

```python
from gugubot.logic.system.basic_system import BasicSystem
from gugubot.builder import MessageBuilder
from gugubot.utils.types import BroadcastInfo


class MyCustomSystem(BasicSystem):
    def __init__(self, server, config=None):
        BasicSystem.__init__(self, "my_custom", enable=True, config=config)
        self.server = server
        self.logger = server.logger

    async def process_broadcast_info(self, broadcast_info: BroadcastInfo) -> bool:
        if not self.is_command(broadcast_info):
            return False
        content = broadcast_info.message[0].get("data", {}).get("text", "")
        prefix = self.config.get("GUGUBot", {}).get("command_prefix", "#")
        if content.startswith(f"{prefix}hello"):
            await self.reply_to_source(
                broadcast_info,
                [MessageBuilder.text("你好！")],
            )
            return True
        return False


def on_load(server, _):
    gugubot = server.get_plugin_instance("gugubot")
    if gugubot is None or gugubot.connector_manager is None:
        return
    system_manager = gugubot.connector_manager.system_manager
    if system_manager is None:
        return
    system_manager.remove_system("my_custom")
    system_manager.register_system(MyCustomSystem(server), before=["echo"])
```

简单的 `#命令` + 回复 + RCON **请用上一节的 `bind_plugin`**，不要走这条路径。

---

## 参考

- [MCDReforged 文档](https://mcdreforged.readthedocs.io/)
- [GUGUBot GitHub](https://github.com/PFingan-Code/PF-GUGUBot)

开发中遇到问题：

- 加入 QQ 交流群：[726741344](https://qm.qq.com/q/TqmRHmTmcU)
- 提交 [GitHub Issue](https://github.com/PFingan-Code/PF-GUGUBot/issues)
