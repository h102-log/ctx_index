# 압축된 원래 세션을 질문마다 분기(--fork-session)해 claude -p로 묻는다. A와 B에 같은 명령을 쓴다.
# 사용: python ask.py r02 s02k [질문 이름 ...]   (원래 세션 ID는 runs\<run>\sessions.json에서 읽는다)
import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys

RUN, SETNAME, ONLY = sys.argv[1], sys.argv[2], sys.argv[3:]
HERE = pathlib.Path(__file__).parent
PARENTS = json.loads((HERE / "runs" / RUN / "sessions.json").read_text(encoding="utf-8"))
OUT = HERE / "out" / ("%s-%s" % (RUN, SETNAME))
CLAUDE = pathlib.Path.home() / ".local" / "bin" / "claude.exe"
# [의도] 이 스크립트를 띄운 Claude Code 세션의 환경 변수가 실험 세션에 섞이지 않게 한다.
ENV = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "ANTHROPIC"))}


def ask(job):
    q, cond = job
    dest = OUT / ("%s-%s.json" % (q.stem, cond))
    if dest.exists():
        return "%s %s skip (already done)" % (q.stem, cond)
    try:
        p = subprocess.run(
            [str(CLAUDE), "-p", "--resume", PARENTS[cond], "--fork-session", "--output-format", "json"],
            input=q.read_bytes(), capture_output=True, cwd=HERE / "runs" / RUN / cond, env=ENV, timeout=900)
        result = json.loads(p.stdout)
    except subprocess.TimeoutExpired:
        return "%s %s TIMEOUT" % (q.stem, cond)
    except ValueError:
        return "%s %s FAILED rc=%d %s" % (q.stem, cond, p.returncode, p.stderr.decode("utf-8", "replace")[-300:])
    if result.get("is_error"):
        return "%s %s ERROR %s" % (q.stem, cond, str(result.get("result"))[:300])
    dest.write_bytes(p.stdout)
    return "%s %s ok session=%s turns=%s denials=%d %ds" % (
        q.stem, cond, str(result.get("session_id"))[:8], result.get("num_turns"),
        len(result.get("permission_denials") or []), (result.get("duration_ms") or 0) // 1000)


OUT.mkdir(parents=True, exist_ok=True)
files = [q for q in sorted((HERE / "prompts" / SETNAME).glob("q*.txt")) if not ONLY or q.stem in ONLY]
jobs = [(q, cond) for q in files for cond in "AB"]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for line in pool.map(ask, jobs):
        print(line, flush=True)
