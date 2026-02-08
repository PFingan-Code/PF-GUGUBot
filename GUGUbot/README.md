# GUGUBot

<div align="center">

[![Visitor Count](https://count.getloli.com/get/@PF-GUGUBot)] 

[![查看次数起始时间](https://img.shields.io/badge/查看次数统计起始于-2023%2F9%2F2-1?style=flat-square)](/)
[![仓库大小](https://img.shields.io/github/repo-size/PFingan-Code/PF-GUGUBot?style=flat-square&label=仓库占用)](/) 
[![最新版](https://img.shields.io/github/v/release/PFingan-Code/PF-GUGUBot?style=flat-square&label=最新版)](https://github.com/PFingan-Code/PF-GUGUBot/releases/latest/download/GUGUbot.mcdr)
[![议题](https://img.shields.io/github/issues/PFingan-Code/PF-GUGUBot?style=flat-square&label=Issues)](https://github.com/PFingan-Code/PF-GUGUBot/issues) 
[![已关闭issues](https://img.shields.io/github/issues-closed/PFingan-Code/PF-GUGUBot?style=flat-square&label=已关闭%20Issues)](https://github.com/PFingan-Code/PF-GUGUBot/issues?q=is%3Aissue+is%3Aclosed)
[![下载量](https://img.shields.io/github/downloads/PFingan-Code/PF-GUGUBot/total?style=flat-square&label=下载量)](https://github.com/PFingan-Code/PF-GUGUBot/releases)
[![最新发布下载量](https://img.shields.io/github/downloads/PFingan-Code/PF-GUGUBot/latest/total?style=flat-square&label=最新版本下载量)](https://github.com/PFingan-Code/PF-GUGUBot/releases/latest)

**一个功能强大的 MCDR 插件，实现 Minecraft 服务器与 QQ 群的无缝互通**

[快速开始](#快速开始) • [功能特性](#功能特性) • [完整文档](https://pfingan-code.github.io/PF-GUGUBot/) • [问题反馈](https://github.com/PFingan-Code/PF-GUGUBot/issues)

</div>

---

## 简介

GUGUBot 是一个专为 MCDReforged 设计的 QQ 机器人插件，支持离线服务器和正版/离线混合服务器。它不仅实现了游戏内外的聊天互通，还集成了白名单管理、玩家绑定、违禁词过滤等实用功能，让服务器管理更加便捷。

### 核心特性

- **🔄 双向聊天转发** - MC 服务器与 QQ 群消息实时互通，支持图片、表情等多种消息类型
- **👥 智能绑定系统** - 玩家 QQ 与游戏 ID 绑定，支持 Java 版和基岩版，退群自动解绑
- **🎯 白名单管理** - 完善的白名单系统，支持在线/离线/基岩版模式
- **🛡️ 违禁词过滤** - 自动检测并撤回包含违禁词的消息
- **🤖 多机器人风格** - 可切换的机器人回复风格，个性化定制
- **🔗 多服互联** - 支持多个 Minecraft 服务器之间的消息互通
- **📊 玩家管理** - 在线玩家查询、不活跃玩家检查、未绑定用户检查
- **⚙️ 命令执行** - 远程执行 MC 命令和 MCDR 命令（管理员权限）
- **📝 关键词回复** - 自定义关键词触发自动回复
- **✅ 待办管理** - 群内协作待办事项系统

> [!NOTE]
> **招募贡献者**
> 
> GUGUbot 和 WebUI 项目正在招募有志者加入开发！
> 
> 有意者请加 QQ [1377820366](http://wpa.qq.com/msgrd?v=3&uin=1377820366&site=qq&menu=yes) 或 QQ群 [726741344](https://qm.qq.com/q/TqmRHmTmcU)

---

## 快速开始

### 前置依赖

在安装 GUGUBot 之前，请确保已安装以下依赖：

| 依赖项 | 版本要求 | 说明 |
|--------|---------|------|
| [MCDReforged](https://github.com/Fallen-Breath/MCDReforged) | ≥ 2.0.0 | Minecraft 服务器管理框架 |
| [whitelist_api](https://github.com/TISUnion/whitelist_api) | ≥ 1.3.0 | 白名单 API 插件 |
| [mg_events](https://github.com/AnzhiZhang/MCDReforgedPlugins/tree/master/src/mg_events) | ≥ 0.2.3 | 游戏事件监听插件 |

### 安装方式

#### 方式一：MCDR 一键安装（推荐）

```bash
!!MCDR plugin install gugubot
```

安装完成后：
1. 配置 `/config/GUGUbot/config.yml`（配置机器人基本信息）
2. 重载 gugubot：`!!MCDR plugin reload gugubot`

#### 方式二：手动安装

1. 下载前置插件并放入 `/plugins` 目录
2. 前往 [Releases](https://github.com/PFingan-Code/PF-GUGUBot/releases) 下载 `gugubot-vX.X.X.mcdr`
3. 将 `gugubot-vX.X.X.mcdr` 放入 `/plugins` 目录
4. 按照上述步骤配置文件
5. 重启或重载插件

### 基础配置

#### 1. QQ 机器人配置

选择以下任一方案配置 QQ 机器人：

- **[NapCat](https://napneko.github.io/)** - 推荐，稳定高效
- **[LiteLoaderQQNT + LLOneBot](https://github.com/LLOneBot/LLOneBot)** - 轻量级方案

配置 WebSocket 服务端口（如 `8080`），消息上报格式选择 **CQ 码** 或者 **消息体**。

#### 3. GUGUBot 配置

编辑 `/config/GUGUbot/config.yml`，配置以下必要项：

```yaml
connector:
  QQ:
    connection:
      port: 8777  # WebSocket 服务端口
    permissions:
      admin_ids:  # 管理员 QQ 号
        - 1234567890
      group_ids:  # 要监听的 QQ 群号
        - 123456789
```

> [!TIP]
> 完整配置说明请查看 [在线文档 - 配置指南](https://pfingan-code.github.io/PF-GUGUBot/configuration/)

---

## 功能特性

### 聊天系统

- **双向消息转发**：游戏内聊天实时同步到 QQ 群，QQ 群消息显示在游戏内
- **多媒体支持**：支持图片、表情等多种消息类型
- **自定义模板**：可自定义消息格式和显示样式
- **游戏事件转发**：玩家加入/离开、成就、死亡消息等

### 玩家绑定系统

```
#绑定 <游戏ID> [基岩]     # 绑定自己的游戏账号
#绑定 [@QQ号] <游戏ID>    # 管理员为他人绑定
#解绑 [游戏ID]            # 解绑账号
#绑定 列表                # 查看绑定列表
```

- 支持 Java 版和基岩版账号分别绑定
- 退群自动解绑（可配置）
- 绑定时自动添加白名单（可配置）

### 白名单管理

```
#白名单 添加 <玩家名> [模式]   # 添加白名单
#白名单 删除 <玩家名>          # 删除白名单
#白名单 列表                   # 查看白名单
#白名单 开启/关闭              # 启用/禁用白名单
```

支持三种模式：
- `online` / `正版` - 正版验证
- `offline` / `离线` - 离线模式
- `bedrock` / `基岩` - 基岩版

### 命令执行系统

```
#执行 <MC命令>            # 执行 Minecraft 命令
#mcdr <MCDR命令>          # 执行 MCDR 命令
#执行@服务器名 <命令>      # 跨服执行（多服互联）
```

> 仅管理员可用

### 其他功能

- **关键词回复**：自定义关键词触发特定回复
- **违禁词过滤**：自动检测并处理违禁内容
- **风格系统**：切换机器人回复风格
- **待办管理**：群内协作管理待办事项
- **玩家列表查询**：查询当前在线玩家
- **不活跃检查**：定期检查不活跃玩家并通知
- **未绑定提醒**：提醒新成员绑定账号

查看更多功能详情，请访问 [完整文档 - 功能列表](https://pfingan-code.github.io/PF-GUGUBot/features/)

---

## 多服互联

GUGUBot 支持多个 Minecraft 服务器之间的消息互通，实现跨服聊天和命令执行。

配置示例：

```yaml
connector:
  minecraft_bridge:
    enable: true
    is_main_server: true  # 主服务器
    connection:
      host: 127.0.0.1
      port: 8787
```

详细配置请参考 [多服互联教程](https://pfingan-code.github.io/PF-GUGUBot/multi-server/)

---

## 文档

- 📖 [完整在线文档](https://pfingan-code.github.io/PF-GUGUBot/)
- 📝 [安装指南](https://pfingan-code.github.io/PF-GUGUBot/installation/)
- ⚙️ [配置说明](https://pfingan-code.github.io/PF-GUGUBot/configuration/)
- 🎯 [功能详解](https://pfingan-code.github.io/PF-GUGUBot/features/)
- 🔧 [API 文档](https://pfingan-code.github.io/PF-GUGUBot/api/)
- ❓ [疑难解答](https://pfingan-code.github.io/PF-GUGUBot/troubleshooting/)
- 🔗 [多服互联](https://pfingan-code.github.io/PF-GUGUBot/multi-server/)

---

## 开发与贡献

### 开发指南

GUGUBot 提供了丰富的 API 接口，方便开发者进行二次开发或集成。

查看 [API 文档](https://pfingan-code.github.io/PF-GUGUBot/api/) 了解更多。

### 贡献代码

欢迎提交 Pull Request！在提交之前，请确保：

1. 代码符合项目的编码规范
2. 添加必要的注释和文档
3. 测试新功能或修复

### 项目结构

```
PF-GUGUBot/
├── GUGUbot/
│   ├── gugubot/          # 核心代码
│   │   ├── builder/      # 消息构建器
│   │   ├── config/       # 配置管理
│   │   ├── connector/    # 连接器（QQ、MC、Bridge）
│   │   ├── logic/        # 逻辑系统
│   │   │   ├── system/   # 核心系统（绑定、白名单等）
│   │   │   └── plugins/  # 插件功能
│   │   ├── parser/       # 消息解析器
│   │   ├── utils/        # 工具类
│   │   └── ws/           # WebSocket 服务
│   ├── lang/             # 多语言支持
│   └── requirements.txt  # 依赖列表
├── docs/                 # 文档源文件
└── tests/                # 测试文件
```

---

## 问题反馈与支持

### 遇到问题？

1. 查看 [疑难解答](https://pfingan-code.github.io/PF-GUGUBot/troubleshooting/)
2. 搜索 [已有 Issues](https://github.com/PFingan-Code/PF-GUGUBot/issues)
3. 提交新的 [Issue](https://github.com/PFingan-Code/PF-GUGUBot/issues/new)

### 联系方式

- **QQ**：[1377820366](http://wpa.qq.com/msgrd?v=3&uin=1377820366&site=qq&menu=yes)
- **QQ 群**：[726741344](https://qm.qq.com/q/TqmRHmTmcU)
- **GitHub Issues**：[提交问题](https://github.com/PFingan-Code/PF-GUGUBot/issues)

---

## 致谢

### 代码贡献

- [QQChat](https://github.com/AnzhiZhang/MCDReforgedPlugins/tree/master/src/qq_chat) | [AnzhiZhang](https://github.com/AnzhiZhang) - 原始代码基础

### 技术支持

- [@XueK__](https://github.com/XueK66) - 核心开发与技术支持

### 文档贡献

- [@Dreamwxz](https://github.com/Dreamwxz) - 第三方文档 [PF-plugins](https://docs.pfingan.com/PF-gugubot/)

### 社区反馈

感谢所有提交 Issue、Pull Request 和提供反馈的用户！

---

## TODO

- [ ] [多服聚合](https://github.com/PFingan-Code/PF-GUGUBot/issues/106)
- [ ] [联动 WebUI](https://github.com/PFingan-Code/PF-GUGUBot/issues/107) & [WebUI 开发](https://github.com/LoosePrince/PF-MCDR-WebUI/issues/8)

---

## 许可证

本项目基于 GPL-3.0 许可证开源。详见 [LICENSE](LICENSE.txt)。

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给我们一个 Star！**

Made with ❤️ by [LoosePrince](https://github.com/LoosePrince) & [XueK__](https://github.com/XueK66)

</div>
