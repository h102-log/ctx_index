# 한 세션에서 압축이 여러 번 나도록 프롬프트를 늘린 세트 s03을 만든다.
# p01~p16은 s02의 파일을 그대로 복사하고, p17~p42만 같은 형식으로 새로 만든다.
# [의도] 질문 세트 s02k(대상은 p01~p08)를 그대로 써서 압축 1회 실행과 직접 비교한다.
import pathlib
import random
import shutil
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))  # python -I 로 실행해도 make_set을 찾게 한다
import make_set  # noqa: E402

OUT = HERE / "s03"
TOPICS = [  # (서비스, 노드 접두어, 제목, 날짜) — p17부터. 서비스와 접두어는 s02와 겹치지 않아야 한다.
    ("search-api", "sa", "검색 API(search-api) 색인 재구축 구간", "2026-10-21"),
    ("cart-svc", "cs", "장바구니(cart-svc) 세션 이관 구간", "2026-10-22"),
    ("price-engine", "pe", "가격 엔진(price-engine) 룰 배포 구간", "2026-10-23"),
    ("coupon-svc", "cu", "쿠폰 서비스(coupon-svc) 발급 폭주 구간", "2026-10-24"),
    ("ship-track", "sk", "배송 추적(ship-track) 연동 점검 구간", "2026-10-25"),
    ("fraud-scan", "fs", "이상 거래 탐지(fraud-scan) 모델 교체 구간", "2026-10-26"),
    ("media-store", "ms", "미디어 저장소(media-store) 이관 구간", "2026-10-27"),
    ("push-gw", "pw", "푸시 게이트웨이(push-gw) 인증서 교체 구간", "2026-10-28"),
    ("audit-log", "al", "감사 로그(audit-log) 보존 정책 적용 구간", "2026-10-29"),
    ("geo-lookup", "gl", "위치 조회(geo-lookup) 캐시 워밍 구간", "2026-10-30"),
    ("billing-api", "ba", "청구 API(billing-api) 월말 마감 구간", "2026-10-31"),
    ("user-profile", "up", "회원 프로필(user-profile) 스키마 변경 구간", "2026-11-01"),
    ("review-svc", "rv", "리뷰 서비스(review-svc) 스팸 필터 구간", "2026-11-02"),
    ("ab-router", "ar", "실험 라우터(ab-router) 트래픽 분할 구간", "2026-11-03"),
    ("feature-flag", "ff", "기능 플래그(feature-flag) 동기화 구간", "2026-11-04"),
    ("metric-agg", "ma", "지표 집계기(metric-agg) 롤업 구간", "2026-11-05"),
    ("trace-sink", "ts", "트레이스 수집(trace-sink) 샘플링 조정 구간", "2026-11-06"),
    ("config-repo", "cr", "설정 저장소(config-repo) 복제 지연 구간", "2026-11-07"),
    ("secret-vault", "sv", "비밀 저장소(secret-vault) 키 교체 구간", "2026-11-08"),
    ("lb-ctl", "lb", "로드밸런서 제어(lb-ctl) 가중치 변경 구간", "2026-11-09"),
    ("dns-sync", "ds", "DNS 동기화(dns-sync) 존 갱신 구간", "2026-11-10"),
    ("queue-broker", "qb", "메시지 브로커(queue-broker) 파티션 재배치 구간", "2026-11-11"),
    ("etl-loader", "el", "ETL 적재기(etl-loader) 야간 적재 구간", "2026-11-12"),
    ("thumb-cache", "tc", "썸네일 캐시(thumb-cache) 축출 점검 구간", "2026-11-13"),
    ("sms-gate", "sg", "문자 게이트웨이(sms-gate) 통신사 전환 구간", "2026-11-14"),
    ("pdf-render", "pr", "PDF 렌더러(pdf-render) 큐 정리 구간", "2026-11-15"),
]


def main():
    OUT.mkdir(exist_ok=True)
    copied = sorted((HERE / "s02").glob("p*.txt"))
    assert len(copied) == len(make_set.TOPICS)
    for src in copied:
        shutil.copyfile(src, OUT / src.name)
    used = {(t[0], t[1]) for t in make_set.TOPICS}
    make_set.rng = random.Random(20261128)  # build()와 filler()가 쓰는 난수. s02와 다른 시드로 새 로그를 만든다.
    for n, topic in enumerate(TOPICS, len(copied) + 1):
        assert not any(topic[0] == s or topic[1] == p for s, p in used), topic
        used.add((topic[0], topic[1]))
        text = make_set.build(n, *topic)
        (OUT / ("p%02d.txt" % n)).write_text(text, encoding="utf-8", newline="\n")
    print("s03: %d prompts (%d copied from s02, %d new)" % (len(used), len(copied), len(TOPICS)))


main()
