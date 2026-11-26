#!/usr/bin/env python3
"""Drive the real interactive TUI through a pty (lab tooling for schema probing).

  PROBE_OUT=<file> python3 tui_drive.py <scenario module>
"""
import os, pty, sys, time, select, re, json, fcntl, termios, struct, signal

P = os.path.dirname(os.path.abspath(__file__))
R = os.environ.get("CTX_LAB_RUN") or os.path.join(P, ".run")   # prepared by setup_lab.py
ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][A-Za-z0-9]|\x1b[=>78]")
PAY = os.environ.get("PROBE_OUT") or os.path.join(R, "out", "payloads.jsonl")


def npay():
    try:
        return sum(1 for _ in open(PAY, encoding="utf-8"))
    except FileNotFoundError:
        return 0


def main(steps, settings):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(os.path.join(R, "proj"))
        os.execv(os.path.join(P, "run_cli.sh"), [os.path.join(P, "run_cli.sh"), "--settings", os.path.join(R, "settings", settings), "--allowedTools", "Bash"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 130, 0, 0))
    raw = open(os.path.join(R, "out", "tui.raw"), "wb")
    buf = b""

    def pump(secs):
        nonlocal buf
        end = time.time() + secs
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    return False
                if not data:
                    return False
                raw.write(data); raw.flush()
                buf += data
        return True

    def screen_tail(n=700):
        t = ANSI.sub("", buf.decode("utf-8", "replace"))
        t = re.sub(r"[ \t]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t[-n:]

    pump(8)
    print("=== after startup ===\n" + screen_tail(900))
    for label, keys, wait in steps:
        before = npay()
        buf = b""
        for k in keys:
            os.write(fd, k.encode("utf-8"))
            pump(0.4)
        alive = pump(wait)
        print(f"\n=== step: {label} | payloads +{npay()-before} | alive={alive} ===")
        print(screen_tail(500))
        if not alive:
            break
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    raw.close()


if __name__ == "__main__":
    import importlib
    sc = importlib.import_module(sys.argv[1])
    main(sc.STEPS, os.environ.get("PROBE_SETTINGS") or getattr(sc, "SETTINGS", "probe-settings.json"))
