#!/usr/bin/env python3
"""Print context around byte-pattern matches in the Claude Code binary (schema probing only)."""
import mmap, os, re, shutil, sys

BIN = os.environ.get("CLAUDE_BIN") or os.path.realpath(shutil.which("claude") or "claude")

def main():
    pat = sys.argv[1].encode("utf-8")
    before = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    after = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    start_at = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    with open(BIN, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        n = 0
        for m in re.finditer(pat, mm):
            if m.start() < start_at:
                continue
            s = max(0, m.start() - before)
            e = min(len(mm), m.end() + after)
            chunk = mm[s:e].decode("utf-8", "replace")
            print(f"===== @{m.start()} =====")
            print(chunk)
            print()
            n += 1
            if n >= limit:
                break
        print(f"[shown {n}]")

main()
