"""Abstract base connector class."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from gugubot.config import BotConfig
from gugubot.parser.basic_parser import BasicParser
from gugubot.utils.types import ProcessedInfo


class BasicConnector(ABC):
    """Abstract base connector class.

    Attributes
    ----------
    source : str
        Identifier or description of the underlying source (for example a
        URL, websocket address, or client name).  Concrete implementations
        should set this value to describe where messages come from.
    parser : Any
        Object responsible for parsing raw incoming data into internal
        message objects.
    builder : Any
        Object responsible for building outgoing messages from internal
        message objects into the raw format required by the source.
    server : Any
        Back-reference to the MCDR server instance.
    logger : Any
        Logger instance.  May be overridden by ``ConnectorManager`` during
        registration.
    """

    def __init__(
        self,
        source: str = "",
        parser: Optional[BasicParser] = None,
        builder: Any = None,
        server: Any = None,
        logger: Any = None,
        config: Optional[BotConfig] = None,
    ) -> None:
        self.source: str = source
        self.parser: Optional[BasicParser] = parser
        self.builder: Any = builder
        self.server: Any = server
        self.connector_manager: Any = (
            None  # Will be set when registered to ConnectorManager
        )
        self.logger: Any = logger
        self.config: BotConfig = config or {}
        self.enable: bool = self.config.get_keys(
            ["connector", self.source, "enable"], True
        )
        self.enable_receive: bool = self.config.get_keys(
            ["connector", self.source, "enable_receive"], self.enable
        )
        self.enable_send: bool = self.config.get_keys(
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
    async def send_message(self, processed_info: ProcessedInfo) -> None:
        """Send a message through the connector.

        Parameters
        ----------
        processed_info : ProcessedInfo
            The message to be sent.  Implementations should use
            ``self.builder`` to transform the message if needed before
            sending.

        Notes
        -----
        Implementations may check ``self.enable_send`` and return early if
        disabled.
        """
        raise NotImplementedError

    @abstractmethod
    async def on_message(self, raw: Any) -> None:
        """Handle a raw incoming message.

        Typical responsibilities:

        * Use ``self.parser`` to convert *raw* into an internal message
          object.
        * Dispatch the parsed message to upper-layer handlers.

        Parameters
        ----------
        raw : Any
            The raw data received from the source.

        Notes
        -----
        Implementations may check ``self.enable`` and return early if
        disabled.
        """
        raise NotImplementedError
