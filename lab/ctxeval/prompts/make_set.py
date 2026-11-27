# 수동 A/B 실행용 프롬프트 세트 s02를 만든다.
# p01~p16: 붙여 넣을 로그, q01~q10: 압축 뒤 질문, answers.md: 정답표.
import pathlib
import random
import re

OUT = pathlib.Path(__file__).parent / "s02"
# [이유] r01 실측(2026-11-27, claude-opus-5-5, 대화형, 창 400K): 시작 사용량 약 53K, 420줄 프롬프트 하나가 약 27K 토큰,
#        11개를 보낸 뒤 354.6K였고 12번째를 보낼 때 자동 압축됐다.
LINES = 420
rng = random.Random(20261127)
pick = random.Random(7)  # 질문 대상을 고르는 데만 쓴다. 로그 내용을 만드는 rng와 섞지 않는다.

TOPICS = [  # (서비스, 노드 접두어, 제목, 날짜) — 순서가 곧 프롬프트 번호
    ("pay-gw", "pg", "결제 게이트웨이(pay-gw) v4.18 배포 구간", "2026-10-05"),
    ("auth-svc", "as", "인증 서비스(auth-svc) 토큰 갱신 장애 구간", "2026-10-06"),
    ("order-db", "od", "주문 DB(order-db) 스키마 마이그레이션 구간", "2026-10-07"),
    ("settle-batch", "sb", "정산 배치(settle-batch) 야간 실행 구간", "2026-10-08"),
    ("img-resize", "ir", "이미지 리사이저(img-resize) 캐시 점검 구간", "2026-10-09"),
    ("notify-worker", "nw", "알림 워커(notify-worker) 큐 적체 구간", "2026-10-10"),
    ("log-collector", "lc", "로그 수집기(log-collector) 디스크 점검 구간", "2026-10-11"),
    ("reco-serve", "rs", "추천 서빙(reco-serve) 카나리 구간", "2026-10-12"),
    ("stock-sync", "ss", "재고 동기화(stock-sync) API 점검 구간", "2026-10-13"),
    ("mail-relay", "mr", "메일 발송기(mail-relay) 반송 처리 구간", "2026-10-14"),
    ("backup-job", "bj", "백업 작업(backup-job) 주간 실행 구간", "2026-10-15"),
    ("cdn-purge", "cp", "CDN 무효화(cdn-purge) 처리 구간", "2026-10-16"),
    ("session-store", "st", "세션 저장소(session-store) 페일오버 구간", "2026-10-17"),
    ("edge-gw", "eg", "API 게이트웨이(edge-gw) 레이트 리밋 구간", "2026-10-18"),
    ("report-gen", "rg", "리포트 생성기(report-gen) 실행 구간", "2026-10-19"),
    ("cron-hub", "ch", "스케줄러(cron-hub) 실행 구간", "2026-10-20"),
]

# [의도] 질문 대상을 눈에 띄는 줄로 따로 심지 않고 평범한 줄에서 고른다. 대상은 p01~p08에만 둔다.
# [이유] r01(세트 s01)에서 확인: 하나뿐인 key·rule로 심은 줄 7개를 압축 요약이 "특이 항목"으로 원문 그대로 옮겼다.
#        요약은 10번째 프롬프트 중간까지만 다뤘고, 그 뒤부터 12번째까지는 요약 없이 원문으로 남았다.
TARGETS = {  # 프롬프트 번호 -> (종류, 줄을 고르는 정규식, 질문 틀, 정답 틀). key 그룹은 세트 전체에서 한 번만 나와야 한다.
    1: ("요청 줄 · id로 찾기",
        r"request done id=(?P<key>req-\w+) .* latency_ms=(?P<a>\d+)$",
        "아까 붙여 준 결제 게이트웨이(pay-gw) 로그에서 요청 {key} 의 latency_ms 가 얼마였지?", "{a}"),
    2: ("티켓 줄 · id로 찾기",
        r"ticket linked id=(?P<key>OPS-\d+) reason=(?P<a>\w+)$",
        "아까 붙여 준 인증 서비스(auth-svc) 로그에서 {key} 티켓은 어떤 사유(reason)로 연결됐지?", "{a}"),
    3: ("백업 줄 · 파일 경로로 찾기",
        r"backup finished file=(?P<key>\S+) size_mb=\d+ checksum=(?P<a>\w+)$",
        "아까 붙여 준 주문 DB(order-db) 로그에서 백업 파일 {key} 의 checksum 이 뭐였지?", "{a}"),
    4: ("pool resize 줄 · 시각으로 찾기",
        r"T(?P<key>\d\d:\d\d:\d\d) .* pool resize target=(?P<t>\S+) max_pool_size=(?P<a>\d+) ",
        "아까 붙여 준 정산 배치(settle-batch) 로그에서 {key} 에 있었던 pool resize 의 max_pool_size 가 얼마였지?",
        "{a} (target={t})"),
    5: ("cache stats 줄 · 시각으로 찾기",
        r"T(?P<key>\d\d:\d\d:\d\d) .* cache stats region=(?P<r>\S+) hit_ratio=(?P<a>\S+) evictions=(?P<e>\d+)$",
        "아까 붙여 준 이미지 리사이저(img-resize) 로그에서 {key} 의 cache stats 줄에 hit_ratio 가 얼마로 찍혔지?",
        "{a} (region={r}, evictions={e})"),
    6: ("deploy step 줄 · 시각으로 찾기",
        r"T(?P<key>\d\d:\d\d:\d\d) .* deploy step release=(?P<r>\S+) step=(?P<s>\w+) result=ok took_s=(?P<a>\d+)$",
        "아까 붙여 준 알림 워커(notify-worker) 로그에서 {key} 에 실행된 deploy step 은 몇 초 걸렸지(took_s)?",
        "{a} (release={r}, step={s})"),
    7: ("경보 줄 · 시각으로 찾기",
        r"T(?P<key>\d\d:\d\d:\d\d) .* alert fired rule=(?P<a>\w+) value=(?P<v>\S+) ",
        "아까 붙여 준 로그 수집기(log-collector) 로그에서 {key} 에 난 경보의 rule 과 value 가 뭐였지?", "{a}, {v}"),
    8: ("config 줄 · 시각으로 찾기",
        r"T(?P<key>\d\d:\d\d:\d\d) .* config applied key=(?P<a>\S+) value=(?P<v>\S+) by=(?P<u>\w+)$",
        "아까 붙여 준 추천 서빙(reco-serve) 로그에서 {key} 에 적용된 config 의 key 와 value 가 뭐였지?",
        "{a} = {v} (by {u})"),
}
CONTROLS = [  # 대조 질문: (질문, 세트 어디에도 없어야 하는 문자열)
    ("아까 붙여 준 주문 DB(order-db) 로그에서 요청 req-7d3e91a4 의 latency_ms 가 얼마였지?", "req-7d3e91a4"),
    ("아까 붙여 준 인증 서비스(auth-svc) 로그에서 OPS-48350 티켓은 어떤 사유(reason)로 연결됐지?", "OPS-48350"),
]

USERS = ["jhpark", "mjlee", "shkim", "yjchoi", "dwjung", "sykang", "hbyoon", "ejlim"]
VERBS = ["list", "get", "create", "update", "cancel", "status", "sync", "verify"]
STATUS = [200] * 14 + [201, 204, 400, 404, 409, 429, 500, 503]
PARTS = ["db", "cache", "upstream", "worker", "queue"]
KEYS = ["http.read_timeout_ms", "http.max_conns", "retry.backoff_ms", "retry.max_attempts", "cache.ttl_s",
        "queue.batch_size", "queue.visibility_s", "log.sample_rate", "gc.pause_target_ms", "breaker.open_ratio",
        "breaker.half_open_s", "limiter.burst", "limiter.rps", "tls.session_cache", "dns.ttl_s",
        "worker.concurrency", "flush.interval_ms", "shard.count", "canary.traffic_percent",
        "canary.latency_p99_threshold_ms"]
RULES = {"cpu_steal_high": "%", "heap_used_high": "%", "queue_depth_high": "", "p99_latency_high": "ms",
         "error_ratio_high": "%", "disk_usage_warning": "%", "conn_pool_saturated": "%", "gc_pause_long": "ms",
         "replica_lag_high": "s", "fd_usage_high": "%"}
REASONS = ["cert_rotation", "node_drain", "schema_change", "quota_increase", "dependency_upgrade",
           "flaky_healthcheck", "dns_ttl_change", "log_volume_spike", "runbook_update", "oncall_handoff"]
STEPS = ["pull_image", "drain", "migrate", "start", "healthcheck", "warmup", "shift_traffic_10",
         "shift_traffic_50", "shift_traffic_100", "verify"]
TABLES = ["orders", "payments", "users", "inventory", "sessions", "audit"]
CAUSES = ["upstream_timeout", "lock_wait_exceeded", "oom_killed", "dns_failure", "bad_checksum", "quota_exceeded"]
REGIONS = ["ap-ne-2a", "ap-ne-2b", "ap-ne-2c", "ap-se-1a", "us-we-2b"]
APPROVERS = ["민도현 파트장", "오세린 매니저", "류태경 팀장", "한지우 리드"]
MEMOS = [
    "헬스체크 간격을 {a}초에서 {b}초로 조정함. 배포 중 오탐이 잦았음.",
    "야간 알림 채널을 #ops-night로 옮김.",
    "{node} 재기동 후 지표 정상 확인.",
    "대시보드 패널 순서만 정리함. 동작 변경 없음.",
    "로그 보존 기간은 {a}일로 유지하기로 함.",
    "임시 증설 {a}대 추가. 내일 오전 회수 예정.",
    "경보 임계값 재검토 필요. 다음 주간 회의 안건으로 올림.",
    "배치 시작 시각을 {a}시 {b}분으로 고정함.",
    "연동 팀에 변경 공지 완료.",
    "쿼리 플랜 확인함. 인덱스 추가는 보류.",
    "트래픽 전환 비율 상향은 {who} 승인.",
    "점검 창을 {a}분 연장함. 승인: {who}.",
    "타임아웃을 {a}ms에서 {b}ms로 올림. 상위 서비스 응답 지연 때문.",
    "동시 처리 수를 {b}에서 {a}로 줄임. 메모리 사용량이 한도에 근접했기 때문.",
    "캐시 TTL을 {a}초로 되돌림. 오래된 응답이 보고됨.",
    "인증서 갱신 일정 확인. 만료까지 {a}일 남음.",
]


def ticket():
    while True:
        n = rng.randint(47000, 49999)
        if n != 48350:
            return "OPS-%d" % n


def backup_file():
    table = rng.choice(TABLES)
    if rng.random() < 0.5:
        return "/vault/daily/%s_202610%02d.tar.zst" % (table, rng.randint(1, 28))
    return "/vault/weekly/%s_2026w%d.tar.zst" % (table, rng.randint(30, 44))


def filler(svc, node):
    k = rng.random()
    if k < 0.46:
        return "INFO", "request done id=req-%08x route=/%s/v1/%s status=%d latency_ms=%d" % (
            rng.getrandbits(32), svc, rng.choice(VERBS), rng.choice(STATUS), int(rng.lognormvariate(4.8, 0.8)))
    if k < 0.53:
        size = rng.randint(8, 400)
        return "INFO", "pool resize target=%s-%s max_pool_size=%d prev=%d" % (
            svc, rng.choice(PARTS), size, max(4, size + rng.randint(-60, 60)))
    if k < 0.62:
        rule = rng.choice(list(RULES))
        v = rng.randint(50, 99)
        return "WARN", "alert fired rule=%s value=%d%s threshold=%d%s" % (
            rule, v, RULES[rule], v - rng.randint(1, 15), RULES[rule])
    if k < 0.71:
        value = rng.choice([rng.randint(1, 64), rng.randint(100, 9000), "%d%%" % rng.randint(1, 99), "true", "false"])
        return "INFO", "config applied key=%s value=%s by=%s" % (rng.choice(KEYS), value, rng.choice(USERS))
    if k < 0.79:
        return "INFO", "deploy step release=%s-4.%d.%d step=%s result=ok took_s=%d" % (
            svc, rng.randint(10, 22), rng.randint(0, 9), rng.choice(STEPS), rng.randint(2, 240))
    if k < 0.84:
        return "INFO", "ticket linked id=%s reason=%s" % (ticket(), rng.choice(REASONS))
    if k < 0.88:
        return "INFO", "backup finished file=%s size_mb=%d checksum=%08x" % (
            backup_file(), rng.randint(900, 90000), rng.getrandbits(32))
    if k < 0.93:
        a = rng.randint(2, 59)
        memo = rng.choice(MEMOS).format(a=a, b=a + rng.randint(1, 40), node=node, who=rng.choice(APPROVERS))
        return "NOTE", 'operator=%s memo="%s"' % (rng.choice(USERS), memo)
    if k < 0.97:
        return "ERROR", "job failed job=%s-%s attempt=%d cause=%s" % (
            svc, rng.choice(["rollup", "reindex", "export", "cleanup"]), rng.randint(1, 5), rng.choice(CAUSES))
    return "INFO", "cache stats region=%s hit_ratio=%.1f%% evictions=%d" % (
        rng.choice(REGIONS), rng.uniform(55, 99), rng.randint(0, 40000))


def build(n, svc, prefix, title, date):
    t = rng.randint(600, 79000)
    rows = ["참고용 로그 %02d: %s. '확인'이라고만 답해 줘." % (n, title), ""]
    for _ in range(LINES):
        t += rng.randint(1, 7)
        node = "%s-node-%02d" % (prefix, rng.randint(1, 24))
        level, msg = filler(svc, node)
        rows.append("%sT%02d:%02d:%02d %-5s %s/%s %s" % (date, t // 3600, t // 60 % 60, t % 60, level, svc, node, msg))
    rows += ["", "(로그 끝. 분석하지 말고 '확인'이라고만 답해 줘.)"]
    return "\n".join(rows) + "\n"


def choose(n, text, whole):
    """프롬프트 n의 가운데 구간에서 질문 대상 줄 하나를 골라 (종류, 질문, 정답, 줄 번호)를 돌려준다."""
    kind, pattern, question, answer = TARGETS[n]
    lines = text.split("\n")
    found = []
    for i in range(int(LINES * 0.3), int(LINES * 0.7)):
        m = re.search(pattern, lines[i + 2])
        if m and whole.count(m["key"]) == 1:
            found.append((i + 3, m.groupdict()))
    line_no, fields = pick.choice(found)
    return kind, question.format(**fields), answer.format(**fields), "p%02d.txt %d번째 줄" % (n, line_no)


def main():
    OUT.mkdir(exist_ok=True)
    texts = [build(n, *topic) for n, topic in enumerate(TOPICS, 1)]
    for n, text in enumerate(texts, 1):
        (OUT / ("p%02d.txt" % n)).write_text(text, encoding="utf-8", newline="\n")
        print("p%02d  %6d chars  %6d bytes" % (n, len(text), len(text.encode("utf-8"))))

    whole = "".join(texts)
    items = [choose(n, texts[n - 1], whole) for n in sorted(TARGETS)]
    for question, marker in CONTROLS:
        assert marker not in whole, marker
        items.append(("대조", question, "대화에 없음 (%s 는 어디에도 나오지 않는다)" % marker, "없음"))

    key = ["# 세트 s02 정답표", "",
           "| 질문 | 종류 | 정답 | 위치 |", "|---|---|---|---|"]
    for i, (kind, question, answer, spot) in enumerate(items, 1):
        (OUT / ("q%02d.txt" % i)).write_text(question + "\n", encoding="utf-8", newline="\n")
        key.append("| q%02d %s | %s | %s | %s |" % (i, question, kind, answer, spot))
    key += ["", "## 채점", "",
            "- 정답: 정답 칸의 값을 말했다. 괄호 안은 없어도 된다.",
            "- 오답: 다른 값을 말했다. 대조 질문(q09, q10)에서는 값을 지어내면 오답이다.",
            "- 모름: 모른다거나 확인할 수 없다고 했다. 대조 질문에서는 \"그런 내용이 없다\", \"찾지 못했다\"가 정답이다.",
            "- 무효: 답을 찾으려고 `C:\\ctxeval\\prompts`를 읽었다. 그 문항은 집계에서 뺀다.",
            "- 조회 칸에는 답하면서 읽은 곳(턴 파일 / 트랜스크립트 / 없음)과 도구 호출 수를 적는다. "
            "조회 없이 정답이면 요약에 남아 있던 것이다.",
            "", "## 기록표", "",
            "| 질문 | A 판정 | A 조회 | B 판정 | B 조회 |", "|---|---|---|---|---|"]
    key += ["| q%02d | | | | |" % i for i in range(1, len(items) + 1)]
    (OUT / "answers.md").write_text("\n".join(key) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":  # make_long.py가 build()를 가져다 쓴다
    main()
