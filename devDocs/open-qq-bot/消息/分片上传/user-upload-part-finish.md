# 单聊分片上传完成

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_part_finish.post.html
> 抓取日期：2026-11-10

通知服务端某个分片已上传完成。全部分片完成后，用 upload\_id 作为 MediaUpload 的 upload\_id 字段调一次上传接口完成合并

分片上传第二步。每个分片 PUT 到预签名 URL 成功后调用，通知服务端该分片已上传完成。
全部分片完成后，携带 upload\_id 调用 /v2/users/{user\_openid}/files 完成合并。

## 请求

### 基础信息

| 字段 | 值 |
| --- | --- |
| HTTP URL | /v2/users/{user\_id}/upload\_part\_finish |
| HTTP Method | POST |
| 接口频率限制 | 10 QPS |

## 路径参数

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| user\_id | string | 是 | 用户 OpenID |

## 请求体

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| upload\_id | string | 否 | 上传任务 ID |
| part\_index | integer | 否 | 分片序号 |
| block\_size | string | 否 | 分块大小（字节） |
| md5 | string | 否 | 分片 MD5 |

### 请求示例

**通知分片 0 上传完成**

```text
POST /v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/upload_part_finish
{
  "upload_id": "upload_a1b2c3d4e5f6",
  "part_index": 0,
  "block_size": "10485760",
  "md5": "c4d8c5f3a2b1e0f9a8b7c6d5e4f3a2b1"
}
```

## 响应

无

## 响应示例

**分片完成确认**

```json
{}
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
| 40093001 | 文件上传失败，请重试 | 分片转存 BDH 通道异常，请重试 |
| 40093002 | 超过今天发送文件容量上限 | 请明天再试或减少文件大小 |
