# 구독 사용량(claude -p "/usage")을 읽어 out\usage.log에 한 줄 덧붙인다.
# 시작 시각을 주면 그 뒤로 실험 세션(runs\ 아래에서 연 세션)이 쓴 토큰의 환산 비용도 출력한다.
# 사용: python usage.py [시작 시각, 예: 2026-11-27T13:13:51 (이 PC의 현지 시각)]
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
CLAUDE = pathlib.Path.home() / ".local" / "bin" / "claude.exe"
ENV = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "ANTHROPIC"))}
# analyze.py와 같은 단가(달러/100만 토큰)
PRICE = {"input_tokens": 4.0, "output_tokens": 20.0, "cache_read_input_tokens": 0.20, "cache_creation_input_tokens": 8.0}
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

now = datetime.datetime.now().astimezone()
# 훅이 꺼진 배선 확인용 폴더에서 실행해 ctx-index 기록을 남기지 않는다.
out = subprocess.run([str(CLAUDE), "-p", "/usage"], capture_output=True, cwd=HERE / "runs" / "wiring" / "A", env=ENV,
                     timeout=120, stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
weeks = re.findall(r"Current week \((.+?)\): (\d+)% used · resets (.+)", out)
line = "%s  %s" % (now.strftime("%Y-%m-%dT%H:%M:%S"), "  ".join("%s=%s%% (resets %s)" % w for w in weeks) or "no usage lines: " + out[:200])
print(line)
(HERE / "out").mkdir(exist_ok=True)
with open(HERE / "out" / "usage.log", "a", encoding="utf-8") as f:
    f.write(line + "\n")

if len(sys.argv) > 1:
    since = datetime.datetime.fromisoformat(sys.argv[1]).astimezone()
    seen = {}  # 메시지 ID -> (시각, usage). 분기 세션은 원래 세션의 기록을 복사해 갖고 있어 ID로 중복을 뺀다.
    for path in (pathlib.Path.home() / ".claude" / "projects").glob("C--ctxeval-runs-*/*.jsonl"):
        with open(path, encoding="utf-8") as f:
            for row in f:
                if '"usage"' not in row:
                    continue
                e = json.loads(row)
                m = e.get("message") or {}
                if m.get("usage") and m.get("id") and e.get("timestamp"):
                    seen.setdefault(m["id"], (datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")), m["usage"]))
    used = [u for t, u in seen.values() if since <= t <= now]
    tok = {k: sum(u.get(k, 0) for u in used) for k in PRICE}
    print("experiment since %s: api_calls=%d usd=%.2f %s" % (
        sys.argv[1], len(used), sum(tok[k] * PRICE[k] for k in PRICE) / 1e6, tok))
