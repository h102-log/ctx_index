#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lab simulation part 2: synthetic long sessions -> index rendering, stage-1/2 folding
boundaries and the 6,000-char cap. Lab artifact (pre-approval simulation)."""
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ctx_proto as cp  # noqa: E402

WIN_DIR = r"C:\Users\honggildong\.claude\ctx-index\3f2c9a54-7b1e-4c0d-9a6f-5e8d2b1c4a70\turns"

REQ_BIG = [
    "[목표] 결제 모듈의 재시도 로직을 분석하고, 타임아웃이 중복 결제로 이어지는 경로가 있는지 확인해줘. 관련 파일은 payments/retry.py 와 gateway/client.py 야.",
    "auth 미들웨어에서 세션 토큰 갱신이 간헐적으로 실패하는 원인을 찾아줘. 로그는 logs/auth-2026-11-20.log 에 있고 재현 스크립트는 scripts/repro_refresh.sh 야.",
    "지금까지 분석한 내용을 바탕으로 마이그레이션 계획을 단계별로 정리해줘. 다운타임 없이 진행해야 하고 롤백 절차도 반드시 포함해야 해.",
    "CI에서 test_order_pipeline 이 20% 확률로 실패해. flaky 원인을 좁혀보고 고칠 수 있으면 고쳐줘. 관련 PR은 #482 이고 실패 로그를 첨부했어.",
    "Please review the caching layer in services/cache/redis_store.py and tell me whether the invalidation logic can race with the write-through path under load.",
]
REQ_SMALL = ["응 진행해", "좋아 그대로 해줘", "ㅇㅇ", "테스트도 돌려줘", "커밋해줘", "ok go ahead", "다음", "계속", "그 방향으로 가자"]
ANS_BIG = [
    "안녕하세요!\n\n## 분석 결과\n\n재시도 로직은 gateway 타임아웃(30초)과 클라이언트 타임아웃(10초)의 불일치 때문에 동일 주문에 대해 최대 3회까지 결제 요청을 중복 전송할 수 있습니다. idempotency key가 재시도마다 새로 생성되는 것이 핵심 원인입니다.\n\n" + "세부 근거 문단입니다. " * 400,
    "## 원인\n\n토큰 갱신 실패는 refresh 엔드포인트의 락 범위가 사용자 단위가 아니라 세션 단위여서, 같은 사용자의 탭 두 개가 동시에 갱신을 시도할 때 한쪽이 이미 폐기된 토큰으로 요청하게 되는 경쟁 상태입니다.\n\n" + "재현 로그와 코드 인용입니다. " * 250,
    "네, 정리했습니다.\n\n1. 스키마 이중 기록(dual-write) 단계를 먼저 두고 2. 백필 3. 읽기 전환 4. 구 스키마 제거 순서로 진행하며 각 단계는 기능 플래그로 즉시 롤백할 수 있습니다.\n\n" + "단계별 상세입니다. " * 300,
    "The flake comes from a shared temp directory: two test workers write order fixtures to the same path, so the pipeline occasionally reads the other worker's fixture. Isolating tmp_path per worker fixes it.\n\n" + "Details and diff follow. " * 200,
]
ANS_SMALL = ["네, 진행했습니다.", "완료했습니다. 테스트 42개 모두 통과합니다.", "커밋했습니다 (a1b2c3d).", "Done.", "네 계속하겠습니다."]


def make_turns(n, seed=1, small_ratio=0.3, start=1):
    rnd = random.Random(seed)
    turns = []
    for i in range(start, start + n):
        if rnd.random() < small_ratio:
            req, ans = rnd.choice(REQ_SMALL), rnd.choice(ANS_SMALL)
        else:
            req = rnd.choice(REQ_BIG) + " (작업 #%d)" % i
            ans = rnd.choice(ANS_BIG)
        turns.append({"n": i, "pid": "p%d" % i, "status": "done", "req": cp.request_preview(req), "ans": cp.answer_preview(ans),
                      "nreq": 1, "nans": 1, "bytes": len(req.encode("utf-8")) + len(ans.encode("utf-8")), "kind": "user"})
    return turns


def describe(label, turns, prev, turns_dir=WIN_DIR, inflight=None, minimal=False, show=0):
    t0 = time.perf_counter()
    text, info = cp.render_index(turns, prev, turns_dir, inflight, minimal=minimal)
    ms = (time.perf_counter() - t0) * 1000
    lines = text.split("\n")
    body = lines[3:]
    full = [l for l in body if " | " in l]
    folds = [l for l in body if "접힘)" in l]
    kept_first = full[0][:7] if full else "-"
    kept_last = full[-1][:7] if full else "-"
    over = cp.ulen(text) > cp.MAX_CONTEXT_CHARS or len(text) > cp.MAX_CONTEXT_CHARS
    print("%-46s turns=%4d  stage=%-4s chars=%4d utf16=%4d  full-lines=%3d fold-lines=%2d folded=%4d preview=%s  kept %s..%s  %.1fms %s"
          % (label, len(turns), info["stage"], len(text), cp.ulen(text), len(full), len(folds), info["folded"],
             "/".join(map(str, info["preview"])), kept_first, kept_last, ms, "OVER-LIMIT!" if over else ""))
    if info.get("segment"):
        print("%-46s   stage-1 segment: %s ; fold lines: %s" % ("", info["segment"], " ; ".join(folds[:4]) + (" …" if len(folds) > 4 else "")))
    if show:
        for l in lines[:3 + show]:
            print("      | " + l)
        if len(lines) > 3 + show:
            print("      | … (%d more lines) …" % (len(lines) - 3 - show - 2))
            for l in lines[-2:]:
                print("      | " + l)
    assert not over, label
    return text, info


print("=" * 150)
print("PART 2-A  렌더링과 접기 단계 경계 (상한 %d자, 미리보기 %d/%d자, 첫 압축 접기 %d턴, 소형 기준 %dB)"
      % (cp.MAX_CONTEXT_CHARS, cp.REQ_PREVIEW_CHARS, cp.ANS_PREVIEW_CHARS, cp.FIRST_COMPACTION_FOLD_TURNS, cp.SMALL_TURN_BYTES))
print("=" * 150)
describe("S1 첫 압축, 12턴", make_turns(12), None, show=6)
describe("S2 첫 압축, 40턴", make_turns(40), None)
describe("S3 첫 압축, 48턴", make_turns(48), None)
describe("S4 첫 압축, 70턴", make_turns(70), None)
describe("S5 첫 압축, 110턴", make_turns(110), None)
describe("S6 첫 압축, 300턴", make_turns(300), None)
describe("S7 2회차 압축(경계=40), 58턴", make_turns(58), {"last_turn": 40, "last_open": False}, show=4)
describe("S8 2회차 압축(경계=40, 당시 진행 중)", make_turns(58), {"last_turn": 40, "last_open": True})
describe("S9 2회차 압축(경계=40), 140턴", make_turns(140), {"last_turn": 40, "last_open": False})
describe("S10 3회차 압축(경계=140), 400턴", make_turns(400), {"last_turn": 140, "last_open": False})
describe("S11 경계가 0턴으로 기록된 뒤(=첫 압축 취급), 60턴", make_turns(60), {"last_turn": 0, "last_open": False})

print()
print("=" * 150)
print("PART 2-B  단계 전환 경계 탐색: 첫 압축에서 턴 수 n을 1..400으로 늘리며 단계가 바뀌는 지점")
print("=" * 150)
prev_stage = None
for n in range(1, 401):
    text, info = cp.render_index(make_turns(n), None, WIN_DIR)
    assert len(text) <= cp.MAX_CONTEXT_CHARS and cp.ulen(text) <= cp.MAX_CONTEXT_CHARS, n
    if info["stage"] != prev_stage:
        print("  n=%3d → stage %-4s (chars=%d, 접힌 턴=%d, 미리보기=%s)" % (n, info["stage"], len(text), info["folded"], "/".join(map(str, info["preview"]))))
        prev_stage = info["stage"]

print()
print("=" * 150)
print("PART 2-C  상한 스트레스: 무작위 세션 3,000개 (턴 1~3,000개, 한글/emoji/장문 한 줄/긴 경로/임의 경계) — 길이는 code point와 UTF-16 둘 다 검사")
print("=" * 150)
rnd = random.Random(20261126)
worst = (0, None)
stages = {}
EMOJI = "😀🙂🚀🔥🧪📦🛠️" * 40
_t = time.perf_counter()
LONG_REQ = cp.request_preview("가" * 200000)
LONG_ANS = cp.answer_preview("x" * 300000)
print("  장문 한 줄 미리보기 계산(요청 200,000자 + 답변 300,000자): %.2fms → 요청 미리보기 %d자, 답변 미리보기 %d자"
      % ((time.perf_counter() - _t) * 1000, len(LONG_REQ), len(LONG_ANS)))
t_all = time.perf_counter()
slowest = 0.0
for case in range(3000):
    n = rnd.choice([1, 2, 5, 6, 30, 36, 37, 50, 80, 120, 300, 700, 1500, 3000]) if case % 5 == 0 else rnd.randint(1, 260)
    turns = make_turns(n, seed=case, small_ratio=rnd.random())
    mode = case % 6
    for t in turns:
        if mode == 1:          # emoji-only previews (2 UTF-16 units per char)
            t["req"], t["ans"] = EMOJI[:cp.STORED_PREVIEW_CHARS], EMOJI[:cp.STORED_PREVIEW_CHARS]
        elif mode == 2:        # single very long line
            t["req"], t["ans"] = LONG_REQ, LONG_ANS
        elif mode == 3 and rnd.random() < 0.3:   # interrupted / unrecorded
            t["nans"], t["ans"] = 0, ""
            if rnd.random() < 0.3:
                t["req"], t["nreq"] = "", 0
        elif mode == 4:
            t["nreq"], t["nans"] = rnd.randint(1, 12), rnd.randint(1, 12)
    d = WIN_DIR if mode != 5 else "C:\\" + "\\".join(["아주긴디렉터리이름%02d" % i for i in range(20)]) + "\\turns"
    prev = None if rnd.random() < 0.4 else {"last_turn": rnd.randint(0, n), "last_open": rnd.random() < 0.3}
    t0 = time.perf_counter()
    text, info = cp.render_index(turns, prev, d, minimal=bool(case % 2))
    slowest = max(slowest, time.perf_counter() - t0)
    L = max(len(text), cp.ulen(text))
    assert L <= cp.MAX_CONTEXT_CHARS, (case, n, info)
    assert text.startswith(cp.HEADER) and text.count(d) == 1
    for line in text.split("\n")[3:]:
        assert re.match(r"^\d{4,}\.md", line), line[:60]
    stages[info["stage"]] = stages.get(info["stage"], 0) + 1
    if L > worst[0]:
        worst = (L, (case, n, info["stage"]))
print("  3,000/3,000 세션 상한 준수. 단계 분포: %s" % json.dumps(dict(sorted(stages.items())), ensure_ascii=False))
print("  최대 길이=%d (case,n,stage=%s) · 전체 %.1fs · 단일 렌더 최장 %.0fms" % (worst[0], worst[1], time.perf_counter() - t_all, slowest * 1000))

# absurd path: the header alone exceeds the cap -> hard cut still guarantees the invariant
text, info = cp.render_index(make_turns(50), None, "C:\\" + "x" * 7000 + "\\turns")
print("  머리말 경로만으로 상한 초과(7,000자 경로): stage=%s chars=%d → 상한 준수=%s" % (info["stage"], len(text), cp.ulen(text) <= cp.MAX_CONTEXT_CHARS))

print()
print("=" * 150)
print("PART 2-D  1차 접기 방식 비교: 명세 그대로(구간 전체 접기) vs 역제안(같은 구간 안에서 최신 턴부터 필요한 만큼만 접기)")
print("=" * 150)
for label, n, prev in (("첫 압축 40턴", 40, None), ("첫 압축 48턴", 48, None),
                        ("2회차(경계 3) 45턴", 45, {"last_turn": 3, "last_open": False}),
                        ("2회차(경계 40) 58턴", 58, {"last_turn": 40, "last_open": False}),
                        ("2회차(경계 20) 120턴", 120, {"last_turn": 20, "last_open": False})):
    for minimal in (False, True):
        describe("%s / %s" % (label, "필요한 만큼" if minimal else "명세 그대로"), make_turns(n), prev, minimal=minimal)

print()
print("=" * 150)
print("PART 2-E  종단 흐름(프로토타입 훅 호출): 60턴 → 압축#1 → 30턴 → 압축#2 → 12턴 → 압축#3, 경계 읽기→렌더링→기록 순서")
print("=" * 150)
base = tempfile.mkdtemp(prefix="ctxsim-")
os.environ["CTX_INDEX_DIR"] = base
SID = "11111111-2222-3333-4444-555555555555"
seq = make_turns(102, seed=7)
raw_req = {}
rnd = random.Random(7)


def feed_turn(i):
    small = rnd.random() < 0.3
    req = (rnd.choice(REQ_SMALL) if small else rnd.choice(REQ_BIG) + " (작업 #%d)" % i)
    ans = (rnd.choice(ANS_SMALL) if small else rnd.choice(ANS_BIG))
    pid = "pid-%04d" % i
    assert cp.handle({"hook_event_name": "UserPromptSubmit", "session_id": SID, "prompt_id": pid, "prompt": req, "cwd": "/w/branch-%d" % (i % 3)}) is None
    assert cp.handle({"hook_event_name": "Stop", "session_id": SID, "prompt_id": pid, "last_assistant_message": ans, "stop_hook_active": False}) is None
    raw_req[i] = (req, ans)


def compact(tag):
    before = sum(1 for _ in open(os.path.join(base, SID, "compactions.jsonl"), encoding="utf-8")) if os.path.exists(os.path.join(base, SID, "compactions.jsonl")) else 0
    out = cp.handle({"hook_event_name": "SessionStart", "session_id": SID, "source": "compact", "prompt_id": "compact-" + tag})
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    comp = [json.loads(l) for l in open(os.path.join(base, SID, "compactions.jsonl"), encoding="utf-8")]
    folds = [l for l in text.split("\n") if "접힘)" in l]
    print("  압축 %s: 기록 전 경계 %d줄 → 기록 후 %d줄 | stage=%s chars=%d | 접힌 줄: %s" % (tag, before, len(comp), comp[-1]["stage"], len(text), " ; ".join(folds) or "(없음)"))
    assert len(text) <= cp.MAX_CONTEXT_CHARS
    return text, comp


for i in range(1, 61):
    feed_turn(i)
t1, c1 = compact("#1")
assert c1[-1]["last_turn"] == 60 and re.search(r"0056\.md~0060\.md .*\(5턴 접힘\)", t1), "first compaction must fold the newest 5"
for i in range(61, 91):
    feed_turn(i)
t2, c2 = compact("#2")
assert re.search(r"0061\.md~0090\.md .*\(30턴 접힘\)", t2), "second compaction must fold everything after the previous boundary (61..90)"
assert "0060.md " in t2 and "0056.md~0060.md" not in t2, "turns before the previous boundary get their lines back"
for i in range(91, 103):
    feed_turn(i)
t3, c3 = compact("#3")
m3 = re.search(r"(\d{4})\.md~0102\.md .*\((\d+)턴 접힘\)", t3)
assert m3 and int(m3.group(1)) <= 91, "third compaction must fold at least everything after the previous boundary (91..102)"
d = os.path.join(base, SID)
print("  세션 디렉터리 1개(cwd가 바뀌어도 동일): %s" % os.listdir(base))
print("  파일: %s, turns/ %d개" % (sorted(os.listdir(d)), len(os.listdir(os.path.join(d, "turns")))))
body = open(os.path.join(d, "turns", "0001.md"), encoding="utf-8").read()
print("  턴 파일 무손실: 요청 원문 포함=%s, 답변 원문 포함=%s" % (raw_req[1][0] in body, raw_req[1][1] in body))
assert raw_req[1][0] in body and raw_req[1][1] in body
print("  index.md 스냅샷 == 마지막 주입문: %s" % open(os.path.join(d, "index.md"), encoding="utf-8").read().startswith(t3))
shutil.rmtree(base, ignore_errors=True)
print("\nALL FOLD SIMULATIONS PASSED")
