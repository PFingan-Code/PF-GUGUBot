# 获取访问凭证

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html
> 抓取日期：2026-11-10

QQ 机器人开放平台提供以下类型的访问凭证：

| 凭证类型 | 是否需要用户授权 | 说明 |
| --- | --- | --- |
| access\_token | 否 | 机器人身份调用 API 时使用的凭证，可读写的数据范围由机器人的权限范围决定。适用于机器人主动发消息、管理群聊等场景。 |

## 获取 access\_token

### 请求

| 基本 | |
| --- | --- |
| HTTP URL | https://api.bot.qq.com/app/getAppAccessToken |
| HTTP Method | POST |

### 请求参数

| **属性** | **类型** | **必填** | **说明** |
| --- | --- | --- | --- |
| appId | string | 是 | 在开放平台管理端上获得。 |
| clientSecret | string | 是 | 在开放平台管理端上获得。 |

### 返回参数

**成功响应**

| **属性** | **类型** | **说明** |
| --- | --- | --- |
| access\_token | string | 获取到的凭证。 |
| expires\_in | number | 凭证有效时间，单位：秒。目前是 7200 秒之内的值。 |

**失败响应**

| **属性** | **类型** | **说明** |
| --- | --- | --- |
| code | number | 错误码，取值见下方「业务错误码」。 |
| message | string | 错误信息，仅用于人工排查，内容可能随时调整。 |

注意

该接口的业务错误通过响应体的 `code` 返回，即使调用失败，HTTP 返回码仍为 `200`。请优先依据 `code` 判断请求是否成功，不要只依赖 HTTP 返回码；也不要依据 `message` 判定错误类型。详见下方「错误返回码」。

### 错误码

#### 业务错误码

| **错误码** | **错误信息** | **排查指南** |
| --- | --- | --- |
| 100001 | Too many requests | 请求过于频繁，请降低调用频率后重试 |
| 100007 | appid invalid | AppID 无效，或机器人状态不正常（被封禁或已删除），请检查 AppID 是否正确以及机器人状态 |
| 100016 | invalid appid or secret | AppID 或 ClientSecret 不正确，请检查传入的 appId 和 clientSecret 是否与开放平台管理端一致 |
| 10004 | 机器人不存在 | AppID 对应的机器人不存在，请确认 AppID 是否正确 |

### 调用示例

```shell
curl --location 'https://api.bot.qq.com/app/getAppAccessToken' \
--header 'Content-Type: application/json' \
--data '{
  "appId": "APPID",
  "clientSecret": "CLIENTSECRET"
}'
```

### 返回示例

**成功**

```json
{
  "access_token": "ACCESS_TOKEN",
  "expires_in": "7200"
}
```

**失败**

```json
{
  "code": 100007,
  "message": "appid invalid"
}
```

## 凭证有效期与刷新

目前 `access_token` 生命周期默认 `7200` 秒（2 小时），开发者需要在过期后自行刷新 `access_token`，保证调用链路权限正常。

- 每次请求不会刷新新的 `access_token`，在有效期内重复获取会返回相同的值
- 在上一个 `access_token` 接近过期时间 `60` 秒内，获取 `access_token` 时，会获得一个新的 `access_token`，老的 `access_token` 在这个 `60` 秒内仍然有效
- 建议开发者在服务端设置定时刷新凭证的业务逻辑，以防止过期

## 使用访问凭证

在每次调用 OpenAPI 开放接口时，需要在 HTTP 请求头中引入 `access_token` 进行调用权限验证。

**请求头**：

| 名称 | 类型 | 必填 | 描述 |
| --- | --- | --- | --- |
| Authorization | string | 是 | 格式值：`QQBot ACCESS_TOKEN` |

**示例**：

```shell
curl --location 'https://api.bot.qq.com/users/@me' \
--header 'Authorization: QQBot ACCESS_TOKEN'
```

注意

为了安全考虑，请勿在应用前端使用访问凭证。请在应用服务端发起 API 访问请求。
