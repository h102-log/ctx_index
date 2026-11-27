# 한 실행(run)의 A·B 폴더에서 프롬프트를 p01부터 차례로 보내 자동 압축까지 진행한다(claude -p).
# 끝나면 runs\<run>\sessions.json에 두 세션 ID를 적고, 비교에 쓸 수 있는 상태인지 확인해 출력한다.
# 사용: python fill.py r03 [압축 횟수, 기본 1] [프롬프트 세트, 기본 s02]
#   먼저 new-run.ps1 r03 으로 폴더를 만들어 둔다. 중간에 끊기면 같은 명령을 다시 실행한다.
#   압축을 3번 일으키려면: python fill.py m01 3 s03
import concurrent.futures
import json
import os
import pathlib
import re
import subprocess
import sys
import uuid

RUN = sys.argv[1]
COMPACTIONS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
HERE = pathlib.Path(__file__).parent
PROMPTS = sorted((HERE / "prompts" / (sys.argv[3] if len(sys.argv) > 3 else "s02")).glob("p*.txt"))
CLAUDE = pathlib.Path.home() / ".local" / "bin" / "claude.exe"
HOME = pathlib.Path.home() / ".claude"
# [의도] 이 스크립트를 띄운 Claude Code 세션의 환경 변수가 실험 세션에 섞이지 않게 한다.
ENV = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "ANTHROPIC"))}
LAST_TARGET = 8  # 질문 대상은 p01~p08에만 있다(prompts\make_set.py, make_keyless.py)
# 모델 답에 콘솔 인코딩(cp949)으로 못 쓰는 글자가 섞여도 진행 표시 때문에 멈추지 않게 한다.
sys.stdout.reconfigure(errors="backslashreplace")


def rows_of(cond, sid):
    path = HOME / "projects" / ("C--ctxeval-runs-%s-%s" % (RUN, cond)) / (sid + ".jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def boundaries(rows):
    return [i for i, e in enumerate(rows) if e.get("subtype") == "compact_boundary"]


def compacted(cond, sid):
    return len(boundaries(rows_of(cond, sid))) >= COMPACTIONS


def started(cond):
    """중단된 실행을 이어 가도록, 이미 있는 세션의 (세션 ID, 보낸 프롬프트 수)를 돌려준다. 없으면 새 ID와 0이다."""
    files = list((HOME / "projects" / ("C--ctxeval-runs-%s-%s" % (RUN, cond))).glob("*.jsonl"))
    if not files:
        return str(uuid.uuid4()), 0
    if len(files) > 1:
        raise RuntimeError("%s: more than one session in this run folder" % cond)
    sid = files[0].stem
    heads = [re.search(r"참고용 로그 (\d\d)", text_of((e.get("message") or {}).get("content") or "")[:200])
             for e in rows_of(cond, sid) if e.get("type") == "user"]
    return sid, len({m[1] for m in heads if m})


def fill(cond):
    """압축이 정한 횟수만큼 날 때까지 보내고 (세션 ID, 보낸 프롬프트 수)를 돌려준다."""
    sid, sent = started(cond)
    if sent and compacted(cond, sid):
        return sid, sent
    for n, prompt in enumerate(PROMPTS[sent:], sent + 1):
        session = ["--session-id", sid] if n == 1 else ["--resume", sid]
        p = subprocess.run([str(CLAUDE), "-p", "--output-format", "json"] + session, input=prompt.read_bytes(),
                           capture_output=True, cwd=HERE / "runs" / RUN / cond, env=ENV, timeout=1200)
        try:
            result = json.loads(p.stdout)
        except ValueError:
            raise RuntimeError("%s %s: rc=%d %s" % (cond, prompt.stem, p.returncode, p.stderr.decode("utf-8", "replace")[-400:]))
        # 세션 ID가 바뀌면 B의 훅 기록이 세션마다 나뉘어 목차가 끊기므로 멈춘다.
        if result.get("is_error") or result.get("session_id") != sid:
            raise RuntimeError("%s %s: %s" % (cond, prompt.stem, str(result)[:400]))
        print("%s %s sent, answer=%r" % (cond, prompt.stem, str(result.get("result"))[:12]), flush=True)
        if compacted(cond, sid):
            return sid, n
    raise RuntimeError("%s: fewer than %d compactions after %d prompts" % (cond, COMPACTIONS, len(PROMPTS)))


def check(cond, sid, sent):
    rows = rows_of(cond, sid)
    bounds = boundaries(rows)
    metas = [rows[b]["compactMetadata"] for b in bounds]
    index = {e.get("uuid"): i for i, e in enumerate(rows)}
    seg = metas[-1].get("preservedSegment") or {}
    kept = []  # 마지막 압축에서 요약되지 않고 원문으로 남은 프롬프트 번호
    if seg.get("headUuid") in index:
        for e in rows[index[seg["headUuid"]]:index.get(seg.get("tailUuid"), bounds[-1]) + 1]:
            m = re.search(r"참고용 로그 (\d\d)", text_of((e.get("message") or {}).get("content") or "")[:200]) if e.get("type") == "user" else None
            if m:
                kept.append(int(m[1]))
    hook = HOME / "ctx-index" / sid
    turns = len(list((hook / "turns").glob("*.md"))) if hook.exists() else 0
    injected = sum(1 for e in rows[bounds[0] + 1:] if (e.get("attachment") or {}).get("type") == "hook_additional_context")
    problems = []
    if any(m.get("trigger") != "auto" for m in metas):
        problems.append("compaction was not automatic")
    if len(bounds) != COMPACTIONS:
        problems.append("expected %d compactions, found %d" % (COMPACTIONS, len(bounds)))
    if kept and min(kept) <= LAST_TARGET:
        problems.append("a prompt holding a question target was kept verbatim")
    if cond == "A" and (turns or injected):
        problems.append("hook left records in A")
    if cond == "B" and (turns != sent or injected < len(bounds)):
        problems.append("hook records incomplete in B (turns=%d, injected=%d)" % (turns, injected))
    print("%s session=%s prompts=%d compaction=%s kept_verbatim=%s hook_turns=%d index_injected=%d %s" % (
        cond, sid, sent, ", ".join("%s %s>%s" % (m.get("trigger"), m.get("preTokens"), m.get("postTokens")) for m in metas),
        kept, turns, injected, "OK" if not problems else "PROBLEM: " + "; ".join(problems)), flush=True)
    return not problems


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    done = dict(zip("AB", pool.map(fill, "AB")))
(HERE / "runs" / RUN / "sessions.json").write_text(json.dumps({c: done[c][0] for c in "AB"}, indent=1), encoding="utf-8")
ok = [check(c, *done[c]) for c in "AB"]
if done["A"][1] != done["B"][1]:
    print("note: A and B compacted at different prompts (%d vs %d)" % (done["A"][1], done["B"][1]))
sys.exit(0 if all(ok) else 1)
