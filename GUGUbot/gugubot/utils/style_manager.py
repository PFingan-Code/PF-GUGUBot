# -*- coding: utf-8 -*-
"""风格管理器模块

该模块提供风格管理功能，允许用户自定义翻译风格。
"""

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mcdreforged.api.types import PluginServerInterface

try:
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.default_flow_style = False
except ImportError:
    import yaml as _yaml


    class YAMLWrapper:
        @staticmethod
        def load(stream):
            return _yaml.safe_load(stream)

        @staticmethod
        def dump(data, stream):
            return _yaml.safe_dump(
                data, stream, allow_unicode=True, default_flow_style=False
            )


    yaml = YAMLWrapper()


class StyleManager:
    """风格管理器类

    管理自定义翻译风格文件，提供风格加载、切换和翻译查询功能。

    Attributes
    ----------
    server : PluginServerInterface
        MCDR 服务器接口
    style_dir : Path
        风格文件目录路径
    styles : Dict[str, Dict]
        已加载的所有风格，key 为风格名称，value 为翻译字典
    current_style : Optional[str]
        当前激活的风格名称
    """

    def __init__(self, server: PluginServerInterface, config=None):
        """初始化风格管理器

        Parameters
        ----------
        server : PluginServerInterface
            MCDR 服务器接口
        config : BotConfig, optional
            配置对象，用于读取和保存当前风格设置
        """
        self.server = server
        self.config = config
        self.style_dir = Path(server.get_data_folder()) / "style"
        self.styles: Dict[str, Dict] = {}
        self.current_style: Optional[str] = None

        # 冷却时间相关
        self.last_switch_time: float = 0.0
        self.cooldown: int = 0

        # 从配置中读取冷却时间设置
        if config:
            self.cooldown = config.get_keys(["style", "style_cooldown"], 0)

        # 确保风格目录存在
        self._ensure_style_directory()

        # 从配置中读取上次使用的风格
        if config:
            self.current_style = config.get_keys(["GUGUBot", "style"], None)

    def _ensure_style_directory(self) -> None:
        """确保风格目录存在，并复制默认样本文件（仅复制不存在的文件）"""
        # 确保风格目录存在
        if not self.style_dir.exists():
            self.style_dir.mkdir(parents=True, exist_ok=True)
            self.server.logger.info(f"[GUGUBot] 已创建风格目录: {self.style_dir}")

        # 复制样本文件到风格目录（只复制不存在的文件）
        try:
            # 所有风格示例文件列表
            style_files = [
                "normal.yml",
                "傲娇.yml",
                "雌小鬼.yml",
                "御姐.yml",
                "萝莉.yml",
                "波奇酱.yml",
                "病娇.yml",
                "中二病.yml",
            ]

            copied_count = 0
            for style_file in style_files:
                try:
                    # 检查目标文件是否已存在
                    sample_file = self.style_dir / style_file
                    if sample_file.exists():
                        self.server.logger.debug(
                            f"[GUGUBot] 风格文件已存在，跳过: {style_file}"
                        )
                        continue

                    # 获取插件包目录中的风格文件
                    with self.server.open_bundled_file(
                            f"gugubot/constant/{style_file}"
                    ) as f:
                        content = f.read().decode("utf-8")

                    # 写入样本文件
                    sample_file.write_text(content, encoding="utf-8")
                    copied_count += 1
                    self.server.logger.debug(f"[GUGUBot] 已复制风格文件: {style_file}")
                except Exception as e:
                    self.server.logger.debug(
                        f"[GUGUBot] 复制风格文件 {style_file} 失败: {e}"
                    )

            if copied_count > 0:
                self.server.logger.info(
                    f"[GUGUBot] 已复制 {copied_count} 个风格示例文件到: {self.style_dir}"
                )
        except Exception as e:
            self.server.logger.warning(f"[GUGUBot] 复制风格示例文件失败: {e}")

    def scan_styles(self) -> None:
        """扫描风格目录并加载所有 .yml 文件"""
        if not self.style_dir.exists():
            self.server.logger.warning(f"[GUGUBot] 风格目录不存在: {self.style_dir}")
            return

        # 清空现有风格
        self.styles.clear()

        # 扫描所有 .yml 文件
        for file_path in self.style_dir.glob("*.yml"):
            style_name = file_path.stem
            try:
                self.load_style(style_name)
                self.server.logger.info(f"[GUGUBot] 已加载风格: {style_name}")
            except Exception as e:
                self.server.logger.error(f"[GUGUBot] 加载风格 {style_name} 失败: {e}")

        # 如果配置中指定了风格，但该风格不存在，则重置
        if self.current_style and self.current_style not in self.styles:
            self.server.logger.warning(
                f"[GUGUBot] 配置的风格 {self.current_style} 不存在，已重置"
            )
            self.current_style = None
            self._save_current_style()
        elif self.current_style:
            # 如果有当前风格，注册到 MCDR
            self._register_style_to_mcdr(self.current_style)

        self.server.logger.info(f"[GUGUBot] 共加载 {len(self.styles)} 个风格")

    def load_style(self, style_name: str) -> bool:
        """加载单个风格文件

        Parameters
        ----------
        style_name : str
            风格名称（不含 .yml 扩展名）

        Returns
        -------
        bool
            是否加载成功
        """
        style_file = self.style_dir / f"{style_name}.yml"

        if not style_file.exists():
            self.server.logger.error(f"[GUGUBot] 风格文件不存在: {style_file}")
            return False

        try:
            with open(style_file, "r", encoding="utf-8") as f:
                style_data = yaml.load(f)

            if not isinstance(style_data, dict):
                self.server.logger.error(f"[GUGUBot] 风格文件格式错误: {style_file}")
                return False

            self.styles[style_name] = style_data
            return True
        except Exception as e:
            self.server.logger.error(f"[GUGUBot] 加载风格文件失败 {style_file}: {e}")
            return False

    def reload_styles(self) -> None:
        """重新加载所有风格文件"""
        self.scan_styles()

    def get_translation(self, key: str, **kwargs) -> Optional[str]:
        """获取翻译

        从当前激活的风格中查询翻译。如果当前风格中没有该翻译，返回 None。

        Parameters
        ----------
        key : str
            翻译键，支持点分隔的路径，如 "gugubot.system.help.name"
        **kwargs
            格式化参数

        Returns
        -------
        Optional[str]
            翻译文本，如果不存在则返回 None
        """
        if not self.current_style or self.current_style not in self.styles:
            return None

        # 从风格字典中查找翻译
        style_data = self.styles[self.current_style]
        keys = key.split(".")

        current = style_data
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return None

        # 如果找到的是字符串，进行格式化
        if isinstance(current, str):
            try:
                return current.format(**kwargs)
            except KeyError:
                # 如果格式化参数不匹配，返回原始字符串
                return current

        return None

    def can_switch_style(self) -> Tuple[bool, float]:
        """检查是否可以切换风格（冷却时间检查）

        Returns
        -------
        Tuple[bool, float]
            (是否可以切换, 剩余冷却时间)
        """
        if self.cooldown <= 0:
            return True, 0.0

        current_time = time.time()
        time_passed = current_time - self.last_switch_time

        if time_passed >= self.cooldown:
            return True, 0.0
        else:
            remaining = self.cooldown - time_passed
            return False, remaining

    def set_current_style(
            self, style_name: str, bypass_cooldown: bool = False
    ) -> Tuple[bool, str, float]:
        """切换当前风格

        Parameters
        ----------
        style_name : str
            风格名称
        bypass_cooldown : bool
            是否绕过冷却时间检查，默认为 False

        Returns
        -------
        Tuple[bool, str, float]
            (是否切换成功, 失败原因, 剩余冷却时间)
            失败原因: "cooldown" - 冷却中, "not_found" - 风格不存在, "" - 成功
        """
        # 检查冷却时间
        if not bypass_cooldown:
            can_switch, remaining = self.can_switch_style()
            if not can_switch:
                return False, "cooldown", remaining

        if style_name not in self.styles:
            self.server.logger.error(f"[GUGUBot] 风格不存在: {style_name}")
            return False, "not_found", 0.0

        self.current_style = style_name
        self.last_switch_time = time.time()

        # 注册风格翻译到 MCDR
        self._register_style_to_mcdr(style_name)

        self._save_current_style()
        self.server.logger.info(f"[GUGUBot] 已切换到风格: {style_name}")
        return True, "", 0.0

    def _register_style_to_mcdr(self, style_name: str) -> None:
        """将风格翻译注册到 MCDR 翻译系统

        这样可以让风格翻译直接通过 server.tr() 使用，提升性能。
        如果注册失败，会回退到通过 get_translation() 方法获取翻译。

        Parameters
        ----------
        style_name : str
            风格名称
        """
        if style_name not in self.styles:
            return

        try:
            # 获取当前语言
            language = self.server.get_mcdr_language()

            # 获取风格数据
            style_data = self.styles[style_name]

            # 使用 register_translation 注册风格翻译
            # mapping 是嵌套字典，直接传入风格数据即可
            self.server.register_translation(language, style_data)

            self.server.logger.info(
                f"[GUGUBot] 已将风格 {style_name} 注册到 MCDR 翻译系统"
            )
        except Exception as e:
            self.server.logger.debug(f"[GUGUBot] 无法将风格注册到 MCDR 翻译系统: {e}")

    def list_styles(self) -> List[str]:
        """列出所有可用风格

        Returns
        -------
        List[str]
            风格名称列表
        """
        return list(self.styles.keys())

    def get_current_style(self) -> Optional[str]:
        """获取当前风格名称

        Returns
        -------
        Optional[str]
            当前风格名称，None 表示未使用任何风格
        """
        return self.current_style

    def _save_current_style(self) -> None:
        """保存当前风格到配置文件"""
        if self.config:
            gugubot_config = self.config.get("GUGUBot", {})
            gugubot_config["style"] = self.current_style
            self.config["GUGUBot"] = gugubot_config
            self.config.save()
