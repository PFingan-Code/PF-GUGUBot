import json

from gugubot.config.BasicConfig import BasicConfig, yaml


class BotConfig(BasicConfig):
    def __init__(
            self, path="./config.yml", default_content=None, yaml_format=True, logger=None
    ):
        self.logger = logger
        super().__init__(path, default_content, yaml_format)

    def load(self):
        self.validate()
        super().load()
        self.plugin_check()

    def add_new_config(self, server):
        """Add new configs from latest version to current config"""
        # read the latest config file from MCDR package
        with server.open_bundled_file(
                "gugubot/config/defaults/default_config.yml"
        ) as file_handler:
            message = file_handler.read()
        message_unicode = message.decode("utf-8").replace("\r\n", "\n")
        yaml_data = yaml.load(message_unicode)

        # update
        def _update_config(old_yaml_data, new_yaml_data):
            for key, value in old_yaml_data.items():
                if isinstance(value, dict):
                    _update_config(value, new_yaml_data[key])
                else:
                    new_yaml_data[key] = value
            return new_yaml_data

        self.update(_update_config(self, yaml_data))
        self.save()

    def plugin_check(self):
        """Avoid None or empty value in config"""

        # Not exist/None -> error
        # not list -> [value]
        # extra empty value -> remove empty value
        listTypeConfigs = ["admin_id", "group_id"]

        for config_name in listTypeConfigs:
            if not self.get(config_name):
                if self.logger:
                    self.logger.error(f"请设置 {config_name}")
                continue

            value = self[config_name]
            if not isinstance(value, list):
                self[config_name] = [value]
                continue

            if any(value):
                self[config_name] = [i for i in value if i]

        # prevent None value/not list type
        if "admin_group_id" in self:
            if not self["admin_group_id"]:
                self["admin_group_id"] = []

            elif not isinstance(self["admin_group_id"], list):
                self["admin_group_id"] = [self["admin_group_id"]]

        self.save()

    def validate(self):
        """Validate config file and prompt user where is wrong, including YAML/JSON syntax errors."""
        # Check YAML or JSON syntax
        try:
            with open(self.path, "r", encoding="UTF-8") as f:
                if self.yaml_format:
                    yaml.load(f)
                else:
                    json.load(f)
        except Exception as e:
            if self.yaml_format:
                mark = getattr(e, "problem_mark", None)
                if mark:
                    error_detail = f"详细信息: {e}"
                    location_info = (
                        f"出错位置：第 {mark.line + 1} 行，第 {mark.column + 1} 列"
                    )
                    msg = (
                            f"YAML 配置文件语法错误: {location_info}" + "\n" + error_detail
                    )
                else:
                    error_detail = f"YAML 配置文件语法错误: {e}"
                    check_hint = "请检查 YAML 文件的缩进和冒号(:)是否正确。"
                    msg = error_detail + "\n" + check_hint
            else:
                lineno = getattr(e, "lineno", None)
                colno = getattr(e, "colno", None)
                if lineno and colno:
                    error_detail = f"详细信息: {e}"
                    location_info = f"出错位置：第 {lineno} 行，第 {colno} 列"
                    msg = (
                            f"JSON 配置文件语法错误: {location_info}" + "\n" + error_detail
                    )
                else:
                    error_detail = f"JSON 配置文件语法错误: {e}"
                    check_hint = "请检查 JSON 文件的格式是否正确。"
                    msg = error_detail + "\n" + check_hint

                if self.logger:
                    self.logger.error(msg)
                else:
                    print(msg)

            return False
