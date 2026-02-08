# 配置说明

本文档详细介绍 GUGUBot 的所有配置选项。

---

## 配置文件结构

GUGUBot 的主配置文件位于 `config/GUGUbot/config.yml`，结构如下：

```yaml
GUGUBot:          # 基础设置
connector:        # 连接器配置
  QQ:             # QQ 连接器
  minecraft:      # Minecraft 连接器
  minecraft_bridge: # 桥接器
style:            # 风格系统
system:           # 功能系统
```

---

## 基础设置

### GUGUBot 配置

```yaml
GUGUBot:
  command_prefix: "#"         # 命令前缀
  group_admin: false          # 群指令是否只能被管理员执行
  show_message_in_console: false  # 是否在控制台显示详细消息
```

#### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `command_prefix` | 字符串 | `"#"` | 所有命令的前缀，如 `#帮助`、`#绑定` |
| `group_admin` | 布尔值 | `false` | 是否限制群内命令只能被管理员执行 |
| `show_message_in_console` | 布尔值 | `false` | 是否在控制台显示详细的消息上报信息 |

---

## 连接器配置

### QQ 连接器

QQ 连接器负责与 QQ 机器人通信。

```yaml
connector:
  QQ:
    source_name: "QQ"         # 显示名称
    enable: true              # 是否启用
    
    connection:               # 连接设置
      host: 127.0.0.1         # 主机地址
      port: 8777              # 端口（跟QQ机器人设置的端口一样）
      post_path: ""           # 路径（通常为空）
      use_ssl: false          # 是否使用 SSL
      verify: true            # 是否验证证书
      ca_certs: ""            # 证书路径
      sslopt: {}              # SSL 选项
      reconnect: 5            # 重连时间（秒）
      max_wait_time: 5        # 最大等待时间（秒）
      token: ""               # 令牌（强力推荐，跟QQ机器人设置的token一样即可）
    
    permissions:              # 权限配置
      admin_ids:              # 管理员 QQ 号列表
        - 1377820366
        - 
      
      admin_group_ids:        # 管理群群号列表
        - 
      
      group_ids:              # 要监听的群号列表
        - 12345615646416
      
      friend_is_admin: false  # 好友是否自动拥有管理权限
      
      custom_group_name:      # 自定义群名显示
        726741344: "定制的显示群名"
    
    chat_templates:           # 消息模板（随机选择）
      - "({display_name}) {sender}: "
      - "[{display_name}] {sender}: "
      - "{display_name} | {sender} 说："
      - "{display_name} 的 {sender} : "
    
    others:
      forward_other_bot: false  # 是否转发官方机器人的消息
      change_group_card: true  # 是否修改群员群名片（绑定ID时自动修改群名片为游戏名）
```

#### 连接设置说明

| 配置项 | 说明 | 推荐值 |
|--------|------|--------|
| `host` | WebSocket 服务器地址 | `127.0.0.1`（本地） |
| `port` | WebSocket 端口 | `8777` |
| `reconnect` | 断线后重连间隔 | `5` 秒 |
| `token` | 访问令牌 | 默认留空，但强烈推荐设置！（与QQ机器人设置一样） |

#### 权限配置说明

| 配置项 | 说明 |
|--------|------|
| `admin_ids` | 拥有管理权限的 QQ 号，可执行所有管理命令 |
| `admin_group_ids` | 管理群，群内所有成员拥有管理权限，群内消息不会转发 |
| `group_ids` | 要监听和转发消息的群号 |
| `friend_is_admin` | 是否给机器人的所有好友管理权限 |
| `custom_group_name` | 自定义群名在游戏内的显示 |

#### 消息模板说明

消息模板用于从 MC 转发到 QQ 的消息格式，系统会随机选择一个模板使用。

可用变量：
- `{display_name}` - 服务器显示名称
- `{sender}` - 玩家名称

---

### Minecraft 连接器

Minecraft 连接器负责处理游戏内的消息和事件。

```yaml
connector:
  minecraft:
    source_name: "Minecraft"  # 服务器显示名称
    enable: true              # 是否启用
    
    # 消息转发选项
    mc_achievement: true      # 转发成就消息
    mc_death: true            # 转发死亡消息
    
    # 玩家进出通知
    player_join_notice: true  # 玩家加入通知
    player_left_notice: true  # 玩家离开通知
    bot_join_notice: true     # 机器人加入通知
    bot_left_notice: true     # 机器人离开通知
    
    # 服务器状态通知
    server_start_notice: true # 服务器启动通知
    server_stop_notice: true  # 服务器停止通知
    
    # 图片显示插件支持
    chat_image: false         # ChatImage 插件支持
    image_previewer: false    # ImagePreview 插件支持
    
    # 玩家加入消息的正则表达式模式
    player_join_patterns:
      - "([^\\s]+) joined the game"
    
    # 玩家离开消息的正则表达式模式
    player_left_patterns:
      - "([^\\[]+)\\[.*?\\] left the game"
      - "([^\\s]+) left the game"
    
    # 机器人名称模式（用于过滤机器人的进出通知）
    bot_names_pattern:
      - ".*bot.*"
      - "^[A-Za-z]+Bot$"
    
    # 忽略转发的 MC 命令模式
    ignore_mc_command_patterns:
      - "!!.*"                          # MCDR 指令
      - ".*?\\[Command: /.*\\]"         # Carpet 指令记录
      - ".*?xaero-waypoint:.*"          # Xaero 路径点共享
```

#### 配置项说明

| 配置项 | 说明 |
|--------|------|
| `mc_achievement` | 是否将玩家获得成就的消息转发到 QQ |
| `mc_death` | 是否将玩家死亡消息转发到 QQ |
| `player_join_notice` | 是否在 QQ 通知玩家加入 |
| `player_left_notice` | 是否在 QQ 通知玩家离开 |
| `bot_join_notice` | 是否通知机器人加入（假人） |
| `bot_left_notice` | 是否通知机器人离开 |
| `server_start_notice` | 是否通知服务器启动 |
| `server_stop_notice` | 是否通知服务器停止 |

#### 正则表达式配置 （[参考](https://www.runoob.com/regexp/regexp-syntax.html)）

- **player_join_patterns**: 用于识别玩家加入消息的正则表达式，第一个捕获组应为玩家名
- **player_left_patterns**: 用于识别玩家离开消息的正则表达式
- **bot_names_pattern**: 用于识别机器人的名称模式，匹配的玩家不会触发进出通知
- **ignore_mc_command_patterns**: 忽略的命令模式，不会转发到 QQ

---

### Minecraft 桥接器

桥接器用于多服务器互联。

```yaml
connector:
  minecraft_bridge:
    source_name: "Main"       # 服务器显示名称
    enable: true              # 是否启用
    is_main_server: true      # 是否为主服务器
    
    connection:               # 连接设置
      host: 127.0.0.1         # 主机地址
      port: 8787              # 端口
      use_ssl: false          # 是否使用 SSL
      verify: true            # 是否验证证书
      ca_certs: ""            # 证书路径
      sslopt: {}              # SSL 选项
      reconnect: 5            # 重连时间（秒）
      ping_interval: 5        # 心跳间隔（秒）
      ping_timeout: 5         # 心跳超时（秒）
      max_wait_time: 5        # 最大等待时间（秒）
      token: ""               # 令牌（强力推荐设置）
```

#### 配置项说明

| 配置项 | 说明 |
|--------|------|
| `is_main_server` | 是否为主服务器，主服务器会创建 WebSocket 服务器，其他服务器连接到主服务器 |
| `ping_interval` | 心跳检测间隔，用于检测连接状态 |
| `ping_timeout` | 心跳超时时间，超时后判定连接断开 |

详细的多服互联配置请参考 [多服互联教程](multi-server.md)。

---

## 风格系统

风格系统允许切换机器人的回复风格。

```yaml
style:
  current_style: "正常"      # 当前风格
  style_cooldown: 0         # 风格切换冷却时间（秒）
```

### 自定义风格

你可以在 `config/GUGUbot/style/` 目录下创建自定义风格文件（xx风格.yml 格式），格式与[语言文件](https://github.com/PFingan-Code/PF-GUGUBot/blob/main/GUGUbot/lang/zh_cn.yml)相同。

示例 `config/GUGUbot/style/可爱.yml`：

```yaml
gugubot:
  system:
    bound:
      bind_success: "绑定成功啦~ ✨"
      unbind_success: "已经解绑啦~ 👋"
    key_words:
      name: "喵" # 默认: "关键词"
      add: "喵" # 默认: "添加"
```

> 命令也可以更改，如上述关键词添加指令会从 `#关键词 添加 <关键词>` 变成 `#喵 喵 <关键词>`

---

## 功能系统配置

### 违禁词系统

```yaml
system:
  ban_words:
    enable: false           # 是否启用
```

启用后，机器人不会转发包含违禁词的消息。

管理违禁词：
- `#违禁词 添加 <词> [理由]` - 添加违禁词
- `#违禁词 删除 <词>` - 删除违禁词
- `#违禁词 列表` - 查看所有违禁词

---

### 绑定系统

```yaml
system:
  bound:
    enable: false                   # 是否启用
    max_bedrock_bound: 1            # 最大基岩版绑定数
    max_java_bound: 1               # 最大 Java 版绑定数
    whitelist_add_with_bound: false # 绑定时自动添加白名单
    whitelist_remove_with_leave: true # 退群时自动移除白名单
```

#### 配置项说明

| 配置项 | 说明 |
|--------|------|
| `max_bedrock_bound` | 每个 QQ 账号最多可绑定几个基岩版账号 |
| `max_java_bound` | 每个 QQ 账号最多可绑定几个 Java 版账号 |
| `whitelist_add_with_bound` | 绑定时是否自动添加到服务器白名单 |
| `whitelist_remove_with_leave` | 退群时是否自动从白名单移除 |

---

### 绑定提醒

```yaml
system:
  bound_notice:
    enable: false           # 是否启用
```

启用后，未绑定的用户发言时会收到绑定提醒。

---

### 转发系统

```yaml
system:
  echo:
    enable: true            # 是否启用
```

这是核心功能，控制所有消息转发。

---

### 命令执行系统

```yaml
system:
  execute:
    enable: false           # 是否启用
    allow_bridge_execute: true  # 是否允许通过桥接器执行命令
    ignore_execute_command_patterns:  # 忽略的命令模式
      - ".*?give.*?"        # 忽略 give 指令
```

**安全提示**：命令执行系统仅管理员可用，但仍需谨慎启用并配置好管理员权限。

---

### 关键词回复

```yaml
system:
  key_words:
    enable: true            # 是否启用
    max_add_time: 30        # 添加关键词的最大时间（秒）
```

使用方法：
1. 发送 `#添加 关键词`
2. 在 30 秒内发送回复内容（文本或图片）
3. 完成添加

---

### 玩家列表查询

```yaml
system:
  list:
    enable: false           # 是否启用
```

启用后可使用 `#玩家` 或 `#list` 查询在线玩家。

**注意**：需要配置 RCON 或使用支持的服务器版本。

---

### 机器人昵称

```yaml
system:
  name:
    enable: false           # 是否启用
```

启用后可使用 `#昵称 <名称>` 修改机器人在游戏内的显示昵称。

---

### 启动指令

```yaml
system:
  startup_command:
    enable: false           # 是否启用
```

会在开服时执行指定指令（地毯反作弊指令等）。

使用方法：
- `#启动指令 添加 <指令>` - 添加启动指令
- `#启动指令 删除 <指令>` - 删除启动指令
- `#启动指令 列表` - 查看所有启动指令
- `#启动指令 执行` - 手动执行所有启动指令

---

### 白名单系统

```yaml
system:
  whitelist:
    enable: false           # 是否启用
```

提供白名单管理功能，需要 `whitelist_api` 插件支持(会自动安装的前置插件)。

---

### 未绑定用户检查

```yaml
system:
  unbound_check:
    enable: false           # 是否启用
    timeout_days: 7         # 入群后未绑定的超时天数
    check_interval: 86400   # 检查间隔（秒，默认 24 小时）
    notify_targets:         # 通知目标
      admin_private: true   # 私聊管理员
      admin_groups: true    # 发送到管理群
      origin_group: false   # 发送到原群
```

定期检查入群后长时间未绑定账号的用户。

---

### 不活跃玩家检查

```yaml
system:
  inactive_check:
    enable: false           # 是否启用
    inactive_days: 30       # 不活跃天数阈值
    never_played_days: 7    # 从未进入游戏的天数阈值
    check_interval: 86400   # 检查间隔（秒）
    notify_targets:         # 通知目标
      admin_private: true   # 私聊管理员
      admin_groups: true    # 发送到管理群
      origin_group: false   # 发送到原群
```

定期检查长时间未登录的玩家和绑定后从未进入游戏的玩家。

---

## 配置示例

### 小型私服配置

适合 10-20 人的小型服务器：

```yaml
GUGUBot:
  command_prefix: "#"
  group_admin: false

connector:
  QQ:
    enable: true
    connection:
      port: 8777
    permissions:
      admin_ids:
        - 1234567890  # 你的 QQ 号
      group_ids:
        - 987654321   # 你的群号

system:
  echo:
    enable: true
  bound:
    enable: true
    max_java_bound: 1
    max_bedrock_bound: 1
    whitelist_add_with_bound: true
  key_words:
    enable: true
  whitelist:
    enable: true
```

### 大型公益服配置

适合大型公益服，需要更严格的管理：

```yaml
GUGUBot:
  command_prefix: "#"
  group_admin: true  # 群指令仅管理员可用

connector:
  QQ:
    enable: true
    permissions:
      admin_ids:
        - 1111111111
        - 2222222222
      admin_group_ids:
        - 888888888  # 管理群
      group_ids:
        - 999999999  # 玩家群

system:
  echo:
    enable: true
  bound:
    enable: true
    whitelist_add_with_bound: true
    whitelist_remove_with_leave: true
  bound_notice:
    enable: true
  ban_words:
    enable: true
  whitelist:
    enable: true
  unbound_check:
    enable: true
    timeout_days: 7
    notify_targets:
      admin_groups: true
  inactive_check:
    enable: true
    inactive_days: 30
    notify_targets:
      admin_groups: true
```

---

## 重载配置

修改配置后，需要重载插件使配置生效：

```bash
!!MCDR plugin reload gugubot
```

---

## 配置验证

### 检查配置语法

YAML 格式对缩进非常敏感，可以使用在线工具验证：

- [YAML Lint](http://www.yamllint.com/)
- [YAML Checker](https://yamlchecker.com/)

### 查看日志

配置错误时，MCDR 会在日志中显示详细的错误信息：

```bash
tail -f logs/latest.log
```

---

## 下一步

- [功能详解](features.md) - 了解如何使用各项功能
- [疑难解答](troubleshooting.md) - 解决配置问题
- [多服互联](multi-server.md) - 配置多服务器互联

