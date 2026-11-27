# 질문 세트 — autocompact 맥락 유지 실험

`gen_scenarios.py`가 시드로 만드는 세션 6개의 심은 세부와 질문입니다. 값은 모두 무작위라 기억만으로는 맞힐 수 없습니다. 채움 턴(긴 붙여넣기와 짧은 분석 요청, 한 줄 대답)에는 질문 대상이 없어서 수와 예시만 적습니다. 위치는 autocompact 발동 지점(400K 창에서 약 350K 토큰) 대비 비율이며, 실행기는 대화가 그 비율에 닿은 다음 턴에 해당 요청을 보냅니다. 공유 빌드는 약 330K 토큰에서 멈추고, 두 조건은 각각 같은 '참고용 로그 — 확인이라고만 답해 줘' 턴을 차례로 받다가 CLI가 스스로 autocompact하는 지점에서 압축됩니다.

| 세션 | 주제 | 질문 수 | 준비된 채움 턴 |
|---|---|---|---|
| s01 | 결제 서비스 장애 분석 | 11 | 120 |
| s02 | 주문 DB 마이그레이션 계획 | 11 | 120 |
| s03 | 검색 API 지연 분석 | 11 | 120 |
| s04 | 인증 서버 점검 | 11 | 120 |
| s05 | 모바일 앱 크래시 분석 | 11 | 120 |
| s06 | 데이터 파이프라인 지연 | 11 | 120 |

**채점** (`grade.py`, 판정 모델 없음)

- 세부 질문: 정답 값이 답에 독립된 토큰으로 있으면 정답. 없고 '찾을 수 없다 / 기록에 없다 / 모르겠다' 류의 표현이 있으면 모름, 둘 다 아니면 오답(지어냄). 다른 후보를 둘 이상 늘어놓으면 정답으로 치지 않습니다.
- 원문 인용: 원래 요청 문장이 답에 순서대로 90% 이상 들어 있으면 정답.
- 대조 질문(`negative`): 세션에 한 번도 나오지 않은 내용입니다. '기록에 없다'고 답하면 정답, 무언가를 지어내면 오답.
- `assistant_derived`: 압축 전 그 턴에서 모델이 실제로 정답을 말한 경우에만 셉니다. 두 조건이 같은 대화를 공유하므로 양쪽에서 똑같이 걸러집니다.

## s01 결제 서비스 장애 분석

| 질문 | 종류 | 위치 | 심은 턴(목표 위치) | 정답 |
|---|---|---|---|---|
| 이번 세션에서 내가 맨 처음 붙여넣은 로그는 어느 서비스의 로그였지? 짧게 답해 줘. | order | early | n1 (0%) | `ledger-writer` |
| 맨 처음 붙여넣은 ledger-writer 로그에서 status=409였던 요청의 trace 값이 뭐였지? 짧게 답해 줘. | paste_value | early | n1 (0%) | `db65544c47` |
| 스테이징 결제 DB 포트가 몇 번이었지? 짧게 답해 줘. | user_fact | early | n2 (10%) | `5606` |
| 내가 절대 수정하지 말라고 했던 디렉터리가 어디였지? 짧게 답해 줘. | constraint | early | n3 (22%) | `ledger` |
| 아까 네가 지연 지표 표에서 찾아 준, p99가 가장 높았던 엔드포인트가 어디였지? 짧게 답해 줘. | assistant_derived | mid | n4 (35%) | `/v1/disputes` |
| 내가 결제 재시도 정책을 바꾸기 전에 먼저 확인하고 싶다고 했던 요청을 원문 그대로 다시 보여줘. | verbatim | mid | n5 (48%) | 아래 n5 원문 |
| 아까 붙여넣은 payment-service.yaml 설정에서 retry.backoff_ms 값이 얼마였지? 짧게 답해 줘. | paste_value | mid | n6 (60%) | `3803` |
| CDC 방식(B안)으로 정하면서 내가 기준으로 말한 쓰기 지연 상한이 몇 ms였지? 짧게 답해 줘. | decision_reason | late | n7 (74%) | `44` |
| ledger-writer 스택 트레이스에 찍혀 있던 예외 코드(code=...)가 뭐였지? 짧게 답해 줘. | paste_value | late | n8 (88%) | `LDG-8092` |
| 아까 정한 Kafka 컨슈머 그룹 이름이 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |
| 내가 공유했던 Grafana 대시보드 UID가 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |

심은 턴의 요청문(붙여넣기는 앞 3줄만):

- **n1** (목표 0%)

````text
결제 건을 같이 보자. 먼저 ledger-writer 로그부터 붙여넣을게. 전체적으로 어떤 오류가 많은지 짧게 정리해 줘.

2026-03-12T02:00:00.876Z WARN  ledger-writer [req=r43e7ae] POST /v1/refunds status=404 latency_ms=548 trace=b0d662029d user=u16876
2026-03-12T02:00:03.424Z INFO  ledger-writer [req=r3ac6c9] GET /v1/captures status=200 latency_ms=1773 trace=f9b9894cef user=u35427
2026-03-12T02:00:06.058Z INFO  ledger-writer [req=r1d4b21] DELETE /v1/webhooks status=200 latency_ms=2370 trace=08e0fcffb2 user=u78783
… (180줄 더)
````

- **n2** (목표 10%)

````text
참고로 스테이징 결제 DB 포트는 5606번이고, 운영 결제 DB 포트는 5240번이야. 나중에 스크립트 짤 때 이 값 써야 하니까 기억해 둬.
````

- **n3** (목표 22%)

````text
아 그리고 중요한 거. 앞으로 ledger/ 디렉터리 아래 파일은 절대 수정하지 마. 회계 감사 대상이라 변경 이력이 남으면 안 돼.
````

- **n4** (목표 35%)

````text
엔드포인트별 지연 지표야. 이 표 전체에서 p99_ms가 가장 높은 행의 엔드포인트와 그 값을 찾아 줘.

minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate
21:14,/v1/charges,124,101,332,855,0.0096
02:02,/v1/refunds,36,70,106,652,0.0018
… (293줄 더)
````

- **n5** (목표 48%)

````text
결제 재시도 정책을 바꾸기 전에 세 가지를 먼저 확인하고 싶어. 첫째, 게이트웨이 타임아웃 27초와 클라이언트 타임아웃 6초의 차이 때문에 같은 요청이 두 번 처리되는지. 둘째, 재시도할 때마다 idempotency key가 새로 만들어지는지. 셋째, 실패 알림이 #payment-alerts-919 채널로 제대로 가는지. 이 세 가지를 확인하기 전에는 코드를 바꾸지 말아 줘.
````

- **n6** (목표 60%)

````text
이건 payment-service.yaml 설정 파일 전체야. 운영 반영 전에 위험한 값이 있는지 짧게 봐 줘.

# payment-service.yaml
service: payment-api
stream_cache:
… (1130줄 더)
````

- **n7** (목표 74%)

````text
결론적으로 이중 기록(A안) 대신 CDC 방식(B안)으로 가자. 쓰기 지연이 44ms를 넘으면 안 되거든. 이 기준은 팀에도 그대로 공유할 거야.
````

- **n8** (목표 88%)

````text
방금 ledger-writer에서 난 스택 트레이스야. 원인이 뭐로 보이는지 짧게 알려 줘.

2026-03-12T19:00:21.984Z ERROR ledger-writer: LedgerWriteException: code=LDG-8092 message="cursor retry failed after 2 attempts"
    at com.example.ledgerwriter.PlannerSnapshot.token(Reader.java:782)
    at com.example.ledgerwriter.ChecksumCursor.session(Writer.java:653)
… (45줄 더)
````

채움 턴 예시 (f001, notes, 첫 400자):

````text
회의록이야. 세 줄로 요약해 줘.

```
# 회의록 (notify-svc)
- 이도윤님: 대시보드 지표 이름을 통일하자는 제안이 있었습니다.
- 김하늘님: 비용 보고는 월말에 한 번에 하자고 했습니다.
- 김하늘님: 다음 회의에서 롤백 절차를 다시 점검하기로 했습니다.
- 김하늘님: 대시보드 지표 이름을 통일하자는 제안이 있었습니다.
- 윤세린님: notify-svc 담당자 교체 일정은 아직 미정입니다.
- 김하늘님: 다음 회의에서 롤백 절차를 다시 점검하기로 했습니다.
- 최유나님: notify-svc 배포는 다음 주 화요일 오전으로 미루자는 의견이 나왔습니다.
- 이도윤님: 비용 보고는 월말에 한 번에 하자고 했습니다.
- 이도윤님: 비용 보고는 월말에 한 번에 하자고 했습니다.
- 최유나님: 테스트 
…
````

## s02 주문 DB 마이그레이션 계획

| 질문 | 종류 | 위치 | 심은 턴(목표 위치) | 정답 |
|---|---|---|---|---|
| 이번 세션에서 내가 맨 처음 붙여넣은 로그는 어느 서비스의 로그였지? 짧게 답해 줘. | order | early | n1 (0%) | `inventory-api` |
| 맨 처음 붙여넣은 inventory-api 로그에서 status=409였던 요청의 trace 값이 뭐였지? 짧게 답해 줘. | paste_value | early | n1 (0%) | `fd61d99b05` |
| 스테이징 주문 DB 포트가 몇 번이었지? 짧게 답해 줘. | user_fact | early | n2 (10%) | `5896` |
| 내가 절대 수정하지 말라고 했던 디렉터리가 어디였지? 짧게 답해 줘. | constraint | early | n3 (22%) | `migrations/applied` |
| 아까 네가 지연 지표 표에서 찾아 준, p99가 가장 높았던 엔드포인트가 어디였지? 짧게 답해 줘. | assistant_derived | mid | n4 (35%) | `/orders/{id}/items` |
| 내가 청크 복사 재시도 정책을 바꾸기 전에 먼저 확인하고 싶다고 했던 요청을 원문 그대로 다시 보여줘. | verbatim | mid | n5 (48%) | 아래 n5 원문 |
| 아까 붙여넣은 migrator.yaml 설정에서 batch.rows_per_chunk 값이 얼마였지? 짧게 답해 줘. | paste_value | mid | n6 (60%) | `3992` |
| 점진 백필(B안)으로 정하면서 내가 기준으로 말한 복제 지연 상한이 몇 ms였지? 짧게 답해 줘. | decision_reason | late | n7 (74%) | `41` |
| order-migrator 스택 트레이스에 찍혀 있던 예외 코드(code=...)가 뭐였지? 짧게 답해 줘. | paste_value | late | n8 (88%) | `MIG-9126` |
| 아까 정한 Kafka 컨슈머 그룹 이름이 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |
| 내가 공유했던 Grafana 대시보드 UID가 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |

심은 턴의 요청문(붙여넣기는 앞 3줄만):

- **n1** (목표 0%)

````text
주문 DB 마이그레이션 건을 같이 보자. 먼저 inventory-api 로그부터 붙여넣을게. 전체적으로 어떤 오류가 많은지 짧게 정리해 줘.

2026-03-12T06:00:00.475Z ERROR inventory-api [req=rad482b] GET /orders/search status=502 latency_ms=31 trace=66022d45c4 user=u48568
2026-03-12T06:00:03.413Z INFO  inventory-api [req=r485418] POST /orders status=200 latency_ms=1056 trace=a4c1549b50 user=u91516
2026-03-12T06:00:06.987Z ERROR inventory-api [req=r4f6fb9] GET /orders/search status=200 latency_ms=1120 trace=0ed2309363 user=u26568
… (177줄 더)
````

- **n2** (목표 10%)

````text
참고로 스테이징 주문 DB 포트는 5896번이고, 운영 주문 DB 포트는 5901번이야. 나중에 스크립트 짤 때 이 값 써야 하니까 기억해 둬.
````

- **n3** (목표 22%)

````text
아 그리고 중요한 거. 앞으로 migrations/applied/ 디렉터리 아래 파일은 절대 수정하지 마. 이미 운영에 적용된 스크립트라 손대면 체크섬이 깨져.
````

- **n4** (목표 35%)

````text
엔드포인트별 지연 지표야. 이 표 전체에서 p99_ms가 가장 높은 행의 엔드포인트와 그 값을 찾아 줘.

minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate
03:00,/orders,148,38,326,1217,0.0020
11:40,/orders/{id}/items,153,93,287,457,0.0064
… (281줄 더)
````

- **n5** (목표 48%)

````text
청크 복사 재시도 정책을 바꾸기 전에 세 가지를 먼저 확인하고 싶어. 첫째, 게이트웨이 타임아웃 25초와 클라이언트 타임아웃 5초의 차이 때문에 같은 요청이 두 번 처리되는지. 둘째, 재시도할 때마다 idempotency key가 새로 만들어지는지. 셋째, 실패 알림이 #order-alerts-992 채널로 제대로 가는지. 이 세 가지를 확인하기 전에는 코드를 바꾸지 말아 줘.
````

- **n6** (목표 60%)

````text
이건 migrator.yaml 설정 파일 전체야. 운영 반영 전에 위험한 값이 있는지 짧게 봐 줘.

# migrator.yaml
service: order-api
pool_decode:
… (1131줄 더)
````

- **n7** (목표 74%)

````text
결론적으로 일괄 복사(A안) 대신 점진 백필(B안)으로 가자. 복제 지연이 41ms를 넘으면 안 되거든. 이 기준은 팀에도 그대로 공유할 거야.
````

- **n8** (목표 88%)

````text
방금 order-migrator에서 난 스택 트레이스야. 원인이 뭐로 보이는지 짧게 알려 줘.

2026-03-12T01:00:21.944Z ERROR order-migrator: ChunkCopyException: code=MIG-9126 message="cache token failed after 5 attempts"
    at com.example.ordermigrator.RetryReader.replica(Cursor.java:882)
    at com.example.ordermigrator.SnapshotQueue.shard(Offset.java:403)
… (41줄 더)
````

채움 턴 예시 (f001, config, 첫 400자):

````text
inventory-api 설정 파일이야. 운영에 안 맞아 보이는 값만 짧게 짚어 줘.

```
# inventory-api.yaml
service: inventory-api
lease_snapshot:
  session_size: 0.79
  cursor_enabled: "retry-91cb"
  cache_limit: true
  batch_size: "checksum-9e16"
  offset_name: 0.98
session_batch:
  pool_enabled: 1832
  queue_name: "quota-a09e"
  cursor_name: "batch-3911"
  quota_size: false
  batch_size: "stream-a00b"
  cache_ratio: 0.62
  repl
…
````

## s03 검색 API 지연 분석

| 질문 | 종류 | 위치 | 심은 턴(목표 위치) | 정답 |
|---|---|---|---|---|
| 이번 세션에서 내가 맨 처음 붙여넣은 로그는 어느 서비스의 로그였지? 짧게 답해 줘. | order | early | n1 (0%) | `index-builder` |
| 맨 처음 붙여넣은 index-builder 로그에서 status=409였던 요청의 trace 값이 뭐였지? 짧게 답해 줘. | paste_value | early | n1 (0%) | `98034070da` |
| 스테이징 검색 메타 DB 포트가 몇 번이었지? 짧게 답해 줘. | user_fact | early | n2 (10%) | `5738` |
| 내가 절대 수정하지 말라고 했던 디렉터리가 어디였지? 짧게 답해 줘. | constraint | early | n3 (22%) | `index-snapshots` |
| 아까 네가 지연 지표 표에서 찾아 준, p99가 가장 높았던 엔드포인트가 어디였지? 짧게 답해 줘. | assistant_derived | mid | n4 (35%) | `/index/refresh` |
| 내가 샤드 질의 재시도 정책을 바꾸기 전에 먼저 확인하고 싶다고 했던 요청을 원문 그대로 다시 보여줘. | verbatim | mid | n5 (48%) | 아래 n5 원문 |
| 아까 붙여넣은 search-api.yaml 설정에서 cache.ttl_seconds 값이 얼마였지? 짧게 답해 줘. | paste_value | mid | n6 (60%) | `4387` |
| 쿼리 캐시 도입(B안)으로 정하면서 내가 기준으로 말한 p95 지연 상한이 몇 ms였지? 짧게 답해 줘. | decision_reason | late | n7 (74%) | `27` |
| query-planner 스택 트레이스에 찍혀 있던 예외 코드(code=...)가 뭐였지? 짧게 답해 줘. | paste_value | late | n8 (88%) | `SRH-9390` |
| 아까 정한 Kafka 컨슈머 그룹 이름이 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |
| 내가 공유했던 Grafana 대시보드 UID가 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |

심은 턴의 요청문(붙여넣기는 앞 3줄만):

- **n1** (목표 0%)

````text
검색 지연 건을 같이 보자. 먼저 index-builder 로그부터 붙여넣을게. 전체적으로 어떤 오류가 많은지 짧게 정리해 줘.

2026-03-12T18:00:00.091Z INFO  index-builder [req=r9c69b9] GET /search/facets status=200 latency_ms=2281 trace=01e45aca51 user=u55212
2026-03-12T18:00:03.030Z WARN  index-builder [req=r3009dc] GET /search/suggest status=200 latency_ms=1153 trace=397baf410b user=u11853
2026-03-12T18:00:06.316Z INFO  index-builder [req=reaa6dc] GET /rank/score status=200 latency_ms=2317 trace=d911d44636 user=u66505
… (179줄 더)
````

- **n2** (목표 10%)

````text
참고로 스테이징 검색 메타 DB 포트는 5738번이고, 운영 검색 메타 DB 포트는 6488번이야. 나중에 스크립트 짤 때 이 값 써야 하니까 기억해 둬.
````

- **n3** (목표 22%)

````text
아 그리고 중요한 거. 앞으로 index-snapshots/ 디렉터리 아래 파일은 절대 수정하지 마. 복구용 스냅숏이라 덮어쓰면 되돌릴 수 없어.
````

- **n4** (목표 35%)

````text
엔드포인트별 지연 지표야. 이 표 전체에서 p99_ms가 가장 높은 행의 엔드포인트와 그 값을 찾아 줘.

minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate
13:36,/search,205,97,400,877,0.0016
20:22,/search/suggest,140,12,281,1054,0.0062
… (287줄 더)
````

- **n5** (목표 48%)

````text
샤드 질의 재시도 정책을 바꾸기 전에 세 가지를 먼저 확인하고 싶어. 첫째, 게이트웨이 타임아웃 21초와 클라이언트 타임아웃 5초의 차이 때문에 같은 요청이 두 번 처리되는지. 둘째, 재시도할 때마다 idempotency key가 새로 만들어지는지. 셋째, 실패 알림이 #search-alerts-837 채널로 제대로 가는지. 이 세 가지를 확인하기 전에는 코드를 바꾸지 말아 줘.
````

- **n6** (목표 60%)

````text
이건 search-api.yaml 설정 파일 전체야. 운영 반영 전에 위험한 값이 있는지 짧게 봐 줘.

# search-api.yaml
service: search-api
queue_offset:
… (1123줄 더)
````

- **n7** (목표 74%)

````text
결론적으로 샤드 증설(A안) 대신 쿼리 캐시 도입(B안)으로 가자. p95 지연이 27ms를 넘으면 안 되거든. 이 기준은 팀에도 그대로 공유할 거야.
````

- **n8** (목표 88%)

````text
방금 query-planner에서 난 스택 트레이스야. 원인이 뭐로 보이는지 짧게 알려 줘.

2026-03-12T18:00:21.368Z ERROR query-planner: ShardTimeoutException: code=SRH-9390 message="writer checksum failed after 4 attempts"
    at com.example.queryplanner.ReaderWriter.shard(Decode.java:420)
    at com.example.queryplanner.WriterLease.retry(Shard.java:592)
… (35줄 더)
````

채움 턴 예시 (f001, log, 첫 400자):

````text
query-planner 로그 일부야. 오류가 몰린 구간이 있는지만 짧게 봐 줘.

```
2026-03-12T13:00:00.773Z INFO  query-planner [req=r7b82cd] GET /search/facets status=200 latency_ms=1327 trace=27dba572b7 user=u71191
2026-03-12T13:00:03.010Z INFO  query-planner [req=rb6dc7c] POST /search status=200 latency_ms=324 trace=852752b692 user=u41616
2026-03-12T13:00:06.882Z INFO  query-planner [req=r279a7e] GET /search/export status=200
…
````

## s04 인증 서버 점검

| 질문 | 종류 | 위치 | 심은 턴(목표 위치) | 정답 |
|---|---|---|---|---|
| 이번 세션에서 내가 맨 처음 붙여넣은 로그는 어느 서비스의 로그였지? 짧게 답해 줘. | order | early | n1 (0%) | `auth-api` |
| 맨 처음 붙여넣은 auth-api 로그에서 status=409였던 요청의 trace 값이 뭐였지? 짧게 답해 줘. | paste_value | early | n1 (0%) | `438e5475d1` |
| 스테이징 세션 DB 포트가 몇 번이었지? 짧게 답해 줘. | user_fact | early | n2 (10%) | `6530` |
| 내가 절대 수정하지 말라고 했던 디렉터리가 어디였지? 짧게 답해 줘. | constraint | early | n3 (22%) | `keys/rotation` |
| 아까 네가 지연 지표 표에서 찾아 준, p99가 가장 높았던 엔드포인트가 어디였지? 짧게 답해 줘. | assistant_derived | mid | n4 (35%) | `/mfa/verify` |
| 내가 토큰 재발급 정책을 바꾸기 전에 먼저 확인하고 싶다고 했던 요청을 원문 그대로 다시 보여줘. | verbatim | mid | n5 (48%) | 아래 n5 원문 |
| 아까 붙여넣은 auth-server.yaml 설정에서 token.refresh_window_s 값이 얼마였지? 짧게 답해 줘. | paste_value | mid | n6 (60%) | `4938` |
| 토큰 재발급 지연(B안)으로 정하면서 내가 기준으로 말한 로그인 지연 상한이 몇 ms였지? 짧게 답해 줘. | decision_reason | late | n7 (74%) | `17` |
| token-issuer 스택 트레이스에 찍혀 있던 예외 코드(code=...)가 뭐였지? 짧게 답해 줘. | paste_value | late | n8 (88%) | `AUT-7419` |
| 아까 정한 Kafka 컨슈머 그룹 이름이 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |
| 내가 공유했던 Grafana 대시보드 UID가 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |

심은 턴의 요청문(붙여넣기는 앞 3줄만):

- **n1** (목표 0%)

````text
인증 서버 건을 같이 보자. 먼저 auth-api 로그부터 붙여넣을게. 전체적으로 어떤 오류가 많은지 짧게 정리해 줘.

2026-03-12T13:00:00.039Z WARN  auth-api [req=re927b9] GET /session/refresh status=401 latency_ms=311 trace=9926e2a444 user=u43788
2026-03-12T13:00:03.344Z INFO  auth-api [req=r91aa55] POST /oauth/token status=200 latency_ms=2218 trace=10afb4dfce user=u53358
2026-03-12T13:00:06.045Z INFO  auth-api [req=r69d48a] GET /oauth/token status=201 latency_ms=625 trace=d30a88add3 user=u54660
… (186줄 더)
````

- **n2** (목표 10%)

````text
참고로 스테이징 세션 DB 포트는 6530번이고, 운영 세션 DB 포트는 6500번이야. 나중에 스크립트 짤 때 이 값 써야 하니까 기억해 둬.
````

- **n3** (목표 22%)

````text
아 그리고 중요한 거. 앞으로 keys/rotation/ 디렉터리 아래 파일은 절대 수정하지 마. 키 순환 스크립트라 실수하면 전체 로그인이 막혀.
````

- **n4** (목표 35%)

````text
엔드포인트별 지연 지표야. 이 표 전체에서 p99_ms가 가장 높은 행의 엔드포인트와 그 값을 찾아 줘.

minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate
16:03,/oauth/token,169,63,210,233,0.0042
21:41,/oauth/revoke,455,12,227,623,0.0136
… (287줄 더)
````

- **n5** (목표 48%)

````text
토큰 재발급 정책을 바꾸기 전에 세 가지를 먼저 확인하고 싶어. 첫째, 게이트웨이 타임아웃 30초와 클라이언트 타임아웃 7초의 차이 때문에 같은 요청이 두 번 처리되는지. 둘째, 재시도할 때마다 idempotency key가 새로 만들어지는지. 셋째, 실패 알림이 #auth-alerts-df2 채널로 제대로 가는지. 이 세 가지를 확인하기 전에는 코드를 바꾸지 말아 줘.
````

- **n6** (목표 60%)

````text
이건 auth-server.yaml 설정 파일 전체야. 운영 반영 전에 위험한 값이 있는지 짧게 봐 줘.

# auth-server.yaml
service: auth-api
budget_cache:
… (1128줄 더)
````

- **n7** (목표 74%)

````text
결론적으로 세션 고정(A안) 대신 토큰 재발급 지연(B안)으로 가자. 로그인 지연이 17ms를 넘으면 안 되거든. 이 기준은 팀에도 그대로 공유할 거야.
````

- **n8** (목표 88%)

````text
방금 token-issuer에서 난 스택 트레이스야. 원인이 뭐로 보이는지 짧게 알려 줘.

2026-03-12T01:00:21.494Z ERROR token-issuer: TokenSignException: code=AUT-7419 message="budget stream failed after 4 attempts"
    at com.example.tokenissuer.LeaseBatch.budget(Budget.java:736)
    at com.example.tokenissuer.PlannerDecode.token(Offset.java:620)
… (37줄 더)
````

채움 턴 예시 (f001, config, 첫 400자):

````text
audit-logger 설정 파일이야. 운영에 안 맞아 보이는 값만 짧게 짚어 줘.

```
# audit-logger.yaml
service: audit-logger
shard_token:
  planner_enabled: "retry-ce58"
  queue_enabled: 0.61
  offset_ratio: 465
  pool_count: 0.36
  upload_limit: 1173
  upload_count: true
  budget_size: 1113
  shard_name: 0.81
  token_name: "queue-0253"
checksum_planner:
  quota_enabled: 962
  stream_count: false
  index_enabled: false
  replic
…
````

## s05 모바일 앱 크래시 분석

| 질문 | 종류 | 위치 | 심은 턴(목표 위치) | 정답 |
|---|---|---|---|---|
| 이번 세션에서 내가 맨 처음 붙여넣은 로그는 어느 서비스의 로그였지? 짧게 답해 줘. | order | early | n1 (0%) | `app-backend` |
| 맨 처음 붙여넣은 app-backend 로그에서 status=409였던 요청의 trace 값이 뭐였지? 짧게 답해 줘. | paste_value | early | n1 (0%) | `2f1b4ac405` |
| 스테이징 프로필 DB 포트가 몇 번이었지? 짧게 답해 줘. | user_fact | early | n2 (10%) | `6511` |
| 내가 절대 수정하지 말라고 했던 디렉터리가 어디였지? 짧게 답해 줘. | constraint | early | n3 (22%) | `release/signing` |
| 아까 네가 지연 지표 표에서 찾아 준, p99가 가장 높았던 엔드포인트가 어디였지? 짧게 답해 줘. | assistant_derived | mid | n4 (35%) | `/profile/{id}` |
| 내가 업로드 재시도 정책을 바꾸기 전에 먼저 확인하고 싶다고 했던 요청을 원문 그대로 다시 보여줘. | verbatim | mid | n5 (48%) | 아래 n5 원문 |
| 아까 붙여넣은 app-backend.yaml 설정에서 upload.chunk_kb 값이 얼마였지? 짧게 답해 줘. | paste_value | mid | n6 (60%) | `3006` |
| 서버 측 우회(B안)으로 정하면서 내가 기준으로 말한 업로드 지연 상한이 몇 ms였지? 짧게 답해 줘. | decision_reason | late | n7 (74%) | `26` |
| media-upload 스택 트레이스에 찍혀 있던 예외 코드(code=...)가 뭐였지? 짧게 답해 줘. | paste_value | late | n8 (88%) | `APP-7312` |
| 아까 정한 Kafka 컨슈머 그룹 이름이 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |
| 내가 공유했던 Grafana 대시보드 UID가 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |

심은 턴의 요청문(붙여넣기는 앞 3줄만):

- **n1** (목표 0%)

````text
앱 크래시 건을 같이 보자. 먼저 app-backend 로그부터 붙여넣을게. 전체적으로 어떤 오류가 많은지 짧게 정리해 줘.

2026-03-12T14:00:00.228Z ERROR app-backend [req=raed8c8] GET /feed/next status=503 latency_ms=166 trace=42506f6722 user=u75398
2026-03-12T14:00:03.205Z INFO  app-backend [req=rb8c945] GET /media/upload status=200 latency_ms=1900 trace=58ea1b1c84 user=u84447
2026-03-12T14:00:06.413Z INFO  app-backend [req=r6493d2] GET /media/upload status=200 latency_ms=122 trace=b3712be9f2 user=u60453
… (184줄 더)
````

- **n2** (목표 10%)

````text
참고로 스테이징 프로필 DB 포트는 6511번이고, 운영 프로필 DB 포트는 5816번이야. 나중에 스크립트 짤 때 이 값 써야 하니까 기억해 둬.
````

- **n3** (목표 22%)

````text
아 그리고 중요한 거. 앞으로 release/signing/ 디렉터리 아래 파일은 절대 수정하지 마. 스토어 서명 설정이라 바뀌면 배포가 막혀.
````

- **n4** (목표 35%)

````text
엔드포인트별 지연 지표야. 이 표 전체에서 p99_ms가 가장 높은 행의 엔드포인트와 그 값을 찾아 줘.

minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate
15:06,/feed,848,42,209,383,0.0081
04:05,/feed/next,713,82,445,647,0.0155
… (299줄 더)
````

- **n5** (목표 48%)

````text
업로드 재시도 정책을 바꾸기 전에 세 가지를 먼저 확인하고 싶어. 첫째, 게이트웨이 타임아웃 35초와 클라이언트 타임아웃 8초의 차이 때문에 같은 요청이 두 번 처리되는지. 둘째, 재시도할 때마다 idempotency key가 새로 만들어지는지. 셋째, 실패 알림이 #app-alerts-4cc 채널로 제대로 가는지. 이 세 가지를 확인하기 전에는 코드를 바꾸지 말아 줘.
````

- **n6** (목표 60%)

````text
이건 app-backend.yaml 설정 파일 전체야. 운영 반영 전에 위험한 값이 있는지 짧게 봐 줘.

# app-backend.yaml
service: app-backend
shard_reader:
… (1128줄 더)
````

- **n7** (목표 74%)

````text
결론적으로 강제 업데이트(A안) 대신 서버 측 우회(B안)으로 가자. 업로드 지연이 26ms를 넘으면 안 되거든. 이 기준은 팀에도 그대로 공유할 거야.
````

- **n8** (목표 88%)

````text
방금 media-upload에서 난 스택 트레이스야. 원인이 뭐로 보이는지 짧게 알려 줘.

2026-03-12T18:00:21.398Z ERROR media-upload: MediaDecodeException: code=APP-7312 message="decode quota failed after 5 attempts"
    at com.example.mediaupload.LeasePlanner.upload(Cursor.java:617)
    at com.example.mediaupload.BackoffBudget.planner(Upload.java:35)
… (41줄 더)
````

채움 턴 예시 (f001, log, 첫 400자):

````text
app-backend 로그 일부야. 오류가 몰린 구간이 있는지만 짧게 봐 줘.

```
2026-03-12T11:00:00.673Z WARN  app-backend [req=r92b865] GET /feed status=200 latency_ms=1846 trace=30ed8f3a15 user=u58373
2026-03-12T11:00:03.073Z ERROR app-backend [req=re9b914] DELETE /feed status=503 latency_ms=2027 trace=d6e0842809 user=u14012
2026-03-12T11:00:06.446Z INFO  app-backend [req=ra145f5] GET /profile/{id} status=200 latency_ms=1192 
…
````

## s06 데이터 파이프라인 지연

| 질문 | 종류 | 위치 | 심은 턴(목표 위치) | 정답 |
|---|---|---|---|---|
| 이번 세션에서 내가 맨 처음 붙여넣은 로그는 어느 서비스의 로그였지? 짧게 답해 줘. | order | early | n1 (0%) | `report-svc` |
| 맨 처음 붙여넣은 report-svc 로그에서 status=409였던 요청의 trace 값이 뭐였지? 짧게 답해 줘. | paste_value | early | n1 (0%) | `e26271fba7` |
| 스테이징 적재 DB 포트가 몇 번이었지? 짧게 답해 줘. | user_fact | early | n2 (10%) | `6459` |
| 내가 절대 수정하지 말라고 했던 디렉터리가 어디였지? 짧게 답해 줘. | constraint | early | n3 (22%) | `dags/prod` |
| 아까 네가 지연 지표 표에서 찾아 준, p99가 가장 높았던 엔드포인트가 어디였지? 짧게 답해 줘. | assistant_derived | mid | n4 (35%) | `/reports/daily` |
| 내가 적재 재시도 정책을 바꾸기 전에 먼저 확인하고 싶다고 했던 요청을 원문 그대로 다시 보여줘. | verbatim | mid | n5 (48%) | 아래 n5 원문 |
| 아까 붙여넣은 etl-runner.yaml 설정에서 retry.max_attempts 값이 얼마였지? 짧게 답해 줘. | paste_value | mid | n6 (60%) | `3172` |
| 증분 적재(B안)으로 정하면서 내가 기준으로 말한 적재 지연 상한이 몇 ms였지? 짧게 답해 줘. | decision_reason | late | n7 (74%) | `31` |
| warehouse-loader 스택 트레이스에 찍혀 있던 예외 코드(code=...)가 뭐였지? 짧게 답해 줘. | paste_value | late | n8 (88%) | `ETL-8602` |
| 아까 정한 Kafka 컨슈머 그룹 이름이 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |
| 내가 공유했던 Grafana 대시보드 UID가 뭐였지? 짧게 답해 줘. | negative | none | — | '기록에 없음' |

심은 턴의 요청문(붙여넣기는 앞 3줄만):

- **n1** (목표 0%)

````text
파이프라인 지연 건을 같이 보자. 먼저 report-svc 로그부터 붙여넣을게. 전체적으로 어떤 오류가 많은지 짧게 정리해 줘.

2026-03-12T05:00:00.473Z WARN  report-svc [req=rdc1914] GET /ingest/batch status=200 latency_ms=1324 trace=c8045983a5 user=u64672
2026-03-12T05:00:03.554Z INFO  report-svc [req=rf10cbc] GET /ingest/batch status=200 latency_ms=1088 trace=0131d24d8c user=u61930
2026-03-12T05:00:06.555Z ERROR report-svc [req=r618099] GET /load/commit status=204 latency_ms=155 trace=f00052229b user=u94041
… (182줄 더)
````

- **n2** (목표 10%)

````text
참고로 스테이징 적재 DB 포트는 6459번이고, 운영 적재 DB 포트는 5979번이야. 나중에 스크립트 짤 때 이 값 써야 하니까 기억해 둬.
````

- **n3** (목표 22%)

````text
아 그리고 중요한 거. 앞으로 dags/prod/ 디렉터리 아래 파일은 절대 수정하지 마. 운영 DAG라 바꾸면 야간 정산이 틀어져.
````

- **n4** (목표 35%)

````text
엔드포인트별 지연 지표야. 이 표 전체에서 p99_ms가 가장 높은 행의 엔드포인트와 그 값을 찾아 줘.

minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate
00:26,/ingest/batch,692,109,506,908,0.0161
07:37,/ingest/stream,856,14,368,525,0.0199
… (287줄 더)
````

- **n5** (목표 48%)

````text
적재 재시도 정책을 바꾸기 전에 세 가지를 먼저 확인하고 싶어. 첫째, 게이트웨이 타임아웃 30초와 클라이언트 타임아웃 5초의 차이 때문에 같은 요청이 두 번 처리되는지. 둘째, 재시도할 때마다 idempotency key가 새로 만들어지는지. 셋째, 실패 알림이 #ingest-alerts-854 채널로 제대로 가는지. 이 세 가지를 확인하기 전에는 코드를 바꾸지 말아 줘.
````

- **n6** (목표 60%)

````text
이건 etl-runner.yaml 설정 파일 전체야. 운영 반영 전에 위험한 값이 있는지 짧게 봐 줘.

# etl-runner.yaml
service: ingest-api
queue_pool:
… (1123줄 더)
````

- **n7** (목표 74%)

````text
결론적으로 전체 재적재(A안) 대신 증분 적재(B안)으로 가자. 적재 지연이 31ms를 넘으면 안 되거든. 이 기준은 팀에도 그대로 공유할 거야.
````

- **n8** (목표 88%)

````text
방금 warehouse-loader에서 난 스택 트레이스야. 원인이 뭐로 보이는지 짧게 알려 줘.

2026-03-12T10:00:21.788Z ERROR warehouse-loader: LoadCommitException: code=ETL-8602 message="shard retry failed after 5 attempts"
    at com.example.warehouseloader.SnapshotUpload.reader(Replica.java:410)
    at com.example.warehouseloader.QuotaIndex.replica(Queue.java:340)
… (34줄 더)
````

채움 턴 예시 (f001, metrics, 첫 400자):

````text
이 지표에서 이상한 구간만 짧게 알려 줘.

```
minute,endpoint,rps,p50_ms,p95_ms,p99_ms,error_rate
09:11,/ingest/batch,649,45,131,181,0.0025
21:53,/ingest/stream,486,93,363,379,0.0077
00:26,/etl/jobs,216,85,350,747,0.0120
01:31,/load/commit,410,71,110,474,0.0194
10:12,/reports/daily,842,95,228,919,0.0093
01:57,/scheduler/runs,344,35,63,512,0.0186
14:50,/ingest/batch,845,79,199,291,0.0031
13:35,/ingest/stream,525,82
…
````

