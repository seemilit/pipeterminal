"""Recognize a single ls target without executing or expanding shell syntax."""

import shlex
import re

from common.i18n import tr


def hovered_names(reference):
    """Bounded filename candidates around the hovered output, without listing I/O."""
    text, offset = reference.output, reference.offset
    separators = tuple(re.finditer(r"\s{2,}", text))
    left = max((match.end() for match in separators if match.end() <= offset), default=0)
    right = min((match.start() for match in separators if match.start() > offset), default=len(text))
    column = text[left:right].strip().rstrip("/@*|=")
    if column == reference.text:
        return (reference.text,)
    try:
        parts = shlex.split(column)
        if len(parts) == 1 and parts[0] == reference.text:
            return (reference.text,)
    except ValueError:
        pass
    boundaries = tuple(re.finditer(r"\s+", text))
    starts = [0] + [match.end() for match in boundaries if match.end() <= offset]
    ends = [match.start() for match in boundaries if match.start() > offset] + [len(text)]
    candidates = {reference.text, column}
    for start in starts[-10:]:
        for end in ends[:10]:
            value = text[start:end].strip().rstrip("/@*|=")
            try:
                parts = shlex.split(value)
                if len(parts) == 1:
                    candidates.add(parts[0])
            except ValueError:
                pass
            candidates.add(value)
    return tuple(sorted((name for name in candidates if name and "/" not in name and
                         len(name.encode("utf-8")) <= 255 and not any(ord(char) < 32 for char in name)),
                        key=len, reverse=True)[:32])


def listing_operand(command):
    if command is None:
        return None, True
    if not command:
        raise ValueError(tr("无法确定输出目录，请使用完整路径"))
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError as exc:
        raise ValueError(tr("无法确定输出目录，请使用完整路径")) from exc
    if any(token and all(char in ";&|<>()" for char in token) for token in tokens):
        raise ValueError(tr("无法确定输出目录，请使用完整路径"))
    if tokens[:1] == ["command"]:
        tokens = tokens[1:]
    if not tokens or tokens[0].rsplit("/", 1)[-1] not in {"ls", "ll", "la"}:
        return None, True
    operands, children, options = [], True, True
    values = {"--block-size", "--ignore", "--hide", "--width", "--tabsize", "--time-style", "--sort", "--format", "--quoting-style", "--color", "--indicator-style", "--time"}
    switches = {"--all", "--almost-all", "--author", "--escape", "--classify", "--file-type", "--full-time", "--group-directories-first", "--human-readable", "--inode", "--kibibytes", "--literal", "--numeric-uid-gid", "--quote-name", "--reverse", "--size", "--dereference", "--dereference-command-line", "--dereference-command-line-symlink-to-dir", "--zero", "--hyperlink", "--dired"}
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if options and token == "--":
            options = False
        elif options and token.startswith("--"):
            flag, separator, _value = token.partition("=")
            if flag == "--recursive":
                raise ValueError(tr("无法确定输出目录，请使用完整路径"))
            if flag == "--directory":
                children = False
            elif flag not in values and flag not in switches:
                raise ValueError(tr("无法确定输出目录，请使用完整路径"))
            if flag in values and not separator and flag != "--color":
                index += 1
                if index == len(tokens):
                    raise ValueError(tr("无法确定输出目录，请使用完整路径"))
        elif options and token.startswith("-") and token != "-":
            flags = token[1:]
            for position, flag in enumerate(flags):
                if flag == "R":
                    raise ValueError(tr("无法确定输出目录，请使用完整路径"))
                if flag == "d":
                    children = False
                if flag in "ITw":
                    if position == len(flags) - 1:
                        index += 1
                        if index == len(tokens):
                            raise ValueError(tr("无法确定输出目录，请使用完整路径"))
                    break
        else:
            operands.append(token)
        index += 1
    if len(operands) > 1 or any(any(char in operand for char in "$`*?[]{}") for operand in operands):
        raise ValueError(tr("无法确定输出目录，请使用完整路径"))
    if operands and operands[0].startswith("~") and any(char in command for char in "'\"\\"):
        raise ValueError(tr("无法确定输出目录，请使用完整路径"))
    return (operands[0] if operands else None), children
