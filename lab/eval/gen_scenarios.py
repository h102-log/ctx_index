#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the synthetic sessions of the autocompact retention eval (deterministic per seed).

    python3 lab/eval/gen_scenarios.py              write lab/eval/CASES.md (the reviewable case list)
    python3 lab/eval/gen_scenarios.py --check      exit 1 if CASES.md differs from a fresh generation
    python3 lab/eval/gen_scenarios.py --dump DIR   also write the full scenarios as DIR/sNN.json

The runner imports build_all(); the multi-megabyte scenario texts are regenerated, never committed.

A scenario is a Korean development session. Filler turns (a pasted log, config, code module, metrics
table or meeting notes with a short analysis request, or a one-line remark) carry the context towards
the autocompact threshold. Needle turns plant the details the probes ask about after compaction.
The runner sends a needle turn once the context passes its target position, a fraction of the
compaction threshold, so "early" and "late" keep their meaning whatever the real token counts are.
Every value comes from a seeded generator, so nothing can be answered from memory.

Probe kinds:
  order             which service the first pasted log came from
  paste_value       a value inside a long paste (early / mid / late)
  user_fact         a short fact the user stated
  constraint        a directory the user said must never be modified
  assistant_derived a result the assistant itself read off a pasted table
  verbatim          a long request, to be quoted word for word
  decision_reason   the threshold the user gave as the reason for a decision
  negative          something that never came up (the right answer is "not in the record")
"""
import argparse
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "CASES.md")
FILLER_TURNS = 120          # far more than a session needs; the runner stops once the session is armed
PASTE_CHARS = 24000         # target size of one pasted block
SHORT_SHARE = 0.25          # share of filler turns that are a one-line remark without a paste
TAIL_TURNS = 12             # paste turns that carry each arm from the build's stop point into autocompact

THEMES = [
    {"id": "s01", "seed": 1101, "title": "결제 서비스 장애 분석", "topic": "결제",
     "services": ["payment-api", "gateway-proxy", "ledger-writer", "refund-worker", "notify-svc"],
     "endpoints": ["/v1/charges", "/v1/refunds", "/v1/captures", "/v1/payouts", "/v1/disputes", "/v1/webhooks"],
     "guard_dir": "ledger", "guard_reason": "회계 감사 대상이라 변경 이력이 남으면 안 돼",
     "db": "결제 DB", "cfg_file": "payment-service.yaml", "cfg_key": "retry.backoff_ms", "retry_topic": "결제 재시도",
     "exc": "LedgerWriteException", "exc_prefix": "LDG", "trace_svc": "ledger-writer",
     "plan_a": "이중 기록(A안)", "plan_b": "CDC 방식(B안)", "metric": "쓰기 지연"},
    {"id": "s02", "seed": 1202, "title": "주문 DB 마이그레이션 계획", "topic": "주문 DB 마이그레이션",
     "services": ["order-api", "order-migrator", "inventory-api", "cart-svc", "billing-sync"],
     "endpoints": ["/orders", "/orders/{id}/items", "/carts/{id}", "/inventory/reserve", "/billing/sync", "/orders/search"],
     "guard_dir": "migrations/applied", "guard_reason": "이미 운영에 적용된 스크립트라 손대면 체크섬이 깨져",
     "db": "주문 DB", "cfg_file": "migrator.yaml", "cfg_key": "batch.rows_per_chunk", "retry_topic": "청크 복사 재시도",
     "exc": "ChunkCopyException", "exc_prefix": "MIG", "trace_svc": "order-migrator",
     "plan_a": "일괄 복사(A안)", "plan_b": "점진 백필(B안)", "metric": "복제 지연"},
    {"id": "s03", "seed": 1303, "title": "검색 API 지연 분석", "topic": "검색 지연",
     "services": ["search-api", "query-planner", "index-builder", "suggest-svc", "ranking-svc"],
     "endpoints": ["/search", "/search/suggest", "/search/facets", "/index/refresh", "/rank/score", "/search/export"],
     "guard_dir": "index-snapshots", "guard_reason": "복구용 스냅숏이라 덮어쓰면 되돌릴 수 없어",
     "db": "검색 메타 DB", "cfg_file": "search-api.yaml", "cfg_key": "cache.ttl_seconds", "retry_topic": "샤드 질의 재시도",
     "exc": "ShardTimeoutException", "exc_prefix": "SRH", "trace_svc": "query-planner",
     "plan_a": "샤드 증설(A안)", "plan_b": "쿼리 캐시 도입(B안)", "metric": "p95 지연"},
    {"id": "s04", "seed": 1404, "title": "인증 서버 점검", "topic": "인증 서버",
     "services": ["auth-api", "token-issuer", "session-store", "mfa-svc", "audit-logger"],
     "endpoints": ["/oauth/token", "/oauth/revoke", "/session/refresh", "/mfa/verify", "/users/me", "/audit/events"],
     "guard_dir": "keys/rotation", "guard_reason": "키 순환 스크립트라 실수하면 전체 로그인이 막혀",
     "db": "세션 DB", "cfg_file": "auth-server.yaml", "cfg_key": "token.refresh_window_s", "retry_topic": "토큰 재발급",
     "exc": "TokenSignException", "exc_prefix": "AUT", "trace_svc": "token-issuer",
     "plan_a": "세션 고정(A안)", "plan_b": "토큰 재발급 지연(B안)", "metric": "로그인 지연"},
    {"id": "s05", "seed": 1505, "title": "모바일 앱 크래시 분석", "topic": "앱 크래시",
     "services": ["app-backend", "push-svc", "media-upload", "profile-api", "feed-svc"],
     "endpoints": ["/feed", "/feed/next", "/profile/{id}", "/media/upload", "/push/register", "/feed/like"],
     "guard_dir": "release/signing", "guard_reason": "스토어 서명 설정이라 바뀌면 배포가 막혀",
     "db": "프로필 DB", "cfg_file": "app-backend.yaml", "cfg_key": "upload.chunk_kb", "retry_topic": "업로드 재시도",
     "exc": "MediaDecodeException", "exc_prefix": "APP", "trace_svc": "media-upload",
     "plan_a": "강제 업데이트(A안)", "plan_b": "서버 측 우회(B안)", "metric": "업로드 지연"},
    {"id": "s06", "seed": 1606, "title": "데이터 파이프라인 지연", "topic": "파이프라인 지연",
     "services": ["ingest-api", "etl-runner", "warehouse-loader", "scheduler", "report-svc"],
     "endpoints": ["/ingest/batch", "/ingest/stream", "/etl/jobs", "/load/commit", "/reports/daily", "/scheduler/runs"],
     "guard_dir": "dags/prod", "guard_reason": "운영 DAG라 바꾸면 야간 정산이 틀어져",
     "db": "적재 DB", "cfg_file": "etl-runner.yaml", "cfg_key": "retry.max_attempts", "retry_topic": "적재 재시도",
     "exc": "LoadCommitException", "exc_prefix": "ETL", "trace_svc": "warehouse-loader",
     "plan_a": "전체 재적재(A안)", "plan_b": "증분 적재(B안)", "metric": "적재 지연"},
]

LEVELS = ["INFO"] * 14 + ["WARN"] * 3 + ["ERROR"]
METHODS = ["GET"] * 5 + ["POST"] * 3 + ["PUT", "DELETE"]
STATUSES = [200] * 30 + [201] * 4 + [204] * 2 + [400, 401, 403, 404, 429, 500, 502, 503, 504]
SHORT_REMARKS = [
    "좋아, 다음으로 넘어가자.", "그 부분은 나중에 다시 보자.", "고마워. 계속하자.", "알겠어, 그 방향으로 가자.",
    "음, 일단 메모만 해 두고 넘어가자.", "좋아. 다음 자료 줄게.", "그건 팀에 공유해 둘게. 계속하자.", "오케이, 이해했어.",
]
PASTE_ASKS = {
    "log": ["이 {svc} 로그에서 눈에 띄는 패턴을 세 줄 이내로 짚어 줘.", "{svc} 로그 일부야. 오류가 몰린 구간이 있는지만 짧게 봐 줘.",
            "이건 {svc} 쪽 로그야. 이상한 점 두 가지만 짧게 알려 줘."],
    "config": ["이 설정에서 위험해 보이는 값이 있으면 두세 개만 짧게 알려 줘.", "{svc} 설정 파일이야. 운영에 안 맞아 보이는 값만 짧게 짚어 줘."],
    "code": ["이 코드에서 버그가 생길 만한 곳 두 군데만 짧게 짚어 줘.", "{svc} 모듈 코드야. 동시성 문제가 있을 만한 부분만 짧게 봐 줘."],
    "metrics": ["이 지표에서 이상한 구간만 짧게 알려 줘.", "{svc} 지표 덤프야. 추세가 꺾이는 지점만 짧게 짚어 줘."],
    "notes": ["회의록이야. 세 줄로 요약해 줘.", "어제 논의 기록이야. 합의된 것만 짧게 뽑아 줘."],
}
WORDS = ("cache retry queue shard lease token batch window cursor offset checksum quota budget backoff pool "
         "writer reader planner snapshot replica index session upload decode stream").split()
NOTE_LINES = [
    "{a}님: {svc} 배포는 다음 주 화요일 오전으로 미루자는 의견이 나왔습니다.", "{a}님: 알림 임계값을 낮추면 야간 호출이 늘어날 수 있다고 우려했습니다.",
    "{a}님: 지난 장애 회고 문서에 원인 분석이 아직 비어 있다고 했습니다.", "{a}님: {svc} 담당자 교체 일정은 아직 미정입니다.",
    "{a}님: 테스트 환경의 데이터가 오래돼서 재현이 어렵다고 했습니다.", "{a}님: 비용 보고는 월말에 한 번에 하자고 했습니다.",
    "{a}님: 대시보드 지표 이름을 통일하자는 제안이 있었습니다.", "{a}님: 다음 회의에서 롤백 절차를 다시 점검하기로 했습니다.",
]
NAMES = ["김하늘", "이도윤", "박서준", "최유나", "한민재", "오지우", "윤세린", "서태오"]
# "negative" probes ask about things that never appear anywhere in the session
NEGATIVES = [("Kafka", "아까 정한 Kafka 컨슈머 그룹 이름이 뭐였지? 짧게 답해 줘."),
             ("Grafana", "내가 공유했던 Grafana 대시보드 UID가 뭐였지? 짧게 답해 줘.")]
# A value "stands alone" unless glued to letters, digits or path characters; grade.py uses the same
# matcher. mode "dir" also accepts one trailing slash ("ledger" matches "ledger/" but not "ledger-writer");
# mode "num" also accepts a unit right after the number, so "44" matches "44ms", "44 ms" and "44밀리초"
# but not "144", "u4412" or the inside of a hex id such as "a3992b".
EDGE = r"0-9A-Za-z_/{}.\-"


def standalone(text, value, mode="token"):
    if mode == "num":
        pat = r"(?<![0-9A-Za-z.])%s(?:(?![0-9A-Za-z])|(?=(?:ms|s|sec|kb|KB)(?![0-9A-Za-z])))" % re.escape(value)
    else:
        pat = r"(?<![%s])%s%s(?![%s])" % (EDGE, re.escape(value), "/?" if mode == "dir" else "", EDGE)
    return len(re.findall(pat, text))


class Gen(object):
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.used = set()

    def unique(self, make):
        while True:
            v = make()
            if v not in self.used:
                self.used.add(v)
                return v

    def hexid(self, n=10):
        return self.unique(lambda: "".join(self.r.choice("0123456789abcdef") for _ in range(n)))

    def num(self, lo, hi):
        return self.unique(lambda: str(self.r.randint(lo, hi)))

    def ts(self, base_h, i):
        s = base_h * 3600 + i * 3
        return "2026-03-12T%02d:%02d:%02d.%03dZ" % ((s // 3600) % 24, (s // 60) % 60, s % 60, self.r.randint(0, 999))


# Numbers in fillers stay below 3000 (latencies, counts) or come from Gen.num, so the planted
# values (config 3000-4999, ports 5000-6999, codes and hex ids) can never show up by accident.

def log_paste(g, th, svc, chars, plant=None):
    """A request log of one service; plant=(status, trace) puts exactly one line with that status."""
    lines, i, h = [], 0, g.r.randint(1, 20)
    want = None if plant is None else g.r.randint(40, 120)
    while sum(len(x) + 1 for x in lines) < chars or (want is not None and i <= want):
        if i == want:
            status, trace = plant
        else:
            status = g.r.choice(STATUSES)
            if plant is not None and status == plant[0]:
                status = 200
            trace = g.hexid()
        lvl = "ERROR" if status >= 500 else ("WARN" if status >= 400 else g.r.choice(LEVELS))
        lines.append("%s %-5s %s [req=r%s] %s %s status=%d latency_ms=%d trace=%s user=u%05d" % (
            g.ts(h, i), lvl, svc, g.hexid(6), g.r.choice(METHODS), g.r.choice(th["endpoints"]), status,
            g.r.randint(4, 2400), trace, g.r.randint(10000, 99999)))
        i += 1
    return "\n".join(lines)


def config_paste(g, th, svc, chars, plant=None):
    """A YAML config; plant=(section.key, value) puts that section once, among random two-word sections."""
    out = ["# %s" % (th["cfg_file"] if plant else svc + ".yaml"), "service: %s" % svc]
    plant_at, n = g.r.randint(5, 9), 0
    while sum(len(x) + 1 for x in out) < chars or (plant and n <= plant_at):
        if plant and n == plant_at:
            sec, key = plant[0].split(".")
            out += ["%s:" % sec, "  %s: %s" % (key, plant[1]), "  timeout_ms: %s" % g.num(1000, 2999)]
        else:
            out.append("%s_%s:" % (g.r.choice(WORDS), g.r.choice(WORDS)))
            for _ in range(g.r.randint(4, 9)):
                k = "%s_%s" % (g.r.choice(WORDS), g.r.choice(["ms", "count", "limit", "ratio", "enabled", "size", "name"]))
                v = g.r.choice([str(g.r.randint(1, 2999)), "true", "false", "%.2f" % g.r.random(), '"%s-%s"' % (g.r.choice(WORDS), g.hexid(4))])
                out.append("  %s: %s" % (k, v))
        n += 1
    return "\n".join(out)


def code_paste(g, svc, chars):
    out = ['"""%s - %s module."""' % (svc, g.r.choice(WORDS)), "import time", "import threading", ""]
    while sum(len(x) + 1 for x in out) < chars:
        a, b = g.r.choice(WORDS), g.r.choice(WORDS)
        out += ["", "def %s_%s(%s, %s, retries=%d):" % (g.r.choice(WORDS), g.r.choice(WORDS), a, b, g.r.randint(1, 7)),
                "    lock = threading.Lock()", "    for attempt in range(retries):", "        with lock:",
                "            if %s.get(%r) is None:" % (a, b), "                time.sleep(%d / 1000.0)" % g.r.randint(10, 900),
                "                continue", "            %s[%r] = %s.pop(%r, %d)" % (a, b, b, a, g.r.randint(0, 99)),
                "    return %s" % a]
    return "\n".join(out)


def metrics_paste(g, th, chars, plant=None):
    """CSV of per-endpoint latency; plant=endpoint makes that endpoint the single highest p99_ms."""
    out = ["minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate"]
    while sum(len(x) + 1 for x in out) < chars:
        for ep in th["endpoints"]:
            p50 = g.r.randint(8, 120)
            p95 = p50 + g.r.randint(20, 400)
            p99 = min(p95 + g.r.randint(10, 900), 1890)
            out.append("%02d:%02d,%s,%d,%d,%d,%d,%.4f" % (g.r.randint(0, 23), g.r.randint(0, 59), ep, g.r.randint(5, 900),
                                                       p50, p95, p99, g.r.random() / 50))
    top = None
    if plant is not None:
        top = 1890 + g.r.randint(150, 900)
        out.insert(g.r.randint(3, len(out) - 2), "%02d:%02d,%s,%d,95,640,%d,0.0123" % (g.r.randint(0, 23), g.r.randint(0, 59),
                                                                                       plant, g.r.randint(5, 900), top))
    return "\n".join(out), top


def notes_paste(g, svc, chars):
    out = ["# 회의록 (%s)" % svc]
    while sum(len(x) + 1 for x in out) < chars:
        out.append("- " + g.r.choice(NOTE_LINES).format(a=g.r.choice(NAMES), svc=svc))
    return "\n".join(out)


def stack_paste(g, th, code):
    pkg = th["trace_svc"].replace("-", "")
    frames = ["    at com.example.%s.%s%s.%s(%s.java:%d)" % (pkg, g.r.choice(WORDS).capitalize(), g.r.choice(WORDS).capitalize(),
                                                          g.r.choice(WORDS), g.r.choice(WORDS).capitalize(), g.r.randint(20, 900))
              for _ in range(g.r.randint(28, 40))]
    head = "%s ERROR %s: %s: code=%s message=\"%s %s failed after %d attempts\"" % (
        g.ts(g.r.randint(1, 20), 7), th["trace_svc"], th["exc"], code, g.r.choice(WORDS), g.r.choice(WORDS), g.r.randint(2, 6))
    return "\n".join([head] + frames + ["Caused by: java.net.SocketTimeoutException: Read timed out"] + frames[:6])


def block(text):
    return "```\n%s\n```" % text


def scenario(th):
    g = Gen(th["seed"])
    svc = th["services"]
    first_svc = g.r.choice(svc)
    # needle values first, so fillers drawn later can never repeat them
    trace409 = g.hexid()
    port_stg, port_prd = g.num(5000, 6999), g.num(5000, 6999)
    cfg_val = g.num(3000, 4999)
    top_ep = g.r.choice(th["endpoints"])
    exc_code = "%s-%s" % (th["exc_prefix"], g.num(7000, 9999))
    limit_ms = g.num(11, 48)
    gw_s, cl_s = g.num(21, 39), g.num(5, 9)
    chan = "#%s-alerts-%s" % (svc[0].split("-")[0], g.hexid(3))
    verbatim = ("%s 정책을 바꾸기 전에 세 가지를 먼저 확인하고 싶어. 첫째, 게이트웨이 타임아웃 %s초와 클라이언트 타임아웃 %s초의 차이 때문에 "
                "같은 요청이 두 번 처리되는지. 둘째, 재시도할 때마다 idempotency key가 새로 만들어지는지. 셋째, 실패 알림이 %s 채널로 제대로 "
                "가는지. 이 세 가지를 확인하기 전에는 코드를 바꾸지 말아 줘." % (th["retry_topic"], gw_s, cl_s, chan))
    needles, probes = [], []

    def needle(nid, frac, text, **extra):
        d = {"id": nid, "target_frac": frac, "text": text}
        d.update(extra)
        needles.append(d)

    needle("n1", 0.0, "%s 건을 같이 보자. 먼저 %s 로그부터 붙여넣을게. 전체적으로 어떤 오류가 많은지 짧게 정리해 줘.\n\n%s" % (
        th["topic"], first_svc, block(log_paste(g, th, first_svc, PASTE_CHARS, plant=(409, trace409)))))
    probes.append({"id": "order", "kind": "order", "needle": "n1", "pos": "early",
                   "question": "이번 세션에서 내가 맨 처음 붙여넣은 로그는 어느 서비스의 로그였지? 짧게 답해 줘.",
                   "gold": [first_svc], "distractors": [s for s in svc if s != first_svc]})
    probes.append({"id": "paste_early", "kind": "paste_value", "needle": "n1", "pos": "early",
                   "question": "맨 처음 붙여넣은 %s 로그에서 status=409였던 요청의 trace 값이 뭐였지? 짧게 답해 줘." % first_svc,
                   "gold": [trace409], "distractors": []})
    needle("n2", 0.10, "참고로 스테이징 %s 포트는 %s번이고, 운영 %s 포트는 %s번이야. 나중에 스크립트 짤 때 이 값 써야 하니까 기억해 둬." % (
        th["db"], port_stg, th["db"], port_prd))
    probes.append({"id": "user_fact", "kind": "user_fact", "needle": "n2", "pos": "early", "match": "num",
                   "question": "스테이징 %s 포트가 몇 번이었지? 짧게 답해 줘." % th["db"], "gold": [port_stg], "distractors": [port_prd]})
    needle("n3", 0.22, "아 그리고 중요한 거. 앞으로 %s/ 디렉터리 아래 파일은 절대 수정하지 마. %s." % (th["guard_dir"], th["guard_reason"]))
    probes.append({"id": "constraint", "kind": "constraint", "needle": "n3", "pos": "early", "match": "dir",
                   "question": "내가 절대 수정하지 말라고 했던 디렉터리가 어디였지? 짧게 답해 줘.", "gold": [th["guard_dir"]], "distractors": []})
    table, top_val = metrics_paste(g, th, PASTE_CHARS // 2, plant=top_ep)
    needle("n4", 0.35, "엔드포인트별 지연 지표야. 이 표 전체에서 p99_ms가 가장 높은 행의 엔드포인트와 그 값을 찾아 줘.\n\n%s" % block(table),
           derived_gold=[top_ep, str(top_val)])
    probes.append({"id": "derived", "kind": "assistant_derived", "needle": "n4", "pos": "mid",
                   "question": "아까 네가 지연 지표 표에서 찾아 준, p99가 가장 높았던 엔드포인트가 어디였지? 짧게 답해 줘.",
                   "gold": [top_ep], "distractors": [e for e in th["endpoints"] if e != top_ep], "requires_answer_contains": top_ep})
    needle("n5", 0.48, verbatim)
    probes.append({"id": "verbatim", "kind": "verbatim", "needle": "n5", "pos": "mid",
                   "question": "내가 %s 정책을 바꾸기 전에 먼저 확인하고 싶다고 했던 요청을 원문 그대로 다시 보여줘." % th["retry_topic"],
                   "gold_text": verbatim})
    needle("n6", 0.60, "이건 %s 설정 파일 전체야. 운영 반영 전에 위험한 값이 있는지 짧게 봐 줘.\n\n%s" % (
        th["cfg_file"], block(config_paste(g, th, svc[0], PASTE_CHARS, plant=(th["cfg_key"], cfg_val)))))
    probes.append({"id": "paste_mid", "kind": "paste_value", "needle": "n6", "pos": "mid", "match": "num",
                   "question": "아까 붙여넣은 %s 설정에서 %s 값이 얼마였지? 짧게 답해 줘." % (th["cfg_file"], th["cfg_key"]),
                   "gold": [cfg_val], "distractors": []})
    needle("n7", 0.74, "결론적으로 %s 대신 %s으로 가자. %s이 %sms를 넘으면 안 되거든. 이 기준은 팀에도 그대로 공유할 거야." % (
        th["plan_a"], th["plan_b"], th["metric"], limit_ms))
    probes.append({"id": "decision", "kind": "decision_reason", "needle": "n7", "pos": "late", "match": "num",
                   "question": "%s으로 정하면서 내가 기준으로 말한 %s 상한이 몇 ms였지? 짧게 답해 줘." % (th["plan_b"], th["metric"]),
                   "gold": [limit_ms], "distractors": []})
    needle("n8", 0.88, "방금 %s에서 난 스택 트레이스야. 원인이 뭐로 보이는지 짧게 알려 줘.\n\n%s" % (th["trace_svc"], block(stack_paste(g, th, exc_code))))
    probes.append({"id": "paste_late", "kind": "paste_value", "needle": "n8", "pos": "late",
                   "question": "%s 스택 트레이스에 찍혀 있던 예외 코드(code=...)가 뭐였지? 짧게 답해 줘." % th["trace_svc"],
                   "gold": [exc_code], "distractors": []})
    for i, (word, q) in enumerate(NEGATIVES, 1):
        probes.append({"id": "negative%d" % i, "kind": "negative", "needle": None, "pos": "none", "question": q, "absent_word": word})

    fillers = []
    for i in range(FILLER_TURNS):
        fid = "f%03d" % (i + 1)
        if g.r.random() < SHORT_SHARE:
            fillers.append({"id": fid, "kind": "short", "text": g.r.choice(SHORT_REMARKS)})
            continue
        kind = g.r.choice(["log", "log", "config", "code", "metrics", "notes"])
        s = g.r.choice(svc)
        size = g.r.randint(int(PASTE_CHARS * 0.7), int(PASTE_CHARS * 1.2))
        body = {"log": lambda: log_paste(g, th, s, size), "config": lambda: config_paste(g, th, s, size),
                "code": lambda: code_paste(g, s, size), "metrics": lambda: metrics_paste(g, th, size)[0],
                "notes": lambda: notes_paste(g, s, size // 3)}[kind]()
        fillers.append({"id": fid, "kind": kind, "text": "%s\n\n%s" % (g.r.choice(PASTE_ASKS[kind]).format(svc=s), block(body))})

    # tail turns: sent in each arm after the shared build, one at a time, until the CLI compacts by itself.
    # They ask for a one-word reply so the two arms' last turns stay as alike as possible.
    tail = []
    for i in range(TAIL_TURNS):
        s = g.r.choice(svc)
        tail.append({"id": "t%02d" % (i + 1), "kind": "tail",
                     "text": "참고용으로 남겨 둘 %s 로그야. 이번에는 분석하지 말고 '확인'이라고만 답해 줘.\n\n%s" % (
                         s, block(log_paste(g, th, s, PASTE_CHARS)))})
    sc = {"id": th["id"], "title": th["title"], "seed": th["seed"], "needles": needles, "fillers": fillers, "tail": tail,
          "probes": probes}
    check_scenario(sc)
    return sc


def check_scenario(sc):
    """Guard rails: each gold is planted where intended and nowhere else; negatives never appear."""
    texts = [n["text"] for n in sc["needles"]] + [f["text"] for f in sc["fillers"]] + [t["text"] for t in sc["tail"]]
    blob = "\n".join(texts)
    for p in sc["probes"]:
        if p["kind"] == "negative":
            assert p["absent_word"].lower() not in blob.lower(), (sc["id"], p["id"])
            continue
        nd = [n for n in sc["needles"] if n["id"] == p["needle"]][0]
        if p["kind"] == "verbatim":
            assert blob.count(p["gold_text"]) == 1, (sc["id"], p["id"])
            continue
        for gval in p["gold"]:
            assert standalone(nd["text"], gval, p.get("match", "token")) >= 1, (sc["id"], p["id"], gval)
            if p["kind"] in ("paste_value", "user_fact"):
                assert standalone(blob, gval, p.get("match", "token")) == 1, (sc["id"], p["id"], gval, "a planted value must appear exactly once")
            if p["kind"] == "decision_reason":
                assert blob.count(gval + "ms") == 1, (sc["id"], p["id"], gval)
            if p["kind"] == "constraint":
                assert blob.count(gval + "/") == 1, (sc["id"], p["id"], gval)


def cases_md(scs):
    L = ["# 질문 세트 — autocompact 맥락 유지 실험", "",
         "`gen_scenarios.py`가 시드로 만드는 세션 %d개의 심은 세부와 질문입니다. 값은 모두 무작위라 기억만으로는 맞힐 수 없습니다. "
         "채움 턴(긴 붙여넣기와 짧은 분석 요청, 한 줄 대답)에는 질문 대상이 없어서 수와 예시만 적습니다. "
         "위치는 autocompact 발동 지점(400K 창에서 약 350K 토큰) 대비 비율이며, 실행기는 대화가 그 비율에 닿은 다음 턴에 해당 요청을 보냅니다. "
         "공유 빌드는 약 330K 토큰에서 멈추고, 두 조건은 각각 같은 '참고용 로그 — 확인이라고만 답해 줘' 턴을 차례로 받다가 CLI가 스스로 autocompact하는 지점에서 압축됩니다." % len(scs), "",
         "| 세션 | 주제 | 질문 수 | 준비된 채움 턴 |", "|---|---|---|---|"]
    for sc in scs:
        L.append("| %s | %s | %d | %d |" % (sc["id"], sc["title"], len(sc["probes"]), len(sc["fillers"])))
    L += ["", "**채점** (`grade.py`, 판정 모델 없음)", "",
          "- 세부 질문: 정답 값이 답에 독립된 토큰으로 있으면 정답. 없고 '찾을 수 없다 / 기록에 없다 / 모르겠다' 류의 표현이 있으면 모름, 둘 다 아니면 오답(지어냄). "
          "다른 후보를 둘 이상 늘어놓으면 정답으로 치지 않습니다.",
          "- 원문 인용: 원래 요청 문장이 답에 순서대로 90% 이상 들어 있으면 정답.",
          "- 대조 질문(`negative`): 세션에 한 번도 나오지 않은 내용입니다. '기록에 없다'고 답하면 정답, 무언가를 지어내면 오답.",
          "- `assistant_derived`: 압축 전 그 턴에서 모델이 실제로 정답을 말한 경우에만 셉니다. 두 조건이 같은 대화를 공유하므로 양쪽에서 똑같이 걸러집니다.", ""]
    for sc in scs:
        L += ["## %s %s" % (sc["id"], sc["title"]), "", "| 질문 | 종류 | 위치 | 심은 턴(목표 위치) | 정답 |", "|---|---|---|---|---|"]
        for p in sc["probes"]:
            nd = [n for n in sc["needles"] if n["id"] == p.get("needle")]
            where = "%s (%d%%)" % (nd[0]["id"], round(nd[0]["target_frac"] * 100)) if nd else "—"
            gold = "아래 n5 원문" if p["kind"] == "verbatim" else ("'기록에 없음'" if p["kind"] == "negative" else " / ".join("`%s`" % x for x in p["gold"]))
            L.append("| %s | %s | %s | %s | %s |" % (p["question"].replace("|", "\\|"), p["kind"], p["pos"], where, gold))
        L += ["", "심은 턴의 요청문(붙여넣기는 앞 3줄만):", ""]
        for n in sc["needles"]:
            head, _, rest = n["text"].partition("```")
            text = head.strip()
            if rest:
                lines = rest.strip("\n").split("\n")
                text += "\n\n" + "\n".join(lines[:3]) + "\n… (%d줄 더)" % max(0, len(lines) - 4)
            L += ["- **%s** (목표 %d%%)" % (n["id"], round(n["target_frac"] * 100)), "", "````text", text, "````", ""]
        ex = [f for f in sc["fillers"] if f["kind"] != "short"][0]
        L += ["채움 턴 예시 (%s, %s, 첫 400자):" % (ex["id"], ex["kind"]), "", "````text", ex["text"][:400] + "\n…", "````", ""]
    return "\n".join(L) + "\n"


def build_all():
    return [scenario(th) for th in THEMES]


def main():
    ap = argparse.ArgumentParser(description="Generate the autocompact retention eval sessions.")
    ap.add_argument("--check", action="store_true", help="exit 1 if CASES.md differs from a fresh generation")
    ap.add_argument("--dump", metavar="DIR", help="also write the full scenarios as DIR/sNN.json")
    a = ap.parse_args()
    scs = build_all()
    md = cases_md(scs)
    if a.check:
        same = os.path.isfile(CASES) and open(CASES, encoding="utf-8").read() == md
        print("CASES.md %s" % ("matches the generator" if same else "differs from the generator"))
        sys.exit(0 if same else 1)
    with open(CASES, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    if a.dump:
        os.makedirs(a.dump, exist_ok=True)
        for sc in scs:
            with open(os.path.join(a.dump, sc["id"] + ".json"), "w", encoding="utf-8", newline="\n") as f:
                json.dump(sc, f, ensure_ascii=False, indent=1)
    for sc in scs:
        print("%s %-16s needles=%d probes=%d fillers=%d (%.1f MB filler text)" % (
            sc["id"], sc["title"], len(sc["needles"]), len(sc["probes"]), len(sc["fillers"]),
            sum(len(f["text"]) for f in sc["fillers"]) / 1e6))


if __name__ == "__main__":
    main()
