# Session logs

The independent `basic/log` package registers a sidebar page and a small logging
service through `module.py`. The loader creates the service once; the viewer is
created only on the first click. Startup creates no log directories, writers or
network connections. Removing the package before restarting removes its menu
and service; Shell continues without session logging.

## Storage and use

Every Shell connection attempt creates one UTF-8 file under:

```
conf/.logs/YYYYMMDD/shell_<configuration-name>_<time>_<unique-id>.log
```

The records contain timestamps, connection/disconnection status, connection
errors and remote output. Incremental decoding handles UTF-8 split between SSH
reads. ANSI colors, cursor sequences and control strings are filtered out.
Carriage returns become line breaks for readable progress output. This is an
output transcript, not a reconstruction of the terminal screen.

Session records also include the target user/host/port and initial directory.
The Shell header's Logs button opens the current or most recent connection
attempt in a separate, read-only window. That window stays pinned to its log,
including after disconnection; a reconnect creates a new log. It uses the same
bounded asynchronous preview as the main Logs module.

Authentication credentials and outgoing keyboard/paste bytes are not sent to
the log writer. Remote output is recorded verbatim after control filtering, so
anything echoed or printed by the server is included.

Open Logs to see the dated files in the directory panel. Select a file to read
it; the visible page refreshes once per second and has a manual Refresh button.
Scrolling up preserves the viewing position; staying at the bottom follows new
output. The preview reads at most the last 4 MB asynchronously; the complete log
file is preserved. Logs are read-only. The existing Delete toolbar action is
enabled only after a writer has closed and asks for confirmation.

Configuration operations create dated `configuration_operations_*.log` files;
history snapshot/deletion actions create `history_operations_*.log` files. The
configuration records cover create, save, copy, rename, delete and restoration,
including success/failure and changed field names. Field values and passwords
are excluded. Failure metadata records exception types. These files are visible
in the main Logs directory list and share the background writer and exit flush.
Write failures update the Shell log button or configuration status message.

## Producer API and lifetime

`ModuleRegistry.get_service("log")` returns the optional service. Producers use
`open_session(category, name)`, then `writer.output(bytes)` and
`writer.event(kind, message)`. No Shell import of the log package is required.
Future workflow producers can use the same service.

Output is observed in the SSH reader, before the GUI delivery queue. A bounded
writer queue and a separate worker handle filtering and file writes. Output
backpressure stays on the reader thread; status event enqueueing and `close()`
do not block the GUI. An event rejected by a full queue sets `writer.error`.
Filesystem errors also set `writer.error`; a failed writer stops accepting data.

`register_producer(stop)` supplies a shutdown callback. On application exit the
service stops producers, closes writers and waits up to three seconds in total
for accepted records to be flushed. The files stay within the configured log
root, and active files are protected from deletion through the viewer.
`unregister_producer(stop)` removes a callback when a configuration's Shell widget
is disposed after deleting that configuration.

This stage has been checked by source review only. No new log tests, application
startup, build or deployment were run.
