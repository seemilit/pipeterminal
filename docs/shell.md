# SSH Shell integration

This task followed the completed native drawing foundation. It adds an independent
`basic/shell` package. Shell is the umbrella for SSH/SFTP capabilities; this
stage provides SSH sessions. The separate [SFTP stage](sftp.md) now supplies
file browsing and transfers through the current connection.

Connection, Shell and Terminal remain sibling packages. Shell registers with
`sidebar=False`; the native Terminal component has no standalone page. The
configuration page obtains the Shell page factory from the registry and presents
its widget in the shared bottom panel. MainWindow only handles generic panel
signals and does not import feature packages.

## Use

Open Configs and enter server information, even without creating a named record
first. The address and manually entered port share a row. Save prompts for a name
for a new draft. Click Connect on the top toolbar to open the server's Shell tab in the
bottom panel; a new or edited configuration must save successfully first. Cancel
or save failure prevents the connection and default command execution.

Double-clicking a saved configuration in the left directory uses the same
connection entry point and save guard. A single click selects it for editing.
Double-clicking anywhere in an access-path row also connects that row, including
its labels, checkboxes, inputs, Connect button and empty space. Delete is excluded
and removes the row immediately on a single click. Single-click Connect waits
for the system double-click interval to avoid a duplicate connection.
Connection opens a small bottom-right pane and leaves the editor visible above;
the vertical divider adjusts the pane's height. The pane remains available when
switching sidebar modules until hidden or its last tab is closed.

The Shell header shows the target and status on the left and compact actions on
the right. The native viewport uses a dark navy background and light text, scoped
to Shell; other pages retain the application theme. A command bar below supports
Enter/Send, Interrupt (Ctrl+C), and local Clear. Clicking Terminal mode hides the
sidebar, editor and application toolbar so the terminal fills the workspace.
Back to editor restores their previous visibility and both splitter sizes.
Connecting normally still opens only the small bottom-right pane. Switching
session tabs retains the mode; closing the last tab, hiding the interaction panel,
switching to another main page or resetting the layout exits it. Mode captions
use the selected language. Viewport resizing uses the existing `resize_pty` path.
Terminal mode also creates the optional [server monitoring sidebar](monitor.md),
with system/resources, disk usage and the top 12 processes, through the registry.
Close tab disconnects and disposes
that configuration's Shell page. File transfer opens the SFTP browser;
upload/download opens its task list.

The Logs button opens the current connection attempt's saved transcript without
leaving terminal mode. It remains available after disconnecting and follows the
new transcript after reconnecting. See [Session logs](logs.md).

Sizing follows the retained original desktop layout: Cascadia Mono at 10 pt,
an 8 px terminal inset, header margins of 6/5/6/5, command-bar margins of
4/5/4/5, and adjoining compact controls. The initial editor/panel splitter sizes
are 370/380 and adapt to the available window height; the lower panel has a
160 px minimum. The final 32 px entry expands/collapses the inline server file
list. It shares the [SFTP workspace](sftp.md) with the popup and its task list;
the list stays hidden until explicitly opened and collapses on disconnect.

The application toolbar follows the original left/right arrangement. File
operations stay on the left; password visibility, Connect, interaction-panel
visibility and Run are on the right. Version history sits above the editor on
the right and now opens saved [configuration versions](history.md). Run is
disabled until an execution feature supplies its handler.
Sidebar visibility and Reset Layout remain in the toolbar's right-click menu.
The buttons, navigation rows, cards and text fields use the original compact
dimensions with the current theme colors. Connection cards preserve the new
combined address/port row and omit the removed inline hint and help button.
Shell tabs have a close button using the same disposal path as Close tab in the
header. A disabled `+` entry reserves the original new-session position.

The bottom panel stays hidden at startup and after Reset Layout. Opening Configs,
editing fields and saving do not show it. Existing Shell tabs are reused for the
same configuration. No connection starts at application startup or merely when
opening the configuration page. Choose an optional saved directory in the Shell
controls. Defaults marked for command execution are used only when connecting
to their selected directory. Bound Shell Connect/Reconnect buttons also route
through the configuration's saved-data guard.

Password and private-key authentication follow the saved authentication mode.
Initial unknown host keys require explicit fingerprint confirmation. Changed
recorded keys are rejected. Host-key records use the standard `conf/known_hosts`
format; server records remain `.server.json`.

```
Paramiko Channel.recv -> bounded byte queue -> Qt timer (16 ms)
 -> NativeTerminalWidget.feed -> engine -> dirty rows -> QPainter

key / IME / paste -> terminal byte signal -> bounded writer queue
 -> Channel.send (partial writes handled by worker)

viewport resize -> grid resize -> size signal -> worker -> resize_pty
```

Qt widgets and screen updates stay on the GUI thread. Authentication, directory
resolution, receive/send, resize requests and channel closure run in workers.
Input has a bounded queue and a 1 MB per-paste limit. Incoming data is buffered
up to 1 MB and delivered in batches of at most 64 KiB per GUI frame.

`SSHSession.attach_channel()` accepts an already-open Paramiko channel. The new
session must be its exclusive reader. Borrowed channels are not closed by the
session; owned channels and clients are closed on disconnect/application exit.

When the optional log module is registered, each connection attempt also opens
a dated `.log` file. Remote bytes are observed in the SSH reader; credentials
and outgoing input are not logged by the client. The log module owns background
writing, the viewer and exit flushing. See [Session logs](logs.md).

## Verification and limits

Tests use fake channels and a temporary local Paramiko server, covering actual
SSH byte transport, input, PTY resize, GUI thread delivery, EOF ordering, host-key
rejection/change, and page activation without connecting. They write no user
server profiles and remove temporary trust records afterwards.

These are not real Linux application acceptance tests. vim/nano/top/htop/tmux,
sudo, nested SSH, shell-specific startup scripts and every terminal protocol mode
still require testing against an explicitly chosen Linux server.

Reference: https://docs.paramiko.org/en/stable/api/channel.html.
