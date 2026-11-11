# 群成员加入

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_member_add.html
> 抓取日期：2026-11-10

有新成员加入群聊时触发。

## 事件

| 字段 | 值 |
| --- | --- |
| 事件名 | GROUP\_MEMBER\_ADD |
| Intent | GROUP\_MEMBER\_EVENT (1<<24) |

### 事件体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| timestamp | integer | 事件时间戳（Unix 秒） |
| group\_openid | string | 群 OpenID |
| member\_openid | string | 新加入成员的 OpenID |

### 事件示例

**示例1**

```text
{
  "timestamp": 1784276757,
  "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
  "member_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6"
}
```
