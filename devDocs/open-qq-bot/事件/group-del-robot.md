# 机器人退出群聊

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_del_robot.html
> 抓取日期：2026-11-10

机器人被移出群聊时触发。

## 事件

| 字段 | 值 |
| --- | --- |
| 事件名 | GROUP\_DEL\_ROBOT |
| Intent | GROUP\_AND\_C2C\_EVENT (1<<25) |

### 事件体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| timestamp | integer | 移除时间戳（Unix 秒） |
| group\_openid | string | 群 OpenID |
| op\_member\_openid | string | 操作移除机器人退群的群成员 OpenID |

### 事件示例

**机器人退出群聊**

```text
{
  "group_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "op_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570535
}
```
