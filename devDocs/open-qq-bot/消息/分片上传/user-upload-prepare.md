# 单聊富媒体预上传

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_prepare.post.html
> 抓取日期：2026-11-10

单聊大文件分片上传前的准备工作。返回 upload\_id、分片预签名 URL 和上传配置。
后续将文件按 block\_size 分片，逐片 PUT 到预签名 URL，每片完成后调用分片完成接口。

大文件分片上传第一步。传入文件大小、MD5/SHA1 校验值，服务端返回 upload\_id 和各分片预签名 URL。

## 请求

### 基础信息

| 字段 | 值 |
| --- | --- |
| HTTP URL | /v2/users/{user\_id}/upload\_prepare |
| HTTP Method | POST |
| 接口频率限制 | 10 QPS |

## 路径参数

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| user\_id | string | 是 | 用户 OpenID |

## 请求体

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| file\_type | integer | 是 | 业务类型。1=图片, 2=视频, 3=语音, 4=文件 |
| file\_size | string | 是 | 文件大小（字节） |
| file\_name | string | 是 | 文件名 |
| md5 | string | 是 | 整个文件的 MD5 |
| sha1 | string | 是 | 整个文件的 SHA1 |
| md5\_10m | string | 是 | 文件前 10002432 字节（约 10MB）的 MD5 校验值 |

### 请求示例

**预上传视频文件**

```text
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/upload_prepare
{
  "file_type": 2,
  "file_size": "31457280",
  "file_name": "demo.mp4",
  "md5": "d41d8cd98f00b204e9800998ecf8427e",
  "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
  "md5_10m": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## 响应

### 响应体

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| upload\_id | string | 上传任务 ID，后续分片上传和完成合并时需携带 |
| block\_size | string | 分块大小（字节），默认 5MB。客户端按此大小对文件分片 |
| parts | [][UploadPart](#schema-uploadpart) | 分片列表，每个分片包含一个预签名上传 URL |
| upload\_config | [UploadConfig](#schema-uploadconfig) | 上传配置，由后台下发控制客户端上传行为 |

**UploadPart**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| index | integer | 分片序号，从 0 开始 |
| presigned\_url | string | 预签名上传 URL，客户端通过 HTTP PUT 将分片数据上传到此 URL |
| block\_size | string | 该分块的大小（字节） |

**UploadConfig**

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| concurrency | integer | 上传并发数，默认 1 |
| retry\_timeout | integer | 重试超时时间（秒），默认 300（5分钟） |
| retry\_delay | integer | 重试延迟（秒），默认 1 |

## 响应示例

**预上传成功（3 个分片）**

```json
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "block_size": "10485760",
  "parts": [
    {
      "index": 0,
      "presigned_url": "https://cos.example.com/upload?partNumber=1&sign=aaa",
      "block_size": "10485760"
    },
    {
      "index": 1,
      "presigned_url": "https://cos.example.com/upload?partNumber=2&sign=bbb",
      "block_size": "10485760"
    },
    {
      "index": 2,
      "presigned_url": "https://cos.example.com/upload?partNumber=3&sign=ccc",
      "block_size": "10485760"
    }
  ],
  "upload_config": {
    "concurrency": 1,
    "retry_timeout": 300,
    "retry_delay": 1
  }
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
| 40093001 | 文件上传失败，请重试 | 申请上传失败，请重试 |
