import requests
from mcdreforged.api.types import PluginServerInterface
from packaging import version


# 检查插件版本
def check_plugin_version(server: PluginServerInterface):
    async def check_plugin_version():
        try:
            response = requests.get(
                "https://api.github.com/repos/PFingan-Code/PF-GUGUBot/releases/latest"
            )
            if response.status_code != 200:
                server.logger.warning(
                    f"无法检查插件版本，网络代码: {response.status_code}"
                )
                return
            latest_version = response.json()["tag_name"].replace("v", "")
            current_version = str(server.get_self_metadata().version)
            if version.parse(latest_version) > version.parse(current_version):
                server.logger.info(
                    f"§e[PF-GUGUBot] §6有新版本可用: §b{latest_version}§6，当前版本: §b{current_version}"
                )
                server.logger.info(
                    "§e[PF-GUGUBot] §6请使用 §b!!MCDR plugin install -U -y gugubot §6来更新插件"
                )
            else:
                server.logger.info(
                    f"§e[PF-GUGUBot] §6已是最新版本: §b{current_version}"
                )
        except Exception as e:
            server.logger.warning(f"检查插件版本时出错: {e}")

    return check_plugin_version
