# Markdown 消息

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html
> 抓取日期：2026-11-10

2026/04/23 能力更新说明

单聊场景、群聊场景自定义 Markdown 消息能力已开放到所有机器人均可使用，无需单独申请 Markdown 模版，频道场景目前需要内邀开通。

## 支持格式

### 标题

```text
# 一号标题
## 二号标题
正文
```

### 文字样式

```text
**加粗**
__下划线加粗__
_斜体_
*星号斜体*
***加粗斜体***
~~删除线~~
```

### 链接

```text
欢迎来到：[🔗腾讯网](https://www.qq.com)
文档可以访问<https://doc.qq.com>
```

### 图片

对于 markdown 消息内的图片资源，请使用可在公网访问的资源 url，开放平台会下载转存该资源。

```text
![text #208px #320px](https://resource5-1255303497.cos.ap-guangzhou.myqcloud.com/abcmouse_word_watch/markdown/building.png)
```

图片上传

若图片没有可公网访问的 URL，可以先将图片上传到平台，获取 `qqbot-media://` 引用后在 Markdown 中直接引用，无需依赖网络资源，详见 [素材管理](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/material-management.html)（消息类型 > 素材管理）。

### 有序列表

```text
# 有序列表
1. 新人降落桃源岛的欢迎仪式
2. 阳光准则助力建设有温度的频道
3. 岛民分享吹水纳凉
```

### 无序列表

```text
# 无序列表
- 新人降落桃源岛的欢迎仪式
- 阳光准则助力建设有温度的频道
- 岛民分享吹水纳凉
```

### 列表嵌套

```text
# 有序列表标题
1. 嵌套一层
    - 列表前是普通文本，则需要在列表前用空行隔开，否则无法识别
    - 如果是段落标签比如标题，则无需用空行隔开
2. 嵌套二层
    1. 我是有序列表，二级列表前面需要空4个空格
    2. 无序列表和有序列表可以相互嵌套，但是不建议无限制嵌套。
```

### 块引用

```text
> 青青子衿，悠悠我心，但为君故，沉吟至今
> 四月维夏，六月徂暑。先祖匪人，胡宁忍予
> 秋日凄凄，百卉具腓。乱离瘼矣，爰其适归？
诗经《小雅》
```

### 水平分割线

```text
这是段落1
***
这是段落2
```

### 换多行

```text
第一行

第二行

\u200B
\u200B
第三行
```

## 发送方式

自定义 markdown 消息使用示例：

```json
{
  "markdown": {
    "content": "# 标题 \n## 简介很开心 \n内容[🔗腾讯](https://www.qq.com)"
  }
}
```

markdown 模版消息的使用示例：

```text
// 模版例子

#{{.title}}

![img#618px #249px]({{.image}})

*{{.para1}}
*{{.para2}}

## {{.desc}}

{{.content}}[{{.link_introduction}}]({{.link}})

// 发送case
{
	"markdown": {
		"custom_template_id": "101993071_1658748972",
		"params": [{
				"key": "title",
				"values": ["标题"]
			},
			{
				"key": "image",
				"values": [
					"https://resource5-1255303497.cos.ap-guangzhou.myqcloud.com/abcmouse_word_watch/other/mkd_img.png"
				]
			},
			{
				"key": "para1",
				"values": ["段落1"]
			},
			{
				"key": "para2",
				"values": ["段落2"]
			},
			{
				"key": "desc",
				"values": ["简介"]
			},
			{
				"key": "content",
				"values": ["在这个子频道非常开心"]
			},
			{
				"key": "link_introduction",
				"values": ["链接介绍"]
			},
			{
				"key": "link",
				"values": ["https://www.qq.com"]
			}
		]
	}
}
```

## 数据结构与协议

消息发送 markdown 字段值是一个 json object，具体字段如下：

| **属性** | **类型** | **必填** | **说明** |
| --- | --- | --- | --- |
| content | string | 否 | 自定义 markdown 文本内容 |
| custom\_template\_id | string | 否 | markdown 模版id，申请模版后获得 |
| params | Array | 否 | {key: xxx, values: xxx}，模版内变量与填充值的kv映射 |
