#!/bin/bash
# Submit one instruction through the real API of a running scripts/demo.sh and follow it to the end.
# usage: scripts/demo_cli.sh "Pick up the red cube and place it in the storage box"
[ -n "$1" ] || { echo 'usage: demo_cli.sh "<instruction>"'; exit 2; }
API="http://127.0.0.1:${APP_PORT:-8000}"
TOKEN_DIR="${XDG_RUNTIME_DIR:-$HOME/.cache/munder_difflin}"; mkdir -p -m 700 "$TOKEN_DIR"
TOKEN_FILE="$TOKEN_DIR/munder_difflin_demo.token"
TOKEN="${MD_API_TOKEN:-$(cat "$TOKEN_FILE" 2>/dev/null)}"
[ -n "$TOKEN" ] || { echo "no token: is scripts/demo.sh running? (or export MD_API_TOKEN)"; exit 1; }
# token goes to curl via stdin (-H @-), never argv, so `ps` cannot show it
auth() { printf "Authorization: Bearer %s" "$TOKEN" | curl -s -m 10 -H @- -H "Content-Type: application/json" "$@"; }
BODY="$(python3 -c 'import json,sys; print(json.dumps({"instruction": sys.argv[1]}))' "$1")"
RESP="$(auth -X POST -d "$BODY" "$API/api/v1/tasks")"
ID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("task_id",""))' "$RESP" 2>/dev/null)"
[ -n "$ID" ] || { echo "submit failed: $RESP"; exit 1; }
echo "task $ID submitted"
last=""
for _ in $(seq 1 300); do
  D="$(auth "$API/api/v1/tasks/$ID")"
  S="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); ev=d.get("events",[]); print(d.get("status"), "|", (ev[-1]["stage"]+" "+ev[-1]["state"]+" "+ev[-1].get("message","")) if ev else "")' "$D" 2>/dev/null)"
  [ "$S" != "$last" ] && echo "$S" && last="$S"
  case "${S%% *}" in completed|failed|cancelled|needs_clarification|validated_no_executor) break;; esac
  sleep 1
done
echo "final: ${S%% *}"; [ "${S%% *}" = completed ]
