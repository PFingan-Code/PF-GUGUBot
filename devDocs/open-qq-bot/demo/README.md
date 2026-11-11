# QQ 官方机器人 Demo

独立单文件 Demo（`qq_official_demo.py`），用官方机器人 API 演示与 GUGUBot（OneBot/NapCat 版）对应的 QQ 侧能力。行为参照 `devDocs/proj/` 的两份源码分析文档，官方接口细节见 `devDocs/open-qq-bot/`（起步指南 / 事件 / 消息 / 群管理）。

## 运行

```bash
pip install websocket-client
# 复制 config.example.json 为 config.json，填入 AppID/AppSecret
python qq_official_demo.py
```

`sandbox: true` 走沙箱环境（`sandbox.api.bot.qq.com`），`false` 走正式环境。

## 前置条件

1. [QQ 开放平台](https://q.qq.com/) 创建机器人，拿到 AppID/AppSecret。
2. 机器人加入目标群。
3. **群主在手机 QQ 添加机器人时「设置权限」**（详见 `../事件/event-group-message-create.md` 实践要点）：
   - 接收全量消息 → 群内所有消息改推 `GROUP_MESSAGE_CREATE`（聊天同步类功能的基础，仅 @ 模式收不到非 @ 消息）；
   - 主动推送消息 → 欢迎/告别等主动发言；
   - 撤回成员消息（机器人设为群管理员）→ 违禁词撤回。

## 功能对照（GUGUBot → Demo）

| GUGUBot 功能（见 `../../proj/QQ消息处理流程与功能清单.md`） | Demo 对应实现 | 官方接口 |
|---|---|---|
| 违禁词拦截+提醒（管理员豁免） | 命中即撤回 + 提醒；撤回需管理员身份、消息未超 2 分钟 | `DELETE /v2/groups/{openid}/messages/{id}` |
| 关键词回复 | `keywords` 配置命中即被动回复 | `POST /v2/groups/{openid}/messages` |
| 群命令（#帮助 等） | 「帮助」「图片/视频/语音/文件」「成员列表」「群信息」「机器人状态」「公告 内容」「发本地文件 <文件名>」（管理员，分片上传） | 见 `消息/`、`群管理/` |
| 群成员对账 | 「成员列表」= 成员清点 + 本机活跃统计 TOP5（`activity.json` 持久化）；成员/群信息接口为白名单内邀（11253 优雅降级） | `群管理/group-members.md` |
| 多媒体消息（图片转发） | 收到图片 → **Markdown 图文回显（附文件名说明）**，失败回退纯图片转存；发送「图片」回演示图（rich-media 上传） | `POST /v2/groups/{openid}/files`、Markdown `![](url)` |
| 语音/视频/文件/分片上传 | 「视频/语音/文件」命令走 URL 上传（file_type 2/3/4）；「发本地文件」走分片上传四步（prepare→PUT→part_finish→files 合并），限 demo 目录内、管理员触发 | `消息/rich-media.md`、`分片上传/` |
| 单聊扩展 | 「图片」= 单聊媒体上传发送；「撤回」= 撤回机器人最近一条单聊回复（2 分钟内，超时报 40064004） | `消息/user-files-post.md`、`user-messages-delete.md` |
| 引用回复 | 群文本回复默认携带 `message_reference`（msg_idx 取自入站 `message_scene.ext`），`quote_reply_enable` 可关 | `group-messages-post.md` |
| 收发分离 | `listen_groups` 群白名单（空=全部响应）；`send_groups` 主动消息目标群（空=回事件来源群），对照 GUGUBot `group_ids` ≠ `forward_group_ids` | 纯配置 |
| 发送层：长消息分片 + 0.5~1.5s 随机限速 | `split_message()` 优先换行切分，多片间随机 sleep | 消息长度超限报 40054007 |
| 被动回复管理 | `SeqManager`：同一 msg_id 最多 5 次、自动换 seq 重试 40054005、过期配额清理 | 被动消息 5 分钟有效、5 次上限 |
| at 段渲染成名字 | 入站 `<@openid>`/`<qqbot-at-user/>` 替换为 @昵称；**被 @ 时经 Markdown 消息发送 `<qqbot-at-user id="{member_openid}" />` @ 回对方**（实测 @ 标签仅在 msg_type=2 渲染，纯文本一律原样显示） | `POST /v2/groups/{openid}/messages` |
| 进出服通知 | `GROUP_MEMBER_ADD`/`REMOVE` → 欢迎(@新成员，Markdown)/告别（主动消息，可关） | 主动消息受频控 |
| 消息去重 | `DedupSet`：官方可能重复推送同一 msg_id | — |

## 配置项

| 键 | 默认 | 说明 |
|---|---|---|
| `app_id` / `app_secret` | — | 开放平台凭证 |
| `sandbox` | `true` | 沙箱/正式环境 |
| `log_file` | 无 | 日志文件名（滚动 1MB×3，同时输出控制台） |
| `echo_enable` | `true` | 未命中其他规则时原样 echo |
| `at_reply_enable` | `true` | 被 @ 时回复并 @ 回对方 |
| `at_reply_format` | `markdown` | @ 格式：`markdown`=经 msg_type=2 Markdown 发送 `<qqbot-at-user>` 标签；`qqbot-at-user`/`legacy`=纯文本下两种标记（均实测原样显示，不渲染）；`off`=不 @ |
| `image_echo_enable` | `true` | 收到图片转存回显 |
| `member_notice_enable` | `true` | 入群欢迎 / 退群告别 |
| `listen_groups` | `[]` | 群白名单：非空时仅响应列表内的群 |
| `send_groups` | `[]` | 主动消息（欢迎/告别）目标群：非空时发往列表内群，空=回事件来源群 |
| `quote_reply_enable` | `true` | 群文本回复携带引用回复（message_reference） |
| `welcome_text` / `farewell_text` | 见 example | 欢迎/告别文案（主动消息） |
| `max_message_length` | `2000` | 单片长度上限，超出自动分片 |
| `keywords` | `{}` | 关键词 → 回复文本 |
| `ban_words` | `[]` | 违禁词列表（命中撤回+提醒） |
| `demo_image_url` | `""` | 「图片」命令发送的演示图 URL |
| `demo_video_url` / `demo_voice_url` / `demo_file_url` | `""` | 「视频」「语音」「文件」命令的演示媒体 URL（mp4 / silk / 任意格式） |

## 官方平台限制速查

- 被动回复：5 分钟内有效，同一 msg_id 最多 5 次；相同 `msg_id+msg_seq` 去重（错误码 40054005）。
- 主动消息频控：Bot 维度 30~60 条/分钟；单群 20 条/分钟、1000 条/天。
- 群文本消息长度超限：40054007。
- WebSocket 关闭码 4914/4915 = 机器人下架/封禁，直接退出；4008/4009 可 Resume，其余重新 Identify。
- 错误码全表见 `../消息/group-messages-post.md`。

## 安全

`config.json`（真实密钥）与 `*.log`（含 openid）已在 `.gitignore` 中排除，勿提交。

## 官方文档补充记录（2026-11-11）

- `<qqbot-at-everyone />` @全体成员：群聊**文本、Markdown** 消息均支持；机器人需为该群管理员；**每群每天仅 1 次**。demo 中由「公告 内容」命令触发（群主/管理员可用）。实测：第二次触发返回 **HTTP 400 + 错误码 40034142**「@全体成员次数超限」（该码不在 group-messages-post.md 错误码表中）。
- Markdown 图片语法 `![说明 #宽px #高px](url)`：url 可为公网图片，也可为 `qqbot-media://` 素材引用（素材管理三步上传 prepare/PUT/complete：≤10MB、100 张/机器人、90 天滑动过期）——本地存档见 `../消息/material-management.md`。
- 图片+文字说明（caption）通过 Markdown 图文实现；`msg_type=7` 是否支持 content 并存官方仍无说明（demo 已不依赖）。

## 已实测确认（2026-11-10，正式环境）

- `<qqbot-at-user id="{member_openid}" />` 标签**仅在 Markdown 消息（msg_type=2）中渲染**为可点击 @ 标签；纯文本（msg_type=0）API 接受（HTTP 200）但客户端原样显示——新标签与旧 `<@openid>` 格式均如此；
- 群聊自定义 Markdown 对所有机器人开放（`消息/markdown.md`），无需申请模板；被动回复锚点（msg_id/msg_seq）对 Markdown 消息同样适用；
- 入站方向：全量模式下 @机器人 的标记是旧格式 `<@{bot_openid}>`，与 READY 事件返回的数字 `user.id` 不同；识别「被 @」以 `mentions` 数组中的 `bot: true` 标志为准。
