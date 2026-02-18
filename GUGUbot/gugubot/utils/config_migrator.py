# -*- coding: utf-8 -*-
import shutil
from pathlib import Path

from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True


def migrate_config_v1_to_v2(
        config_path: Path, default_config_content: str, logger=None
):
    """
    Migrate configuration from v1.0 to v2.0.
    """
    if not config_path.exists():
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            old_config = yaml.load(f)
    except Exception:
        return  # Not a valid YAML or something, let normal init handle it

    # Check if it is v1 config
    # v1 has "admin_id" at root, v2 has "GUGUBot" at root
    if not old_config or "GUGUBot" in old_config:
        return  # Already v2 or empty or unknown

    # Basic check for v1 signature fields
    if "admin_id" not in old_config and "group_id" not in old_config:
        return  # Doesn't look like v1 either

    if logger:
        logger.info("检测到旧版本配置，正在迁移到新版本...")

    # Load default v2 config
    new_config = yaml.load(default_config_content)

    # --- MIGRATION MAPPING ---

    # Helper to safe get
    def get(d, *keys, default=None):
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k)
            else:
                return default
        return d if d is not None else default

    # Connector / QQ / Permissions
    if "admin_id" in old_config:
        new_config["connector"]["QQ"]["permissions"]["admin_ids"] = old_config[
            "admin_id"
        ]
    if "admin_group_id" in old_config:
        new_config["connector"]["QQ"]["permissions"]["admin_group_ids"] = old_config[
            "admin_group_id"
        ]
    if "group_id" in old_config:
        new_config["connector"]["QQ"]["permissions"]["group_ids"] = old_config[
            "group_id"
        ]
    if "friend_is_admin" in old_config:
        new_config["connector"]["QQ"]["permissions"]["friend_is_admin"] = old_config[
            "friend_is_admin"
        ]

    custom_group_name = get(old_config, "custom_group_name")
    if custom_group_name:
        new_config["connector"]["QQ"]["permissions"][
            "custom_group_name"
        ] = custom_group_name

    # Connector / Minecraft Bridge
    if "is_main_server" in old_config:
        new_config["connector"]["minecraft_bridge"]["is_main_server"] = old_config[
            "is_main_server"
        ]

    # Connector / Minecraft
    if "server_name" in old_config:
        new_config["connector"]["minecraft"]["source_name"] = (
                old_config["server_name"] or "Minecraft"
        )

    # GUGUBot (Core)
    if "command_prefix" in old_config:
        new_config["GUGUBot"]["command_prefix"] = old_config["command_prefix"]
    if "show_message_in_console" in old_config:
        new_config["GUGUBot"]["show_message_in_console"] = old_config[
            "show_message_in_console"
        ]

    # Commands (System Enables)
    cmds = old_config.get("command", {})
    if "group_admin" in cmds:
        new_config["GUGUBot"]["group_admin"] = cmds["group_admin"]
    if "ban_word" in cmds:
        new_config["system"]["ban_words"]["enable"] = cmds["ban_word"]
    if "key_word" in cmds:
        new_config["system"]["key_words"]["enable"] = cmds["key_word"]
    if "list" in cmds:
        new_config["system"]["list"]["enable"] = cmds["list"]
    if "name" in cmds:
        new_config["system"]["name"]["enable"] = cmds["name"]
    if "start_command" in cmds:
        new_config["system"]["start_command"]["enable"] = cmds["start_command"]
    if "whitelist" in cmds:
        new_config["system"]["whitelist"]["enable"] = cmds["whitelist"]

    if "bound_notice" in old_config:
        new_config["system"]["bound_notice"]["enable"] = old_config["bound_notice"]

    # Forward (Connector / Minecraft features)
    fwd = old_config.get("forward", {})
    if "forward_other_bot" in fwd:
        new_config["connector"]["QQ"]["others"]["forward_other_bot"] = fwd[
            "forward_other_bot"
        ]
    if "mc_achievement" in fwd:
        new_config["connector"]["minecraft"]["mc_achievement"] = fwd["mc_achievement"]
    if "mc_death" in fwd:
        new_config["connector"]["minecraft"]["mc_death"] = fwd["mc_death"]

    if "player_notice" in fwd:
        new_config["connector"]["minecraft"]["player_join_notice"] = fwd[
            "player_notice"
        ]
        new_config["connector"]["minecraft"]["player_left_notice"] = fwd[
            "player_notice"
        ]

    if "bot_notice" in fwd:
        new_config["connector"]["minecraft"]["bot_join_notice"] = fwd["bot_notice"]
        new_config["connector"]["minecraft"]["bot_left_notice"] = fwd["bot_notice"]

    # Style
    if "style" in old_config:
        new_config["style"]["current_style"] = old_config["style"]
    if "style_cooldown" in old_config:
        new_config["style"]["style_cooldown"] = old_config["style_cooldown"]

    # Bound System
    if "whitelist_add_with_bound" in old_config:
        new_config["system"]["bound"]["whitelist_add_with_bound"] = old_config[
            "whitelist_add_with_bound"
        ]
    if "whitelist_remove_with_leave" in old_config:
        new_config["system"]["bound"]["whitelist_remove_with_leave"] = old_config[
            "whitelist_remove_with_leave"
        ]
    if "max_bound" in old_config:
        new_config["system"]["bound"]["max_java_bound"] = old_config["max_bound"]
        new_config["system"]["bound"]["max_bedrock_bound"] = old_config["max_bound"]

    # Backup old config
    backup_path = config_path.with_name(
        f"{config_path.stem}_v1_backup{config_path.suffix}"
    )
    shutil.copy2(config_path, backup_path)
    if logger:
        logger.info(f"已备份旧配置到 {backup_path}")

    # Save new config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(new_config, f)

    if logger:
        logger.info("配置迁移成功")
