#!/usr/bin/env bash
# Notices when Carrel is down, and when the disk is about to take Reeve with it.
#
# There is no alerting here — no email, no Slack, no pager. This deployment has
# no mail sender, and a watchdog that pretends to notify somebody is worse than
# one that plainly does not. What it does instead is the half that works without
# infrastructure: recover automatically, and leave a record you can read.
#
#   tail ~/carrel/watchdog.log
#
# Install:
#   chmod +x ~/carrel/deploy/watchdog.sh
#   ( crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/carrel/deploy/watchdog.sh >> $HOME/carrel/watchdog.log 2>&1" ) | crontab -

set -uo pipefail   # deliberately not -e: a failing check must be handled, not fatal

URL="https://carrel.reeve.co.in/api/health"
STAMP="$(date -uIs)"

# ── Disk ────────────────────────────────────────────────────────────────────
# Checked first and reported even when everything else is fine, because this is
# the failure that takes down the *other* service on this box. Carrel shares a
# 6GB volume with the production MCP server; filling it stops Reeve too.
USED=$(df / | awk 'NR==2 {gsub("%","",$5); print $5}')
if [ "${USED:-0}" -ge 90 ]; then
    echo "$STAMP DISK CRITICAL: ${USED}% used — Reeve is on this volume too"
    # Reclaim what is safe to reclaim without touching any running container.
    docker image prune -f >/dev/null 2>&1
    docker builder prune -f >/dev/null 2>&1
    journalctl --vacuum-size=50M >/dev/null 2>&1
    echo "$STAMP pruned; now $(df / | awk 'NR==2 {print $5}') used"
elif [ "${USED:-0}" -ge 80 ]; then
    echo "$STAMP disk warning: ${USED}% used"
fi

# ── Health ──────────────────────────────────────────────────────────────────
CODE=$(curl -s -o /tmp/health.json -w "%{http_code}" --max-time 20 "$URL" || echo "000")

if [ "$CODE" = "200" ]; then
    # Quiet on success. A watchdog that logs every five minutes buries the one
    # line that mattered under three hundred that did not.
    exit 0
fi

echo "$STAMP UNHEALTHY: $URL returned $CODE"
[ -s /tmp/health.json ] && echo "$STAMP body: $(head -c 300 /tmp/health.json)"

# One restart attempt, then stop. If restarting fixed it, say so. If it did not,
# restarting again every five minutes turns a broken service into a crash loop
# and destroys the log that would explain why.
echo "$STAMP restarting carrel-api"
docker restart carrel-api >/dev/null 2>&1
sleep 25

RECHECK=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$URL" || echo "000")
if [ "$RECHECK" = "200" ]; then
    echo "$STAMP recovered after restart"
else
    echo "$STAMP STILL UNHEALTHY after restart ($RECHECK) — needs a human"
    echo "$STAMP last container logs:"
    docker logs --tail 20 carrel-api 2>&1 | sed "s/^/$STAMP   /"
fi
