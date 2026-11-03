#!/bin/sh
# Starts the judge service on a Unix socket that only the service and the group the API container joins (3000) can use.
# A candidate's program runs as another user without that group, so it cannot reach the service.
set -e
if [ "$#" -gt 0 ]; then exec "$@"; fi
mkdir -p /run/judge
chown root:3000 /run/judge
chmod 2770 /run/judge
rm -f /run/judge/judge.sock
umask 0117
exec python -m uvicorn judge_service:app --uds /run/judge/judge.sock --log-level warning
