# Webhook 方式

> 来源：https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html
> 抓取日期：2026-11-10

QQ 机器人开放平台支持通过使用 HTTP 接口接收事件。开发者可通过[管理端](https://q.qq.com/qqbot/#/developer/webhook-setting)设定回调地址，监听事件等。

目前回调地址允许配置的端口号为：80、443、8080、8443。

## 签名校验

机器人服务端需要对回调请求进行签名验证以保证数据没有被篡改过。[签名算法](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html)

## 回调地址及事件监听配置

开发者需要提供一个 HTTPS 回调地址。并选定监听的事件类型。开放平台会将事件通过回调的方式推送给机器人。

![event_subscription](https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.47.0/assets/img/webhook_new.b24ed4d6.png)

配置回调地址后，开放平台会对回调地址进行验证：

- 请求结构(Payload.d)

| **字段** | **描述** |
| --- | --- |
| plain\_token | 需要计算签名的字符串 |
| event\_ts | 计算签名使用时间戳 |

- 返回结果

| **字段** | **描述** |
| --- | --- |
| plain\_token | 需要计算签名的字符串 |
| signature | 签名 |

计算过程如下(golang)：

```go
func handleValidation(rw http.ResponseWriter, r *http.Request, botSecret string) {
	httpBody, err := io.ReadAll(r.Body)
	if err != nil {
		log.Println("read http body err", err)
		return
	}
	payload := &Payload{}
	if err = json.Unmarshal(httpBody, payload); err != nil {
		log.Println("parse http payload err", err)
		return
	}
	validationPayload := &ValidationRequest{}
	if 	err = json.Unmarshal(payload.Data, validationPayload);err != nil {
		log.Println("parse http payload failed:", err)
		return
	}
	seed := botSecret
	for len(seed) < ed25519.SeedSize {
		seed = strings.Repeat(seed, 2)
	}
	seed = seed[:ed25519.SeedSize]
	reader := strings.NewReader(seed)
	// GenerateKey 方法会返回公钥、私钥，这里只需要私钥进行签名生成不需要返回公钥
	_, privateKey, err := ed25519.GenerateKey(reader)
	if err != nil {
		log.Println("ed25519 generate key failed:", err)
		return
	}
	var msg bytes.Buffer
	msg.WriteString(validationPayload.EventTs)
	msg.WriteString(validationPayload.PlainToken)
	signature := hex.EncodeToString(ed25519.Sign(privateKey, msg.Bytes()))
	if err != nil {
		log.Println("generate signature failed:", err)
		return
	}
	rspBytes, err := json.Marshal(
		&ValidationResponse{
			PlainToken: validationPayload.PlainToken,
			Signature:  signature,
		})
	if err != nil {
		log.Println("handle validation failed:", err)
		return
	}
	rw.Write(rspBytes)
}
```

例如机器人账号

```text
appid: 11111111
secret: DG5g3B4j9X2KOErG
```

回调验证请求：

```text
headers: User-Agent:[QQBot-Callback] X-Bot-Appid:[11111111]
body: {"d":{"plain_token":"Arq0D5A61EgUu4OxUvOp","event_ts":"1725442341"},"op":13},
```

机器人应返回：

```text
body: {"plain_token": "Arq0D5A61EgUu4OxUvOp","signature": "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"}
```
