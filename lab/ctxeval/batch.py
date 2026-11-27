# 실행 여러 개를 r04·r05 때와 같은 절차로 진행한다: 두 실행씩 채우기를 동시에 돌리고, 질문 단계는 한 실행씩 차례로 돌린 뒤 집계한다.
# 사용: python batch.py s02k r08 r09 r10 r11
#       python batch.py s02k 3 s03 m01 m02 m03 m04   (압축 3회, 프롬프트 세트 s03 — fill.py에 그대로 넘긴다)
#   폴더는 new-run.ps1로 먼저 만든다. 끊기면 같은 명령을 다시 실행한다(끝난 단계는 건너뛴다).
#   단계별 출력은 runs\<실행>\fill.log, ask.log에 쌓인다.
import pathlib
import re
import subprocess
import sys

SETNAME, RUNS, FILL_ARGS = sys.argv[1], sys.argv[2:], []
if RUNS and RUNS[0].isdigit():
    FILL_ARGS, RUNS = RUNS[:2], RUNS[2:]
HERE = pathlib.Path(__file__).parent
PY = [sys.executable, "-I"]
JOBS = 2 * len(list((HERE / "prompts" / SETNAME).glob("q*.txt")))  # 질문 수 x 두 조건
# [의도] 실험이 구독 주간 한도를 다 써서 이 PC의 다른 Claude 작업이 막히지 않게, 이 사용률부터는 새 실행을 시작하지 않는다.
# [이유] 2026-11-27 실측: 압축 3회 실행 두 쌍이 한도를 약 3%p 쓴다(31분 동안 환산 $71에 4%p 상승).
STOP_AT = 90


def usage_percent():
    """주간 한도(모든 모델) 사용률. 읽지 못하면 None."""
    out = subprocess.run(PY + [str(HERE / "usage.py")], capture_output=True).stdout.decode("utf-8", "replace")
    m = re.search(r"all models=(\d+)%", out)
    return int(m[1]) if m else None


def answers(run):
    return len(list((HERE / "out" / ("%s-%s" % (run, SETNAME))).glob("q*.json")))


def fill_lines(run):
    log = HERE / "runs" / run / "fill.log"
    text = log.read_bytes().decode("cp949", "replace") if log.exists() else ""
    return [line.strip() for line in text.splitlines() if re.match(r"[AB] session=", line)]


def filled(run):
    """채우기가 두 조건 모두 점검을 통과했는지."""
    return all(any(line.startswith(c) and line.endswith(" OK") for line in fill_lines(run)) for c in "AB")


def start(run, step, script, *args):
    with open(HERE / "runs" / run / (step + ".log"), "ab") as log:
        return subprocess.Popen(PY + [str(HERE / script)] + list(args), stdout=log, stderr=subprocess.STDOUT)


failed = []
for i in range(0, len(RUNS), 2):
    pair = RUNS[i:i + 2]
    if not all(filled(run) for run in pair):
        used = usage_percent()
        print("usage before %s: %s%%" % (" ".join(pair), used), flush=True)
        if used is not None and used >= STOP_AT:
            print("STOPPED before %s: weekly usage %d%% >= %d%%" % (" ".join(pair), used, STOP_AT), flush=True)
            sys.exit(2)
    for proc in [start(run, "fill", "fill.py", run, *FILL_ARGS) for run in pair if not filled(run)]:
        proc.wait()
    for run in pair:
        if not filled(run):
            failed.append(run)
            print("%s fill FAILED, see runs\\%s\\fill.log" % (run, run), flush=True)
            continue
        print("\n".join("%s %s" % (run, line) for line in fill_lines(run)[-2:]), flush=True)
        for _ in range(3):  # 실패한 분기만 다시 묻는다(ask.py가 받은 답은 건너뛴다)
            if answers(run) >= JOBS:
                break
            start(run, "ask", "ask.py", run, SETNAME).wait()
        if answers(run) < JOBS:
            failed.append(run)
            print("%s ask INCOMPLETE answers=%d/%d, see runs\\%s\\ask.log" % (run, answers(run), JOBS, run), flush=True)
            continue
        done = subprocess.run(PY + [str(HERE / "analyze.py"), run, SETNAME], capture_output=True)
        print("%s %s" % (run, (done.stdout or done.stderr[-300:]).decode("cp949", "replace").strip()), flush=True)
    if failed:
        # 사용 한도 같은 공통 원인일 수 있어 다음 실행을 시작하지 않는다.
        break
sys.exit(1 if failed else 0)
