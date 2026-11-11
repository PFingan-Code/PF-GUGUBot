# 消息收发概述

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html
> 抓取日期：2026-11-10

机器人可在 QQ 单聊、群聊、频道三种场景下收发消息。本页介绍基础概念与通用规则，具体接口与事件请参考对应子分类。

## 收发场景

| 场景 | 发送消息 | 接收事件 |
| --- | --- | --- |
| QQ 单聊 | [发送单聊消息](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html) / [流式消息](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_stream_messages.post.html) | [C2C\_MESSAGE\_CREATE](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_message_create.html) |
| QQ 群聊 | [发送群消息](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) | [GROUP\_AT\_MESSAGE\_CREATE](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_at_message_create.html) / [GROUP\_MESSAGE\_CREATE](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html) |
| 频道 | [发送子频道消息](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/send.html) / [频道私信](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/dms.html) | [频道消息事件](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/event.html) |

### 对话场景图示

说明

机器人可以被添加各种聊天场景下

| 单聊 | 群聊 | 文字子频道 | 频道私信 |
| --- | --- | --- | --- |
| 单聊 | 群聊 | 文字子频道 | 频道私信 |

## 主动消息与被动消息

| 类型 | 特征 | 说明 |
| --- | --- | --- |
| 主动消息 | 无任何条件 | 机器人主动触达用户，用户可在客户端关闭「允许主动发送」开关，关闭后主动消息将发送失败 |
| 互动召回消息 | `is_wakeup=true` | 用户主动与机器人对话之后每个周期内可下发 1 条召回消息 |
| 被动消息（回复用户） | 携带 `msg_id` | 对用户消息的回复 |
| 被动消息（响应事件） | 携带 `event_id` | 对事件的回复 |

## 消息类型

通过 `msg_type` 指定消息内容格式：

| msg\_type | 类型 | 内容字段 | 发送 | 接收 |
| --- | --- | --- | --- | --- |
| 0 | 文本 | `content` | ✅ | ✅ |
| 2 | Markdown | `markdown` | ✅ | - |
| 7 | 富媒体 | `media`（需先上传文件获取 `file_info`） | ✅ | ✅ |

除上述之外，响应中还可能收到图片、视频、语音、表情、卡片等类型，详见 [消息类型](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/overview.html)。

## 富媒体消息

图片、视频、语音、文件等富媒体需先上传获取 `file_info`，再通过发消息接口（`msg_type=7`）携带 `media.file_info` 发送。

上传方式：

- **分片上传**：推荐使用，无需开发者提供公网 CDN 地址，参考 [分片上传流程](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html#分片上传（推荐）)
- **整文件上传**：[单聊上传](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html#url-上传) / [群聊上传](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html#url-上传)

> - `file_info` 有时效性（`ttl`），过期需重新上传。
> - 单聊和群聊的文件上传接口不互通。

## 频率与时效规则

### 被动消息

| 场景 | 有效期 | 每条消息可回复次数 |
| --- | --- | --- |
| 单聊 | 60 分钟 | 4 次 |
| 群聊 | 5 分钟 | 5 次 |
| 频道 | 5 分钟 | - |

### 主动消息

主动消息与被动消息说明： QQ 用户可以在 QQ 客户端主动设置是否接收机器人发送的主动消息，如果设置了关闭，主动消息一律发送失败。

#### 单聊

- 主动消息发送频率限制（HTTP接口）

| 认证类型 | 场景 | Bot 维度频控 | 单关系维度频控 | 每日上限 |
| --- | --- | --- | --- | --- |
| 企业认证 | 单聊 | 10/qps | 20/qpm | 1000 条/用户 |
| 个人认证 | 单聊 | 10/qps | 20/qpm | 1000 条/用户 |
| 未认证 | 单聊 | 5/qps & 30/qpm | 20/qpm | 1000 条/用户 |

- 互动召回消息：在用户主动与机器人对话之后，机器人在未来 30 天内可下发互动召回消息给用户（消息类型与当前机器人拥有的消息类型权限一致），每个周期内可下发一条。分别为：当天、1 - 3 天、3 - 7 天、7 - 30 天，合计：4 个周期。在发消息接口中使用 is\_wakeup 字段声明使用该能力。

#### 群聊

- 主动消息发送频率限制（HTTP接口）

| 认证类型 | 场景 | Bot 维度频控 | 单关系维度频控 | 每日上限 |
| --- | --- | --- | --- | --- |
| 企业认证 | 群 | 60/qpm | 20/qpm | 1000 条/群 |
| 个人认证 | 群 | 60/qpm | 20/qpm | 1000 条/群 |
| 未认证 | 群 | 30/qpm | 20/qpm | 1000 条/群 |

#### 文字子频道

- 主动消息在频道主或管理设置了情况下，按设置的数量进行限频。在未设置的情况遵循如下限制:
  - 主动推送消息，默认每天往每个子频道可推送的消息数是 20 条，超过会被限制。
  - 主动推送消息在每个频道中，每天可以往 2 个子频道推送消息。超过后会被限制。
- 不论主动消息还是被动消息，在一个子频道中，每秒 最多可发送 5 条 消息。
- 被动回复消息有效期为 5 分钟，超时会发送失败。
- 发送消息接口要求机器人接口需要连接到 WebSocket 上保持在线状态
- 有关主动消息审核，可以通过 事件订阅 Intents 中审核事件 MESSAGE\_AUDIT 返回 MessageAudited 对象获取结果。

#### 频道私信

- 私信场景下，每个机器人每天可以对一个用户发 2 条 主动消息。
- 私信场景下，每个机器人每天累计可以发 200 条 主动消息。
- 被动回复消息有效期为 5 分钟，超时会发送失败。

## 消息去重

相同 `msg_id` 可能多次推送，请结合 `msg_seq` 去重。被动回复时，相同的 `msg_id + msg_seq` 重复发送会失败，可递增 `msg_seq` 实现对同一消息的多次回复。

## 撤回消息

机器人可撤回自己发送的消息（发送超过 **2 分钟**不可撤回）：

- [撤回单聊消息](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages_message_id.delete.html)
- [撤回群聊消息](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages_message_id.delete.html)
- [撤回频道消息](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/recall.html) / [撤回频道私信](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/dms.html#撤回私信)
