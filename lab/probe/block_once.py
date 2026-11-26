#!/usr/bin/env python3
# Lab tooling: a second Stop hook that blocks the first stop of each prompt (to observe repeated Stop events).
import json, sys
p = json.loads(sys.stdin.buffer.read().decode("utf-8"))
if not p.get("stop_hook_active"):
    sys.stderr.write("probe: please continue once more")
    sys.exit(2)
sys.exit(0)
