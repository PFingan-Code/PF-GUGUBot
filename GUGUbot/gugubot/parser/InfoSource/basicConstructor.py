import json
from typing import Union


class BasicConstructor:
    def __init__(self, raw_data: Union[str, dict]):
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)
        self.raw_data = raw_data

    def __getattr__(self, key):
        value = self.raw_data.get(key)
        if value is None or isinstance(value, dict):
            return BasicConstructor(value or {})
        return value

    def __bool__(self):
        return bool(self.raw_data)

    def __repr__(self):
        return str(self.raw_data)
