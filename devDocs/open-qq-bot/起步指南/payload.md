# 通用数据结构

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html
> 抓取日期：2026-11-10

`payload` 指的是在 `webhook` 或 `websocket` 连接上传输的数据，网关的上下行消息采用的都是同一个结构，如下：

```json
{
  "id":"event_id",
  "op": 0,
  "d": {},
  "s": 42,
  "t": "GATEWAY_EVENT_NAME"
}
```

| 字段 | 描述 |
| --- | --- |
| id | 事件id |
| op | 指的是 opcode，参考连接维护 |
| s | 下行消息都会有一个序列号，标识消息的唯一性，客户端需要再发送心跳的时候，携带客户端收到的最新的 s |
| t | 代表事件类型。主要用在 op 为 0 Dispatch 的时候 |
| d | 代表事件内容，不同事件类型的事件内容格式都不同，请注意识别。主要用在 op 为 0 Dispatch 的时候 |

## OpCode 含义

所有 `opcode` 列表如下：

| **CODE** | **名称** | **接入方式** | **客户端行为** | **描述** |
| --- | --- | --- | --- | --- |
| 0 | Dispatch | webhook/websocket | Receive | 服务端进行消息推送 |
| 1 | Heartbeat | websocket | Send/Receive | 客户端或服务端发送心跳 |
| 2 | Identify | websocket | Send | 客户端发送鉴权 |
| 6 | Resume | websocket | Send | 客户端恢复连接 |
| 7 | Reconnect | websocket | Receive | 服务端通知客户端重新连接 |
| 9 | Invalid Session | websocket | Receive | 当 identify 或 resume 的时候，如果参数有错，服务端会返回该消息 |
| 10 | Hello | websocket | Receive | 当客户端与网关建立 ws 连接之后，网关下发的第一条消息 |
| 11 | Heartbeat ACK | websocket | Receive/Reply | 当发送心跳成功之后，就会收到该消息 |
| 12 | HTTP Callback ACK | webhook | Reply | 仅用于 http 回调模式的回包，代表机器人收到了平台推送的数据 |
| 13 | 回调地址验证 | webhook | Receive | 开放平台对机器人服务端进行验证 |

客户端行为含义如下：

- `Receive` 客户端接收到服务端 `push` 的消息
- `Send` 客户端发送消息
- `Reply` 客户端接收到服务端发送的消息之后的回包（HTTP 回调模式）

## 事件订阅 Intents

事件的 `intents` 是一个标记位，每一位都代表不同的事件，如果需要接收某类事件，就将该位置为 `1`。

每个 `intents` 位代表的是一类事件，可以使用 `websocket` 传输的数据中的 `t` 字段的值来区分。

事件和位移的关系如下：

```text
GUILDS (1 << 0)
  - GUILD_CREATE           // 当机器人加入新guild时
  - GUILD_UPDATE           // 当guild资料发生变更时
  - GUILD_DELETE           // 当机器人退出guild时
  - CHANNEL_CREATE         // 当channel被创建时
  - CHANNEL_UPDATE         // 当channel被更新时
  - CHANNEL_DELETE         // 当channel被删除时

GUILD_MEMBERS (1 << 1)
  - GUILD_MEMBER_ADD       // 当成员加入时
  - GUILD_MEMBER_UPDATE    // 当成员资料变更时
  - GUILD_MEMBER_REMOVE    // 当成员被移除时

GUILD_MESSAGES (1 << 9)    // 消息事件，仅 *私域* 机器人能够设置此 intents。
  - MESSAGE_CREATE         // 发送消息事件，代表频道内的全部消息，而不只是 at 机器人的消息。内容与 AT_MESSAGE_CREATE 相同
  - MESSAGE_DELETE         // 删除（撤回）消息事件

GUILD_MESSAGE_REACTIONS (1 << 10)
  - MESSAGE_REACTION_ADD    // 为消息添加表情表态
  - MESSAGE_REACTION_REMOVE // 为消息删除表情表态

DIRECT_MESSAGE (1 << 12)
  - DIRECT_MESSAGE_CREATE   // 当收到用户发给机器人的私信消息时
  - DIRECT_MESSAGE_DELETE   // 删除（撤回）消息事件

GROUP_AND_C2C_EVENT (1 << 25)
  - C2C_MESSAGE_CREATE      // 用户单聊发消息给机器人时候
  - FRIEND_ADD              // 用户添加使用机器人
  - FRIEND_DEL              // 用户删除机器人
  - C2C_MSG_REJECT          // 用户在机器人资料卡手动关闭"主动消息"推送
  - C2C_MSG_RECEIVE         // 用户在机器人资料卡手动开启"主动消息"推送开关
  - GROUP_AT_MESSAGE_CREATE // 用户在群里@机器人时收到的消息
  - GROUP_ADD_ROBOT         // 机器人被添加到群聊
  - GROUP_DEL_ROBOT         // 机器人被移出群聊
  - GROUP_MSG_REJECT        // 群管理员主动在机器人资料页操作关闭通知
  - GROUP_MSG_RECEIVE       // 群管理员主动在机器人资料页操作开启通知

INTERACTION (1 << 26)
  - INTERACTION_CREATE     // 互动事件创建时

MESSAGE_AUDIT (1 << 27)
  - MESSAGE_AUDIT_PASS     // 消息审核通过
  - MESSAGE_AUDIT_REJECT   // 消息审核不通过

FORUMS_EVENT (1 << 28)  // 论坛事件，仅 *私域* 机器人能够设置此 intents。
  - FORUM_THREAD_CREATE     // 当用户创建主题时
  - FORUM_THREAD_UPDATE     // 当用户更新主题时
  - FORUM_THREAD_DELETE     // 当用户删除主题时
  - FORUM_POST_CREATE       // 当用户创建帖子时
  - FORUM_POST_DELETE       // 当用户删除帖子时
  - FORUM_REPLY_CREATE      // 当用户回复评论时
  - FORUM_REPLY_DELETE      // 当用户回复评论时
  - FORUM_PUBLISH_AUDIT_RESULT      // 当用户发表审核通过时

AUDIO_ACTION (1 << 29)
  - AUDIO_START             // 音频开始播放时
  - AUDIO_FINISH            // 音频播放结束时
  - AUDIO_ON_MIC            // 上麦时
  - AUDIO_OFF_MIC           // 下麦时

PUBLIC_GUILD_MESSAGES (1 << 30) // 消息事件，此为公域的消息事件
  - AT_MESSAGE_CREATE       // 当收到@机器人的消息时
  - PUBLIC_MESSAGE_DELETE   // 当频道的消息被删除时
```

### 举例

如开发者需要接收用户 at 机器人的消息，那么就需要在 `intents` 中设置接收 `PUBLIC_GUILD_MESSAGES`。则需要先计算 `1 << 30` 的值。然后与 `0` 做位或操作，得到最终需要传递的 `intents`。

如果涉及到多个事件类型的接收，则需要将多个结果做位或操作，如：`0|1<<30|1<<1` 代表订阅 `PUBLIC_GUILD_MESSAGES` 和 `GUILD_MEMBERS` 这两类事件。

### 权限

事件类型的订阅，是有权限控制的，除了 `GUILDS`，`PUBLIC_GUILD_MESSAGES`，`GUILD_MEMBERS` 事件是基础的事件，默认有权限订阅之外，其他的特殊事件，都需要经过申请才能够使用，如果在鉴权的时候传递了无权限的 `intents`，`websocket` 会报错，并直接关闭连接。请开发者注意订阅事件的范围需要控制在自己所需要的范围之内。

如果拥有的某个特殊事件类型的权限被取消，则在当前连接上不会报错，但是将不会收到对应的事件类型，如果重新连接，则报错，所以如果开发者的事件类型权限被取消，请及时调整监听事件代码，避免报错导致的无法连接。
