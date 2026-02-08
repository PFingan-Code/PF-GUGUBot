# 疑难解答

本文档收集了常见问题及其解决方案。

---

## 安装问题

### 插件加载失败

**症状**：MCDR 提示插件加载失败，显示 ImportError 或 ModuleNotFoundError

**原因**：Python 依赖未安装或版本不兼容

**解决方案**：

1. 在服务器目录打开终端

2. 检查 Python 版本：
```bash
python --version
```
确保 ≥ 3.8

3. 安装依赖：
```bash
pip install "缺失的依赖"
```

4. 如果使用虚拟环境，确保激活了正确的环境：
```bash
source /path/to/venv/bin/activate  # Linux/Mac
# 或
\path\to\venv\Scripts\activate  # Windows
```

5. 检查日志文件 `logs/latest.log` 查看详细错误信息

---

### 依赖插件未安装

**症状**：提示缺少 `whitelist_api` 或 `mg_events`

**解决方案**：

安装缺失的依赖插件：

```bash
!!MCDR plugin install whitelist_api
!!MCDR plugin install mg_events
```

---

### 配置文件不存在

**症状**：启动后找不到 `config/GUGUbot/config.yml`

**解决方案**：

1. 手动下载默认配置文件：
   [default_config.yml](https://github.com/PFingan-Code/PF-GUGUBot/blob/main/GUGUbot/gugubot/config/defaults/default_config.yml)

2. 重命名为 `config.yml` 并放入 `config/GUGUbot/` 目录

3. 重新加载插件：
```bash
!!MCDR plugin reload gugubot
```

---

## 连接问题

### 无法连接到 QQ 机器人

**症状**：日志显示 "连接错误" 或 "Connection refused"

**可能原因**：

1. QQ 机器人未启动
2. WebSocket 端口配置错误
3. 防火墙阻止连接
4. GUGUBot 配置错误

**解决方案**：

#### 1. 检查 QQ 机器人状态

确认 QQ 机器人（NapCat/LLOneBot）已启动并成功登录。

#### 2. 检查端口配置

**QQ 机器人配置**：
- NapCat: 检查 WebSocket 端口设置
- LLOneBot: 检查正向 WebSocket 端口

#### 3. 检查防火墙

临时关闭防火墙测试：

**Linux**:
```bash
sudo ufw disable  # Ubuntu
sudo systemctl stop firewalld  # CentOS
```

**Windows**: 在控制面板中临时禁用防火墙

#### 4. 测试连接

使用 WebSocket 测试工具测试连接：
- [WebSocket King](http://websocketking.com/)
- 连接地址：`ws://127.0.0.1:8080`

#### 5. 查看详细日志

```bash
tail -f logs/latest.log
```

查找连接相关的错误信息。

---

### QQ 机器人频繁断线

**症状**：连接建立后很快断开，反复重连

**可能原因**：

1. 网络不稳定
2. QQ 机器人配置问题
3. 消息处理超时

**解决方案**：

#### 1. 增加重连间隔

编辑 `config/GUGUbot/config.yml`：

```yaml
connector:
  QQ:
    connection:
      reconnect: 10  # 增加到10秒
      max_wait_time: 10
```

#### 2. 检查消息上报格式

确保 QQ 机器人使用 **CQ 码** 格式上报消息，不是 JSON。

#### 3. 减少消息处理压力

如果群消息量很大，考虑：
- 启用消息过滤
- 减少转发的事件类型

---

### 多服互联连接失败

**症状**：桥接器无法连接到主服务器

**解决方案**：

#### 1. 检查主服务器是否启用

主服务器配置：
```yaml
connector:
  minecraft_bridge:
    enable: true
    is_main_server: true  # 必须为 true
    connection:
      port: 8787
```

#### 2. 检查子服务器配置

子服务器配置：
```yaml
connector:
  minecraft_bridge:
    enable: true
    is_main_server: false  # 必须为 false
    connection:
      host: 主服务器IP
      port: 8787
```

#### 3. 检查网络

确保子服务器可以访问主服务器的 8787 端口：

```bash
telnet 主服务器IP 8787
# 或
nc -zv 主服务器IP 8787
```

#### 4. 检查令牌

如果设置了令牌，确保主服务器和子服务器的令牌一致：

```yaml
connection:
  token: "your_secret_token"
```

---

## 功能问题

### 消息无法转发

**症状**：QQ 和游戏之间的消息不能互通

**解决方案**：

#### 1. 检查转发系统是否启用

```yaml
system:
  echo:
    enable: true  # 必须为 true
```

#### 2. 检查群号配置

```yaml
connector:
  QQ:
    permissions:
      group_ids:
        - 你的群号  # 必须正确
```

#### 3. 检查机器人是否在群内

确认机器人账号已加入配置的 QQ 群。

#### 4. 检查日志

查看是否有错误信息：
```bash
grep -i error logs/latest.log
```

---

### 命令无响应

**症状**：发送命令后机器人没有回复

**可能原因**：

1. 命令前缀错误
2. 系统未启用
3. 权限不足

**解决方案**：

#### 1. 检查命令前缀

默认前缀是 `#`，可在配置中修改：

```yaml
GUGUBot:
  command_prefix: "#"
```

确保使用正确的前缀，如 `#帮助` 而不是 `帮助`。

#### 2. 检查系统是否启用

例如绑定系统：
```yaml
system:
  bound:
    enable: true  # 必须启用
```

#### 3. 检查权限

某些命令需要管理员权限，确认你的 QQ 号在管理员列表中：

```yaml
connector:
  QQ:
    permissions:
      admin_ids:
        - 你的QQ号
```

#### 4. 查看日志

检查是否有命令处理的错误：
```bash
grep "#" logs/latest.log
```

---

### 绑定失败

**症状**：执行 `#绑定 玩家名` 后提示失败

**可能原因**：

1. 绑定系统未启用
2. 玩家名已被绑定
3. 达到绑定数量上限

**解决方案**：

#### 1. 启用绑定系统

```yaml
system:
  bound:
    enable: true
```

#### 2. 检查绑定数量限制

```yaml
system:
  bound:
    max_java_bound: 1     # 增加允许绑定的数量
    max_bedrock_bound: 1
```

#### 3. 查询现有绑定

```
#绑定 列表
```

如果已有绑定，先解绑：
```
#解绑 旧玩家名
```

#### 4. 检查玩家名格式

- Java 版：常规字符，3-16位
- 基岩版：可能包含空格，需要加 `基岩` 参数

```
#绑定 Steve1234 基岩
```

---

### 白名单操作失败

**症状**：白名单添加/删除命令无效

**可能原因**：

1. `whitelist_api` 未安装
2. 白名单系统未启用
3. RCON 未配置

**解决方案**：

#### 1. 安装 whitelist_api

```bash
!!MCDR plugin install whitelist_api
```

#### 2. 启用白名单系统

```yaml
system:
  whitelist:
    enable: true
```

#### 3. 配置 RCON（如果需要）

编辑 `config/whitelist_api/config.json`：

```json
{
  "rcon": {
    "enable": true,
    "host": "127.0.0.1",
    "port": 25575,
    "password": "your_rcon_password"
  }
}
```

服务器的 `server.properties`：
```properties
enable-rcon=true
rcon.port=25575
rcon.password=your_rcon_password
```

---

### 图片无法显示

**症状**：QQ 发送的图片在游戏内无法查看

**原因**：图片需要特殊插件支持

**解决方案**：

#### 方案一：使用 [ChatImage](https://github.com/kitUIN/ChatImage/blob/fabric-1.19.3/README.md)

1. 安装 ChatImage 插件
2. 配置：
```yaml
connector:
  minecraft:
    chat_image: true
```

#### 方案二：使用 ImagePreview

1. 安装 ImagePreview 插件
2. 配置：
```yaml
connector:
  minecraft:
    image_previewer: true
```

#### 方案三：仅显示链接

如果不安装插件，图片会以链接形式显示：
```
[图片: https://...]
```

玩家可以复制链接到浏览器查看。

---

## 性能问题

### 服务器卡顿

**症状**：启用 GUGUBot 后服务器出现卡顿

**可能原因**：

1. 消息处理占用太多资源
2. 频繁的网络请求
3. 日志记录过多

**解决方案**：

#### 1. 禁用详细日志

```yaml
GUGUBot:
  show_message_in_console: false
```

#### 2. 减少转发的事件

如果群消息量很大，可以关闭一些不必要的通知：

```yaml
connector:
  minecraft:
    mc_achievement: false  # 关闭成就通知
    player_join_notice: false  # 关闭进出通知（如果不需要）
```

#### 3. 过滤高频消息

使用正则表达式过滤不需要转发的消息：

```yaml
connector:
  minecraft:
    ignore_mc_command_patterns:
      - "!!.*"
      - ".+\\[Command.*"
```

---

### 内存占用高

**症状**：GUGUBot 占用过多内存

**解决方案**：

#### 1. 清理旧数据

定期清理不需要的数据文件：
```bash
cd config/GUGUbot/system/
# 备份后清理旧的数据文件
```

#### 2. 限制缓存

如果实现了缓存机制，设置合理的缓存大小和过期时间。

#### 3. 重启服务器

定期重启 MCDR 服务器释放内存：
```bash
!!MCDR restart
```

---

## 配置问题

### YAML 格式错误

**症状**：修改配置后插件无法加载，提示 YAML 解析错误

**原因**：YAML 格式对缩进非常敏感

**解决方案**：

#### 1. 检查缩进

- 必须使用空格，不能使用 Tab
- 每级缩进使用 2 个空格
- 保持一致的缩进

**错误示例**：
```yaml
connector:
QQ:  # 缩进错误
    enable: true
```

**正确示例**：
```yaml
connector:
  QQ:  # 2个空格缩进
    enable: true
```

#### 2. 使用在线工具验证

- [YAML Lint](http://www.yamllint.com/)
- [YAML Checker](https://yamlchecker.com/)

复制配置内容到这些工具检查语法。

#### 3. 恢复默认配置

如果无法修复，从 GitHub 下载默认配置文件重新开始。

---

### 配置不生效

**症状**：修改配置后没有变化

**解决方案**：

#### 1. 重载插件

```bash
!!MCDR plugin reload gugubot
```

某些配置需要重载才能生效。

#### 2. 重启 MCDR

有些配置需要完全重启：
```bash
!!MCDR restart
```

#### 3. 检查配置路径

确保修改的是正确的配置文件：
```
config/GUGUbot/config.yml  # 不是 default_config.yml
```

#### 4. 查看日志

检查是否有配置加载的错误：
```bash
grep -i config logs/latest.log
```

---

## 日志分析

### 如何查看日志

#### 实时查看

```bash
tail -f logs/latest.log
```

#### 搜索错误

```bash
grep -i error logs/latest.log
grep -i exception logs/latest.log
```

#### 搜索特定关键词

```bash
grep "GUGUBot" logs/latest.log
grep "连接" logs/latest.log
```

### 常见错误信息

#### "Connection refused"

**含义**：无法连接到目标服务（QQ 机器人或主服务器）

**解决**：检查目标服务是否启动，端口是否正确

#### "Permission denied"

**含义**：权限不足

**解决**：检查文件权限或用户权限配置

#### "Module not found"

**含义**：缺少 Python 模块

**解决**：安装缺失的依赖包

#### "JSON decode error"

**含义**：JSON 数据格式错误

**解决**：检查配置文件格式，删除损坏的数据文件

---

## 其他问题

### 中文乱码

**症状**：消息显示为乱码

**解决方案**：

#### 1. 检查文件编码

确保所有配置文件使用 UTF-8 编码。

#### 2. 检查终端编码

**Linux/Mac**:
```bash
export LANG=zh_CN.UTF-8
```

**Windows**: 使用支持 UTF-8 的终端，如 Windows Terminal

#### 3. 检查 Java 参数

在服务器启动脚本中添加：
```bash
java -Dfile.encoding=UTF-8 -jar server.jar
```

---

### 命令冲突

**症状**：某些命令与其他插件冲突

**解决方案**：

修改命令前缀：
```yaml
GUGUBot:
  command_prefix: "!"  # 改为其他符号
```

或修改其他插件的命令前缀。

---

### QQ 表情显示问题

**症状**：QQ 表情无法正确转换

**说明**：部分特殊表情可能无法完美转换

**解决方案**：

GUGUBot 会将常见表情转换为文字，如 `[呲牙]`、`[大笑]` 等。

如需自定义表情映射，修改 `gugubot/constant/qq_emoji_map.py`。

---

## 获取帮助

如果以上方案都无法解决你的问题：

### 1. 查看 GitHub Issues

搜索类似的问题：
[https://github.com/PFingan-Code/PF-GUGUBot/issues](https://github.com/PFingan-Code/PF-GUGUBot/issues)

### 2. 加入 QQ 交流群

群号：[726741344](https://qm.qq.com/q/TqmRHmTmcU)

在群内提问时，请提供：
- GUGUBot 版本
- MCDR 版本
- Python 版本
- 错误日志
- 相关配置

### 3. 提交 Issue

在 GitHub 上提交详细的问题报告：
[https://github.com/PFingan-Code/PF-GUGUBot/issues/new](https://github.com/PFingan-Code/PF-GUGUBot/issues/new)

包含以下信息：
- 问题描述
- 复现步骤
- 期望结果
- 实际结果
- 环境信息
- 错误日志

### 4. 联系作者

QQ：[1377820366](http://wpa.qq.com/msgrd?v=3&uin=1377820366&site=qq&menu=yes)

---

## 调试技巧

### 启用详细日志

```yaml
GUGUBot:
  show_message_in_console: true
```

### 测试模式

使用测试连接器进行本地测试：

```yaml
connector:
  test:
    enable: true
```

### 逐步排查

1. 确认基础连接正常
2. 测试简单功能（如帮助命令）
3. 逐步启用其他功能
4. 出问题时回退到上一步

---

## 常见配置错误

### 1. 端口冲突

**错误**：
```yaml
connector:
  QQ:
    connection:
      port: 8080  # 与其他服务冲突
```

**正确**：使用未被占用的端口，如 8777

### 2. 列表格式错误

**错误**：
```yaml
admin_ids:
  1234567890  # 缺少 -
```

**正确**：
```yaml
admin_ids:
  - 1234567890
```

### 3. 字符串格式错误

**错误**：
```yaml
command_prefix: #  # 特殊字符需要引号
```

**正确**：
```yaml
command_prefix: "#"
```

### 4. 布尔值错误

**错误**：
```yaml
enable: True  # 首字母大写错误
```

**正确**：
```yaml
enable: true  # 全小写
```

---

## 预防措施

### 1. 定期备份

备份配置和数据：
```bash
tar -czf gugubot_backup_$(date +%Y%m%d).tar.gz config/GUGUbot/
```

### 2. 版本管理

记录当前使用的版本：
```bash
!!MCDR plugin list
```

### 3. 测试环境

在测试服务器上先测试新功能或配置更改。

### 4. 阅读更新日志

更新前查看 [Release Notes](https://github.com/PFingan-Code/PF-GUGUBot/releases) 了解变更。

---

**如果这个文档没有解决你的问题，欢迎在 QQ 群或 GitHub 提问！**

