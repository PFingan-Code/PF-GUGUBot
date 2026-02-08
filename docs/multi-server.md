# 多服互联教程

本教程将指导你配置多个 Minecraft 服务器之间的消息互通。

---

## 什么是多服互联？

多服互联允许多个 Minecraft 服务器通过 GUGUBot 实现：

- **跨服聊天** - 不同服务器的玩家可以互相聊天
- **统一管理** - 在一个 QQ 群管理多个服务器
- **命令转发** - 向指定服务器发送命令
- **事件同步** - 同步玩家进出、服务器状态等事件

---

## 架构说明

### 工作原理

```
QQ 群
  ↓
主服务器 (GUGUBot)
  ├─ WebSocket 服务器 (端口 8787)
  ├─ 子服务器 1 (WebSocket 客户端)
  ├─ 子服务器 2 (WebSocket 客户端)
  └─ 子服务器 3 (WebSocket 客户端)
```

### 消息流程

1. QQ 消息发送到主服务器
2. 主服务器广播给所有子服务器
3. 子服务器接收并显示消息
4. 子服务器的消息发送到主服务器
5. 主服务器转发到 QQ 和其他子服务器

---

## 术语说明

| 术语 | 说明 |
|------|------|
| **主服务器** | 运行 WebSocket 服务器，负责消息分发 |
| **子服务器** | 连接到主服务器的其他服务器 |
| **桥接器** | GUGUBot 的多服互联组件 |
| **source_name** | 服务器在聊天中显示的名称 |

---

## 前置准备

### 1. 所有服务器都需要

- ✅ 安装 MCDReforged
- ✅ 安装 GUGUBot 及依赖插件
- ✅ 服务器之间网络互通

### 2. 仅主服务器需要

- ✅ 配置 QQ 连接器
- ✅ 配置 QQ 机器人

### 3. 网络要求

- 子服务器能访问主服务器的 8787 端口（或自定义端口）
- 如果服务器在不同机器上，需要开放防火墙

---

## 配置步骤

### 步骤 1：配置主服务器

编辑主服务器的 `config/GUGUbot/config.yml`：

```yaml
connector:
  # QQ 连接器 - 主服务器必须配置
  QQ:
    source_name: "QQ"
    enable: true
    connection:
      port: 8777
    permissions:
      admin_ids:
        - 你的QQ号
      group_ids:
        - 你的群号
  
  # Minecraft 连接器
  minecraft:
    source_name: "主服"  # 在聊天中显示的名称
    enable: true
    mc_achievement: true
    mc_death: true
    player_join_notice: true
    player_left_notice: true
  
  # 桥接器 - 主服务器配置
  minecraft_bridge:
    source_name: "Main"  # 桥接器名称
    enable: true
    is_main_server: true  # 关键：必须设为 true
    
    connection:
      host: 0.0.0.0      # 监听所有网卡
      port: 8787         # WebSocket 服务端口
      reconnect: 5
      ping_interval: 5
      ping_timeout: 5
      token: ""          # 可选：访问令牌
```

### 步骤 2：配置子服务器

编辑每个子服务器的 `config/GUGUbot/config.yml`：

#### 子服务器 1（生存服）

```yaml
connector:
  # QQ 连接器 - 子服务器可以禁用
  QQ:
    enable: false
  
  # Minecraft 连接器
  minecraft:
    source_name: "生存服"  # 在聊天中显示的名称
    enable: true
    mc_achievement: true
    mc_death: true
    player_join_notice: true
    player_left_notice: true
  
  # 桥接器 - 子服务器配置
  minecraft_bridge:
    source_name: "Survival"
    enable: true
    is_main_server: false  # 关键：必须设为 false
    
    connection:
      host: 主服务器IP     # 主服务器地址
      port: 8787          # 主服务器的桥接端口
      reconnect: 5
      ping_interval: 5
      ping_timeout: 5
      token: ""           # 如果主服务器设置了令牌
```

#### 子服务器 2（创造服）

```yaml
connector:
  QQ:
    enable: false
  
  minecraft:
    source_name: "创造服"
    enable: true
  
  minecraft_bridge:
    source_name: "Creative"
    enable: true
    is_main_server: false
    
    connection:
      host: 主服务器IP
      port: 8787
      reconnect: 5
```

#### 子服务器 3（小游戏服）

```yaml
connector:
  QQ:
    enable: false
  
  minecraft:
    source_name: "小游戏"
    enable: true
  
  minecraft_bridge:
    source_name: "Minigame"
    enable: true
    is_main_server: false
    
    connection:
      host: 主服务器IP
      port: 8787
      reconnect: 5
```

### 步骤 3：启动服务器

#### 1. 先启动主服务器

查看日志，确认桥接器 WebSocket 服务器已启动：
```
[GUGUBot] 桥接器 WebSocket 服务器已启动，监听端口: 8787
```

#### 2. 再启动子服务器

依次启动所有子服务器

查看日志，确认连接成功：
```
[GUGUBot] 桥接器已连接到主服务器
```

### 步骤 4：验证连接

#### 在主服务器上

应该看到类似输出：
```
[GUGUBot] 桥接器 WebSocket 服务器已启动，监听端口: 8787
[GUGUBot] 桥接器客户端已连接: Survival
[GUGUBot] 桥接器客户端已连接: Creative
```

#### 测试消息转发

1. 在主服玩家聊天：`你好`
2. 应该在 QQ 群和所有子服看到：`[主服] 玩家名: 你好`

3. 在子服玩家聊天：`大家好`
4. 应该在 QQ 群、主服和其他子服看到：`[生存服] 玩家名: 大家好`

5. 在 QQ 群发送：`服务器正常吗`
6. 应该在所有服务器看到：`[QQ] 昵称: 服务器正常吗`

---

## 高级配置

### 使用令牌保护连接

如果服务器暴露在公网，建议使用令牌保护：

#### 主服务器

```yaml
connector:
  minecraft_bridge:
    connection:
      token: "your_secret_token_here"
```

#### 子服务器

```yaml
connector:
  minecraft_bridge:
    connection:
      token: "your_secret_token_here"  # 必须与主服务器相同
```

### 使用 SSL 加密

对于公网连接，可以启用 SSL：

#### 主服务器

```yaml
connector:
  minecraft_bridge:
    connection:
      use_ssl: true
      ca_certs: "/path/to/cert.pem"
```

#### 子服务器

```yaml
connector:
  minecraft_bridge:
    connection:
      host: wss://主服务器域名  # 使用 wss:// 而不是 ws://
      use_ssl: true
      verify: true
      ca_certs: "/path/to/cert.pem"
```

### 自定义心跳设置

调整心跳检测参数：

```yaml
connector:
  minecraft_bridge:
    connection:
      ping_interval: 10  # 心跳间隔（秒）
      ping_timeout: 10   # 心跳超时（秒）
```

- `ping_interval`: 发送心跳的间隔，过小会增加网络负担
- `ping_timeout`: 心跳无响应后判定断线的时间

### 自动重连设置

```yaml
connector:
  minecraft_bridge:
    connection:
      reconnect: 5       # 断线后重连间隔（秒）
      max_wait_time: 5   # 最大等待时间（秒）
```

---

## 跨服命令执行

### 语法

```
#执行@服务器名 <命令>
#mcdr@服务器名 <命令>
```

### 示例

#### 在生存服执行命令

```
#执行@Survival say 大家好！
```

在生存服执行：`/say 大家好！`

#### 在创造服执行 MCDR 命令

```
#mcdr@Creative backup make
```

在创造服执行 MCDR 备份命令。

### 配置

确保命令执行系统已启用并允许跨服执行：

```yaml
system:
  execute:
    enable: true
    allow_bridge_execute: true  # 必须为 true
```

### 权限

跨服命令执行仅管理员可用，确保你的 QQ 号在管理员列表中。

---

## 故障排查

### 子服务器无法连接

#### 问题 1：端口不通

**检查**：
```bash
# 在子服务器上另起一个终端测试
telnet 主服务器IP 8787
```

**解决**：
- 检查主服务器防火墙
- 检查路由器端口转发（如果跨网络）

#### 问题 2：令牌不匹配

**现象**：日志显示 "认证失败"

**解决**：确保主服务器和子服务器的 `token` 完全一致。

#### 问题 3：主服务器未启动

**现象**：连接被拒绝

**解决**：先启动主服务器，确认桥接服务已运行，子服务器会自动重连。

### 消息重复

**现象**：同一条消息显示多次

**原因**：配置错误导致消息循环

**解决**：

1. 确保只有主服务器的 QQ 连接器启用
2. 子服务器的 QQ 连接器应禁用：
```yaml
connector:
  QQ:
    enable: false
```

### 部分服务器收不到消息

**原因**：连接断开但未发现

**解决**：

重载没收到消息的服务器的gugubot即可
```bash
!!MCDR plg reload gugubot
```

如何预防：
1. 检查日志确认连接状态
2. 调整心跳参数：
```yaml
connection:
  ping_interval: 5
  ping_timeout: 5
```

### 延迟过高

**原因**：网络延迟或服务器性能问题

**优化**：

1. 使用更快的网络
2. 减少转发的消息类型
3. 优化服务器性能

---

## 网络拓扑

### 本地网络（推荐）

所有服务器在同一局域网：

```
[主服] 192.168.1.10:8787
  ├─ [子服1] 192.168.1.11
  ├─ [子服2] 192.168.1.12
  └─ [子服3] 192.168.1.13
```

**优点**：
- 低延迟
- 高安全性
- 无需额外配置

### 跨网络（公网）

服务器分布在不同地点：

```
[主服] 公网IP:8787
  ├─ [子服1] → 通过公网连接
  ├─ [子服2] → 通过公网连接
  └─ [子服3] → 通过公网连接
```

**要求**：
- 主服务器需要公网 IP 或域名
- 开放防火墙端口
- 建议使用 SSL 和令牌保护

**配置**：
```yaml
# 主服务器
connection:
  host: 0.0.0.0  # 监听所有网卡
  port: 8787
  use_ssl: true
  token: "strong_password"

# 子服务器
connection:
  host: 主服务器公网IP或域名
  port: 8787
  use_ssl: true
  token: "strong_password"
```

### 混合网络

部分服务器在本地，部分在公网：

```
[主服] 公网IP:8787
  ├─ [子服1] 192.168.1.11 (本地)
  ├─ [子服2] 192.168.1.12 (本地)
  └─ [子服3] 其他公网IP (远程)
```

**配置**：
- 本地子服使用内网 IP
- 远程子服使用公网 IP

---

## 性能优化

### 1. 减少不必要的转发

对于不需要跨服同步的事件，可以单独控制：

```yaml
connector:
  minecraft:
    mc_achievement: false  # 成就不跨服
    player_join_notice: false  # 进出通知不跨服
```

### 2. 消息过滤

过滤高频或不重要的消息：

```yaml
connector:
  minecraft:
    ignore_mc_command_patterns:
      - "!!.*"
      - ".+\\[Command.*"
```

### 3. 合理设置心跳

根据网络情况调整：

- 本地网络：可以设置较短的间隔（3-5秒）
- 公网连接：建议较长的间隔（10-15秒）

---

## 安全建议

### 1. 使用令牌

```yaml
connection:
  token: "使用强密码"
```

### 2. 限制访问 IP

在防火墙中只允许已知的 IP 访问：

```bash
# iptables 示例
iptables -A INPUT -p tcp --dport 8787 -s 子服务器IP -j ACCEPT
iptables -A INPUT -p tcp --dport 8787 -j DROP
```

### 3. 使用 SSL

公网连接必须启用 SSL 加密。

### 4. 定期更新

保持 GUGUBot 和 MCDR 更新到最新版本。

---

## 监控和维护

### 查看日志

```bash
tail -f logs/latest.log | grep "桥接"
```

### 重连所有子服务器

如果出现问题，可以重载主服务器的插件：

```bash
!!MCDR plugin reload gugubot
```

所有子服务器会自动重连。

---

## 常见配置示例

### 双服务器配置

**主服 + 1 个子服**

主服：
```yaml
minecraft_bridge:
  enable: true
  is_main_server: true
  connection:
    port: 8787
```

子服：
```yaml
minecraft_bridge:
  enable: true
  is_main_server: false
  connection:
    host: 主服IP
    port: 8787
```

### 三服务器配置

**主服 + 2 个子服**

只需在主服配置基础上，增加第二个子服，配置与第一个相同。

### 大型群组服务器

**主服 + 5+ 个子服**

考虑：
- 使用专用机器作为主服（消息中转量大）
- 启用消息过滤
- 优化网络连接

---

## 进阶功能

### 服务器分组

通过配置不同的端口实现服务器分组：

**组1（生存系列）**：
- 主服 A：端口 8787
- 子服：生存服、资源服

**组2（娱乐系列）**：
- 主服 B：端口 8788
- 子服：小游戏服、创造服

### 动态服务器

子服务器可以随时上线/下线，无需重启主服务器。

### 消息路由

开发自定义路由规则，控制消息在哪些服务器之间转发。

---

## 下一步

- [配置说明](configuration.md) - 了解详细的配置选项
- [功能详解](features.md) - 学习如何使用各项功能
- [疑难解答](troubleshooting.md) - 解决多服互联问题

---

## 需要帮助？

多服互联配置相对复杂，如果遇到问题：

- 加入 QQ 交流群：[726741344](https://qm.qq.com/q/TqmRHmTmcU)
- 提交 [GitHub Issue](https://github.com/PFingan-Code/PF-GUGUBot/issues)
- 查看 [疑难解答](troubleshooting.md) 文档

