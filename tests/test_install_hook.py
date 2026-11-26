# -*- coding: utf-8 -*-
"""Tests for tools/install_hook.py: merge into settings.json with a backup, keep existing hooks,
no duplicate registration on a second run - and the registered command really starts the hook.

Every test works on a settings file inside a temporary directory; the real
~/.claude/settings.json is never opened (support.py also points HOME at a throwaway directory).
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # make `support` importable however the tests are started
import support as S  # noqa: E402

inst = S.load_module("install_hook", os.path.join(S.TOOLS, "install_hook.py"))
SCRIPT = os.path.join(S.TOOLS, "install_hook.py")
EVENTS = ["UserPromptSubmit", "Stop", "SessionStart"]

USER_SETTINGS = {
    "model": "opus",
    "permissions": {"allow": ["Bash(git status:*)"], "deny": []},
    "env": {"한글_키": "값 🙂"},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/notify.py", "timeout": 5}]}],
        "SessionStart": [
            {"matcher": "startup", "hooks": [{"type": "command", "command": "echo start"}]},
            {"matcher": "compact", "hooks": [{"type": "command", "command": "echo after-compact"}]},
        ],
        "Notification": [],
    },
    "statusLine": {"type": "command", "command": "echo status"},
}


def ours(settings):
    return [(e, m, h) for e, _gi, _hi, m, h in inst.find_ours(settings)]


def without_ours(settings):
    s = copy.deepcopy(settings)
    inst.remove_ours(s)
    return s


class InstallCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ctxidx-install-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = os.path.join(self.root, "home", ".claude")
        os.makedirs(self.cfg)
        self.settings = os.path.join(self.cfg, "settings.json")

    def write(self, obj, path=None, raw=None):
        with open(path or self.settings, "wb") as f:
            f.write(raw if raw is not None else json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))

    def read(self, path=None):
        with open(path or self.settings, "rb") as f:
            return f.read()

    def load(self, path=None):
        return json.loads(self.read(path).decode("utf-8"))

    def cli(self, *args, **kw):
        argv = [sys.executable, SCRIPT, "--settings", kw.pop("settings", self.settings)] + list(args)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")        # a pipe would otherwise get the ANSI code page on Windows
        env.update(kw.pop("env", {}))
        cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=300)
        cp.text = cp.stdout.decode("utf-8", "replace")
        return cp

    def backups(self):
        return sorted(n for n in os.listdir(self.cfg) if n.startswith("settings.json.bak-"))

    def listing(self):
        out = {}
        for d, _dirs, files in os.walk(self.root):
            for n in files:
                p = os.path.join(d, n)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, self.root)] = f.read()
        return out


class Install(InstallCase):
    def test_i_fresh_install_creates_the_three_registrations(self):
        cp = self.cli()
        self.assertEqual((cp.returncode, cp.stderr), (0, b""), cp.text)
        s = self.load()
        self.assertEqual(list(s), ["hooks"])
        self.assertEqual(list(s["hooks"]), EVENTS)
        target = os.path.join(self.cfg, "hooks", "ctx_index.py")
        for event in EVENTS:
            (group,) = s["hooks"][event]
            (h,) = group["hooks"]
            self.assertEqual(group.get("matcher"), "compact" if event == "SessionStart" else None)
            self.assertEqual(sorted(h), ["args", "command", "timeout", "type"])
            self.assertEqual((h["type"], h["timeout"]), ("command", 15))
            self.assertTrue(os.path.isabs(h["command"]) and os.path.isfile(h["command"]))
            self.assertEqual(h["args"], ["-I", "-c", inst.LAUNCHER, target])
        self.assertEqual(self.read(target), self.read(S.HOOK))                  # the registered file is a copy of the hook
        self.assertEqual(self.backups(), [])                                    # there was nothing to back up
        self.assertIn("실행 점검: 통과", cp.text)
        self.assertTrue(self.read().endswith(b"}\n"))

    def test_i_existing_settings_and_hooks_are_preserved(self):
        self.write(USER_SETTINGS)
        original = self.read()
        cp = self.cli()
        self.assertEqual(cp.returncode, 0, cp.text)
        s = self.load()
        self.assertEqual(without_ours(s), USER_SETTINGS)                        # everything else is exactly as before
        self.assertEqual(list(s), list(USER_SETTINGS))                          # key order too
        self.assertEqual(list(s["hooks"]), ["PreToolUse", "Stop", "SessionStart", "Notification", "UserPromptSubmit"])
        self.assertEqual([e for e, _m, _h in ours(s)], ["Stop", "SessionStart", "UserPromptSubmit"])
        self.assertEqual(s["hooks"]["Stop"][0], USER_SETTINGS["hooks"]["Stop"][0])            # the user's Stop hook still runs first
        self.assertEqual(s["hooks"]["SessionStart"][:2], USER_SETTINGS["hooks"]["SessionStart"])
        self.assertEqual(s["hooks"]["SessionStart"][2]["matcher"], "compact")
        self.assertEqual(s["hooks"]["Notification"], [])
        (bak,) = self.backups()
        self.assertEqual(self.read(os.path.join(self.cfg, bak)), original)      # byte-for-byte backup of the old file
        self.assertIn("값 🙂".encode("utf-8"), self.read())                     # non-ASCII kept readable

    def test_i_second_run_changes_nothing(self):
        self.write(USER_SETTINGS)
        self.assertEqual(self.cli().returncode, 0)
        first = self.listing()
        cp = self.cli()
        self.assertEqual(cp.returncode, 0, cp.text)
        self.assertIn("바꾼 것이 없습니다", cp.text)
        self.assertEqual(self.listing(), first)                                 # no second registration, no second backup
        s = self.load()
        self.assertEqual(sorted(e for e, _m, _h in ours(s)), sorted(EVENTS))
        for _ in range(3):
            self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(self.listing(), first)

    def test_i_older_registrations_are_updated_not_duplicated(self):
        old = {"type": "command", "command": "python3", "args": ["/old/place/ctx_index.py"], "timeout": 15}
        old_shell = {"type": "command", "command": 'python "C:\\old\\CTX_INDEX.PY"'}
        s = copy.deepcopy(USER_SETTINGS)
        s["hooks"]["UserPromptSubmit"] = [{"hooks": [dict(old)]}]
        s["hooks"]["Stop"].append({"hooks": [dict(old), {"type": "command", "command": "echo another"}]})
        s["hooks"]["Stop"].append({"hooks": [dict(old_shell)]})                                # registered twice by mistake
        s["hooks"]["SessionStart"].insert(0, {"hooks": [dict(old)]})                           # without the compact matcher
        s["hooks"]["PreCompact"] = [{"hooks": [dict(old)]}]                                    # an event the hook is not for
        self.write(s)
        cp = self.cli()
        self.assertEqual(cp.returncode, 0, cp.text)
        new = self.load()
        got = ours(new)
        self.assertEqual(sorted(e for e, _m, _h in got), sorted(EVENTS))                       # exactly one each
        self.assertEqual([m for e, m, _h in got if e == "SessionStart"], ["compact"])
        self.assertTrue(all(h["args"][-1] == os.path.join(self.cfg, "hooks", "ctx_index.py") for _e, _m, h in got))
        self.assertNotIn("PreCompact", new["hooks"])
        self.assertIn({"type": "command", "command": "echo another"}, [h for g in new["hooks"]["Stop"] for h in g["hooks"]])
        expect = copy.deepcopy(USER_SETTINGS)
        expect["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo another"}]})
        self.assertEqual(without_ours(new)["hooks"]["Stop"], expect["hooks"]["Stop"])
        self.assertEqual(without_ours(new)["hooks"]["SessionStart"], USER_SETTINGS["hooks"]["SessionStart"])
        again = self.read()
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(self.read(), again)

    def test_i_single_registration_is_updated_in_place(self):
        s = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo first"},
                                           {"type": "command", "command": "python3", "args": ["/old/ctx_index.py"]},
                                           {"type": "command", "command": "echo last"}]}]}}
        self.write(s)
        self.assertEqual(self.cli().returncode, 0)
        hooks = self.load()["hooks"]["Stop"][0]["hooks"]
        self.assertEqual([h["command"] for h in hooks][0::2], ["echo first", "echo last"])     # position kept
        self.assertEqual(hooks[1]["args"][:2], ["-I", "-c"])

    def test_i_uninstall_restores_the_previous_settings(self):
        self.write(USER_SETTINGS)
        self.assertEqual(self.cli().returncode, 0)
        cp = self.cli("--uninstall")
        self.assertEqual(cp.returncode, 0, cp.text)
        self.assertEqual(self.load(), USER_SETTINGS)
        self.assertEqual(len(self.backups()), 2)                                # one per change
        self.assertTrue(os.path.isfile(os.path.join(self.cfg, "hooks", "ctx_index.py")))       # the copy is left alone
        cp = self.cli("--uninstall")
        self.assertEqual(cp.returncode, 0)
        self.assertIn("등록되어 있지 않습니다", cp.text)
        self.assertEqual(len(self.backups()), 2)

    def test_i_uninstall_of_a_fresh_install_leaves_an_empty_object(self):
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(self.cli("--uninstall").returncode, 0)
        self.assertEqual(self.load(), {})

    def test_i_dry_run_writes_nothing(self):
        cp = self.cli("--dry-run")
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(self.listing(), {})
        self.write(USER_SETTINGS)
        before = self.listing()
        for args in (["--dry-run"], ["--dry-run", "--uninstall"], ["--status"]):
            self.cli(*args)
            self.assertEqual(self.listing(), before, args)
        self.assertEqual(self.cli().returncode, 0)
        before = self.listing()
        self.assertEqual(self.cli("--dry-run", "--uninstall").returncode, 0)
        self.assertEqual(self.listing(), before)

    def test_i_unreadable_settings_are_never_overwritten(self):
        bad = [b"{ not json", b'{"hooks": {"Stop": [}', b"// comment\n{}", b"[1, 2]", b'"text"', b"null", b"\xff\xfe\x00\x01",
               b'{"hooks": []}', b'{"hooks": {"Stop": {}}}', b'{"hooks": {"Stop": ["x"]}}', b'{"hooks": {"UserPromptSubmit": [{"hooks": 5}]}}']
        for raw in bad:
            self.write(None, raw=raw)
            for args in ([], ["--uninstall"], ["--status"]):
                cp = self.cli(*args)
                if not (args and raw.startswith(b'{"hooks"') and b"[}" not in raw):   # --uninstall/--status only need parseable JSON
                    self.assertEqual(cp.returncode, 1, (raw, args, cp.text))
                self.assertEqual(self.read(), raw, (raw, args))
            self.assertEqual(self.backups(), [], raw)

    def test_i_empty_settings_file_is_treated_as_empty_object(self):
        self.write(None, raw=b"")
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(list(self.load()), ["hooks"])
        self.assertEqual(len(self.backups()), 1)

    def test_i_file_style_is_kept(self):
        raw = b"\xef\xbb\xbf" + json.dumps(USER_SETTINGS, ensure_ascii=False, indent=4).replace("\n", "\r\n").encode("utf-8") + b"\r\n"
        self.write(None, raw=raw)
        self.assertEqual(self.cli().returncode, 0)
        out = self.read()
        self.assertFalse(out.startswith(b"\xef\xbb\xbf"))                       # written back without a BOM
        self.assertNotIn(b"\n", out.replace(b"\r\n", b""))                      # CRLF everywhere
        self.assertIn(b'\r\n    "model": "opus"', out)                          # 4-space indent
        self.assertEqual(without_ours(json.loads(out.decode("utf-8"))), USER_SETTINGS)
        self.write(None, raw=json.dumps(USER_SETTINGS, indent="\t").encode("utf-8"))
        self.assertEqual(self.cli().returncode, 0)
        self.assertIn(b'\n\t"model": "opus"', self.read())

    def test_i_status(self):
        cp = self.cli("--status")
        self.assertEqual(cp.returncode, 1)
        self.assertIn("등록되어 있지 않습니다", cp.text)
        self.assertEqual(self.cli().returncode, 0)
        cp = self.cli("--status")
        self.assertEqual(cp.returncode, 0, cp.text)
        for event in EVENTS:
            self.assertIn("  " + event, cp.text)
        self.assertIn("저장소의 훅과 같음", cp.text)
        os.remove(os.path.join(self.cfg, "hooks", "ctx_index.py"))
        self.assertIn("등록된 훅 파일이 없습니다", self.cli("--status").text)
        s = self.load()
        del s["hooks"]["Stop"]
        s["disableAllHooks"] = True
        self.write(s)
        cp = self.cli("--status")
        self.assertEqual(cp.returncode, 1)
        self.assertIn("등록되지 않은 이벤트: Stop", cp.text)
        self.assertIn("disableAllHooks", cp.text)

    def test_i_in_place_and_custom_hook_directory(self):
        cp = self.cli("--in-place")
        self.assertEqual(cp.returncode, 0, cp.text)
        self.assertEqual(set(h["args"][-1] for _e, _m, h in ours(self.load())), {S.HOOK})
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "hooks")))
        custom = os.path.join(self.root, "other place", "훅 모음")
        cp = self.cli("--hook-dir", custom)
        self.assertEqual(cp.returncode, 0, cp.text)
        self.assertEqual(set(h["args"][-1] for _e, _m, h in ours(self.load())), {os.path.join(custom, "ctx_index.py")})
        self.assertEqual(len(ours(self.load())), 3)

    def test_i_copy_is_refreshed_when_the_hook_changes(self):
        self.assertEqual(self.cli().returncode, 0)
        target = os.path.join(self.cfg, "hooks", "ctx_index.py")
        with open(target, "ab") as f:
            f.write(b"\n# local edit\n")
        self.assertIn("저장소의 훅과 다름", self.cli("--status").text)
        settings_before = self.read()
        cp = self.cli()
        self.assertEqual(cp.returncode, 0)
        self.assertIn("훅 파일만 갱신했습니다", cp.text)
        self.assertEqual(self.read(target), self.read(S.HOOK))
        self.assertEqual(self.read(), settings_before)
        self.assertEqual(self.backups(), [])

    def test_i_paths_with_spaces_and_hangul(self):
        cfg = os.path.join(self.root, "사용자 홍 길동", ".claude")
        os.makedirs(cfg)
        settings = os.path.join(cfg, "settings.json")
        cp = self.cli(settings=settings)
        self.assertEqual(cp.returncode, 0, cp.text)
        self.assertIn("실행 점검: 통과", cp.text)
        (h,) = [h for e, _m, h in ours(self.load(settings)) if e == "Stop"]
        self.assertEqual(h["args"][-1], os.path.join(cfg, "hooks", "ctx_index.py"))
        self.assertIn("사용자 홍 길동".encode("utf-8"), self.read(settings))

    def test_i_default_settings_path_is_under_home(self):
        self.assertEqual(inst.default_settings_path(), os.path.join(S.FAKE_HOME, ".claude", "settings.json"))
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.root, "cfg")
        try:
            self.assertEqual(inst.default_settings_path(), os.path.join(self.root, "cfg", "settings.json"))
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
        cp = subprocess.run([sys.executable, SCRIPT, "--dry-run"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(cp.returncode, 0)
        self.assertIn(os.path.join(S.FAKE_HOME, ".claude", "settings.json"), cp.stdout.decode("utf-8", "replace"))
        self.assertFalse(os.path.exists(os.path.join(S.FAKE_HOME, ".claude", "settings.json")))

    def test_i_bad_interpreter_or_hook_changes_nothing(self):
        self.write(USER_SETTINGS)
        before = self.listing()
        self.assertEqual(self.cli("--python", os.path.join(self.root, "no-such-python")).returncode, 1)
        fake = os.path.join(self.root, "notpython.txt")
        with open(fake, "wb") as f:
            f.write(b"not an interpreter")
        before[os.path.relpath(fake, self.root)] = b"not an interpreter"
        self.assertEqual(self.cli("--python", fake).returncode, 1)
        self.assertEqual(self.cli("--hook", os.path.join(self.root, "missing.py")).returncode, 1)
        self.assertEqual(self.listing(), before)

    def test_i_failed_self_test_leaves_settings_alone(self):
        self.write(USER_SETTINGS)
        broken = os.path.join(self.root, "src", "ctx_index.py")
        os.makedirs(os.path.dirname(broken))
        for body in (b"import sys\nsys.exit(3)\n", b"pass\n", b"print('noise on stdout')\n", b"this is not python\n"):
            with open(broken, "wb") as f:
                f.write(body)
            cp = self.cli("--hook", broken)
            self.assertEqual(cp.returncode, 1, cp.text)
            self.assertIn("실행 점검: 실패", cp.text)
            self.assertEqual(self.load(), USER_SETTINGS)
            self.assertEqual(self.backups(), [])
        cp = self.cli("--hook", broken, "--no-selftest")                        # explicit override
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(len(ours(self.load())), 3)


class RegisteredCommand(InstallCase):
    """What the installer wrote is started the way Claude Code 2.1.332 starts a hook."""

    def run_registered(self, form, payload, base, break_hook=False):
        cp = self.cli("--form", form)
        self.assertEqual(cp.returncode, 0, cp.text)
        (h,) = [h for e, _m, h in ours(self.load()) if e == payload["hook_event_name"]]
        if break_hook:
            os.remove(os.path.join(self.cfg, "hooks", "ctx_index.py"))
        argv = inst.command_line(h, form)
        env = dict(os.environ, CTX_INDEX_DIR=base)
        return subprocess.run(argv, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, cwd=self.root, timeout=120)

    def check_form(self, form):
        base = os.path.join(self.root, "ctx")
        cp = self.run_registered(form, S.ups("등록된 명령으로 실행 🙂", "p1"), base)
        self.assertEqual((cp.returncode, cp.stdout), (0, b""), cp.stderr)
        cp = self.run_registered(form, S.stop("등록된 명령의 답변입니다.", "p1"), base)
        self.assertEqual((cp.returncode, cp.stdout), (0, b""), cp.stderr)
        cp = self.run_registered(form, S.session_start(), base)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        text = S.context_of(cp.stdout.strip())
        self.assertIn("0001.md 0.1KB | 등록된 명령으로 실행 🙂 → 등록된 명령의 답변입니다.", text)
        with open(os.path.join(base, S.SID, "turns", "0001.md"), "rb") as f:
            self.assertIn("등록된 명령으로 실행 🙂".encode("utf-8"), f.read())
        # the hook file disappears: the prompt must not be blocked (exit status 2 would block it)
        cp = self.run_registered(form, S.ups("훅 파일이 없을 때", "p2"), base, break_hook=True)
        self.assertNotEqual(cp.returncode, 2, cp.stderr)
        self.assertNotEqual(cp.returncode, 0)
        self.assertEqual(cp.stdout.strip(), b"")
        self.assertIn(b"ctx_index.py", cp.stderr)

    def test_i_exec_form_runs_the_hook(self):
        self.check_form("exec")

    def test_i_exec_form_is_not_affected_by_files_in_the_working_directory(self):
        """-I: a json.py in the project directory must not shadow the standard library."""
        for name in ("json.py", "re.py", "hashlib.py", "datetime.py"):
            with open(os.path.join(self.root, name), "wb") as f:
                f.write(b"raise RuntimeError('shadowed standard library module')\n")
        base = os.path.join(self.root, "ctx")
        cp = self.run_registered("exec", S.ups("그늘진 모듈", "p1"), base)
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
        self.assertTrue(os.path.isfile(os.path.join(base, S.SID, "turns", "0001.md")))

    @unittest.skipUnless(inst.find_bash(), "bash (Git Bash on Windows) is not available")
    def test_i_bash_form_runs_the_hook(self):
        self.check_form("bash")

    @unittest.skipUnless(inst.find_powershell(), "PowerShell is not available")
    def test_i_powershell_form_runs_the_hook(self):
        self.check_form("powershell")

    def test_i_plain_form_would_block_prompts_when_the_file_is_missing(self):
        """Why the launcher exists: "python <missing file>" exits 2, which Claude Code reads as a block."""
        cp = subprocess.run([sys.executable, os.path.join(self.root, "missing", "ctx_index.py")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode, 2)
        cp = subprocess.run([sys.executable, "-I", "-c", inst.LAUNCHER, os.path.join(self.root, "missing", "ctx_index.py")],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode, 1)


class Entries(unittest.TestCase):
    def test_i_entry_shapes(self):
        py, hook = "/opt/py thon/bin/python3", "/home/o'brien/.claude/hooks/ctx_index.py"
        e = inst.hook_entry(py, hook, "exec", 15)
        self.assertEqual(e, {"type": "command", "command": py, "args": ["-I", "-c", inst.LAUNCHER, hook], "timeout": 15})
        b = inst.hook_entry(py, hook, "bash", 20)
        self.assertEqual((b["shell"], b["timeout"], "args" in b), ("bash", 20, False))
        self.assertTrue(b["command"].startswith("'/opt/py thon/bin/python3' -I -c '"))
        self.assertTrue(b["command"].endswith(" '/home/o'\\''brien/.claude/hooks/ctx_index.py'"))
        p = inst.hook_entry("C:\\Program Files\\Python312\\python.exe", "C:\\Users\\O'Brien\\.claude\\hooks\\ctx_index.py", "powershell", 15)
        self.assertEqual(p["shell"], "powershell")
        self.assertTrue(p["command"].startswith("& 'C:\\Program Files\\Python312\\python.exe' -I -c '"))
        self.assertTrue(p["command"].endswith(" 'C:\\Users\\O''Brien\\.claude\\hooks\\ctx_index.py'"))
        self.assertIn("open(p,''rb'')", p["command"])
        for entry in (e, b, p):
            self.assertTrue(inst.is_ours(entry))
            self.assertEqual(len(inst.hook_paths(entry)), 1)
        self.assertEqual(inst.hook_paths(e), [hook])
        self.assertEqual(inst.hook_paths(b), [hook])
        self.assertEqual(inst.hook_paths(p), ["C:\\Users\\O'Brien\\.claude\\hooks\\ctx_index.py"])
        self.assertEqual(inst.hook_paths({"command": 'python "C:\\old\\CTX_INDEX.PY"'}), ["C:\\old\\CTX_INDEX.PY"])
        with self.assertRaises(inst.InstallError):
            inst.hook_entry(py, hook, "cmd", 15)

    def test_i_launcher_has_nothing_a_windows_command_line_would_mangle(self):
        for ch in ('"', "\\", "%", "^", "&", "|", "<", ">", "!", "`", "$", "\n", "\t"):
            self.assertNotIn(ch, inst.LAUNCHER, repr(ch))
        self.assertNotIn("${", inst.LAUNCHER)                                   # the CLI substitutes ${...} in args
        compile(inst.LAUNCHER, "<launcher>", "exec")

    def test_i_bash_paths(self):
        self.assertEqual(inst.to_bash_path("C:\\Users\\me\\x.py", sep="\\"), "C:/Users/me/x.py")
        self.assertEqual(inst.to_bash_path("/home/me/odd\\name.py", sep="/"), "/home/me/odd\\name.py")

    def test_i_only_ctx_index_hooks_are_recognised(self):
        yes = [{"command": "python3", "args": ["/x/ctx_index.py"]}, {"command": "py -3 C:\\h\\CTX_INDEX.PY"},
               {"command": "/usr/bin/python3", "args": ["-I", "-c", inst.LAUNCHER, "/x/hooks/ctx_index.py"]}]
        no = [{"command": "python3 /x/notify.py"}, {"command": "python3", "args": ["/x/ctx_proto.py"]}, {"command": "echo ctx-index"},
              {"command": "python3 lab/proto/ctx_proto.py"}, {}, None, "ctx_index.py", {"command": 5, "args": "ctx_index.py"},
              {"command": "python3 /x/my_ctx_index.py"}, {"command": "python3 tests/test_ctx_index.py"},
              {"command": "python3", "args": ["tools/ctx_index_measure.py"]}, {"command": "cat /x/ctx_index.py.bak"}]
        self.assertTrue(all(inst.is_ours(h) for h in yes))
        self.assertFalse(any(inst.is_ours(h) for h in no))

    def test_i_remove_keeps_the_users_empty_lists(self):
        s = {"hooks": {"Notification": [], "Stop": [{"hooks": [{"command": "python3 /x/ctx_index.py"}]}]}, "x": 1}
        self.assertEqual(inst.remove_ours(s), 1)
        self.assertEqual(s, {"hooks": {"Notification": []}, "x": 1})
        s = {"hooks": {}, "x": 1}
        self.assertEqual(inst.remove_ours(s), 0)
        self.assertEqual(s, {"hooks": {}, "x": 1})

    def test_i_events_and_timeout(self):
        self.assertEqual(inst.EVENTS, (("UserPromptSubmit", None), ("Stop", None), ("SessionStart", "compact")))
        self.assertEqual(inst.DEFAULT_TIMEOUT, 15)
        self.assertEqual(inst.POWERSHELL_ARGS, ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
