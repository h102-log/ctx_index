#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the autocompact retention A/B eval: the real Claude Code CLI, with and without ctx-index.

    python3 lab/eval/run_eval.py --api mock --scenarios s01 --out lab/eval/.run/mock-oracle --mock-mode oracle
    python3 lab/eval/run_eval.py --api real --scenarios s01 --out lab/eval/.run/pilot --i-approve-paid-run

Per unit (one scenario x one rep):
  1. build    one session in a throwaway HOME with ctx-index installed: needle and filler turns, one at a time,
              until the context passes the autocompact threshold. The session is then "armed": its next prompt
              compacts. ctx-index writes nothing into the context before compaction, so the same history is the
              pre-compaction state of both arms - a paired design, built once.
  2. split    copy the HOME twice. Arm A ("baseline", no hook): hook registration, hook file and every ctx-index
              record removed. Arm B ("v1", ctx-index): unchanged. Both may read anything under ~/.claude.
  3. compact  in each arm resume the same session with the same neutral prompt; an automatic compaction must fire.
  4. probe    every question as its own fork of the compacted session (--resume --fork-session), graded by grade.py.

Output under --out: report/{baseline,v1}/results.jsonl + traces/ + errors.jsonl, units/<unit>/unit.json (build,
compaction and summary details), run.log. Rows are written as they complete; re-running resumes. Paid runs
(--api real) refuse to start without --i-approve-paid-run.
"""
import argparse
import concurrent.futures
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools"))
from gen_scenarios import build_all, standalone  # noqa: E402
from grade import grade  # noqa: E402
from ctx_index_measure import classify_call  # noqa: E402  (the same rule as the real-usage measurement)

RUNNER = os.path.join(HERE, "run_cli_eval.sh")
MOCK = os.path.join(HERE, "mock_eval_api.py")
INSTALL = os.path.join(REPO, "tools", "install_hook.py")
PLACEHOLDER = "sk-ant-eval-placeholder-0000000000000000"     # the mock key in run_cli_eval.sh
TOOLS = "Read,Grep,Glob"
READ_RULE = "Read(~/.claude/**)"
VARIANT = {"A": "baseline", "B": "v1"}
ARM_NAME = {"A": "훅 없음", "B": "ctx-index"}
_log_lock = threading.Lock()


class UnitError(Exception):
    def __init__(self, cls, msg):
        Exception.__init__(self, msg)
        self.cls = cls


def log(out, msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    with _log_lock:
        print(line, flush=True)
        with open(os.path.join(out, "run.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")


def jdump(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def append_jsonl(path, obj):
    with _log_lock, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def inside(root, path):
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(root) + os.sep):
        raise SystemExit("refusing to touch %s outside %s" % (real, root))
    return real


# ---------------------------------------------------------------- stream-json helpers

def parse_events(lines):
    out = []
    for line in lines:
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def summarize(evs):
    """Everything the eval needs from one CLI run's stream-json events."""
    msgs, order = {}, []
    tool_results, compacts, summary = [], [], None
    for i, e in enumerate(evs):
        t = e.get("type")
        if t == "assistant":
            m = e.get("message") or {}
            mid = m.get("id") or ("anon%d" % i)
            if mid not in msgs:
                msgs[mid] = {"model": m.get("model"), "blocks": [], "usage": {}, "stop_reason": None}
                order.append(mid)
            rec = msgs[mid]
            rec["blocks"].extend(m.get("content") or [])
            if m.get("usage"):
                rec["usage"] = m["usage"]
            if m.get("stop_reason"):
                rec["stop_reason"] = m["stop_reason"]
            rec["model"] = m.get("model") or rec["model"]
        elif t == "user":
            c = (e.get("message") or {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        body = b.get("content")
                        if isinstance(body, list):
                            body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                        tool_results.append({"is_error": bool(b.get("is_error")), "text": str(body or "")})
            if compacts and summary is None and e.get("isSynthetic"):
                summary = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))
        elif t == "system" and e.get("subtype") == "compact_boundary":
            compacts.append(e.get("compact_metadata") or {})
    result = [e for e in evs if e.get("type") == "result"]
    result = result[-1] if result else None
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "cache_creation_5m": 0, "cache_creation_1h": 0}
    tool_calls, texts, models = [], [], set()
    for mid in order:
        rec = msgs[mid]
        u = rec["usage"] or {}
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            usage[k] += int(u.get(k) or 0)
        cc = u.get("cache_creation") or {}
        usage["cache_creation_5m"] += int(cc.get("ephemeral_5m_input_tokens") or 0)
        usage["cache_creation_1h"] += int(cc.get("ephemeral_1h_input_tokens") or 0)
        if rec["model"]:
            models.add(rec["model"])
        for b in rec["blocks"]:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tool_calls.append({"name": b.get("name"), "input": b.get("input") or {}})
            elif isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                texts.append(b["text"])
    last = msgs[order[-1]] if order else None
    lu = (last or {}).get("usage") or {}
    context = sum(int(lu.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
    return {"result": result, "usage": usage, "tool_calls": tool_calls, "tool_results": tool_results, "models": sorted(models),
            "requests": len(order), "context": context, "texts": texts, "compacts": compacts, "summary": summary,
            "last_stop": (last or {}).get("stop_reason"), "session_id": (result or {}).get("session_id")}


def classify_calls(calls):
    """(turn-file, transcript, other ctx-index) references, one count per tool call at most per category."""
    turns = transcript = other = 0
    for c in calls:
        cats = classify_call(c["name"], c["input"])[0]
        turns += bool(cats["turns"])
        transcript += bool(cats["transcript"])
        other += bool(cats["ctx_other"])
    return turns, transcript, other


# ---------------------------------------------------------------- the eval

class Eval(object):
    def __init__(self, a):
        self.a = a
        self.out = os.path.abspath(a.out)
        self.scen = {s["id"]: s for s in build_all()}
        self.rng = random.Random(a.seed)
        for v in VARIANT.values():
            os.makedirs(os.path.join(self.out, "report", v, "traces"), exist_ok=True)
        os.makedirs(os.path.join(self.out, "units"), exist_ok=True)
        jdump(os.path.join(self.out, "config.json"), {k: getattr(a, k) for k in vars(a)})
        jdump(os.path.join(self.out, "report", "_state.json"), {
            "metrics": [{"id": "correct", "label": "정답", "kind": "binary"}, {"id": "abstained", "label": "모름", "kind": "binary"},
                        {"id": "wrong", "label": "오답", "kind": "binary"}],
            "perf_fields": ["latency_s", "tool_calls", "usage", "turn_file_reads", "transcript_reads"]})

    # -- processes
    def env(self, home, port=None):
        e = dict(os.environ, CTX_EVAL_HOME=home, CTX_EVAL_API=self.a.api, CLAUDE_CODE_AUTO_COMPACT_WINDOW=str(self.a.window))
        if port:
            e["MOCK_PORT"] = str(port)
        return e

    def base_args(self):
        return ["--model", self.a.model, "--tools", TOOLS, "--output-format", "stream-json", "--verbose"]

    def run_once(self, home, proj, args, port, timeout):
        t0 = time.time()
        try:
            cp = subprocess.run([RUNNER] + args + self.base_args(), cwd=proj, env=self.env(home, port),
                                capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise UnitError("timeout", "CLI run exceeded %ds" % timeout)
        evs = parse_events(cp.stdout.decode("utf-8", "replace").splitlines())
        s = summarize(evs)
        s["wall_s"] = round(time.time() - t0, 1)
        s["stderr"] = cp.stderr.decode("utf-8", "replace")[-600:]
        s["events"] = evs
        return s

    def start_mock(self, unit_dir, port, sc):
        key = os.path.join(unit_dir, "mock-key.json")          # per unit: several scenarios share question texts
        jdump(key, sc["probes"])
        env = dict(os.environ, MOCK_KEY=key, MOCK_PROBE_MODE=self.a.mock_mode, MOCK_TOKEN_SCALE=str(self.a.mock_token_scale))
        p = subprocess.Popen([sys.executable, MOCK, str(port), os.path.join(unit_dir, "mock-requests.jsonl")], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.8)
        return p

    # -- setup
    def prepare(self, unit_dir):
        proj, home = os.path.join(unit_dir, "proj"), os.path.join(unit_dir, "home_build")
        os.makedirs(proj, exist_ok=True)
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(proj, "README.md"), "w", encoding="utf-8") as f:
            f.write("# eval project\n\n이 디렉터리는 실험용 빈 프로젝트입니다.\n")
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
            subprocess.run(["git", "-C", proj, "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
                            "-c", "commit.gpgsign=false"] + args, check=True, capture_output=True)
        approved = [PLACEHOLDER[-20:]]
        if self.a.api == "real" and os.environ.get("CTX_EVAL_API_KEY"):
            approved.append(os.environ["CTX_EVAL_API_KEY"][-20:])     # what the CLI itself records for an approved key
        jdump(os.path.join(home, ".claude.json"), {"hasCompletedOnboarding": True,
                                                   "customApiKeyResponses": {"approved": approved, "rejected": []},
                                                   "projects": {proj: {"allowedTools": [], "hasTrustDialogAccepted": True}}})
        cp = subprocess.run([sys.executable, INSTALL], env=dict(os.environ, HOME=home), capture_output=True)
        if cp.returncode != 0:
            raise UnitError("setup", "install_hook failed: " + cp.stdout.decode("utf-8", "replace")[-400:])
        sp = os.path.join(home, ".claude", "settings.json")
        s = json.load(open(sp, encoding="utf-8"))
        s["permissions"] = {"allow": [READ_RULE]}                      # same in both arms
        jdump(sp, s)
        for f in os.listdir(os.path.join(home, ".claude")):
            if f.startswith("settings.json.bak"):
                os.remove(os.path.join(home, ".claude", f))
        return proj, home

    def strip_hook(self, unit_dir, home):
        cp = subprocess.run([sys.executable, INSTALL, "--uninstall"], env=dict(os.environ, HOME=home), capture_output=True)
        if cp.returncode != 0:
            raise UnitError("setup", "uninstall failed")
        d = os.path.join(home, ".claude")
        shutil.rmtree(inside(unit_dir, os.path.join(d, "ctx-index")), ignore_errors=True)
        hook = os.path.join(d, "hooks", "ctx_index.py")
        if os.path.exists(hook):
            os.remove(inside(unit_dir, hook))
        for f in os.listdir(d):
            if f.startswith("settings.json.bak"):
                os.remove(inside(unit_dir, os.path.join(d, f)))
        text = open(os.path.join(d, "settings.json"), encoding="utf-8").read()
        if "ctx_index" in text or os.path.exists(os.path.join(d, "ctx-index")):
            raise UnitError("setup", "arm A still carries ctx-index")

    # -- one CLI process, fed one prompt at a time over stream-json (the build, and each arm's way into compaction)
    class Driver(object):
        def __init__(self, ev, home, proj, port, extra, evlog_path):
            self.ev, self.seen, self.lines = ev, 0, []
            self.cv = threading.Condition()
            cmd = [RUNNER, "-p", "--input-format", "stream-json"] + extra + ev.base_args()
            self.proc = subprocess.Popen(cmd, cwd=proj, env=ev.env(home, port), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
            self.evlog = open(evlog_path, "a", encoding="utf-8")
            threading.Thread(target=self._read, daemon=True).start()
            threading.Thread(target=lambda: self.proc.stderr.read(), daemon=True).start()

        def _read(self):
            for line in self.proc.stdout:
                with self.cv:
                    self.lines.append(line.decode("utf-8", "replace"))
                    self.cv.notify_all()
            with self.cv:
                self.lines.append(None)
                self.cv.notify_all()

        def send(self, text, label, timeout):
            msg = {"type": "user", "message": {"role": "user", "content": text}}
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
            t0, got = time.time(), []
            while True:
                with self.cv:
                    while self.seen >= len(self.lines):
                        if not self.cv.wait(timeout=5) and time.time() - t0 > timeout:
                            raise UnitError("timeout", "turn %s exceeded %ds" % (label, timeout))
                    line = self.lines[self.seen]
                    self.seen += 1
                if line is None:
                    raise UnitError("serving", "CLI exited during turn %s" % label)
                got.extend(parse_events([line]))
                if got and got[-1].get("type") == "result":
                    break
            for e in got:
                if e.get("type") in ("assistant", "result", "system"):
                    self.evlog.write(json.dumps(e, ensure_ascii=False) + "\n")
            s = summarize(got)
            s["seconds"] = round(time.time() - t0, 1)
            res = s["result"] or {}
            if res.get("is_error"):
                raise UnitError("serving", "turn %s failed: %s" % (label, str(res.get("result"))[:200]))
            self.ev.check_model(s, "turn %s" % label)
            return s

        def close(self):
            self.evlog.close()
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    # -- 1. build
    def build(self, sc, unit_dir, proj, home, port, state):
        a = self.a
        needles = sorted(sc["needles"], key=lambda n: n["target_frac"])
        fillers = list(sc["fillers"])
        turns, ctx, t_start, sid = [], 0, time.time(), None
        drv = self.Driver(self, home, proj, port, [], os.path.join(unit_dir, "build-events.jsonl"))
        try:
            while ctx < a.build_stop:
                if needles and ctx >= needles[0]["target_frac"] * a.needle_scale:
                    turn = needles.pop(0)
                elif fillers:
                    turn = fillers.pop(0)
                else:
                    raise UnitError("not_armed", "ran out of filler turns at %d tokens" % ctx)
                if len(turns) >= a.max_build_turns or time.time() - t_start > a.build_timeout:
                    raise UnitError("not_armed", "build limit reached at %d tokens after %d turns" % (ctx, len(turns)))
                s = drv.send(turn["text"], turn["id"], a.turn_timeout)
                if s["compacts"]:
                    raise UnitError("early_compaction", "compaction during the build at turn %s (%d tokens before)" % (turn["id"], ctx))
                res = s["result"] or {}
                ctx = s["context"] or ctx
                sid = s["session_id"] or sid
                answer = "\n".join(s["texts"])
                turns.append({"n": len(turns) + 1, "id": turn["id"], "kind": turn.get("kind", "needle"), "context": ctx,
                              "cost_cli": res.get("total_cost_usd"), "duration_s": s["seconds"], "usage": s["usage"],
                              "chars": len(turn["text"]), "answer_chars": len(answer), "answer_head": answer[:300]})
                if turn["id"].startswith("n"):
                    state.setdefault("needle_answers", {})[turn["id"]] = answer[:4000]
                if len(turns) % 5 == 0 or turn["id"].startswith("n"):
                    log(self.out, "  %s build turn %d (%s) context=%d" % (state["unit"], len(turns), turn["id"], ctx))
        finally:
            drv.close()
        state["build"] = {"session_id": sid, "turns": turns, "n_turns": len(turns), "context": ctx,
                          "unsent_needles": [n["id"] for n in needles], "seconds": round(time.time() - t_start, 1),
                          "cost_cli": (turns[-1]["cost_cli"] or 0) if turns else 0}      # total_cost_usd is cumulative per session
        log(self.out, "  %s build stopped after %d turns at %d tokens (unsent needles: %s)" % (
            state["unit"], len(turns), ctx, ",".join(state["build"]["unsent_needles"]) or "none"))

    def check_model(self, s, where):
        bad = [m for m in s["models"] if not m.startswith(self.a.model)]
        if bad:
            raise UnitError("served_model_mismatch", "%s served by %s, asked for %s" % (where, bad, self.a.model))

    # -- 3. compact: the same tail turns, one at a time, until the CLI compacts by itself
    def compact(self, sc, unit_dir, proj, home, port, state, arm):
        sid = state["build"]["session_id"]
        drv = self.Driver(self, home, proj, port, ["--resume", sid], os.path.join(unit_dir, "arm%s-events.jsonl" % arm))
        tail, meta, s = [], None, None
        try:
            for t in sc["tail"]:
                s = drv.send(t["text"], "%s/%s" % (arm, t["id"]), self.a.turn_timeout)
                tail.append({"id": t["id"], "context": s["context"], "cost_cli": (s["result"] or {}).get("total_cost_usd"),
                             "usage": s["usage"], "reply": "\n".join(s["texts"])[:120], "compacted": bool(s["compacts"])})
                if (s["session_id"] or sid) != sid:
                    raise UnitError("setup", "arm %s: resume continued as another session" % arm)
                if s["compacts"]:
                    meta = s["compacts"][0]
                    break
        finally:
            drv.close()
        if meta is None:
            raise UnitError("not_compacted", "arm %s: no autocompact after %d tail turns (context %s)" % (arm, len(tail), tail[-1]["context"] if tail else None))
        if meta.get("trigger") != "auto":
            raise UnitError("not_compacted", "arm %s: compaction trigger was %r" % (arm, meta.get("trigger")))
        cum = tail[-1]["cost_cli"] or 0          # cumulative CLI cost of the session once compacted (probes fork from here)
        info = {"compact": meta, "tail_turns": len(tail), "tail": tail, "summary_chars": len(s["summary"] or ""),
                "summary": (s["summary"] or "")[:60000], "cum_cost_cli": cum, "cost_cli": cum - (state["build"]["cost_cli"] or 0)}
        if arm == "B":
            d = os.path.join(home, ".claude", "ctx-index", sid)
            idx, comp = os.path.join(d, "index.md"), os.path.join(d, "compactions.jsonl")
            if not os.path.isfile(idx):
                raise UnitError("no_index", "arm B: ctx-index wrote no index.md for %s" % sid)
            info["index_chars"] = len(open(idx, encoding="utf-8").read())
            info["ctx_compaction"] = json.loads(open(comp, encoding="utf-8").read().strip().splitlines()[-1])
        state.setdefault("arms", {})[arm] = info
        log(self.out, "  %s arm %s autocompacted at tail turn %d: %s -> %s tokens%s" % (
            state["unit"], arm, len(tail), meta.get("pre_tokens"), meta.get("post_tokens"),
            (", index %d chars stage %s" % (info["index_chars"], info["ctx_compaction"].get("stage"))) if arm == "B" else ""))

    # -- 4. probe
    def probe(self, sc, unit_dir, proj, home, port, state, arm, p, rep):
        sid = state["build"]["session_id"]
        variant = VARIANT[arm]
        vdir = os.path.join(self.out, "report", variant)
        pid = "%s/%s" % (sc["id"], p["id"])
        last_err = None
        for attempt in range(1, self.a.attempts + 1):
            try:
                s = self.run_once(home, proj, ["-p", p["question"], "--resume", sid, "--fork-session"], port, self.a.probe_timeout)
                res = s["result"] or {}
                if res.get("is_error") or not res:
                    raise UnitError("serving", "probe failed: %s %s" % (res.get("subtype"), str(res.get("result"))[:160]))
                self.check_model(s, "probe %s" % pid)
                answer = res.get("result") or ""
                if not answer.strip():
                    raise UnitError("empty_answer", "empty final answer")
                g = grade(p, answer)
                tf, tx, other = classify_calls(s["tool_calls"])
                row = {"prompt_id": pid, "rep": rep, "unit": state["unit"], "arm": arm, "variant": variant, "prompt": p["question"],
                       "tags": [p["kind"], p["pos"], sc["id"]], "status": "truncated" if s["last_stop"] == "max_tokens" else "ok",
                       "stop_reason": s["last_stop"], "grade": {k: g[k] for k in ("correct", "abstained", "wrong")},
                       "hedged": g["hedged"], "coverage": g["coverage"], "note": g["note"], "answer": answer[:4000],
                       "model": (s["models"] or [None])[0], "usage": s["usage"],
                       "cost_cli": (res.get("total_cost_usd") or 0) - (state["arms"][arm].get("cum_cost_cli") or 0),
                       "latency_s": round((res.get("duration_ms") or 0) / 1000.0, 2), "wall_s": s["wall_s"],
                       "requests": s["requests"], "tool_calls": len(s["tool_calls"]), "tools": [c["name"] for c in s["tool_calls"]],
                       "turn_file_reads": tf, "transcript_reads": tx, "ctx_other_reads": other,
                       "tool_errors": sum(1 for r in s["tool_results"] if r["is_error"]),
                       "permission_denials": len(res.get("permission_denials") or []), "attempt": attempt}
                trace = [{"role": "user", "content": p["question"]}]
                ti = 0
                for e in s["events"]:
                    if e.get("type") == "assistant":
                        for b in (e.get("message") or {}).get("content") or []:
                            if b.get("type") == "tool_use":
                                trace.append({"role": "tool_call", "name": b.get("name"), "content": json.dumps(b.get("input"), ensure_ascii=False, indent=2)})
                            elif b.get("type") == "text" and b.get("text"):
                                trace.append({"role": "assistant", "content": b["text"]})
                    elif e.get("type") == "user" and ti < len(s["tool_results"]):
                        c = (e.get("message") or {}).get("content")
                        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                            r = s["tool_results"][ti]
                            ti += 1
                            trace.append({"role": "tool_result", "content": r["text"][:6000] + ("\n…(%d chars)" % len(r["text"]) if len(r["text"]) > 6000 else "")})
                jdump(os.path.join(vdir, "traces", "%s__%s_rep%d.json" % (sc["id"], p["id"], rep)), trace)
                append_jsonl(os.path.join(vdir, "results.jsonl"), row)
                return row
            except UnitError as e:
                last_err = e
                append_jsonl(os.path.join(vdir, "errors.jsonl"), {"prompt_id": pid, "rep": rep, "unit": state["unit"], "arm": arm,
                                                                  "class": e.cls, "error": str(e), "attempt": attempt})
                if e.cls in ("served_model_mismatch",):
                    break
                time.sleep(min(60, 5 * attempt) * (0.5 + random.random()))
        log(self.out, "  %s arm %s probe %s gave up: %s" % (state["unit"], arm, p["id"], last_err))
        return None

    def done_keys(self, variant):
        path = os.path.join(self.out, "report", variant, "results.jsonl")
        keys = set()
        if os.path.isfile(path):
            for line in open(path, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    keys.add((r["prompt_id"], r["rep"]))
        return keys

    def unit(self, sc_id, rep, port):
        sc = self.scen[sc_id]
        name = "%s-r%d" % (sc_id, rep)
        unit_dir = os.path.join(self.out, "units", name)
        state_path = os.path.join(unit_dir, "unit.json")
        state = json.load(open(state_path, encoding="utf-8")) if os.path.isfile(state_path) else {"unit": name, "scenario": sc_id, "rep": rep}
        os.makedirs(unit_dir, exist_ok=True)
        mock = self.start_mock(unit_dir, port, sc) if self.a.api == "mock" else None
        try:
            proj = os.path.join(unit_dir, "proj")
            home_build = os.path.join(unit_dir, "home_build")
            if "build" not in state:
                for d in ("proj", "home_build", "home_A", "home_B"):
                    shutil.rmtree(inside(self.out, os.path.join(unit_dir, d)), ignore_errors=True)
                proj, home_build = self.prepare(unit_dir)
                log(self.out, "%s: build (%s)" % (name, sc["title"]))
                self.build(sc, unit_dir, proj, home_build, port, state)
                jdump(state_path, state)
            valid, invalid = [], {}
            sent = {t["id"] for t in state["build"]["turns"]}
            for p in sc["probes"]:
                if p.get("needle") and p["needle"] not in sent:
                    invalid[p["id"]] = "needle turn %s was not sent before compaction" % p["needle"]
                elif p.get("requires_answer_contains") and not standalone(state.get("needle_answers", {}).get(p["needle"], ""), p["requires_answer_contains"]):
                    invalid[p["id"]] = "the build answer of %s did not contain %s" % (p["needle"], p["requires_answer_contains"])
                else:
                    valid.append(p)
            state["invalid_probes"] = invalid
            order = ["A", "B"]
            random.Random("%s-%d" % (sc_id, rep)).shuffle(order)
            state["arm_order"] = order
            for arm in order:
                home = os.path.join(unit_dir, "home_" + arm)
                if arm not in state.get("arms", {}):
                    shutil.rmtree(inside(self.out, home), ignore_errors=True)
                    shutil.copytree(home_build, home, symlinks=True)
                    if arm == "A":
                        self.strip_hook(unit_dir, home)
                    self.compact(sc, unit_dir, proj, home, port, state, arm)
                    jdump(state_path, state)
                done = self.done_keys(VARIANT[arm])
                todo = [p for p in valid if ("%s/%s" % (sc_id, p["id"]), rep) not in done]
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.a.probe_concurrency) as ex:
                    rows = list(ex.map(lambda p: self.probe(sc, unit_dir, proj, home, port, state, arm, p, rep), todo))
                ok = [r for r in rows if r]
                log(self.out, "  %s arm %s (%s): %d probes, correct %d" % (name, arm, ARM_NAME[arm], len(ok), sum(r["grade"]["correct"] for r in ok)))
            state["finished"] = True
            jdump(state_path, state)
        except UnitError as e:
            state.setdefault("errors", []).append({"class": e.cls, "error": str(e), "t": time.time()})
            jdump(state_path, state)
            append_jsonl(os.path.join(self.out, "errors.jsonl"), {"unit": name, "class": e.cls, "error": str(e)})
            log(self.out, "%s: FAILED (%s) %s" % (name, e.cls, e))
        finally:
            if mock:
                mock.terminate()
                mock.wait()


def main():
    ap = argparse.ArgumentParser(description="Autocompact retention A/B eval of ctx-index (real Claude Code CLI).")
    ap.add_argument("--api", choices=["mock", "real"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios", default="s01,s02,s03,s04,s05,s06")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--first-rep", type=int, default=0)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--window", type=int, default=400000, help="CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    ap.add_argument("--build-stop", type=int, default=330000, help="the shared build stops once the context reaches this; "
                    "2.1.332 never compacted a 400K window below ~349,500 tokens, so the build itself cannot compact")
    ap.add_argument("--needle-scale", type=int, default=350000, help="tokens that needle positions are fractions of "
                    "(the observed autocompact point of a 400K window)")
    ap.add_argument("--probe-concurrency", type=int, default=3)
    ap.add_argument("--unit-concurrency", type=int, default=1)
    ap.add_argument("--attempts", type=int, default=2, help="attempts per probe on harness/serving errors")
    ap.add_argument("--max-build-turns", type=int, default=150)
    ap.add_argument("--build-timeout", type=int, default=4 * 3600)
    ap.add_argument("--turn-timeout", type=int, default=900)
    ap.add_argument("--probe-timeout", type=int, default=900)
    ap.add_argument("--mock-mode", default="oracle", choices=["oracle", "null", "wrong", "search"])
    ap.add_argument("--mock-token-scale", type=float, default=1.0)
    ap.add_argument("--mock-port", type=int, default=8790)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--i-approve-paid-run", action="store_true", help="required for --api real")
    a = ap.parse_args()
    if a.api == "real":
        if not (os.environ.get("CTX_EVAL_OAUTH_TOKEN") or os.environ.get("CTX_EVAL_API_KEY")):
            sys.exit("--api real needs CTX_EVAL_OAUTH_TOKEN (a subscription token from `claude setup-token`) or CTX_EVAL_API_KEY")
        if not a.i_approve_paid_run:
            sys.exit("--api real uses the subscription's limits or bills the API key; pass --i-approve-paid-run once that is approved")
    ev = Eval(a)
    units = [(s, r) for r in range(a.first_rep, a.first_rep + a.reps) for s in a.scenarios.split(",")]
    log(ev.out, "eval: %d units (%s), api=%s model=%s window=%d build stop %d" % (len(units), a.scenarios, a.api, a.model, a.window, a.build_stop))
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.unit_concurrency) as ex:
        list(ex.map(lambda iu: ev.unit(iu[1][0], iu[1][1], a.mock_port + iu[0]), enumerate(units)))
    log(ev.out, "eval finished: see %s" % os.path.join(ev.out, "report"))


if __name__ == "__main__":
    main()
