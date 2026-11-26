import subprocess, os
P = os.path.dirname(os.path.abspath(__file__))
R = os.environ.get("CTX_LAB_RUN") or os.path.join(P, ".run")
def branch():
    r = subprocess.run(["git", "-C", os.path.join(R, "proj"), "checkout", "-q", "-b", "feature/branch-x"], capture_output=True, text=True)
    return "git checkout -b feature/branch-x rc=%d %s" % (r.returncode, r.stderr.strip())
STEPS = [
    "첫 번째 질문: 한글 테스트입니다",
    "[[TOOL]] 도구를 써서 답해줘",
    "[[AGENT]] 서브에이전트를 써서 답해줘",
    "/mycmd 인자1 인자2",
    branch,
    "브랜치 전환 후 질문입니다",
    "/compact",
    "압축 후 첫 질문입니다",
    "/cost",
    "/help",
    "/status",
    "[[EMPTY]] 빈 답변 케이스",
    "/clear",
    "clear 이후 질문입니다",
]
