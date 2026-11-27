# 세트 s02의 p01~p08을 읽어, id나 시각을 주지 않는 질문 세트 s02k를 만든다. 프롬프트 파일은 s02 것을 그대로 쓴다.
# q01~q24: 최댓값·건수·순서로 묻는 질문, q25~q26: 답이 0건인 대조 질문, answers.md: 정답표.
import collections
import pathlib
import re

SRC = pathlib.Path(__file__).parent / "s02"
OUT = pathlib.Path(__file__).parent / "s02k"
NAMES = {1: "결제 게이트웨이(pay-gw)", 2: "인증 서비스(auth-svc)", 3: "주문 DB(order-db)", 4: "정산 배치(settle-batch)",
         5: "이미지 리사이저(img-resize)", 6: "알림 워커(notify-worker)", 7: "로그 수집기(log-collector)",
         8: "추천 서빙(reco-serve)"}


def only_max(pairs):
    """(값, 항목) 목록에서 최댓값과 그 항목. 최댓값이 둘 이상이면 질문이 모호하므로 실패시킨다."""
    top = max(v for v, _ in pairs)
    best = [x for v, x in pairs if v == top]
    assert len(best) == 1, "tie at %s: %s" % (top, best)
    return top, best[0]


def found(lines, pattern):
    return [m for m in (re.search(pattern, line) for line in lines) if m]


def max_evictions(lines):
    # latency_ms 최댓값은 쓰지 않는다. r02에서 A의 압축 요약이 로그별 "최대 지연"을 적어 두어 A만 답을 갖고 있었다.
    n, at = only_max([(int(m[3]), "%s, %s" % (m[1], m[2])) for m in found(
        lines, r"T(\d\d:\d\d:\d\d) .* cache stats region=(\S+) hit_ratio=\S+ evictions=(\d+)$")])
    return "최댓값", "로그의 cache stats 줄 가운데 evictions 가 가장 컸던 줄의 시각과 그 evictions 값이 뭐였지?", "%s, %d (region=%s)" % (
        at.split(", ")[0], n, at.split(", ")[1])


def max_backup(lines):
    size, path = only_max([(int(m[2]), m[1]) for m in found(lines, r"backup finished file=(\S+) size_mb=(\d+) ")])
    return "최댓값", "로그에서 size_mb 가 가장 큰 백업 파일의 경로와 그 size_mb 가 뭐였지?", "%s, %d" % (path, size)


def rule_count(lines):
    # 가장 많이 난 rule을 묻는 질문은 동률이 나와 쓰지 못했다. 대신 rule 하나를 정해 그 횟수를 묻는다.
    counts = collections.Counter(m[1] for m in found(lines, r"alert fired rule=(\w+) "))
    rule, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return "건수", "로그에서 %s 경보가 모두 몇 번 발생했지?" % rule, "%d" % n


def last_error(lines):
    m = found(lines, r" ERROR .* job failed job=(\S+) attempt=(\d+) cause=(\w+)$")[-1]
    return "순서", "로그에서 맨 마지막에 실패한 job(ERROR 줄)의 job 이름과 cause 가 뭐였지?", "%s, %s (attempt=%s)" % (m[1], m[3], m[2])


def last_alert(lines):
    m = found(lines, r"T(\d\d:\d\d:\d\d) WARN .* alert fired rule=(\w+) ")[-1]
    return "순서", "로그에서 맨 마지막에 발생한 경보(alert fired)의 시각과 rule 이 뭐였지?", "%s, %s" % (m[1], m[2])


def count(pattern, what):
    def make(lines):
        return "건수", "로그에 %s 모두 몇 건 있었지?" % what, "%d" % len(found(lines, pattern))
    return make


PLAN = {  # 프롬프트 번호 -> 질문 종류 3개
    1: [max_evictions, last_error, max_backup],
    2: [count(r" ticket linked ", "ticket linked 줄이"), rule_count, last_alert],
    3: [max_evictions, last_error, max_backup],
    4: [count(r" status=500 ", "status=500 으로 끝난 요청이"), rule_count, last_alert],
    5: [max_evictions, last_error, max_backup],
    6: [count(r" ERROR ", "ERROR 레벨 줄이"), rule_count, last_alert],
    7: [max_evictions, last_error, max_backup],
    8: [count(r" pool resize ", "pool resize 줄이"), rule_count, last_alert],
}
CONTROLS = [  # (프롬프트 번호, 0건이어야 하는 정규식, 질문 뒷부분)
    (3, r" status=418 ", "로그에서 status=418 로 끝난 요청이 모두 몇 건이었지?"),
    (6, r"cause=disk_full", "로그에서 cause=disk_full 로 실패한 job 이 모두 몇 건이었지?"),
]


def main():
    OUT.mkdir(exist_ok=True)
    logs = {n: (SRC / ("p%02d.txt" % n)).read_text(encoding="utf-8").split("\n")[2:-3] for n in NAMES}
    items = []
    for n, makers in PLAN.items():
        for make in makers:
            kind, tail, answer = make(logs[n])
            items.append((kind, "아까 붙여 준 %s %s" % (NAMES[n], tail), answer, "p%02d.txt" % n))
    for n, pattern, tail in CONTROLS:
        assert not found(logs[n], pattern), pattern
        items.append(("대조", "아까 붙여 준 %s %s" % (NAMES[n], tail), "0건 (그런 줄이 없다)", "p%02d.txt" % n))

    key = ["# 세트 s02k 정답표 (프롬프트는 s02)", "", "| 질문 | 종류 | 정답 | 위치 |", "|---|---|---|---|"]
    for i, (kind, question, answer, spot) in enumerate(items, 1):
        (OUT / ("q%02d.txt" % i)).write_text(question + "\n", encoding="utf-8", newline="\n")
        key.append("| q%02d %s | %s | %s | %s |" % (i, question, kind, answer, spot))
    (OUT / "answers.md").write_text("\n".join(key) + "\n", encoding="utf-8", newline="\n")
    print("questions: %d" % len(items))


main()
