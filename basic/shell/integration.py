"""Session-local Bash prompt metadata and command-free directory actions."""

import shlex

from .command_integration import command_prompt_setup

from common.i18n import tr


def directory_key(token: str) -> bytes:
    return f"\x1b[777;{int(token[:6], 16)}~".encode("ascii")


def directory_input(token: str, directory: str) -> bytes:
    if not directory.startswith("/") or any(ord(char) < 32 or ord(char) == 127 for char in directory):
        raise ValueError(tr("目录跳转请求无效"))
    # Match the original path action: clear unfinished input first.
    # Frame the path separately from the CR that refreshes the prompt. The
    # receiver ignores anything before RS and stops at US, preserving the
    # exact UTF-8 path without collecting a previous prompt-refresh CR.
    return b"\x15" + directory_key(token) + b"\x1e" + directory.encode("utf-8") + b"\x1f\r"


def bash_prompt_setup(token: str, command_names: tuple[str, ...] = (), extension: str = "") -> str:
    jump = "__pipeterminal_jump_" + token
    status = "__pipeterminal_status_" + token
    report = "__pipeterminal_prompt_" + token
    key = directory_key(token).decode("ascii").replace("\x1b", r"\e")
    binding = shlex.quote(f'"{key}":{jump}')
    ready = f"printf '\\033]777;PipeTerminalReady;{token}\\007'"
    hook = f'''{status}=$?
{report}() {{
    local previous=$1
{command_prompt_setup(token, command_names)}
{extension}
    if ! declare -F {jump} >/dev/null; then
        {jump}() {{
            local frame target
            IFS= read -r -s -d $'\\037' frame || return
            target=${{frame##*$'\\036'}}
            READLINE_LINE=
            READLINE_POINT=0
            if builtin cd -- "$target"; then
                printf '\\033]777;PipeTerminalJump;{token};%s\\007' "$PWD"
            else
                printf '\\033]777;PipeTerminalJumpFailed;{token};%s\\007' "$target"
            fi
        }}
        if builtin bind -m emacs-standard -x {binding}; then
            builtin bind -m vi-insert -x {binding} 2>/dev/null
            builtin bind -m vi-command -x {binding} 2>/dev/null
            {ready}
        fi
    fi
    printf '\\033]777;PipeTerminalCwd;{token};%s\\007' "$PWD"
    return "$previous"
}}
{report} "${{{status}}}"'''
    # Startup files still run normally. This affects only the login Bash's
    # environment; other shells retain their existing startup behavior.
    return (
        'case "${SHELL:-/bin/bash}" in */bash|bash) '
        f'export PROMPT_COMMAND="${{PROMPT_COMMAND:+${{PROMPT_COMMAND}};}}"{shlex.quote(hook)}; '
        'esac; '
    )
