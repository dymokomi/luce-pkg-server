#!/usr/bin/env bash
# Keeps the month's network transfer inside the instance's included allowance by
# shaping egress harder as the budget is consumed. Run every few minutes by
# luce-egress-budget.timer. State survives reboots; counters reset each calendar month.
set -euo pipefail

BUDGET_GIB=${LUCE_EGRESS_BUDGET_GIB:-2800}   # the plan includes 3 TB; keep a margin
STATE=/var/lib/luce-egress
IFACE=${LUCE_EGRESS_IFACE:-$(ip -o route show default | awk '{print $5; exit}')}
[[ -n "$IFACE" ]] || { echo "no default interface" >&2; exit 1; }

mkdir -p "$STATE"
month=$(date -u +%Y-%m)
read -r saved_month used last < <(cat "$STATE/usage" 2>/dev/null || echo "$month 0 0")
# Lightsail counts inbound and outbound transfer against the allowance.
now=$(( $(cat "/sys/class/net/$IFACE/statistics/tx_bytes") + $(cat "/sys/class/net/$IFACE/statistics/rx_bytes") ))
[[ "$saved_month" == "$month" ]] || used=0
# A counter smaller than last time means the interface counters restarted (reboot).
if (( now >= last )); then used=$(( used + now - last )); else used=$(( used + now )); fi
printf '%s %s %s\n' "$month" "$used" "$now" > "$STATE/usage.new"
mv "$STATE/usage.new" "$STATE/usage"

percent=$(( used * 100 / (BUDGET_GIB * 1024 * 1024 * 1024) ))
if   (( percent >= 97 )); then rate=256kbit
elif (( percent >= 90 )); then rate=1mbit
elif (( percent >= 70 )); then rate=20mbit
else                           rate=200mbit
fi
tc qdisc replace dev "$IFACE" root cake bandwidth "$rate" 2>/dev/null \
  || tc qdisc replace dev "$IFACE" root tbf rate "$rate" burst 256kb latency 400ms
printf 'month=%s used_gib=%s percent=%s rate=%s iface=%s\n' "$month" $(( used / 1073741824 )) "$percent" "$rate" "$IFACE"
