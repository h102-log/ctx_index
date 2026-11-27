#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Summarise an autocompact retention eval run (paired A/B) as Markdown and JSON.

    python3 lab/eval/analyze.py lab/eval/.run/pilot                 Markdown summary on stdout
    python3 lab/eval/analyze.py lab/eval/.run/pilot --json out.json also write the numbers as JSON

Headline: recall of the planted details after autocompact (needle probes; probes whose needle was not sent or
whose build answer lacked the derived value are excluded in both arms alike), per arm, and the paired
difference B - A with a 95% interval from a cluster bootstrap over units (scenario x rep) plus an exact McNemar
test on the discordant pairs. Costs are derived from each probe's recorded usage and model, never assumed:
Claude Opus 5.5 at $4 / MTok input, $20 / MTok output, cache reads $0.20 / MTok, cache writes 1.25x input
(5-minute) or 2x input (1-hour). The CLI's own total_cost_usd is shown next to it as a cross-check.
"""
import argparse
import json
import math
import os
import random
import statistics
import sys

PRICES = {"claude-opus-5-5": {"in": 4.0, "out": 20.0, "cache_read": 0.20}}
VARIANTS = [("A", "baseline", "훅 없음"), ("B", "v1", "ctx-index")]
KIND_KO = {"order": "순서(첫 붙여넣기)", "paste_value": "붙여넣기 속 값", "user_fact": "사용자가 말한 값", "constraint": "제약(수정 금지)",
           "assistant_derived": "모델이 찾아 준 값", "verbatim": "원문 인용", "decision_reason": "결정 기준값", "negative": "대조(없던 일)"}
POS_KO = {"early": "초반(0~22%)", "mid": "중반(35~60%)", "late": "후반(74~88%)"}


def load_rows(run, variant):
    path = os.path.join(run, "report", variant, "results.jsonl")
    rows = []
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                rows.append(json.loads(line))
    # keep the first row per (case, rep): resume never writes duplicates, but be strict anyway
    seen, out = set(), []
    for r in rows:
        k = (r["prompt_id"], r["rep"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def cost(row):
    p = PRICES.get(row.get("model") or "", None)
    if p is None:
        return None
    u = row.get("usage") or {}
    cc = int(u.get("cache_creation_input_tokens") or 0)
    c1h = int(u.get("cache_creation_1h") or 0)
    c5m = int(u.get("cache_creation_5m") or 0) or max(0, cc - c1h)
    return (int(u.get("input_tokens") or 0) * p["in"] + int(u.get("output_tokens") or 0) * p["out"]
            + int(u.get("cache_read_input_tokens") or 0) * p["cache_read"] + c5m * p["in"] * 1.25 + c1h * p["in"] * 2.0) / 1e6


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    ph = k / float(n)
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar_p(b, c):
    """Exact two-sided McNemar p-value: b = only A correct, c = only B correct."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / float(2 ** n)
    return min(1.0, 2 * p)


def pct(x):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else "%.1f%%" % (100 * x)


def money(x):
    return "—" if x is None else ("$%.4f" % x if x < 0.1 else "$%.3f" % x)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def analyze(run, boot=4000, seed=11):
    units = {}
    udir = os.path.join(run, "units")
    for name in sorted(os.listdir(udir)) if os.path.isdir(udir) else []:
        p = os.path.join(udir, name, "unit.json")
        if os.path.isfile(p):
            units[name] = json.load(open(p, encoding="utf-8"))
    rows = {arm: load_rows(run, v) for arm, v, _ in VARIANTS}
    errors = {}
    for arm, v, _ in VARIANTS:
        ep = os.path.join(run, "report", v, "errors.jsonl")
        errors[arm] = [json.loads(l) for l in open(ep, encoding="utf-8") if l.strip()] if os.path.isfile(ep) else []
    uerr = os.path.join(run, "errors.jsonl")
    unit_errors = [json.loads(l) for l in open(uerr, encoding="utf-8") if l.strip()] if os.path.isfile(uerr) else []

    res = {"run": run, "units": {}, "arms": {}, "paired": {}, "by_kind": {}, "by_pos": {}, "errors": {}}
    for name, u in units.items():
        b = u.get("build") or {}
        model = (u.get("model") or "claude-opus-5-5")
        bcost = sum(cost({"model": model, "usage": t.get("usage")}) or 0 for t in b.get("turns", []))
        res["units"][name] = {"finished": bool(u.get("finished")), "build_turns": b.get("n_turns"), "armed_at": b.get("context"),
                              "build_cost": bcost, "build_cost_cli": b.get("cost_cli"), "build_minutes": round((b.get("seconds") or 0) / 60.0, 1),
                              "invalid_probes": u.get("invalid_probes", {}),
                              "arms": {arm: {"pre_tokens": (x.get("compact") or {}).get("pre_tokens"), "post_tokens": (x.get("compact") or {}).get("post_tokens"),
                                             "summary_chars": x.get("summary_chars"), "index_chars": x.get("index_chars"),
                                             "index_stage": (x.get("ctx_compaction") or {}).get("stage"), "compact_cost_cli": x.get("cost_cli"),
                                             "tail_turns": x.get("tail_turns"),
                                             "compact_cost": sum(cost({"model": model, "usage": t.get("usage")}) or 0 for t in x.get("tail", []))}
                                       for arm, x in (u.get("arms") or {}).items()}}
    for arm, v, label in VARIANTS:
        rs = [r for r in rows[arm] if r["status"] == "ok"]
        needle = [r for r in rs if r["tags"][0] != "negative"]
        neg = [r for r in rs if r["tags"][0] == "negative"]
        k = sum(r["grade"]["correct"] for r in needle)
        costs = [cost(r) for r in rs]
        res["arms"][arm] = {
            "label": label, "probes": len(rs), "truncated": sum(1 for r in rows[arm] if r["status"] == "truncated"),
            "needle_n": len(needle), "recall": k / float(len(needle)) if needle else None, "recall_ci": wilson(k, len(needle)),
            "abstained": mean([r["grade"]["abstained"] for r in needle]), "wrong": mean([r["grade"]["wrong"] for r in needle]),
            "negative_n": len(neg), "negative_correct": mean([r["grade"]["correct"] for r in neg]),
            "cost_per_probe_mean": mean(costs), "cost_per_probe_median": med(costs), "cost_total": sum(c for c in costs if c is not None),
            "cost_cli_total": sum((r.get("cost_cli") or 0) for r in rs),
            "cost_per_correct": (sum(c for c in costs if c is not None) / k) if k else None,
            "tool_calls_mean": mean([r["tool_calls"] for r in rs]), "requests_mean": mean([r["requests"] for r in rs]),
            "turn_file_reads": sum(r["turn_file_reads"] for r in rs), "transcript_reads": sum(r["transcript_reads"] for r in rs),
            "probes_reading_turn_files": mean([1 if r["turn_file_reads"] else 0 for r in rs]),
            "probes_reading_transcript": mean([1 if r["transcript_reads"] else 0 for r in rs]),
            "latency_median_s": med([r["latency_s"] for r in rs]), "latency_mean_s": mean([r["latency_s"] for r in rs]),
            "input_tokens_median": med([sum(int((r.get("usage") or {}).get(x) or 0) for x in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")) for r in rs]),
            "output_tokens_median": med([int((r.get("usage") or {}).get("output_tokens") or 0) for r in rs]),
            "models": sorted(set(r.get("model") for r in rs)), "permission_denials": sum(r.get("permission_denials") or 0 for r in rs)}
        res["errors"][arm] = {}
        for e in errors[arm]:
            res["errors"][arm][e["class"]] = res["errors"][arm].get(e["class"], 0) + 1
    res["errors"]["units"] = {}
    for e in unit_errors:
        res["errors"]["units"][e["class"]] = res["errors"]["units"].get(e["class"], 0) + 1

    # paired comparison on needle probes present in both arms
    a = {(r["prompt_id"], r["rep"]): r for r in rows["A"] if r["status"] == "ok"}
    b = {(r["prompt_id"], r["rep"]): r for r in rows["B"] if r["status"] == "ok"}
    keys = sorted(k for k in set(a) & set(b) if a[k]["tags"][0] != "negative")
    only_a = sum(1 for k in keys if a[k]["grade"]["correct"] and not b[k]["grade"]["correct"])
    only_b = sum(1 for k in keys if b[k]["grade"]["correct"] and not a[k]["grade"]["correct"])
    diffs_by_unit = {}
    for k in keys:
        diffs_by_unit.setdefault(a[k]["unit"], []).append(b[k]["grade"]["correct"] - a[k]["grade"]["correct"])
    d = [x for xs in diffs_by_unit.values() for x in xs]
    diff = sum(d) / float(len(d)) if d else None
    lo = hi = None
    if diffs_by_unit:
        rng = random.Random(seed)
        names = list(diffs_by_unit)
        stats = []
        for _ in range(boot):
            pick = [x for n in (rng.choice(names) for _ in names) for x in diffs_by_unit[n]]
            stats.append(sum(pick) / float(len(pick)))
        stats.sort()
        lo, hi = stats[int(0.025 * boot)], stats[int(0.975 * boot) - 1]
    cost_pairs = [(cost(a[k]), cost(b[k])) for k in set(a) & set(b)]
    res["paired"] = {"pairs": len(keys), "units": len(diffs_by_unit), "diff": diff, "ci": (lo, hi), "only_A": only_a, "only_B": only_b,
                     "mcnemar_p": mcnemar_p(only_a, only_b),
                     "cost_ratio_B_over_A": (sum(y for _, y in cost_pairs if y) / sum(x for x, _ in cost_pairs if x)) if cost_pairs and sum(x for x, _ in cost_pairs if x) else None}
    for field, store in (("kind", res["by_kind"]), ("pos", res["by_pos"])):
        idx = 0 if field == "kind" else 1
        groups = sorted(set(r["tags"][idx] for arm in rows for r in rows[arm]))
        for gname in groups:
            entry = {}
            for arm in ("A", "B"):
                rs = [r for r in rows[arm] if r["status"] == "ok" and r["tags"][idx] == gname]
                entry[arm] = {"n": len(rs), "correct": mean([r["grade"]["correct"] for r in rs]),
                              "wrong": mean([r["grade"]["wrong"] for r in rs]), "abstained": mean([r["grade"]["abstained"] for r in rs])}
            store[gname] = entry
    return res


def markdown(res):
    A, B, P = res["arms"].get("A", {}), res["arms"].get("B", {}), res["paired"]
    L = ["# autocompact 맥락 유지 A/B 결과", "", "실행 디렉터리: `%s`" % res["run"], ""]
    L += ["## 핵심 수치", "", "| | 훅 없음 (A) | ctx-index (B) |", "|---|---|---|"]

    def row(label, fa, fb):
        L.append("| %s | %s | %s |" % (label, fa, fb))
    row("세부 회상 정답률", "%s (95%% %s~%s, n=%d)" % (pct(A.get("recall")), pct(A.get("recall_ci", (None,))[0]), pct(A.get("recall_ci", (None, None))[1]), A.get("needle_n", 0)),
        "%s (95%% %s~%s, n=%d)" % (pct(B.get("recall")), pct(B.get("recall_ci", (None,))[0]), pct(B.get("recall_ci", (None, None))[1]), B.get("needle_n", 0)))
    row("오답(틀리거나 지어냄)", pct(A.get("wrong")), pct(B.get("wrong")))
    row("모름", pct(A.get("abstained")), pct(B.get("abstained")))
    row("대조 질문(없던 일) 정답률", pct(A.get("negative_correct")), pct(B.get("negative_correct")))
    row("질문 1개당 비용(사용량 기준 평균 / 중앙값)", "%s / %s" % (money(A.get("cost_per_probe_mean")), money(A.get("cost_per_probe_median"))),
        "%s / %s" % (money(B.get("cost_per_probe_mean")), money(B.get("cost_per_probe_median"))))
    row("정답 1개당 비용", money(A.get("cost_per_correct")), money(B.get("cost_per_correct")))
    row("질문 1개당 도구 호출(평균)", "%.2f" % (A.get("tool_calls_mean") or 0), "%.2f" % (B.get("tool_calls_mean") or 0))
    row("턴 파일을 읽은 질문 비율", pct(A.get("probes_reading_turn_files")), pct(B.get("probes_reading_turn_files")))
    row("트랜스크립트를 뒤진 질문 비율", pct(A.get("probes_reading_transcript")), pct(B.get("probes_reading_transcript")))
    row("응답 시간 중앙값", "%.1f초" % (A.get("latency_median_s") or 0), "%.1f초" % (B.get("latency_median_s") or 0))
    row("질문 1개당 입력 토큰 중앙값(캐시 포함)", "%s" % A.get("input_tokens_median"), "%s" % B.get("input_tokens_median"))
    L += ["", "짝지은 비교(같은 대화·같은 질문, 세부 질문 %d쌍, 세션 %d개): 정답률 차이 B − A = **%s** (95%% 부트스트랩 %s ~ %s), "
          "A만 정답 %d · B만 정답 %d, McNemar p = %.4g. 질문 비용 합계 비율 B/A = %s." % (
              P.get("pairs", 0), P.get("units", 0), pct(P.get("diff")), pct((P.get("ci") or (None, None))[0]), pct((P.get("ci") or (None, None))[1]),
              P.get("only_A", 0), P.get("only_B", 0), P.get("mcnemar_p", 1.0),
              ("%.2f" % P["cost_ratio_B_over_A"]) if P.get("cost_ratio_B_over_A") else "—"), ""]
    L += ["## 질문 종류별 정답률", "", "| 종류 | A 정답 | B 정답 | A 오답 | B 오답 | n(A/B) |", "|---|---|---|---|---|---|"]
    for k, e in res["by_kind"].items():
        L.append("| %s | %s | %s | %s | %s | %d/%d |" % (KIND_KO.get(k, k), pct(e["A"]["correct"]), pct(e["B"]["correct"]), pct(e["A"]["wrong"]),
                                                         pct(e["B"]["wrong"]), e["A"]["n"], e["B"]["n"]))
    L += ["", "## 위치별 정답률 (autocompact 발동 지점 대비)", "", "| 위치 | A 정답 | B 정답 | n(A/B) |", "|---|---|---|---|"]
    for k, e in res["by_pos"].items():
        if k == "none":
            continue
        L.append("| %s | %s | %s | %d/%d |" % (POS_KO.get(k, k), pct(e["A"]["correct"]), pct(e["B"]["correct"]), e["A"]["n"], e["B"]["n"]))
    L += ["", "## 세션(유닛)", "", "| 유닛 | 공유 빌드 턴 | 빌드 종료 토큰 | 빌드 비용 | 마무리 턴 A/B | 압축 전→후 토큰 A | 압축 전→후 토큰 B | 요약 길이 A/B | 목차 길이·단계 | 제외한 질문 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for name, u in res["units"].items():
        ua, ub = u["arms"].get("A", {}), u["arms"].get("B", {})
        L.append("| %s | %s | %s | %s | %s/%s | %s→%s | %s→%s | %s/%s | %s자 · %s | %s |" % (
            name, u["build_turns"], u["armed_at"], money(u["build_cost"]), ua.get("tail_turns"), ub.get("tail_turns"), ua.get("pre_tokens"), ua.get("post_tokens"),
            ub.get("pre_tokens"), ub.get("post_tokens"), ua.get("summary_chars"), ub.get("summary_chars"), ub.get("index_chars"),
            ub.get("index_stage"), ", ".join(sorted(u["invalid_probes"])) or "없음"))
    L += ["", "## 비용과 오류", "",
          "- 질문 비용 합계: A %s, B %s (CLI 보고값 A %s, B %s)" % (money(A.get("cost_total")), money(B.get("cost_total")), money(A.get("cost_cli_total")), money(B.get("cost_cli_total"))),
          "- 빌드 비용 합계: %s (CLI 보고값 %s) · 압축까지의 마무리 턴 비용 합계: %s" % (
              money(sum(u["build_cost"] for u in res["units"].values())), money(sum((u["build_cost_cli"] or 0) for u in res["units"].values())),
              money(sum(x.get("compact_cost") or 0 for u in res["units"].values() for x in u["arms"].values()))),
          "- 응답 모델: A %s, B %s" % (A.get("models"), B.get("models")),
          "- 오류(재시도 포함 시도 단위): A %s, B %s, 유닛 %s" % (res["errors"].get("A") or "없음", res["errors"].get("B") or "없음", res["errors"].get("units") or "없음"),
          "- 잘린 답(max_tokens): A %d, B %d · 권한 거부: A %d, B %d" % (A.get("truncated", 0), B.get("truncated", 0), A.get("permission_denials", 0), B.get("permission_denials", 0))]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Summarise an autocompact retention eval run.")
    ap.add_argument("run")
    ap.add_argument("--json")
    a = ap.parse_args()
    res = analyze(a.run)
    sys.stdout.write(markdown(res))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
