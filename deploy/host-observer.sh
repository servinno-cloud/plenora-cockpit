#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

output=/run/plenora-cockpit/host.json
install -d -m 0755 -o root -g root /run/plenora-cockpit
temporary="${output}.tmp"

read -r root_total root_used root_free root_inode < <(df -B1 --output=size,used,avail,ipcent / | tail -1)
read -r backup_total backup_used backup_free backup_inode < <(df -B1 --output=size,used,avail,ipcent /var/backups/plenora/status.json | tail -1)
read -r load_1 load_5 load_15 _ < /proc/loadavg
uptime_seconds=${SECONDS}
if [[ -r /proc/uptime ]]; then read -r uptime_seconds _ < /proc/uptime; fi

printf '{"timestamp":"%s","uptime_seconds":%.0f,"root_total_bytes":%s,"root_used_bytes":%s,"root_free_bytes":%s,"root_inode_used_percent":%s,"backup_total_bytes":%s,"backup_used_bytes":%s,"backup_free_bytes":%s,"backup_inode_used_percent":%s,"load_1m":%s,"load_5m":%s,"load_15m":%s}\n' \
  "$(date --utc +%FT%TZ)" "$uptime_seconds" "$root_total" "$root_used" "$root_free" "${root_inode%%%}" \
  "$backup_total" "$backup_used" "$backup_free" "${backup_inode%%%}" "$load_1" "$load_5" "$load_15" > "$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$output"
