#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lab simulation part 1: replay REAL hook payloads captured from Claude Code 2.1.332
(driven against a local mock API) through the prototype. Lab artifact (pre-approval simulation).

Fidelity: the capture recorded the transcript size at the moment each hook ran, so every
event is replayed against a copy of the transcript truncated to exactly that size.
The committed captures hold slim transcripts (see ../probe/pack_captures.py); tx_size was
re-based onto them, so the lines visible to the hook are the same as in the original run.
Set CTX_LAB_CAPTURES to replay another capture directory.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.environ.get("CTX_LAB_CAPTURES") or os.path.join(os.path.dirname(HERE), "captures", "v2")
TX = os.path.join(LAB, "transcripts")
sys.path.insert(0, HERE)
import ctx_proto as cp  # noqa: E402

VERBOSE = "-q" not in sys.argv


def replay(name):
    rows = [json.loads(l) for l in open(os.path.join(LAB, name, "payloads.jsonl"), encoding="utf-8")]
    base = tempfile.mkdtemp(prefix="ctxsim-")
    txdir = tempfile.mkdtemp(prefix="ctxsim-tx-")
    os.environ["CTX_INDEX_DIR"] = base
    outs = []
    for r in rows:
        p = dict(r["payload"])
        ev = p.get("hook_event_name")
        assert ev in ("UserPromptSubmit", "Stop", "SessionStart"), ev
        name_ = os.path.basename(p.get("transcript_path") or "")
        real = os.path.join(TX, name_)
        copy = os.path.join(txdir, name_ or "none.jsonl")
        if r.get("tx_size") is None:
            if os.path.exists(copy):
                os.remove(copy)
        else:
            with open(real, "rb") as src, open(copy, "wb") as dst:
                dst.write(src.read(r["tx_size"]))
        p["transcript_path"] = copy
        out = cp.handle(p)
        if ev != "SessionStart":
            assert out is None, "principle 2 violated: output outside compaction"
        if out:
            outs.append((p["session_id"], json.loads(out)["hookSpecificOutput"]["additionalContext"]))
    result = {}
    for sid in sorted(os.listdir(base)):
        d = os.path.join(base, sid)
        if not os.path.isdir(d):
            continue
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        cpath = os.path.join(d, "compactions.jsonl")
        comp = [json.loads(l) for l in open(cpath, encoding="utf-8")] if os.path.exists(cpath) else []
        result[sid] = {"meta": meta, "comp": comp, "errs": os.path.exists(os.path.join(d, "errors.jsonl")), "dir": d}
    shutil.rmtree(txdir, ignore_errors=True)
    return rows, outs, result, base


def show(name, title):
    rows, outs, result, base = replay(name)
    if VERBOSE:
        print("=" * 100)
        print("LAB %s — %s  (hook events fed: %d)" % (name, title, len(rows)))
        for sid, r in result.items():
            print("\n  session %s…  turns=%d  compactions=%d  errors.jsonl=%s" % (sid[:8], len(r["meta"]["turns"]), len(r["comp"]), r["errs"]))
            for t in r["meta"]["turns"]:
                print("    %s" % cp.turn_line(t, cp.REQ_PREVIEW_CHARS, cp.ANS_PREVIEW_CHARS, None))
                print("        [status=%s kind=%s nreq=%d nans=%d pid=%s]" % (t["status"], t["kind"], t["nreq"], t["nans"], (t.get("pid") or "-")[:8]))
            for c in r["comp"]:
                print("    compaction: %s" % json.dumps({k: c[k] for k in ("last_turn", "last_open", "turns", "chars", "stage", "folded")}, ensure_ascii=False))
        for sid, text in outs:
            print("\n  --- injected additionalContext (session %s…, %d chars / utf16 %d) ---" % (sid[:8], len(text), cp.ulen(text)))
            for line in text.split("\n"):
                print("  | " + line.replace(base, "<CTX>"))
    return rows, outs, result, base


def session_with(result, needle):
    for sid, r in result.items():
        if any(needle in (t.get("req") or "") for t in r["meta"]["turns"]):
            return sid, r
    raise KeyError(needle)


def turn_file(r, n):
    return open(os.path.join(r["dir"], "turns", "%04d.md" % n), encoding="utf-8").read()


checks = []


def check(desc, cond):
    checks.append((desc, bool(cond)))


# ---------------------------------------------------------------- lab a
rows, outs, res, base = show("a", "stream-json: 일반/도구/서브에이전트/커스텀 슬래시/브랜치 전환/compact/빈 답변/clear")
sid, r = session_with(res, "첫 번째 질문")
T = r["meta"]["turns"]
check("a: 세션 2개(원 세션 + /clear 이후 새 session_id)만 생성 — 브랜치 전환·압축은 디렉터리를 바꾸지 않음", len(res) == 2)
check("a: 원 세션 턴 8개(일반, 도구, 서브에이전트, 작업 알림, 커스텀 슬래시, 브랜치 전환 후, 압축 후, 빈 답변)", len(T) == 8)
check("a: 내장 명령(/compact,/cost,/help,/status,/clear)은 턴으로 기록되지 않음", not any(t["req"].startswith(("/compact", "/cost", "/help", "/status", "/clear")) for t in T))
check("a: 커스텀 슬래시 명령은 입력 원문 그대로 기록", any(t["req"] == "/mycmd 인자1 인자2" and t["kind"] == "user" for t in T))
check("a: 도구 턴의 답변은 최종 텍스트(중간 내레이션 아님)", "도구 실행을 마쳤습니다" in T[1]["ans"] and "먼저 도구를" not in turn_file(r, 2))
check("a: task-notification 자동 턴은 [작업 알림] 요약으로 표시", T[3]["req"].startswith("[작업 알림] Agent") and T[3]["kind"] == "auto")
empty = [t for t in T if t["req"].startswith("[[EMPTY]]")][0]
check("a: last_assistant_message 없는 Stop → 폴백이 이전 턴 답변을 끌어오지 않음(답변 0건, done)", empty["nans"] == 0 and empty["status"] == "done")
check("a: 압축 주입 1회, 상한 이하, 고정 머리말로 시작", len(outs) == 1 and cp.ulen(outs[0][1]) <= cp.MAX_CONTEXT_CHARS and outs[0][1].startswith(cp.HEADER))
check("a: 디렉터리 절대 경로는 주입문에 1회만 등장", outs[0][1].count(os.path.join(r["dir"], "turns")) == 1)
first = turn_file(r, 1)
check("a: 턴 파일에 요청·답변 원문 그대로 저장(한글·emoji·코드펜스)", "첫 번째 질문: 한글 테스트입니다" in first and "한글·emoji 🙂 포함." in first and "```python\nprint('ok')\n```" in first)
check("a: errors.jsonl 없음", not any(x["errs"] for x in res.values()))
shutil.rmtree(base, ignore_errors=True)

# ---------------------------------------------------------------- lab b
rows, outs, res, base = show("b", "자동 압축(UserPromptSubmit→압축→Stop 순서) + 수동 압축(/compact 지시문)")
(r,) = res.values()
T, comp = r["meta"]["turns"], r["comp"]
check("b: 압축 2회 모두 같은 세션 디렉터리, 경계 2줄 기록", len(res) == 1 and len(comp) == 2)
check("b: 자동 압축 시점의 진행 중 턴은 '(진행 중)'으로 표시('중단' 아님)", "(진행 중)" in outs[0][1] and cp.NO_ANSWER not in outs[0][1])
check("b: 자동 압축 경계는 last_turn=3, last_open=True(진행 중이던 3번 턴)", comp[0]["last_turn"] == 3 and comp[0]["last_open"] is True)
check("b: 자동 압축 뒤 도착한 Stop이 같은 턴(3번)에 귀속", T[2]["nans"] == 1 and T[2]["req"].startswith("B3"))
check("b: 수동 압축 경계는 last_turn=4, last_open=False", comp[1]["last_turn"] == 4 and comp[1]["last_open"] is False)
check("b: '/compact <지시문>'은 턴으로 기록되지 않음(턴 5개)", len(T) == 5)
shutil.rmtree(base, ignore_errors=True)

# ---------------------------------------------------------------- lab c
rows, outs, res, base = show("c", "Stop 훅 차단으로 Stop 2회 / --resume / --continue / --fork-session")
_, c0 = session_with(res, "C0 ")
check("c: 같은 prompt_id의 Stop 2회 → 턴 1개에 답변 2건(목차 줄 중복 없음)", len(c0["meta"]["turns"]) == 1 and c0["meta"]["turns"][0]["nans"] == 2)
check("c: 턴 파일에 두 답변이 순서대로 저장('답변', '답변 (이어짐 2)')", "## ◇ 답변 ·" in turn_file(c0, 1) and "## ◇ 답변 (이어짐 2) ·" in turn_file(c0, 1))
_, c1 = session_with(res, "C1 ")
check("c: --resume/--continue 는 같은 session_id → 같은 디렉터리에 턴 3개 누적", [t["req"][:2] for t in c1["meta"]["turns"]] == ["C1", "C2", "C3"])
check("c: --fork-session 은 새 session_id 디렉터리(세션 3개)", len(res) == 3)
shutil.rmtree(base, ignore_errors=True)

# ---------------------------------------------------------------- lab d
rows, outs, res, base = show("d", "대화형 TUI: 내장 명령 / Esc 중단 / bash 모드(!cmd) / compact / clear / exit")
_, r = session_with(res, "대화형 첫 질문")
T = r["meta"]["turns"]
slow = [t for t in T if t["req"].startswith("[[SLOW]]")][0]
check("d: Esc 중단 턴은 Stop 미발생 → open 유지, 목차에 '(답변 없음/중단)'", slow["status"] == "open" and slow["nans"] == 0 and (" | [[SLOW]] 느린 답변을 요청합니다 → " + cp.NO_ANSWER) in outs[0][1])
bash = [t for t in T if t["kind"] == "orphan"]
check("d: UserPromptSubmit 없이 온 Stop(bash 모드)은 직전 턴에 붙지 않고 새 턴 파일", len(bash) == 1 and bash[0]["n"] == 4)
check("d: 그 새 턴의 요청은 트랜스크립트에서 복원('!echo bash-mode-probe')", bash[0]["req"] == "!echo bash-mode-probe")
check("d: 중단 다음 턴의 답변이 중단된 턴에 잘못 붙지 않음", [t for t in T if t["req"].startswith("중단 이후")][0]["nans"] == 1)
check("d: /clear 이후는 새 session_id 디렉터리", len(res) == 2)
shutil.rmtree(base, ignore_errors=True)

# ---------------------------------------------------------------- lab e
rows, outs, res, base = show("e", "대화형 TUI: 작업 중 입력(대기열) — 별도 턴으로 처리 / 진행 중 턴에 흡수")
(r,) = res.values()
T = r["meta"]["turns"]
Q2_ECHO = "요청하신 내용(Q2 대기열에 넣은 질문)"   # the mock answer echoes the prompt it answers
check("e: Q1 턴에는 Q1의 답변 1건만 귀속(Q2의 답변이 섞이지 않음)", T[0]["req"].startswith("[[SLOW]] Q1") and turn_file(r, 1).count("## ◇ 답변") == 1 and Q2_ECHO not in turn_file(r, 1))
check("e: Q2는 작업 중 입력으로 Q1 턴 파일에 '추가 요청'으로도 보존", T[0]["nreq"] == 2 and "Q2 대기열에 넣은 질문" in turn_file(r, 1))
check("e: Q2 자체 턴은 Stop 시점에 새 턴으로 만들어지고 요청은 트랜스크립트에서 복원, Q2의 답변이 귀속", T[1]["kind"] == "orphan" and T[1]["req"].startswith("Q2 대기열") and Q2_ECHO in turn_file(r, 2))
check("e: 도구 턴 중 입력(Q4)은 같은 턴에 흡수 → 턴 1개, 요청 2건, 답변 1건", T[2]["nreq"] == 2 and T[2]["nans"] == 1 and len(T) == 3)
check("e: 어떤 턴도 '(답변 없음/중단)'으로 잘못 표시되지 않음", all(t["nans"] >= 1 for t in T))
shutil.rmtree(base, ignore_errors=True)

# ---------------------------------------------------------------- lab stacked
rows, outs, res, base = show("stacked", "대화형 TUI: 중첩 대기열(Q1 실행 중 Q2 입력, Q2 실행 중 Q5 입력) + 유휴 상태의 일반/커스텀 슬래시")
(r,) = res.values()
T = r["meta"]["turns"]
check("stacked: 유휴 상태의 일반 프롬프트·커스텀 슬래시는 '새 턴'으로 판정(트랜스크립트 선조회가 오판하지 않음)", T[0]["kind"] == "user" and T[1]["kind"] == "user" and T[1]["req"] == "/mycmd 대화형 인자")
check("stacked: 턴 5개 — Q1(+Q2 입력) / Q2 자체 턴(+Q5 입력) / Q5 자체 턴", len(T) == 5)
check("stacked: Q2 자체 턴은 UserPromptSubmit(Q5) 시점에 트랜스크립트에서 요청을 복원해 생성", T[3]["kind"] == "recovered" and T[3]["req"].startswith("[[SLOW]] Q2") and T[3]["nreq"] == 2)
check("stacked: Q2의 답변(#9)은 Q2 자체 턴에, Q5의 답변(#10)은 Q5 자체 턴에 귀속", "답변 9" in turn_file(r, 4) and "답변 10" in turn_file(r, 5) and T[4]["req"].startswith("Q5 두 번째"))
shutil.rmtree(base, ignore_errors=True)

# ---------------------------------------------------------------- lab headless
rows, outs, res, base = show("headless", "stream-json: 일반 / 커스텀 슬래시 / 백그라운드 서브에이전트 → 작업 알림 자동 턴 / 후속 질문")
(r,) = res.values()
T = r["meta"]["turns"]
check("headless: 턴 5개, 모두 UserPromptSubmit로 생성(오판 없음), 작업 알림은 auto", [t["kind"] for t in T] == ["user", "user", "user", "auto", "user"])
check("headless: 모든 턴에 답변 1건씩 귀속", all(t["nans"] == 1 for t in T))
shutil.rmtree(base, ignore_errors=True)

print("\n" + "=" * 100)
ok = sum(1 for _, c in checks if c)
for desc, c in checks:
    print("  [%s] %s" % ("PASS" if c else "FAIL", desc))
print("replay checks: %d/%d passed" % (ok, len(checks)))
sys.exit(0 if ok == len(checks) else 1)
