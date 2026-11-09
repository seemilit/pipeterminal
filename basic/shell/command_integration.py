"""Optional, session-local Bash command boundary and name-resolution metadata."""

import re
import shlex

from common.i18n import tr


def command_prompt_setup(token: str, names: tuple[str, ...]) -> str:
    names = tuple(sorted(set(names)))
    if not names:
        return ""
    if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None for name in names):
        raise ValueError(tr("监测命令名称无效"))
    initialized = "__pipeterminal_commands_" + token
    cached = "__pipeterminal_command_types_" + token
    return f'''
    if [[ ! ${{{initialized}+set}} ]]; then
        {initialized}=1
        if (( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4) )); then
            PS0="${{PS0-}}"$'\\033]777;PipeTerminalCommandStart;{token}\\007'
        fi
    fi
    builtin printf '\\033]777;PipeTerminalCommandDone;{token};%s\\007' "$previous"
    local pt_name pt_kind pt_value pt_encoded pt_record pt_snapshot=
    for pt_name in {shlex.join(names)}; do
        pt_kind=normal
        pt_value=
        if builtin declare -F "$pt_name" >/dev/null; then
            pt_kind=function
        fi
        if [[ ${{BASH_ALIASES[$pt_name]+set}} ]]; then
            [[ $pt_kind == function ]] && pt_kind=alias_function || pt_kind=alias
            pt_value=${{BASH_ALIASES[$pt_name]}}
        fi
        if (( ${{#pt_value}} > 512 )); then
            pt_kind=unknown
            pt_value=
        fi
        builtin printf -v pt_encoded '%q' "$pt_value"
        if (( ${{#pt_encoded}} > 2048 )); then
            pt_kind=unknown
            pt_encoded="''"
        fi
        builtin printf -v pt_record '\\033]777;PipeTerminalCommandType;{token};%s;%s;%s;end\\007' "$pt_name" "$pt_kind" "$pt_encoded"
        pt_snapshot+=$pt_record
    done
    if [[ $pt_snapshot != "${{{cached}-}}" ]]; then
        builtin printf '\\033]777;PipeTerminalCommandTypes;{token};begin\\007%s\\033]777;PipeTerminalCommandTypes;{token};end\\007' "$pt_snapshot"
        {cached}=$pt_snapshot
    fi
'''
