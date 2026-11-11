# WebSocket 方式

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html
> 抓取日期：2026-11-10

## 发起连接到 Gateway

第一步先调用 [获取通用WSS 接入点](https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html) 或 [获取带分片WSS 接入点](https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/shard_url_get.html) 接口获取网关地址。

会得到一个类似下面这样的地址：

```text
wss://api.bot.qq.com/websocket/
```

然后进行 `websocket` 长连接建立，一旦连接成功，就会返回 OpCode 10 Hello 消息。这个消息主要的内容是心跳周期，单位毫秒(milliseconds)，如下：

```json
{
  "op": 10,
  "d": {
    "heartbeat_interval": 45000
  }
}
```

## 登录鉴权获得 Session

`websocket` 长连接建立之后，需要进行登录鉴权，登录鉴权成功后会获得一个 session 会话 id，只有登录成功后，QQ 后台才会下发事件通知。

发送一个 OpCode 2 Identify 消息，`payload` 如下：

```json
{
  "op": 2,
  "d": {
    "token": "token string",
    "intents": 513,
    "shard": [0, 4],
    "properties": {
      "$os": "linux",
      "$browser": "my_library",
      "$device": "my_library"
    }
  }
}
```

| **字段** | **描述** |
| --- | --- |
| token | 格式为 "QQBot {AccessToken}" |
| intents | 是此次连接所需要接收的事件，具体可参考 [事件订阅 Intents](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html#事件订阅-intents) |
| shard | 考虑到开发者事件接收时可以实现负载均衡，QQ 提供了分片逻辑，事件通知会落在不同的分片上，该参数是个拥有两个元素的数组。例如：`[0,4]`，代表分为四个片，当前链接是第 0 个片，业务稍后应该继续建立 `shard` 为 `[1,4]`, `[2,4]`, `[3,4]` 的链接，才能完整接收事件，更多详细的内容可以参考 [Shard 机制](#%E5%88%86%E7%89%87%E8%BF%9E%E6%8E%A5-loadbalance)。若无需分片，使用 `[0, 1]` 即可。 |
| properties | 目前无实际作用，可以按照自己的实际情况填写，也可以留空 |

鉴权成功之后，QQ 后台会下发一个 Ready Event，`payload` 如下：

```json
{
  "op": 0,
  "s": 1,
  "t": "READY",
  "d": {
    "version": 1,
    "session_id": "082ee18c-0be3-491b-9d8b-fbd95c51673a",
    "user": {
      "id": "6158788878435714165",
      "username": "群pro测试机器人",
      "bot": true
    },
    "shard": [0, 0]
  }
}
```

## 发送心跳 Ack

鉴权成功之后，就需要按照周期进行心跳发送。d 为客户端收到的最新的消息的 s，如果是首次连接，d 为传 null，`payload` 如下：

```json
{
  "op": 1,
  "d": 251
}
```

心跳发送成功之后会收到 OpCode 11 Heartbeat ACK 消息，`payload` 如下：

```json
{
  "op": 11
}
```

## 恢复登录态 Session

有很多原因可能会导致 `websocket` 长连接断开，断开之后短时间内重连会补发中间遗漏的事件，以保障业务逻辑的正确性。断开重连 gateway 后不需要发送重新登录 OpCode 2 Identify 请求。在连接到 `Gateway` 之后，需要发送 OpCode 6 Resume 消息，`payload` 如下：

```json
{
  "op": 6,
  "d": {
    "token": "my_token",
    "session_id": "session_id_i_stored",
    "seq": 1337
  }
}
```

其中 `seq` 指的是在接收事件时候的 `s` 字段，我们推荐开发者在处理过事件之后记录下 `s` 这样可以在 `resume` 的时候传递给 `websocket`，`websocket` 会自动补发这个 seq 之后的事件。

恢复成功之后，就开始补发遗漏事件，所有事件补发完成之后，会下发一个 `Resumed Event`，`payload` 如下：

```json
{
  "op": 0,
  "s": 2002,
  "t": "RESUMED",
  "d": ""
}
```

## 分片连接 LoadBalance

随着 bot 的增长并被添加到越来越多的频道中，事件越来越多，业务有必要对事件进行水平分割，实现负载均衡。机器人网关实现了一种用户可控制的分片方法，该方法允许跨多个网关连接拆分事件。分片完全由用户控制，并且不需要在单独的连接之间进行状态共享。

要在连接上启用分片，需要在建立连接的时候指定分片参数，具体参考 [gateway](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/reference.html)

### 获得合适的分片数

使用 [/gateway/bot](https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/shard_url_get.html) 接口获取网关地址的时候，会同时返回一个建议的 `shard` 数，及最大并发限制。

```json
{
  "url": "wss://api.bot.qq.com/websocket",
  "shards": 1,
  "session_start_limit": {
    "total": 1000,
    "remaining": 1000,
    "reset_after": 86400000,
    "max_concurrency": 1
  }
}
```

### 分片规则

分片是按照频道 id 进行哈希的，同一个频道的信息会固定从同一个链接推送。具体哈希计算规则如下：

```bash
shard_id = (guild_id >> 22) % num_shards
```

### 最大连接数

每个机器人创建的连接数不能超过 `remaining` 剩余连接数。

## WebSocket 错误码

| 值 | 含义 | 是否可以重试 RESUME | 是否可以重试 IDENTIFY |
| --- | --- | --- | --- |
| 4001 | 无效的 opcode | 否 | 否 |
| 4002 | 无效的 payload | 否 | 否 |
| 4007 | seq 错误 | 否 | **是** |
| 4006 | 无效的 session id，无法继续 resume，请 identify | 否 | **是** |
| 4008 | 发送 payload 过快，请重新连接，并遵守连接后返回的频控信息 | **是** | **是** |
| 4009 | 连接过期，请重连并执行 resume 进行重新连接 | **是** | **是** |
| 4010 | 无效的 shard | 否 | 否 |
| 4011 | 连接需要处理的 guild 过多，请进行合理的分片 | 否 | 否 |
| 4012 | 无效的 version | 否 | 否 |
| 4013 | 无效的 intent | 否 | 否 |
| 4014 | intent 无权限 | 否 | 否 |
| 4900~4913 | 内部错误，请重连 | 否 | **是** |
| 4914 | 机器人已下架，只允许连接沙箱环境，请断开连接，检验当前连接环境 | 否 | 否 |
| 4915 | 机器人已封禁，不允许连接，请断开连接，申请解封后再连接 | 否 | 否 |

针对 WebSocket 错误码的简单处理逻辑：

- 4009 可以重新发起 resume
- 4914，4915 不可以连接，请联系官方解封
- 其他错误，请重新发起 identify
