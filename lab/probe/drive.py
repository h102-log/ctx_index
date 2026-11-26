#!/usr/bin/env python3
"""Drive one real CLI process over stream-json stdin/stdout, one prompt at a time.
Lab tooling for schema probing; not part of the deliverable.

  PROBE_SETTINGS=probe-settings2.json PROBE_OUT=<file> python3 drive.py <scenario module>
"""
import json, os, subprocess, sys, threading, time, queue

P = os.path.dirname(os.path.abspath(__file__))
R = os.environ.get("CTX_LAB_RUN") or os.path.join(P, ".run")   # prepared by setup_lab.py


def run(steps, extra_args=(), out_path=None, env_extra=None, per_step_timeout=60):
    env = dict(os.environ)
    env.update(env_extra or {})
    cmd = [os.path.join(P, "run_cli.sh"), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
           "--verbose", "--settings", os.path.join(R, "settings", os.environ.get("PROBE_SETTINGS", "probe-settings.json")),
           "--allowedTools", "Bash", *extra_args]
    proc = subprocess.Popen(cmd, cwd=os.path.join(R, "proj"), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    q = queue.Queue()

    def reader():
        for line in proc.stdout:
            q.put(line)
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    errbuf = []
    threading.Thread(target=lambda: errbuf.extend(proc.stderr.readlines()), daemon=True).start()
    log = open(out_path, "a", encoding="utf-8") if out_path else None
    summary = []
    for step in steps:
        if callable(step):
            summary.append(("ACTION", step()))
            continue
        msg = {"type": "user", "message": {"role": "user", "content": step}}
        proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        proc.stdin.flush()
        t0 = time.time()
        events = []
        result = None
        while time.time() - t0 < per_step_timeout:
            try:
                line = q.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                ev = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if log:
                log.write(json.dumps({"step": step, "ev": ev}, ensure_ascii=False) + "\n")
            tag = ev.get("type") + (":" + str(ev.get("subtype")) if ev.get("subtype") else "")
            events.append(tag)
            if ev.get("type") == "result":
                result = ev
                break
        summary.append((step, events, (result or {}).get("session_id"), ((result or {}).get("result") or "")[:80]))
        time.sleep(0.5)
    proc.stdin.close()
    try:
        proc.wait(timeout=30)
    except Exception:
        proc.kill()
    if log:
        log.close()
    return summary, b"".join(errbuf).decode("utf-8", "replace")


if __name__ == "__main__":
    import importlib
    scenario = importlib.import_module(sys.argv[1])
    summary, err = run(scenario.STEPS, getattr(scenario, "ARGS", ()), os.path.join(R, "out", sys.argv[1] + ".events.jsonl"), getattr(scenario, "ENV", None))
    for s in summary:
        print(json.dumps(s, ensure_ascii=False))
    print("STDERR:", err[-1500:])
