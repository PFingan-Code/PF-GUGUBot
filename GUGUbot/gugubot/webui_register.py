# -*- coding: utf-8 -*-
"""向 PF-MCDR-WebUI（guguwebui）注册插件页与侧边栏入口。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from mcdreforged.api.types import PluginServerInterface

PLUGIN_ID = "gugubot"
# 打包内的默认模板（随插件分发）
_BUNDLED_DEFAULT_HTML = "gugubot/config/defaults/gugubot_webui.html"
# 实际页面：MCDR 服务器根目录下 config/（与 guguwebui SafePath 白名单一致）
_CONFIG_WEBUI_REL = "config/gugubot/gugubot_webui.html"


def _read_plugin_version(server: PluginServerInterface) -> str:
    try:
        with server.open_bundled_file("mcdreforged.plugin.json") as f:
            data = json.loads(f.read().decode("utf-8"))
        return str(data.get("version", "unknown"))
    except Exception:
        return "unknown"


def _sync_webui_html_to_mcdr_config(server: PluginServerInterface) -> Optional[Path]:
    """
    每次加载插件时，用打包内的默认模板覆盖 MCDR 根目录下的
    config/gugubot/gugubot_webui.html（满足 guguwebui SafePath，且与内置页面一致）。
    """
    dest = Path(_CONFIG_WEBUI_REL)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        server.logger.error("[gugubot] 无法创建目录 %s: %s", dest.parent, e)
        return None

    try:
        with server.open_bundled_file(_BUNDLED_DEFAULT_HTML) as f:
            dest.write_bytes(f.read())
    except Exception as e:
        server.logger.error(
            "[gugubot] 无法写入 WebUI 页面 %s（从 %s 覆盖）: %s",
            dest,
            _BUNDLED_DEFAULT_HTML,
            e,
        )
        return None

    server.logger.debug("[gugubot] 已用内置模板覆盖 WebUI 页面: %s", dest)
    return dest


def make_api_handler(
    server: PluginServerInterface,
    get_config: Callable[[], Any],
    get_connector_manager: Callable[[], Any],
) -> Callable[..., Any]:
    """构建 WebUI 转发的 api_handler，约定见 PF-MCDR-WebUI docs/WebApi.md。"""

    def _api_handler(url_path: str, params: dict[str, Any]) -> dict[str, Any]:
        method = params.get("method", "GET")
        norm = (url_path or "").strip("/")
        if norm == "":
            norm = "status"

        if norm == "status" and method == "GET":
            cfg = get_config()
            cm = get_connector_manager()
            connectors: list[str] = []
            if cm is not None:
                try:
                    for c in getattr(cm, "connectors", []) or []:
                        connectors.append(
                            str(getattr(c, "source", None) or type(c).__name__)
                        )
                except Exception:
                    connectors = []
            is_main: Optional[bool] = None
            if cfg is not None:
                try:
                    is_main = cfg.get_keys(
                        ["connector", "minecraft_bridge", "is_main_server"], True
                    )
                except Exception:
                    is_main = None
            return {
                "ok": True,
                "plugin_id": PLUGIN_ID,
                "version": _read_plugin_version(server),
                "is_main_server": is_main,
                "connectors": connectors,
            }

        if norm == "reload" and method == "POST":
            try:
                server.reload_plugin(PLUGIN_ID)
                return {"ok": True, "message": f"{PLUGIN_ID} 重载成功"}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        return {
            "ok": False,
            "error": "not_found",
            "url_path": url_path,
            "method": method,
        }

    return _api_handler


def register_gugubot_webui_page(
    server: PluginServerInterface,
    gugubot_config: Any,
    connector_manager: Any,
) -> None:
    """
    若已加载 guguwebui，则注册插件网页（侧边栏「插件网页」）及 /api/plugin/gugubot/... 代理。
    HTML 路径使用 MCDR 的 config/gugubot/ 下文件，以满足 guguwebui 路径白名单。
    未安装 WebUI 时仅打调试日志，不影响 GUGUBot 运行。
    """
    webui = server.get_plugin_instance("guguwebui")
    if not webui or not hasattr(webui, "register_plugin_page"):
        server.logger.debug(
            "[gugubot] 未检测到 guguwebui（PF-MCDR-WebUI），跳过 WebUI 插件页注册"
        )
        return

    dest = _sync_webui_html_to_mcdr_config(server)
    if dest is None:
        return

    handler = make_api_handler(
        server,
        lambda: gugubot_config,
        lambda: connector_manager,
    )
    # 传入相对 config 目录的路径（见 PF-MCDR-WebUI 文档），须落在 ./config 下供 SafePath 通过
    webui.register_plugin_page(
        PLUGIN_ID,
        _CONFIG_WEBUI_REL,
        api_handler=handler,
    )
    server.logger.info(
        "[gugubot] 已注册 WebUI 插件页：侧边栏「插件网页」→ GUGUBot，页面 %s，API 前缀 /api/plugin/%s/",
        _CONFIG_WEBUI_REL,
        PLUGIN_ID,
    )
