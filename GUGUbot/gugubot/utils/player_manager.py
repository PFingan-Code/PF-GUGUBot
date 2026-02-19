# -*- coding: utf-8 -*-
# +----------------------------------------------------------------------+
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcdreforged.api.types import PluginServerInterface

from gugubot.config import BasicConfig, BotConfig


# +----------------------------------------------------------------------+


@dataclass
class Player:
    """玩家数据类"""

    name: str  # 玩家主名称
    java_name: List[str] = field(default_factory=list)  # Java版名称列表
    bedrock_name: List[str] = field(default_factory=list)  # 基岩版名称列表
    accounts: Dict[str, List[str]] = field(default_factory=dict)  # 账号映射表
    properties: Dict[str, Any] = field(default_factory=dict)  # 自定义属性

    def add_name(self, player_name: str, is_bedrock: bool = False) -> None:
        """添加名称"""
        if is_bedrock and player_name not in self.bedrock_name:
            self.bedrock_name.append(player_name)
        elif player_name not in self.java_name:
            self.java_name.append(player_name)

    def add_account(self, platform: str, account_id: str) -> None:
        """添加关联账号"""
        if platform not in self.accounts:
            self.accounts[platform] = []
        if account_id not in self.accounts[platform]:
            self.accounts[platform].append(account_id)

    def set_property(self, key: str, value: Any) -> None:
        """设置自定义属性"""
        self.properties[key] = value

    def get_property(self, key: str, default: Any = None) -> Any:
        """获取自定义属性"""
        return self.properties.get(key, default)


class PlayerManager(BasicConfig):
    """玩家管理器"""

    def __init__(self, server: PluginServerInterface, bound_system):
        self.server = server
        self.logger = server.logger
        self.bound_system = bound_system
        self._players: Dict[str, Player] = {}  # 玩家数据字典
        data_path = Path(server.get_data_folder()) / "system" / "players.json"
        super().__init__(path=str(data_path), default_content={}, yaml_format=True)

    def load(self) -> None:
        """加载玩家数据"""
        super().load()
        # 转换数据为Player对象
        for name, data in self.items():
            self._players[name] = Player(
                name=name,
                java_name=data.get("java_name", []),
                bedrock_name=data.get("bedrock_name", []),
                accounts=data.get("accounts", {}),
                properties=data.get("properties", {}),
            )

    def save(self) -> None:
        """保存玩家数据"""
        temp = {}
        for name, player in self._players.items():
            temp[name] = {
                "java_name": player.java_name,
                "bedrock_name": player.bedrock_name,
                "accounts": player.accounts,
                "properties": player.properties,
            }
        self.clear()
        self.update(temp)
        super().save()

    def add_player(
        self, name: str, player_name: str = None, is_bedrock: bool = False
    ) -> Player:
        """添加新玩家

        Args:
            name: str - 玩家名称
            player_name: str - 玩家名称
            is_bedrock: bool - 是否为基岩版玩家
        """
        if name not in self._players:
            self._players[name] = Player(name=name)
        if player_name:
            self._players[name].add_name(player_name, is_bedrock)
        self.save()
        return self._players[name]

    def remove_player(self, name: str) -> bool:
        """删除玩家"""
        if name in self._players:
            del self._players[name]
            self.save()
            return True
        return False

    def get_player(
        self, identifier: str, platform: str = None, name_only: bool = False
    ) -> Optional[Player]:
        """
        通用的玩家查找函数

        Args:
            identifier: str - 玩家标识符（可以是名称、UUID或账号ID）

        Returns:
            Optional[Player] - 找到的玩家对象，如果未找到则返回None

        Examples:
            # 通过名称查找
            player = manager.get_player("Steve")

            # 通过UUID查找（Java版或基岩版）
            player = manager.get_player("uuid-xxxxx")

            # 通过关联账号查找
            player = manager.get_player("discord-id")
        """
        # 1. 通过名称查找
        if identifier in self._players:
            return self._players[identifier]

        if name_only:
            return None

        for player in self._players.values():
            # 2. 通过UUID查找
            if identifier in player.java_name or identifier in player.bedrock_name:
                return player

            # 3. 通过关联账号查找
            for platform_name, account_ids in player.accounts.items():
                if platform and platform_name != platform:
                    continue
                if identifier in account_ids:
                    return player

        return None

    def get_all_players(self) -> List[Player]:
        """获取所有玩家列表"""
        return list(self._players.values())

    def add_player_account(
        self, identifier: str, platform: str, account_id: str, is_bedrock: bool = False
    ) -> bool:
        """添加玩家关联账号"""
        player = self.get_player(identifier) or self.get_player(
            account_id, platform=platform
        )
        if not player:
            player = self.add_player(
                identifier, player_name=identifier, is_bedrock=is_bedrock
            )
        player.add_account(platform, account_id)
        self.save()
        return True

    def is_name_bound_by_other_user(
        self, player_name: str, current_user_id: str, source: str
    ) -> bool:
        """检查玩家名是否已被其他用户绑定

        Args:
            player_name: str - 要检查的玩家名
            current_user_id: str - 当前用户ID
            source: str - 当前用户来源
            is_bedrock: bool - 是否为基岩版玩家名

        Returns:
            bool - 如果已被其他用户绑定则返回True
        """
        for player in self._players.values():
            player_in_name = (
                player_name in player.java_name or player_name in player.bedrock_name
            )
            not_current_user = current_user_id not in player.accounts.get(source, [])
            platform_not_bound = source in player.accounts

            if player_in_name and not_current_user and platform_not_bound:
                return True

        return False

    async def is_admin(self, sender_id: str) -> bool:
        """检查是否是管理员"""
        player = self.get_player(sender_id)

        if not player:
            return False

        config: BotConfig = self.bound_system.config
        connectors = config.get_keys(["connector"], {})

        for source, connector_config in connectors.items():
            permissions = connector_config.get("permissions", {})
            admin_ids = permissions.get("admin_ids", [])
            admin_group_ids = permissions.get("admin_group_ids", [])

            if source == config.get_keys(["connector", "QQ", "source_name"], "QQ"):
                admin_group_member_ids = set()
                for admin_group_id in admin_group_ids:
                    if not admin_group_id:
                        continue
                    try:
                        admin_group_members = await self.bound_system.system_manager.connector_manager.get_connector(
                            "QQ"
                        ).bot.get_group_member_list(
                            group_id=int(admin_group_id)
                        )

                        if (
                            admin_group_members
                            and admin_group_members.get("status") == "ok"
                        ):
                            admin_group_member_ids.update(
                                [
                                    str(member.get("user_id", ""))
                                    for member in admin_group_members.get("data", [])
                                ]
                            )
                    except Exception as e:
                        self.logger.error(
                            f"获取管理群 {admin_group_id} 成员列表失败: {e}"
                        )
                        continue
                admin_group_ids = list(admin_group_member_ids)

            platform_accounts = player.accounts.get(source, [])
            for account_id in platform_accounts:
                if str(account_id) in [str(i) for i in admin_ids + admin_group_ids]:
                    return True

        return False
