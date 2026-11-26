#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Time one run of the hook as Claude Code starts it: a separate process per event.

    python tests/bench_hook.py            (40 runs per event)
    python tests/bench_hook.py --runs 100

Not a test (unittest discovery does not pick it up). It prints, for the final hook and - when the
lab prototype is present - for the prototype under the same conditions:
  * wall-clock time of the whole process (interpreter start-up + the hook's own work)
  * the same through the command form that tools/install_hook.py registers ("-I -c <launcher>")
  * interpreter start-up alone, for reference

Everything happens in a temporary directory; nothing under the real home directory is used.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOOK = os.path.join(REPO, "hooks", "ctx_index.py")
PROTO = os.path.join(REPO, "lab", "proto", "ctx_proto.py")
LAUNCHER = "import sys;p=sys.argv[1];exec(compile(open(p,'rb').read(),p,'exec'),{'__name__':'__main__','__file__':p})"
SID = "bench-0000-4000-8000-000000000000"
REQ = "결제 모듈의 재시도 로직을 분석하고, 타임아웃이 중복 결제로 이어지는 경로가 있는지 확인해줘. 관련 파일은 payments/retry.py 야."
ANS = "안녕하세요!\n\n## 분석 결과\n\n재시도 로직은 타임아웃 불일치 때문에 같은 주문을 최대 3회까지 중복 전송할 수 있습니다.\n\n" + "세부 근거 문단입니다. " * 200


def run(argv, payload, env):
    t0 = time.perf_counter()
    cp = subprocess.run(argv, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    ms = (time.perf_counter() - t0) * 1000.0
    if cp.returncode != 0:
        raise SystemExit("hook exited %d: %s" % (cp.returncode, cp.stderr.decode("utf-8", "replace")[-300:]))
    return ms


def event(name, i, **kw):
    p = {"hook_event_name": name, "session_id": SID, "prompt_id": "bench-prompt-%05d" % i, "cwd": REPO, "transcript_path": ""}
    p.update(kw)
    return json.dumps(p, ensure_ascii=False).encode("utf-8")


def bench(label, argv, runs, base):
    env = dict(os.environ, CTX_INDEX_DIR=base)
    for i in range(30):                                  # a session with some history, as in real use
        run(argv, event("UserPromptSubmit", i, prompt=REQ), env)
        run(argv, event("Stop", i, last_assistant_message=ANS, stop_hook_active=False), env)
    rows = {}
    for name in ("UserPromptSubmit", "Stop", "SessionStart(compact)"):
        times = []
        for i in range(runs):
            n = 1000 + i
            if name == "UserPromptSubmit":
                times.append(run(argv, event("UserPromptSubmit", n, prompt=REQ), env))
            elif name == "Stop":
                times.append(run(argv, event("Stop", n, last_assistant_message=ANS, stop_hook_active=False), env))
            else:
                times.append(run(argv, event("SessionStart", n, source="compact"), env))
        rows[name] = times
    everything = [t for times in rows.values() for t in times]
    rows["all three events"] = everything
    for name, times in rows.items():
        times = sorted(times)
        print("  %-22s %-24s median %6.1f ms   p95 %6.1f ms   max %6.1f ms" % (
            label, name, statistics.median(times), times[int(0.95 * (len(times) - 1))], times[-1]))
    return statistics.median(everything)


def main():
    ap = argparse.ArgumentParser(description="Time one run of the ctx-index hook (separate process per event).")
    ap.add_argument("--runs", type=int, default=40)
    ap.add_argument("--python", default=sys.executable, help="interpreter to time (default: this one)")
    a = ap.parse_args()
    root = tempfile.mkdtemp(prefix="ctxidx-bench-")
    try:
        print("python %s on %s, %d runs per event, one process per run" % (
            subprocess.run([a.python, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"], stdout=subprocess.PIPE).stdout.decode().strip(),
            sys.platform, a.runs))
        start = sorted(run([a.python, "-I", "-c", "pass"], b"", dict(os.environ)) for _ in range(a.runs))
        print("  %-22s %-24s median %6.1f ms" % ("(interpreter alone)", "python -I -c pass", statistics.median(start)))
        final = bench("final hook", [a.python, HOOK], a.runs, os.path.join(root, "final"))
        launch = bench("final hook, installed", [a.python, "-I", "-c", LAUNCHER, HOOK], a.runs, os.path.join(root, "launch"))
        print("final hook: median %.1f ms (as registered by the installer: %.1f ms)" % (final, launch))
        if os.path.isfile(PROTO):
            proto = bench("lab prototype", [a.python, PROTO], a.runs, os.path.join(root, "proto"))
            print("lab prototype under the same conditions: median %.1f ms (the lab report measured 42 ms on its Linux container)" % proto)
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
