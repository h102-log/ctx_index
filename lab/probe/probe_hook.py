#!/usr/bin/env python3
"""Schema probe hook: dumps the raw stdin payload of every hook event to a JSONL file.
Lab tooling for schema probing; not part of the deliverable."""
import json, os, sys, time

out = os.environ.get("PROBE_OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".run", "out", "payloads.jsonl")
raw = sys.stdin.buffer.read()
try:
    payload = json.loads(raw.decode("utf-8"))
except Exception as e:  # keep the raw bytes for inspection
    payload = {"_decode_error": repr(e), "_raw": raw[:500].decode("utf-8", "replace")}
rec = {"t": time.time(), "argv": sys.argv[1:], "payload": payload, "raw_len": len(raw),
       "env": {k: v for k, v in os.environ.items() if k.startswith(("CLAUDE_PROJECT_DIR", "CLAUDE_EFFORT", "CLAUDE_ENV_FILE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE"))}}
with open(out, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
ev = payload.get("hook_event_name") if isinstance(payload, dict) else None
if ev == "SessionStart" and os.environ.get("PROBE_INJECT", "1") == "1":
    marker = "PROBE-INJECT-MARKER source=%s 한글목차" % payload.get("source")
    sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": marker}}, ensure_ascii=False).encode("utf-8"))
sys.exit(0)
