# -*- coding: utf-8 -*-
"""Tests for tools/ctx_index_measure.py (completion criterion c).

Synthetic transcripts with a known number of references are scanned and the counts are
compared with the expected values, tool by tool and session by session.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # make `support` importable however the tests are started
import support as S  # noqa: E402
from support import ci, session_start, stop, ups  # noqa: E402

measure = S.load_module("ctx_index_measure", os.path.join(S.TOOLS, "ctx_index_measure.py"))
SCRIPT = os.path.join(S.TOOLS, "ctx_index_measure.py")

S1 = "aaaaaaaa-1111-4111-8111-111111111111"
S2 = "bbbbbbbb-2222-4222-8222-222222222222"
NIX = "/home/u/.claude/ctx-index/%s" % S1
WIN = "C:\\Users\\me\\.claude\\ctx-index\\%s" % S1

# (id, side, session, tool, input, expected categories, expected label, turn files named)
CASES = [
    ("t01", "main", S1, "Read", {"file_path": NIX + "/turns/0003.md"}, ["turns"], "Read", ["0003"]),
    ("t02", "main", S1, "Read", {"file_path": WIN + "\\turns\\0004.md"}, ["turns"], "Read", ["0004"]),
    ("t03", "main", S1, "Grep", {"pattern": "retry", "path": WIN.replace("\\", "\\\\") + "\\\\turns"}, ["turns"], "Grep", []),
    ("t04", "main", S1, "Grep", {"pattern": "x", "path": NIX, "glob": "turns/*.md"}, ["turns"], "Grep", []),
    ("t05", "main", S1, "Glob", {"pattern": "**/turns/*.md", "path": "/home/u/.claude/ctx-index"}, ["turns"], "Glob", []),
    ("t06", "main", S1, "Bash", {"command": "cd ~/.claude/ctx-index/%s && cat turns/0001.md turns/0002.md" % S1}, ["turns"], "Bash", ["0001", "0002"]),
    ("t07", "main", S1, "Bash", {"command": "cat ~/.claude/ctx-index/%s/meta.json | python -m json.tool" % S1}, ["ctx_other"], "Bash", []),
    ("t08", "main", S1, "Bash", {"command": 'grep -l "timeout" ~/.claude/projects/-w-proj/*.jsonl'}, ["transcript"], "Bash", []),
    ("t09", "main", S1, "Read", {"file_path": "C:\\Users\\me\\.claude\\projects\\C--work-proj\\%s.jsonl" % S1}, ["transcript"], "Read", []),
    ("t10", "main", S1, "Bash", {"command": "ls ~/.claude/projects/"}, [], "Bash", []),
    ("t11", "main", S1, "Bash", {"command": "grep turns README.md && ls turns/"}, [], "Bash", []),
    ("t12", "main", S1, "PowerShell", {"command": "Get-Content %s\\turns\\0003.md; Select-String -Path C:\\Users\\me\\.claude\\projects\\C--w\\*.jsonl -Pattern x" % WIN},
     ["turns", "transcript"], "PowerShell", ["0003"]),
    ("t13", "main", S1, "mcp__fs__read_files", {"args": {"paths": [NIX + "/turns/0007.md"], "opts": {"n": 1}}}, ["turns"], "mcp__fs__read_files", ["0007"]),
    ("t14", "main", S1, "Write", {"file_path": "/work/README.md", "content": "원문은 ~/.claude/ctx-index/<session_id>/turns/ 에 있습니다."},
     ["turns"], "Write(text)", []),
    ("t15", "main", S1, "Edit", {"file_path": NIX + "/turns/0003.md", "old_string": "a", "new_string": "b"}, ["turns"], "Edit", ["0003"]),
    ("t16", "main", S1, "Agent", {"description": "look up", "prompt": "Read %s/turns/0005.md and summarise it" % NIX}, ["turns"], "Agent", ["0005"]),
    ("t17", "main", S1, "Read", {"file_path": "/work/src/turns/0001.md"}, [], "Read", []),
    ("t18", "main", S1, "Read", {"file_path": "/work/ctx-index-notes/turns/x.md"}, [], "Read", []),
    ("t19", "main", S1, "Bash", {"command": "cat my-ctx-index/turns/a; echo ctx-index; python hooks/ctx_index.py"}, [], "Bash", []),
    ("t20", "main", S1, "Bash", {"command": "ls /c/Users/me/.claude/ctx-index/*/turns | head"}, ["turns"], "Bash", []),
    ("t21", "main", S1, "Read", {"file_path": "/mnt/c/Users/me/.claude/ctx-index/%s/index.md" % S1}, ["ctx_other"], "Read", []),
    ("t22", "main", S1, "Bash", {"command": "wc -l $HOME/.claude/projects/-w-proj/%s/subagents/agent-1.jsonl" % S1}, ["transcript"], "Bash", []),
    ("t23", "main", S1, "Write", {"file_path": "C:/Users/me/.claude/ctx-index/%s/notes.md" % S1, "content": "x"}, ["ctx_other"], "Write", []),
    ("t24", "main", S1, "Read", {"file_path": "%USERPROFILE%\\.CLAUDE\\CTX-INDEX\\" + S1 + "\\TURNS\\0009.md"}, ["turns"], "Read", ["0009"]),
    ("t25", "main", S1, "WeirdTool", "a plain string input: " + NIX + "/turns/0011.md", ["turns"], "WeirdTool", ["0011"]),
    ("t26", "main", S1, "WeirdTool", None, [], "WeirdTool", []),
    ("t27", "main", S1, "WeirdTool", [NIX + "\\turns", 5, None, {"deep": [{"er": "x"}]}], ["turns"], "WeirdTool", []),
    ("u01", "sub", S1, "Read", {"file_path": NIX + "/turns/0005.md"}, ["turns"], "Read", ["0005"]),
    ("u02", "sub", S1, "Bash", {"command": "tail -n 5 /home/u/.claude/projects/-w-proj/%s.jsonl" % S1}, ["transcript"], "Bash", []),
    ("u03", "sub", S1, "Bash", {"command": "echo done"}, [], "Bash", []),
    ("v01", "main", S2, "Read", {"file_path": "/home/u/.claude/ctx-index/%s/turns/0001.md" % S2}, ["turns"], "Read", ["0001"]),
    ("v02", "main", S2, "Bash", {"command": "git status"}, [], "Bash", []),
]


def assistant(sid, blocks, ts, **kw):
    e = {"parentUuid": "p", "isSidechain": False, "type": "assistant", "sessionId": sid, "timestamp": ts,
         "message": {"id": "msg_" + ts, "role": "assistant", "model": "claude-test", "content": blocks}}
    e.update(kw)
    return e


def tool_use(case):
    return {"type": "tool_use", "id": "toolu_" + case[0], "name": case[3], "input": case[4]}


def build_tree(root):
    """A ~/.claude/projects look-alike holding CASES plus entries that must not be counted."""
    proj = os.path.join(root, "projects", "-w-proj")
    os.makedirs(os.path.join(proj, S1, "subagents"))
    main1 = [c for c in CASES if c[1] == "main" and c[2] == S1]
    lines = [{"type": "user", "sessionId": S1, "promptId": "p1", "timestamp": "2026-11-20T01:00:00.000Z",
              "message": {"role": "user", "content": "read %s/turns/0001.md please" % NIX}},
             assistant(S1, [{"type": "text", "text": "I will read %s/turns/0001.md" % NIX}], "2026-11-20T01:00:01.000Z")]
    for i, c in enumerate(main1):
        ts = "2026-11-%02dT02:%02d:00.000Z" % (20 + i % 5, i)
        if i == 3:                                   # two tool calls in one entry
            continue
        blocks = [tool_use(c)] + ([tool_use(main1[3])] if i == 2 else [])
        lines.append(assistant(S1, blocks, ts))
        lines.append({"type": "user", "sessionId": S1, "timestamp": ts, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_" + c[0], "content": "result mentions %s/turns/0099.md and ~/.claude/projects/x/y.jsonl" % NIX}]}})
    lines += [
        {"type": "system", "subtype": "compact_boundary", "sessionId": S1, "timestamp": "2026-11-21T00:00:00.000Z", "content": "Conversation compacted"},
        {"type": "system", "subtype": "compact_boundary", "sessionId": S1, "timestamp": "2026-11-23T00:00:00.000Z", "content": "Conversation compacted"},
        {"type": "system", "subtype": "stop_hook_summary", "sessionId": S1, "timestamp": "2026-11-23T00:00:01.000Z"},
        {"type": "attachment", "sessionId": S1, "attachment": {"type": "hook_additional_context", "content": [
            "SessionStart hook additional context: 디렉터리: %s/turns" % NIX, {"type": "tool_use", "id": "toolu_fake", "name": "Read", "input": {"file_path": NIX + "/turns/0001.md"}}]}},
        {"type": "api-request-blob", "sessionId": S1, "message": {"content": [{"type": "tool_use", "id": "toolu_blob", "name": "Read", "input": {"file_path": NIX + "/turns/0001.md"}}]}},
        assistant(S1, [tool_use(main1[0])], "2026-11-24T05:00:00.000Z"),            # the same tool call id again
        assistant(S1, "a string instead of blocks mentioning tool_use", "2026-11-24T05:00:01.000Z"),
        assistant(S1, [{"type": "tool_use"}, "junk", None, {"type": "thinking", "thinking": NIX + "/turns/0001.md tool_use"}], "2026-11-24T05:00:02.000Z"),
    ]
    with open(os.path.join(proj, S1 + ".jsonl"), "wb") as f:
        for e in lines:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        f.write(b'{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_cut","name":"Read","input":{"file_pa\n')
        f.write(b'\xff\xfe not json but mentions "tool_use"\n\n')
        f.write(b'["tool_use"]\n"tool_use"\n')
    with open(os.path.join(proj, S1, "subagents", "agent-abc123.jsonl"), "wb") as f:
        for i, c in enumerate([c for c in CASES if c[1] == "sub"]):
            e = assistant(S1, [tool_use(c)], "2026-11-22T03:%02d:00.000Z" % i, isSidechain=True, agentId="abc123")
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    with open(os.path.join(proj, S1, "subagents", "agent-abc123.meta.json"), "wb") as f:
        f.write(b'{"agentType":"general-purpose"}')
    with open(os.path.join(proj, S2 + ".jsonl"), "wb") as f:                        # a fork: starts with a copy of S1's history
        copied = assistant(S2, [tool_use(main1[0]), tool_use(main1[1])], "2026-11-20T02:00:00.000Z")
        f.write(json.dumps(copied, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        for i, c in enumerate([c for c in CASES if c[2] == S2]):
            e = assistant(S2, [tool_use(c)], "2026-11-25T04:%02d:00.000Z" % i)
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    os.utime(os.path.join(proj, S1 + ".jsonl"), (1000000000, 1000000000))            # the original is older than its fork
    with open(os.path.join(proj, "notes.txt"), "wb") as f:
        f.write(("not a transcript: " + NIX + "/turns/0001.md").encode("utf-8"))
    os.makedirs(os.path.join(root, "projects", "-empty-proj", "memory"))
    open(os.path.join(root, "projects", "-empty-proj", "empty.jsonl"), "wb").close()
    return os.path.join(root, "projects")


def expected(cases):
    total = dict((c, {"main": 0, "sub": 0}) for c in measure.CATEGORIES)
    by_tool = {}
    for _id, side, _sid, _tool, _inp, cats, label, _files in cases:
        for c in cats:
            total[c][side] += 1
            by_tool.setdefault(label, dict((x, {"main": 0, "sub": 0}) for x in measure.CATEGORIES))[c][side] += 1
    return total, by_tool


class Classification(unittest.TestCase):
    """The counting rule itself, one tool call at a time."""

    def test_c_every_case_is_classified_as_expected(self):
        for cid, _side, _sid, tool, inp, cats, label, files in CASES:
            got, got_label, got_files, _w = measure.classify_call(tool, inp)
            self.assertEqual(sorted(k for k, v in got.items() if v), sorted(cats), cid)
            self.assertEqual(got_label, label, cid)
            self.assertEqual(got_files, files, cid)

    def test_c_both_path_separators_and_their_mixtures_count(self):
        tail = ["ctx-index", S1, "turns", "0003.md"]
        heads = ["C:{s}Users{s}me{s}.claude", "{s}home{s}u{s}.claude", "~{s}.claude", "$HOME{s}.claude", "%USERPROFILE%{s}.claude",
                 "{s}c{s}Users{s}me{s}.claude", "{s}{s}server{s}share{s}.claude"]
        seps = ["/", "\\", "\\\\", "//", "\\/", "/\\"]
        n = 0
        for head in heads:
            for a in seps:
                for b in seps:
                    path = head.format(s=a) + a + b.join(tail)
                    for tool, inp in (("Read", {"file_path": path}), ("Bash", {"command": 'cat "%s" | head -3' % path}),
                                      ("Grep", {"pattern": "x", "path": path.rsplit(b, 1)[0]})):
                        cats = measure.classify_call(tool, inp)[0]
                        self.assertEqual((cats["turns"], cats["ctx_other"], cats["transcript"]), (True, False, False), (tool, path))
                        n += 1
                    tx = head.format(s=a) + a + b.join(["projects", "-w-proj", S1 + ".jsonl"])
                    cats = measure.classify_call("Read", {"file_path": tx})[0]
                    self.assertEqual((cats["turns"], cats["ctx_other"], cats["transcript"]), (False, False, True), tx)
        self.assertEqual(n, 7 * 6 * 6 * 3)

    def test_c_json_escaped_windows_paths_as_they_appear_in_a_transcript(self):
        """A transcript line stores "C:\\Users\\..." JSON-escaped; after parsing, the path has single backslashes."""
        line = json.dumps({"type": "tool_use", "id": "x", "name": "Read", "input": {"file_path": WIN + "\\turns\\0001.md"}})
        self.assertIn("\\\\turns\\\\0001.md", line)
        cats = measure.classify_call("Read", json.loads(line)["input"])[0]
        self.assertTrue(cats["turns"])

    def test_c_near_misses_are_not_counted(self):
        misses = ["ctx-index", "turns/0001.md", "/home/u/.claude/ctx_index/x/turns/0001.md", "/home/u/.claude/ctx-indexes/x/turns/1.md",
                  "/home/u/.claude/my-ctx-index/x/turns/1.md", "ctx-index and turns as plain words", "/x/ctx-index.bak/turns/",
                  "~/.claude/projects", "~/.claude/projects/-w/", "session.jsonl", "/tmp/data.jsonl and ~/.claude/settings.json",
                  "~/.claude/projects-old/a.jsonl", "~/.claude/projects/a.jsonlines", "~/.claude/project/a.jsonl"]
        for text in misses:
            cats = measure.classify_call("Bash", {"command": text})[0]
            self.assertEqual((cats["turns"], cats["transcript"]), (False, False), text)
        self.assertTrue(measure.classify_call("Bash", {"command": "ls ~/.claude/ctx-index"})[0]["ctx_other"])

    def test_c_write_targets_under_ctx_index_are_flagged(self):
        self.assertTrue(measure.classify_call("Write", {"file_path": NIX + "/turns/0001.md", "content": "x"})[3])
        self.assertTrue(measure.classify_call("NotebookEdit", {"notebook_path": WIN + "\\x.ipynb", "new_source": "x"})[3])
        self.assertFalse(measure.classify_call("Write", {"file_path": "/w/a.md", "content": NIX + "/turns/0001.md"})[3])
        self.assertFalse(measure.classify_call("Read", {"file_path": NIX + "/turns/0001.md"})[3])
        self.assertEqual(measure.classify_call("Edit", {"file_path": "/w/a.md", "old_string": "~/.claude/projects/x.jsonl", "new_string": ""})[1], "Edit(text)")
        self.assertEqual(measure.classify_call("Write", {"file_path": "/w/a.md", "content": "nothing"})[1], "Write")

    def test_c_strings_of_walks_nested_inputs(self):
        self.assertEqual(measure.strings_of({"a": ["x", {"b": "y", "c": [1, None, ("z",)]}], "d": 5}), ["x", "y", "z"])
        deep = "leaf"
        for _ in range(50):
            deep = [deep]
        self.assertEqual(measure.strings_of(deep), [])           # bounded depth, no recursion error

    def test_c_parse_time(self):
        utc = measure.parse_time("2026-11-26T00:49:59.491Z")
        self.assertEqual(utc.isoformat(), "2026-11-26T00:49:59.491000+00:00")
        self.assertEqual(measure.parse_time("2026-11-26T09:49:59+09:00"), measure.parse_time("2026-11-26T00:49:59Z"))
        self.assertEqual(measure.parse_time("2026-11-26T09:49:59+0900"), measure.parse_time("2026-11-26T00:49:59Z"))
        self.assertIsNotNone(measure.parse_time("2026-11-26").tzinfo)
        self.assertIsNotNone(measure.parse_time("2026-11-26 10:00:00").tzinfo)
        for bad in (None, 5, "", "yesterday", "2026-13-45", "2026-11-26T99:00:00Z"):
            self.assertIsNone(measure.parse_time(bad), bad)


class Counting(unittest.TestCase):
    """Whole transcripts with a known number of references."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ctxidx-measure-")
        cls.projects = build_tree(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def scan(self, **kw):
        subagents = kw.pop("subagents", True)
        files = measure.find_transcripts([self.projects], subagents=subagents)
        return measure.scan_transcripts(files, subagents=subagents, **kw)

    def totals(self, res):
        out = dict((c, {"main": 0, "sub": 0}) for c in measure.CATEGORIES)
        for s in res["sessions"].values():
            for c in measure.CATEGORIES:
                for side in ("main", "sub"):
                    out[c][side] += s["calls"][c][side]
        return out

    def test_c_reference_counts_match_the_known_values(self):
        res = self.scan()
        want_total, want_by_tool = expected(CASES)
        self.assertEqual(self.totals(res), want_total)
        # the same numbers written out, so that a mistake in the table above cannot hide a mistake in the script
        self.assertEqual(self.totals(res), {"turns": {"main": 16, "sub": 1}, "transcript": {"main": 4, "sub": 1},
                                            "ctx_other": {"main": 3, "sub": 0}})
        self.assertEqual(res["by_tool"], want_by_tool)
        flat = dict((tool, tuple(v[c]["main"] + v[c]["sub"] for c in measure.CATEGORIES)) for tool, v in res["by_tool"].items())
        self.assertEqual(flat, {"Read": (5, 1, 1), "Grep": (2, 0, 0), "Glob": (1, 0, 0), "Bash": (2, 3, 1), "PowerShell": (1, 1, 0),
                                "mcp__fs__read_files": (1, 0, 0), "Write(text)": (1, 0, 0), "Edit": (1, 0, 0), "Agent": (1, 0, 0),
                                "WeirdTool": (2, 0, 0), "Write": (0, 0, 1)})

    def test_c_counts_per_session_and_tool_calls(self):
        res = self.scan()
        self.assertEqual(sorted(res["sessions"]), [S1, S2])
        s1, s2 = res["sessions"][S1], res["sessions"][S2]
        self.assertEqual(s1["tool_calls"], {"main": 27, "sub": 3})
        self.assertEqual(s2["tool_calls"], {"main": 2, "sub": 0})
        self.assertEqual((s1["calls"]["turns"], s2["calls"]["turns"]), ({"main": 15, "sub": 1}, {"main": 1, "sub": 0}))
        self.assertEqual(s1["calls"]["transcript"], {"main": 4, "sub": 1})
        self.assertEqual(s1["compact_boundaries"], 2)
        self.assertEqual(s2["compact_boundaries"], 0)
        self.assertEqual(sorted(s1["turn_files"]), ["0001", "0002", "0003", "0004", "0005", "0007", "0009", "0011"])
        self.assertEqual(s1["turn_files"]["0003"], 3)            # t01, t12, t15
        self.assertEqual(s1["turn_files"]["0005"], 2)            # t16 (main) and u01 (subagent)
        self.assertEqual(sorted(s2["turn_files"]), ["0001"])

    def test_c_duplicated_tool_calls_are_counted_once(self):
        res = self.scan()
        self.assertEqual(res["duplicates"], 3)                   # t01 repeated in S1, t01 + t02 copied into the fork

    def test_c_files_and_unparsable_lines(self):
        res = self.scan()
        self.assertEqual(res["files"], {"main": 3, "sub": 1})    # S1, S2, empty.jsonl + the agent file; notes.txt and *.meta.json ignored
        self.assertEqual(res["bad_lines"], 2)
        self.assertEqual(res["unreadable"], [])

    def test_c_write_under_ctx_index_is_reported(self):
        res = self.scan()
        self.assertEqual([(w["tool"], w["session"]) for w in res["writes"]], [("Edit", S1), ("Write", S1)])

    def test_c_subagent_transcripts_can_be_left_out(self):
        res = self.scan(subagents=False)
        self.assertEqual(res["files"], {"main": 3, "sub": 0})
        self.assertEqual(self.totals(res), {"turns": {"main": 16, "sub": 0}, "transcript": {"main": 4, "sub": 0},
                                            "ctx_other": {"main": 3, "sub": 0}})

    def test_c_sidechain_entries_inside_a_main_transcript_count_as_subagent(self):
        d = tempfile.mkdtemp(prefix="ctxidx-side-")
        try:
            with open(os.path.join(d, "s.jsonl"), "wb") as f:
                for i, side in enumerate((False, True, True)):
                    e = assistant("sess-x", [{"type": "tool_use", "id": "t%d" % i, "name": "Read", "input": {"file_path": NIX + "/turns/0001.md"}}],
                                  "2026-11-20T01:00:0%d.000Z" % i, isSidechain=side)
                    f.write(json.dumps(e).encode("utf-8") + b"\n")
            res = measure.scan_transcripts(measure.find_transcripts([d]))
            self.assertEqual(res["sessions"]["sess-x"]["calls"]["turns"], {"main": 1, "sub": 2})
            res = measure.scan_transcripts(measure.find_transcripts([d]), subagents=False)
            self.assertEqual(res["sessions"]["sess-x"]["calls"]["turns"], {"main": 1, "sub": 0})
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_c_time_window(self):
        t = measure.parse_time
        res = self.scan(since=t("2026-11-22T00:00:00Z"))
        late = [c for c in CASES if c[1] == "sub" or c[2] == S2]
        idx = dict((c[0], i) for i, c in enumerate([c for c in CASES if c[1] == "main" and c[2] == S1]))
        late += [c for c in CASES if c[0] in idx and 20 + idx[c[0]] % 5 >= 22]
        self.assertEqual(self.totals(res), expected(late)[0])
        self.assertEqual(res["sessions"][S1]["compact_boundaries"], 1)
        res = self.scan(until=t("2026-11-20T00:00:00Z"))
        self.assertEqual(self.totals(res), expected([])[0])
        res = self.scan(since=t("2026-11-25T00:00:00Z"), until=t("2026-11-26T00:00:00Z"))
        self.assertEqual(sorted(res["sessions"]), [S2])
        self.assertEqual(self.totals(res)["turns"], {"main": 1, "sub": 0})

    def test_c_single_session_filter(self):
        res = self.scan(only_session=S2)
        self.assertEqual(sorted(res["sessions"]), [S2])
        self.assertEqual(res["sessions"][S2]["calls"]["turns"], {"main": 1, "sub": 0})

    def test_c_explicit_files_and_missing_paths(self):
        one = os.path.join(self.projects, "-w-proj", S2 + ".jsonl")
        res = measure.scan_transcripts(measure.find_transcripts([one, os.path.join(self.root, "does-not-exist")]))
        self.assertEqual(res["files"], {"main": 1, "sub": 0})
        self.assertEqual(res["sessions"][S2]["calls"]["turns"], {"main": 3, "sub": 0})      # without S1 its copied calls count here
        self.assertEqual(measure.scan_transcripts(measure.find_transcripts([]))["sessions"], {})

    def test_c_scanning_is_read_only(self):
        def snapshot():
            out = {}
            for d, _dirs, files in os.walk(self.root):
                for n in files:
                    p = os.path.join(d, n)
                    with open(p, "rb") as f:
                        out[p] = (os.path.getmtime(p), f.read())
            return out
        before = snapshot()
        self.scan()
        measure.scan_ctx_dir(os.path.join(self.root, "projects"))
        self.assertEqual(snapshot(), before)


class HookRecords(unittest.TestCase):
    """The second half of the report: what the hook itself recorded (real hook, real files)."""

    @classmethod
    def setUpClass(cls):
        cls.sb = S.Sandbox().enter()
        sb = cls.sb
        for i in range(1, 4):
            sb.feed(ups("질문 %d" % i, "p%d" % i, S1))
            sb.feed(stop("답변 %d 입니다. 내용이 이어집니다." % i, "p%d" % i, S1))
        sb.feed(session_start(sid=S1))
        sb.feed(ups("답이 없는 질문", "p4", S1))
        sb.feed(stop("요청 없는 답변입니다. 내용.", "p-orphan", S1))
        sb.feed(ups("서브에이전트 입력", "p5", S1, agent_id="agent-1"))
        sb.feed(session_start(sid=S1, pid="p4"))
        for i in range(1, 61):
            sb.feed(ups(S.REQ_BIG[i % 5] + " #%d" % i, "q%d" % i, S2))
            sb.feed(stop(S.ANS_BIG[i % 4], "q%d" % i, S2))
        sb.feed(session_start(sid=S2))
        sb.feed(session_start(sid="cccccccc-3333-4333-8333-333333333333"))          # compaction of a session without turns
        ci.log_error("lock", "timeout waiting for the session lock; continuing without it", S1)
        ci.log_error("main", "Traceback ...", None)
        with open(os.path.join(sb.sdir(S1), "events.jsonl"), "ab") as f:
            f.write(b"not json\n[1]\n")
        os.makedirs(os.path.join(sb.base, "dddddddd-empty"))
        cls.res = measure.scan_ctx_dir(sb.base)

    @classmethod
    def tearDownClass(cls):
        cls.sb.leave()
        cls.sb.destroy()

    def test_c_turns_compactions_and_injections(self):
        s1, s2 = self.res["sessions"][S1], self.res["sessions"][S2]
        self.assertEqual((s1["turns"], s1["turn_files"], s1["unanswered"]), (5, 5, 1))
        self.assertEqual(s1["kinds"], {"user": 4, "orphan": 1})
        self.assertEqual((s1["compactions"], s1["injections"], s1["stages"]), (2, 2, {"full": 2}))
        self.assertEqual((s2["turns"], s2["compactions"], s2["injections"], s2["folded"]), (60, 1, 1, 5))
        self.assertEqual(list(s2["stages"]), ["2a"])
        self.assertLessEqual(s2["max_utf16"], 6000)
        self.assertGreater(s2["max_chars"], 3000)
        empty = self.res["sessions"]["cccccccc-3333-4333-8333-333333333333"]
        self.assertEqual((empty["turns"], empty["compactions"], empty["injections"], empty["stages"]), (0, 1, 0, {"empty": 1}))
        self.assertEqual(self.res["sessions"]["dddddddd-empty"]["turns"], 0)

    def test_c_errors_events_and_timings(self):
        s1 = self.res["sessions"][S1]
        self.assertEqual((s1["errors"], self.res["root_errors"]), (1, 1))
        self.assertEqual(self.res["error_where"], {"lock": 1, "main": 1})
        self.assertEqual(s1["events"], {"UserPromptSubmit": 5, "Stop": 4, "SessionStart": 2})
        self.assertEqual(s1["actions"], {"new_turn": 4, "answer": 3, "orphan_turn": 1, "skip_agent": 1, "inject": 2})
        self.assertEqual((s1["agent_inputs"], s1["answer_src"]), (1, {"payload": 4}))
        self.assertEqual(self.res["bad_lines"], 2)
        self.assertEqual(len(self.res["ms"]), 11 + 121 + 1)
        self.assertEqual(self.res["ms"], sorted(self.res["ms"]))
        self.assertEqual(s1["hook"]["version"], ci.VERSION)

    def test_c_time_window_applies_to_hook_records(self):
        future = measure.parse_time("2999-01-01")
        res = measure.scan_ctx_dir(self.sb.base, since=future)
        self.assertEqual((res["sessions"][S1]["compactions"], res["sessions"][S1]["errors"], res["root_errors"], res["ms"]), (0, 0, 0, []))
        self.assertEqual(res["sessions"][S1]["turns"], 5)        # the turn count is the current state of the index
        res = measure.scan_ctx_dir(self.sb.base, only_session=S2)
        self.assertEqual(sorted(res["sessions"]), [S2])

    def test_c_missing_or_broken_directory(self):
        res = measure.scan_ctx_dir(os.path.join(self.sb.root, "nope"))
        self.assertEqual((res["exists"], res["sessions"]), (False, {}))
        d = tempfile.mkdtemp(prefix="ctxidx-broken-")
        try:
            os.makedirs(os.path.join(d, "sess", "turns"))
            for name, blob in (("meta.json", b"\x00garbage"), ("compactions.jsonl", b'{"chars":"x","stage":null}\n\xff\n'),
                               ("events.jsonl", b'{"ms":"slow","ev":5}\n'), ("errors.jsonl", b"{}\n")):
                with open(os.path.join(d, "sess", name), "wb") as f:
                    f.write(blob)
            with open(os.path.join(d, "errors.jsonl"), "wb") as f:
                f.write(b"\xff\xfe")
            res = measure.scan_ctx_dir(d)
            self.assertEqual((res["sessions"]["sess"]["turns"], res["sessions"]["sess"]["compactions"], res["sessions"]["sess"]["errors"]), (0, 1, 1))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Report(unittest.TestCase):
    """The command line: text and JSON output, files, encodings."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ctxidx-report-")
        cls.projects = build_tree(cls.root)
        cls.sb = S.Sandbox().enter()
        for i in range(1, 3):
            cls.sb.feed(ups("질문 %d" % i, "p%d" % i, S1))
            cls.sb.feed(stop("답변 %d 입니다. 내용이 이어집니다." % i, "p%d" % i, S1))
        cls.sb.feed(session_start(sid=S1))
        cls.sb.feed(ups("fork 한 세션의 질문", "p1", S2))
        cls.args = ["--projects", cls.projects, "--ctx-dir", cls.sb.base]

    @classmethod
    def tearDownClass(cls):
        cls.sb.leave()
        cls.sb.destroy()
        shutil.rmtree(cls.root, ignore_errors=True)

    def run_cli(self, *extra, **kw):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")        # a pipe would otherwise get the ANSI code page on Windows
        env.update(kw.get("env") or {})
        return subprocess.run([sys.executable, SCRIPT] + self.args + list(extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    def test_c_json_report(self):
        cp = self.run_cli("--json")
        self.assertEqual((cp.returncode, cp.stderr), (0, b""))
        rep = json.loads(cp.stdout.decode("utf-8"))
        self.assertEqual(rep["references"], {"turns": {"main": 16, "sub": 1}, "transcript": {"main": 4, "sub": 1}, "ctx_other": {"main": 3, "sub": 0}})
        self.assertEqual(rep["transcripts"]["tool_calls"], {"main": 29, "sub": 3})
        self.assertEqual(rep["transcripts"]["duplicates"], 3)
        rows = dict((r["session"], r) for r in rep["sessions"])
        self.assertEqual((rows[S1]["ref_turns"], rows[S1]["ref_transcript"], rows[S1]["ref_ctx_other"], rows[S1]["turn_files_named"]), (16, 5, 3, 8))
        self.assertEqual((rows[S1]["turns"], rows[S1]["compactions"], rows[S1]["injections"], rows[S1]["compact_boundaries"]), (2, 1, 1, 2))
        self.assertEqual((rows[S2]["ref_turns"], rows[S2]["turns"], rows[S2]["injections"]), (1, 1, 0))
        self.assertEqual((rep["sessions_with_injection"], rep["sessions_with_injection_and_turns_reference"]), (1, 1))
        self.assertEqual((rep["hook"]["turns"], rep["hook"]["compactions"], rep["hook"]["injections"], rep["hook"]["stages"]), (3, 1, 1, {"full": 1}))
        self.assertEqual(len(rep["writes_under_ctx_index"]), 2)
        self.assertEqual(rep["by_tool"]["Bash"]["transcript"], {"main": 2, "sub": 1})

    def test_c_text_report(self):
        cp = self.run_cli()
        self.assertEqual((cp.returncode, cp.stderr), (0, b""))
        text = cp.stdout.decode("utf-8")
        lines = [" ".join(line.split()) for line in text.split("\n")]
        self.assertIn("턴 파일 (ctx-index/…/turns/) 16 1 17", lines)
        self.assertIn("트랜스크립트 (.claude/projects/….jsonl) 4 1 5", lines)
        self.assertIn("ctx-index 기타 (meta.json 등) 3 0 3", lines)
        self.assertIn("전체 도구 호출 29 3 32", lines)
        self.assertIn("Read 5 1 1", lines)
        self.assertIn("Bash 2 3 1", lines)
        self.assertIn("Write(text) 1 0 0", lines)
        self.assertIn("주입이 있었던 세션 1개 중 턴 파일을 참조한 세션: 1개", lines)
        self.assertIn("%s 2 1 2 1 16 8 5 0" % S1, lines)
        self.assertIn("%s 1 0 0 0 1 1 0 0" % S2, lines)
        self.assertTrue(any(line.startswith("압축 1회 · 주입 1회 · 접기 단계: full 1") for line in lines))
        self.assertTrue(any(line.startswith("경고: 쓰기 도구가 ctx-index 아래를 대상으로 한 호출 2건") for line in lines))
        self.assertNotIn(chr(0xC815) + chr(0xBCF8), text)

    def test_c_out_file_is_utf8(self):
        out = os.path.join(self.root, "report.txt")
        cp = self.run_cli("--out", out, env={"PYTHONIOENCODING": "ascii", "LC_ALL": "C", "PYTHONUTF8": "0"})
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
        with open(out, "rb") as f:
            self.assertIn("ctx-index 실사용 측정", f.read().decode("utf-8"))

    def test_c_ascii_console_cannot_crash_the_report(self):
        cp = self.run_cli(env={"PYTHONIOENCODING": "ascii", "LC_ALL": "C", "PYTHONUTF8": "0"})
        self.assertEqual((cp.returncode, cp.stderr), (0, b""))
        self.assertIn(b"16", cp.stdout)

    def test_c_options(self):
        rep = json.loads(self.run_cli("--json", "--no-subagents").stdout.decode("utf-8"))
        self.assertEqual(rep["references"]["turns"], {"main": 16, "sub": 0})
        rep = json.loads(self.run_cli("--json", "--session", S2).stdout.decode("utf-8"))
        self.assertEqual([r["session"] for r in rep["sessions"]], [S2])
        rep = json.loads(self.run_cli("--json", "--since", "2026-11-25", "--until", "2026-11-26").stdout.decode("utf-8"))
        self.assertEqual(rep["references"]["turns"], {"main": 1, "sub": 0})
        rep = json.loads(self.run_cli("--json", "--days", "0.0001").stdout.decode("utf-8"))
        self.assertEqual(rep["references"]["turns"], {"main": 0, "sub": 0})
        self.assertEqual(self.run_cli("--since", "not-a-date").returncode, 2)
        one = os.path.join(self.projects, "-w-proj", S2 + ".jsonl")
        rep = json.loads(self.run_cli("--json", one).stdout.decode("utf-8"))
        self.assertEqual(rep["transcripts"]["files"], {"main": 1, "sub": 0})

    def test_c_defaults_point_into_the_home_directory(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        env.pop("CTX_INDEX_DIR", None)                           # set by the sandbox of this test class
        cp = subprocess.run([sys.executable, SCRIPT, "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(cp.returncode, 0)
        rep = json.loads(cp.stdout.decode("utf-8"))
        self.assertEqual(rep["meta"]["projects"], [os.path.join(S.FAKE_HOME, ".claude", "projects")])
        self.assertEqual(rep["hook"]["dir"], os.path.join(S.FAKE_HOME, ".claude", "ctx-index"))

    def test_c_empty_everything(self):
        cp = subprocess.run([sys.executable, SCRIPT, "--projects", os.path.join(self.root, "none"), "--ctx-dir", os.path.join(self.root, "none2")],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual((cp.returncode, cp.stderr), (0, b""))
        self.assertIn("트랜스크립트를 찾지 못했습니다", cp.stdout.decode("utf-8"))

    def test_c_display_width(self):
        self.assertEqual([measure.display_width(x) for x in ("abc", "한글", "a한b", "…", "")], [3, 4, 4, 1, 0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
