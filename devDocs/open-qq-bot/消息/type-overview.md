# 消息类型

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/overview.html
> 抓取日期：2026-11-10

通过 `msg_type` 指定消息格式，不同的类型对应不同的内容字段和收发能力。

## 发送：msg\_type

发送消息时通过 `msg_type` 指定格式：

| msg\_type | 类型 | 内容字段 | 说明 |
| --- | --- | --- | --- |
| 0 | 文本 | `content` | 纯文本消息 |
| 2 | Markdown | `markdown` | 支持 Markdown 语法，详见 [Markdown 消息](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html) |
| 7 | 富媒体 | `media` | 图片/视频/语音/文件，需先上传获取 `file_info` |

## 接收：message\_type

收到用户消息时，事件体中的 `message_type` 表示消息内容类型：

| message\_type | 含义 | 说明 |
| --- | --- | --- |
| 0 | 普通文本 | `content` 字段携带文本内容 |
| 3 | 结构化卡片 | `ark_data` 字段携带卡片数据 |
| 103 | 引用消息 | `msg_elements` 字段携带嵌套内容 |

> 图片、视频、语音、文件等附加内容通过 `attachments` 字段携带（`content_type` 区分具体类型），不通过 `message_type` 单独表示。

## 各场景支持情况

| 类型 | 单聊 | 群聊 | 频道 |
| --- | --- | --- | --- |
| **文本** | 收发 ✅ | 收发 ✅ | 收发 ✅ |
| **Markdown** | 发 ✅ / 收 ❌ | 收发 ✅ | 发 ✅ / 收 ❌ |
| **图片** | 收发 ✅ | 收发 ✅ | 收发 ✅ |
| **视频** | 收发 ✅ | 收发 ✅ | 收发 ✅ |
| **语音** | 收发 ✅ | 收发 ✅ | 收发 ✅ |
| **文件** | 收发 ✅ | 收发 ✅ | ❌ |
| **结构化卡片** | 发 ❌ / 收 ✅ | 发 ❌ / 收 ✅ | 发 ❌ / 收 ❌ |
| **Embed** | ❌ | ❌ | 发 ✅ / 收 ❌ |
| **表情表态** | ❌ | ❌ | 收发 ✅ |
| **引用消息** | 收 ✅ | 收 ✅ | 收 ✅ |

> - 发送侧只有 msg\_type=0/2/3/7 四种（见上方表格）
> - 富媒体上传流程见 [富媒体使用说明](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html)
> - 表情表态仅频道支持，详见 [表情表态](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/emoji.html)
