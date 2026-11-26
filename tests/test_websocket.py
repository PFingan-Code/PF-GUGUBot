"""WebSocket 模块测试

测试 WebSocket 客户端和服务器的基本功能
"""
import unittest
import time
import logging
from typing import List, Dict
from unittest import mock

try:
    from gugubot.ws import WebSocketServer, WebSocketClient, WebSocketFactory
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False


@unittest.skipIf(not WS_AVAILABLE, "WebSocket 模块不可用")
class TestWebSocketServer(unittest.TestCase):
    """测试 WebSocket 服务器"""
    
    @classmethod
    def setUpClass(cls):
        print("\n** Testing WebSocket Server **")
        cls.logger = logging.getLogger(__name__)
        cls.logger.setLevel(logging.INFO)
    
    def setUp(self):
        """每个测试前的设置"""
        self.received_messages: List[str] = []
        self.connected_clients: List[Dict] = []
        self.disconnected_clients: List[Dict] = []
    
    def on_message(self, client, server, message):
        """消息接收回调"""
        self.received_messages.append(message)
        self.logger.info(f"收到消息: {message}")
    
    def on_client_connect(self, client, server):
        """客户端连接回调"""
        self.connected_clients.append(client)
        self.logger.info(f"客户端连接: {client['address']}")
    
    def on_client_disconnect(self, client, server):
        """客户端断开回调"""
        self.disconnected_clients.append(client)
        self.logger.info(f"客户端断开: {client['address']}")
    
    def test_server_start_stop(self):
        """测试服务器启动和停止"""
        server = WebSocketServer(
            host="127.0.0.1",
            port=18080,  # 使用不同的端口避免冲突
            logger=self.logger
        )
        
        # 启动服务器
        server.start(daemon=True)
        self.assertTrue(server.is_running())
        
        # 等待服务器完全启动
        time.sleep(0.5)
        
        # 停止服务器
        server.stop()
        self.assertFalse(server.is_running())
    
    def test_server_properties(self):
        """测试服务器属性"""
        server = WebSocketServer(
            host="127.0.0.1",
            port=18081,
            on_message=self.on_message,
            on_client_connect=self.on_client_connect,
            on_client_disconnect=self.on_client_disconnect,
            logger=self.logger
        )
        
        server.start(daemon=True)
        time.sleep(0.5)
        
        # 测试初始状态
        self.assertEqual(server.get_client_count(), 0)
        self.assertEqual(len(server.get_clients()), 0)
        
        server.stop()
    
    def test_server_broadcast_without_clients(self):
        """测试没有客户端时的广播"""
        server = WebSocketServer(
            host="127.0.0.1",
            port=18082,
            logger=self.logger
        )
        
        server.start(daemon=True)
        time.sleep(0.5)
        
        # 广播消息（没有客户端）
        count = server.broadcast({"type": "test", "message": "hello"})
        self.assertEqual(count, 0)
        
        server.stop()


@unittest.skipIf(not WS_AVAILABLE, "WebSocket 模块不可用")
class TestWebSocketFactory(unittest.TestCase):
    """测试 WebSocket 工厂类"""
    
    @classmethod
    def setUpClass(cls):
        print("\n** Testing WebSocket Factory **")
        cls.logger = logging.getLogger(__name__)
    
    def test_create_client(self):
        """测试创建客户端"""
        client = WebSocketFactory.create_client(
            url="ws://localhost:8080",
            token="test_token",
            logger=self.logger
        )
        
        self.assertIsInstance(client, WebSocketClient)
        self.assertEqual(client.url, "ws://localhost:8080")
        self.assertIsNotNone(client.headers)
        self.assertEqual(client.headers["Authorization"], "Bearer test_token")
    
    def test_create_client_without_token(self):
        """测试创建无令牌的客户端"""
        client = WebSocketFactory.create_client(
            url="ws://localhost:8080",
            logger=self.logger
        )
        
        self.assertIsInstance(client, WebSocketClient)
        self.assertIsNone(client.headers)

    def test_on_reconnect_callback_runs_after_reconnection(self):
        on_open = mock.Mock()
        on_reconnect = mock.Mock()
        client = WebSocketFactory.create_client(
            url="ws://localhost:8080",
            on_open=on_open,
            on_reconnect=on_reconnect,
            logger=self.logger,
        )
        fake_app = mock.Mock()

        with mock.patch(
            "gugubot.ws.websocket_client.websocket.WebSocketApp",
            return_value=fake_app,
        ) as app_factory, mock.patch(
            "gugubot.ws.websocket_client.threading.Thread"
        ) as thread_factory:
            client.connect(reconnect=0)
            open_callback = app_factory.call_args.kwargs["on_open"]
            fake_app.run_forever.side_effect = lambda **kwargs: open_callback(fake_app)
            thread_factory.call_args.kwargs["target"]()

        on_open.assert_called_once_with(fake_app)
        on_reconnect.assert_not_called()

    def test_reconnect_attempt_limit_is_enforced(self):
        on_open = mock.Mock()
        on_reconnect = mock.Mock()
        client = WebSocketFactory.create_client(
            url="ws://localhost:8080",
            on_open=on_open,
            on_reconnect=on_reconnect,
            logger=self.logger,
        )
        fake_app = mock.Mock()

        with mock.patch(
            "gugubot.ws.websocket_client.websocket.WebSocketApp",
            return_value=fake_app,
        ) as app_factory, mock.patch(
            "gugubot.ws.websocket_client.threading.Thread"
        ) as thread_factory:
            client.connect(reconnect=1, reconnect_attempts=2)
            open_callback = app_factory.call_args.kwargs["on_open"]
            fake_app.run_forever.side_effect = lambda **kwargs: open_callback(fake_app)
            client._stop_event.wait = mock.Mock(return_value=False)
            thread_factory.call_args.kwargs["target"]()

        self.assertEqual(fake_app.run_forever.call_count, 3)
        on_open.assert_called_once_with(fake_app)
        self.assertEqual(on_reconnect.call_count, 2)


if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    unittest.main()
