import re
from typing import Dict, List, Optional, Union

from mcdreforged.api.rtext import RAction, RColor, RText, RTextBase
from packaging import version

from gugubot.constant.qq_emoji_map import qq_emoji_map
from gugubot.utils.player_manager import PlayerManager


class McMessageBuilder:
    @staticmethod
    def build(
            forward_content: Union[str, RText],
            *,
            group_name: str = "QQ",
            group_id: Optional[str] = None,
            sender: Optional[str] = None,
            sender_id: Optional[str] = None,
            receiver: Optional[str] = None,
    ) -> RText:
        rtext = RText(f"[{group_name}]", color=RColor.gold)
        if group_id is not None:
            rtext = rtext.set_hover_text(group_id).set_click_event(
                action=RAction.copy_to_clipboard, value=group_id
            )
        if sender is not None:
            rtext += (
                RText(f" [{sender}]", color=RColor.green)
                .set_hover_text(f"点击草稿 @{sender} 的消息")
                .set_click_event(
                    action=RAction.suggest_command,
                    value=f"[CQ:at,qq={sender_id}]" if sender_id else "",
                )
            )
        if receiver is not None:
            rtext += RText(f"[@{receiver}]", color=RColor.aqua)
        rtext += RText(" ")
        if isinstance(forward_content, RTextBase):
            rtext += forward_content
        else:
            rtext += RText(f"{forward_content}", color=RColor.white)

        return rtext

    @staticmethod
    def array_to_RText(
            array: List[Dict[str, Dict[str, str]]],
            sender_id: Optional[str] = None,
            low_game_version: bool = False,
            chat_image: bool = False,
            image_previewer: bool = False,
            player_manager: PlayerManager = None,
            is_admin: bool = False,
            bot_id: Optional[str] = None,
    ) -> RText:
        def get_player_name(player_id: str) -> str:
            if player_manager:
                player = player_manager.get_player(str(player_id))
                if player:
                    return player.name
            return player_id

        def process_at(data: Dict[str, str]) -> RText:
            qq_id = data.get("qq", "")
            # 跳过对机器人的@
            if bot_id and str(qq_id) == str(bot_id):
                return RText("")
            player_name = get_player_name(qq_id)
            if is_admin:
                return (
                    RText(f"[@{player_name}]", color=RColor.aqua)
                    .set_hover_text(f"点击草稿 @{player_name} 的消息")
                    .set_click_event(
                        action=RAction.suggest_command, value=f"[CQ:at,qq={qq_id}]"
                    )
                )
            else:
                return RText(f"[@{player_name}]", color=RColor.aqua)

        process_functions = {
            "text": lambda data: RText(
                data["text"]
                if not low_game_version
                else McMessageBuilder.replace_emoji_with_placeholder(data["text"])
            ),
            "at": process_at,
            "image": lambda data: McMessageBuilder.process_image(
                data, chat_image=chat_image, image_previewer=image_previewer
            ),
            "record": lambda _: RText("[语音]"),
            "video": lambda _: RText("[视频]"),
            "face": lambda data: McMessageBuilder.process_face(
                data, low_game_version=low_game_version
            ),
            "bface": lambda _: RText("[表情]"),
            "mface": lambda data: McMessageBuilder.process_image(
                data, chat_image=chat_image, image_previewer=image_previewer
            ),
            "sface": lambda _: RText("[表情]"),
            "rps": lambda _: RText("[猜拳]"),
            "dice": lambda _: RText("[掷骰子]"),
            "shake": lambda _: RText("[窗口抖动]"),
            "poke": lambda _: RText("[戳一戳]"),
            "anonymous": lambda _: RText("[匿名消息]"),
            "share": lambda _: RText("[链接]"),
            "contact": lambda data: (
                RText("[推荐群]")
                if data.get("type") == "group"
                else RText("[推荐好友]")
            ),
            "location": lambda _: RText("[定位]"),
            "music": lambda _: RText("[音乐]"),
            "forward": lambda _: RText("[转发消息]"),
            "file": lambda _: RText("[文件]"),
            "redbag": lambda _: RText("[红包]"),
            "json": lambda data: RText(
                f"[链接:{data.get('meta', {}).get('detail_1', {}).get('desc', '')}]"
                or f"[群公告:{data.get('prompt', '')}"
            ),
        }

        result = RText("")

        for message in array:
            message_type = message["type"]
            message_data = message["data"]

            result += process_functions.get(message_type, lambda x: "")(message_data)

        return result

    @staticmethod
    def is_low_game_version(version_string: str) -> bool:
        version_pattern = r"^\d+(\.\d+){0,2}$"
        if not re.match(version_pattern, version_string or ""):
            return True
        return version.parse(version_string or "1.12") >= version.parse("1.12")

    @staticmethod
    def replace_emoji_with_placeholder(text: str) -> str:
        # RE for emoji
        emoji_pattern = re.compile(
            "[\U0001f600-\U0001f64f"  # emoticons
            "\U0001f300-\U0001f5ff"  # various symbols and icons
            "\U0001f680-\U0001f6ff"  # transportation symbols
            "\U0001f700-\U0001f77f"  # alchemical symbols
            "\U0001f780-\U0001f7ff"  # geometric shapes
            "\U0001f800-\U0001f8ff"  # supplemental arrows
            "\U0001f900-\U0001f9ff"  # supplemental emoticons
            "\U0001fa00-\U0001fa6f"  # supplemental tools and objects
            "\U0001fa70-\U0001faff"  # supplemental cultural symbols
            "\u2600-\u26ff"  # miscellaneous symbols
            "\u2700-\u27bf"  # Dingbats
            "]+",
            flags=re.UNICODE,
        )
        # Replace emoji with `[emoji]`
        return emoji_pattern.sub("[emoji]", text)

    @staticmethod
    def process_face(data: Dict[str, str], low_game_version: bool = False) -> RText:
        emoji = str(qq_emoji_map.get(data["id"], ""))

        if low_game_version:
            emoji = McMessageBuilder.replace_emoji_with_placeholder(emoji)

        return RText(f"[表情:{emoji}]") if emoji else RText("[表情]")

    @staticmethod
    def process_image(
            data: Dict[str, str], chat_image: bool = False, image_previewer: bool = False
    ) -> RText:
        url = data.get("url", "")
        file = data.get("file", "")
        file = rf"file:///{file}" if not file.startswith("http") else file

        summary = data.get("summary", "").strip("[]")
        result = None

        image_link = url or file

        if chat_image:
            result = RText(f'[[CICode,url={image_link},name={summary or "图片"}]]')

        text = f"[图片:{summary}]" if summary else "[图片]"
        result = RText(text, color=RColor.gold) if result is None else result

        if image_previewer:
            result = result.set_hover_text(image_link).set_click_event(
                RAction.run_command, f"/imagepreview preview {image_link} 60"
            )

        elif image_link:
            result = result.set_hover_text(image_link).set_click_event(
                action=RAction.open_url, value=image_link
            )
        return result
