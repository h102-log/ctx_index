ENTER = "\r"
SETTINGS = "probe-settings2.json"
STEPS = [
    ("N1 normal prompt (idle)", ["N1 평범한 질문", ENTER], 5),
    ("N2 custom slash (idle)", ["/mycmd 대화형 인자", ENTER], 6),
    ("Q1 slow prompt", ["[[SLOW]] Q1 느린 답변", ENTER], 2),
    ("Q2 queued during Q1 (also slow)", ["[[SLOW]] Q2 첫 번째 대기열", ENTER], 9),
    ("Q5 queued during Q2", ["Q5 두 번째 대기열", ENTER], 14),
    ("exit", ["/exit", ENTER], 4),
]
