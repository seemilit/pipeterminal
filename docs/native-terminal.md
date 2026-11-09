# Native terminal foundation

## Current boundary

The drawing stage is independent of SSH and workflows. The native widget creates
only a viewport. Input emits bytes; it does not execute commands or echo a
simulated shell. Session integration supplies bytes to `feed()`.

The subsequent [Shell stage](shell.md) supplies SSH sessions using the same native
widget, opened from Configs in the bottom panel. Shell and Terminal remain
independent sibling packages but do not appear as standalone sidebar entries.
[Session logs](logs.md) are an optional registered service.

```
bytes -> ANSIParser -> TerminalEngine -> ScreenBuffer -> Renderer -> QPainter
```

`engine/api.py` defines the renderer-facing protocol for replacing the Python
engine with a C/C++ adapter. The engine imports no Qt. The renderer never parses
escape sequences or changes terminal cells. Widgets and engine feeds run on the
Qt GUI thread; the SSH reader delivers bytes through queued signals.

## Implemented

- Incremental UTF-8, CR/LF/backspace/tab, cursor movement, erase and insert/delete.
- Cell foreground/background, bold, italic, underline, inverse; 16/256 colors.
- Wide and continuation cells, combining marks, emoji modifiers, flags and ZWJ.
- Bounded scrollback; viewing history retains its anchor as output arrives.
- Dirty line identifiers, cursor-only blink updates, native selection/clipboard.
- IME commits and keyboard-to-terminal byte encoding.
- A small subset of alternate screen, DEC modes, OSC framing and true color.

Full terminal compatibility is not claimed. Mouse reporting, complete OSC/DCS,
history reflow on column resizing, and real vim/nano/top/htop/tmux acceptance are
later work. Unknown control strings are consumed rather than drawn as text.

## Removed Web chain

The old reference decoded SSH bytes in `ssh_terminal.py`, queued strings in the
Qt tab, then wrote through the Web adapter and JavaScript bridge. Input and PTY
size changes travelled back through the same bridge. Directory tracking also
used bridge metadata and path links.

The Web adapter, bundled JavaScript/CSS/HTML, channel imports and packaging
entries have been removed. The old desktop reference uses a small native-render
compatibility adapter; its SSH/SFTP/workflow code is otherwise unchanged. Native
hover path links are not retained in this drawing foundation.

The Qt dependency is Essentials; no browser renderer is loaded. The archived
desktop source/package configuration now depends on the public native package.

## Offline verification

Engine state and headless Qt viewport tests use temporary in-memory data, without
server configuration writes, SSH connections or project builds.

```
python -m unittest discover -s tests -p '*terminal*.py' -v
```

References: https://doc.qt.io/qt-6/qabstractscrollarea.html,
https://wcwidth.readthedocs.io/en/latest/specs.html.
