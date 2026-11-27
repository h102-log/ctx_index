# 세트 s02 정답표

| 질문 | 종류 | 정답 | 위치 |
|---|---|---|---|
| q01 아까 붙여 준 결제 게이트웨이(pay-gw) 로그에서 요청 req-bf5bcd68 의 latency_ms 가 얼마였지? | 요청 줄 · id로 찾기 | 46 | p01.txt 232번째 줄 |
| q02 아까 붙여 준 인증 서비스(auth-svc) 로그에서 OPS-48587 티켓은 어떤 사유(reason)로 연결됐지? | 티켓 줄 · id로 찾기 | flaky_healthcheck | p02.txt 189번째 줄 |
| q03 아까 붙여 준 주문 DB(order-db) 로그에서 백업 파일 /vault/daily/orders_20261024.tar.zst 의 checksum 이 뭐였지? | 백업 줄 · 파일 경로로 찾기 | bf5ee2a2 | p03.txt 166번째 줄 |
| q04 아까 붙여 준 정산 배치(settle-batch) 로그에서 13:30:22 에 있었던 pool resize 의 max_pool_size 가 얼마였지? | pool resize 줄 · 시각으로 찾기 | 180 (target=settle-batch-queue) | p04.txt 177번째 줄 |
| q05 아까 붙여 준 이미지 리사이저(img-resize) 로그에서 03:31:06 의 cache stats 줄에 hit_ratio 가 얼마로 찍혔지? | cache stats 줄 · 시각으로 찾기 | 84.0% (region=ap-se-1a, evictions=3136) | p05.txt 205번째 줄 |
| q06 아까 붙여 준 알림 워커(notify-worker) 로그에서 01:30:21 에 실행된 deploy step 은 몇 초 걸렸지(took_s)? | deploy step 줄 · 시각으로 찾기 | 142 (release=notify-worker-4.21.2, step=shift_traffic_10) | p06.txt 147번째 줄 |
| q07 아까 붙여 준 로그 수집기(log-collector) 로그에서 07:35:16 에 난 경보의 rule 과 value 가 뭐였지? | 경보 줄 · 시각으로 찾기 | p99_latency_high, 57ms | p07.txt 252번째 줄 |
| q08 아까 붙여 준 추천 서빙(reco-serve) 로그에서 15:24:13 에 적용된 config 의 key 와 value 가 뭐였지? | config 줄 · 시각으로 찾기 | limiter.rps = 72% (by jhpark) | p08.txt 239번째 줄 |
| q09 아까 붙여 준 주문 DB(order-db) 로그에서 요청 req-7d3e91a4 의 latency_ms 가 얼마였지? | 대조 | 대화에 없음 (req-7d3e91a4 는 어디에도 나오지 않는다) | 없음 |
| q10 아까 붙여 준 인증 서비스(auth-svc) 로그에서 OPS-48350 티켓은 어떤 사유(reason)로 연결됐지? | 대조 | 대화에 없음 (OPS-48350 는 어디에도 나오지 않는다) | 없음 |

## 채점

- 정답: 정답 칸의 값을 말했다. 괄호 안은 없어도 된다.
- 오답: 다른 값을 말했다. 대조 질문(q09, q10)에서는 값을 지어내면 오답이다.
- 모름: 모른다거나 확인할 수 없다고 했다. 대조 질문에서는 "그런 내용이 없다", "찾지 못했다"가 정답이다.
- 무효: 답을 찾으려고 `C:\ctxeval\prompts`를 읽었다. 그 문항은 집계에서 뺀다.
- 조회 칸에는 답하면서 읽은 곳(턴 파일 / 트랜스크립트 / 없음)과 도구 호출 수를 적는다. 조회 없이 정답이면 요약에 남아 있던 것이다.

## 기록표

| 질문 | A 판정 | A 조회 | B 판정 | B 조회 |
|---|---|---|---|---|
| q01 | | | | |
| q02 | | | | |
| q03 | | | | |
| q04 | | | | |
| q05 | | | | |
| q06 | | | | |
| q07 | | | | |
| q08 | | | | |
| q09 | | | | |
| q10 | | | | |
