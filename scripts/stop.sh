#!/bin/bash
# Stop all Spendly services started by start.sh

cd "$(dirname "$0")/.."
LOGS="$(pwd)/logs"

stopped=0

for pidfile in "$LOGS"/*.pid; do
    [ -f "$pidfile" ] || continue
    name="$(basename "$pidfile" .pid)"
    pid="$(cat "$pidfile")"

    if kill -0 "$pid" 2>/dev/null; then
        # Kill the entire process group (catches child processes like uvicorn, npm, ollama)
        pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
        if [ -n "$pgid" ] && [ "$pgid" != "0" ]; then
            kill -- -"$pgid" 2>/dev/null
        else
            kill "$pid" 2>/dev/null
        fi

        # Wait up to 5s for the process to actually die
        for i in $(seq 1 10); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done

        if kill -0 "$pid" 2>/dev/null; then
            echo "Force-killing $name (PID $pid)"
            kill -9 -- -"$pgid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
        else
            echo "Stopped $name (PID $pid)"
        fi
        stopped=$((stopped + 1))
    else
        echo "$name (PID $pid) was not running"
    fi

    rm -f "$pidfile"
done

# Fallback: free ports that are still bound (5173–5180 covers Vite's auto-increment range)
for port in 8000 5173 5174 5175 5176 5177 5178 5179 5180; do
    pid_on_port="$(lsof -ti tcp:"$port" 2>/dev/null)"
    if [ -n "$pid_on_port" ]; then
        echo "Port $port still in use by PID $pid_on_port — killing"
        kill "$pid_on_port" 2>/dev/null
        sleep 0.5
        kill -0 "$pid_on_port" 2>/dev/null && kill -9 "$pid_on_port" 2>/dev/null
    fi
done

[ "$stopped" -eq 0 ] && echo "No services were running."
