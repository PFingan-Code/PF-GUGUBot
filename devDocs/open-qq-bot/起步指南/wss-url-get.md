# 获取通用 WSS 接入点

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/openapi/wss/url_get.html
> 抓取日期：2026-11-10

### 接口

```http
GET /gateway
```

### 功能描述

用于获取 WSS 接入地址，通过该地址可建立 `websocket` 长连接。

### Content-Type

```http
application/json
```

### 返回

返回一个用于连接 `websocket` 的地址。

### 错误码

详见[错误码](https://bot.q.qq.com/wiki/develop/api-v2/openapi/error/error.html)。

### 示例

响应数据包

```json
{
  "url": "wss://api.bot.qq.com/websocket/"
}
```
