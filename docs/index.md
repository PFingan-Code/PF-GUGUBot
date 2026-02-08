# 欢迎使用 GUGUBot

<div align="center">

<strong>一个功能强大的 MCDR 插件，实现 Minecraft 服务器与 QQ 群的无缝互通</strong>

<a href="https://github.com/PFingan-Code/PF-GUGUBot/releases/latest"><img src="https://img.shields.io/github/v/release/PFingan-Code/PF-GUGUBot?style=flat-square&label=最新版" alt="最新版"></a>
<a href="https://github.com/PFingan-Code/PF-GUGUBot/releases"><img src="https://img.shields.io/github/downloads/PFingan-Code/PF-GUGUBot/total?style=flat-square&label=下载量" alt="下载量"></a>


</div>

---

## 什么是 GUGUBot？

GUGUBot 是一个专为 MCDReforged 设计的 QQ 机器人插件，它能够：

- **实现游戏与 QQ 的双向聊天转发**
- **管理服务器白名单和玩家绑定**
- **提供丰富的群管理和服务器管理功能**
- **支持多服务器互联**

无论你是小型私服还是大型公益服，GUGUBot 都能为你提供完善的社区管理解决方案。

---

## 核心特性

### 🔄 双向聊天转发

游戏内聊天实时同步到 QQ 群，QQ 群消息显示在游戏内，支持图片、表情等多种消息类型。

```
[QQ] 张三: 有人在线吗？
[MC] Steve: 我在！
```

### 👥 智能绑定系统

玩家 QQ 与游戏 ID 绑定，支持 Java 版和基岩版：

- ✅ 自动白名单管理
- ✅ 退群自动解绑
- ✅ 多账号支持
- ✅ 跨版本绑定

### 🛡️ 权限管理

- 管理员权限系统（通过 QQ 号配置）
- 管理群配置（群内所有成员拥有管理权限）
- 好友权限管理（机器人好友可选自动获得管理权限）

### 🔗 多服互联

支持多个 Minecraft 服务器之间的消息互通：

- 跨服聊天
- 跨服命令执行
- 服务器间消息转发
- 灵活的服务器配置

### 📊 玩家管理

- 在线玩家查询
- 不活跃玩家检查
- 未绑定用户检查
- 玩家绑定信息查询

### ⚙️ 丰富的功能模块

- **关键词回复** - 自定义触发词和回复内容
- **违禁词过滤** - 自动检测和处理违规内容
- **命令执行** - 远程执行服务器命令
- **风格系统** - 多种机器人回复风格
- **待办管理** - 群内协作管理
- **启动指令** - 服务器启动自动执行

---

## 快速导航

### 新手入门

如果你是第一次使用 GUGUBot，建议按以下顺序阅读文档：

1. [**安装指南**](installation.md) - 了解如何安装和部署 GUGUBot
2. [**配置说明**](configuration.md) - 学习如何配置机器人和各项功能
3. [**功能详解**](features.md) - 探索 GUGUBot 的所有功能

### 高级用户

如果你已经熟悉 GUGUBot 的基本使用：

- [**多服互联教程**](multi-server.md) - 配置多服务器互联
- [**API 文档**](api.md) - 了解如何进行二次开发
- [**疑难解答**](troubleshooting.md) - 解决常见问题

---

## 系统要求

| 组件 | 要求 |
|------|------|
| **MCDReforged** | ≥ 2.0.0 |
| **Python** | ≥ 3.8 |
| **Minecraft** | Java Edition / Bedrock Edition |
| **QQ 机器人** | NapCat / LLOneBot 等 |

---

## 快速开始

### 1. 安装插件

```bash
!!MCDR plugin install gugubot
```

### 2. 配置 QQ 机器人

选择并配置你的 QQ 机器人（推荐 NapCat）：

- WebSocket 端口：`8080`
- 消息格式：CQ 码

### 3. 配置 GUGUBot

编辑 `/config/GUGUbot/config.yml`：

```yaml
connector:
  QQ:
    connection:
      port: 8777
    permissions:
      admin_ids:
        - 你的QQ号
      group_ids:
        - 你的群号
```

### 4. 启动机器人

重载插件即可开始使用：

```bash
!!MCDR plugin reload gugubot
```

详细安装步骤请查看 [完整安装指南](installation.md)。

---

## 使用示例

### 玩家绑定

```
玩家: #绑定 Steve
机器人: 绑定成功！玩家 Steve 已与您的 QQ 账号绑定
```

### 查询在线玩家

```
玩家: #玩家
机器人: 在线玩家(3): Steve, Alex, Notch
```

### 命令执行（管理员）

```
管理员: #执行 say 大家好！
服务器: [Server] 大家好！
```

---

## 社区与支持

### 获取帮助

- 📖 [完整文档](https://pfingan-code.github.io/PF-GUGUBot/)
- 💬 [QQ 交流群](https://qm.qq.com/q/TqmRHmTmcU) - 726741344
- 🐛 [问题反馈](https://github.com/PFingan-Code/PF-GUGUBot/issues)

### 参与贡献

GUGUBot 是开源项目，欢迎各种形式的贡献：

- 💻 代码贡献
- 📝 文档完善
- 🐛 问题反馈
- 💡 功能建议

### 联系作者

- **QQ**: [1377820366](http://wpa.qq.com/msgrd?v=3&uin=1377820366&site=qq&menu=yes)
- **GitHub**: [@LoosePrince](https://github.com/LoosePrince) / [@XueK66](https://github.com/XueK66)

---

## 致谢

感谢以下项目和个人对 GUGUBot 的贡献：

- [QQChat](https://github.com/AnzhiZhang/MCDReforgedPlugins/tree/master/src/qq_chat) - 原始代码基础
- [@AnzhiZhang](https://github.com/AnzhiZhang) - 代码贡献
- [@XueK__](https://github.com/XueK66) - 核心开发
- [@Dreamwxz](https://github.com/Dreamwxz) - 文档贡献
- 所有提交反馈和建议的用户

---

## 许可证

本项目基于 [GPL-3.0 许可证](https://github.com/PFingan-Code/PF-GUGUBot/blob/main/LICENSE.txt) 开源。

---

<div align="center">

<strong>准备好了吗？让我们开始吧！</strong>

<a href="installation/" class="md-button md-button--primary">开始安装</a>
<a href="features/" class="md-button">查看功能</a>

</div>

