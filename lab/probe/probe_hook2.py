#!/usr/bin/env python3
"""Schema probe hook v2: also records what the transcript already contains for the payload's prompt_id
at the moment the hook runs. Lab tooling; not part of the deliverable."""
import json, os, sys, time

out = os.environ.get("PROBE_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".run", "out", "payloads.jsonl")
raw = sys.stdin.buffer.read()
payload = json.loads(raw.decode("utf-8"))
rec = {"t": time.time(), "argv": sys.argv[1:], "payload": payload}
pid = payload.get("prompt_id")
tp = payload.get("transcript_path")
seen = []
size = None
try:
    size = os.path.getsize(tp)
    with open(tp, "rb") as f:
        for line in f:
            if pid and pid.encode() in line and b'"type":"user"' in line:
                e = json.loads(line.decode("utf-8"))
                c = (e.get("message") or {}).get("content")
                seen.append({"promptSource": e.get("promptSource"), "isMeta": e.get("isMeta"),
                             "content": c[:80] if isinstance(c, str) else "[%s]" % ",".join(b.get("type", "?") for b in c)})
except Exception as ex:
    seen = ["ERR %r" % (ex,)]
rec["tx_size"] = size
rec["tx_user_entries_for_pid"] = seen
with open(out, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
sys.exit(0)
