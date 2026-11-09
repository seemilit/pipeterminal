# Terminal-mode server sidebar

`basic/monitor` is an independent feature registered through `module.py` with
`sidebar=False`. Shell requests its page factory from the registry when the
visible terminal first enters terminal mode. No monitoring UI, timer or SSH
queries run during application startup. Removing the monitor package before
restarting leaves Shell usable without the status sidebar.

The panel follows the original layout and includes:

- OS, kernel, uptime and system load.
- CPU, memory and swap progress bars.
- Disk mounts, used/total space and usage percentage.
- The top 12 processes by CPU, with service names, ports, CPU and memory usage.
- PID and command tooltips, and the last update time.

The default width is 275 px, adjustable between 220 and 400 px. It appears only
in terminal mode and is hidden again when returning to editing. All labels and
captions support the existing six application languages. Server-provided values
and process names are retained as received.

`SSHSession.command_runner()` captures the current connection's transport and
stop token on the GUI thread. Each refresh opens its own non-PTY SSH channel in a
worker, drains stdout and stderr, and closes only that auxiliary channel. The
terminal's PTY channel is not used for monitoring commands or responses.

Visible, connected panels refresh every three seconds, with one request in
flight at a time. Hiding the panel, changing tabs, disconnecting, reconnecting or
closing it cancels the current request. Generation checks discard stale results.
After the first successful sample, the footer shows a stable refresh interval
instead of an advancing clock or alternating sampling message. Hover over it
to see the last successful update date and time; connection and collection errors
remain visible. The existing six UI languages are supported.
A request has a ten-second deadline, a channel-close watchdog and a combined
256 KiB output limit; channel opening has a five-second timeout. Cancellation
while opening a channel may wait for that bounded timeout.

Collection currently targets Linux and reads `/proc`, OS release metadata,
`uname`, `df`, `ps` and `ss`. CPU usage needs two snapshots; the first says
sampling. Guest CPU counters are not counted twice. RAM uses MemAvailable where
present; older systems use an estimate from the available free/cache counters.
Missing optional data is shown as unknown or an empty list. Port attribution
depends on `ss` availability and the SSH user's permissions. Process percentages
come from `ps` and need not match a single refresh interval's CPU percentage.

Snapshots and panel width are kept in memory. No server profiles or monitoring
files are saved. This stage provides read-only monitoring, without the old
process restart/termination actions.

No application startup, project build, tests or real-server acceptance were run
for this stage. Real Linux distributions and SSH server channel limits remain
to be checked with the user's test servers.

References: [Paramiko channels](https://docs.paramiko.org/en/stable/api/channel.html),
[Linux /proc](https://www.kernel.org/doc/html/latest/filesystems/proc.html).
