"""Localized client error summaries with original diagnostic details retained."""

import errno

from . import TranslatedText, tr


def error_message(error: Exception):
    args = getattr(error, "args", ())
    if args and isinstance(args[0], TranslatedText):
        return args[0]
    detail = str(error) or type(error).__name__
    name = type(error).__name__
    sources = {
        "AuthenticationException": "SSH 认证失败：{0}",
        "BadAuthenticationType": "SSH 认证失败：{0}",
        "PasswordRequiredException": "私钥需要密码：{0}",
        "BadHostKeyException": "服务器主机密钥不匹配：{0}",
        "NoValidConnectionsError": "无法连接服务器：{0}",
        "SSHException": "SSH 操作失败：{0}",
    }
    if name in sources:
        return tr(sources[name], detail)
    if isinstance(error, UnicodeError):
        return tr("文本编码错误：{0}", detail)
    if isinstance(error, TimeoutError):
        return tr("操作超时：{0}", detail)
    if isinstance(error, ConnectionAbortedError):
        return tr("操作已取消：{0}", detail)
    if isinstance(error, (EOFError, ConnectionResetError, BrokenPipeError)):
        return tr("连接意外关闭：{0}", detail)
    if isinstance(error, OSError):
        sources = {
            errno.ENOENT: "文件或目录不存在：{0}",
            errno.EACCES: "没有操作权限：{0}",
            errno.EPERM: "没有操作权限：{0}",
            errno.EEXIST: "目标已存在：{0}",
            errno.ENOSPC: "磁盘空间不足：{0}",
            errno.EROFS: "文件系统只读：{0}",
            errno.ECONNREFUSED: "无法连接服务器：{0}",
            errno.ENETUNREACH: "无法连接服务器：{0}",
            errno.EHOSTUNREACH: "无法连接服务器：{0}",
        }
        return tr(sources.get(error.errno, "文件操作失败：{0}"), detail)
    return tr("错误：{0}", detail)
