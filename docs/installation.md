# 安装指南

本指南将帮助你从零开始安装和配置 GUGUBot。

---

## 前置依赖

在安装 GUGUBot 之前，请确保你已经安装了以下组件：

### 必需组件

| 组件 | 版本要求 | 说明 | 下载链接 |
|------|---------|------|----------|
| **MCDReforged** | ≥ 2.0.0 | Minecraft 服务器管理框架 | [GitHub](https://github.com/Fallen-Breath/MCDReforged) |
| **Python** | ≥ 3.8 | Python 运行环境 | [官网](https://www.python.org/) |
| **Minecraft 服务器** | 任意版本 | Java Edition 或 Bedrock Edition | - |

### 必需插件

| 插件 | 版本要求 | 说明 | 安装命令 |
|------|---------|------|----------|
| **whitelist_api** | ≥ 1.3.0 | 白名单 API 插件 | `!!MCDR plugin install whitelist_api` |
| **mg_events** | ≥ 0.2.3 | 游戏事件监听插件 | `!!MCDR plugin install mg_events` |

### 可选依赖

| 插件 | 说明 | 安装命令 |
|------|------|----------|
| **player_ip_logger** | 玩家 IP 记录（用于高级功能） | `!!MCDR plugin install player_ip_logger` |

---

## 安装方式

### 方式一：MCDR 一键安装（推荐）

这是最简单快捷的安装方式。

#### 步骤 1：安装插件

在 MCDR 控制台或游戏内输入：

```bash
!!MCDR plugin install gugubot
```

MCDR 会自动下载并安装 GUGUBot 及其依赖插件。

#### 步骤 2：验证安装

安装完成后，检查插件是否正常加载：

```bash
!!MCDR plugin list
```

你应该能看到以下插件：
- `gugubot`
- `whitelist_api`
- `mg_events`

---

### 方式二：手动安装

如果你需要安装特定版本或开发版本，可以选择手动安装。

#### 步骤 1：下载插件

1. 前往 [Releases 页面](https://github.com/PFingan-Code/PF-GUGUBot/releases)
2. 下载最新版本的 `gugubot-vX.X.X.mcdr` 文件

#### 步骤 2：下载依赖插件

分别下载以下插件：
- [whitelist_api](https://github.com/TISUnion/whitelist_api/releases)
- [mg_events](https://github.com/AnzhiZhang/MCDReforgedPlugins/releases)

#### 步骤 3：安装插件

将所有下载的 `.mcdr` 文件复制到 MCDR 的 `plugins` 目录：

```
MCDReforged/
└── plugins/
    ├── gugubot-vX.X.X.mcdr
    ├── whitelist_api-vX.X.X.mcdr
    └── mg_events-vX.X.X.mcdr
```

#### 步骤 4：加载插件

```bash
!!MCDR plugin load MoreGameEvents-vX.X.X.mcdr
!!MCDR plugin load WhitelistAPI-vX.X.X.mcdr
!!MCDR plugin load gugubot-vX.X.X.mcdr
```

或重启 MCDR 服务器。

---

### 方式三：开发者安装

如果你想参与开发或使用最新的开发版本：

#### 步骤 1：克隆仓库

```bash
cd /path/to/MCDReforged/plugins
git clone https://github.com/PFingan-Code/PF-GUGUBot.git
```

#### 步骤 2：安装依赖

```bash
cd PF-GUGUBot/GUGUbot
pip install -r requirements.txt
```

#### 步骤 3：创建符号链接

在 `plugins` 目录下创建 `gugubot` 文件夹，并创建 `mcdreforged.linked_directory_plugin.json`

文件内容：
```bash
{
  "target": "/path/to/PF-GUGUBot/GUGUbot/"
}
```

#### 步骤 4：加载插件

```bash
!!MCDR plugin load MoreGameEvents-vX.X.X.mcdr
!!MCDR plugin load WhitelistAPI-vX.X.X.mcdr
!!MCDR plugin load gugubot
```

---

## 配置 QQ 机器人

GUGUBot 需要连接到 QQ 机器人才能工作。目前推荐使用以下方案：

### 方案一：NapCat（推荐）

[NapCat](https://napneko.github.io/) 是一个稳定高效的 QQ 机器人框架。

#### 安装 NapCat

1. 前往 [NapCat 官网](https://napneko.github.io/) 下载
2. 按照官方文档安装和配置
3. 登录你的 QQ 机器人账号

#### 配置 WebSocket

编辑 NapCat 的配置文件，启用正向 WebSocket：

```json
{
  "ws": {
    "enable": true,
    "host": "0.0.0.0",
    "port": 8080
  },
  "messageFormat": "array"
}
```

### 方案二：LiteLoaderQQNT + LLOneBot

#### 安装 LiteLoaderQQNT

1. 下载 [LiteLoaderQQNT](https://github.com/LiteLoaderQQNT/LiteLoaderQQNT)
2. 按照官方教程安装到 QQ 客户端

#### 安装 LLOneBot

1. 下载 [LLOneBot](https://github.com/LLOneBot/LLOneBot)
2. 将插件放入 LiteLoaderQQNT 的 plugins 目录
3. 重启 QQ

#### 配置 WebSocket

在 LLOneBot 设置中：

1. 启用正向 WebSocket 服务
2. 设置端口为 `8080`
3. 消息格式可选择 **CQ 码** 或 **消息体**

---

## 配置 GUGUBot

### 配置文件位置

```
config/GUGUbot/config.yml
```

### 最小化配置

首次使用时，你只需要配置以下必要项：

```yaml
connector:
  QQ:
    connection:
      port: 8080 # QQ 机器人所配置的端口
    permissions:
      admin_ids:  # 管理员 QQ 号
        - 1234567890
      group_ids:  # 要监听的 QQ 群号
        - 987654321
```

### 验证配置

1. 保存配置文件
2. 重载插件：

```bash
!!MCDR plugin reload gugubot
```

3. 查看日志，确认没有错误信息

---

## 验证安装

### 检查连接状态

查看 MCDR 日志，确认连接成功：

应该看到类似输出：
- `[GUGUBot] QQ连接器: ~ 连接成功 ~`
- `[GUGUBot] Minecraft连接器已启用`

### 测试聊天转发

1. 在 QQ 群发送消息：`你好`
2. 应该在游戏内看到：`[QQ] 昵称: 你好`
3. 在游戏内聊天：`hi`
4. 应该在 QQ 群看到：`[服务器名] 玩家: hi`

### 测试命令

在 QQ 群发送：

```
#帮助
```

机器人应该回复帮助信息。

---

## 常见问题

### 插件无法加载

**问题**：MCDR 提示插件加载失败

**解决方案**：
1. 检查 Python 版本：`python --version`（需要 ≥ 3.8）
2. 安装缺失的依赖：
  ```bash
  cd plugins/gugubot
  pip install -r requirements.txt
  ```
3. 查看详细错误日志：`logs/MCDR.log`

**问题**：报错 `ImportError: No module named XXX`

**解决方案**：
1. 在MCDR根目录打开终端
2. 安装缺失的依赖：
  ```bash
  pip install XXX
  ```
3. 尝试加载gugubot
  ```bash
  !!MCDR plg load gugubot-vX.X.X.mcdr
  ```

### 无法连接到 QQ 机器人

**问题**：日志显示 "连接错误" 或 "Connection refused"

**解决方案**：
1. 确认 QQ 机器人已启动并登录
2. 检查 WebSocket 端口是否正确
3. 确认防火墙没有阻止连接
4. 检查 GUGUBot 的配置是否正确
5. 检查 GUGUBot 和 QQ 机器人的 token 设置是否一样

### 消息无法转发

**问题**：QQ 和游戏之间的消息不能互通

**解决方案**：
1. 确认 `group_ids` 配置正确
2. 检查机器人是否在该群内
3. 确认 echo 系统已启用：
   ```yaml
   system:
     echo:
       enable: true
   ```
4. 查看日志是否有错误信息

### 配置文件不存在

**问题**：启动后找不到 `/config/GUGUbot/config.yml`

**解决方案**：
1. 第一次加载插件时会自动生成默认配置
2. 如果没有生成，手动下载：[default_config.yml](https://github.com/PFingan-Code/PF-GUGUBot/blob/main/GUGUbot/gugubot/config/defaults/default_config.yml)
3. 将其重命名为 `config.yml` 并放入 `/config/GUGUbot/` 目录

---

## 下一步

安装完成后，建议你：

1. [**配置说明**](configuration.md) - 了解详细的配置选项
2. [**功能详解**](features.md) - 探索 GUGUBot 的所有功能
3. [**疑难解答**](troubleshooting.md) - 查看更多常见问题的解决方案

---

## 需要帮助？

如果遇到问题，可以：

- 查看 [疑难解答](troubleshooting.md)
- 加入 QQ 交流群：[726741344](https://qm.qq.com/q/TqmRHmTmcU)
- 提交 [GitHub Issue](https://github.com/PFingan-Code/PF-GUGUBot/issues)

