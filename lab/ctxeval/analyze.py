# 한 실행(run)의 분기 세션 기록에서 질문별 답·조회 경로·토큰·시간을 뽑아 결과 파일을 만든다.
# 사용: python analyze.py r02 [질문 세트, 기본 s02]   (원래 세션 ID는 runs\<run>\sessions.json에서 읽는다)
import datetime
import json
import pathlib
import re
import sys

RUN = sys.argv[1]
SETNAME = sys.argv[2] if len(sys.argv) > 2 else "s02"
HERE = pathlib.Path(__file__).parent
SET = HERE / "prompts" / SETNAME
PARENTS = json.loads((HERE / "runs" / RUN / "sessions.json").read_text(encoding="utf-8"))
PROJECTS = pathlib.Path.home() / ".claude" / "projects"
RESULT = HERE / ("results-%s.md" % (RUN if SETNAME == "s02" else RUN + "-" + SETNAME))
RECORDS = HERE / "out" / ("%s-%s" % (RUN, SETNAME)) / "records.json"
# [이유] claude-opus-5-5 단가(달러/100만 토큰): 입력 4, 출력 20, 캐시 읽기 0.20, 1시간 캐시 쓰기는 입력의 2배.
#        출처는 Claude Code 내장 claude-api 문서(2026-11-03 기준 표). 분기 세션의 캐시 쓰기는 모두 1시간 TTL로 기록돼 있었다.
PRICE = {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 8.0}

questions, expected, kinds = {}, {}, {}
for row in (SET / "answers.md").read_text(encoding="utf-8").splitlines():
    m = re.match(r"\| (q\d\d) (.+?) \| (.+?) \| (.+?) \| .+ \|$", row)
    if m:
        questions[m[1]], kinds[m[1]] = m[2], m[3]
        expected[m[1]] = None if m[3] == "대조" else re.split(r", | = ", re.sub(r" \(.*\)$", "", m[4]))
detail = [q for q in questions if expected[q] is not None]
control = [q for q in questions if expected[q] is None]


def load(cond, name):
    path = PROJECTS / ("C--ctxeval-runs-%s-%s" % (RUN, cond)) / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def summary_of(cond):
    """원래 세션의 압축 요약 본문."""
    rows = load(cond, PARENTS[cond] + ".jsonl")
    b = max(i for i, e in enumerate(rows) if e.get("subtype") == "compact_boundary")
    return next(text_of(e["message"]["content"]) for e in rows[b + 1:] if e.get("type") == "user")


def target(inp):
    blob = json.dumps(inp, ensure_ascii=False).replace("\\\\", "\\").replace("/", "\\").lower()
    if "ctxeval\\prompts" in blob:
        return "원본 파일"
    if "ctx-index" in blob:
        return "턴 파일"
    if ".jsonl" in blob or "\\projects\\" in blob:
        return "트랜스크립트"
    return "기타"


def when(e):
    return datetime.datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))


def grade(q, answer):
    """정답표의 값이 답에 들어 있는지 본다. 자동 표시일 뿐이라 사람이 답 원문으로 다시 확인한다."""
    answer = re.sub(r"(?<=\d),(?=\d{3})", "", answer)  # 88,133 -> 88133
    if expected[q] is None:  # 대조 질문: 없다고 하거나 0건이라고 하면 정답
        return "정답" if "없" in answer or re.search(r"(?<![\d.])0\s*(건|개|번|회)", answer) else "확인 필요"

    def has(tok):
        return re.search(r"(?<![\d.])%s(?!\d)" % tok, answer) if tok.isdigit() else tok in answer
    return "정답" if all(has(tok) for tok in expected[q]) else "확인 필요"


records = []
for cond in "AB":
    for path in sorted((PROJECTS / ("C--ctxeval-runs-%s-%s" % (RUN, cond))).glob("*.jsonl")):
        if path.stem == PARENTS[cond]:
            continue
        rows = load(cond, path.name)
        asked = []
        for i, e in enumerate(rows):
            body = text_of((e.get("message") or {}).get("content") or "") if e.get("type") == "user" else ""
            asked += [(i, q) for q, qt in questions.items() if qt in body and len(body) < len(qt) + 200]
        for n, (i, q) in enumerate(asked):
            seg = rows[i:asked[n + 1][0] if n + 1 < len(asked) else len(rows)]
            calls, usage, answer, last = [], {}, "", rows[i]
            for e in seg:
                m = e.get("message") or {}
                if e.get("type") != "assistant":
                    continue
                last = e
                if m.get("usage") and m.get("id"):
                    usage[m["id"]] = m["usage"]
                for b in m.get("content") or []:
                    if b.get("type") == "tool_use":
                        calls.append(target(b.get("input") or {}))
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        answer = b["text"].strip()
            tok = {k: sum(u.get(f, 0) for u in usage.values()) for k, f in (
                ("input", "input_tokens"), ("cache_write", "cache_creation_input_tokens"),
                ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens"))}
            cost = sum(tok[k] * PRICE[k] for k in PRICE) / 1e6
            # [의도] 분기 세션의 첫 호출이 캐시에 새로 쓰는 양은 조회 행동이 아니라 분기 방식에서 나오므로, 이를 뺀 비용을 따로 둔다.
            # [이유] 실측(2026-11-27): 첫 호출의 캐시 쓰기가 실행·조건에 따라 약 300~10,400토큰으로 달랐다(m02의 A 279, B 10,383).
            #        B는 훅의 목차만큼 더 쓴다(턴 13개일 때 약 850토큰, 37개일 때 약 3,000토큰). 이어지는 세션이라면 한 번만 내는 값이다.
            first_write = next(iter(usage.values()), {}).get("cache_creation_input_tokens", 0)
            records.append(dict(
                run=RUN, q=q, kind=kinds[q], cond=cond, session=path.stem[:8], questions_in_fork=len(asked),
                verdict=grade(q, answer), calls=calls, api_calls=len(usage),
                cost=cost, first_write=first_write, cost_adj=cost - first_write * PRICE["cache_write"] / 1e6,
                seconds=round((when(last) - when(rows[i])).total_seconds()), answer=answer, **tok))
records.sort(key=lambda r: (r["q"], r["cond"]))

# [의도] 조회하지 않아도 답할 수 있었던 문항은 훅의 효과를 재지 못하므로 비교에서 뺀다.
# [이유] r02에서 A의 요약에만 로그별 "최대 지연"이 적혀 있었다. 요약은 압축할 때마다 내용이 달라진다.
summaries = [summary_of(c) for c in "AB"]
excluded = {}
for q in detail:
    marks = [t for t in expected[q] if not t.isdigit() or len(t) >= 4]
    if marks and any(all(t in s for t in marks) for s in summaries):
        excluded[q] = "요약에 답 있음"
    elif any(r["q"] == q and not r["calls"] for r in records):
        excluded[q] = "조회 없이 답함"
for r in records:
    r["excluded"] = excluded.get(r["q"], "")
compared = [q for q in detail if q not in excluded]


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def summary(label, qs):
    lines = ["### %s" % label, "", "| 항목 | A (훅 없음) | B (ctx-index) |", "|---|---|---|"]
    part = {c: [r for r in records if r["cond"] == c and r["q"] in qs] for c in "AB"}

    def row(name, fn):
        lines.append("| %s | %s | %s |" % (name, fn(part["A"]), fn(part["B"])))
    row("정답 / 문항", lambda rs: "%d / %d" % (sum(r["verdict"] == "정답" for r in rs), len(rs)))
    row("도구 호출 합계 (문항당)", lambda rs: "%d (%.2f)" % (sum(len(r["calls"]) for r in rs), mean([len(r["calls"]) for r in rs])))
    for t in ("턴 파일", "트랜스크립트", "원본 파일", "기타"):
        row("조회 대상: " + t, lambda rs, t=t: "%d" % sum(r["calls"].count(t) for r in rs))
    row("API 호출 문항당", lambda rs: "%.2f" % mean([r["api_calls"] for r in rs]))
    row("캐시 읽기 토큰 문항당", lambda rs: "{:,.0f}".format(mean([r["cache_read"] for r in rs])))
    row("캐시 쓰기 토큰 문항당", lambda rs: "{:,.0f}".format(mean([r["cache_write"] for r in rs])))
    row("출력 토큰 문항당", lambda rs: "{:,.0f}".format(mean([r["output"] for r in rs])))
    row("환산 비용 문항당 (달러)", lambda rs: "%.4f" % mean([r["cost"] for r in rs]))
    row("첫 호출 캐시 쓰기 토큰 문항당", lambda rs: "{:,.0f}".format(mean([r["first_write"] for r in rs])))
    row("조정 비용 문항당 (달러)", lambda rs: "%.4f" % mean([r["cost_adj"] for r in rs]))
    row("소요 시간 문항당 (초)", lambda rs: "%.1f" % mean([r["seconds"] for r in rs]))
    return lines + [""]


out = ["# %s 결과 (세트 %s)" % (RUN, SETNAME), "",
       "원래 세션: A `%s`, B `%s`. 질문마다 `--fork-session`으로 연 분기 세션의 기록에서 뽑았다." % (PARENTS["A"], PARENTS["B"]),
       "판정은 정답표의 값이 답에 들어 있는지로 자동 표시한 것이다. 비용은 사용량에 claude-opus-5-5 API 단가를 곱한 환산값이다.",
       "조정 비용은 환산 비용에서 분기 세션 첫 호출의 캐시 쓰기를 뺀 값이다. 이 쓰기는 분기할 때마다 생기고 조회 행동과 무관하다.", ""]
if excluded:
    out += ["비교에서 뺀 세부 질문: " + ", ".join("%s(%s)" % kv for kv in sorted(excluded.items())) + ".", ""]
out += ["## 조건별 요약", ""]
out += summary("세부 질문 %d개" % len(compared), compared) + summary("대조 질문 (%s)" % ", ".join(control), control)
out += ["### 질문 종류별 (문항당 평균)", "",
        "| 종류 | 정답 A | 정답 B | 도구 호출 A | 도구 호출 B | 시간(초) A | 시간(초) B | 비용($) A | 비용($) B |",
        "|---|---|---|---|---|---|---|---|---|"]
for kind in dict.fromkeys(kinds.values()):
    part = {c: [r for r in records if r["cond"] == c and r["kind"] == kind and not r["excluded"]] for c in "AB"}
    cells = [kind]
    cells += ["%d / %d" % (sum(r["verdict"] == "정답" for r in part[c]), len(part[c])) for c in "AB"]
    cells += ["%.2f" % mean([len(r["calls"]) for r in part[c]]) for c in "AB"]
    cells += ["%.1f" % mean([r["seconds"] for r in part[c]]) for c in "AB"]
    cells += ["%.4f" % mean([r["cost"] for r in part[c]]) for c in "AB"]
    out.append("| " + " | ".join(cells) + " |")

pairs = [(a, b) for a in records for b in records
         if a["q"] == b["q"] and a["cond"] == "A" and b["cond"] == "B" and a["q"] in compared]
out += ["", "### 같은 질문끼리 비교 (세부 질문 %d쌍)" % len(pairs), "",
        "| 항목 | A가 더 큼 | 같음 | B가 더 큼 |", "|---|---|---|---|"]
for label, value in (("도구 호출 수", lambda r: len(r["calls"])), ("소요 시간", lambda r: r["seconds"]),
                     ("환산 비용", lambda r: round(r["cost"], 4)), ("조정 비용", lambda r: round(r["cost_adj"], 4))):
    diffs = [value(a) - value(b) for a, b in pairs]
    out.append("| %s | %d | %d | %d |" % (label, sum(d > 0 for d in diffs), sum(d == 0 for d in diffs), sum(d < 0 for d in diffs)))

out += ["", "## 문항별", "",
        "| 질문 | 조건 | 판정 | 도구 호출 | 조회 대상 | API 호출 | 캐시 읽기 | 캐시 쓰기 | 출력 | 비용($) | 시간(초) | 비고 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in records:
    where = ", ".join("%s %d" % (t, r["calls"].count(t)) for t in dict.fromkeys(r["calls"])) or "없음"
    out.append("| %s | %s | %s | %d | %s | %d | %s | %s | %s | %.4f | %d | %s |" % (
        r["q"], r["cond"], r["verdict"], len(r["calls"]), where, r["api_calls"],
        "{:,}".format(r["cache_read"]), "{:,}".format(r["cache_write"]), "{:,}".format(r["output"]),
        r["cost"], r["seconds"], r["excluded"]))
out += ["", "## 문항별 답 (앞부분)", ""]
for r in records:
    extra = "" if r["questions_in_fork"] == 1 else " (분기 하나에 질문 %d개)" % r["questions_in_fork"]
    out.append("- **%s %s** `%s`%s: %s" % (r["q"], r["cond"], r["session"], extra, r["answer"][:200].replace("\n", " ")))
RESULT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
RECORDS.parent.mkdir(parents=True, exist_ok=True)
RECORDS.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
print("records: %d, excluded: %s -> %s" % (len(records), excluded or "none", RESULT))
