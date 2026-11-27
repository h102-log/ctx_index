# 여러 실행(run)의 analyze.py 결과(out\<run>-<set>\records.json)를 합쳐 results-all-<set>.md를 만든다.
# 사용: python combine.py s02k r02 r03
import json
import math
import pathlib
import sys

SETNAME, RUNS = sys.argv[1], sys.argv[2:]
# 첫 실행 이름 자리에 .md 파일 이름을 주면 그 이름으로 쓴다. 예: combine.py s02k results-multi-s02k.md m01 m02
NAME = RUNS.pop(0) if RUNS[0].endswith(".md") else "results-all-%s.md" % SETNAME
HERE = pathlib.Path(__file__).parent
records = []
for run in RUNS:
    records += json.loads((HERE / "out" / ("%s-%s" % (run, SETNAME)) / "records.json").read_text(encoding="utf-8"))
detail = [r for r in records if r["kind"] != "대조" and not r["excluded"]]
VALUES = (("도구 호출 수", lambda r: len(r["calls"])), ("소요 시간(초)", lambda r: r["seconds"]),
          ("환산 비용($)", lambda r: r["cost"]), ("조정 비용($)", lambda r: r["cost_adj"]))


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def sign_p(up, down):
    """부호 검정 양측 p값(같은 값은 제외)."""
    n, k = up + down, min(up, down)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0


def table(rows_by_label):
    lines = ["| 구분 | 문항 | 정답 A | 정답 B | 도구 호출 A | 도구 호출 B | 시간(초) A | 시간(초) B | 비용($) A | 비용($) B | 조정 비용($) A | 조정 비용($) B |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, rs in rows_by_label:
        part = {c: [r for r in rs if r["cond"] == c] for c in "AB"}
        cells = [label, "%d" % len(part["A"])]
        cells += ["%d / %d" % (sum(r["verdict"] == "정답" for r in part[c]), len(part[c])) for c in "AB"]
        cells += ["%.2f" % mean([len(r["calls"]) for r in part[c]]) for c in "AB"]
        cells += ["%.1f" % mean([r["seconds"] for r in part[c]]) for c in "AB"]
        cells += ["%.4f" % mean([r["cost"] for r in part[c]]) for c in "AB"]
        cells += ["%.4f" % mean([r["cost_adj"] for r in part[c]]) for c in "AB"]
        lines.append("| " + " | ".join(cells) + " |")
    return lines + [""]


def paired(rs):
    a = {(r["run"], r["q"]): r for r in rs if r["cond"] == "A"}
    b = {(r["run"], r["q"]): r for r in rs if r["cond"] == "B"}
    lines = ["| 항목 | 쌍 | A가 더 큼 | 같음 | B가 더 큼 | 부호 검정 p |", "|---|---|---|---|---|---|"]
    for label, value in VALUES:
        diffs = [round(value(a[k]) - value(b[k]), 4) for k in a if k in b]
        up, down = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
        p = sign_p(up, down)
        lines.append("| %s | %d | %d | %d | %d | %s |" % (
            label, len(diffs), up, len(diffs) - up - down, down, "%.4f" % p if p >= 0.0001 else "0.0001 미만"))
    return lines + [""]


kinds = list(dict.fromkeys(r["kind"] for r in records))
out = ["# 실행 합산 결과 (세트 %s, 실행 %s)" % (SETNAME, ", ".join(RUNS)), "",
       "세부 질문 가운데 조회 없이 답할 수 있었던 문항(요약에 답이 있거나 조회 없이 답한 문항)은 뺐다. "
       "시간·비용은 문항당 평균이고, 비용은 사용량에 API 단가를 곱한 환산값이다. "
       "조정 비용은 분기 세션 첫 호출의 캐시 쓰기(분기할 때마다 생기고 조회 행동과 무관한 값)를 뺀 비용이다.", "",
       "## 실행별 (세부 질문)", ""]
out += table([(run, [r for r in detail if r["run"] == run]) for run in RUNS] + [("합계", detail)])
# [의도] 문항끼리는 같은 압축 세션을 공유해 독립이 아니므로, 실행을 한 표본으로 본 비교를 따로 낸다.
out += ["## 실행 단위 비교 (세부 질문의 실행별 평균)", "",
        "| 항목 | 실행 | A가 더 큼 | B가 더 큼 | 부호 검정 p | B가 줄인 비율 (실행별 최소~최대) |", "|---|---|---|---|---|---|"]
for label, value in VALUES:
    means = [[mean([value(r) for r in detail if r["run"] == run and r["cond"] == c]) for c in "AB"] for run in RUNS]
    up, down = sum(a > b for a, b in means), sum(a < b for a, b in means)
    cut = [(a - b) / a * 100 for a, b in means]
    out.append("| %s | %d | %d | %d | %.4f | %.0f%%~%.0f%% |" % (label, len(RUNS), up, down, sign_p(up, down), min(cut), max(cut)))
out += ["", "## 질문 종류별 (전체 실행)", ""]
out += table([(k, [r for r in records if r["kind"] == k and not r["excluded"]]) for k in kinds])
out += ["## 같은 실행·같은 질문끼리 비교 (세부 질문)", ""]
for run in RUNS:
    out += ["### %s" % run, ""] + paired([r for r in detail if r["run"] == run])
out += ["### 합계", ""] + paired(detail)
skipped = sorted({(r["run"], r["q"], r["excluded"]) for r in records if r["excluded"]})
if skipped:
    out += ["## 뺀 문항", ""] + ["- %s %s: %s" % s for s in skipped] + [""]
wrong = [r for r in records if r["verdict"] != "정답"]
out += ["## 자동 판정이 정답이 아닌 답", ""] + (
    ["- %s %s %s: %s" % (r["run"], r["q"], r["cond"], r["answer"][:300].replace("\n", " ")) for r in wrong] or ["- 없음"])
dest = HERE / NAME
dest.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
print("runs: %s, records: %d -> %s" % (RUNS, len(records), dest))
