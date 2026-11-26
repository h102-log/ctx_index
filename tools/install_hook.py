#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Register the ctx-index hook in a Claude Code settings.json (merge, never overwrite).

    python tools/install_hook.py                 install / update (user settings: ~/.claude/settings.json)
    python tools/install_hook.py --dry-run       show what would change, write nothing
    python tools/install_hook.py --status        show what is registered, change nothing
    python tools/install_hook.py --uninstall     remove the registration again

What it does
  * Copies hooks/ctx_index.py to <settings dir>/hooks/ctx_index.py (~/.claude/hooks by default) and
    registers that copy, so that switching branches in or moving this repository cannot change or
    break the hook of a running session. --in-place registers the repository file itself.
  * Adds the hook to UserPromptSubmit, Stop and SessionStart (matcher "compact"). Existing hooks and
    all other settings are kept. Running it again changes nothing; an older ctx-index registration
    is updated in place instead of being added a second time.
  * Before the first change it copies settings.json to settings.json.bak-<timestamp>.
  * Before settings.json is changed it runs the command once against a throwaway directory, the way
    Claude Code would start it, and checks that a turn file with non-ASCII text appears. If that
    fails, nothing is registered.

How the interpreter is addressed
  The command is the absolute path of the Python that runs this installer (override: --python). A
  bare "python" would depend on the PATH of whatever starts the hook, and on Windows it may resolve
  to the Microsoft Store stub.

Why the command is "python -I -c <launcher> <hook>" rather than "python <hook>"
  If the hook file is ever missing, "python <hook>" exits with status 2, and Claude Code treats
  status 2 of a UserPromptSubmit hook as "block this prompt" - every prompt would be rejected until
  the settings are repaired (measured on 2.1.332). The launcher makes a missing file an ordinary
  error (status 1): the prompt goes through and the CLI shows a hook error. -I keeps the working
  directory and PYTHON* variables from shadowing standard library modules.

Forms (--form)
  exec        "command" + "args", started without a shell (default; verified on Linux only)
  bash        one command line with "shell": "bash" (Git Bash on Windows)
  powershell  one command line with "shell": "powershell"
The shell forms are fallbacks for a machine where the exec form does not work.

Standard library only.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HOOK_NAME = "ctx_index.py"
EVENTS = (("UserPromptSubmit", None), ("Stop", None), ("SessionStart", "compact"))
DEFAULT_TIMEOUT = 15
# Runs the hook file given as the first argument as __main__. Single quotes only and no backslash,
# so that it survives Windows command-line quoting unchanged.
LAUNCHER = "import sys;p=sys.argv[1];exec(compile(open(p,'rb').read(),p,'exec'),{'__name__':'__main__','__file__':p})"
POWERSHELL_ARGS = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"]   # as the CLI starts it


class InstallError(Exception):
    pass


def say(msg=""):
    sys.stdout.write(msg + "\n")


# ----------------------------------------------------------------------------- the hook entry
def bash_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def powershell_quote(s):
    return "'" + s.replace("'", "''") + "'"


def to_bash_path(path, sep=os.sep):
    """Git Bash takes C:/Users/... ; on POSIX the path is left alone."""
    return path.replace("\\", "/") if sep == "\\" else path


def hook_entry(python, hook, form, timeout):
    """The settings.json hook object for one event."""
    if form == "exec":
        return {"type": "command", "command": python, "args": ["-I", "-c", LAUNCHER, hook], "timeout": timeout}
    if form == "bash":
        py, hk = to_bash_path(python), to_bash_path(hook)
        launcher = LAUNCHER.replace("'", '"')
        return {"type": "command", "command": "%s -I -c %s %s" % (bash_quote(py), bash_quote(launcher), bash_quote(hk)),
                "shell": "bash", "timeout": timeout}
    if form == "powershell":
        return {"type": "command", "command": "& %s -I -c %s %s" % (powershell_quote(python), powershell_quote(LAUNCHER), powershell_quote(hook)),
                "shell": "powershell", "timeout": timeout}
    raise InstallError("unknown form: %r" % (form,))


_OURS = re.compile(r"(?:^|[\\/\s'\"])%s(?=$|[\s'\"])" % re.escape(HOOK_NAME), re.I)


def is_ours(h):
    """True for a hook object that runs a file named ctx_index.py (whatever its path or form)."""
    if not isinstance(h, dict):
        return False
    parts = [h.get("command")] + (h.get("args") if isinstance(h.get("args"), list) else [])
    return any(isinstance(p, str) and _OURS.search(p) for p in parts)


def hook_paths(h):
    """Paths of the hook script named by a registration, whatever its form."""
    if isinstance(h.get("args"), list):
        return [a for a in h["args"] if isinstance(a, str) and a.lower().endswith(HOOK_NAME) and "\n" not in a]
    cmd = h.get("command")
    if not isinstance(cmd, str):
        return []
    name = re.escape(HOOK_NAME)
    if h.get("shell") == "powershell":                   # '...' with '' for a quote inside
        m = re.search(r"'((?:[^']|'')*%s)'\s*$" % name, cmd, re.I)
        if m:
            return [m.group(1).replace("''", "'")]
    m = re.search(r"'((?:[^']|'\\'')*%s)'\s*$" % name, cmd, re.I)      # bash: '...' with '\'' for a quote inside
    if m:
        return [m.group(1).replace("'\\''", "'")]
    return [t.strip("\"'") for t in cmd.split() if t.strip("\"'").lower().endswith(HOOK_NAME)]


def describe(h):
    if isinstance(h.get("args"), list):
        return "%s %s" % (h.get("command"), " ".join(str(a) if a != LAUNCHER else "<launcher>" for a in h["args"]))
    return str(h.get("command")).replace(LAUNCHER, "<launcher>").replace(LAUNCHER.replace("'", '"'), "<launcher>")


# ----------------------------------------------------------------------------- settings.json
def read_settings(path):
    """(settings dict, raw bytes or None). Never guesses: unreadable JSON is an error."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return {}, None
    text = raw.decode("utf-8-sig")
    if not text.strip():
        return {}, raw
    try:
        data = json.loads(text)
    except ValueError as e:
        raise InstallError("%s 을(를) JSON으로 읽을 수 없습니다 (%s). 파일을 고친 뒤 다시 실행하세요. 아무것도 바꾸지 않았습니다." % (path, e))
    if not isinstance(data, dict):
        raise InstallError("%s 의 최상위 값이 JSON 객체가 아닙니다. 아무것도 바꾸지 않았습니다." % path)
    return data, raw


def groups_of(settings, event, create=False):
    hooks = settings.get("hooks")
    if hooks is None:
        if not create:
            return []
        hooks = settings["hooks"] = {}
    if not isinstance(hooks, dict):
        raise InstallError('"hooks" 값이 객체가 아닙니다. 아무것도 바꾸지 않았습니다.')
    groups = hooks.get(event)
    if groups is None:
        if not create:
            return []
        groups = hooks[event] = []
    if not isinstance(groups, list):
        raise InstallError('"hooks.%s" 값이 배열이 아닙니다. 아무것도 바꾸지 않았습니다.' % event)
    for g in groups:
        if not isinstance(g, dict) or not isinstance(g.get("hooks", []), list):
            raise InstallError('"hooks.%s" 안에 예상하지 못한 형태의 항목이 있습니다. 아무것도 바꾸지 않았습니다.' % event)
    return groups


def find_ours(settings):
    """[(event, group index, hook index, matcher, hook object)] for every ctx-index registration."""
    out = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for gi, g in enumerate(groups):
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                continue
            for hi, h in enumerate(g["hooks"]):
                if is_ours(h):
                    out.append((event, gi, hi, g.get("matcher"), h))
    return out


def remove_ours(settings, only_event=None):
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    removed = 0
    for event in list(hooks):
        groups = hooks[event]
        if (only_event and event != only_event) or not isinstance(groups, list):
            continue
        kept, here = [], 0
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list) and any(is_ours(h) for h in g["hooks"]):
                rest = [h for h in g["hooks"] if not is_ours(h)]
                here += len(g["hooks"]) - len(rest)
                if rest:
                    g["hooks"] = rest
                    kept.append(g)
            else:
                kept.append(g)
        removed += here
        if here:
            hooks[event] = kept
            if not kept and not only_event:
                del hooks[event]                  # only what this call emptied; the user's own empty lists stay
    if removed and not hooks and not only_event:
        del settings["hooks"]
    return removed


def apply_install(settings, entry):
    """Merge the registration into settings (in place). Returns a list of human-readable changes."""
    changes = []
    for event, matcher in EVENTS:
        groups = groups_of(settings, event, create=True)
        ours = [(gi, hi) for gi, g in enumerate(groups) for hi, h in enumerate(g.get("hooks", [])) if is_ours(h)]
        if len(ours) == 1:
            gi, hi = ours[0]
            if matcher is None or groups[gi].get("matcher") == matcher:
                if groups[gi]["hooks"][hi] != entry:
                    groups[gi]["hooks"][hi] = dict(entry)
                    changes.append("%s: 기존 ctx-index 등록을 갱신" % event)
                continue
        if ours:
            remove_ours(settings, only_event=event)
            groups = groups_of(settings, event, create=True)
            changes.append("%s: 기존 ctx-index 등록 %d건을 정리하고 다시 등록" % (event, len(ours)))
        else:
            changes.append("%s: 등록%s" % (event, ' (matcher "%s")' % matcher if matcher else ""))
        group = {"matcher": matcher, "hooks": [dict(entry)]} if matcher else {"hooks": [dict(entry)]}
        groups.append(group)
    stray = [o for o in find_ours(settings) if o[0] not in [e for e, _m in EVENTS]]
    for event in sorted(set(o[0] for o in stray)):
        remove_ours(settings, only_event=event)
        if not settings["hooks"].get(event):
            del settings["hooks"][event]
        changes.append("%s: 이 이벤트에는 등록하지 않으므로 ctx-index 항목을 제거" % event)
    return changes


def serialize(settings, raw):
    """JSON text in the style of the existing file (indent and line endings), UTF-8 without BOM."""
    indent, newline = 2, "\n"
    if raw:
        text = raw.decode("utf-8-sig")
        if "\r\n" in text:
            newline = "\r\n"
        for line in text.splitlines()[1:]:
            stripped = line.lstrip(" \t")
            if stripped and line != stripped:
                lead = line[:len(line) - len(stripped)]
                indent = "\t" if lead[0] == "\t" else len(lead)
                break
    out = json.dumps(settings, ensure_ascii=False, indent=indent) + "\n"
    return out.replace("\n", newline).encode("utf-8")


def replace_file(path, data):
    """Write atomically: a reader sees the old file or the new one, never a partial one."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".%s.tmp%d" % (os.path.basename(path), os.getpid()))
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        for i in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:               # Windows: the target is open in another process right now
                if i == 19:
                    raise
                time.sleep(0.05 * (i + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def backup(path, raw):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = "%s.bak-%s" % (path, stamp)
    n = 1
    while os.path.exists(target):
        n += 1
        target = "%s.bak-%s-%d" % (path, stamp, n)
    with open(target, "xb") as f:
        f.write(raw)
    return target


# ----------------------------------------------------------------------------- checks
def default_settings_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "settings.json")


def default_python():
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):        # inside a venv: use the interpreter behind it
        base = getattr(sys, "_base_executable", None)
        if base and os.path.isfile(base):
            return os.path.abspath(base), "가상 환경 밖의 기본 인터프리터를 등록합니다(가상 환경을 지워도 훅이 동작하도록)."
    return os.path.abspath(sys.executable), None


def check_python(python):
    """The interpreter must start in isolated mode and be new enough."""
    try:
        cp = subprocess.run([python, "-I", "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise InstallError("Python 인터프리터를 실행할 수 없습니다: %s (%s)" % (python, e))
    version = cp.stdout.decode("ascii", "replace").strip()
    parts = version.split(".")
    if cp.returncode != 0 or len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise InstallError("Python 인터프리터가 예상과 다르게 응답했습니다: %s (종료 코드 %s, 출력 %r)" % (python, cp.returncode, version[:80]))
    if (int(parts[0]), int(parts[1])) < (3, 8):
        raise InstallError("Python 3.8 이상이 필요합니다: %s 은(는) %s 입니다." % (python, version))
    return version


def find_bash():
    """bash as Claude Code would use it: on Windows that is Git Bash, never the WSL launcher in System32."""
    if os.name != "nt":
        return shutil.which("bash")
    found = shutil.which("bash")
    candidates = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), "C:\\Program Files\\Git\\bin\\bash.exe",
                  "C:\\Program Files (x86)\\Git\\bin\\bash.exe", found if found and "system32" not in found.lower() else None]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def find_powershell():
    return shutil.which("pwsh") or shutil.which("powershell")


def command_line(entry, form):
    """argv that starts the registered hook the way Claude Code 2.1.332 does, or None if the shell is missing."""
    if form == "exec":
        return [entry["command"]] + entry["args"]
    if form == "bash":
        bash = find_bash()
        return [bash, "-c", entry["command"]] if bash else None
    shell = find_powershell()
    return [shell] + POWERSHELL_ARGS + [entry["command"]] if shell else None


def self_test(entry, form):
    """Start the registered command once with a sample payload; (ok, detail)."""
    argv = command_line(entry, form)
    if argv is None:
        return None, "%s 을(를) 찾지 못해 실행 점검을 건너뜁니다." % ("bash" if form == "bash" else "PowerShell")
    probe = "설치 점검: 한글 · emoji 🙂"
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "install-self-test", "prompt_id": "self-test-prompt",
               "prompt": probe, "cwd": os.getcwd(), "transcript_path": ""}
    tmp = tempfile.mkdtemp(prefix="ctx-index-selftest-")
    try:
        env = dict(os.environ, CTX_INDEX_DIR=tmp)
        try:
            cp = subprocess.run(argv, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            return False, "명령을 시작하지 못했습니다: %s" % e
        turn = os.path.join(tmp, "install-self-test", "turns", "0001.md")
        if cp.returncode != 0:
            return False, "종료 코드 %d, stderr: %s" % (cp.returncode, cp.stderr.decode("utf-8", "replace").strip()[-400:])
        if cp.stdout.strip():
            return False, "UserPromptSubmit 에서 stdout 출력이 있었습니다: %r" % cp.stdout[:120]
        if not os.path.isfile(turn):
            return False, "턴 파일이 만들어지지 않았습니다(훅이 입력을 받지 못했을 수 있습니다). stderr: %s" % cp.stderr.decode("utf-8", "replace").strip()[-400:]
        with open(turn, "rb") as f:
            if probe.encode("utf-8") not in f.read():
                return False, "턴 파일에 입력 원문이 그대로 들어 있지 않습니다(인코딩 손상)."
        return True, "종료 코드 0, stdout 0바이트, 턴 파일에 원문 저장 확인"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def hook_version(path):
    try:
        with open(path, "rb") as f:
            for line in f.read(8000).decode("utf-8", "replace").splitlines():
                if line.startswith("VERSION = "):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def same_file_content(a, b):
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


# ----------------------------------------------------------------------------- actions
def status(settings_path, source):
    settings, raw = read_settings(settings_path)
    say("설정 파일: %s%s" % (settings_path, "" if raw is not None else " (없음)"))
    ours = find_ours(settings)
    if not ours:
        say("ctx-index 훅이 등록되어 있지 않습니다.")
        return 1
    wanted = dict(EVENTS)
    seen = {}
    for event, _gi, _hi, matcher, h in ours:
        seen[event] = seen.get(event, 0) + 1
        note = ""
        if event not in wanted:
            note = "  <- 등록 대상이 아닌 이벤트"
        elif wanted[event] and matcher != wanted[event]:
            note = '  <- matcher 가 "%s" 이어야 합니다' % wanted[event]
        say("  %s%s: %s (timeout %s)%s" % (event, ' [matcher "%s"]' % matcher if matcher else "", describe(h), h.get("timeout"), note))
    missing = [e for e in wanted if e not in seen]
    doubled = [e for e, n in seen.items() if n > 1]
    if missing:
        say("등록되지 않은 이벤트: %s" % ", ".join(missing))
    if doubled:
        say("중복 등록된 이벤트: %s" % ", ".join(doubled))
    paths = set()
    for _e, _gi, _hi, _m, h in ours:
        paths.update(hook_paths(h))
    for p in sorted(paths):
        if not os.path.isfile(p):
            say("  경고: 등록된 훅 파일이 없습니다: %s" % p)
        elif source and os.path.isfile(source):
            same = same_file_content(p, source)
            say("  훅 파일: %s (버전 %s, 저장소의 훅과 %s)" % (p, hook_version(p), "같음" if same else "다름 — 설치를 다시 실행하면 갱신됩니다"))
    if settings.get("disableAllHooks") is True:
        say('  경고: "disableAllHooks": true 가 설정되어 있어 훅이 실행되지 않습니다.')
    return 0 if not missing and not doubled else 1


def uninstall(settings_path, dry_run):
    settings, raw = read_settings(settings_path)
    ours = find_ours(settings)
    if not ours:
        say("ctx-index 훅이 등록되어 있지 않습니다. 바꾼 것이 없습니다: %s" % settings_path)
        return 0
    remove_ours(settings)
    data = serialize(settings, raw)
    say("제거할 등록: %d건 (%s)" % (len(ours), ", ".join(sorted(set(o[0] for o in ours)))))
    if dry_run:
        say("--dry-run: 파일을 바꾸지 않았습니다.")
        return 0
    say("백업: %s" % backup(settings_path, raw))
    replace_file(settings_path, data)
    say("제거했습니다: %s" % settings_path)
    say("복사해 둔 훅 파일과 기록(~/.claude/ctx-index)은 그대로 둡니다. 필요 없으면 직접 지우세요.")
    return 0


def install(a):
    settings_path = os.path.abspath(a.settings)
    source = os.path.abspath(a.hook)
    if not os.path.isfile(source):
        raise InstallError("훅 파일이 없습니다: %s" % source)
    note = None
    if a.python:
        python = a.python if os.path.isfile(a.python) else (shutil.which(a.python) or a.python)
        python = os.path.abspath(python)
    else:
        python, note = default_python()
    if not os.path.isfile(python):
        raise InstallError("Python 인터프리터를 찾을 수 없습니다: %s" % python)
    version = check_python(python)
    settings, raw = read_settings(settings_path)
    if a.in_place:
        target = source
    else:
        target = os.path.join(os.path.abspath(a.hook_dir) if a.hook_dir else os.path.join(os.path.dirname(settings_path), "hooks"), HOOK_NAME)
    entry = hook_entry(python, target, a.form, a.timeout)
    before = json.dumps(settings, sort_keys=True)
    changes = apply_install(settings, entry)
    changed = json.dumps(settings, sort_keys=True) != before
    copy_needed = not a.in_place and not same_file_content(source, target)

    say("설정 파일: %s%s" % (settings_path, "" if raw is not None else " (새로 만듭니다)"))
    say("Python: %s (%s)" % (python, version))
    if note:
        say("  " + note)
    say("훅 파일: %s (버전 %s)%s" % (target, hook_version(source), "" if not a.in_place else " — 저장소의 파일을 그대로 등록"))
    if a.in_place:
        say("  주의: 이 파일을 옮기거나 다른 브랜치로 바꾸면 실행 중인 세션의 훅이 함께 바뀌거나 실패합니다.")
    elif copy_needed:
        say("  %s 에서 복사합니다%s." % (source, " (기존 복사본을 갱신)" if os.path.exists(target) else ""))
    say("형식: %s — %s" % (a.form, describe(entry)))
    for c in changes:
        say("  " + c)
    if not changed:
        say("  등록은 이미 최신입니다.")
    if settings.get("disableAllHooks") is True:
        say('  경고: "disableAllHooks": true 가 설정되어 있어 훅이 실행되지 않습니다.')
    if a.dry_run:
        say("--dry-run: 파일을 바꾸지 않았습니다.")
        return 0
    if copy_needed:
        with open(source, "rb") as f:
            replace_file(target, f.read())
    if not a.no_selftest:                                        # before settings.json is touched
        ok, detail = self_test(entry, a.form)
        if ok is None:
            say("실행 점검: 건너뜀 — " + detail)
        elif ok:
            say("실행 점검: 통과 — " + detail)
        else:
            say("실행 점검: 실패 — " + detail)
            say("  이 형식의 명령이 이 컴퓨터에서 동작하지 않아 설정 파일은 바꾸지 않았습니다.")
            say("  --form bash 또는 --form powershell 로 다시 실행해 보세요.")
            return 1
    if changed:
        data = serialize(settings, raw)
        json.loads(data.decode("utf-8"))                         # what is about to be written parses back
        if raw is not None:
            say("백업: %s" % backup(settings_path, raw))
        replace_file(settings_path, data)
        say("등록했습니다.")
    elif copy_needed:
        say("훅 파일만 갱신했습니다. 설정 파일은 바꾸지 않았습니다.")
    else:
        say("바꾼 것이 없습니다.")
    say("새로 시작하는 Claude Code 세션부터 적용됩니다. 제거하려면 --uninstall 로 다시 실행하세요.")
    return 0


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Register the ctx-index hook in a Claude Code settings.json (merge with backup).")
    ap.add_argument("--settings", default=default_settings_path(), help="settings file to change (default: ~/.claude/settings.json)")
    ap.add_argument("--hook", default=os.path.join(os.path.dirname(here), "hooks", HOOK_NAME), help="hook script to install (default: ../hooks/ctx_index.py)")
    ap.add_argument("--hook-dir", help="directory the hook is copied to (default: <settings directory>/hooks)")
    ap.add_argument("--in-place", action="store_true", help="register --hook where it is instead of copying it")
    ap.add_argument("--python", help="interpreter that runs the hook (default: the one running this installer)")
    ap.add_argument("--form", choices=("exec", "bash", "powershell"), default="exec", help="how the command is written (default: exec)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="hook timeout in seconds (default: %d)" % DEFAULT_TIMEOUT)
    ap.add_argument("--no-selftest", action="store_true", help="do not try the command once before registering it")
    ap.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    ap.add_argument("--status", action="store_true", help="show the current registration; change nothing")
    ap.add_argument("--uninstall", action="store_true", help="remove the ctx-index registration")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    try:
        if a.status:
            return status(os.path.abspath(a.settings), os.path.abspath(a.hook))
        if a.uninstall:
            return uninstall(os.path.abspath(a.settings), a.dry_run)
        return install(a)
    except InstallError as e:
        say("오류: %s" % e)
        return 1
    except UnicodeDecodeError as e:
        say("오류: 설정 파일이 UTF-8이 아닙니다 (%s). 아무것도 바꾸지 않았습니다." % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
