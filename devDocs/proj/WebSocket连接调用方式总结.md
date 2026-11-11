# GUGUBot：WebSocket 连接机器人的所有调用方式

> 基于源码分析（`GUGUbot/` 目录），不依赖 README 描述。
> 生成日期：2026-11-10

一句话概括：所有 WebSocket 调用都收敛到 `WebSocketFactory` → `WebSocketClient` / `WebSocketServer` 两个封装类，上层只有两个消费方 — QQ 走「客户端连 OneBot 正向 WS + `Bot` 动态 API 回显」，桥接走「主服开 WS 服务端 / 子服做客户端」的对等双模式。

## 一、底层封装层 `GUGUbot/gugubot/ws/`

### 1. `WebSocketClient`（`ws/websocket_client.py`，基于 `websocket-client` 库的 `WebSocketApp`）

- 构造：`WebSocketClient(url, headers, on_message, on_open, on_error, on_close, logger)`
- `connect(reconnect=5, ping_interval=20, ping_timeout=10, use_ssl, verify, ca_certs, extra_sslopt, thread_name, suppress_origin=True)`
  - daemon 线程跑 `run_forever`；
  - `reconnect > 0` 时启用库的自动重连参数；
  - `use_ssl` 时构建 sslopt（`verify=False` 则 `CERT_NONE`，否则 `CERT_REQUIRED` + 可选 `ca_certs`）；
  - 默认抑制 Origin 头。
- `send(message) -> bool`：dict / list 自动 `json.dumps`；未连接返回 False。
- `disconnect(timeout=5)`：`ws.close()` + join 线程。
- `is_connected()`：检查 `ws.sock.connected`。

### 2. `WebSocketServer`（`ws/websocket_server.py`，基于 `websocket-server` 库，缺库时构造抛 ImportError）

- 回调签名：`on_message(client, server, message)`、`on_client_connect(client, server)`、`on_client_disconnect(client, server)`，回调异常均被捕获仅记日志。
- `start(daemon=True)` / `stop(timeout=5)`：stop 前先向所有客户端广播 `{"type": "server_shutdown"}`，再逐一断开（优先 `disconnect_client`，降级直接关 handler），最后 `shutdown_gracefully` / `shutdown_abruptly`。
- `send_message(client, msg) -> bool`、`broadcast(msg) -> int`、`get_clients()`、`get_client_count()`、`is_running()`。

### 3. `WebSocketFactory`（`ws/websocket_factory.py`）— 统一创建入口

| 方法 | 说明 |
|---|---|
| `create_client(url, token, 四个回调, logger)` | token → `Authorization: Bearer <token>` header |
| `create_server(host, port, 三回调, logger)` | 直连参数版（默认 0.0.0.0:8787） |
| `create_bridge_server(config, ...)` | 读 `connector.minecraft_bridge.connection.{host, port}`（默认 0.0.0.0:8787） |
| `create_bridge_client(config, ...)` | 读同节点的 host / port / use_ssl / token，拼 `ws(s)://host:port` |

## 二、QQ 机器人连接（`QQWebSocketConnector`，`connector/qq_connector.py`）

### 1. 装配与生命周期

- `gugubot/__init__.py:109`：on_load 时若 QQ 系统开关开启则 `connectors.append(QQWebSocketConnector(server, gugubot_config))`。
- `ConnectorManager.register` → `await connector.connect()`；`unregister` → `await connector.disconnect()`（`connector/connector_manager.py:102,131`）。
- `webui_register.py:76` 也有 connectors 装配点。

### 2. 连接方式

```python
self.ws_client = WebSocketFactory.create_client(url, token,
    on_message=self._on_ws_message, on_open=self._on_open,
    on_error=self._on_error, on_close=self._on_close, logger=self.logger)
self.ws_client.connect(reconnect=配置, ping_interval=0, ping_timeout=0,  # OneBot 不需要 ping/pong
    use_ssl=..., verify=..., ca_certs=..., extra_sslopt=..., thread_name="[GUGUBot]QQ_Connector")
```

- URL：`ws(s)://{host}:{port}/{post_path}`。
- 配置键：`connector.QQ.connection.{host, port, post_path, use_ssl, token, reconnect(默认5), ping_interval, ping_timeout, verify, ca_certs, sslopt, max_wait_time(默认5, 上限9)}`。

### 3. 收消息 `_on_ws_message`（`:456`）

- JSON 解析 → 带 `echo` 的为 API 响应，写入 `bot.function_return[echo]` 唤醒等待协程；
- 其余事件 → `server.schedule_task(self.parser.process_message(raw))` 投到 MCDR 事件循环；
- `on_message(raw)`（`:448`）也直接委托给它（供注入 / 测试用）。

### 4. 发消息（路径）

1. **事件下发** `send_message(ProcessedInfo)`（`:335`）→ 构造 OneBot 段消息（剥 Minecraft 色码、非 QQ 来源加前缀模板 `chat_templates` 加权随机、按 `max_message_length` 默认 2000 分片、多片随机 0.5–1.5s 限速）→ 按目标类型调 `bot.send_group_msg / send_private_msg / send_temp_msg`（`:417-424`）。
2. **`Bot` OneBot API 客户端**（`:36`）：`__getattr__` 动态派发 —
   - `get_*` / `can_*` / `_get` 开头的方法自动附加 uuid echo、轮询 `function_return`（0.2s 间隔，超时 `max_wait_time`，过期请求自动清理）等待响应；
   - 其余 action 发完即忘（fire-and-forget）。
3. **系统层直接调用** `qq_connector.bot.send_group_msg(...)`：
   - `logic/system/bound.py:702`
   - `logic/plugins/unbound_check.py:454,467`
   - `logic/plugins/inactive_check.py:869,882`

### 5. 断开

`disconnect()`（`:432`）：`ws_client.disconnect(timeout=5)`。

## 三、跨服桥接（`BridgeConnector`，`connector/bridge_connector.py`，双模式）

- 装配：`__init__.py:105` 无条件创建，由 `connector.minecraft_bridge.enable` 控制。

### 1. 服务端模式（`is_main_server=True`，`:82`）

- `create_bridge_server(config, on_message=_handle_server_message, on_client_connect, on_client_disconnect)` → `start(daemon=True)`。
- 收到子服消息后（`:211`）：
  - `!!qq` 广播命令（`system.cross_broadcast.qq_command` 前缀）不中继；
  - 其余加 `bridge_source` / `is_admin` 后中继给其它客户端（`:226-228` `ws_server.send_message`）；
  - 本地 `_process_bridge_message` 重建 `BroadcastInfo` 分发到 `system_manager.broadcast_command`。

### 2. 客户端模式（`:98`）

- `create_bridge_client(config, 四回调)` → `connect(reconnect, ping_interval=5, ping_timeout=5, ssl参数..., thread_name="[GUGUBot]Bridge_{client_id}")`。
- `_on_client_close`（`:162`）：忽略旧连接的 close 事件；起后台重连线程（`_is_reconnecting` 标志防并发，循环检查 `enable` 与连接状态）。

### 3. 发送 `send_message`（`:316`）

- `BroadcastInfo` 序列化为 dict（sender / sender_id / source 列表 / processed_message / target / is_admin…）；
- 服务端走 `ws_server.broadcast(message_data)`；
- 客户端走 `ws_client.send(message_data)`。

### 4. 断开（`:357`）

`enable=False` → 服务端 `ws_server.stop()` / 客户端 `ws_client.disconnect()`。

## 四、依赖与测试

- 客户端依赖 `websocket-client`，服务端依赖 `websocket-server`（均在 `GUGUbot/requirements.txt`）。
- `tests/test_websocket.py` 为可通过的定向测试；快速验证：`PYTHONPATH=GUGUBot python -m unittest tests.test_websocket`。

## 五、调用关系速览

```
ConnectorManager.register ──▶ connector.connect()
  ├─ QQWebSocketConnector ──▶ WebSocketFactory.create_client ──▶ WebSocketClient.connect   (WS 客户端 → OneBot)
  └─ BridgeConnector
       ├─ is_main_server ──▶ create_bridge_server ──▶ WebSocketServer.start               (WS 服务端，等子服接入)
       └─ 子服          ──▶ create_bridge_client ──▶ WebSocketClient.connect             (WS 客户端 → 主服)

发消息：
  业务层 ──▶ ConnectorManager.broadcast ──▶ connector.send_message
       ├─ QQ:  bot.send_*_msg ──▶ Bot.__getattr__ ──▶ ws_client.send (OneBot action JSON)
       └─ Bridge: 主服 broadcast / 子服 send (BroadcastInfo dict)

收消息（WS 回调线程）：
       ├─ QQ: echo 响应 → bot.function_return；事件 → server.schedule_task(parser)
       └─ Bridge: 服务端中继+本地处理 / 客户端本地处理 (_process_bridge_message)

断开：ConnectorManager.unregister ──▶ connector.disconnect ──▶ ws_client.disconnect / ws_server.stop
```
