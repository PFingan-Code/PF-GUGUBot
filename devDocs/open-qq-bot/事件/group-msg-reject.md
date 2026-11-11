# 群聊消息接收关闭

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_msg_reject.html
> 抓取日期：2026-11-10

群管理员在机器人资料页操作关闭通知时触发。

## 事件

| 字段 | 值 |
| --- | --- |
| 事件名 | GROUP\_MSG\_REJECT |
| Intent | GROUP\_AND\_C2C\_EVENT (1<<25) |

### 事件体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| timestamp | integer | 操作时间戳（Unix 秒） |
| group\_openid | string | 群 OpenID |
| op\_member\_openid | string | 操作群成员 OpenID |

### 事件示例

**群消息接收关闭**

```text
{
  "timestamp": 1784276810,
  "group_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "op_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
}
```
