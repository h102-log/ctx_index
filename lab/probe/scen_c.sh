#!/bin/bash
# Capture "c": a Stop hook that blocks once (two Stop events for one prompt), then
# --resume / --continue / --fork-session. One CLI process per step, so it is a shell
# script rather than a drive.py scenario.
#
#   PROBE_OUT=<file> ./scen_c.sh [v1]      (v1 = full-event probe, default = probe_hook2)
P="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
R="${CTX_LAB_RUN:-$P/.run}"
if [ "$1" = "v1" ]; then S=probe-settings.json; B=probe-settings-block.json
else S=probe-settings2.json; B=probe-settings2-block.json; fi
export PROBE_OUT="${PROBE_OUT:-$R/out/c/payloads.jsonl}"
mkdir -p "$(dirname "$PROBE_OUT")"
cd "$R/proj" || exit 1
run() { timeout 120 "$P/run_cli.sh" "$@" --output-format json < /dev/null; }
sid() { python3 -c "import json,sys; print(json.load(sys.stdin)['session_id'])"; }

run -p "C0 스톱 훅이 한 번 막는 케이스" --settings "$R/settings/$B" > /dev/null
SID=$(run -p "C1 새 세션 첫 질문" --settings "$R/settings/$S" | sid)
echo "session: $SID"
run -p "C2 resume 후 질문" --resume "$SID" --settings "$R/settings/$S" > /dev/null
run -p "C3 continue 후 질문" --continue --settings "$R/settings/$S" > /dev/null
echo "fork: $(run -p "C4 fork 후 질문" --resume "$SID" --fork-session --settings "$R/settings/$S" | sid)"
