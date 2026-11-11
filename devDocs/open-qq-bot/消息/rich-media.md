# 富媒体消息概述

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html
> 抓取日期：2026-11-10

富媒体消息支持发送图片、视频、语音、文件等类型，需先将文件上传获取 `file_info`，再通过发消息接口（`msg_type=7`）携带 `media.file_info` 发送。

## 支持的消息类型

| 图片 | 语音 | 视频 | 文件 |
| --- | --- | --- | --- |
| 图片消息 | 语音消息 | 视频消息 | 文件消息 |
| 支持 jpg/png/gif/webp/bmp 格式，发送后直接展示图片 | 支持 silk/mp3/wav/ogg 格式，发送后展示语音条 | 支持 mp4 格式，发送后展示视频封面可播放 | 支持任意格式，发送后展示文件卡片可下载 |

## 文件类型与限制

| file\_type | 类型 | 格式 | 软限制 | 硬限制 |
| --- | --- | --- | --- | --- |
| 1 | 图片 | png / jpg | 20 MB | 200 MB |
| 2 | 视频 | mp4 | 30 MB | 200 MB |
| 3 | 语音 | silk | 20 MB | 200 MB |
| 4 | 文件 | - | 200 MB | 200 MB |

超过软限制会降级为文件类型上传，超过硬限制会报错。

## 上传方式

整文件上传使用 [单聊上传](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_files.post.html) / [群聊上传](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html) 接口，直接传入文件 URL；文件较大时使用分片上传，参考 [单聊预上传](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_prepare.post.html) 开始分片流程。

### 分片上传（推荐）

适用于大文件或本地文件。分四步完成：

```text
1. 预上传
   调用 upload_prepare，传入文件信息和校验值
   → 获取 upload_id + block_size + 各分片预签名 URL

2. 分片 PUT
   按 block_size 将文件分片，逐片 HTTP PUT 到对应的预签名 URL

3. 确认分片
   每片 PUT 成功后调用 upload_part_finish，通知服务端该分片完成

4. 完成合并
   全部分片完成后，携带 upload_id 调用上传接口
   → 返回 file_info
```

流程图：

```text
 upload_prepare         分片 PUT + part_finish        上传接口（合并）
┌──────────────┐    ┌─────────────────────────┐    ┌──────────────────┐
│ 获取        │    │  for each chunk:        │    │ POST .../files   │
│ upload_id   │───▶│  PUT → presigned_url    │───▶│ { upload_id }   │
│ block_size  │    │  POST → part_finish     │    │ → file_info      │
│ presigned   │    └─────────────────────────┘    └──────────────────┘
│ URLs        │
└──────────────┘
```

### URL 上传

适用于文件已在公网可访问的场景，直接传入文件 URL，平台自动下载转存。

```text
POST /v2/users/{user_openid}/files
{
  "file_type": 1,
  "url": "https://example.com/image.png"
}
```

返回 `file_info`，即可用于发消息。

## 使用 file\_info 发送

获取 `file_info` 后，在发消息接口中设置 `msg_type=7`，将 `file_info` 填入 `media` 字段：

```json
POST /v2/users/{user_openid}/messages
{
  "msg_type": 7,
  "media": {
    "file_info": "{上一步返回的 file_info}"
  }
}
```

> `srv_send_msg=true` 可在上传的同时直接发送，跳过单独调用发消息接口这一步，但会占用主动消息频次。

## 单聊与群聊隔离

单聊和群聊的文件上传接口相互独立，上传的文件不能跨场景使用：

| 场景 | 上传接口 |
| --- | --- |
| 单聊 | `/v2/users/{user_openid}/files` |
| 群聊 | `/v2/groups/{group_openid}/files` |

对应的预上传和分片接口也需使用同场景的端点。

## 注意事项

- `file_info` 有有效期（`ttl`），过期后需重新上传。
- `md5_10m`（文件前 10002432 字节，约 9.54 MB 的 MD5）可用于秒传判断，避免重复上传。
- 分片大小默认 5MB，并发数、重试策略由服务端在 `upload_config` 中下发。
- 上传接口超时建议设为 ≥ 5 秒。
