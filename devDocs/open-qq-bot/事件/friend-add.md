# 用户添加好友

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/friend_add.html
> 抓取日期：2026-11-10

通过传 scene\_param 中的 callback\_data 可区分不同来源的添加好友场景。

## 事件

| 字段 | 值 |
| --- | --- |
| 事件名 | FRIEND\_ADD |
| Intent | GROUP\_AND\_C2C\_EVENT (1<<25) |

### 事件体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| timestamp | integer | 添加时间戳（Unix 秒） |
| openid | string | 用户 OpenID |
| scene | integer | 加好友场景值。1000=缺省默认, 1001=网络搜索（全部tab）, 1002=网络搜索（机器人tab）, 1003=群场景, 1004=空间场景, 2001=站内分享资料页, 2002=站外分享资料页, 2003=开发者生成的分享链接（站内）, 2004=开发者生成的分享链接（站外） |
| scene\_param | string | 开发者自定义的回调数据（callback\_data），用于区分不同来源 |
| author | [FriendAuthor](#schema-friendauthor) | 用户信息 |
| short\_code | string | 机器人分享链接的短链code |

**FriendAuthor**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| union\_openid | string | 用户统一 OpenID（跨应用标识） |

### 事件示例

**用户添加好友（网络搜索场景）**

```text
{
  "openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570523,
  "scene": 1001,
  "scene_param": "",
  "author": {
    "union_openid": "DB85A74E07BA08B5B44CD9ED332FCBD2"
  }
}
```

**用户添加好友（开发者分享链接）**

```text
{
  "openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
  "timestamp": 1784570600,
  "scene": 2003,
  "scene_param": "callback_abc123",
  "author": {
    "union_openid": "DB85A74E07BA08B5B44CD9ED332FCBD2"
  }
}
```
