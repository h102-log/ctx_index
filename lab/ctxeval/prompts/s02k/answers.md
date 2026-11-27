# 세트 s02k 정답표 (프롬프트는 s02)

| 질문 | 종류 | 정답 | 위치 |
|---|---|---|---|
| q01 아까 붙여 준 결제 게이트웨이(pay-gw) 로그의 cache stats 줄 가운데 evictions 가 가장 컸던 줄의 시각과 그 evictions 값이 뭐였지? | 최댓값 | 01:45:58, 36892 (region=ap-ne-2b) | p01.txt |
| q02 아까 붙여 준 결제 게이트웨이(pay-gw) 로그에서 맨 마지막에 실패한 job(ERROR 줄)의 job 이름과 cause 가 뭐였지? | 순서 | pay-gw-reindex, lock_wait_exceeded (attempt=2) | p01.txt |
| q03 아까 붙여 준 결제 게이트웨이(pay-gw) 로그에서 size_mb 가 가장 큰 백업 파일의 경로와 그 size_mb 가 뭐였지? | 최댓값 | /vault/weekly/sessions_2026w31.tar.zst, 88133 | p01.txt |
| q04 아까 붙여 준 인증 서비스(auth-svc) 로그에 ticket linked 줄이 모두 몇 건 있었지? | 건수 | 25 | p02.txt |
| q05 아까 붙여 준 인증 서비스(auth-svc) 로그에서 disk_usage_warning 경보가 모두 몇 번 발생했지? | 건수 | 5 | p02.txt |
| q06 아까 붙여 준 인증 서비스(auth-svc) 로그에서 맨 마지막에 발생한 경보(alert fired)의 시각과 rule 이 뭐였지? | 순서 | 16:23:16, fd_usage_high | p02.txt |
| q07 아까 붙여 준 주문 DB(order-db) 로그의 cache stats 줄 가운데 evictions 가 가장 컸던 줄의 시각과 그 evictions 값이 뭐였지? | 최댓값 | 19:35:13, 39492 (region=ap-ne-2b) | p03.txt |
| q08 아까 붙여 준 주문 DB(order-db) 로그에서 맨 마지막에 실패한 job(ERROR 줄)의 job 이름과 cause 가 뭐였지? | 순서 | order-db-reindex, lock_wait_exceeded (attempt=4) | p03.txt |
| q09 아까 붙여 준 주문 DB(order-db) 로그에서 size_mb 가 가장 큰 백업 파일의 경로와 그 size_mb 가 뭐였지? | 최댓값 | /vault/weekly/sessions_2026w34.tar.zst, 89458 | p03.txt |
| q10 아까 붙여 준 정산 배치(settle-batch) 로그에 status=500 으로 끝난 요청이 모두 몇 건 있었지? | 건수 | 12 | p04.txt |
| q11 아까 붙여 준 정산 배치(settle-batch) 로그에서 p99_latency_high 경보가 모두 몇 번 발생했지? | 건수 | 8 | p04.txt |
| q12 아까 붙여 준 정산 배치(settle-batch) 로그에서 맨 마지막에 발생한 경보(alert fired)의 시각과 rule 이 뭐였지? | 순서 | 13:45:46, p99_latency_high | p04.txt |
| q13 아까 붙여 준 이미지 리사이저(img-resize) 로그의 cache stats 줄 가운데 evictions 가 가장 컸던 줄의 시각과 그 evictions 값이 뭐였지? | 최댓값 | 03:24:11, 37851 (region=ap-se-1a) | p05.txt |
| q14 아까 붙여 준 이미지 리사이저(img-resize) 로그에서 맨 마지막에 실패한 job(ERROR 줄)의 job 이름과 cause 가 뭐였지? | 순서 | img-resize-reindex, oom_killed (attempt=2) | p05.txt |
| q15 아까 붙여 준 이미지 리사이저(img-resize) 로그에서 size_mb 가 가장 큰 백업 파일의 경로와 그 size_mb 가 뭐였지? | 최댓값 | /vault/weekly/users_2026w39.tar.zst, 79109 | p05.txt |
| q16 아까 붙여 준 알림 워커(notify-worker) 로그에 ERROR 레벨 줄이 모두 몇 건 있었지? | 건수 | 18 | p06.txt |
| q17 아까 붙여 준 알림 워커(notify-worker) 로그에서 disk_usage_warning 경보가 모두 몇 번 발생했지? | 건수 | 6 | p06.txt |
| q18 아까 붙여 준 알림 워커(notify-worker) 로그에서 맨 마지막에 발생한 경보(alert fired)의 시각과 rule 이 뭐였지? | 순서 | 01:47:52, gc_pause_long | p06.txt |
| q19 아까 붙여 준 로그 수집기(log-collector) 로그의 cache stats 줄 가운데 evictions 가 가장 컸던 줄의 시각과 그 evictions 값이 뭐였지? | 최댓값 | 07:37:16, 38038 (region=ap-ne-2b) | p07.txt |
| q20 아까 붙여 준 로그 수집기(log-collector) 로그에서 맨 마지막에 실패한 job(ERROR 줄)의 job 이름과 cause 가 뭐였지? | 순서 | log-collector-cleanup, quota_exceeded (attempt=4) | p07.txt |
| q21 아까 붙여 준 로그 수집기(log-collector) 로그에서 size_mb 가 가장 큰 백업 파일의 경로와 그 size_mb 가 뭐였지? | 최댓값 | /vault/daily/users_20261005.tar.zst, 81196 | p07.txt |
| q22 아까 붙여 준 추천 서빙(reco-serve) 로그에 pool resize 줄이 모두 몇 건 있었지? | 건수 | 23 | p08.txt |
| q23 아까 붙여 준 추천 서빙(reco-serve) 로그에서 queue_depth_high 경보가 모두 몇 번 발생했지? | 건수 | 6 | p08.txt |
| q24 아까 붙여 준 추천 서빙(reco-serve) 로그에서 맨 마지막에 발생한 경보(alert fired)의 시각과 rule 이 뭐였지? | 순서 | 15:35:03, error_ratio_high | p08.txt |
| q25 아까 붙여 준 주문 DB(order-db) 로그에서 status=418 로 끝난 요청이 모두 몇 건이었지? | 대조 | 0건 (그런 줄이 없다) | p03.txt |
| q26 아까 붙여 준 알림 워커(notify-worker) 로그에서 cause=disk_full 로 실패한 job 이 모두 몇 건이었지? | 대조 | 0건 (그런 줄이 없다) | p06.txt |
