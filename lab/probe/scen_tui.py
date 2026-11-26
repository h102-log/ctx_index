ENTER = "\r"
SETTINGS = "probe-settings2.json"
ESC = "\x1b"
STEPS = [
    ("T1 normal prompt", ["대화형 첫 질문입니다", ENTER], 6),
    ("T2 /help", ["/help", ENTER], 4),
    ("T2b esc", [ESC], 2),
    ("T3 /status", ["/status", ENTER], 4),
    ("T3b esc", [ESC], 2),
    ("T4 /cost", ["/cost", ENTER], 4),
    ("T4b esc", [ESC], 2),
    ("T5 slow prompt then ESC interrupt", ["[[SLOW]] 느린 답변을 요청합니다", ENTER], 3),
    ("T5b esc interrupt", [ESC], 4),
    ("T6 prompt after interrupt", ["중단 이후 질문입니다", ENTER], 6),
    ("T7 bash mode", ["!echo bash-mode-probe", ENTER], 5),
    ("T8 /compact", ["/compact", ENTER], 10),
    ("T9 prompt after compact", ["압축 이후 대화형 질문", ENTER], 6),
    ("T10 /clear", ["/clear", ENTER], 5),
    ("T11 prompt after clear", ["clear 이후 대화형 질문", ENTER], 6),
    ("T12 /exit", ["/exit", ENTER], 5),
]
