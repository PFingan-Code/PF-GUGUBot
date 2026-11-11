# 单聊富媒体上传

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_files.post.html
> 抓取日期：2026-11-10

上传图片/视频/语音到单聊，返回 file\_info 用于发送消息接口的 media 字段。
用单聊接口上传的文件仅能发送到单聊。
文件类型与大小限制:

- 1=图片(png/jpg): 软限制 20MB, 硬限制 200MB
- 2=视频(mp4): 软限制 30MB, 硬限制 200MB
- 3=语音(silk): 软限制 20MB, 硬限制 200MB
- 4=文件: 软限制 200MB, 硬限制 200MB
  超过软限制会降级为文件类型上传，超过硬限制会报错。

支持三种上传方式，按实际文件大小和资源来源选择。

## 一、支持的上传方式

| 方式 | 说明 | 限制 / 注意 |
| --- | --- | --- |
| URL 上传 | 传入 `url`，由平台下载并转存 | 服务端下载资源可能因网络等原因失败 |
| 分片上传合并 | 先通过 `upload_prepare` + `upload_part_finish` 完成分片上传，再携带 `upload_id` 调用本接口完成合并 | **推荐使用** |
| 直接上传二进制数据 | 直接传文件二进制内容 | 数据大小不能超过 5M，超过建议使用分片上传 |

## 二、推荐流程：分片上传

1. 调用 `upload_prepare`，获取 `upload_id`、`block_size` 以及各分片的预签名 URL。
2. 按 `block_size` 将文件切分为多个分片，逐片通过 HTTP `PUT` 上传到对应的预签名 URL。
3. 每片 `PUT` 成功后，调用 `upload_part_finish` 通知服务端该分片上传完成。
4. 全部分片上传完成后，携带 `upload_id` 调用本接口完成合并，返回 `file_info`。

## 三、注意事项

- URL 上传存在服务端下载失败的可能，若遇到下载失败，可先将资源下载到本地，再通过**直接上传二进制数据**的方式上传。
- 二进制直传有 5M 大小上限，文件较大时请改用分片上传。

## 请求

### 基础信息

| 字段 | 值 |
| --- | --- |
| HTTP URL | /v2/users/{user\_openid}/files |
| HTTP Method | POST |
| 接口频率限制 | 50 QPS |

## 路径参数

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| user\_openid | string | 是 | 用户 OpenID |

## 请求体

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| file\_type | integer | 否 | 媒体类型。1=图片, 2=视频, 3=语音, 4=文件 图片支持 png/jpg，视频支持 mp4，语音支持 silk |
| url | string | 否 | 媒体资源的 URL，需以 http 开头，平台会下载并转存 分片上传合并时可为空 |
| srv\_send\_msg | boolean | 否 | true=直接发送消息并占用主动消息频次，返回中包含消息 ID false=仅返回 file\_info，用于后续发送消息接口的 media 字段 |
| upload\_id | string | 否 | 分片上传任务 ID。来自 UploadPrepare 响应的 upload\_id， 传入后走分片上传合并路径，url 可为空 |
| file\_name | string | 否 | 文件名 (分片上传或者二进制上传时必填） |
| file\_data | string | 否 | 直接上传二进制数据。 直接上传二进制有大小限制，需要在5M以内，如果超过则需要使用URL上传或者分片上传。 |

### 请求示例

**URL 上传图片**

```text
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files
{
  "file_type": 1,
  "url": "https://example.com/image.png",
  "srv_send_msg": false
}
```

**分片上传合并**

```text
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files
{
  "file_type": 2,
  "srv_send_msg": false,
  "file_name": "video.mp4",
  "upload_id": "upload_a1b2c3d4e5f6"
}
```

**二进制上传**

```text
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/files

{
  "file_type": 1,
  "file_name": "111.png",
  "file_data": "xxxx图片的二进制数据"
}
```

## 响应

### 响应体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| file\_uuid | string | 文件唯一 ID |
| file\_info | string | 文件信息，用于发送消息接口的 media.file\_info 字段。 内部为序列化的二进制数据，开发者无需解析，直接透传即可 |
| ttl | integer | file\_info 有效期（秒）。到期后需重新上传。 0 表示可长期使用 |
| id | string | 发送消息的唯一 ID。仅 srv\_send\_msg=true 时返回 |
| raw\_url | string | 文件下载链接（COS 预签名 GET URL），有效期与 ttl 一致 仅分片上传合并（upload\_id 路径）且 file\_type 为图片/视频/语音时返回； URL 直传和文件类型(file\_type=4)不返回此字段 |

## 响应示例

**上传成功**

```json
{
  "file_uuid": "uuid_a1b2c3d4e5f6",
  "file_info": "AE86C5D3F0E14B238C656C0F6DD1D0479C",
  "ttl": 300
}
```

### 错误码

| 错误码 | 描述 | 排查建议 |
| --- | --- | --- |
| 850018 | 群被禁言或者机器人被禁言 | 请检查机器人是否被禁言 |
| 850019 | 不支持的文件格式 | 请检查 file\_type 是否正确 |
| 850026 | 下载原始文件失败 | 请检查 URL 是否可访问或重试 |
| 850031 | 上传文件超过大小限制 | 请减小文件大小 |
| 850027 | 发送数据超时 | 请稍后重试 |
| 10000 | 不支持的操作 | 请检查请求参数 |
| 40093001 | 文件上传失败，请重试 | 大文件分片上传中 BDH 通道异常，请重试 |
| 40093002 | 超过今天发送文件容量上限 | 请明天再试或减少文件大小 |
