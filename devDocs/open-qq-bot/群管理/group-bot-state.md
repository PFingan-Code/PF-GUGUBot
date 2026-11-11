# 获取机器人群内状态

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_bot_state.get.html
> 抓取日期：2026-11-10

获取机器人在指定群中的状态信息。

## 请求

### 基础信息

| 字段 | 值 |
| --- | --- |
| HTTP URL | /v2/groups/{group\_openid}/bot\_state |
| HTTP Method | GET |
| 接口频率限制 | 30 QPM |

## 路径参数

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| group\_openid | string | 是 | 群OpenID |

### 请求示例

**获取机器人群内状态**

```text
GET /v2/groups/3E5D8A1F7B2C9E4D6A0F1B3C5D7E9F2A/bot_state
```

## 响应

### 响应体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| member\_openid | string | 机器人的 openid |
| joined\_at | string | 入群时间戳（RFC3339格式） |
| allow\_proactive\_msg | boolean | 是否接收主动推送。true: 接受主动推送 |
| recv\_msg\_setting | string | 接受消息的类型：群内接收消息的设置：all、only\_mention、mention\_and\_context |
| member\_role | string | 群成员角色 member-普通成员，owner-群主，admin-管理员 |

## 响应示例

**获取机器人群内状态**

```json
{
  "member_openid": "7A3B9C1D5E2F4A6B8C0D1E3F5A7B9C2D",
  "joined_at": "2025-06-15T14:30:00+08:00",
  "allow_proactive_msg": false,
  "recv_msg_setting": "only_mention",
  "member_role": "member
}
```

### 错误码

| 错误码 | 描述 | 排查建议 |
| --- | --- | --- |
| 11253 | 应用无接口访问权限 | 该接口仅白名单机器人可用，请联系平台运营申请权限 |
