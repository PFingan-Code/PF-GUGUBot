# -*- coding: utf-8 -*-
"""Message builder"""

class MessageBuilder:
    """Message builder"""

    @staticmethod
    def text(text: str) -> dict:
        return {"type": "text", "data": {"text": text}}

    @staticmethod
    def at(qq: int) -> dict:
        return {"type": "at", "data": {"qq": str(qq)}}

    @staticmethod
    def image(file: str) -> dict:
        return {"type": "image", "data": {"file": file}}

    @staticmethod
    def voice(file: str) -> dict:
        return {"type": "record", "data": {"file": file}}

    @staticmethod
    def face(id: int) -> dict:
        return {"type": "face", "data": {"id": str(id)}}

    @staticmethod
    def bface(id: int) -> dict:
        return {"type": "bface", "data": {"id": str(id)}}

    @staticmethod
    def sface(id: int) -> dict:
        return {"type": "sface", "data": {"id": str(id)}}

    @staticmethod
    def location(lat: float, lon: float, title: str = "", content: str = "") -> dict:
        return {
            "type": "location",
            "data": {
                "lat": str(lat),
                "lon": str(lon),
                "title": title,
                "content": content,
            },
        }

    @staticmethod
    def share(url: str, title: str = "", content: str = "", image: str = "") -> dict:
        return {
            "type": "share",
            "data": {
                "url": url,
                "title": title,
                "content": content,
                "image": image,
            },
        }

    @staticmethod
    def contact(type_: str, id_: int) -> dict:
        return {"type": "contact", "data": {"type": type_, "id": str(id_)}}

    @staticmethod
    def reply(id_: int) -> dict:
        return {"type": "reply", "data": {"id": str(id_)}}

    @staticmethod
    def poke(qq: int) -> dict:
        return {"type": "poke", "data": {"qq": str(qq)}}

    @staticmethod
    def dice() -> dict:
        return {"type": "dice", "data": {}}

    @staticmethod
    def rps() -> dict:
        return {"type": "rps", "data": {}}

    @staticmethod
    def shake() -> dict:
        return {"type": "shake", "data": {}}
