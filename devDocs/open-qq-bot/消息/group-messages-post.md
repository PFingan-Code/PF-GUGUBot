# 发送群聊消息

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html
> 抓取日期：2026-11-10

向指定群发送消息。支持文本/Markdown/富媒体等类型，可附带内嵌键盘。
注意: 群消息不支持流式参数

- 被动消息有效时间 **5 分钟**，每个消息最多回复 **5 次**
- 主动消息频控规则
  - Bot 维度（发送方）：企业认证/个人身份证认证 **60/qpm**；未认证 **30/qpm**
  - 单关系维度（接收方）：**20/qpm**，每个群 1 天最多接收 **1000** 条

## 请求

### 基础信息

| 字段 | 值 |
| --- | --- |
| HTTP URL | /v2/groups/{group\_openid}/messages |
| HTTP Method | POST |
| 接口频率限制 | 100 QPS |

## 路径参数

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| group\_openid | string | 是 | 群 OpenID |

## 请求体

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| msg\_type | integer | 否 | 消息类型。决定哪个内容字段生效: 0=纯文本(content) 2=Markdown(markdown) 7=富媒体(media) 8=图文卡片(card) |
| content | string | 否 | 文本内容。msg\_type=0 时为全文 注意: 传了 markdown 后此字段必须为空 |
| markdown | [MessageMarkdown](#schema-messagemarkdown) | 否 | Markdown 消息。msg\_type=2 时必填 注意: 填写此字段后 content/ark 必须全为空 |
| keyboard | [Keyboard](#schema-keyboard) | 否 | 内嵌键盘。短形式只传 id，长形式传 content.rows |
| msg\_id | string | 否 | 被动回复的消息 ID。从 GROUP\_AT\_MESSAGE\_CREATE 等事件的 d.id 获取，5 分钟内有效 |
| event\_id | string | 否 | 被动回复的事件 ID。从事件最外层的id获取。与 msg\_id 二选一，支持事件："INTERACTION\_CREATE"、"GROUP\_ADD\_ROBOT"、"GROUP\_MSG\_RECEIVE" |
| msg\_seq | integer | 否 | 回复消息的序号，与 msg\_id 联合使用，避免相同消息 id 回复重复发送，不填默认是 1。相同的 msg\_id + msg\_seq 重复发送会失败。 |
| media | [MediaInfo](#schema-mediainfo) | 否 | 富媒体消息。msg\_type=7 时填写，file\_info 来自 /v2/groups/{group\_openid}/files |
| message\_reference | [MessageReference](#schema-messagereference) | 否 | 引用回复。填写后以引用形式展示，关联上下文 |
| card | [MessageCard](#schema-messagecard) | 否 | msg\_type=8时必须填写 |

**MessageMarkdown**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| template\_id | integer | 否 | 【已废弃】平台 Markdown 模板 ID。使用模板时填写，非模板不传 |
| content | string | 否 | Markdown 内容。支持的格式参考文档：[Markdown](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html) |
| custom\_template\_id | string | 否 | 【已废弃】自定义模板 ID，与 template\_id 二选一 |
| force\_verify\_image\_resource | boolean | 否 | 是否校验图片转存结果，当为true时，如果出现图片转存失败，则会返回错误，消息不会发送。 默认为false |

**Keyboard**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| id | string | 否 | 内嵌键盘模板 ID。使用平台预设模板时填写此字段 |
| content | [KeyboardContent](#schema-keyboardcontent) | 否 | 自定义键盘布局。与 id 互斥，用于自定义按钮 |

**KeyboardContent**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| rows | [][Row](#schema-row) | 否 | 按钮行列表 |

**Row**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| buttons | [][Button](#schema-button) | 否 | 行内按钮，从左到右排列 |

**Button**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| id | string | 否 | 按钮 ID。同一键盘内唯一 |
| render\_data | [RenderData](#schema-renderdata) | 否 | 按钮渲染 |
| action | [Action](#schema-action) | 否 | 按钮点击行为 |
| group\_id | string | 否 | 分组ID, 同一分组内有一个按钮操作后, 其它按钮则变灰不可点击 注意:只有当action.type = 1 时才有效 |

**RenderData**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| label | string | 否 | 按钮文字，最多 10 字符 |
| visited\_label | string | 否 | 点击后文字，不传则保持不变 |
| style | integer | 否 | 0：灰色线框，1：蓝色线框 3: 白色背景+红色字体, 4:蓝色背景+白色字体 |

**Action**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| type | integer | 否 | 0：跳转按钮：http 或 小程序 1：回调按钮：回调后台接口, data 传给后台， 2：指令按钮：自动在输入框插入 @bot data |
| permission | [Permission](#schema-permission) | 否 | 操作权限 |
| data | string | 否 | 回调数据。type=1/2 时必填 |
| click\_limit | integer | 否 | 【已废弃】可点击次数限制。0=无限 |
| unsupport\_tips | string | 否 | 版本过低时提示文案 |
| enter | boolean | 否 | 指令按钮可用，点击按钮后直接自动发送 data，仅单聊可用，默认 false。支持版本 8983 |
| reply | boolean | 否 | 指令按钮可用，指令是否带引用回复本消息，默认 false。支持版本 8983 |
| anchor | integer | 否 | 本字段仅在指令按钮下有效，设置后后会忽略 action.enter 配置。 设置为 1 时 ，点击按钮自动唤起启手Q选图器，其他值暂无效果。 （仅支持手机端版本 8983+ 的单聊场景，桌面端不支持） |
| modal | [Modal](#schema-modal) | 否 | 用户点击二次确认操作 |

**Permission**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| type | integer | 否 | 0=指定用户, 1=管理员, 2=所有人 |
| specify\_user\_ids | []string | 否 | 有权限的用户 id 的列表 |
| specify\_role\_ids | []string | 否 | 有权限的身份组 id 的列表（仅频道可用） |

**Modal**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| content | string | 否 | 二次确认的提示文本,如果不为空则会进行二次确认. 注意:最多40个字符, 不能有URL |
| confirm\_text | string | 否 | 二次确认提示确认按钮中展示的文字,可以为空, 默认为"确认" 注意:最多4个字符 |
| cancel\_text | string | 否 | 二次确认提示取消按钮中的文字,可以为空,默认为"取消" 注意:最多4个字符 |

**MediaInfo**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| file\_info | string | 否 | 文件数据。来自文件上传接口返回值 |

**MessageReference**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| message\_id | string | 否 | 被引用消息 ID，例如REFIDX\_xxxxxx   - 非机器人发的消息，从消息事件的`MessageScene`的`ext`数组，`msg_idx`字段中获取   - 机器人自己发的消息，从发消息请求响应`ext_info.ref_idx`获取 |

**MessageCard**

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| type | string | 否 | 卡片类型：tuwen： 图文卡片 |
| content | object | 否 | 卡片消息中上传的元素 当type=tuwen, 时必须包括: title(1-50 字符), description(1-200 字符), url(必须为https,链接长度≤ 1024 字符), pic\_url(必须为https,链接长度≤ 1024 字符) |

### 请求示例

**文本消息 (msg\_type=0)**

```text
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 0,
  "content": "欢迎使用本群助手，有什么可以帮你的吗？",
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**Markdown + 键盘消息 (msg\_type=2)**

```text
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 2,
  "markdown": {
    "content": "## 每日签到\n\n今日签到成功！获得 **50** 积分\n连续签到 **7** 天"
  },
  "keyboard": {
    "content": {
      "rows": [
        {
          "buttons": [
            {
              "id": "btn_signin",
              "render_data": {
                "label": "签到",
                "style": 1
              },
              "action": {
                "type": 2,
                "permission": {
                  "type": 2
                },
                "data": "/签到",
                "enter": true
              }
            }
          ]
        }
      ]
    }
  },
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 1
}
```

**富媒体消息 (msg\_type=7)**

```text
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 7,
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 2,
  "media": {
    "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C"
  },
  "message_reference": {
    "message_id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
  }
}
```

**图文卡片消息 (msg\_type=8)**

```text
POST /v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages
{
  "msg_type": 8,
  "msg_id": "ROBOT1.0_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "msg_seq": 2,
  "card": {
    "type": "tuwen",
    "content": {
      "title":       "iPhone 17 Pro 正式发布",
      "description": "全新 A20 芯片 / 钛金属机身 / 支持卫星通信",
      "url":         "https://news.qq.com/rain/a/20261014A05XYZ00",
      "pic_url":     "https://inews.gtimg.com/newsapp_bt/0/xxx/1000.jpg"
    }
  },
  "message_reference": {
    "message_id": "ROBOT1.0_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
  }
}
```

## 响应

### 响应体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| id | string | 消息 ID，可用于后续撤回 |
| timestamp | string | 发送时间，RFC3339 东八区 |
| ext\_info | [MessageExtInfo](#schema-messageextinfo) | 扩展信息 |

**MessageExtInfo**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| ref\_idx | string | 引用消息索引。对应消息时间ext里的msg\_idx与ref\_msg\_idx |

## 响应示例

**发送成功**

```json
{
  "id": "ROBOT1.0_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
  "timestamp": "2026-07-21T10:00:00+08:00",
  "ext_info": {
    "ref_idx": "REFIDX_xxxxxxxxxxxxxxx=="
  }
}
```

### 错误码

| 错误码 | 描述 | 排查建议 |
| --- | --- | --- |
| 22006 | 消息类型与内容不匹配 | 请检查msg\_type与content是否对应 |
| 304004 | 无权限使用该ARK模板 | 请先申请ARK模板权限 |
| 304036 | 无Markdown模板权限 | 请先申请Markdown模板权限 |
| 304061 | 消息内容无效 | 请检查消息格式是否符合要求 |
| 304064 | 订阅消息未授权 | 请先引导用户授权订阅消息 |
| 304080 | 文件信息无效 | 请检查文件信息格式是否正确 |
| 304103 | 消息ID已过期，不能回复 | 请在收到消息后尽快回复 |
| 305007 | 键盘样式参数错误 | 请检查keyboard参数 |
| 340069 | 消息类型无效 | 请检查msg\_type取值 |
| 40034004 | 富媒体信息转存失败 | 请重试 |
| 40034005 | 回复消息msg\_id已过期 | 请在收到消息后尽快回复 |
| 40034006 | 消息内容违规 | 请修改消息内容后重试 |
| 40034008 | markdown参数有空值 | 请确保所有Markdown参数都有值 |
| 40034009 | markdown参数有换行符 | 请移除Markdown参数中的换行符 |
| 40034010 | 模版参数中不能含有markdown语法 | 请使用纯文本参数，不要包含Markdown语法 |
| 40034011 | 无效的markdown内容 | 请检查Markdown语法是否正确 |
| 40034024 | 请求参数msg\_id无效或越权 | 请检查msg\_id是否正确 |
| 40034025 | 请求参数event\_id无效 | 请检查event\_id是否正确 |
| 40034026 | 请求参数event\_id已过期 | 请在收到事件后尽快回复 |
| 40034027 | 该事件不支持回复消息 | 请确认事件类型是否支持回复 |
| 40034029 | 内联键盘行/列超限 | 请减少键盘按钮数量 |
| 40034100 | 主动消息发送超过频控限制 | 请降低发送频率或等待配额恢复 |
| 40034101 | 机器人非群成员 | 请先将机器人加入群聊 |
| 40034105 | 主动消息发送失败，无权限 | 请检查机器人权限设置 |
| 40034106 | 消息不支持该指令类型 | 请检查消息指令类型 |
| 40034108 | 指令参数长度超限 | 请缩短指令参数 |
| 40034109 | 指令参数解析失败 | 请检查指令参数格式 |
| 40034124 | markdown消息参数错误 | 请检查Markdown参数格式 |
| 40034127 | 无markdown模板权限 | 请先申请Markdown模板权限 |
| 40034128 | 被动回复时间或次数超限 | 请在收到事件后尽快回复 |
| 40054002 | 机器人被禁言 | 请等待解禁后再发送 |
| 40054003 | 机器人不是群成员 | 请先将机器人加入群聊 |
| 40054005 | 消息被去重 | 请确保每次请求使用不同的msgseq值 |
| 40054007 | 消息长度超限 | 请缩短消息内容 |
| 40054010 | 不允许发送URL | 请移除消息中的URL |
| 40054016 | 机器人已下线 | 请检查机器人状态 |
| 50055001 | 消息发送异常，请稍后重试 | 请稍后重试 |
| 50055006 | ARK消息发送异常，请稍后重试 | 请稍后重试 |
