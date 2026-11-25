#!/usr/bin/env bash
#
# system_health.sh - basic health check for a Linux machine.
#
# Checks CPU, memory, disk usage and running processes. Anything over its
# threshold is logged as an ALERT to the console and to the log file.
# Exit code is 1 when there was at least one alert, so it can run from cron.

set -uo pipefail

CPU_THRESHOLD=80
MEM_THRESHOLD=80
DISK_THRESHOLD=80
PROC_THRESHOLD=500
REQUIRED_PROCS=""
LOG_FILE="./system_health.log"
INTERVAL=0

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

  -c PERCENT   CPU usage threshold (default $CPU_THRESHOLD)
  -m PERCENT   memory usage threshold (default $MEM_THRESHOLD)
  -d PERCENT   disk usage threshold, checked per filesystem (default $DISK_THRESHOLD)
  -p COUNT     max number of processes (default $PROC_THRESHOLD)
  -s NAMES     comma separated list of processes that must be running, e.g. sshd,cron
  -l FILE      log file (default $LOG_FILE)
  -i SECONDS   keep running and check every SECONDS
  -h           show this help
EOF
}

while getopts ":c:m:d:p:s:l:i:h" opt; do
    case "$opt" in
        c) CPU_THRESHOLD=$OPTARG ;;
        m) MEM_THRESHOLD=$OPTARG ;;
        d) DISK_THRESHOLD=$OPTARG ;;
        p) PROC_THRESHOLD=$OPTARG ;;
        s) REQUIRED_PROCS=$OPTARG ;;
        l) LOG_FILE=$OPTARG ;;
        i) INTERVAL=$OPTARG ;;
        h) usage; exit 0 ;;
        :) echo "option -$OPTARG needs a value" >&2; exit 2 ;;
        *) echo "unknown option -$OPTARG" >&2; usage >&2; exit 2 ;;
    esac
done

for value in "$CPU_THRESHOLD" "$MEM_THRESHOLD" "$DISK_THRESHOLD" "$PROC_THRESHOLD" "$INTERVAL"; do
    if [[ ! $value =~ ^[0-9]+$ ]]; then
        echo "not a whole number: $value" >&2
        exit 2
    fi
done

if [[ ! -r /proc/stat || ! -r /proc/meminfo ]]; then
    echo "this script needs a Linux /proc filesystem" >&2
    exit 2
fi

if ! touch "$LOG_FILE" 2>/dev/null; then
    echo "can't write to log file $LOG_FILE" >&2
    exit 2
fi

ALERTS=0

log() {
    local level=$1
    shift
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S') [$level] $*"
    echo "$line"
    echo "$line" >> "$LOG_FILE"
}

alert() {
    log ALERT "$@"
    ALERTS=$((ALERTS + 1))
}

# /proc/stat counters only ever go up, so take two samples a second apart
# and compare. Fields: user nice system idle iowait irq softirq steal
cpu_usage() {
    local a b i total=0
    read -ra a < <(grep '^cpu ' /proc/stat)
    sleep 1
    read -ra b < <(grep '^cpu ' /proc/stat)

    for i in 1 2 3 4 5 6 7 8; do
        total=$((total + b[i] - a[i]))
    done
    local idle=$(( (b[4] + b[5]) - (a[4] + a[5]) ))

    if (( total <= 0 )); then
        echo 0
    else
        echo $(( 100 * (total - idle) / total ))
    fi
}

check_cpu() {
    local usage
    usage=$(cpu_usage)
    if (( usage > CPU_THRESHOLD )); then
        alert "CPU usage is ${usage}% (threshold ${CPU_THRESHOLD}%)"
        ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu | head -n 6 | tee -a "$LOG_FILE"
    else
        log OK "CPU usage ${usage}%"
    fi
}

check_memory() {
    local total available used pct
    total=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
    available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
    used=$((total - available))
    pct=$((100 * used / total))

    local msg="memory usage ${pct}% ($((used / 1024)) MB of $((total / 1024)) MB)"
    if (( pct > MEM_THRESHOLD )); then
        alert "$msg (threshold ${MEM_THRESHOLD}%)"
        ps -eo pid,user,%mem,rss,comm --sort=-%mem | head -n 6 | tee -a "$LOG_FILE"
    else
        log OK "$msg"
    fi
}

check_disks() {
    local pct mount
    while read -r _ _ _ _ pct mount; do
        pct=${pct%\%}
        [[ $pct =~ ^[0-9]+$ ]] || continue
        if (( pct > DISK_THRESHOLD )); then
            alert "disk usage on $mount is ${pct}% (threshold ${DISK_THRESHOLD}%)"
        else
            log OK "disk usage on $mount ${pct}%"
        fi
    done < <(df -P -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | tail -n +2)
}

check_processes() {
    local count
    count=$(ps -e --no-headers | wc -l)
    if (( count > PROC_THRESHOLD )); then
        alert "$count processes running (threshold $PROC_THRESHOLD)"
    else
        log OK "$count processes running"
    fi

    local zombies
    zombies=$(ps -eo stat --no-headers | awk '/^Z/ {n++} END {print n + 0}')
    if (( zombies > 0 )); then
        log WARN "$zombies zombie process(es)"
    fi

    local names name
    IFS=',' read -ra names <<< "$REQUIRED_PROCS"
    for name in "${names[@]}"; do
        [[ -z $name ]] && continue
        if pgrep -x "$name" > /dev/null; then
            log OK "$name is running"
        else
            alert "$name is not running"
        fi
    done
}

run_checks() {
    ALERTS=0
    log INFO "checking $(uname -n)"
    check_cpu
    check_memory
    check_disks
    check_processes
    if (( ALERTS > 0 )); then
        log INFO "done, $ALERTS alert(s)"
    else
        log INFO "done, everything within limits"
    fi
}

if (( INTERVAL > 0 )); then
    while true; do
        run_checks
        sleep "$INTERVAL"
    done
fi

run_checks
[[ $ALERTS -eq 0 ]] || exit 1
