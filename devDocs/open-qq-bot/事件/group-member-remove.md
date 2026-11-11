# 群成员退出

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_member_remove.html
> 抓取日期：2026-11-10

群成员退出或被移出群聊时触发。

## 事件

| 字段 | 值 |
| --- | --- |
| 事件名 | GROUP\_MEMBER\_REMOVE |
| Intent | GROUP\_MEMBER\_EVENT (1<<24) |

### 事件体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| timestamp | integer | 事件时间戳（Unix 秒） |
| group\_openid | string | 群 OpenID |
| member\_openid | string | 退出成员的 OpenID |
| user\_openid | string | 退出成员的用户 OpenID（可能为空） |

### 事件示例

**示例1**

```text
{
  "timestamp": 1784276759,
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "member_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
  "user_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6"
}
```
