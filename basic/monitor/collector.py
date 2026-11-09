"""Read-only Linux statistics command, following the original panel's fields."""

STATUS_COMMAND = r"""export LC_ALL=C;
if [ ! -r /proc/stat ] || [ ! -r /proc/meminfo ]; then
    printf 'PT_MONITOR_UNSUPPORTED\n' >&2; exit 1;
fi;
printf 'SYSTEM ';
awk -F= '$1=="PRETTY_NAME" {value=substr($0,index($0,"=")+1); gsub(/^"|"$/,"",value); print value; found=1; exit} END {if(!found) print "Linux"}' /etc/os-release 2>/dev/null;
printf 'KERNEL '; uname -srmo 2>/dev/null || uname -a;
printf 'UPTIME '; cut -d. -f1 /proc/uptime;
printf 'LOAD '; awk '{print $1, $2, $3}' /proc/loadavg;
grep '^cpu ' /proc/stat | head -n 1;
grep -E '^(MemTotal|MemAvailable|MemFree|Buffers|Cached|SReclaimable|Shmem|SwapTotal|SwapFree):' /proc/meminfo;
printf 'DF_BEGIN\n'; df -Pk 2>/dev/null;
printf 'PS_BEGIN\n'; ps -ww -eo pid=,pcpu=,pmem=,comm=,args= --sort=-pcpu 2>/dev/null | head -n 12 |
while IFS= read -r process; do
    set -f; set -- $process; pid=$1;
    IFS= read -r identity < "/proc/$pid/stat" 2>/dev/null || continue;
    identity=${identity##*) }; set -- $identity;
    [ "$1" != Z ] || continue;
    printf 'PT_PROCESS %s %s\n' "${20}" "$process";
done;
printf 'PORT_BEGIN\n'; ss -H -lntup 2>/dev/null || true;
"""
