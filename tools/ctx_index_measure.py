#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctx-index usage measurement - how often the model went back to the stored turns.

    python tools/ctx_index_measure.py                 everything under ~/.claude
    python tools/ctx_index_measure.py --days 14       tool calls of the last 14 days only
    python tools/ctx_index_measure.py --json          machine-readable
    python tools/ctx_index_measure.py --out report.txt   write the report as UTF-8 (use this on Windows
                                                          instead of redirecting with ">")

What is counted. Every tool call (a `tool_use` block of an assistant entry) in the session
transcripts under ~/.claude/projects is examined: Read, Grep, Glob, Bash, PowerShell, Agent,
MCP tools - any tool. All string values of the call's input are searched, with "/" and "\\"
both accepted as path separators (also doubled, as in shell-escaped Windows paths). One tool
call counts once per category, however many paths it names:

  turns        the input names a path under a `ctx-index` directory and a `turns` path
               segment, e.g. Read ...\\ctx-index\\<session>\\turns\\0003.md, Grep with
               path=.../ctx-index/<session> and glob=turns/*.md, or a shell command doing
               `cd .../ctx-index/<session> && cat turns/0003.md`
  transcript   the input names `.claude/projects` and a `.jsonl` file, e.g. grep ... over
               ~/.claude/projects/<project>/*.jsonl (raw transcripts, the expensive way)
  ctx_other    a `ctx-index` path without `turns` (meta.json, index.md, ...); informational

Tool results, prompts and the injected index itself are not tool calls and are not counted.

Subagent transcripts (<session>/subagents/agent-*.jsonl, and entries marked isSidechain) are
counted too, in a column of their own and attributed to the parent session: the main model
may delegate the lookup, and that is still a use of the index. --no-subagents leaves them out.
A tool call that appears in several files (a forked session copies its history) is counted
once, by its tool_use id.

For file-writing tools (Write, Edit, MultiEdit, NotebookEdit) a path that appears only in
the text being written is reported as "<tool>(text)": that is editing a document which
mentions the path, not a lookup. A write whose target is under ctx-index is listed as a
warning, because the model is never supposed to write there.

The second half of the report comes from the hook's own files under ~/.claude/ctx-index:
turns, compactions, injections, fold stages, errors, and the hook's processing time.

Standard library only; read-only (it never modifies transcripts or the index).
"""
import argparse
import datetime
import json
import os
import re
import sys

# ----------------------------------------------------------------------------- matching
_CTX = re.compile(r"[\\/]ctx-index(?![\w.-])|(?<![\w.-])ctx-index[\\/]", re.I)
_TURNS = re.compile(r"(?<![\w.-])turns[\\/]|[\\/]turns(?![\w-])", re.I)
_TURN_FILE = re.compile(r"(?:^|[\\/\s\"'`=(,;:])(\d{4,})\.md(?![\w-])")
_PROJECTS = re.compile(r"\.claude[\\/]+projects(?![\w-])", re.I)
_JSONL = re.compile(r"\.jsonl(?!\w)", re.I)
_SUBAGENT_FILE = re.compile(r"[\\/]([^\\/]+)[\\/]subagents[\\/][^\\/]+\.jsonl$", re.I)

WRITE_TOOLS = {"Write": ("file_path",), "Edit": ("file_path",), "MultiEdit": ("file_path",),
               "NotebookEdit": ("notebook_path",)}
CATEGORIES = ("turns", "transcript", "ctx_other")


def strings_of(value, out=None, depth=0):
    """Every string inside a tool input (nested dicts and lists included)."""
    if out is None:
        out = []
    if isinstance(value, str):
        out.append(value)
    elif depth < 12:
        if isinstance(value, dict):
            for v in value.values():
                strings_of(v, out, depth + 1)
        elif isinstance(value, (list, tuple)):
            for v in value:
                strings_of(v, out, depth + 1)
    return out


def classify_text(text):
    """Which categories one tool call's input text falls into."""
    has_ctx = bool(_CTX.search(text))
    turns = has_ctx and bool(_TURNS.search(text))
    return {"turns": turns,
            "transcript": bool(_PROJECTS.search(text)) and bool(_JSONL.search(text)),
            "ctx_other": has_ctx and not turns}


def classify_call(name, tool_input):
    """(categories, label, turn files named, write-target-under-ctx-index?) for one tool call."""
    text = "\n".join(strings_of(tool_input))
    cats = classify_text(text)
    label = name
    writes_there = False
    if name in WRITE_TOOLS and isinstance(tool_input, dict):
        target = "\n".join(str(tool_input.get(k) or "") for k in WRITE_TOOLS[name])
        by_target = classify_text(target)
        if by_target["turns"] or by_target["ctx_other"]:
            writes_there = True
        elif cats["turns"] or cats["ctx_other"] or cats["transcript"]:
            if not by_target["transcript"]:
                label = name + "(text)"
    files = sorted(set(_TURN_FILE.findall(text))) if cats["turns"] else []
    return cats, label, files, writes_there


# ----------------------------------------------------------------------------- transcripts
def parse_time(value):
    """Aware datetime from an ISO-8601 string (as in transcripts and in the hook's files), or None."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    v = value.strip()
    if v.endswith("Z") or v.endswith("z"):
        v = v[:-1] + "+00:00"
    m = re.match(r"^(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:?\d\d)?$", v)
    try:
        if m:
            frac = (m.group(2) or "")[:7]
            tz = m.group(3) or ""
            if tz and ":" not in tz:
                tz = tz[:3] + ":" + tz[3:]
            dt = datetime.datetime.fromisoformat(m.group(1).replace(" ", "T") + frac + tz)
        else:
            dt = datetime.datetime.fromisoformat(v[:10])
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def find_transcripts(paths, subagents=True):
    """[(file, parent session id or None)] - main transcripts first, each group oldest first."""
    main, sub = [], []
    for root in paths:
        if os.path.isfile(root):
            candidates = [root]
        else:
            candidates = []
            for d, _dirs, files in os.walk(root):
                candidates += [os.path.join(d, n) for n in files if n.lower().endswith(".jsonl")]
        for f in candidates:
            m = _SUBAGENT_FILE.search(f)
            if m:
                if subagents:
                    sub.append((f, m.group(1)))
            else:
                main.append((f, None))

    def mtime(item):
        try:
            return os.path.getmtime(item[0])
        except OSError:
            return 0
    return sorted(main, key=mtime) + sorted(sub, key=mtime)


def new_session(sid):
    return {"session": sid, "tool_calls": {"main": 0, "sub": 0}, "compact_boundaries": 0,
            "calls": dict((c, {"main": 0, "sub": 0}) for c in CATEGORIES), "turn_files": {}, "first": None, "last": None}


def scan_transcripts(files, since=None, until=None, subagents=True, only_session=None):
    """Count tool-call references in the given transcript files."""
    res = {"files": {"main": 0, "sub": 0}, "bad_lines": 0, "duplicates": 0, "unreadable": [],
           "sessions": {}, "by_tool": {}, "writes": [], "with_transcript": set()}
    seen = set()
    for path, parent in files:
        is_sub_file = parent is not None
        base_sid = parent or os.path.splitext(os.path.basename(path))[0]
        try:
            fh = open(path, "rb")
        except OSError as e:
            res["unreadable"].append("%s: %s" % (path, e))
            continue
        res["files"]["sub" if is_sub_file else "main"] += 1
        if not is_sub_file:
            res["with_transcript"].add(base_sid)         # a transcript exists, even if nothing in it is counted
        with fh:
            for line in fh:
                if b'"tool_use"' not in line and b'"compact_boundary"' not in line:
                    continue
                try:
                    e = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    res["bad_lines"] += 1
                    continue
                if not isinstance(e, dict):
                    continue
                kind = e.get("type")
                if kind not in ("assistant", "system"):
                    continue
                when = parse_time(e.get("timestamp"))
                sid = parent or (e.get("sessionId") if isinstance(e.get("sessionId"), str) and e.get("sessionId") else base_sid)
                wanted = not (when is not None and ((since and when < since) or (until and when >= until))) \
                    and not (only_session and sid != only_session)
                if kind == "system":
                    if wanted and e.get("subtype") == "compact_boundary" and not is_sub_file:
                        res["sessions"].setdefault(sid, new_session(sid))["compact_boundaries"] += 1
                    continue
                msg = e.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                side = "sub" if (is_sub_file or e.get("isSidechain")) else "main"
                if side == "sub" and not subagents:
                    wanted = False
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use" or not isinstance(b.get("name"), str) or not b["name"]:
                        continue
                    tid = b.get("id")
                    if isinstance(tid, str) and tid:
                        # A call is counted where it first appears, whatever the filters: a fork's copy of
                        # an older call must not turn into a new call of the fork.
                        if tid in seen:
                            if wanted:
                                res["duplicates"] += 1
                            continue
                        seen.add(tid)
                    if not wanted:
                        continue
                    s = res["sessions"].setdefault(sid, new_session(sid))
                    s["tool_calls"][side] += 1
                    if when is not None:
                        stamp = when.isoformat()
                        s["first"] = stamp if s["first"] is None or stamp < s["first"] else s["first"]
                        s["last"] = stamp if s["last"] is None or stamp > s["last"] else s["last"]
                    name = b["name"]
                    cats, label, turn_files, writes_there = classify_call(name, b.get("input"))
                    if writes_there:
                        res["writes"].append({"session": sid, "tool": name, "side": side,
                                              "target": str((b.get("input") or {}).get(WRITE_TOOLS[name][0]))[:300]})
                    for c in CATEGORIES:
                        if cats[c]:
                            s["calls"][c][side] += 1
                            t = res["by_tool"].setdefault(label, dict((x, {"main": 0, "sub": 0}) for x in CATEGORIES))
                            t[c][side] += 1
                    for name_ in turn_files:
                        s["turn_files"][name_] = s["turn_files"].get(name_, 0) + 1
    return res


# ----------------------------------------------------------------------------- the hook's own records
def read_jsonl(path):
    out, bad = [], 0
    try:
        with open(path, "rb") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    o = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    bad += 1
                    continue
                if isinstance(o, dict):
                    out.append(o)
                else:
                    bad += 1
    except OSError:
        pass
    return out, bad


def in_range(rec, since, until):
    when = parse_time(rec.get("ts"))
    return when is None or not ((since and when < since) or (until and when >= until))


def percentile(sorted_values, q):
    if not sorted_values:
        return None
    i = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[i]


def scan_ctx_dir(ctx_dir, since=None, until=None, only_session=None):
    """What the hook recorded: turns, compactions, injections, fold stages, errors, timings."""
    res = {"dir": ctx_dir, "exists": os.path.isdir(ctx_dir), "sessions": {}, "root_errors": 0, "error_where": {},
           "bad_lines": 0, "ms": []}
    if not res["exists"]:
        return res
    root_errors, bad = read_jsonl(os.path.join(ctx_dir, "errors.jsonl"))
    root_errors = [e for e in root_errors if in_range(e, since, until)
                   and (not only_session or e.get("session") == only_session)]
    res["root_errors"] = len(root_errors)
    res["bad_lines"] += bad
    for e in root_errors:
        w = str(e.get("where"))
        res["error_where"][w] = res["error_where"].get(w, 0) + 1
    try:
        names = sorted(os.listdir(ctx_dir))
    except OSError:
        names = []
    for name in names:
        d = os.path.join(ctx_dir, name)
        if not os.path.isdir(d) or (only_session and name != only_session):
            continue
        s = {"session": name, "turns": 0, "turn_files": 0, "bytes": 0, "kinds": {}, "unanswered": 0,
             "compactions": 0, "injections": 0, "stages": {}, "folded": 0, "max_chars": 0, "max_utf16": 0,
             "errors": 0, "events": {}, "actions": {}, "agent_inputs": 0, "answer_src": {}, "hook": None}
        try:
            s["turn_files"] = len([n for n in os.listdir(os.path.join(d, "turns")) if re.match(r"^\d{4,}\.md$", n)])
        except OSError:
            pass
        try:
            with open(os.path.join(d, "meta.json"), "rb") as f:
                meta = json.loads(f.read().decode("utf-8", "replace"))
            turns = meta.get("turns") if isinstance(meta, dict) else None
            for t in turns if isinstance(turns, list) else []:
                if not isinstance(t, dict):
                    continue
                s["turns"] += 1
                s["bytes"] += t.get("bytes") if isinstance(t.get("bytes"), int) else 0
                k = str(t.get("kind") or "?")
                s["kinds"][k] = s["kinds"].get(k, 0) + 1
                if not t.get("nans"):
                    s["unanswered"] += 1
            if isinstance(meta, dict) and isinstance(meta.get("hook"), dict):
                s["hook"] = meta["hook"]
        except (OSError, ValueError):
            pass
        comps, bad = read_jsonl(os.path.join(d, "compactions.jsonl"))
        res["bad_lines"] += bad
        for c in comps:
            if not in_range(c, since, until):
                continue
            s["compactions"] += 1
            chars = c.get("chars") if isinstance(c.get("chars"), int) else 0
            if chars > 0:
                s["injections"] += 1
            st = str(c.get("stage"))
            s["stages"][st] = s["stages"].get(st, 0) + 1
            s["folded"] += c.get("folded") if isinstance(c.get("folded"), int) else 0
            s["max_chars"] = max(s["max_chars"], chars)
            s["max_utf16"] = max(s["max_utf16"], c.get("utf16") if isinstance(c.get("utf16"), int) else chars)
        errs, bad = read_jsonl(os.path.join(d, "errors.jsonl"))
        res["bad_lines"] += bad
        for e in errs:
            if not in_range(e, since, until):
                continue
            s["errors"] += 1
            w = str(e.get("where"))
            res["error_where"][w] = res["error_where"].get(w, 0) + 1
        events, bad = read_jsonl(os.path.join(d, "events.jsonl"))
        res["bad_lines"] += bad
        for e in events:
            if not in_range(e, since, until):
                continue
            ev, act = str(e.get("ev")), str(e.get("act"))
            s["events"][ev] = s["events"].get(ev, 0) + 1
            s["actions"][act] = s["actions"].get(act, 0) + 1
            if e.get("agent"):
                s["agent_inputs"] += 1
            if ev == "Stop" and e.get("src"):
                s["answer_src"][str(e["src"])] = s["answer_src"].get(str(e["src"]), 0) + 1
            if isinstance(e.get("ms"), (int, float)) and not isinstance(e.get("ms"), bool):
                res["ms"].append(float(e["ms"]))
        res["sessions"][name] = s
    res["ms"].sort()
    return res


# ----------------------------------------------------------------------------- report
def add(a, b):
    for k, v in b.items():
        a[k] = a.get(k, 0) + v
    return a


def build_report(tx, ctx, meta):
    """Plain dict with everything; --json prints it, the text report is rendered from it."""
    totals = dict((c, {"main": 0, "sub": 0}) for c in CATEGORIES)
    tool_calls = {"main": 0, "sub": 0}
    for s in tx["sessions"].values():
        for c in CATEGORIES:
            for side in ("main", "sub"):
                totals[c][side] += s["calls"][c][side]
        for side in ("main", "sub"):
            tool_calls[side] += s["tool_calls"][side]
    sessions = []
    for sid in sorted(set(tx["sessions"]) | set(ctx["sessions"])):
        t, h = tx["sessions"].get(sid), ctx["sessions"].get(sid)
        row = {"session": sid, "in_transcripts": t is not None or sid in tx["with_transcript"], "in_ctx_index": h is not None}
        row["tool_calls"] = sum(t["tool_calls"].values()) if t else 0
        for c in CATEGORIES:
            row["ref_" + c] = sum(t["calls"][c].values()) if t else 0
        row["turn_files_named"] = len(t["turn_files"]) if t else 0
        row["compact_boundaries"] = t["compact_boundaries"] if t else 0
        for k in ("turns", "compactions", "injections", "errors"):
            row[k] = h[k] if h else 0
        row["first"], row["last"] = (t["first"], t["last"]) if t else (None, None)
        sessions.append(row)
    stages, kinds, events, actions, answer_src = {}, {}, {}, {}, {}
    hook_versions = {}
    agg = {"sessions": len(ctx["sessions"]), "turns": 0, "turn_files": 0, "bytes": 0, "unanswered": 0, "compactions": 0,
           "injections": 0, "folded": 0, "max_chars": 0, "max_utf16": 0, "errors": ctx["root_errors"], "agent_inputs": 0}
    for s in ctx["sessions"].values():
        for k in ("turns", "turn_files", "bytes", "unanswered", "compactions", "injections", "folded", "errors", "agent_inputs"):
            agg[k] += s[k]
        agg["max_chars"] = max(agg["max_chars"], s["max_chars"])
        agg["max_utf16"] = max(agg["max_utf16"], s["max_utf16"])
        add(stages, s["stages"])
        add(kinds, s["kinds"])
        add(events, s["events"])
        add(actions, s["actions"])
        add(answer_src, s["answer_src"])
        if s["hook"]:
            key = "%s / Python %s / %s" % (s["hook"].get("version"), s["hook"].get("python"), s["hook"].get("platform"))
            hook_versions[key] = hook_versions.get(key, 0) + 1
    ms = ctx["ms"]
    injected = [r for r in sessions if r["injections"] > 0]
    return {
        "meta": meta,
        "transcripts": {"files": tx["files"], "bad_lines": tx["bad_lines"], "duplicates": tx["duplicates"],
                        "unreadable": tx["unreadable"], "sessions": len(tx["sessions"]), "tool_calls": tool_calls},
        "references": totals,
        "by_tool": tx["by_tool"],
        "writes_under_ctx_index": tx["writes"],
        "sessions": sessions,
        "sessions_with_injection": len(injected),
        "sessions_with_injection_and_turns_reference": len([r for r in injected if r["ref_turns"] > 0]),
        "hook": dict(agg, exists=ctx["exists"], dir=ctx["dir"], stages=stages, kinds=kinds, events=events, actions=actions,
                     answer_src=answer_src, error_where=ctx["error_where"], bad_lines=ctx["bad_lines"], versions=hook_versions,
                     ms={"n": len(ms), "median": percentile(ms, 0.5), "p95": percentile(ms, 0.95), "max": ms[-1] if ms else None}),
    }


def fmt_bytes(n):
    return "%.1fMB" % (n / 1048576.0) if n >= 1048576 else "%.1fKB" % (n / 1024.0)


def fmt_counts(d):
    return ", ".join("%s %d" % (k, v) for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))) or "없음"


def table(rows, right=()):
    widths = [max(display_width(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    out = []
    for r in rows:
        cells = []
        for i, cell in enumerate(r):
            pad = " " * (widths[i] - display_width(str(cell)))
            cells.append(pad + str(cell) if i in right else str(cell) + pad)
        out.append("  " + "  ".join(cells).rstrip())
    return out


def display_width(s):
    """Column width in a terminal: Hangul and other wide characters take two cells."""
    w = 0
    for ch in s:
        o = ord(ch)
        w += 2 if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
                   or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFF60 or 0xFFE0 <= o <= 0xFFE6) else 1
    return w


def render_text(rep):
    m, tr, ref, hook = rep["meta"], rep["transcripts"], rep["references"], rep["hook"]
    L = ["ctx-index 실사용 측정", ""]
    L.append("대상: 트랜스크립트 %s" % ", ".join(m["projects"]))
    L.append("      훅 기록 %s%s" % (hook["dir"], "" if hook["exists"] else " (없음)"))
    L.append("기간: %s ~ %s" % (m["since"] or "처음", m["until"] or "지금"))
    L.append("읽은 파일: 메인 트랜스크립트 %d개, 서브에이전트 트랜스크립트 %d개%s · 세션 %d개"
             % (tr["files"]["main"], tr["files"]["sub"], "" if m["subagents"] else " (제외함)", tr["sessions"]))
    L += ["", "[1] 도구 호출의 참조 횟수 (도구 호출 1건을 1회로 셈)"]
    rows = [("", "메인", "서브에이전트", "합계")]
    for label, key in (("턴 파일 (ctx-index/…/turns/)", "turns"), ("트랜스크립트 (.claude/projects/….jsonl)", "transcript"),
                       ("ctx-index 기타 (meta.json 등)", "ctx_other")):
        rows.append((label, ref[key]["main"], ref[key]["sub"], ref[key]["main"] + ref[key]["sub"]))
    rows.append(("전체 도구 호출", tr["tool_calls"]["main"], tr["tool_calls"]["sub"], sum(tr["tool_calls"].values())))
    L += table(rows, right=(1, 2, 3))
    L.append("  주입이 있었던 세션 %d개 중 턴 파일을 참조한 세션: %d개"
             % (rep["sessions_with_injection"], rep["sessions_with_injection_and_turns_reference"]))
    L += ["", "[2] 도구별 참조 횟수 (메인 + 서브에이전트)"]
    if rep["by_tool"]:
        rows = [("도구", "턴 파일", "트랜스크립트", "ctx-index 기타")]
        order = sorted(rep["by_tool"].items(), key=lambda kv: (-sum(sum(v.values()) for v in kv[1].values()), kv[0]))
        for name, t in order:
            rows.append((name,) + tuple(t[c]["main"] + t[c]["sub"] for c in CATEGORIES))
        L += table(rows, right=(1, 2, 3))
        if any(name.endswith("(text)") for name in rep["by_tool"]):
            L.append("  (text): 쓰기 도구가 기록하는 본문에만 경로가 나온 호출입니다(문서 편집 등). 조회가 아닙니다.")
    else:
        L.append("  참조한 도구 호출이 없습니다.")
    L += ["", "[3] 세션별"]
    shown = [r for r in rep["sessions"] if r["ref_turns"] or r["ref_transcript"] or r["ref_ctx_other"] or r["in_ctx_index"]]
    if shown:
        rows = [("세션", "턴", "압축(훅)", "압축(CLI)", "주입", "턴 파일 참조", "참조한 턴 파일", "트랜스크립트 참조", "오류")]
        for r in shown:
            rows.append((r["session"][:36], r["turns"] if r["in_ctx_index"] else "-", r["compactions"] if r["in_ctx_index"] else "-",
                         r["compact_boundaries"] if r["in_transcripts"] else "-", r["injections"] if r["in_ctx_index"] else "-",
                         r["ref_turns"], r["turn_files_named"], r["ref_transcript"], r["errors"]))
        L += table(rows, right=(1, 2, 3, 4, 5, 6, 7, 8))
        L.append("  압축(훅)은 훅이 기록한 압축 수, 압축(CLI)은 트랜스크립트의 압축 경계 수입니다. 둘이 다르면 훅이 압축을 놓친 것입니다.")
    else:
        L.append("  해당하는 세션이 없습니다.")
    L += ["", "[4] 훅 기록 (%s)" % hook["dir"]]
    if not hook["exists"]:
        L.append("  디렉터리가 없습니다. 훅이 등록되어 실행된 적이 있는지 확인하세요.")
    else:
        L.append("  세션 %d개 · 턴 %d개(파일 %d개) · 저장 원문 %s · 답변 없는 턴 %d개"
                 % (hook["sessions"], hook["turns"], hook["turn_files"], fmt_bytes(hook["bytes"]), hook["unanswered"]))
        L.append("  턴 종류: %s" % fmt_counts(hook["kinds"]))
        L.append("  압축 %d회 · 주입 %d회 · 접기 단계: %s · 접힌 턴 합계 %d개"
                 % (hook["compactions"], hook["injections"], fmt_counts(hook["stages"]), hook["folded"]))
        L.append("  가장 긴 주입문: %d자 (UTF-16 %d단위, 상한 6,000)" % (hook["max_chars"], hook["max_utf16"]))
        L.append("  오류(errors.jsonl): %d건%s" % (hook["errors"], " — " + fmt_counts(hook["error_where"]) if hook["errors"] else ""))
        L.append("  훅 호출(events.jsonl): %s" % fmt_counts(hook["events"]))
        L.append("  처리 내용: %s" % fmt_counts(hook["actions"]))
        if hook["answer_src"]:
            L.append("  답변 출처: %s" % fmt_counts(hook["answer_src"]))
        L.append("  agent_id가 있던 훅 입력: %d건" % hook["agent_inputs"])
        if hook["ms"]["n"]:
            L.append("  훅 처리 시간(인터프리터 기동 제외): 중앙값 %.1fms · 95%% %.1fms · 최대 %.1fms (%d회)"
                     % (hook["ms"]["median"], hook["ms"]["p95"], hook["ms"]["max"], hook["ms"]["n"]))
        for version, n in sorted(hook["versions"].items()):
            L.append("  훅 버전: %s (세션 %d개)" % (version, n))
    notes = []
    if rep["writes_under_ctx_index"]:
        notes.append("경고: 쓰기 도구가 ctx-index 아래를 대상으로 한 호출 %d건 (모델은 여기에 쓰지 않아야 합니다)" % len(rep["writes_under_ctx_index"]))
        for w in rep["writes_under_ctx_index"][:10]:
            notes.append("  - %s %s (세션 %s)" % (w["tool"], w["target"], w["session"][:8]))
    if tr["duplicates"]:
        notes.append("여러 파일에 중복으로 들어 있던 도구 호출 %d건은 한 번만 셌습니다(fork한 세션 등)." % tr["duplicates"])
    if tr["bad_lines"] or hook["bad_lines"]:
        notes.append("읽지 못한 줄: 트랜스크립트 %d줄, 훅 기록 %d줄 (건너뜀)" % (tr["bad_lines"], hook["bad_lines"]))
    for u in tr["unreadable"][:5]:
        notes.append("열지 못한 파일: %s" % u)
    if not tr["files"]["main"] and not tr["files"]["sub"]:
        notes.append("트랜스크립트를 찾지 못했습니다. --projects 로 위치를 지정하세요.")
    if notes:
        L += ["", "[참고]"] + ["  " + n for n in notes]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- command line
def main(argv=None):
    home = os.path.expanduser("~")
    ap = argparse.ArgumentParser(description="Count how often tool calls referred to ctx-index turn files and to raw transcripts.")
    ap.add_argument("paths", nargs="*", help="transcript files or directories to scan (default: --projects)")
    ap.add_argument("--projects", default=os.path.join(home, ".claude", "projects"), help="transcript root (default: ~/.claude/projects)")
    ap.add_argument("--ctx-dir", default=os.environ.get("CTX_INDEX_DIR") or os.path.join(home, ".claude", "ctx-index"),
                    help="the hook's storage root (default: ~/.claude/ctx-index, or $CTX_INDEX_DIR when set)")
    ap.add_argument("--days", type=float, help="only the last N days")
    ap.add_argument("--since", help="only from this date/time on (YYYY-MM-DD or ISO 8601, local time)")
    ap.add_argument("--until", help="only before this date/time")
    ap.add_argument("--session", help="only this session id")
    ap.add_argument("--no-subagents", action="store_true", help="leave subagent transcripts out")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the text report")
    ap.add_argument("--out", help="write the report to this file as UTF-8 instead of printing it")
    a = ap.parse_args(argv)

    since = until = None
    if a.days is not None:
        since = datetime.datetime.now().astimezone() - datetime.timedelta(days=a.days)
    if a.since:
        since = parse_time(a.since)
        if since is None:
            ap.error("--since: cannot read %r as a date" % a.since)
    if a.until:
        until = parse_time(a.until)
        if until is None:
            ap.error("--until: cannot read %r as a date" % a.until)
    roots = a.paths or [a.projects]
    files = find_transcripts(roots, subagents=not a.no_subagents)
    tx = scan_transcripts(files, since, until, subagents=not a.no_subagents, only_session=a.session)
    ctx = scan_ctx_dir(a.ctx_dir, since, until, only_session=a.session)
    meta = {"projects": [os.path.abspath(r) for r in roots], "since": since.isoformat(timespec="seconds") if since else None,
            "until": until.isoformat(timespec="seconds") if until else None, "subagents": not a.no_subagents,
            "session": a.session, "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    rep = build_report(tx, ctx, meta)
    text = json.dumps(rep, ensure_ascii=False, indent=1) + "\n" if a.json else render_text(rep)
    if a.out:
        with open(a.out, "wb") as f:
            f.write(text.encode("utf-8"))
        return 0
    try:
        sys.stdout.reconfigure(errors="replace")       # a console code page must not be able to crash the report
    except Exception:
        pass
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
