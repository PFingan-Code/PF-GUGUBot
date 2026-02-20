# -*- coding: utf-8 -*-
"""Message Builder for Minecraft(via MCDR - RText)"""

import re
from typing import Dict, List, Optional, Union

from mcdreforged.api.rtext import RAction, RColor, RText, RTextBase
from packaging import version

from gugubot.builder.basic_builder import BasicBuilder
from gugubot.constant.qq_emoji_map import qq_emoji_map
from gugubot.utils.player_manager import PlayerManager


class McMessageBuilder(BasicBuilder):
    """Message Builder for Minecraft(via MCDR - RText)"""

    @staticmethod
    def array_to_rtext(
        array: List[Dict[str, Dict[str, str]]],
        low_game_version: bool = False,
        chat_image: bool = False,
        image_previewer: bool = False,
        player_manager: PlayerManager = None,
        bot_id: Optional[str] = None,
    ) -> RText:
        """Convert array to MCDR - RText

        Parameters
        ----------
        array : List[Dict[str, Dict[str, str]]]
            Array message
        low_game_version : bool, optional
            Whether the MC is a low version, default False
        chat_image : bool, optional
            Whether to preview the image with `ChatImage` plugin, default False
        image_previewer : bool, optional
            Whether to preview the image with `ImagePreview` plugin, default False
        player_manager : PlayerManager, optional
            Player manager, default None
        bot_id : Optional[str], optional
            gugubot's id, default None

        Returns
        -------
        RText
            Minecraft message in MCDR - RText format

        Notes
        -----
        - If the MC is a low version, replace the emoji with [emoji].
        - If the image uses ChatImage plugin to preview, convert the image text to CICode.
        - If the image uses ImagePreview plugin to preview, set the image hover text and
          click event to ImagePreview format. If the image link exists, set the image hover text and click event to open link.
        - If @ is for all group members, do not create hover text and click event.
        - If the player is not bound, use the player ID as the player name.
        """

        def _get_player_name(player_id: str) -> str:
            """Get player name"""
            if player_manager:
                player = player_manager.get_player(str(player_id))
                if player:
                    return player.name
            return player_id

        def _process_at(data: Dict[str, str]) -> RText:
            """Process @ message"""
            qq_id = data.get("qq", "")

            # Skip @ to the bot
            if bot_id and str(qq_id) == str(bot_id):
                return RText("")

            player_name = _get_player_name(qq_id)
            # If the player name is all, do not create hover text and click event
            if player_name.strip() == "all":
                return RText(f"[@{player_name}]", color=RColor.aqua)

            return (
                RText(f"[@{player_name}]", color=RColor.aqua)
                .set_hover_text(f"点击草稿 @{player_name} 的消息")
                .set_click_event(
                    action=RAction.suggest_command, value=f"[CQ:at,qq={qq_id}]"
                )
            )

        def _process_face(data: Dict[str, str]) -> RText:
            """Process face"""
            return McMessageBuilder.process_face(
                data, low_game_version=low_game_version
            )

        def _process_image(data: Dict[str, str]) -> RText:
            """Process image"""
            return McMessageBuilder.process_image(
                data, chat_image=chat_image, image_previewer=image_previewer
            )

        def _process_text(data: Dict[str, str]) -> RText:
            """Process text"""
            text = data["text"]
            if low_game_version:
                text = McMessageBuilder.replace_emoji_with_placeholder(text)
            return RText(text)

        def _process_contact(data: Dict[str, str]) -> RText:
            """Process contact"""
            return RText("[推荐群]" if data.get("type") == "group" else "[推荐好友]")

        def _process_json(data: Dict[str, str]) -> RText:
            """Process JSON"""
            url_link = data.get("meta", {}).get("detail_1", {}).get("desc", "")
            group_notice = data.get("prompt", "")
            return RText(
                f"[链接:{url_link}]" if url_link else f"[群公告:{group_notice}]"
            )

        process_functions = {
            "at": _process_at,
            "contact": _process_contact,
            "face": _process_face,
            "json": _process_json,
            "image": _process_image,
            "mface": _process_image,
            "text": _process_text,
            "record": lambda _: RText("[语音]"),
            "video": lambda _: RText("[视频]"),
            "bface": lambda _: RText("[表情]"),
            "sface": lambda _: RText("[表情]"),
            "rps": lambda _: RText("[猜拳]"),
            "dice": lambda _: RText("[掷骰子]"),
            "shake": lambda _: RText("[窗口抖动]"),
            "poke": lambda _: RText("[戳一戳]"),
            "anonymous": lambda _: RText("[匿名消息]"),
            "share": lambda _: RText("[链接]"),
            "location": lambda _: RText("[定位]"),
            "music": lambda _: RText("[音乐]"),
            "forward": lambda _: RText("[转发消息]"),
            "file": lambda _: RText("[文件]"),
            "redbag": lambda _: RText("[红包]"),
        }

        result = RText("")

        for message in array:
            message_type = message["type"]
            message_data = message["data"]

            result += process_functions.get(message_type, lambda x: "")(message_data)

        return result

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
        """Build Minecraft message

        Parameters
        ----------
        forward_content : Union[str, RText]
            Forward content
        group_name : str, optional
            Group name, default "QQ"
        group_id : Optional[str], optional
            Group ID, default None
        sender : Optional[str], optional
            Sender, default None
        sender_id : Optional[str], optional
            Sender ID, default None
        receiver : Optional[str], optional
            Receiver, default None

        Returns
        -------
        RText
            Minecraft message in MCDR - RText format
        """
        rtext = RText(f"[{group_name}]", color=RColor.gold)

        # If the group ID exists, set the group hover text and click event
        if group_id is not None:
            rtext = rtext.set_hover_text(group_id).set_click_event(
                action=RAction.copy_to_clipboard, value=group_id
            )

        # If the sender exists, add the sender text and click event
        if sender is not None:
            rtext += (
                RText(f" [{sender}]", color=RColor.green)
                .set_hover_text(f"点击草稿 @{sender} 的消息")
                .set_click_event(
                    action=RAction.suggest_command,
                    value=f"[CQ:at,qq={sender_id}]" if sender_id else "",
                )
            )

        # If the receiver exists, add the receiver text
        if receiver is not None:
            rtext += RText(f"[@{receiver}]", color=RColor.aqua)

        rtext += RText(" ")

        if isinstance(forward_content, RTextBase):
            rtext += forward_content
        else:
            rtext += RText(f"{forward_content}", color=RColor.white)

        return rtext

    @staticmethod
    def is_low_game_version(version_string: str) -> bool:
        """Check if the MC is a low versio (less than 1.12)"""
        version_pattern = r"^\d+(\.\d+){0,2}$"
        if not re.match(version_pattern, version_string or ""):
            return True
        return version.parse(version_string or "1.12") >= version.parse("1.12")

    @staticmethod
    def process_face(data: Dict[str, str], low_game_version: bool = False) -> RText:
        """Process face"""
        emoji = str(qq_emoji_map.get(data["id"], ""))

        if low_game_version:
            emoji = McMessageBuilder.replace_emoji_with_placeholder(emoji)

        return RText(f"[表情:{emoji}]") if emoji else RText("[表情]")

    @staticmethod
    def process_image(
        data: Dict[str, str], chat_image: bool = False, image_previewer: bool = False
    ) -> RText:
        """
        Process image

        Parameters
        ----------
        data : Dict[str, str]
            Image data
        chat_image : bool, optional
            Whether to preview the image with `ChatImage` plugin, default False
        image_previewer : bool, optional
            Whether to preview the image with `ImagePreview` plugin, default False

        Returns
        -------
        RText
            Minecraft message in MCDR - RText format
        """
        url = data.get("url", "")
        file = data.get("file", "")
        file = rf"file:///{file}" if not file.startswith("http") else file
        summary = data.get("summary", "").strip("[]")
        text = f"[图片:{summary}]" if summary else "[图片]"

        image_link = url or file

        # If the image uses ChatImage plugin to preview, convert the image text to CICode
        if chat_image:
            result = RText(f'[[CICode,url={image_link},name={summary or "图片"}]]')
        else:
            result = RText(text, color=RColor.gold)

        # If the image uses ImagePreview plugin to preview, set the image hover text and
        #   click event to ImagePreview format.
        if image_previewer:
            result = result.set_hover_text(image_link).set_click_event(
                RAction.run_command, f"/imagepreview preview {image_link} 60"
            )
        # If the image link exists, set the image hover text and click event to open link
        elif image_link:
            result = result.set_hover_text(image_link).set_click_event(
                action=RAction.open_url, value=image_link
            )

        return result

    @staticmethod
    def replace_emoji_with_placeholder(text: str) -> str:
        """Replace utf-8 emoji with [emoji]"""
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
