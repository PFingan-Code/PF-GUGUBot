# -*- coding: utf-8 -*-
"""Basic configuration class for loading and saving JSON/YAML files with auto-saving."""

import json
from pathlib import Path
from typing import Any, List, Optional

from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True


class BasicConfig(dict):
    """
    Basic configuration class for loading and saving JSON/YAML files with auto-saving.
    Be careful, changing the mutable value will not be saved automatically.
    """

    def __init__(
        self,
        path: str = "./config.json",
        default_content: dict = None,
        yaml_format: bool = False,
    ) -> None:
        super().__init__()
        self.yaml_format = yaml_format
        self.path = Path(path).with_suffix(".yml" if yaml_format else ".json")
        self.default_content = default_content or {}
        self.load()

    def load(self) -> None:
        """Load data from file."""
        if self.path.is_file() and self.path.stat().st_size > 0:
            with self.path.open("r", encoding="UTF-8") as f:
                self.update(yaml.load(f) if self.yaml_format else json.load(f))
        else:
            self.update(self.default_content)
            self.save()

    def save(self) -> None:
        """Save data to file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="UTF-8") as f:
            if self.yaml_format:
                yaml.dump(dict(self), f)
            else:
                json.dump(dict(self), f, ensure_ascii=False)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.save()

    def get_keys(self, key: List[str], default: Optional[Any] = None) -> Any:
        """
        Get value from config by key path.

        Parameters
        ----------
        key : List[str]
            A list of keys to get the value from config
        default : Any, optional
            Default value if the key is not found, default None

        Returns
        -------
        Any
            Value from config by key path

        Examples
        --------
        >>> config = BasicConfig()
        >>> config.get_keys(["connector", "QQ", "permissions", "admin_ids"])
        [123456, 654321]
        >>> config.get_keys(["key", "not", "exists"], [123, 321])
        [123, 321]
        """
        result = self
        for k in key[:-1]:
            result = result.get(k, {})
        return result.get(key[-1], default)
