"""Configuration-owned help content passed to the shared help component."""

from common.i18n import tr


def access_path_help_text() -> str:
    return (
        tr("目录：服务器上的文件夹，例如 /var/log。")
        + "\n\n" + tr("默认路径：普通连接时优先进入这里，只能选一个。")
        + "\n\n" + tr("执行命令：勾选后自动运行右侧命令，例如 pwd；命令可留空。")
        + "\n\n" + tr("直接连接：进入这一行的目录，连接前先保存配置。")
    )
