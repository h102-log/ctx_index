ENTER = "\r"
SETTINGS = "probe-settings2.json"
STEPS = [
    ("Q1 slow prompt", ["[[SLOW]] Q1 느린 답변", ENTER], 2),
    ("Q2 queued while Q1 streaming", ["Q2 대기열에 넣은 질문", ENTER], 16),
    ("Q3 slow tool prompt", ["[[TOOL]] [[SLOW]] Q3 도구와 느린 응답", ENTER], 2),
    ("Q4 queued during tool turn", ["Q4 도구 턴 중 대기열 질문", ENTER], 26),
    ("exit", ["/exit", ENTER], 4),
]
