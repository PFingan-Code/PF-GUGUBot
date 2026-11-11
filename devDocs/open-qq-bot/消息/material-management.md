# 素材管理（Markdown 图片素材）

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/material-management.html
> 抓取日期：2026-11-11（webfetch）

开发者可将 Markdown 消息所需的图片预先上传到平台，获得 `qqbot-media://` 引用后写入 Markdown 消息，无需依赖网络资源。图片在有效期内可反复引用，发送时由平台自动转存。**与公网图片 URL 可在同一 Markdown 中混用**——图片本身有公网 URL 时无需走素材上传。

## 使用流程

1. `POST /v2/media-images/prepare` 申请上传：body 含 `file_name`（含扩展名）、`file_size`、`content_type`（image/png|jpeg|gif|webp）、`md5`（32 位）、`sha1`（40 位）→ 返回 `upload_id`（4 小时有效）、`presigned_url`、`expires_in`
2. `PUT <presigned_url>` 直传图片二进制：Content-Type 必须与声明一致（否则 COS 403）；响应头 ETag 即文件 MD5（去引号）
3. `POST /v2/media-images/complete`：body 含 `upload_id`、`md5`（ETag；不一致报 40035003）→ 返回 `image_id`、`url`（`qqbot-media://image/v1/<token>`）、`ttl`（7776000s）、`preview_url`（短时效，勿持久化）
4. Markdown 引用：`![说明 #800px #400px](qqbot-media://image/v1/<token>)`，宽高可选，语法与公网图片一致

## 限制

| 项目 | 限制 |
|---|---|
| 单张图片 | ≤ 10MB；png/jpeg/gif/webp；扩展名与 Content-Type 一致 |
| 数量上限 | 100 张/机器人（删除可释放，超限报 40035007） |
| 图片有效期 | 滑动过期：最后一次被消息引用起 90 天，未被引用则失效（40035009） |
| 上传任务 | prepare 的 upload_id 4 小时失效 |

## 查询 / 删除

- `GET /v2/media-images?cursor={next_cursor}`：分页查询有效图片（含 image_id、url、file_name、preview_url、created_at、expires_at），next_cursor 为空即末页
- `DELETE /v2/media-images/{image_id}/delete`：释放配额；图片不存在报 40035008；已发送消息不受影响（发送时平台已转存副本）

## 错误码

| 码 | 说明 |
|---|---|
| 40035001 | 图片格式不支持（扩展名与 Content-Type 需为 png/jpeg/gif/webp 且一致） |
| 40035002 | 超过大小上限（10MB） |
| 40035003 | 任务不存在/已过期/不属于当前机器人，或 MD5 与 COS ETag 不符 |
| 40035006 | 服务端内部错误，可稍后重试 |
| 40035007 | 数量超上限（100 张） |
| 40035008 | 图片不存在或已删除 |
| 40035009 | 图片已过期，引用链接不可用 |
| 40035010 | 引用链接无效或不属于当前机器人 |

## 注意

- `qqbot-media://` 链接与机器人绑定，其他机器人引用报 40035010
- 服务端只校验扩展名与 Content-Type 匹配，不校验实际内容；内容非法会在发消息时因格式检查失败
- sha1 仅用于上传任务登记与幂等识别，complete 校验以 md5 为准
