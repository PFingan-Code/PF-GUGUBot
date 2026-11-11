# 获取群成员列表

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_members.get.html
> 抓取日期：2026-11-10

获取群成员列表，每次最多返回 30 条，支持分页。

该能力正在内邀接入中，敬请期待

## 请求

### 基础信息

| 字段 | 值 |
| --- | --- |
| HTTP URL | /v2/groups/{group\_openid}/members |
| HTTP Method | GET |
| 接口频率限制 | 60 QPM |

## 路径参数

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| group\_openid | string | 是 | 群OpenID |

## 请求体

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| cursor | string | 否 | 分页游标，首次请求可不传或传空串；后续传上一次响应的 next\_cursor |

### 请求示例

```text
GET /v2/groups/3E5D8A1F7B2C9E4D6A0F1B3C5D7E9F2A/members?cursor=
```

## 响应

### 响应体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| members | [][Member](#schema-member) | 成员列表，每次最多返回 30 条 |
| next\_cursor | string | 下一页游标，空串表示已到末页 |

**Member**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| member\_openid | string | 成员 OpenID |
| username | string | 用户昵称 |
| member\_role | string | 群成员角色 member-普通成员，owner-群主，admin-管理员 |
| bot | boolean | 是否机器人 |
| joined\_at | string | 入群时间戳（RFC3339格式） |
| union\_openid | string | 用户在应用/开放平台下的统一标识（如有） |

## 响应示例

```json
{
    "members": [
        {
            "member_openid": "7A3B9C1D5E2F4A6B8C0D1E3F5A7B9C2D",
            "username": "阳光小助手",
            "member_role": "member",
            "bot": false,
            "joined_at": "2025-08-20T09:15:00+08:00",
            "union_openid": "9F2E872045CCCC5948BEAF5B5FCCDF22"
        },
        {
            "member_openid": "EC58D87F598C8294A533B9D458DAAF33",
            "username": "T小不点101",
            "member_role": "member",
            "bot": false,
            "joined_at": "2025-07-01T10:30:00+08:00",
            "union_openid": "FE003FAF76C4817251FDC128A16753BB"
        }
    ],
    "next_cursor": "bG1fNmIxOTM1NTRjNy4zMA"
}
```

### 错误码

| 错误码 | 描述 | 排查建议 |
| --- | --- | --- |
| 11253 | 应用无接口访问权限 | 该接口仅白名单机器人可用，请联系平台运营申请权限 |
