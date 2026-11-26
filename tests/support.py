# -*- coding: utf-8 -*-
"""Shared helpers for the ctx-index test suite.

Standard library only; meant to run unchanged on Windows and POSIX:

    python -m unittest discover -s tests -v

Importing this module points HOME / USERPROFILE at a throwaway directory for the whole test
process (and every child process it starts), so that no test can touch the real
~/.claude/settings.json or ~/.claude/ctx-index even by mistake.
"""
import atexit
import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HOOK = os.path.join(REPO, "hooks", "ctx_index.py")
TOOLS = os.path.join(REPO, "tools")
FIXTURES = os.path.join(HERE, "fixtures")
CAPTURES = os.path.join(FIXTURES, "captures")
LAB_CAPTURES = os.path.join(REPO, "lab", "captures", "v2")
PROTO = os.path.join(REPO, "lab", "proto", "ctx_proto.py")
CAPTURE_NAMES = ("a", "b", "c", "d", "e", "headless", "stacked")

# ---------------------------------------------------------------- safety net: fake home
FAKE_HOME = tempfile.mkdtemp(prefix="ctxidx-home-")
atexit.register(shutil.rmtree, FAKE_HOME, True)
os.environ["HOME"] = FAKE_HOME
os.environ["USERPROFILE"] = FAKE_HOME
for _k in ("HOMEDRIVE", "HOMEPATH", "CLAUDE_CONFIG_DIR", "CTX_INDEX_DIR"):
    os.environ.pop(_k, None)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ci = load_module("ctx_index_hook", HOOK)


def read_fixture(path):
    """Fixture bytes with LF line endings. The fixtures are cut at recorded byte offsets, so a
    checkout that converted them to CRLF would shift every offset; .gitattributes prevents the
    conversion and this undoes it should it happen anyway (the JSONL never holds a raw CR)."""
    with open(path, "rb") as f:
        return f.read().replace(b"\r\n", b"\n")


def read_json(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        return [json.loads(line.decode("utf-8")) for line in f.read().split(b"\n") if line.strip()]


# ---------------------------------------------------------------- sandbox
class Sandbox(object):
    """A throwaway ctx-index root. While entered, CTX_INDEX_DIR points at it."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="ctxidx-")
        self.base = os.path.join(self.root, "ctx-index")
        os.makedirs(self.base)
        self._saved = None

    def enter(self):
        self._saved = os.environ.get("CTX_INDEX_DIR")
        os.environ["CTX_INDEX_DIR"] = self.base
        return self

    def leave(self):
        """Stop pointing CTX_INDEX_DIR here; the files stay until destroy()."""
        if self._saved is None:
            os.environ.pop("CTX_INDEX_DIR", None)
        else:
            os.environ["CTX_INDEX_DIR"] = self._saved

    def destroy(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self):
        return self.enter()

    def __exit__(self, *exc):
        self.leave()
        self.destroy()
        return False

    # -- paths and stored state
    def sdir(self, sid):
        return os.path.join(self.base, sid)

    def sessions(self):
        return sorted(n for n in os.listdir(self.base) if os.path.isdir(os.path.join(self.base, n)))

    def meta(self, sid):
        return read_json(os.path.join(self.sdir(sid), "meta.json"))

    def turns(self, sid):
        return self.meta(sid)["turns"]

    def turn_bytes(self, sid, n):
        with open(os.path.join(self.sdir(sid), "turns", "%04d.md" % n), "rb") as f:
            return f.read()

    def turn_text(self, sid, n):
        return self.turn_bytes(sid, n).decode("utf-8")

    def sections(self, sid, n):
        """[(label, body bytes)] of a turn file, split by the hook's own parser."""
        return [(label, body) for label, _ts, body in ci.parse_turn_file(self.turn_bytes(sid, n))[1]]

    def turn_files(self, sid):
        d = os.path.join(self.sdir(sid), "turns")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def compactions(self, sid):
        return read_jsonl(os.path.join(self.sdir(sid), "compactions.jsonl"))

    def events(self, sid):
        return read_jsonl(os.path.join(self.sdir(sid), "events.jsonl"))

    def errors(self, sid=None):
        return read_jsonl(os.path.join(self.sdir(sid) if sid else self.base, "errors.jsonl"))

    def all_errors(self):
        out = self.errors()
        for sid in self.sessions():
            out += self.errors(sid)
        return out

    # -- feeding events
    def feed(self, payload):
        """In-process: the hook's handle(); returns the stdout text or None."""
        return ci.handle(payload)

    def run(self, data, env=None, timeout=120, base=None, args=()):
        """Separate process, exactly as the CLI starts the hook: bytes on stdin, bytes back."""
        return run_hook(data, base or self.base, env=env, timeout=timeout, args=args)


def run_hook(data, base, env=None, timeout=120, args=(), hook=HOOK):
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False).encode("utf-8")
    elif isinstance(data, str):
        data = data.encode("utf-8")
    e = dict(os.environ)
    e["CTX_INDEX_DIR"] = base
    e.update(env or {})
    return subprocess.run([sys.executable] + list(args) + [hook], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=e, timeout=timeout)


def context_of(out):
    """additionalContext from the hook's stdout (str or bytes)."""
    if isinstance(out, bytes):
        out = out.decode("ascii")          # the hook prints ASCII-escaped JSON only
    obj = json.loads(out)
    hso = obj["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart", hso
    assert sorted(obj.keys()) == ["hookSpecificOutput"] and sorted(hso.keys()) == ["additionalContext", "hookEventName"]
    return hso["additionalContext"]


class HookCase(unittest.TestCase):
    """TestCase with a fresh sandbox per test."""

    maxDiff = None

    def setUp(self):
        self.sb = Sandbox()
        self.sb.__enter__()
        self.addCleanup(self.sb.__exit__, None, None, None)


# ---------------------------------------------------------------- payload builders
SID = "11111111-2222-3333-4444-555555555555"
NOTHING = object()      # pass key=NOTHING to a builder to leave that key out of the payload


def ups(prompt, pid="p1", sid=SID, **kw):
    p = {"session_id": sid, "transcript_path": "", "cwd": "/work/proj", "prompt_id": pid, "permission_mode": "default",
         "hook_event_name": "UserPromptSubmit", "prompt": prompt}
    p.update(kw)
    return {k: v for k, v in p.items() if v is not NOTHING}


def stop(answer=None, pid="p1", sid=SID, **kw):
    p = {"session_id": sid, "transcript_path": "", "cwd": "/work/proj", "prompt_id": pid, "permission_mode": "default",
         "effort": {"level": "medium"}, "hook_event_name": "Stop", "stop_hook_active": False,
         "background_tasks": [], "session_crons": []}
    if answer is not None:
        p["last_assistant_message"] = answer
    p.update(kw)
    return {k: v for k, v in p.items() if v is not NOTHING}


def session_start(source="compact", pid=None, sid=SID, **kw):
    p = {"session_id": sid, "transcript_path": "", "cwd": "/work/proj", "hook_event_name": "SessionStart", "source": source}
    if pid is not None:
        p["prompt_id"] = pid
    p.update(kw)
    return {k: v for k, v in p.items() if v is not NOTHING}


# ---------------------------------------------------------------- synthetic transcripts
def tx_user(text, pid, **kw):
    e = {"parentUuid": None, "isSidechain": False, "promptId": pid, "type": "user",
         "message": {"role": "user", "content": text}, "promptSource": "typed"}
    e.update(kw)
    return e


def tx_assistant(text, mid="msg_1", **kw):
    blocks = text if isinstance(text, list) else [{"type": "text", "text": text}]
    e = {"parentUuid": "x", "isSidechain": False, "type": "assistant",
         "message": {"id": mid, "type": "message", "role": "assistant", "model": "claude-test", "content": blocks}}
    e.update(kw)
    return e


def write_transcript(path, entries):
    """Write entries the way the CLI does: one compact JSON object per line, UTF-8, LF."""
    with open(path, "wb") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    return path


# ---------------------------------------------------------------- replay of captured payloads
class Replay(object):
    """Real hook payloads captured from Claude Code 2.1.332 (tests/fixtures/captures) fed to the
    hook. As in lab/proto/sim_replay.py, every event sees a copy of the transcript cut to the
    size it had when that hook ran (tx_size), so the hook reads what it would have read live."""

    def __init__(self, name, via="handle", captures=CAPTURES):
        self.name = name
        self.sb = Sandbox()
        self.txdir = tempfile.mkdtemp(prefix="ctxidx-tx-")
        self.rows = [json.loads(line.decode("utf-8"))
                     for line in read_fixture(os.path.join(captures, name, "payloads.jsonl")).split(b"\n") if line.strip()]
        self.outs = []          # (session id, additionalContext) per injection, in order
        self.procs = []         # (event name, returncode, stdout bytes, stderr bytes) when via == "process"
        self.sb.enter()
        try:
            for r in self.rows:
                p = dict(r["payload"])
                ev = p.get("hook_event_name")
                assert ev in ("UserPromptSubmit", "Stop", "SessionStart"), ev
                name_ = os.path.basename(p.get("transcript_path") or "")
                copy = os.path.join(self.txdir, name_ or "none.jsonl")
                if r.get("tx_size") is None:
                    if os.path.exists(copy):
                        os.remove(copy)
                else:
                    with open(copy, "wb") as dst:
                        dst.write(read_fixture(os.path.join(captures, "transcripts", name_))[:r["tx_size"]])
                p["transcript_path"] = copy
                if via == "handle":
                    out = self.sb.feed(p)
                else:
                    cp = self.sb.run(p)
                    self.procs.append((ev, cp.returncode, cp.stdout, cp.stderr))
                    out = cp.stdout.decode("ascii") if cp.stdout else None
                if ev != "SessionStart":
                    assert not out, "principle 2 violated: output outside compaction (%s)" % ev
                if out:
                    self.outs.append((p["session_id"], context_of(out)))
            self.sessions = {}
            for sid in self.sb.sessions():
                self.sessions[sid] = {"meta": self.sb.meta(sid), "comp": self.sb.compactions(sid),
                                      "errs": self.sb.errors(sid), "events": self.sb.events(sid),
                                      "dir": self.sb.sdir(sid)}
            self.root_errors = self.sb.errors()
        finally:
            self.sb.leave()             # the files stay readable until close()

    def session_with(self, needle):
        for sid, r in self.sessions.items():
            if any(needle in (t.get("req") or "") for t in r["meta"]["turns"]):
                return sid, r
        raise KeyError(needle)

    def turn_file(self, r, n):
        with open(os.path.join(r["dir"], "turns", "%04d.md" % n), "rb") as f:
            return f.read().decode("utf-8")

    def close(self):
        shutil.rmtree(self.txdir, ignore_errors=True)
        self.sb.destroy()


# ---------------------------------------------------------------- synthetic long sessions
# Same generator as lab/proto/sim_fold.py, so the numbers stay comparable with the lab report.
WIN_DIR = r"C:\Users\honggildong\.claude\ctx-index\3f2c9a54-7b1e-4c0d-9a6f-5e8d2b1c4a70\turns"

REQ_BIG = [
    "[목표] 결제 모듈의 재시도 로직을 분석하고, 타임아웃이 중복 결제로 이어지는 경로가 있는지 확인해줘. 관련 파일은 payments/retry.py 와 gateway/client.py 야.",
    "auth 미들웨어에서 세션 토큰 갱신이 간헐적으로 실패하는 원인을 찾아줘. 로그는 logs/auth-2026-11-20.log 에 있고 재현 스크립트는 scripts/repro_refresh.sh 야.",
    "지금까지 분석한 내용을 바탕으로 마이그레이션 계획을 단계별로 정리해줘. 다운타임 없이 진행해야 하고 롤백 절차도 반드시 포함해야 해.",
    "CI에서 test_order_pipeline 이 20% 확률로 실패해. flaky 원인을 좁혀보고 고칠 수 있으면 고쳐줘. 관련 PR은 #482 이고 실패 로그를 첨부했어.",
    "Please review the caching layer in services/cache/redis_store.py and tell me whether the invalidation logic can race with the write-through path under load.",
]
REQ_SMALL = ["응 진행해", "좋아 그대로 해줘", "ㅇㅇ", "테스트도 돌려줘", "커밋해줘", "ok go ahead", "다음", "계속", "그 방향으로 가자"]
ANS_BIG = [
    "안녕하세요!\n\n## 분석 결과\n\n재시도 로직은 gateway 타임아웃(30초)과 클라이언트 타임아웃(10초)의 불일치 때문에 동일 주문에 대해 최대 3회까지 결제 요청을 중복 전송할 수 있습니다. idempotency key가 재시도마다 새로 생성되는 것이 핵심 원인입니다.\n\n" + "세부 근거 문단입니다. " * 400,
    "## 원인\n\n토큰 갱신 실패는 refresh 엔드포인트의 락 범위가 사용자 단위가 아니라 세션 단위여서, 같은 사용자의 탭 두 개가 동시에 갱신을 시도할 때 한쪽이 이미 폐기된 토큰으로 요청하게 되는 경쟁 상태입니다.\n\n" + "재현 로그와 코드 인용입니다. " * 250,
    "네, 정리했습니다.\n\n1. 스키마 이중 기록(dual-write) 단계를 먼저 두고 2. 백필 3. 읽기 전환 4. 구 스키마 제거 순서로 진행하며 각 단계는 기능 플래그로 즉시 롤백할 수 있습니다.\n\n" + "단계별 상세입니다. " * 300,
    "The flake comes from a shared temp directory: two test workers write order fixtures to the same path, so the pipeline occasionally reads the other worker's fixture. Isolating tmp_path per worker fixes it.\n\n" + "Details and diff follow. " * 200,
]
ANS_SMALL = ["네, 진행했습니다.", "완료했습니다. 테스트 42개 모두 통과합니다.", "커밋했습니다 (a1b2c3d).", "Done.", "네 계속하겠습니다."]


def make_turns(n, seed=1, small_ratio=0.3, start=1, hook=None):
    hook = hook or ci
    rnd = random.Random(seed)
    turns = []
    for i in range(start, start + n):
        if rnd.random() < small_ratio:
            req, ans = rnd.choice(REQ_SMALL), rnd.choice(ANS_SMALL)
        else:
            req = rnd.choice(REQ_BIG) + " (작업 #%d)" % i
            ans = rnd.choice(ANS_BIG)
        turns.append({"n": i, "pid": "p%d" % i, "status": "done", "req": hook.request_preview(req),
                      "ans": hook.answer_preview(ans), "nreq": 1, "nans": 1,
                      "bytes": len(req.encode("utf-8")) + len(ans.encode("utf-8")), "kind": "user"})
    return turns


# The pinned numbers in the fold tests were computed for exactly these synthetic sessions.
# random.Random.choice() is not guaranteed to be stable across Python versions; if this
# fingerprint ever differs, the pinned-number tests skip themselves (invariants still run).
GENERATOR_FINGERPRINT = "75f5eec7149d46b13f104cad0aeeee3408a00886"


def generator_fingerprint():
    data = json.dumps(make_turns(60, seed=1), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(data).hexdigest()


def body_lines(text):
    return text.split("\n")[3:]


def full_lines(text):
    return [line for line in body_lines(text) if " | " in line]


def fold_lines(text):
    return [line for line in body_lines(text) if "접힘)" in line]
