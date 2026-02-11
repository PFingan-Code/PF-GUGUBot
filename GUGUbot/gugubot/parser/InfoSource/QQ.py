from mcdreforged.api.event import LiteralEvent

from gugubot.parser.InfoSource.basicConstructor import BasicConstructor


class QQInfo(BasicConstructor):
    parser_name = "QQ"

    PROCESS_POST_TYPE = [
        "message",
        "request",
        "notice"
    ]

    def __init__(self, raw_data, server, bot):
        super().__init__(raw_data)

        self.server = server
        self.bot = bot

        if self.post_type not in self.PROCESS_POST_TYPE:
            return

        if self.post_type == "message":
            self.source_id = self.user_id if self.message_type == "private" else self.group_id

        self.server.dispatch_event(
            LiteralEvent("gugubot.on_qq_message"),
            (self, self.bot)
        )
