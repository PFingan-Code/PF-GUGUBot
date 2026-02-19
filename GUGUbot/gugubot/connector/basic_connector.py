from abc import ABC, abstractmethod
from typing import Any, Optional

from gugubot.config.BotConfig import BotConfig
from gugubot.parser.basic_parser import BasicParser
from gugubot.utils.types import BroadcastInfo, ProcessedInfo


class BasicConnector(ABC):
    """Abstract base connector class.

    Attributes
    ----------
    source: str
            Identifier or description of the underlying source (for example a URL,
            websocket address, or client name). Concrete implementations should set
            this value to describe where messages come from.
    parser: Any
            Object responsible for parsing raw incoming data into internal message
            objects.
    builder: Any
            Object responsible for building outgoing messages from internal
            message objects into the raw format required by the source.

    Methods
    -------
    connect()
            Establish the underlying connection (usually asynchronous).
    disconnect()
            Tear down the connection and free resources (usually asynchronous).
    on_message(raw)
            Handle a raw incoming message (usually asynchronous).
    """

    def __init__(
        self,
        source: str = "",
        parser: Optional[BasicParser] = None,
        builder: Any = None,
        server: Any = None,
        logger: Any = None,
        config: BotConfig = None,
    ) -> None:
        self.source: str = source
        self.parser: Optional[BasicParser] = parser
        self.builder: Any = builder
        self.connector_manager: Any = (
            None  # Will be set when registered to ConnectorManager
        )
        self.logger: Any = None  # Will be set when registered to ConnectorManager
        self.config: BotConfig = config or {}
        self.enable: bool = config.get_keys(["connector", self.source, "enable"], True)
        self.enable_receive: bool = config.get_keys(
            ["connector", self.source, "enable_receive"], self.enable
        )
        self.enable_send: bool = config.get_keys(
            ["connector", self.source, "enable_send"], self.enable
        )

    @abstractmethod
    async def connect(self) -> None:
        """Establish the low-level connection. Implementations should override
        this method and perform asynchronous connection setup.
        """
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the low-level connection and release resources."""
        raise NotImplementedError

    @abstractmethod
    async def send_message(self, processed_info: ProcessedInfo, **kwargs) -> None:
        """Send a message through the connector.

        Parameters
        ----------
        processed_info: ProcessedInfo
                The message to be sent. Implementations should use self.builder
                to transform the message if needed before sending.

        Note
        ----
        Implementations may check self.enable (master switch) and return early if disabled.
        enable_send 由 connector_manager 在广播时统一过滤，此处无需再判。
        """
        raise NotImplementedError

    @abstractmethod
    async def on_message(self, raw: Any) -> BroadcastInfo:
        """Called when a raw message is received.

        Typical responsibilities:
        - Use self.parser to convert `raw` into an internal message object.
        - Dispatch the parsed message to upper-layer handlers.

        Parameters
        ----------
        raw: Any
                The raw data received from `source`.

        Note
        ----
        Implementations may check self.enable (master switch) and return early if disabled.
        enable_receive 由 echo 在转发时统一排除，此处无需再判。
        """
        raise NotImplementedError
