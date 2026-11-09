# Terminal directory navigation

- Hold Ctrl and move over a path or filename in terminal output. A link underline is drawn only for that candidate; normal selection still works without Ctrl.
- Ctrl + left click verifies the remote path and uses a session-local Bash directory action. No `cd -- ...` command is inserted into the input line or command history. The existing lower server-file panel switches only after the shell confirms the directory change. Clicking a regular file uses its parent directory and selects the file in the list.
- The directory in standard `[user@host directory]#` and `user@host:directory$` prompts is clickable, including `~`. Commands following the prompt, and their automatically wrapped/history cells, are excluded from links. This does not remove literal underscore characters or ANSI underline attributes.
- Navigation follows the original connected-shell path action: verify the path, clear unfinished input, change directory silently, scroll to the bottom and focus the terminal. Client-side cursor/prompt heuristics, pending-input flags and a 150 ms timing gate do not block clicks. The Bash helper clears its Readline input buffer instead of rejecting an unfinished line. Typing, prompt redraws and automatic file-list refreshes do not cancel a clicked path that already has its own historical directory context. Disconnects and explicit file-browser navigation still invalidate pending activation. The action is handled by the interactive shell's Readline binding; it does not terminate foreground programs.
- A complete absolute-path output line, such as `pwd` output, is one clickable path including spaces, Chinese characters and wrapped rows. It does not require a recorded working directory. Command input remains excluded from links.

## Data and rendering

The engine records prompt and input provenance in cells without depending on Qt or SSH. Path hit testing uses the cell grid, including wide/combining characters and wrapped output.

Path recognition is independent of the command name: `ls`, `ll`, `ls -a` and other commands use the same output matching. Quoted/escaped filenames retain their spaces and punctuation. For bare names, the navigation worker compares the clicked output with actual entries in its recorded working directory, preferring the longest complete name and recognizing listing suffixes such as `/` and `@`. The resolved target is still verified before navigation. A missing-target error includes the attempted absolute path. Bare names printed from some other directory without a path or directory context cannot be resolved unambiguously; the resolver does not search unrelated directories or substitute the latest working directory.

Recorded command input now supplies the source of a single-target `ls`/`ll`/`la`
listing. For example, output from `ls /b` while the shell is in `/a` is matched
against `/b`, not against same-named entries in `/a`. Recursive or multi-target
listings and complex shell expressions require an explicit absolute path rather
than guessing a source folder. Command provenance is included in navigation
cache keys; the private page cache uses a previously verified mapping for such
relative references instead of guessing from cwd. Input-frame file actions and
terminal-menu actions are disabled when the active prompt belongs to a different
identity or an alternate screen is active.

Prompt events capture their displayed directory and enabled state when parsed, rather than reading a potentially overwritten screen row when the batch finishes. Repeated prompt events also retain accompanying full-directory metadata. This preserves associations when a Readline redraw and new prompt arrive in the same batch.

The connector prints a connection-specific OSC marker carrying the login shell PID before `exec` starts that shell. It also supplies a Bash `PROMPT_COMMAND` hook in this connection's environment. The hook emits a token-checked full `$PWD` immediately before each prompt. These stream-ordered records are saved against individual prompt contexts, so even several prompts delivered in one SSH batch keep their original directories. Historical prompt basenames and relative output paths use those saved absolute directories, never the latest directory. Up to 5,000 contexts are retained until disconnection.

The Bash hook registers a private Readline `bind -x` action. The client sends Ctrl+U before the action, followed by RS (`0x1e`), the exact UTF-8 target path, US (`0x1f`), and a final CR to refresh the prompt. The helper silently reads through US and extracts only the bytes after RS; a leftover CR before the frame cannot become part of the path. Newline-based path reading is not used. Client validation excludes control characters from directory names, so the frame delimiters cannot occur in the payload; meaningful spaces and Unicode in the path are preserved. The helper then clears `READLINE_LINE`/`READLINE_POINT`, changes the shell directory, and reports success. An empty-line submission refreshes the normal prompt. It writes no startup files, changes no user key bindings such as Tab, and places no generated command in shell history. Capability acknowledgement is required before sending the action. These changes take effect on a fresh connection. Other shells, or custom startup files replacing `PROMPT_COMMAND`, do not enable this Bash-specific silent action and receive a localized status message rather than having a command inserted into their input.

For prompts without inline directory metadata, an independent SFTP channel can still query `/proc/<pid>/cwd` on Linux. A fallback query must match the current prompt and displayed directory before it is recorded and cannot overwrite an inline directory record. A historical basename with no saved directory is not guessed. Nonstandard/multiline prompts are not automatically instrumented. Switching to another user/host prompt disables links until the original identity returns; this prevents resolving nested SSH paths against the outer server.

One navigation worker performs cancellable read-only path verification and listing. Connection generations discard stale results. No background task creates widgets, calls QPainter, activates a directory action, or opens the file panel. The main thread activates results only after an explicit click while connected, and applies the list and folder-tree selection after the server's success acknowledgement. An acknowledgement for an earlier, different target does not consume the latest target's pending snapshot. Failure acknowledgements include the requested path for the same reason. The file list and folder tree draw batches of up to 100 entries with an approximately 4 ms work budget, and pause batches briefly during terminal/command-entry typing. Filesystem permissions or a target disappearing can still cause the server to reject a directory change; the existing file list then remains intact.

Protocol references: [GNU Bash interactive prompt behavior](https://www.gnu.org/software/bash/manual/html_node/Interactive-Shell-Behavior.html), [GNU Bash bind/read builtins](https://www.gnu.org/s/bash/manual/html_node/Bash-Builtins.html).

## Optional strategy

The public `ClickPathPolicy` never loads folders on hover. Clicking starts a normal background read; the UI remains responsive while it loads.

An optional registry service named `terminal_path_policy` supplies `create_policy()`. The policy implements the Qt-free `PathPolicy` interface (`prefetch`, `get`, `put`, `clear`). The public consumer contains no premium imports or paid-version conditions.

The private `premium/terminal_acceleration/module.py` registers this service through the same ModuleLoader. It enables a 250 ms stable-hover prefetch and keeps up to eight directory snapshots for five seconds, skipping cache storage for listings over 10,000 entries. Hover caches data only; clicking promotes an in-progress request or displays a valid snapshot. Moving away cancels unwanted hover work. Disconnecting clears each terminal's cache. Removing the private package restores ordinary click loading automatically.

## Changed files and principal APIs

Public terminal package:
- `paths.py`: `PathReference`, `prompt_match`, `cell_text`, `reference_at`, `_output_spans` provide cell-based prompt/path matching, standalone absolute output paths and padding-aware wrapped text.
- `path_policy.py`: `PathPolicy` and the default `ClickPathPolicy` define the optional strategy boundary.
- `widget.py`: `pathHovered`, `pathActivated`, `enable_path_navigation` and hover/event-filter helpers implement Ctrl links and activation with local repaint.
- `engine/model.py`: cells add `input` and `context_id`; lines add prompt span/directory/context/input-boundary and path-enabled state.
- `engine/engine.py`: `note_input`, `shell_ready`, `path_links_enabled`, prompt counters and input provenance cover command echo and readiness.
- `engine/buffer.py`: writing/erasing prompt cells invalidates stale prompt hit areas.
- `engine/api.py`: the engine protocol declares the new input/readiness capabilities.

Public shell package:
- `runtime.py`: adds a random per-connection `shell_token`.
- `connector.py`: starts the existing login shell with a PID metadata marker and session-local Bash integration.
- `integration.py`: `bash_prompt_setup`, `directory_key`, `directory_input` build the prompt metadata hook and silent directory-action protocol.
- `session.py`: adds `inputQueued` and `shell_token()`; SSH read/write threading remains unchanged.
- `path_navigation.py`: `PathNavigation.metadata`, `_remember_directory`, `send_directory`, `hover`, `activate`, `cancel_activation`, `reset`, `shutdown` manage historical directory contexts, silent-action capability/acknowledgement, one worker and optional prefetch. `_ready` checks connection state only; obsolete `_input_pending`/`_input_time` fields were removed. `_reported_directory`, `_quiet_ready`, `_jump_snapshot` hold protocol state; `directory_changed` signals confirmed success.
- `page.py`: registry binding selects the strategy, `_jump_directory` requests the silent action and scrolls/focuses the terminal, `_show_directory` opens the shared lower file panel after confirmation; `eventFilter` briefly defers list/tree rendering during typing. Automatic file-list loading no longer cancels terminal path activation.
- `translations.py`: adds new status messages in the existing supported languages.

Public SFTP package:
- `backend.py`: extracts `read_directory` for reuse on an already-open worker channel.
- `navigation.py`: adds `DirectorySnapshot`, `read_shell_directory`, `read_path_snapshot` for read-only resolution and listings.
- `controller.py`: adds `use_snapshot` and optional initial snapshots without a redundant browse request.
- `workspace.py` and `dialog.py`: add `show_directory` and forward optional initial snapshots.
- `browser.py`: adds `select_file`, `defer_rendering` and bounded rendering batches.

Private package `premium/terminal_acceleration`:
- `__init__.py`: independent feature package marker.
- `module.py`: `get_module`/`create_provider` register the optional service without a sidebar item.
- `provider.py`: `PathPolicyProvider.create_policy` creates isolated `PrefetchPathPolicy` caches (`get`, `put`, `clear`).

This document is the only added documentation file. No configuration schema, database, workflow or transfer-task business rules changed.
