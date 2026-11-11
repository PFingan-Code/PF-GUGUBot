# 单聊消息事件

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_message_create.html
> 抓取日期：2026-11-10

用户给机器人发送单聊消息时触发。
为确保消息可达，相同 msg\_id 可能重复推送，开发者需结合 msg\_seq 做去重。

为确保消息可达，相同 msg\_id 可能重复推送，需结合 message\_scene.ext 中的 msg\_idx 做去重。message\_type 决定消息结构：0=纯文本，3=ARK卡片（ark\_data 有值），103=引用消息（msg\_elements 有值，message\_scene.ext 含 ref\_msg\_idx）。

## 事件

| 字段 | 值 |
| --- | --- |
| 事件名 | C2C\_MESSAGE\_CREATE |
| Intent | GROUP\_AND\_C2C\_EVENT (1<<25) |

### 事件体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| id | string | 消息 ID，可用于被动回复和撤回 |
| author | [User](#schema-user) | 发送者（user\_openid 有值） |
| content | string | 消息文本内容 |
| timestamp | string | 消息发送时间，RFC3339 格式 |
| message\_type | integer | 消息内容类型: 0=普通文本, 3=结构化卡片, 101=并行消息, 102=聊天记录, 103=引用消息 |
| message\_scene | [MessageScene](#schema-messagescene) | 消息场景上下文（含消息索引、鉴权令牌等） |
| attachments | [][MessageAttachment](#schema-messageattachment) | 消息附件（图片、文件、语音等） |
| ark\_data | [ARKData](#schema-arkdata) | 结构化卡片消息数据（message\_type=3 时有值） |
| msg\_elements | [][MsgElement](#schema-msgelement) | 消息元素列表（message\_type=103 引用消息时包含被引用内容） |

**User**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| id | string | 用户唯一标识（OpenID 格式） |
| username | string | 用户昵称 |
| bot | boolean | 是否为机器人 |
| union\_openid | string | 跨应用统一用户 OpenID（可能为空） |
| union\_user\_account | string | 跨应用统一用户账号（可能为空） |
| user\_openid | string | 用户 OpenID（单聊场景使用） |
| member\_openid | string | 群成员 OpenID（群聊场景使用） |
| member\_role | string | 群内角色。member=普通成员, admin=管理员, owner=群主 |

**MessageScene**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| source | string | 场景来源。default=默认聊天窗口 |
| ext | []string | 扩展数据列表，key=value 格式: msg\_idx=消息索引, 用于引用场景 ref\_msg\_idx=引用的消息索引 auth\_token=鉴权令牌 |

**MessageAttachment**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| url | string | 附件下载 URL |
| filename | string | 文件名 |
| width | integer | 图片宽度（像素），非图片附件无此字段 |
| height | integer | 图片高度（像素），非图片附件无此字段 |
| size | integer | 文件大小（字节） |
| content\_type | string | 附件内容类型（MIME 类型）: voice=语音消息 image/jpeg=JPEG 图片 image/png=PNG 图片 image/gif=GIF 图片 video/mp4=MP4 视频 file=群文件 |
| voice\_wav\_url | string | 语音消息 SILK 等转换后的 WAV 文件 URL |
| asr\_refer\_text | string | 语音消息 ASR 参考结果 |

**ARKData**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| prompt | string | 卡片消息中的用户操作提示文本 |
| ark\_type | string | 卡片消息类型标识: tuwen = 图文 H5（如快手分享链接） feed = 图文卡片（群相册、频道帖子、分享卡片） miniapp = 小程序（微信小程序、QQ 小程序、哔哩哔哩等） map = 位置卡片 contact\_card = 好友名片 video\_share = 视频分享 music\_together = 一起听歌 picture = 图片 |
| ark\_name | string | 卡片消息类型的中文名称，如"图文 H5"、"小程序"、"图文卡片" |
| fields | object | 卡片消息字段，常见键名: tag/tags=来源标签, title=标题, desc=描述, jump\_url=跳转链接, preview=预览图, source=来源名称, source\_logo=来源图标, tag\_icon=标签图标, nickname=昵称, avatar=头像, address=地址 |

**MsgElement**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| msg\_idx | string | 消息元素在列表中的引用消息索引 |
| author | [User](#schema-user) | 该元素对应的消息发送者 |
| message\_type | integer | 消息内容类型: 0=普通文本, 3=结构化卡片, 101=并行消息, 102=聊天记录, 103=引用消息 |
| content | string | 消息正文内容 |
| attachments | [][MessageAttachment](#schema-messageattachment) | 该元素携带的附件 |
| ark\_data | [ARKData](#schema-arkdata) | 结构化卡片消息数据（message\_type=3 时有值） |
| msg\_elements | [][MsgElement](#schema-msgelement) | 嵌套消息元素列表（递归结构） |

### 事件示例

**示例1**

```text
{
  "id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "author": {
    "id": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "user_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "union_openid": "",
    "username": "",
    "bot": false
  },
  "content": "你好，今天有什么推荐的活动吗？",
  "message_type": 0,
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_xxxxxxxxxxxxxxx=="
    ]
  },
  "timestamp": "2026-07-21T10:00:00+08:00"
}
```

**示例2**

```text
{
  "id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
  "author": {
    "id": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "user_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "union_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "username": "",
    "bot": false
  },
  "content": "[卡片消息] 小程序\n摘要: [每日打卡]快来完成今日学习打卡",
  "message_type": 3,
  "ark_data": {
    "ark_type": "miniapp",
    "ark_name": "小程序",
    "prompt": "[每日打卡]快来完成今日学习打卡",
    "fields": {
      "title": "快来完成今日学习打卡",
      "source": "学习助手",
      "tag": "微信小程序",
      "preview": "https://pubminishare-30161.picsz.qpic.cn/preview_a1b2c3d4",
      "source_logo": "https://miniapp.gtimg.cn/generated-icon/app_a1b2c3d4.png",
      "tag_icon": "https://miniapp.gtimg.cn/public/miniwx.png"
    }
  },
  "message_scene": {
    "source": "default",
    "ext": [
      "msg_idx=REFIDX_yyyyyyyyyyyyyyy=="
    ]
  },
  "timestamp": "2026-07-21T10:01:00+08:00"
}
```

**示例3**

```text
{
  "id": "ROBOT1.0_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
  "author": {
    "id": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "user_openid": "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6",
    "union_openid": "",
    "username": "",
    "bot": false
  },
  "content": "这个建议很有帮助，谢谢你！",
  "message_type": 103,
  "msg_elements": [
    {
      "msg_idx": "REFIDX_aaaaaaaaaaaaaaa==",
      "message_type": 103,
      "content": "每天坚持阅读半小时，一个月后你会发现自己的变化"
    }
  ],
  "message_scene": {
    "source": "default",
    "ext": [
      "ref_msg_idx=REFIDX_aaaaaaaaaaaaaaa==",
      "msg_idx=REFIDX_zzzzzzzzzzzzzzz=="
    ]
  },
  "timestamp": "2026-07-21T10:02:00+08:00"
}
```
