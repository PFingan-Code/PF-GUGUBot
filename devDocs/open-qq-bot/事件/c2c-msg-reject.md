# 单聊消息接收关闭

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_msg_reject.html
> 抓取日期：2026-11-10

用户在机器人资料卡手动关闭"主动消息"推送时触发。

用户在机器人资料卡手动关闭主动消息推送时触发。关闭后机器人无法向该用户发送主动消息。

## 事件

| 字段 | 值 |
| --- | --- |
| 事件名 | C2C\_MSG\_REJECT |
| Intent | GROUP\_AND\_C2C\_EVENT (1<<25) |

### 事件体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| timestamp | integer | 操作时间戳（Unix 秒） |
| openid | string | 用户 OpenID |

### 事件示例

**C2C消息接收关闭**

```text
{
  "openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570599
}
```
