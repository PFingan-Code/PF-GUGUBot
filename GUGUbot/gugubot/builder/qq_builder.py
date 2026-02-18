import html
import re
from typing import Dict, List


class ArrayHandler:
    @staticmethod
    def build(
            array: List[Dict[str, Dict[str, str]]],
    ) -> List[Dict[str, Dict[str, str]]]:
        return array

    @staticmethod
    def parse(
            message: List[Dict[str, Dict[str, str]]],
    ) -> List[Dict[str, Dict[str, str]]]:
        return message


class CQHandler:
    @staticmethod
    def parse(message: str) -> List[Dict[str, Dict[str, str]]]:
        """
        Parse CQ string to Array.
        """
        cq_pattern = re.compile(r"\[CQ:(\w+)((?:,\w+=[^,\]]*)*)\]")
        kv_pattern = re.compile(r",(\w+)=([^,\]]*)")

        result = []
        last_index = 0

        for match in cq_pattern.finditer(message):
            start, end = match.span()

            # text
            if start > last_index:
                text_part = message[last_index:start]
                if text_part:
                    result.append(
                        {"type": "text", "data": {"text": html.unescape(text_part)}}
                    )

            # CQ Code
            cq_type = match.group(1)
            kv_string = match.group(2)

            kv_pairs = {
                key: html.unescape(val) for key, val in kv_pattern.findall(kv_string)
            }

            result.append({"type": cq_type, "data": kv_pairs})

            last_index = end

        # Ending text
        if last_index < len(message):
            tail_text = message[last_index:]
            if tail_text:
                result.append(
                    {"type": "text", "data": {"text": html.unescape(tail_text)}}
                )

        return result

    @staticmethod
    def build(array: List[Dict[str, Dict[str, str]]]) -> str:
        """Covert Array to CQ string."""

        def escape_val(val: str) -> str:
            return (
                html.escape(val, quote=False)
                .replace("[", "&#91;")
                .replace("]", "&#93;")
                .replace(",", "&#44;")
            )

        parts = []
        for unit in array:
            t = unit.get("type")
            data = unit.get("data", {})
            if t == "text":
                parts.append(html.escape(data.get("text", "")))
            else:
                kv = ",".join(f"{k}={escape_val(v)}" for k, v in data.items())
                parts.append(f"[CQ:{t}{',' + kv if kv else ''}]")
        return "".join(parts)
