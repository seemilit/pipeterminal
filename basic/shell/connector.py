"""Paramiko authentication and PTY creation, executed only by a worker."""

import posixpath
import shlex
import socket
import stat

from .host_keys import install_host_key_policy
from .integration import bash_prompt_setup

from common.i18n import tr


def open_channel(run, profile, known_hosts, confirm):
    import paramiko

    client = paramiko.SSHClient()
    run.client = client
    install_host_key_policy(client, known_hosts, confirm)
    configuration = profile.configuration
    arguments = {
        "hostname": configuration.ip_address, "port": configuration.port,
        "username": configuration.username, "timeout": 20, "auth_timeout": 20,
        "banner_timeout": 20, "allow_agent": False, "look_for_keys": False,
    }
    if configuration.auth_method == "PASSWORD":
        if configuration.password:
            arguments["password"] = configuration.password
    else:
        arguments["key_filename"] = str(profile.key_path())
    client.connect(**arguments)
    if run.stop.is_set():
        raise ConnectionAbortedError(tr("连接已取消"))
    transport = client.get_transport()
    transport.set_keepalive(30)
    try:
        transport.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (AttributeError, OSError):
        pass
    columns, rows = run.size
    directory = resolve_directory(client, profile.directory) if profile.directory else None
    channel = transport.open_session(timeout=20)
    run.channel = channel
    channel.get_pty(term="xterm-256color", width=columns, height=rows)
    startup = f"cd -- {shlex.quote(directory)} || exit; " if directory else ""
    extension = run.prompt_extension(run.shell_token) if run.prompt_extension is not None else ""
    startup += bash_prompt_setup(run.shell_token, run.command_names, extension)
    # exec preserves this PID for read-only /proc cwd queries on Linux.
    # Nothing is written to the remote shell's configuration or history.
    startup += (
        f"printf '\\033]777;PipeTerminalShell;{run.shell_token};%s\\007' \"$$\"; "
        'exec "${SHELL:-/bin/bash}" -l'
    )
    channel.exec_command("exec /bin/sh -c " + shlex.quote(startup))
    if profile.command and not run.stop.is_set():
        channel.sendall((profile.command.rstrip("\r\n") + "\n").encode("utf-8"))
    channel.settimeout(0.2)
    run.applied_size = (columns, rows)
    return channel


def resolve_directory(client, value: str) -> str:
    requested = value.strip().replace("\\", "/")
    sftp = client.open_sftp()
    try:
        home = sftp.normalize(".")
        if requested == "~":
            path = home
        elif requested.startswith("~/"):
            path = posixpath.join(home, requested[2:])
        else:
            path = posixpath.normpath(requested if requested.startswith("/") else "/" + requested)
        if not stat.S_ISDIR(sftp.stat(path).st_mode):
            raise ValueError(tr("服务器路径不是目录"))
        return path
    finally:
        sftp.close()
