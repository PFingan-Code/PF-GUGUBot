# 撤回群聊消息

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages_message_id.delete.html
> 抓取日期：2026-11-10

撤回群消息。发送超过 2 分钟的消息不可撤回。
成功返回 HTTP 200，无响应体。

- 发送超出 **2 分钟**的消息不可撤回。
- 机器人如果是群管理员，可以撤回机器人自己的消息以及普通群成员的消息，群成员的消息ID从群消息事件`GROUP_AT_MESSAGE_CREATE`或`GROUP_MESSAGE_CREATE`里，`d.id`这个字段中获取。
- 机器人如果是普通成员，只能撤回机器人自己发送的消息，消息ID可以从消息发送接口响应里获取。

## 请求

### 基础信息

| 字段 | 值 |
| --- | --- |
| HTTP URL | /v2/groups/{group\_openid}/messages/{message\_id} |
| HTTP Method | DELETE |
| 接口频率限制 | 10 QPS |

## 路径参数

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| group\_openid | string | 是 | 群 OpenID |
| message\_id | string | 是 | 消息 ID |

### 请求示例

**撤回群消息**

```text
DELETE /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages/0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF
```

## 响应

无

## 响应示例

**响应示例**

```json
{}
```

### 错误码

| 错误码 | 描述 | 排查建议 |
| --- | --- | --- |
| 40061001 | 请求参数无效 | 请检查请求参数格式 |
| 40062003 | 无操作权限 | 请检查机器人是否有操作权限，机器人是否为群管理员或者发消息的用户是否为普通用户 |
| 40064004 | 已超出消息撤回时限 | 消息发送超过2分钟后不可撤回 |
| 50065001 | 消息撤回失败，请稍后重试 | 请稍后重试 |
