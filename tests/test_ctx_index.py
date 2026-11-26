# -*- coding: utf-8 -*-
"""Tests for hooks/ctx_index.py.

    python -m unittest discover -s tests -v          (from the repository root)

Layout (each class names the part of docs/phase3-report.md section 0 it covers):

  LabReplay            the 37 checks of lab/proto/sim_replay.py on real 2.1.332 payloads
  ProcessReplay        the same payloads through separate hook processes (exit code, stdout)
  Principles           core principles 1-5
  IndexDensity         required item 1 (index density, previews)
  StateSync            required item 2 (state synchronisation)   + A1, A2, A5
  Folding              required item 3 (two-stage folding)       + A3, A4, A7, cap (criterion b)
  Utf8AndFallbacks     required item 4 (UTF-8, fallbacks)
  Robustness           completion criterion a (always exit 0, errors.jsonl)
  EventLog             A6 (events.jsonl diagnostics)
  Recovery             meta.json rebuild / reconcile from turn files
  PrototypeParity      final hook == lab prototype where the behaviour was meant to stay

Standard library only. Nothing here touches the real home directory (see support.py).
"""
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # make `support` importable however the tests are started
import support as S  # noqa: E402
from support import NOTHING, SID, HookCase, ci, context_of, session_start, stop, ups  # noqa: E402

LIMIT = ci.MAX_CONTEXT_CHARS
TURN_LINE = re.compile(r"^\d{4,}\.md \d+\.\d(KB|MB) \| .* → .*$")
FOLD_LINE = re.compile(r"^\d{4,}\.md(~\d{4,}\.md)? \d+\.\d(KB|MB) \((\d+턴 )?접힘\)$")


def forbidden_word():
    return chr(0xC815) + chr(0xBCF8)


# =============================================================================== lab replay
class LabReplay(unittest.TestCase):
    """lab/proto/sim_replay.py, check by check, against the final hook.

    Input: hook payloads captured from the real Claude Code 2.1.332 CLI. Every event is
    replayed against the transcript cut to the size it had when that hook ran."""

    @classmethod
    def setUpClass(cls):
        cls.R = {}
        for name in S.CAPTURE_NAMES:
            cls.R[name] = S.Replay(name)

    @classmethod
    def tearDownClass(cls):
        for r in cls.R.values():
            r.close()

    def turns_of(self, capture, needle=None):
        r = self.R[capture]
        if needle is None:
            (sess,) = r.sessions.values()
        else:
            _, sess = r.session_with(needle)
        return r, sess, sess["meta"]["turns"]

    # ---- capture a: stream-json - plain / tool / subagent / custom slash / branch switch / compact / empty answer / clear
    def test_lab01_a_two_session_directories_only(self):
        """a: two session directories (original + new id after /clear); branch switch and compaction keep the directory."""
        self.assertEqual(len(self.R["a"].sessions), 2)

    def test_lab02_a_original_session_has_eight_turns(self):
        """a: 8 turns (plain, tool, subagent, task notification, custom slash, after branch switch, after compaction, empty answer)."""
        _, _, T = self.turns_of("a", "첫 번째 질문")
        self.assertEqual(len(T), 8)

    def test_lab03_a_builtin_commands_are_not_recorded(self):
        """a: /compact, /cost, /help, /status, /clear never become turns."""
        _, _, T = self.turns_of("a", "첫 번째 질문")
        self.assertFalse([t["req"] for t in T if t["req"].startswith(("/compact", "/cost", "/help", "/status", "/clear"))])

    def test_lab04_a_custom_slash_command_is_recorded_verbatim(self):
        """a: a custom slash command is stored as typed."""
        _, _, T = self.turns_of("a", "첫 번째 질문")
        self.assertTrue(any(t["req"] == "/mycmd 인자1 인자2" and t["kind"] == "user" for t in T))

    def test_lab05_a_tool_turn_answer_is_the_final_text(self):
        """a: the answer of a tool turn is the final text, not the narration before the tool call."""
        r, sess, T = self.turns_of("a", "첫 번째 질문")
        self.assertIn("도구 실행을 마쳤습니다", T[1]["ans"])
        self.assertNotIn("먼저 도구를", r.turn_file(sess, 2))

    def test_lab06_a_task_notification_turn_is_labelled(self):
        """a: the automatic <task-notification> turn shows as a task note with its summary (A5)."""
        _, _, T = self.turns_of("a", "첫 번째 질문")
        self.assertTrue(T[3]["req"].startswith("[작업 알림] Agent"))
        self.assertEqual(T[3]["kind"], "auto")

    def test_lab07_a_stop_without_answer_does_not_pull_the_previous_answer(self):
        """a: Stop without last_assistant_message - the fallback must not fetch the previous turn's answer."""
        _, _, T = self.turns_of("a", "첫 번째 질문")
        empty = [t for t in T if t["req"].startswith("[[EMPTY]]")][0]
        self.assertEqual((empty["nans"], empty["status"]), (0, "done"))

    def test_lab08_a_one_injection_under_the_cap_starting_with_the_header(self):
        """a: exactly one injection, within the cap, starting with the fixed header."""
        outs = self.R["a"].outs
        self.assertEqual(len(outs), 1)
        self.assertLessEqual(ci.ulen(outs[0][1]), LIMIT)
        self.assertTrue(outs[0][1].startswith(ci.HEADER))

    def test_lab09_a_directory_path_appears_once(self):
        """a: the absolute turns directory appears exactly once in the injected text."""
        r, sess, _ = self.turns_of("a", "첫 번째 질문")
        self.assertEqual(r.outs[0][1].count(os.path.join(sess["dir"], "turns")), 1)

    def test_lab10_a_turn_file_keeps_request_and_answer_verbatim(self):
        """a: request and answer are stored as they were (Hangul, emoji, code fence)."""
        r, sess, _ = self.turns_of("a", "첫 번째 질문")
        first = r.turn_file(sess, 1)
        self.assertIn("첫 번째 질문: 한글 테스트입니다", first)
        self.assertIn("한글·emoji 🙂 포함.", first)
        self.assertIn("```python\nprint('ok')\n```", first)

    def test_lab11_a_no_errors(self):
        """a: no errors.jsonl anywhere."""
        r = self.R["a"]
        self.assertEqual([s["errs"] for s in r.sessions.values()], [[], []])
        self.assertEqual(r.root_errors, [])

    # ---- capture b: auto compaction (UserPromptSubmit -> compaction -> Stop) + manual /compact <instructions>
    def test_lab12_b_two_compactions_one_directory(self):
        """b: both compactions land in the same session directory; two boundary lines."""
        r, sess, _ = self.turns_of("b")
        self.assertEqual((len(r.sessions), len(sess["comp"])), (1, 2))

    def test_lab13_b_turn_in_flight_during_auto_compaction(self):
        """b: the turn running during auto compaction is shown as in flight, not as interrupted (A2)."""
        text = self.R["b"].outs[0][1]
        self.assertIn(ci.IN_FLIGHT, text)
        self.assertNotIn(ci.NO_ANSWER, text)

    def test_lab14_b_auto_compaction_boundary(self):
        """b: the auto compaction boundary is last_turn=3, last_open=True."""
        _, sess, _ = self.turns_of("b")
        self.assertEqual((sess["comp"][0]["last_turn"], sess["comp"][0]["last_open"]), (3, True))

    def test_lab15_b_late_stop_lands_on_the_same_turn(self):
        """b: the Stop arriving after the auto compaction is attributed to turn 3."""
        _, _, T = self.turns_of("b")
        self.assertEqual(T[2]["nans"], 1)
        self.assertTrue(T[2]["req"].startswith("B3"))

    def test_lab16_b_manual_compaction_boundary(self):
        """b: the manual compaction boundary is last_turn=4, last_open=False."""
        _, sess, _ = self.turns_of("b")
        self.assertEqual((sess["comp"][1]["last_turn"], sess["comp"][1]["last_open"]), (4, False))

    def test_lab17_b_compact_with_instructions_is_not_a_turn(self):
        """b: '/compact <instructions>' is not recorded (5 turns)."""
        _, _, T = self.turns_of("b")
        self.assertEqual(len(T), 5)

    # ---- capture c: Stop blocked once by another hook / --resume / --continue / --fork-session
    def test_lab18_c_two_stops_one_turn_two_answers(self):
        """c: two Stop events with one prompt_id -> one turn holding two answers."""
        _, sess, T = self.turns_of("c", "C0 ")
        self.assertEqual((len(T), T[0]["nans"]), (1, 2))

    def test_lab19_c_both_answers_stored_in_order(self):
        """c: the turn file holds both answers in order."""
        r, sess, _ = self.turns_of("c", "C0 ")
        body = r.turn_file(sess, 1)
        self.assertIn("## ◇ 답변 ·", body)
        self.assertIn("## ◇ 답변 (이어짐 2) ·", body)
        self.assertLess(body.index("## ◇ 답변 ·"), body.index("## ◇ 답변 (이어짐 2) ·"))

    def test_lab20_c_resume_and_continue_keep_the_directory(self):
        """c: --resume / --continue keep the session id -> three turns in one directory."""
        _, _, T = self.turns_of("c", "C1 ")
        self.assertEqual([t["req"][:2] for t in T], ["C1", "C2", "C3"])

    def test_lab21_c_fork_gets_a_new_directory(self):
        """c: --fork-session gets a new session id (three directories in total)."""
        self.assertEqual(len(self.R["c"].sessions), 3)

    # ---- capture d: TUI - built-in commands / Esc interrupt / bash mode / compact / clear / exit
    def test_lab22_d_interrupted_turn_stays_open(self):
        """d: Esc interrupt sends no Stop -> the turn stays open and shows the no-answer label."""
        r, _, T = self.turns_of("d", "대화형 첫 질문")
        slow = [t for t in T if t["req"].startswith("[[SLOW]]")][0]
        self.assertEqual((slow["status"], slow["nans"]), ("open", 0))
        self.assertIn(" | [[SLOW]] 느린 답변을 요청합니다 → " + ci.NO_ANSWER, r.outs[0][1])

    def test_lab23_d_stop_without_prompt_becomes_its_own_turn(self):
        """d: a Stop without UserPromptSubmit (bash mode) is a new turn file, not glued to the previous turn."""
        _, _, T = self.turns_of("d", "대화형 첫 질문")
        bash = [t for t in T if t["kind"] == "orphan"]
        self.assertEqual([t["n"] for t in bash], [4])

    def test_lab24_d_bash_request_recovered_from_transcript(self):
        """d: that turn's request is recovered from the transcript (A5)."""
        _, _, T = self.turns_of("d", "대화형 첫 질문")
        self.assertEqual([t["req"] for t in T if t["kind"] == "orphan"], ["!echo bash-mode-probe"])

    def test_lab25_d_answer_after_interrupt_is_not_misattributed(self):
        """d: the answer of the turn after the interrupt does not land on the interrupted turn."""
        _, _, T = self.turns_of("d", "대화형 첫 질문")
        self.assertEqual([t for t in T if t["req"].startswith("중단 이후")][0]["nans"], 1)

    def test_lab26_d_clear_gets_a_new_directory(self):
        """d: after /clear the session id (and the directory) is new."""
        self.assertEqual(len(self.R["d"].sessions), 2)

    # ---- capture e: TUI - input typed while working (queue): run as its own turn / absorbed by the running turn
    Q2_ECHO = "요청하신 내용(Q2 대기열에 넣은 질문)"      # the mock answer echoes the prompt it answers

    def test_lab27_e_first_turn_holds_only_its_own_answer(self):
        """e: Q1's turn holds Q1's answer only (A1)."""
        r, sess, T = self.turns_of("e")
        self.assertTrue(T[0]["req"].startswith("[[SLOW]] Q1"))
        self.assertEqual(r.turn_file(sess, 1).count("## ◇ 답변"), 1)
        self.assertNotIn(self.Q2_ECHO, r.turn_file(sess, 1))

    def test_lab28_e_queued_input_kept_in_the_running_turn(self):
        """e: Q2, typed while Q1 ran, is also kept in Q1's file as an additional request."""
        r, sess, T = self.turns_of("e")
        self.assertEqual(T[0]["nreq"], 2)
        self.assertIn("Q2 대기열에 넣은 질문", r.turn_file(sess, 1))

    def test_lab29_e_queued_prompt_gets_its_own_turn_at_stop(self):
        """e: Q2's own turn is created at its Stop, request recovered from the transcript, Q2's answer attached."""
        r, sess, T = self.turns_of("e")
        self.assertEqual(T[1]["kind"], "orphan")
        self.assertTrue(T[1]["req"].startswith("Q2 대기열"))
        self.assertIn(self.Q2_ECHO, r.turn_file(sess, 2))

    def test_lab30_e_input_during_tool_turn_is_absorbed(self):
        """e: input typed during a tool turn is absorbed: one turn, two requests, one answer."""
        _, _, T = self.turns_of("e")
        self.assertEqual((T[2]["nreq"], T[2]["nans"], len(T)), (2, 1, 3))

    def test_lab31_e_no_turn_is_wrongly_marked_unanswered(self):
        """e: no turn is shown as unanswered."""
        _, _, T = self.turns_of("e")
        self.assertTrue(all(t["nans"] >= 1 for t in T))

    # ---- capture stacked: TUI - nested queue (Q2 typed during Q1, Q5 typed during Q2) + idle plain / custom slash
    def test_lab32_stacked_idle_prompts_are_new_turns(self):
        """stacked: a plain prompt and a custom slash typed while idle are new turns (the transcript probe does not misfire)."""
        _, _, T = self.turns_of("stacked")
        self.assertEqual((T[0]["kind"], T[1]["kind"], T[1]["req"]), ("user", "user", "/mycmd 대화형 인자"))

    def test_lab33_stacked_five_turns(self):
        """stacked: five turns - Q1 (+Q2 typed) / Q2's own turn (+Q5 typed) / Q5's own turn."""
        _, _, T = self.turns_of("stacked")
        self.assertEqual(len(T), 5)

    def test_lab34_stacked_running_turn_recovered_at_prompt_time(self):
        """stacked: Q2's own turn is created when Q5 is typed, its request recovered from the transcript."""
        _, _, T = self.turns_of("stacked")
        self.assertEqual((T[3]["kind"], T[3]["nreq"]), ("recovered", 2))
        self.assertTrue(T[3]["req"].startswith("[[SLOW]] Q2"))

    def test_lab35_stacked_answers_reach_their_own_turns(self):
        """stacked: Q2's answer (#9) is in Q2's turn, Q5's answer (#10) in Q5's turn."""
        r, sess, T = self.turns_of("stacked")
        self.assertIn("답변 9", r.turn_file(sess, 4))
        self.assertIn("답변 10", r.turn_file(sess, 5))
        self.assertTrue(T[4]["req"].startswith("Q5 두 번째"))

    # ---- capture headless: stream-json - plain / custom slash / background subagent -> task notification / follow-up
    def test_lab36_headless_turn_kinds(self):
        """headless: five turns, all created by UserPromptSubmit; the task notification is 'auto'."""
        _, _, T = self.turns_of("headless")
        self.assertEqual([t["kind"] for t in T], ["user", "user", "user", "auto", "user"])

    def test_lab37_headless_one_answer_each(self):
        """headless: every turn has exactly one answer."""
        _, _, T = self.turns_of("headless")
        self.assertTrue(all(t["nans"] == 1 for t in T))

    # ---- not lab checks, but properties every capture must have
    def test_replay_every_injection_is_within_the_cap_and_well_formed(self):
        n = 0
        for r in self.R.values():
            for _sid, text in r.outs:
                n += 1
                self.assertLessEqual(max(len(text), ci.ulen(text)), LIMIT)
                assert_index_shape(self, text)
        self.assertEqual(n, 4)          # a: 1, b: 2, d: 1

    def test_replay_no_capture_logged_an_error(self):
        for name, r in self.R.items():
            self.assertEqual(r.root_errors, [], name)
            for sid, sess in r.sessions.items():
                self.assertEqual(sess["errs"], [], "%s/%s" % (name, sid))

    def test_replay_fixtures_match_the_lab_captures(self):
        """tests/fixtures/captures is a byte-for-byte copy of lab/captures/v2 (the lab evidence)."""
        if not os.path.isdir(S.LAB_CAPTURES):
            self.skipTest("lab/captures/v2 is not present")
        seen = 0
        for root, _dirs, files in os.walk(S.LAB_CAPTURES):
            for name in files:
                src = os.path.join(root, name)
                dst = os.path.join(S.CAPTURES, os.path.relpath(src, S.LAB_CAPTURES))
                self.assertTrue(os.path.isfile(dst), dst)
                self.assertEqual(S.read_fixture(src), S.read_fixture(dst), dst)
                seen += 1
        self.assertEqual(seen, 18)      # 7 payload files + 11 transcripts


def assert_index_shape(tc, text, turns_dir=None):
    """An injected index is the fixed header, the directory line, the format line and index lines - nothing else."""
    lines = text.split("\n")
    tc.assertEqual(lines[0], ci.HEADER)
    m = re.match(r"^디렉터리: (.+) \(턴 (\d+)개\)$", lines[1])
    tc.assertTrue(m, lines[1])
    if turns_dir is not None:
        tc.assertEqual(m.group(1), turns_dir)
    tc.assertIn(lines[2], ("형식: 파일 크기 | 요청 → 답변",
                           "형식: 파일 크기 | 요청 → 답변 · '접힘'은 미리보기만 생략한 구간이며 파일은 그대로 있음"))
    tc.assertGreater(len(lines), 3)
    for line in lines[3:]:
        tc.assertTrue(TURN_LINE.match(line) or FOLD_LINE.match(line), line)
    tc.assertEqual(text.count(m.group(1)), 1)
    return m.group(1), int(m.group(2))


class ProcessReplay(unittest.TestCase):
    """The captured payloads through separate hook processes: what the CLI would observe."""

    @classmethod
    def setUpClass(cls):
        cls.P = {name: S.Replay(name, via="process") for name in S.CAPTURE_NAMES}
        cls.H = {name: S.Replay(name) for name in S.CAPTURE_NAMES}

    @classmethod
    def tearDownClass(cls):
        for r in list(cls.P.values()) + list(cls.H.values()):
            r.close()

    def test_every_process_exits_zero(self):
        for name, r in self.P.items():
            self.assertEqual([p for p in r.procs if p[1] != 0], [], name)
        self.assertEqual(sum(len(r.procs) for r in self.P.values()), 80)

    def test_stdout_is_empty_outside_compaction(self):
        """Principle 2 on real payloads: UserPromptSubmit and Stop print 0 bytes."""
        for name, r in self.P.items():
            for ev, _rc, out, _err in r.procs:
                if ev != "SessionStart":
                    self.assertEqual(out, b"", "%s %s" % (name, ev))

    def test_stderr_is_empty(self):
        for name, r in self.P.items():
            self.assertEqual([p[3] for p in r.procs if p[3]], [], name)

    def test_compaction_output_is_ascii_json_with_the_documented_shape(self):
        seen = 0
        for r in self.P.values():
            for ev, _rc, out, _err in r.procs:
                if ev == "SessionStart":
                    seen += 1
                    out.decode("ascii")                 # raises if any byte is not ASCII
                    self.assertFalse(out.endswith(b"\n"))
                    self.assertLessEqual(ci.ulen(context_of(out)), LIMIT)
        self.assertEqual(seen, 4)

    def test_process_and_in_process_replays_agree(self):
        def shape(r):
            out = {}
            for sid, sess in r.sessions.items():
                out[sid] = [(t["n"], t["pid"], t["kind"], t["status"], t["nreq"], t["nans"], t["req"], t["ans"], t["bytes"])
                            for t in sess["meta"]["turns"]]
            return out
        for name in S.CAPTURE_NAMES:
            self.assertEqual(shape(self.P[name]), shape(self.H[name]), name)
            strip = lambda r: [(sid, text.replace(r.sb.base, "<BASE>")) for sid, text in r.outs]
            self.assertEqual(strip(self.P[name]), strip(self.H[name]), name)


# =============================================================================== principles
class Principles(HookCase):
    """Core principles 1-5 (report section 0)."""

    def script(self, n=3, sid=SID):
        for i in range(1, n + 1):
            self.sb.feed(ups("요청 %d: 결제 모듈을 분석해줘" % i, "p%d" % i, sid, cwd="/work/branch-%d" % (i % 2)))
            self.sb.feed(stop("안녕하세요!\n\n## 결과\n\n분석 결과 %d 입니다. 세부 내용은 다음과 같습니다." % i, "p%d" % i, sid))

    # -- 1: the model never writes
    def test_p1_injection_is_only_the_fixed_header_and_index_lines(self):
        self.script()
        text = context_of(self.sb.feed(session_start()))
        turns_dir, count = assert_index_shape(self, text, os.path.join(self.sb.sdir(SID), "turns"))
        self.assertEqual(count, 3)

    def test_p1_header_is_the_fixed_sentence_of_the_spec(self):
        with open(os.path.join(S.REPO, "docs", "phase3-report.md"), "rb") as f:
            report = f.read().decode("utf-8")
        self.assertIn('**고정 머리말**: "%s"' % ci.HEADER, report)
        self.assertEqual(S.hashlib.sha256(ci.HEADER.encode("utf-8")).hexdigest(),
                         "1f696b92cae7316f0c4be9d42bb0d9c85967939f0ca9baeb2676f2f811d9c7e9")

    def test_p1_output_carries_nothing_but_additional_context(self):
        self.script()
        obj = json.loads(self.sb.feed(session_start()))
        self.assertEqual(list(obj), ["hookSpecificOutput"])
        self.assertEqual(sorted(obj["hookSpecificOutput"]), ["additionalContext", "hookEventName"])

    # -- 2: nothing is injected outside compaction
    def test_p2_prompt_and_stop_return_no_output(self):
        self.assertIsNone(self.sb.feed(ups("질문")))
        self.assertIsNone(self.sb.feed(stop("답변")))

    def test_p2_prompt_and_stop_processes_print_zero_bytes(self):
        for payload in (ups("질문 🙂"), stop("답변 🙂"), ups("/mycmd 인자"), stop(None), ups("둘째", "p2"), stop("x", "p9")):
            cp = self.sb.run(payload)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""), payload["hook_event_name"])

    def test_p2_session_start_prints_only_for_compact(self):
        self.script()
        for source in ("startup", "resume", "clear", "fork", "", None, "COMPACT", "compact ", 1, ["compact"], NOTHING):
            cp = self.sb.run(session_start(source=source))
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""), repr(source))
        self.assertEqual(self.sb.compactions(SID), [])
        self.assertFalse(os.path.exists(os.path.join(self.sb.sdir(SID), "index.md")))
        cp = self.sb.run(session_start())
        self.assertTrue(context_of(cp.stdout).startswith(ci.HEADER))

    def test_p2_dispatch_cannot_return_text_for_prompt_or_stop(self):
        """Structural guard: whatever the handlers return, only SessionStart can reach stdout."""
        saved = ci.on_prompt, ci.on_stop
        ci.on_prompt = ci.on_stop = lambda p, info: "LEAK"
        try:
            self.assertIsNone(ci.handle(ups("x")))
            self.assertIsNone(ci.handle(stop("y")))
        finally:
            ci.on_prompt, ci.on_stop = saved

    # -- 3: the forbidden expression appears nowhere
    def test_p3_forbidden_expression_is_absent_from_the_repository(self):
        word = forbidden_word().encode("utf-8")
        hits = []
        for root, dirs, files in os.walk(S.REPO):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules", "venv")]
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as f:
                    if word in f.read():
                        hits.append(os.path.relpath(path, S.REPO))
        self.assertEqual(hits, [])

    def test_p3_forbidden_expression_is_absent_from_hook_output(self):
        self.script(40)
        text = context_of(self.sb.feed(session_start()))
        self.assertNotIn(forbidden_word(), text)
        for const in (ci.HEADER, ci.NO_ANSWER, ci.IN_FLIGHT, ci.NO_REQUEST, ci.EMPTY_REQUEST, ci.NO_TEXT, ci.TASK_NOTE,
                      ci.SEC_REQUEST, ci.SEC_REQUEST_RECOVERED, ci.SEC_REQUEST_EXTRA, ci.SEC_ANSWER, ci.SEC_ANSWER_MORE):
            self.assertNotIn(forbidden_word(), const)

    # -- 4: the path is fixed by the session id (no branch name, no cwd)
    def test_p4_directory_is_base_plus_session_id_whatever_the_cwd(self):
        self.script(4)                                   # cwd alternates between two "branch" directories
        self.sb.feed(session_start(cwd="/somewhere/else"))
        self.sb.feed(ups("압축 뒤 질문", "p9", cwd="/third/place"))
        self.assertEqual(self.sb.sessions(), [SID])
        self.assertEqual(sorted(os.listdir(self.sb.base)), [SID])
        self.assertEqual(len(self.sb.turn_files(SID)), 5)

    def test_p4_default_root_is_dot_claude_ctx_index_under_home(self):
        saved = os.environ.pop("CTX_INDEX_DIR")
        try:
            self.assertEqual(ci.base_dir(), os.path.join(S.FAKE_HOME, ".claude", "ctx-index"))
            self.assertEqual(ci.Store.__init__.__code__.co_names.count("getcwd"), 0)
        finally:
            os.environ["CTX_INDEX_DIR"] = saved

    def test_p4_default_root_is_used_by_a_real_process(self):
        env = dict(os.environ)
        env.pop("CTX_INDEX_DIR", None)
        cp = subprocess.run([sys.executable, S.HOOK], input=json.dumps(ups("기본 경로 확인", sid="default-root-check")).encode("utf-8"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self.sb.root)
        self.assertEqual((cp.returncode, cp.stdout), (0, b""))
        d = os.path.join(S.FAKE_HOME, ".claude", "ctx-index", "default-root-check")
        self.assertTrue(os.path.isfile(os.path.join(d, "turns", "0001.md")))
        self.assertEqual(os.listdir(self.sb.root), ["ctx-index"])        # nothing was written into the cwd

    def test_p4_odd_session_ids_stay_inside_the_root(self):
        odd = ["served:abc/def", "../../etc/passwd", "..", "CON", "nul.txt", "a" * 300, "세션 한글", "x\\y:z*?", " . ", "a/b"]
        for i, sid in enumerate(odd):
            self.sb.feed(ups("질문 %d" % i, "p%d" % i, sid))
        names = os.listdir(self.sb.base)
        self.assertEqual(len(names), len(odd) - 1)               # ".." and " . " are unusable: both use the fallback name
        self.assertEqual(len(self.sb.turn_files("unknown-session")), 2)
        for name in names:
            self.assertRegex(name, r"^[A-Za-z0-9._-]{1,80}$")
            self.assertNotIn(name.split(".")[0].upper(), ("CON", "PRN", "AUX", "NUL"))
            self.assertEqual(os.path.dirname(os.path.abspath(os.path.join(self.sb.base, name))), self.sb.base)
        self.assertEqual(ci.safe_session_id("served:abc/def"), ci.safe_session_id("served:abc/def"))
        self.assertNotEqual(ci.safe_session_id("a/b"), ci.safe_session_id("a_b"))
        self.assertEqual(ci.safe_session_id(SID), SID)          # ordinary ids are used as they are

    # -- 5: verbatim storage, only the index is injected
    TRICKY = [
        "평범한 한 줄",
        "여러 줄\n둘째 줄\n\n넷째 줄 (빈 줄 포함)\n",
        "CRLF 줄바꿈\r\n둘째 줄\r\n",
        "\t탭과  연속  공백   그리고 끝 공백   ",
        "emoji 🙂🚀 와 조합형 문자 é, 한자 漢字, 전각　공백",
        "```python\nprint('코드 펜스')\n```\n",
        "## ◇ 답변 · 2026-01-01T00:00:00+09:00 · 5B\n\n가짜 섹션 머리말이 본문에 들어 있음\n\n## ◇ 요청 · x\n\n끝",
        "<!-- ctx-index | turn 9999 | session x | prompt y -->",
        "\n\n앞뒤 빈 줄\n\n",
        "널 문자 \x00 와 제어 문자 \x1b[31m",
        "x" * 100000,
        "",
    ]

    def test_p5_request_and_answer_bytes_are_stored_verbatim(self):
        for i, text in enumerate(self.TRICKY):
            pid = "tricky-%02d" % i
            self.sb.feed(ups(text, pid))
            self.sb.feed(stop(text + "\n(답변) " + text if text else "답변만 있음", pid))
        self.assertEqual(len(self.sb.turn_files(SID)), len(self.TRICKY))
        for i, text in enumerate(self.TRICKY):
            secs = self.sb.sections(SID, i + 1)
            answer = text + "\n(답변) " + text if text else "답변만 있음"
            self.assertEqual(secs, [(ci.SEC_REQUEST, text.encode("utf-8")), (ci.SEC_ANSWER, answer.encode("utf-8"))], i)
            raw = self.sb.turn_bytes(SID, i + 1)
            self.assertIn(text.encode("utf-8"), raw)
            self.assertEqual(self.sb.turns(SID)[i]["bytes"], len(text.encode("utf-8")) + len(answer.encode("utf-8")))

    def test_p5_same_bytes_through_a_real_process(self):
        text = "CRLF\r\n한글 🙂\ttab  \n```\ncode\n```\n"
        self.assertEqual(self.sb.run(ups(text)).returncode, 0)
        self.assertEqual(self.sb.run(stop(text * 3)).returncode, 0)
        self.assertEqual(self.sb.sections(SID, 1), [(ci.SEC_REQUEST, text.encode("utf-8")),
                                                    (ci.SEC_ANSWER, (text * 3).encode("utf-8"))])
        self.assertNotIn(b"\r\r", self.sb.turn_bytes(SID, 1))        # no newline translation on the way to disk

    def test_p5_only_previews_are_injected(self):
        long_req = "요청 본문 " + "가나다라마바사 " * 3000 + "요청-끝-표식"
        long_ans = "답변 본문 " + "세부 근거 문단입니다. " * 5000 + "답변-끝-표식"
        self.sb.feed(ups(long_req))
        self.sb.feed(stop(long_ans))
        text = context_of(self.sb.feed(session_start()))
        self.assertNotIn("요청-끝-표식", text)
        self.assertNotIn("답변-끝-표식", text)
        self.assertLess(len(text), 600)
        self.assertIn("답변-끝-표식", self.sb.turn_text(SID, 1))
        self.assertIn("요청-끝-표식", self.sb.turn_text(SID, 1))


# =============================================================================== required item 1
class IndexDensity(HookCase):
    """Required item 1: index density and previews."""

    def test_s1_directory_once_then_file_name_and_size_per_line(self):
        for i in range(1, 6):
            self.sb.feed(ups("질문 %d" % i, "p%d" % i))
            self.sb.feed(stop("답변 %d 입니다. 내용이 이어집니다." % i, "p%d" % i))
        text = context_of(self.sb.feed(session_start()))
        turns_dir = os.path.join(self.sb.sdir(SID), "turns")
        self.assertTrue(os.path.isabs(turns_dir))
        self.assertEqual(text.count(turns_dir), 1)
        self.assertEqual(text.split("\n")[1], "디렉터리: %s (턴 5개)" % turns_dir)
        body = S.body_lines(text)
        self.assertEqual(len(body), 5)
        for i, line in enumerate(body, 1):
            self.assertTrue(line.startswith("%04d.md 0.1KB | " % i), line)
            self.assertNotIn(self.sb.base, line)
            self.assertNotIn(os.sep + "turns", line)

    def test_s1_size_column_is_the_stored_text_size(self):
        self.assertEqual([ci.fmt_size(b) for b in (0, 1, 51, 1024, 1536, 12902, 1048575, 1048576, 5 * 1048576 + 1)],
                         ["0.0KB", "0.1KB", "0.1KB", "1.0KB", "1.5KB", "12.6KB", "1024.0KB", "1.0MB", "5.0MB"])

    def test_s1_request_preview_has_no_newlines_or_markdown_and_at_most_70_chars(self):
        req = ("## 목표\n\n- **결제 모듈**의 `재시도` 로직을 [분석](http://example.com/a)하고\n"
               "- ~~오래된~~ 경로를 *정리*해줘\n\n> 인용문도 있음\n1. 번호 목록\n" + "추가 설명 " * 40)
        self.sb.feed(ups(req))
        self.sb.feed(stop("확인했습니다."))
        line = S.body_lines(context_of(self.sb.feed(session_start())))[0]
        preview = line.split(" | ", 1)[1].split(" → ")[0]
        self.assertLessEqual(len(preview), 70)
        self.assertEqual(len(preview), 70)                       # long request: cut exactly at the limit
        self.assertTrue(preview.endswith("…"))
        self.assertTrue(preview.startswith("목표 결제 모듈의 재시도 로직을 분석하고 오래된 경로를 정리해줘 인용문도 있음 번호 목록"), preview)
        for mark in ("\n", "\r", "#", "*", "`", "~~", "[", "](", ">"):
            self.assertNotIn(mark, preview)

    def test_s1_answer_preview_is_at_most_90_chars(self):
        self.sb.feed(ups("질문"))
        self.sb.feed(stop("결론부터 말씀드리면 " + "아주 긴 문장이 계속 이어집니다 " * 30))
        line = S.body_lines(context_of(self.sb.feed(session_start())))[0]
        preview = line.split(" → ", 1)[1]
        self.assertEqual(len(preview), 90)
        self.assertTrue(preview.endswith("…"))
        self.assertNotIn("\n", preview)

    def test_s1_answer_preview_skips_greeting_and_header_only_lines(self):
        cases = [
            ("안녕하세요!\n\n## 분석 결과\n\n재시도 로직은 타임아웃 불일치 때문에 중복 전송됩니다.\n\n세부", "재시도 로직은 타임아웃 불일치 때문에 중복 전송됩니다."),
            ("# 제목만 있는 첫 줄\n\n본문의 첫 문장은 여기에 있습니다.", "본문의 첫 문장은 여기에 있습니다."),
            ("네, 알겠습니다.\n\n요청하신 작업을 모두 마쳤습니다.", "요청하신 작업을 모두 마쳤습니다."),
            ("Sure!\n\nThe flake comes from a shared temp directory.", "The flake comes from a shared temp directory."),
            ("Of course.\n---\n***\nHere is the summary of the change.", "Here is the summary of the change."),
            ("네, 정리했습니다.\n\n1. 스키마 이중 기록 단계를 먼저 둡니다.", "스키마 이중 기록 단계를 먼저 둡니다."),
            ("안녕하세요! 결제 모듈의 재시도 경로를 분석했습니다.", "결제 모듈의 재시도 경로를 분석했습니다."),
            ("```python\nprint('code first')\n```\n코드 다음에 오는 설명 문장입니다.", "코드 다음에 오는 설명 문장입니다."),
            ("- [x] 완료한 항목: 테스트를 모두 통과했습니다", "완료한 항목: 테스트를 모두 통과했습니다"),
            ("> **요약**: 캐시 무효화가 쓰기 경로와 경합합니다", "요약: 캐시 무효화가 쓰기 경로와 경합합니다"),
        ]
        for text, want in cases:
            self.assertEqual(ci.answer_preview(text), want, text)

    def test_s1_answer_preview_falls_back_when_nothing_is_meaningful(self):
        self.assertEqual(ci.answer_preview("안녕하세요!"), "안녕하세요!")
        self.assertEqual(ci.answer_preview("## 제목뿐"), "제목뿐")
        self.assertEqual(ci.answer_preview("```\nonly code\n```"), "only code")
        self.assertEqual(ci.answer_preview("네."), "네.")
        self.assertEqual(ci.answer_preview(""), "")
        self.assertEqual(ci.answer_preview("\n\n   \n"), "")
        self.assertEqual(ci.answer_preview("Done."), "Done.")

    def test_s1_previews_of_huge_or_hostile_text_stay_cheap(self):
        hostile = ["가" * 300000, "x" * 500000, "__a " * 100000, "**b" * 100000, "[" * 200000, "![" * 100000,
                   "<" * 200000, "_" * 200000, "> " * 100000, "*" * 200000, "\n".join(["#"] * 50000),
                   "\n".join(["안녕하세요!"] * 20000), ("`" * 1999 + "\n") * 2000]
        t0 = time.perf_counter()
        for text in hostile:
            self.assertLessEqual(len(ci.request_preview(text)), ci.STORED_PREVIEW_CHARS)
            self.assertLessEqual(len(ci.answer_preview(text)), ci.STORED_PREVIEW_CHARS)
        self.assertLess(time.perf_counter() - t0, 20.0)

    def test_s1_special_request_previews(self):
        note = "<task-notification>\n<task-id>abc</task-id>\n<summary>Agent \"probe\" finished</summary>\n</task-notification>"
        self.assertEqual(ci.request_preview(note), '[작업 알림] Agent "probe" finished')
        self.assertEqual(ci.request_preview("<task-notification>no summary"), "[작업 알림]")
        self.assertEqual(ci.request_preview("<bash-input>echo  hi</bash-input>\n<bash-stdout>hi</bash-stdout>"), "!echo hi")
        self.assertEqual(ci.request_preview("/mycmd 인자1 인자2"), "/mycmd 인자1 인자2")

    def test_s1_counts_of_extra_requests_and_answers_fit_inside_the_limits(self):
        self.sb.feed(ups("가" * 200, "p1"))
        self.sb.feed(ups("작업 중 추가 입력", "p1"))
        self.sb.feed(stop("나" * 200, "p1"))
        self.sb.feed(stop("다" * 200, "p1", stop_hook_active=True))
        line = S.body_lines(context_of(self.sb.feed(session_start())))[0]
        req, ans = line.split(" | ", 1)[1].split(" → ")
        self.assertTrue(req.endswith("… (+1)") and len(req) == 70, req)
        self.assertTrue(ans.endswith("… (+1)") and len(ans) == 90, ans)


# =============================================================================== required item 2
class StateSync(HookCase):
    """Required item 2: state synchronisation (plus A1 attribution, A2 in-flight, A5 recovery)."""

    def test_s2_index_md_is_a_snapshot_written_only_at_compaction(self):
        index = os.path.join(self.sb.sdir(SID), "index.md")
        for i in (1, 2):
            self.sb.feed(ups("질문 %d" % i, "p%d" % i))
            self.sb.feed(stop("답변 %d 입니다. 이어지는 내용." % i, "p%d" % i))
            self.assertFalse(os.path.exists(index))              # nothing is appended per turn
        first = context_of(self.sb.feed(session_start()))
        with open(index, "rb") as f:
            self.assertTrue(f.read().decode("utf-8").startswith(first + "\n\n<!-- "))
        self.sb.feed(ups("질문 3", "p3"))
        self.sb.feed(stop("답변 3 입니다. 이어지는 내용.", "p3"))
        with open(index, "rb") as f:
            self.assertTrue(f.read().decode("utf-8").startswith(first + "\n\n<!-- "))     # untouched between compactions
        second = context_of(self.sb.feed(session_start()))
        with open(index, "rb") as f:
            snapshot = f.read().decode("utf-8")
        self.assertTrue(snapshot.startswith(second + "\n\n<!-- "))
        self.assertEqual(snapshot.count(ci.HEADER), 1)           # overwritten, not appended
        self.assertEqual(len(S.body_lines(second)), 3)

    def test_s2_meta_is_updated_in_place_by_turn_number(self):
        self.sb.feed(ups("질문 1", "p1"))
        self.assertEqual([(t["n"], t["status"], t["nans"]) for t in self.sb.turns(SID)], [(1, "open", 0)])
        self.sb.feed(ups("질문 2", "p2"))
        self.sb.feed(stop("첫 질문의 답변입니다. 늦게 도착했습니다.", "p1"))
        T = self.sb.turns(SID)
        self.assertEqual([(t["n"], t["status"], t["nans"]) for t in T], [(1, "done", 1), (2, "open", 0)])
        for key in ("n", "pid", "status", "t0", "t1", "req", "ans", "nreq", "nans", "bytes", "kind"):
            self.assertIn(key, T[0])
        self.assertRegex(T[0]["t0"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(T[0]["req"], "질문 1")
        self.assertEqual(T[0]["bytes"], len("질문 1".encode("utf-8")) + len("첫 질문의 답변입니다. 늦게 도착했습니다.".encode("utf-8")))

    def test_s2_index_is_rendered_from_current_state_at_compaction(self):
        self.sb.feed(ups("질문 1", "p1"))
        a = context_of(self.sb.feed(session_start()))
        self.assertIn("0001.md 0.1KB | 질문 1 → " + ci.NO_ANSWER, a)
        self.sb.feed(stop("뒤늦은 답변이 도착했습니다.", "p1"))
        b = context_of(self.sb.feed(session_start()))
        self.assertIn("0001.md 0.1KB | 질문 1 → 뒤늦은 답변이 도착했습니다.", b)

    def test_s2_several_stops_append_to_the_same_turn_file(self):
        self.sb.feed(ups("질문"))
        self.sb.feed(stop("첫 번째 답변입니다."))
        self.sb.feed(stop("두 번째 답변입니다.", stop_hook_active=True))
        self.sb.feed(stop("세 번째 답변입니다.", stop_hook_active=True))
        self.assertEqual(self.sb.turn_files(SID), ["0001.md"])
        self.assertEqual([label for label, _ in self.sb.sections(SID, 1)], ["요청", "답변", "답변", "답변"])
        text = self.sb.turn_text(SID, 1)
        self.assertLess(text.index("## ◇ 답변 ·"), text.index("## ◇ 답변 (이어짐 2) ·"))
        self.assertLess(text.index("## ◇ 답변 (이어짐 2) ·"), text.index("## ◇ 답변 (이어짐 3) ·"))
        (t,) = self.sb.turns(SID)
        self.assertEqual((t["nans"], t["ans"]), (3, "첫 번째 답변입니다."))
        line = S.body_lines(context_of(self.sb.feed(session_start())))[0]
        self.assertTrue(line.endswith("→ 첫 번째 답변입니다. (+2)"), line)

    def test_s2_turn_without_stop_is_shown_as_unanswered(self):
        self.sb.feed(ups("중단될 질문", "p1"))
        self.sb.feed(ups("다음 질문", "p2"))
        self.sb.feed(stop("다음 질문의 답변입니다.", "p2"))
        body = S.body_lines(context_of(self.sb.feed(session_start(pid="other"))))
        self.assertEqual(body[0], "0001.md 0.1KB | 중단될 질문 → (답변 없음/중단)")
        self.assertEqual(body[1], "0002.md 0.1KB | 다음 질문 → 다음 질문의 답변입니다.")

    def test_s2_only_the_builtin_commands_are_skipped(self):
        skipped = ["/clear", "/compact", "/help", "/status", "/cost", "/exit", "/quit", "/compact 한글 지시문: 경로 보존",
                   "  /help  ", "/CLEAR", "/Help me", "/exit\n", "\n/status"]
        recorded = ["/mycmd 인자1 인자2", "/review", "/init", "/helpme", "/clear-cache now", "/compact_all", "/status/of/build",
                    "/ help", "//help", "please run /help", "/한글명령", "/model opus", "!ls", "/"]
        for i, text in enumerate(skipped):
            self.sb.feed(ups(text, "s%d" % i))
            self.assertTrue(ci.is_builtin_command(text), text)
        self.assertEqual(self.sb.sessions(), [])                 # not even a session directory
        for i, text in enumerate(recorded):
            self.sb.feed(ups(text, "r%d" % i))
            self.assertFalse(ci.is_builtin_command(text), text)
        self.assertEqual([body.decode("utf-8") for n in range(1, len(recorded) + 1) for _l, body in self.sb.sections(SID, n)], recorded)
        self.assertEqual(ci.BUILTIN_COMMANDS, frozenset(("clear", "compact", "help", "status", "cost", "exit", "quit")))

    def test_s2_stop_without_an_open_turn_creates_a_new_turn_file(self):
        self.sb.feed(ups("질문 1", "p1"))
        self.sb.feed(stop("답변 1 입니다.", "p1"))
        self.sb.feed(stop("요청 없이 도착한 답변입니다.", "p-unknown"))
        self.assertEqual(self.sb.turn_files(SID), ["0001.md", "0002.md"])
        T = self.sb.turns(SID)
        self.assertEqual((T[1]["kind"], T[1]["nreq"], T[1]["nans"], T[1]["status"]), ("orphan", 0, 1, "done"))
        self.assertEqual(T[0]["nans"], 1)                        # the earlier turn is untouched
        body = S.body_lines(context_of(self.sb.feed(session_start())))
        self.assertEqual(body[1], "0002.md 0.1KB | (요청 미기록) → 요청 없이 도착한 답변입니다.")

    def test_s2_stop_as_first_event_of_a_session(self):
        self.sb.feed(stop("세션의 첫 이벤트가 Stop 입니다.", "p1"))
        self.assertEqual([(t["n"], t["kind"]) for t in self.sb.turns(SID)], [(1, "orphan")])

    def test_s2_input_with_agent_id_is_neither_recorded_nor_injected(self):
        for payload in (ups("서브에이전트 프롬프트", agent_id="agent-1"), stop("서브에이전트 답변", agent_id="agent-1"),
                        session_start(agent_id="agent-1")):
            cp = self.sb.run(payload)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
        self.assertEqual(os.listdir(self.sb.base), [])           # nothing at all was written
        self.sb.feed(ups("메인 스레드 질문", "p1"))
        before = (self.sb.turn_bytes(SID, 1), self.sb.meta(SID))
        for payload in (ups("서브에이전트 프롬프트", "p1", agent_id="agent-1", agent_type="general-purpose"),
                        stop("서브에이전트 답변", "p1", agent_id="agent-1"), session_start(agent_id="agent-1", pid="p1")):
            self.assertIsNone(self.sb.feed(payload))
        self.assertEqual((self.sb.turn_bytes(SID, 1), self.sb.meta(SID)), before)
        self.assertEqual(self.sb.turn_files(SID), ["0001.md"])
        self.assertEqual(self.sb.compactions(SID), [])
        self.assertFalse(os.path.exists(os.path.join(self.sb.sdir(SID), "index.md")))
        self.sb.feed(stop("메인 스레드 답변입니다.", "p1", agent_id=""))      # empty value = main thread
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 1)

    def test_s2_duplicate_stop_is_not_appended(self):
        self.sb.feed(ups("질문"))
        for _ in range(3):
            self.sb.feed(stop("같은 답변이 여러 번 도착합니다."))
        self.sb.feed(stop("  같은 답변이 여러 번 도착합니다.\n"))             # same text apart from outer whitespace
        (t,) = self.sb.turns(SID)
        self.assertEqual(t["nans"], 1)
        self.assertEqual(self.sb.turn_text(SID, 1).count("같은 답변이 여러 번 도착합니다."), 1)
        self.assertEqual([e["act"] for e in self.sb.events(SID)], ["new_turn", "answer"] + ["duplicate_answer"] * 3)

    def test_s2_fallback_text_equal_to_the_previous_record_is_dropped(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [S.tx_user("질문 1", "p1"), S.tx_assistant("트랜스크립트에만 있는 답변입니다.", "m1")])
        self.sb.feed(ups("질문 1", "p1", transcript_path=tx))
        self.sb.feed(stop(None, "p1", transcript_path=tx))                    # fallback finds the text
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 1)
        self.sb.feed(stop(None, "p1", transcript_path=tx))                    # same stale text again
        self.sb.feed(stop("", "p1", transcript_path=tx))
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 1)
        self.sb.feed(ups("질문 2", NOTHING, transcript_path=tx))              # a later turn, version without prompt_id
        self.sb.feed(stop(None, NOTHING, transcript_path=tx))                 # fallback = text of the previous record
        T = self.sb.turns(SID)
        self.assertEqual([(t["n"], t["nans"], t["status"]) for t in T], [(1, 1, "done"), (2, 0, "done")])
        self.assertEqual(self.sb.turn_text(SID, 2).count("답변"), 0)

    # -- versions without prompt_id: the open/done rule of the spec
    def test_s2_open_done_rule_without_prompt_id(self):
        self.sb.feed(ups("질문 1", NOTHING))
        self.sb.feed(stop("답변 1 입니다.", NOTHING))
        self.sb.feed(stop("다른 훅이 막아서 이어진 답변입니다.", NOTHING, stop_hook_active=True))
        self.sb.feed(ups("질문 2", NOTHING))
        self.sb.feed(ups("질문 3", NOTHING))                                   # no Stop for 2
        self.sb.feed(stop("답변 3 입니다.", NOTHING))
        self.sb.feed(stop("열린 턴 없이 온 답변입니다.", NOTHING))
        self.sb.feed(stop("열린 턴 없이 온 답변입니다.", NOTHING))             # repeated Stop: no second orphan
        T = self.sb.turns(SID)
        self.assertEqual([(t["n"], t["status"], t["nreq"], t["nans"], t["kind"]) for t in T],
                         [(1, "done", 1, 2, "user"), (2, "open", 1, 0, "user"), (3, "done", 1, 1, "user"), (4, "done", 0, 1, "orphan")])
        body = S.body_lines(context_of(self.sb.feed(session_start())))
        self.assertTrue(body[1].endswith("→ (답변 없음/중단)"))

    # -- A1: attribution by prompt_id
    def test_a1_answers_follow_the_prompt_id_not_the_arrival_order(self):
        self.sb.feed(ups("Q1 느린 질문", "A"))
        self.sb.feed(ups("Q2 작업 중 입력", "A"))                # typed while A runs: carries A's id
        self.sb.feed(stop("Q1 의 답변입니다. 충분히 깁니다.", "A"))
        self.sb.feed(stop("Q2 의 답변입니다. 충분히 깁니다.", "B"))      # queued prompt ran as its own turn
        T = self.sb.turns(SID)
        self.assertEqual([(t["pid"], t["nreq"], t["nans"]) for t in T], [("A", 2, 1), ("B", 0, 1)])
        self.assertIn("Q1 의 답변", self.sb.turn_text(SID, 1))
        self.assertNotIn("Q2 의 답변", self.sb.turn_text(SID, 1))
        self.assertIn("Q2 의 답변", self.sb.turn_text(SID, 2))
        self.assertEqual([label for label, _ in self.sb.sections(SID, 1)], ["요청", "추가 요청", "답변"])

    def test_a1_late_stop_reaches_an_older_turn(self):
        self.sb.feed(ups("첫째", "A"))
        self.sb.feed(ups("둘째", "B"))
        self.sb.feed(ups("셋째", "C"))
        self.sb.feed(stop("첫째의 답변이 가장 늦게 왔습니다.", "A"))
        self.assertEqual([(t["pid"], t["nans"], t["status"]) for t in self.sb.turns(SID)],
                         [("A", 1, "done"), ("B", 0, "open"), ("C", 0, "open")])

    # -- A2: the turn in flight during auto compaction
    def test_a2_in_flight_turn_and_boundary(self):
        self.sb.feed(ups("끝난 질문", "p1"))
        self.sb.feed(stop("끝난 답변입니다. 내용입니다.", "p1"))
        self.sb.feed(ups("자동 압축 도중의 질문", "p2"))
        body = S.body_lines(context_of(self.sb.feed(session_start(pid="p2"))))
        self.assertEqual(body[1], "0002.md 0.1KB | 자동 압축 도중의 질문 → (진행 중)")
        self.assertEqual([(c["last_turn"], c["last_open"]) for c in self.sb.compactions(SID)], [(2, True)])
        self.sb.feed(stop("압축 뒤에 도착한 답변입니다.", "p2"))
        self.assertEqual(self.sb.turns(SID)[1]["nans"], 1)
        body = S.body_lines(context_of(self.sb.feed(session_start(pid="manual-compact"))))
        self.assertEqual(body[1], "0002.md 0.1KB | 자동 압축 도중의 질문 → 압축 뒤에 도착한 답변입니다.")
        self.assertEqual(self.sb.compactions(SID)[1]["last_open"], False)

    def test_a2_interrupted_turn_is_not_called_in_flight(self):
        self.sb.feed(ups("Esc 로 중단된 질문", "p1"))
        body = S.body_lines(context_of(self.sb.feed(session_start(pid="p-of-the-compact-command"))))
        self.assertEqual(body[0], "0001.md 0.1KB | Esc 로 중단된 질문 → (답변 없음/중단)")
        body = S.body_lines(context_of(self.sb.feed(session_start(pid=NOTHING))))
        self.assertTrue(body[0].endswith(ci.NO_ANSWER))

    # -- A5: requests of turns that started without UserPromptSubmit
    def test_a5_orphan_stop_recovers_its_request_from_the_transcript(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [
            S.tx_user("질문 1", "prompt-A"), S.tx_assistant("답변 1", "m1"),
            S.tx_user("<bash-input>git status</bash-input>", "prompt-B", promptSource=None),
            S.tx_user("<bash-stdout>clean</bash-stdout><bash-stderr></bash-stderr>", "prompt-B", promptSource=None),
            S.tx_assistant("작업 트리가 깨끗합니다. 변경이 없습니다.", "m2")])
        self.sb.feed(ups("질문 1", "prompt-A", transcript_path=tx))
        self.sb.feed(stop("답변 1", "prompt-A", transcript_path=tx))
        self.sb.feed(stop("작업 트리가 깨끗합니다. 변경이 없습니다.", "prompt-B", transcript_path=tx))
        T = self.sb.turns(SID)
        self.assertEqual((T[1]["kind"], T[1]["req"], T[1]["nreq"], T[1]["nans"]), ("orphan", "!git status", 1, 1))
        secs = self.sb.sections(SID, 2)
        self.assertEqual(secs[0], ("요청", "<bash-input>git status</bash-input>\n<bash-stdout>clean</bash-stdout><bash-stderr></bash-stderr>".encode("utf-8")))
        self.assertIn("## ◇ 요청 (트랜스크립트에서 복원) ·", self.sb.turn_text(SID, 2))

    def test_a5_recovery_ignores_meta_summary_and_tool_result_entries(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [
            S.tx_user("요약 본문", "prompt-Q", isCompactSummary=True),
            S.tx_user("<local-command-caveat>메타</local-command-caveat>", "prompt-Q", isMeta=True),
            S.tx_user("서브에이전트 쪽 항목", "prompt-Q", isSidechain=True),
            S.tx_user("대기열에서 꺼낸 실제 질문", "prompt-Q", promptSource="queued"),
            S.tx_assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}], "m1"),
            S.tx_user([{"type": "tool_result", "tool_use_id": "t1", "content": "out"}], "prompt-Q", promptSource=None),
            S.tx_user("어시스턴트 응답 뒤의 항목은 요청이 아님", "prompt-Q"),
            S.tx_assistant("대기열 질문의 답변입니다. 끝.", "m2")])
        self.sb.feed(stop("대기열 질문의 답변입니다. 끝.", "prompt-Q", transcript_path=tx))
        self.assertEqual(self.sb.sections(SID, 1)[0], ("요청", "대기열에서 꺼낸 실제 질문".encode("utf-8")))

    def test_a5_prompt_typed_during_an_unseen_turn_creates_that_turn(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [S.tx_user("대기열에서 실행 중인 Q2", "prompt-B", promptSource="queued")])
        self.sb.feed(ups("Q5 실행 중에 입력", "prompt-B", transcript_path=tx))
        (t,) = self.sb.turns(SID)
        self.assertEqual((t["kind"], t["nreq"], t["req"]), ("recovered", 2, "대기열에서 실행 중인 Q2"))
        self.assertEqual([(label, body.decode("utf-8")) for label, body in self.sb.sections(SID, 1)],
                         [("요청", "대기열에서 실행 중인 Q2"), ("추가 요청", "Q5 실행 중에 입력")])

    def test_a5_fresh_prompt_is_not_mistaken_for_a_running_turn(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [S.tx_user("이전 질문", "prompt-A"), S.tx_assistant("이전 답변", "m1")])
        self.sb.feed(ups("새 질문", "prompt-B", transcript_path=tx))                  # B is not in the transcript yet
        S.write_transcript(tx, [S.tx_user("같은 문구", "prompt-C")])
        self.sb.feed(ups("같은 문구", "prompt-C", transcript_path=tx))                # already there, but it is this very prompt
        self.assertEqual([(t["kind"], t["nreq"]) for t in self.sb.turns(SID)], [("user", 1), ("user", 1)])

    def test_a5_unrecoverable_request_is_labelled_not_invented(self):
        self.sb.feed(stop("요청을 찾을 수 없는 답변입니다.", "Z", transcript_path=os.path.join(self.sb.root, "missing.jsonl")))
        body = S.body_lines(context_of(self.sb.feed(session_start())))
        self.assertEqual(body[0], "0001.md 0.1KB | (요청 미기록) → 요청을 찾을 수 없는 답변입니다.")

    def test_a5_task_notification_is_an_auto_turn(self):
        note = "<task-notification>\n<task-id>t1</task-id>\n<summary>Agent \"indexer\" finished</summary>\n<result>ok</result>\n</task-notification>"
        self.sb.feed(ups(note, "N"))
        self.sb.feed(stop("알림을 확인했습니다. 결과를 반영합니다.", "N"))
        (t,) = self.sb.turns(SID)
        self.assertEqual((t["kind"], t["req"]), ("auto", '[작업 알림] Agent "indexer" finished'))
        self.assertEqual(self.sb.sections(SID, 1)[0], ("요청", note.encode("utf-8")))       # the full notification is kept

    def test_empty_prompt_and_textless_answer_labels(self):
        self.sb.feed(ups("", "p1"))
        self.sb.feed(stop("   ", "p1"))
        self.sb.feed(ups("   \n", "p2"))
        self.sb.feed(stop("---", "p2"))
        body = S.body_lines(context_of(self.sb.feed(session_start())))
        self.assertEqual(body[0], "0001.md 0.0KB | (빈 요청) → (답변 없음/중단)")
        self.assertEqual(body[1], "0002.md 0.1KB | (빈 요청) → ---")


# =============================================================================== required item 3
def render(turns, prev, minimal=None, inflight=None, turns_dir=S.WIN_DIR, limit=None):
    return ci.render_index(turns, prev, turns_dir, inflight, limit=limit, minimal=minimal)


def summary(text, info):
    full, folds = S.full_lines(text), S.fold_lines(text)
    return (info["stage"], len(text), len(full), info["folded"], full[0][:7] if full else "-", full[-1][:7] if full else "-",
            folds[0] if len(folds) == 1 else len(folds))


class Folding(HookCase):
    """Required item 3 (two-stage folding), A3 (fold only as much as needed), A4 (stage 2c and the
    hard cut), A7 (header lines) and the cap of completion criterion b. Port of lab/proto/sim_fold.py."""

    def pinned(self):
        if S.generator_fingerprint() != S.GENERATOR_FINGERPRINT:
            self.skipTest("random.Random.choice() differs on this Python: the pinned numbers do not apply "
                          "(the cap and shape tests still run)")

    def test_s3_defaults(self):
        self.assertEqual((ci.MAX_CONTEXT_CHARS, ci.REQ_PREVIEW_CHARS, ci.ANS_PREVIEW_CHARS, ci.FIRST_COMPACTION_FOLD_TURNS,
                          ci.SMALL_TURN_BYTES), (6000, 70, 90, 5, 500))
        self.assertIs(ci.STAGE1_MINIMAL, True)                   # A3 as approved

    # ---- PART 2-A / 2-B of the lab simulation, recomputed for the approved behaviour (A3 on)
    def test_s3_scenarios_with_pinned_numbers(self):
        self.pinned()
        b = lambda n, open_=False: {"last_turn": n, "last_open": open_}
        rows = [
            # label, turns, previous boundary, (stage, chars, full lines, folded turns, first kept, last kept, fold line | count)
            ("first compaction, 12 turns", 12, None, ("full", 1791, 12, 0, "0001.md", "0012.md", 0)),
            ("first compaction, 40 turns", 40, None, ("full", 5819, 40, 0, "0001.md", "0040.md", 0)),
            ("first compaction, 41 turns", 41, None, ("full", 6000, 41, 0, "0001.md", "0041.md", 0)),
            ("first compaction, 42 turns", 42, None, ("1", 5884, 40, 2, "0001.md", "0040.md", "0041.md~0042.md 25.2KB (2턴 접힘)")),
            ("first compaction, 43 turns", 43, None, ("1", 5884, 40, 3, "0001.md", "0040.md", "0041.md~0043.md 35.7KB (3턴 접힘)")),
            ("first compaction, 44 turns", 44, None, ("1", 5884, 40, 4, "0001.md", "0040.md", "0041.md~0044.md 35.8KB (4턴 접힘)")),
            ("first compaction, 45 turns", 45, None, ("1", 5884, 40, 5, "0001.md", "0040.md", "0041.md~0045.md 35.8KB (5턴 접힘)")),
            ("first compaction, 46 turns", 46, None, ("2a", 3664, 41, 5, "0001.md", "0041.md", "0042.md~0046.md 23.2KB (5턴 접힘)")),
            ("first compaction, 48 turns", 48, None, ("2a", 3864, 43, 5, "0001.md", "0043.md", "0044.md~0048.md 10.7KB (5턴 접힘)")),
            ("first compaction, 70 turns", 70, None, ("2a", 5401, 65, 5, "0001.md", "0065.md", "0066.md~0070.md 12.8KB (5턴 접힘)")),
            ("first compaction, 79 turns", 79, None, ("2a", 5979, 74, 5, "0001.md", "0074.md", "0075.md~0079.md 24.1KB (5턴 접힘)")),
            ("first compaction, 80 turns", 80, None, ("2b", 5997, 68, 12, "0001.md", "0075.md", 7)),
            ("first compaction, 88 turns", 88, None, ("2b", 5986, 54, 34, "0003.md", "0082.md", 20)),
            ("first compaction, 89 turns", 89, None, ("2c", 5921, 52, 37, "0003.md", "0082.md", 22)),
            ("first compaction, 110 turns", 110, None, ("2c", 5924, 52, 58, "0003.md", "0082.md", 22)),
            ("first compaction, 300 turns", 300, None, ("2c", 5923, 52, 248, "0003.md", "0082.md", 22)),
            ("2nd (boundary 40), 58 turns", 58, b(40), ("1", 5885, 40, 18, "0001.md", "0040.md", "0041.md~0058.md 88.5KB (18턴 접힘)")),
            ("2nd (boundary 40, in flight), 58", 58, b(40, True), ("1", 5885, 40, 18, "0001.md", "0040.md", "0041.md~0058.md 88.5KB (18턴 접힘)")),
            ("2nd (boundary 40), 140 turns", 140, b(40), ("1", 5888, 40, 100, "0001.md", "0040.md", "0041.md~0140.md 593.8KB (100턴 접힘)")),
            ("3rd (boundary 140), 400 turns", 400, b(140), ("2c", 5923, 52, 348, "0003.md", "0082.md", 22)),
            ("boundary recorded with 0 turns, 60", 60, b(0), ("2a", 4645, 55, 5, "0001.md", "0055.md", "0056.md~0060.md 19.0KB (5턴 접힘)")),
            ("2nd (boundary 3), 45 turns", 45, b(3), ("1", 5884, 40, 5, "0001.md", "0040.md", "0041.md~0045.md 35.8KB (5턴 접힘)")),
            ("2nd (boundary 20), 120 turns", 120, b(20), ("1", 5887, 40, 80, "0001.md", "0040.md", "0041.md~0120.md 459.4KB (80턴 접힘)")),
        ]
        for label, n, prev, want in rows:
            self.assertEqual(summary(*render(S.make_turns(n), prev)), want, label)

    def test_s3_stage_transitions_with_pinned_numbers(self):
        self.pinned()
        seen, prev_stage = [], None
        for n in range(1, 401):
            text, info = render(S.make_turns(n), None)
            self.assertLessEqual(max(len(text), ci.ulen(text)), LIMIT, n)
            if info["stage"] != prev_stage:
                seen.append((n, info["stage"], len(text), info["folded"]))
                prev_stage = info["stage"]
        self.assertEqual(seen, [(1, "full", 246, 0), (42, "1", 5884, 2), (46, "2a", 3664, 5), (80, "2b", 5997, 12), (89, "2c", 5921, 37)])

    # ---- PART 2-D: the literal wording of the spec vs. A3
    def test_a3_spec_literal_versus_as_needed_with_pinned_numbers(self):
        self.pinned()
        b = lambda n: {"last_turn": n, "last_open": False}
        rows = [  # turns, boundary, spec-literal (stage, chars, full lines, folded), as needed (...)
            (40, None, ("full", 5819, 40, 0), ("full", 5819, 40, 0)),
            (42, None, ("1", 5341, 37, 5), ("1", 5884, 40, 2)),
            (45, None, ("1", 5884, 40, 5), ("1", 5884, 40, 5)),
            (48, None, ("2a", 3864, 43, 5), ("2a", 3864, 43, 5)),
            (45, b(3), ("1", 522, 3, 42), ("1", 5884, 40, 5)),
            (58, b(40), ("1", 5885, 40, 18), ("1", 5885, 40, 18)),
            (120, b(20), ("1", 2849, 20, 100), ("1", 5887, 40, 80)),
        ]
        for n, prev, spec, needed in rows:
            self.assertEqual(summary(*render(S.make_turns(n), prev, minimal=False))[:4], spec, (n, prev, "spec"))
            self.assertEqual(summary(*render(S.make_turns(n), prev, minimal=True))[:4], needed, (n, prev, "needed"))

    def test_a3_stage1_folds_the_newest_turns_of_its_segment_and_no_more_than_needed(self):
        rnd = random.Random(7)
        checked = 0
        for case in range(300):
            n = rnd.randint(30, 160)
            turns = S.make_turns(n, seed=case, small_ratio=rnd.random())
            prev = None if case % 3 == 0 else {"last_turn": rnd.randint(1, n), "last_open": case % 2 == 0}
            text, info = render(turns, prev)
            if info["stage"] != "1":
                continue
            checked += 1
            if prev is None:
                segment = [t["n"] for t in turns[-5:]]
            else:
                segment = [t["n"] for t in turns if t["n"] >= prev["last_turn"] + (0 if prev["last_open"] else 1)]
            k = info["folded"]
            self.assertTrue(1 <= k <= len(segment))
            folds = S.fold_lines(text)
            self.assertEqual(len(folds), 1)                                    # one line for the folded run
            newest = sorted(segment)[-k:]
            self.assertTrue(folds[0].startswith("%04d.md" % newest[0]))
            self.assertIn("%04d.md " % newest[-1] if k > 1 else "(접힘)", folds[0] + " ")
            # minimal: folding one turn fewer would not fit
            fewer = ci.build(turns, set(newest[1:]), 70, 90, S.WIN_DIR, None)
            self.assertGreater(ci.ulen(fewer), LIMIT)
            self.assertLessEqual(ci.ulen(text), LIMIT)
        self.assertGreater(checked, 30)

    def test_s3_stage2a_halves_the_previews(self):
        text, info = render(S.make_turns(60), None)
        self.assertEqual((info["stage"], info["preview"]), ("2a", [35, 45]))
        for line in S.full_lines(text):
            req, ans = line.split(" | ", 1)[1].split(" → ")
            self.assertLessEqual(len(req), 35)
            self.assertLessEqual(len(ans), 45)

    def test_s3_stage2b_folds_small_turns_first_and_keeps_early_large_turns(self):
        turns = S.make_turns(84)
        text, info = render(turns, None)
        self.assertEqual(info["stage"], "2b")
        by_n = dict((t["n"], t) for t in turns)
        shown = set(int(line[:4]) for line in S.full_lines(text))
        hidden = set(by_n) - shown
        segment = set(t["n"] for t in turns[-5:])
        self.assertTrue(segment <= hidden)
        extra = hidden - segment
        self.assertTrue(extra)
        self.assertTrue(all(by_n[n]["bytes"] < ci.SMALL_TURN_BYTES for n in extra))
        large_early = [t["n"] for t in turns[:30] if t["bytes"] >= ci.SMALL_TURN_BYTES]
        self.assertTrue(large_early and set(large_early) <= shown)             # early analysis turns keep their lines
        biggest_hidden = max(by_n[n]["bytes"] for n in extra)
        smallest_shown_small = [by_n[n]["bytes"] for n in shown if by_n[n]["bytes"] < ci.SMALL_TURN_BYTES]
        if smallest_shown_small:
            self.assertLessEqual(biggest_hidden, min(smallest_shown_small))    # smallest first

    def test_a4_stage2c_extends_the_fold_from_the_newest_turn_backwards(self):
        turns = S.make_turns(300)
        text, info = render(turns, None)
        self.assertEqual(info["stage"], "2c")
        self.assertLessEqual(ci.ulen(text), LIMIT)
        shown = sorted(int(line[:4]) for line in S.full_lines(text))
        large = [t["n"] for t in turns if t["bytes"] >= ci.SMALL_TURN_BYTES]
        self.assertEqual(shown, large[:len(shown)])                            # the oldest large turns are the ones kept
        self.assertTrue(S.body_lines(text)[-1].endswith("턴 접힘)"))
        self.assertEqual(info["folded"] + len(shown), 300)

    def test_a4_hard_cut_when_the_header_alone_does_not_fit(self):
        long_dir = "C:\\" + "x" * 7000 + "\\turns"
        text, info = render(S.make_turns(50), None, turns_dir=long_dir)
        self.assertEqual((info["stage"], len(text), ci.ulen(text)), ("cut", 6000, 6000))
        self.assertTrue(text.startswith(ci.HEADER))
        emoji_dir = "C:\\" + "😀" * 4000 + "\\turns"
        text, info = render(S.make_turns(3), None, turns_dir=emoji_dir)
        self.assertEqual(info["stage"], "cut")
        self.assertLessEqual(ci.ulen(text), LIMIT)
        text.encode("utf-8")                                                   # no surrogate was split

    def test_a4_hard_cut_through_the_real_hook(self):
        """The cap holds for the JSON actually printed, even with an absurd storage root."""
        deep = os.path.join(self.sb.root, *(["d" * 100] * 6))
        if os.name == "nt":
            deep = os.path.join(self.sb.root, "d" * 100)                       # stay under MAX_PATH on Windows
        saved = ci.MAX_CONTEXT_CHARS
        ci.MAX_CONTEXT_CHARS = 200                                             # smaller than the header + path
        os.environ["CTX_INDEX_DIR"] = deep
        try:
            ci.handle(ups("질문"))
            ci.handle(stop("답변입니다. 내용."))
            text = context_of(ci.handle(session_start()))
        finally:
            ci.MAX_CONTEXT_CHARS = saved
            os.environ["CTX_INDEX_DIR"] = self.sb.base
        self.assertLessEqual(ci.ulen(text), 200)

    def test_b_cap_holds_for_utf16_heavy_previews(self):
        emoji = "😀🙂🚀🔥🧪📦🛠️" * 40
        turns = S.make_turns(120)
        for t in turns:
            t["req"], t["ans"] = emoji[:ci.STORED_PREVIEW_CHARS], emoji[:ci.STORED_PREVIEW_CHARS]
        text, info = render(turns, None)
        self.assertLessEqual(ci.ulen(text), LIMIT)
        self.assertLess(len(text), ci.ulen(text))                # measured in UTF-16 units, not code points
        self.assertEqual(ci.ulen("a😀한"), 4)

    def test_b_cap_stress_3000_random_sessions(self):
        """PART 2-C: 3,000 random sessions (1 to 3,000 turns; Hangul, emoji, one very long line, long
        paths, random boundaries); length checked in code points and in UTF-16 units."""
        rnd = random.Random(20261126)
        worst, stages = 0, {}
        emoji = "😀🙂🚀🔥🧪📦🛠️" * 40
        long_req = ci.request_preview("가" * 200000)
        long_ans = ci.answer_preview("x" * 300000)
        self.assertEqual((len(long_req), len(long_ans)), (240, 240))
        slowest = 0.0
        for case in range(3000):
            n = rnd.choice([1, 2, 5, 6, 30, 36, 37, 50, 80, 120, 300, 700, 1500, 3000]) if case % 5 == 0 else rnd.randint(1, 260)
            turns = S.make_turns(n, seed=case, small_ratio=rnd.random())
            mode = case % 6
            for t in turns:
                if mode == 1:          # emoji-only previews (2 UTF-16 units per char)
                    t["req"], t["ans"] = emoji[:ci.STORED_PREVIEW_CHARS], emoji[:ci.STORED_PREVIEW_CHARS]
                elif mode == 2:        # single very long line
                    t["req"], t["ans"] = long_req, long_ans
                elif mode == 3 and rnd.random() < 0.3:   # interrupted / unrecorded
                    t["nans"], t["ans"] = 0, ""
                    if rnd.random() < 0.3:
                        t["req"], t["nreq"] = "", 0
                elif mode == 4:
                    t["nreq"], t["nans"] = rnd.randint(1, 12), rnd.randint(1, 12)
            d = S.WIN_DIR if mode != 5 else "C:\\" + "\\".join(["아주긴디렉터리이름%02d" % i for i in range(20)]) + "\\turns"
            prev = None if rnd.random() < 0.4 else {"last_turn": rnd.randint(0, n), "last_open": rnd.random() < 0.3}
            t0 = time.perf_counter()
            text, info = ci.render_index(turns, prev, d, minimal=bool(case % 2))
            slowest = max(slowest, time.perf_counter() - t0)
            length = max(len(text), ci.ulen(text))
            self.assertLessEqual(length, LIMIT, (case, n, info))
            self.assertTrue(text.startswith(ci.HEADER))
            self.assertEqual(text.count(d), 1)
            for line in S.body_lines(text):
                self.assertTrue(re.match(r"^\d{4,}\.md", line), line[:60])
            stages[info["stage"]] = stages.get(info["stage"], 0) + 1
            worst = max(worst, length)
        self.assertEqual(sum(stages.values()), 3000)
        if S.generator_fingerprint() == S.GENERATOR_FINGERPRINT:
            self.assertEqual(stages, {"1": 493, "2a": 337, "2b": 468, "2c": 964, "full": 738})     # as in the lab report
            self.assertEqual(worst, 6000)
        self.assertLess(slowest, 5.0)

    def test_b_cap_stress_default_mode_and_odd_limits(self):
        rnd = random.Random(42)
        for case in range(600):
            n = rnd.randint(1, 400)
            turns = S.make_turns(n, seed=10000 + case, small_ratio=rnd.random())
            prev = None if rnd.random() < 0.3 else {"last_turn": rnd.randint(0, n + 3), "last_open": rnd.random() < 0.5}
            inflight = "p%d" % n if rnd.random() < 0.3 else None
            if inflight:
                turns[-1]["nans"], turns[-1]["ans"], turns[-1]["status"] = 0, "", "open"
            text, info = render(turns, prev, inflight=inflight)
            self.assertLessEqual(max(len(text), ci.ulen(text)), LIMIT, (case, info))
            self.assertEqual(info["utf16"], ci.ulen(text))
            self.assertEqual(info["chars"], len(text))
        turns = S.make_turns(50)
        for limit in (0, 1, 10, 150, 200, 300, 1000, 5999, 6001, 100000):
            text, info = render(turns, None, limit=limit)
            self.assertLessEqual(ci.ulen(text), limit, limit)
        self.assertEqual(render([], None), ("", {"stage": "empty", "turns": 0, "folded": 0, "preview": [70, 90], "chars": 0, "utf16": 0}))

    def test_s3_malformed_boundary_records_do_not_break_rendering(self):
        turns = S.make_turns(60)
        for prev in ({}, {"last_turn": None}, {"last_turn": "40"}, {"last_turn": -5}, {"last_turn": True},
                     {"last_turn": 10 ** 9}, {"last_turn": 40.5}, {"last_turn": 40, "last_open": "yes"}):
            text, info = render(turns, prev)
            self.assertLessEqual(ci.ulen(text), LIMIT, prev)
            self.assertIn(info["stage"], ("1", "2a", "2b", "2c"))

    # ---- A7: the two lines after the fixed header
    def test_a7_header_lines(self):
        text, _ = render(S.make_turns(3), None)
        lines = text.split("\n")
        self.assertEqual(lines[0], ci.HEADER)
        self.assertEqual(lines[1], "디렉터리: %s (턴 3개)" % S.WIN_DIR)
        self.assertEqual(lines[2], "형식: 파일 크기 | 요청 → 답변")
        text, _ = render(S.make_turns(60), None)
        lines = text.split("\n")
        self.assertEqual(lines[1], "디렉터리: %s (턴 60개)" % S.WIN_DIR)
        self.assertEqual(lines[2], "형식: 파일 크기 | 요청 → 답변 · '접힘'은 미리보기만 생략한 구간이며 파일은 그대로 있음")

    # ---- PART 2-E: the whole flow through the hook
    def feed_turn(self, i, rnd, raw):
        small = rnd.random() < 0.3
        req = rnd.choice(S.REQ_SMALL) if small else rnd.choice(S.REQ_BIG) + " (작업 #%d)" % i
        ans = rnd.choice(S.ANS_SMALL) if small else rnd.choice(S.ANS_BIG)
        pid = "pid-%04d" % i
        self.assertIsNone(self.sb.feed(ups(req, pid, cwd="/w/branch-%d" % (i % 3))))
        self.assertIsNone(self.sb.feed(stop(ans, pid)))
        raw[i] = (req, ans)

    def fixed_dir_numbers(self):
        """(stage, chars, folded) the next compaction would give with the fixed Windows-style directory;
        the real numbers depend on the length of the temporary directory."""
        comps = self.sb.compactions(SID)
        text, info = render(self.sb.turns(SID), comps[-1] if comps else None)
        return info["stage"], len(text), info["folded"]

    def test_s3_flow_boundary_is_read_before_rendering_and_recorded_after(self):
        rnd, raw, fixed = random.Random(7), {}, []
        comp_path = os.path.join(self.sb.sdir(SID), "compactions.jsonl")
        for i in range(1, 61):
            self.feed_turn(i, rnd, raw)
        self.assertFalse(os.path.exists(comp_path))
        fixed.append(self.fixed_dir_numbers())
        t1 = context_of(self.sb.feed(session_start(pid="compact-1")))
        c = self.sb.compactions(SID)
        self.assertEqual((len(c), c[-1]["last_turn"], c[-1]["turns"], c[-1]["chars"]), (1, 60, 60, len(t1)))
        # first compaction: no previous boundary -> the newest 5 are the stage-1 segment
        self.assertRegex(t1, r"0056\.md~0060\.md .*\(5턴 접힘\)")
        for i in range(61, 91):
            self.feed_turn(i, rnd, raw)
        fixed.append(self.fixed_dir_numbers())
        t2 = context_of(self.sb.feed(session_start(pid="compact-2")))
        c = self.sb.compactions(SID)
        self.assertEqual((len(c), c[-1]["last_turn"]), (2, 90))
        # second compaction used the boundary recorded by the first (60), not its own (90):
        # everything after 60 is the segment, and the turns folded last time have their lines back
        self.assertRegex(t2, r"0061\.md~0090\.md .*\(30턴 접힘\)")
        self.assertIn("\n0060.md ", t2)
        self.assertNotIn("0056.md~0060.md", t2)
        for i in range(91, 103):
            self.feed_turn(i, rnd, raw)
        fixed.append(self.fixed_dir_numbers())
        t3 = context_of(self.sb.feed(session_start(pid="compact-3")))
        m = re.search(r"(\d{4})\.md~0102\.md .*\((\d+)턴 접힘\)", t3)
        self.assertTrue(m and int(m.group(1)) <= 91)
        for text in (t1, t2, t3):
            self.assertLessEqual(max(len(text), ci.ulen(text)), LIMIT)
            assert_index_shape(self, text, os.path.join(self.sb.sdir(SID), "turns"))
        self.assertEqual(self.sb.sessions(), [SID])              # one directory although the cwd kept changing
        self.assertEqual(len(self.sb.turn_files(SID)), 102)
        self.assertEqual(sorted(os.listdir(self.sb.sdir(SID))), ["compactions.jsonl", "events.jsonl", "index.md", "meta.json", "turns"])
        for i in (1, 37, 102):
            body = self.sb.turn_text(SID, i)
            self.assertIn(raw[i][0], body)
            self.assertIn(raw[i][1], body)
        with open(os.path.join(self.sb.sdir(SID), "index.md"), "rb") as f:
            self.assertTrue(f.read().decode("utf-8").startswith(t3))
        self.assertEqual([x["stage"] for x in self.sb.compactions(SID)][:2], ["2a", "2a"])
        self.assertEqual([x["folded"] for x in self.sb.compactions(SID)][:2], [5, 30])
        if S.generator_fingerprint() == S.GENERATOR_FINGERPRINT:
            self.assertEqual(fixed, [("2a", 4240, 5), ("2a", 4690, 30), ("2c", 5998, 49)])

    def test_s3_first_compaction_folds_at_most_the_newest_five(self):
        for n in (42, 43, 44, 45):
            text, info = render(S.make_turns(n, seed=3), None)
            if info["stage"] != "1":
                continue
            hidden = set(range(1, n + 1)) - set(int(line[:4]) for line in S.full_lines(text))
            self.assertTrue(hidden <= set(range(n - 4, n + 1)), (n, hidden))

    def test_s3_in_flight_boundary_turn_belongs_to_the_next_segment(self):
        turns = S.make_turns(58)
        text, info = render(turns, {"last_turn": 40, "last_open": True}, minimal=False)
        self.assertEqual(info["segment"], "since turn 40 (19 turns)")
        self.assertRegex(text, r"\n0040\.md~0058\.md .*\(19턴 접힘\)")
        text, info = render(turns, {"last_turn": 40, "last_open": False}, minimal=False)
        self.assertEqual(info["segment"], "since turn 41 (18 turns)")

    def test_s3_compaction_without_new_turns_still_fits(self):
        turns = S.make_turns(120)
        text, info = render(turns, {"last_turn": 120, "last_open": False})      # empty segment: nothing to fold in stage 1
        self.assertLessEqual(ci.ulen(text), LIMIT)
        self.assertIn(info["stage"], ("2a", "2b", "2c"))

    def test_s3_empty_session_injects_nothing_but_records_the_boundary(self):
        self.assertIsNone(self.sb.feed(session_start()))
        self.assertEqual([(c["last_turn"], c["turns"], c["chars"], c["stage"]) for c in self.sb.compactions(SID)], [(0, 0, 0, "empty")])
        cp = self.sb.run(session_start())
        self.assertEqual((cp.returncode, cp.stdout), (0, b""))


# =============================================================================== required item 4
class Utf8AndFallbacks(HookCase):
    """Required item 4: explicit UTF-8 everywhere, transcript fallback for the answer, safe fallbacks."""

    ASCII_ENV = {"LC_ALL": "C", "LANG": "C", "LANGUAGE": "C", "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0",
                 "PYTHONLEGACYWINDOWSSTDIO": "1"}

    def test_s4_hangul_emoji_and_crlf_survive_an_ascii_locale(self):
        req = "한글 요청 🙂\r\n둘째 줄 — 전각　공백"
        ans = "안녕하세요!\n\n## 결과\n\n한글 답변 🚀 입니다. emoji 와 CRLF\r\n를 그대로 둡니다."
        for payload in (ups(req), stop(ans)):
            cp = self.sb.run(payload, env=self.ASCII_ENV)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
        self.assertEqual(self.sb.sections(SID, 1), [("요청", req.encode("utf-8")), ("답변", ans.encode("utf-8"))])
        cp = self.sb.run(session_start(), env=self.ASCII_ENV)
        self.assertEqual((cp.returncode, cp.stderr), (0, b""))
        self.assertTrue(all(b < 128 for b in cp.stdout))                       # ASCII-escaped JSON
        text = context_of(cp.stdout)
        self.assertIn("한글 요청 🙂 둘째 줄 — 전각 공백 → 한글 답변 🚀 입니다. emoji 와 CRLF", text)
        for name in ("meta.json", "index.md", "compactions.jsonl", "events.jsonl"):
            with open(os.path.join(self.sb.sdir(SID), name), "rb") as f:
                f.read().decode("utf-8")                                       # every file is valid UTF-8
        self.assertEqual(self.sb.turns(SID)[0]["req"], "한글 요청 🙂 둘째 줄 — 전각 공백")
        self.assertEqual(self.sb.all_errors(), [])

    def test_s4_stdin_is_read_as_bytes_ascii_escaped_or_raw_utf8(self):
        raw = json.dumps(ups("이스케이프된 입력 🙂", "p1"), ensure_ascii=True).encode("ascii")
        self.assertEqual(self.sb.run(raw, env=self.ASCII_ENV).returncode, 0)
        raw = json.dumps(ups("원시 UTF-8 입력 🙂", "p2"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(self.sb.run(raw, env=self.ASCII_ENV).returncode, 0)
        self.assertEqual([t["req"] for t in self.sb.turns(SID)], ["이스케이프된 입력 🙂", "원시 UTF-8 입력 🙂"])

    def test_s4_bom_and_utf16_input_are_tolerated(self):
        body = json.dumps(ups("BOM 이 붙은 입력", "p1"), ensure_ascii=False)
        self.assertEqual(self.sb.run(b"\xef\xbb\xbf" + body.encode("utf-8")).returncode, 0)
        body = json.dumps(ups("UTF-16 입력 🙂", "p2"), ensure_ascii=False)
        self.assertEqual(self.sb.run(body.encode("utf-16")).returncode, 0)     # with BOM, as PowerShell would write
        self.assertEqual([t["req"] for t in self.sb.turns(SID)], ["BOM 이 붙은 입력", "UTF-16 입력 🙂"])
        self.assertEqual(self.sb.all_errors(), [])

    def test_s4_lone_surrogates_cannot_break_storage(self):
        raw = b'{"hook_event_name":"UserPromptSubmit","session_id":"' + SID.encode() + b'","prompt_id":"p1","prompt":"half \\ud83d pair"}'
        cp = self.sb.run(raw)
        self.assertEqual((cp.returncode, cp.stdout), (0, b""))
        self.assertEqual(self.sb.sections(SID, 1), [("요청", "half \ufffd pair".encode("utf-8"))])
        self.sb.run(stop("ok answer text"))
        cp = self.sb.run(session_start())
        self.assertIn("half \ufffd pair", context_of(cp.stdout))

    def test_s4_files_are_written_in_binary_mode(self):
        self.sb.feed(ups("줄1\n줄2"))
        self.sb.feed(stop("답1\n답2"))
        self.sb.feed(session_start())
        for name in ("meta.json", "index.md", "compactions.jsonl", "events.jsonl", os.path.join("turns", "0001.md")):
            with open(os.path.join(self.sb.sdir(SID), name), "rb") as f:
                self.assertNotIn(b"\r\n", f.read(), name)                      # no newline translation, also on Windows

    # -- Stop without last_assistant_message: last assistant text from the transcript
    def answer_from(self, entries, pid="p1", **stop_kw):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, entries)
        self.sb.feed(ups("질문", pid, transcript_path=tx))
        self.sb.feed(stop(None, pid, transcript_path=tx, **stop_kw))
        secs = [body.decode("utf-8") for label, body in self.sb.sections(SID, 1) if label == "답변"]
        return secs

    def test_s4_missing_answer_is_taken_from_the_transcript(self):
        entries = [S.tx_user("질문", "p1"),
                   S.tx_assistant("도구를 쓰기 전의 설명입니다.", "m1"),
                   S.tx_assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}], "m1"),
                   S.tx_user([{"type": "tool_result", "tool_use_id": "t1", "content": "out"}], "p1", promptSource=None),
                   S.tx_assistant("트랜스크립트의 마지막 답변입니다. 🙂", "m2")]
        self.assertEqual(self.answer_from(entries), ["트랜스크립트의 마지막 답변입니다. 🙂"])
        self.assertEqual(self.sb.events(SID)[-1]["src"], "transcript")

    def test_s4_empty_or_blank_answer_also_uses_the_transcript(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [S.tx_user("질문", "p1"), S.tx_assistant("폴백으로 찾은 답변입니다.", "m1")])
        for i, value in enumerate(("", "   \n\t", None, [], [{"type": "text", "text": "  "}])):
            sid = "blank-%d" % i
            self.sb.feed(ups("질문", "p1", sid, transcript_path=tx))
            self.sb.feed(stop(None, "p1", sid, transcript_path=tx, last_assistant_message=value))
            self.assertEqual(self.sb.sections(sid, 1)[1], ("답변", "폴백으로 찾은 답변입니다.".encode("utf-8")), repr(value))

    def test_s4_answer_blocks_of_one_message_are_joined(self):
        entries = [S.tx_user("질문", "p1"), S.tx_assistant("첫 블록입니다.", "m9"), S.tx_assistant("둘째 블록입니다.", "m9")]
        self.assertEqual(self.answer_from(entries), ["첫 블록입니다.\n둘째 블록입니다."])

    def test_s4_fallback_never_takes_another_prompts_answer(self):
        entries = [S.tx_user("이전 질문", "p0"), S.tx_assistant("이전 질문의 답변입니다.", "m0"),
                   S.tx_user("질문", "p1"), S.tx_assistant("", "m1")]
        self.assertEqual(self.answer_from(entries), [])
        (t,) = self.sb.turns(SID)
        self.assertEqual((t["nans"], t["status"]), (0, "done"))

    def test_s4_fallback_skips_synthetic_error_and_sidechain_messages(self):
        entries = [S.tx_user("질문", "p1"), S.tx_assistant("진짜 답변입니다.", "m1"),
                   S.tx_assistant("서브에이전트의 말", "m2", isSidechain=True),
                   S.tx_assistant("API Error: 529", "m3", isApiErrorMessage=True),
                   {"type": "assistant", "isSidechain": False, "message": {"id": "m4", "model": "<synthetic>", "content": [{"type": "text", "text": "No response requested."}]}}]
        self.assertEqual(self.answer_from(entries), ["진짜 답변입니다."])

    def test_s4_fallback_reads_only_the_tail_and_widens_when_needed(self):
        tx = os.path.join(self.sb.root, "big.jsonl")
        filler = {"type": "attachment", "attachment": {"type": "blob", "data": "z" * 4000}}
        noise = S.tx_user([{"type": "tool_result", "tool_use_id": "t", "content": "y" * 4000}], "p1", promptSource=None)
        with open(tx, "wb") as f:
            f.write(json.dumps(S.tx_user("질문", "p1"), ensure_ascii=False).encode("utf-8") + b"\n")
            f.write(json.dumps(S.tx_assistant("3MiB 앞에 있는 답변입니다.", "m1"), ensure_ascii=False).encode("utf-8") + b"\n")
            line = json.dumps(filler).encode("utf-8") + b"\n" + json.dumps(noise).encode("utf-8") + b"\n"
            f.write(line * (3 * 1024 * 1024 // len(line) + 1))
        self.assertGreater(os.path.getsize(tx), ci.TAIL_BYTES)
        self.sb.feed(ups("질문", "p1", transcript_path=tx))
        self.sb.feed(stop(None, "p1", transcript_path=tx))
        self.assertEqual(self.sb.sections(SID, 1)[1], ("답변", "3MiB 앞에 있는 답변입니다.".encode("utf-8")))

    def test_s4_unusable_transcripts_degrade_to_no_answer(self):
        garbage = os.path.join(self.sb.root, "garbage.jsonl")
        with open(garbage, "wb") as f:
            f.write(b"\xff\xfe\x00not json\n{\"type\":\"assistant\"\n{\"type\":\"assistant\",\"message\":7}\n[1,2]\n\"type\":\"user\"\n")
        empty = os.path.join(self.sb.root, "empty.jsonl")
        open(empty, "wb").close()
        paths = [garbage, empty, self.sb.root, os.path.join(self.sb.root, "missing.jsonl"), "", None, 12, ["x"], {"a": 1},
                 "\x00bad", "C:\\nonexistent\\t.jsonl", "/nonexistent/t.jsonl"]
        for i, tp in enumerate(paths):
            sid = "tx-%02d" % i
            for payload in (ups("질문", "p1", sid, transcript_path=tp), stop(None, "p1", sid, transcript_path=tp),
                            stop(None, "p2", sid, transcript_path=tp), ups("질문 2", "p3", sid, transcript_path=tp)):
                cp = self.sb.run(payload)
                self.assertEqual((cp.returncode, cp.stdout), (0, b""), repr(tp))
            self.assertEqual([(t["n"], t["nans"]) for t in self.sb.turns(sid)], [(1, 0), (2, 0)], repr(tp))
        self.assertEqual(self.sb.all_errors(), [])

    # -- uncertain schema fields
    def test_s4_session_id_fallbacks(self):
        tx = os.path.join(self.sb.root, "abcdef12-0000-4000-8000-000000000000.jsonl")
        self.sb.feed(ups("질문", "p1", NOTHING, transcript_path=tx))
        self.sb.feed(ups("질문", "p1", "", transcript_path="C:\\Users\\me\\.claude\\projects\\C--w\\win-style-id.jsonl"))
        self.sb.feed(ups("질문", "p1", None, transcript_path=NOTHING))
        self.sb.feed(ups("질문", "p2", 12345, transcript_path=""))
        self.assertEqual(self.sb.sessions(), ["abcdef12-0000-4000-8000-000000000000", "unknown-session", "win-style-id"])
        self.assertEqual(len(self.sb.turn_files("unknown-session")), 2)

    def test_s4_payload_fields_of_unexpected_types(self):
        odd_prompts = [None, 5, 1.5, True, ["a", {"type": "text", "text": "블록 텍스트"}, 7], {"text": "객체"}, NOTHING]
        for i, value in enumerate(odd_prompts):
            cp = self.sb.run(ups(value, "p%d" % i))
            self.assertEqual((cp.returncode, cp.stdout), (0, b""), repr(value))
        got = [body.decode("utf-8") for n in range(1, len(odd_prompts) + 1) for _l, body in self.sb.sections(SID, n)]
        self.assertEqual(got, ["", "5", "1.5", "true", "a\n블록 텍스트", '{"text": "객체"}', ""])
        self.assertEqual(len([e for e in self.sb.errors(SID) if e["where"] == "schema"]), len(odd_prompts))
        for value in (5, {"text": "객체 답변"}, [{"type": "text", "text": "블록 답변입니다."}], True):
            cp = self.sb.run(stop(None, "p0", last_assistant_message=value))
            self.assertEqual((cp.returncode, cp.stdout), (0, b""), repr(value))
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 4)
        for pid in (None, "", 7, ["p"], {"id": 1}):
            cp = self.sb.run(stop("prompt_id 타입이 이상한 답변 %r" % (pid,), pid))
            self.assertEqual((cp.returncode, cp.stdout), (0, b""), repr(pid))
        cp = self.sb.run(session_start(pid=["x"]))
        self.assertEqual(cp.returncode, 0)
        self.assertLessEqual(ci.ulen(context_of(cp.stdout)), LIMIT)


# =============================================================================== criterion a
class Robustness(HookCase):
    """Completion criterion a: whatever happens, the hook process exits 0, prints nothing it
    should not, and records the exception in errors.jsonl (where there is a place to write)."""

    def check(self, data, base=None, want_error=None, **kw):
        cp = self.sb.run(data, base=base, **kw)
        self.assertEqual(cp.returncode, 0, (data if isinstance(data, bytes) else "payload", cp.stderr))
        self.assertEqual(cp.stdout, b"")
        self.assertEqual(cp.stderr, b"")
        if want_error is not None:
            errs = self.sb.all_errors() if base is None else S.read_jsonl(os.path.join(base, "errors.jsonl"))
            self.assertTrue([e for e in errs if e["where"] == want_error], (want_error, errs))
        return cp

    def test_a_empty_and_blank_input(self):
        for i, data in enumerate((b"", b" ", b"\n", b"\r\n\t ", b"\xef\xbb\xbf")):
            self.check(data, want_error="main")
            self.assertEqual(len(self.sb.errors()), i + 1)
        self.assertIn("JSONDecodeError", self.sb.errors()[0]["error"])
        self.assertEqual(self.sb.sessions(), [])

    def test_a_broken_json(self):
        broken = [b"{", b'{"hook_event_name":', b'{"hook_event_name":"Stop"', b"{'single': 'quotes'}", b"not json at all",
                  b'{"a":1}{"b":2}', b'{"prompt":"unterminated', b"\x00\x00\x00", b'{"hook_event_name":"Stop",}', b"<html>",
                  json.dumps(ups("잘린 입력")).encode("utf-8")[:-7], b"[" * 100000, b'{"a":' * 50000]
        for i, data in enumerate(broken):
            self.check(data, want_error="main")
            self.assertEqual(len(self.sb.errors()), i + 1, data[:30])
        self.assertEqual(self.sb.sessions(), [])

    def test_a_json_that_is_not_an_object(self):
        for i, data in enumerate((b"null", b"true", b"42", b'"text"', b"[]", b'[{"hook_event_name":"Stop"}]', b"1.5e3")):
            self.check(data, want_error="main")
            self.assertEqual(len(self.sb.errors()), i + 1)
            self.assertIn("not a JSON object", self.sb.errors()[-1]["error"])

    def test_a_non_utf8_bytes(self):
        cp949 = '{"hook_event_name":"UserPromptSubmit","session_id":"s-cp949","prompt_id":"p1","prompt":"한글 프롬프트"}'.encode("cp949")
        self.check(cp949, want_error="stdin")                                  # decodable with replacement: recorded + flagged
        (body,) = [b for _l, b in self.sb.sections("s-cp949", 1)]
        self.assertIn("\ufffd", body.decode("utf-8"))
        self.assertIn("not valid UTF-8", self.sb.errors("s-cp949")[0]["error"])
        for data in (b"\xff\xfe\xfd", b"\x80\x81\x82\x83", b'{"hook_event_name":"Stop","session_id":"\xff"}' + b"\xc3",
                     os.urandom(4096), b"\xff\xfe" + b"\x00\xd8" * 7, b"\xfe\xff\xd8"):
            self.check(data)
        self.assertGreaterEqual(len(self.sb.all_errors()), 6)

    def test_a_missing_fields(self):
        base = ups("필드 누락 시험", "p1")
        for key in list(base):
            payload = dict(base)
            del payload[key]
            payload["session_id"] = payload.get("session_id", "no-session-id-key")
            self.check(payload)
        for payload in ({}, {"hook_event_name": "UserPromptSubmit"}, {"hook_event_name": "Stop"}, {"hook_event_name": "SessionStart"},
                        {"hook_event_name": "SessionStart", "source": "compact"}, {"session_id": SID}, {"prompt": "이벤트 이름 없음"},
                        {"hook_event_name": None, "session_id": SID}, {"hook_event_name": 3}, {"hook_event_name": ["Stop"]},
                        {"hook_event_name": "PreCompact", "session_id": SID, "trigger": "auto"},
                        {"hook_event_name": "stop", "session_id": SID}, {"hook_event_name": "SessionEnd", "session_id": SID}):
            if payload.get("source") == "compact":
                cp = self.sb.run(payload)                        # no session_id: the fallback session, which has turns by now
                self.assertEqual((cp.returncode, cp.stderr), (0, b""))
                self.assertIn("unknown-session", context_of(cp.stdout))
            else:
                self.check(payload)
        schema = [e for e in self.sb.all_errors() if e["where"] == "schema"]
        self.assertTrue(any("hook_event_name" in e["error"] for e in schema))

    def test_a_wrong_types_everywhere(self):
        values = [None, True, 0, -1, 3.5, "", "x", [], [1, "a", None], {}, {"k": [1, {"z": None}]}, "가" * 10000]
        events = (ups("타입 오류 시험", "p1"), stop("타입 오류 답변입니다.", "p1"), session_start(pid="p1"))
        n = 0
        for base in events:
            for key in list(base) + ["agent_id", "unexpected_new_field"]:
                if key == "hook_event_name":
                    continue
                for value in values:
                    payload = dict(base)
                    payload[key] = value
                    if key == "session_id" and not isinstance(value, str):
                        payload["transcript_path"] = ""
                    cp = self.sb.run(payload)
                    n += 1
                    self.assertEqual(cp.returncode, 0, (key, value, cp.stderr))
                    self.assertEqual(cp.stderr, b"", (key, value))
                    if base["hook_event_name"] != "SessionStart" or payload.get("source") != "compact" or payload.get("agent_id"):
                        self.assertEqual(cp.stdout, b"", (key, value))
                    elif cp.stdout:
                        self.assertLessEqual(ci.ulen(context_of(cp.stdout)), LIMIT)
        self.assertGreater(n, 250)
        self.assertEqual([e for e in self.sb.all_errors() if e["where"] == "main"], [])     # handled, not crashed

    def test_a_fuzzed_real_payloads_in_process(self):
        """2,000 mutations of the captured payloads through main() itself (stdin/stdout swapped)."""
        rows = []
        for name in S.CAPTURE_NAMES:
            rows += [json.loads(line.decode("utf-8"))["payload"]
                     for line in S.read_fixture(os.path.join(S.CAPTURES, name, "payloads.jsonl")).split(b"\n") if line.strip()]
        rnd = random.Random(1234)
        junk = [None, True, False, 0, 1, -7, 2.5, "", " ", "x", "compact", "Stop", "\ud800", "\x00", "가" * 5000, [], [None], ["a", 1],
                {}, {"type": "text", "text": "t"}, [{"type": "text", "text": "블록"}], self.sb.root, "/nonexistent/x.jsonl"]
        real = (sys.stdin, sys.stdout)

        class Std(object):
            def __init__(self, data=b""):
                self.buffer = io.BytesIO(data)

        outputs = 0
        try:
            for case in range(2000):
                p = dict(rnd.choice(rows))
                p["session_id"] = "fuzz-%d" % (case % 7)
                p["transcript_path"] = ""
                for _ in range(rnd.randint(1, 4)):
                    op = rnd.random()
                    key = rnd.choice(list(p) + ["agent_id", "prompt", "last_assistant_message", "source", "stop_hook_active"])
                    if op < 0.25:
                        p.pop(key, None)
                    else:
                        p[key] = rnd.choice(junk)
                data = json.dumps(p, ensure_ascii=bool(case % 2)).encode("utf-8", "surrogatepass" if case % 2 == 0 else "strict")
                if case % 97 == 0:
                    data = data[:rnd.randint(0, len(data))]
                sys.stdin, sys.stdout = Std(data), Std()
                ci.main()                                        # must never raise
                out = sys.stdout.buffer.getvalue()
                if out:
                    outputs += 1
                    self.assertEqual((p.get("hook_event_name"), p.get("source")), ("SessionStart", "compact"), p)
                    self.assertFalse(p.get("agent_id"))
                    self.assertLessEqual(ci.ulen(context_of(out)), LIMIT)
        finally:
            sys.stdin, sys.stdout = real
        self.assertGreater(outputs, 5)

    def test_a_closed_or_broken_standard_streams(self):
        if os.name == "nt":
            self.skipTest("closing inherited descriptors needs a POSIX shell")
        payload = json.dumps(ups("표준 입출력 시험")).encode("utf-8")
        env = dict(os.environ, CTX_INDEX_DIR=self.sb.base)
        quoted = "'%s' '%s'" % (sys.executable, S.HOOK)
        for script in (quoted + " <&-", quoted + " >&-", quoted + " 2>&-", quoted + " <&- >&- 2>&-", quoted + " > /dev/full"):
            cp = subprocess.run(["/bin/sh", "-c", script], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(cp.returncode, 0, (script, cp.stderr))
        self.sb.feed(stop("답변입니다. 내용."))
        compact = json.dumps(session_start()).encode("utf-8")
        for script in (quoted + " >&-", quoted + " > /dev/full", quoted + " | true"):      # output that cannot be written
            cp = subprocess.run(["/bin/sh", "-c", script], input=compact, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            self.assertEqual(cp.returncode, 0, (script, cp.stderr))

    def test_a_large_and_deep_input(self):
        big = "큰 입력 " * 700000                                              # about 5 MB of UTF-8
        self.check(ups(big, "p1"))
        self.check(stop(big, "p1"))
        self.assertEqual(self.sb.sections(SID, 1)[0][1], big.encode("utf-8"))
        self.assertEqual(self.sb.all_errors(), [])
        deep = ('{"hook_event_name":"UserPromptSubmit","session_id":"deep","x":' + "[" * 200000 + "]" * 200000 + "}").encode("ascii")
        self.check(deep)                                                       # RecursionError or accepted - never a crash
        nested = {"hook_event_name": "Stop", "session_id": SID, "prompt_id": "p9", "last_assistant_message": [[[[["깊은 값"]]]]]}
        self.check(nested)

    # -- damaged meta.json
    def seed(self):
        self.sb.feed(ups("첫 질문", "p1"))
        self.sb.feed(stop("첫 답변입니다. 내용입니다.", "p1"))
        self.sb.feed(ups("둘째 질문", "p2"))
        return os.path.join(self.sb.sdir(SID), "meta.json")

    def test_a_corrupt_meta_json_is_rebuilt_from_the_turn_files(self):
        good = None
        damaged = [b"", b"\x00\x00\x00\x00", b"{", b"not json", b"[]", b"null", b'{"turns": 5}', b'{"turns": "x"}', b'{"schema": 1}',
                   os.urandom(300), b"\xff\xfe" + "meta".encode("utf-16-le")]
        for i, blob in enumerate(damaged):
            with self.subTest(blob=blob[:12]):
                self.sb.destroy()
                os.makedirs(self.sb.base)
                meta_path = self.seed()
                good = good or self.sb.meta(SID)
                with open(meta_path, "wb") as f:
                    f.write(blob)
                self.check(stop("둘째 답변입니다. 손상 뒤에 도착했습니다.", "p2"), want_error="meta")
                T = self.sb.turns(SID)
                self.assertEqual([(t["n"], t["pid"], t["status"], t["nreq"], t["nans"]) for t in T],
                                 [(1, "p1", "done", 1, 1), (2, "p2", "done", 1, 1)])
                self.assertEqual([t["req"] for t in T], ["첫 질문", "둘째 질문"])
                self.assertEqual(T[0]["ans"], "첫 답변입니다. 내용입니다.")
                self.assertEqual(T[0]["bytes"], good["turns"][0]["bytes"])
                self.assertTrue([n for n in os.listdir(self.sb.sdir(SID)) if n.startswith("meta.json.bad-")])
                cp = self.sb.run(session_start())
                self.assertEqual(len(S.body_lines(context_of(cp.stdout))), 2)

    def test_a_truncated_meta_json(self):
        meta_path = self.seed()
        with open(meta_path, "rb") as f:
            data = f.read()
        for cut_at in (1, len(data) // 3, len(data) // 2, len(data) - 2):
            with open(meta_path, "wb") as f:
                f.write(data[:cut_at])
            self.check(ups("손상 뒤의 질문 %d" % cut_at, "q%d" % cut_at), want_error="meta")
        self.assertEqual([t["n"] for t in self.sb.turns(SID)], [1, 2, 3, 4, 5, 6])
        self.assertEqual(len(self.sb.turn_files(SID)), 6)

    def test_a_valid_json_meta_with_damaged_records(self):
        meta_path = self.seed()
        meta = self.sb.meta(SID)
        meta["turns"][0].update({"bytes": "big", "nans": None, "nreq": -3, "req": 17, "ans": ["x"], "status": 5, "kind": None, "ah": 9})
        meta["turns"] += [{"n": "3"}, {"n": 2, "req": "duplicate number"}, "junk", None, {"n": True}, {"n": 0}, {"n": -1},
                          {"n": 7, "pid": {"x": 1}}]
        meta["tx"], meta["last_ans"] = "far", 12
        with open(meta_path, "wb") as f:
            f.write(json.dumps(meta).encode("utf-8"))
        self.check(stop("둘째 답변입니다. 내용입니다.", "p2"))
        cp = self.sb.run(session_start())
        self.assertEqual(cp.returncode, 0)
        body = S.body_lines(context_of(cp.stdout))
        self.assertEqual(body, ["0001.md 0.0KB | (요청 미기록) → (답변 없음/중단)", "0002.md 0.1KB | 둘째 질문 → 둘째 답변입니다. 내용입니다.",
                                "0007.md 0.0KB | (요청 미기록) → (답변 없음/중단)"])
        self.assertEqual([e for e in self.sb.all_errors() if e["where"] == "main"], [])

    def test_a_meta_json_replaced_by_a_directory(self):
        meta_path = self.seed()
        os.remove(meta_path)
        os.mkdir(meta_path)
        self.check(stop("둘째 답변입니다. 내용입니다.", "p2"), want_error="meta")
        self.assertTrue(os.path.isfile(meta_path))
        self.assertEqual([(t["n"], t["nans"]) for t in self.sb.turns(SID)], [(1, 1), (2, 1)])

    def test_a_damaged_side_files(self):
        self.seed()
        d = self.sb.sdir(SID)
        with open(os.path.join(d, "compactions.jsonl"), "wb") as f:
            f.write(b'\xff\xfe\n{"last_turn": "x"}\nnot json\n[1]\n{"last_turn": 1, "last_open": false}\n{"last_turn": tru\n')
        with open(os.path.join(d, "events.jsonl"), "wb") as f:
            f.write(b"\x00garbage without newline")
        with open(os.path.join(d, "index.md"), "wb") as f:
            f.write(os.urandom(64))
        cp = self.sb.run(session_start())
        self.assertEqual((cp.returncode, cp.stderr), (0, b""))
        self.assertEqual(len(S.body_lines(context_of(cp.stdout))), 2)
        self.assertEqual(ci.Store(SID).last_compaction()["last_turn"], 2)
        os.remove(os.path.join(d, "index.md"))
        os.mkdir(os.path.join(d, "index.md"))                                  # the snapshot cannot be written
        os.remove(os.path.join(d, "compactions.jsonl"))
        os.mkdir(os.path.join(d, "compactions.jsonl"))                         # nor the boundary
        cp = self.sb.run(session_start())
        self.assertEqual((cp.returncode, cp.stderr), (0, b""))
        self.assertEqual(len(S.body_lines(context_of(cp.stdout))), 2)          # bookkeeping failed, the injection did not
        self.assertEqual(sorted(e["where"] for e in self.sb.errors(SID)), ["compactions", "index"])

    # -- storage that cannot be written
    def test_a_storage_root_under_a_regular_file(self):
        blocker = os.path.join(self.sb.root, "blocker")
        with open(blocker, "wb") as f:
            f.write(b"x")
        base = os.path.join(blocker, "ctx-index")
        for payload in (ups("쓸 수 없는 경로"), stop("답변입니다. 내용."), session_start(), b"", b"{"):
            cp = self.sb.run(payload, base=base)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
        self.assertTrue(os.path.isfile(blocker))

    def test_a_storage_root_is_a_regular_file(self):
        base = os.path.join(self.sb.root, "root-is-a-file")
        with open(base, "wb") as f:
            f.write(b"x")
        for payload in (ups("쓸 수 없는 경로"), stop("답변입니다. 내용."), session_start()):
            cp = self.sb.run(payload, base=base)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
        with open(base, "rb") as f:
            self.assertEqual(f.read(), b"x")

    def test_a_session_directory_is_a_regular_file(self):
        with open(self.sb.sdir(SID), "wb") as f:
            f.write(b"x")
        for payload in (ups("세션 디렉터리 자리에 파일"), stop("답변입니다. 내용."), session_start()):
            self.check(payload, want_error="main")
        self.assertEqual(len(self.sb.errors()), 3)                             # recorded at the root instead
        self.assertEqual(self.sb.errors()[0]["session"], SID)

    def test_a_turns_directory_is_a_regular_file(self):
        os.makedirs(self.sb.sdir(SID))
        with open(os.path.join(self.sb.sdir(SID), "turns"), "wb") as f:
            f.write(b"x")
        for payload in (ups("turns 자리에 파일"), stop("답변입니다. 내용."), session_start()):
            self.check(payload, want_error="main")
        self.assertEqual(len(self.sb.errors(SID)), 3)

    def test_a_read_only_storage(self):
        if os.name == "nt" or os.geteuid() == 0:
            self.skipTest("permission bits are not enforced here (Windows, or running as root)")
        self.sb.feed(ups("읽기 전용이 되기 전의 질문", "p1"))
        d = self.sb.sdir(SID)
        os.chmod(os.path.join(d, "turns"), 0o500)
        os.chmod(d, 0o500)
        t0 = time.perf_counter()
        try:
            for payload in (ups("읽기 전용", "p2"), stop("답변입니다. 내용.", "p1")):
                cp = self.sb.run(payload)
                self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
            cp = self.sb.run(session_start())                                  # reading still works: the index is injected
            self.assertEqual((cp.returncode, cp.stderr), (0, b""))
            self.assertEqual(S.body_lines(context_of(cp.stdout)), ["0001.md 0.1KB | 읽기 전용이 되기 전의 질문 → (답변 없음/중단)"])
        finally:
            os.chmod(d, 0o700)
            os.chmod(os.path.join(d, "turns"), 0o700)
        self.assertLess(time.perf_counter() - t0, 3 * ci.LOCK_WAIT_SECS)      # no full lock wait per call
        where = [e["where"] for e in self.sb.errors()]                         # recorded at the root: the session directory is read-only
        self.assertEqual(where.count("main"), 2)                               # the two writes that could not happen
        self.assertTrue({"index", "compactions"} <= set(where))                # bookkeeping of the compaction
        self.assertEqual(len(self.sb.turn_files(SID)), 1)                      # the earlier turn is intact

    def test_a_errors_log_itself_cannot_be_written(self):
        os.mkdir(os.path.join(self.sb.base, "errors.jsonl"))
        for data in (b"", b"{", b"null"):
            cp = self.sb.run(data)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))

    # -- lock contention
    def test_a_parallel_hook_processes_do_not_lose_turns(self):
        env = dict(os.environ, CTX_INDEX_DIR=self.sb.base)
        procs = []
        for i in range(12):
            data = json.dumps(ups("동시 요청 %02d" % i, "par-%02d" % i), ensure_ascii=False).encode("utf-8")
            p = subprocess.Popen([sys.executable, S.HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            p.stdin.write(data)
            procs.append(p)
        for p in procs:
            p.stdin.close()
        for p in procs:
            out, err = p.stdout.read(), p.stderr.read()
            p.stdout.close()
            p.stderr.close()
            self.assertEqual((p.wait(60), out, err), (0, b"", b""))
        T = self.sb.turns(SID)
        self.assertEqual(sorted(t["n"] for t in T), list(range(1, 13)))
        self.assertEqual(sorted(t["req"] for t in T), ["동시 요청 %02d" % i for i in range(12)])
        self.assertEqual(len(self.sb.turn_files(SID)), 12)
        self.assertFalse(os.path.exists(os.path.join(self.sb.sdir(SID), ".lock")))
        self.assertEqual(self.sb.all_errors(), [])
        procs = []
        for i in range(12):                                                    # answers race each other as well
            data = json.dumps(stop("동시 답변 %02d 입니다." % i, "par-%02d" % i), ensure_ascii=False).encode("utf-8")
            p = subprocess.Popen([sys.executable, S.HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            p.stdin.write(data)
            procs.append(p)
        for p in procs:
            p.stdin.close()
        for p in procs:
            p.stdout.read(), p.stderr.read()
            p.stdout.close()
            p.stderr.close()
            self.assertEqual(p.wait(60), 0)
        T = self.sb.turns(SID)
        self.assertEqual([t["nans"] for t in T], [1] * 12)
        for t in T:
            self.assertEqual(t["ans"], "동시 답변 %s 입니다." % t["req"][-2:])
        self.assertEqual(self.sb.all_errors(), [])

    def test_a_lock_held_by_someone_else(self):
        self.sb.feed(ups("잠금 전의 질문", "p1"))
        lock = os.path.join(self.sb.sdir(SID), ".lock")
        with open(lock, "wb") as f:
            f.write(b"99999")                                                  # a live foreign lock
        t0 = time.perf_counter()
        self.check(stop("잠금을 기다린 뒤 기록한 답변입니다.", "p1"), want_error="lock")
        waited = time.perf_counter() - t0
        self.assertGreaterEqual(waited, ci.LOCK_WAIT_SECS * 0.9)
        self.assertLess(waited, ci.LOCK_WAIT_SECS + 10)
        self.assertTrue(os.path.exists(lock))                                  # not ours: left alone
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 1)                     # recorded anyway
        self.assertIn("timeout waiting", self.sb.errors(SID)[0]["error"])
        t0 = time.perf_counter()
        cp = self.sb.run(session_start())
        self.assertEqual(cp.returncode, 0)
        self.assertIn("잠금을 기다린 뒤 기록한 답변입니다.", context_of(cp.stdout))

    def test_a_stale_lock_is_broken(self):
        self.sb.feed(ups("오래된 잠금", "p1"))
        lock = os.path.join(self.sb.sdir(SID), ".lock")
        with open(lock, "wb") as f:
            f.write(b"12345")
        old = time.time() - ci.LOCK_STALE_SECS - 60
        os.utime(lock, (old, old))
        self.check(stop("오래된 잠금을 치우고 기록한 답변입니다.", "p1"))
        self.assertFalse(os.path.exists(lock))
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 1)
        self.assertEqual(self.sb.all_errors(), [])               # no lock timeout was recorded: it did not wait

    def test_a_lock_is_released_when_the_handler_fails(self):
        saved = ci.Store.save
        ci.Store.save = lambda self, meta: (_ for _ in ()).throw(OSError("disk full (simulated)"))
        try:
            with self.assertRaises(OSError):
                ci.handle(ups("저장 실패"))
        finally:
            ci.Store.save = saved
        self.assertFalse(os.path.exists(os.path.join(self.sb.sdir(SID), ".lock")))
        self.assertEqual(self.sb.events(SID)[-1]["act"], "error")
        self.assertEqual(self.sb.events(SID)[-1]["err"], "OSError")

    def test_a_exception_inside_a_handler_is_recorded_with_traceback(self):
        probe = os.path.join(self.sb.root, "probe.py")
        with open(probe, "wb") as f:
            f.write(("import importlib.util, sys\n"
                     "spec = importlib.util.spec_from_file_location('h', %r)\n"
                     "h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)\n"
                     "def boom(p, info):\n    raise RuntimeError('simulated failure inside the handler')\n"
                     "h.on_prompt = boom\nh.on_stop = boom\nh.on_session_start = boom\n"
                     "h.main()\nsys.exit(0)\n" % S.HOOK).encode("utf-8"))
        for payload in (ups("예외 시험"), stop("답변"), session_start()):
            cp = S.run_hook(payload, self.sb.base, hook=probe)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, b"", b""))
        errs = self.sb.errors(SID) + self.sb.errors()
        self.assertEqual(len(errs), 3)
        for e in errs:
            self.assertEqual(e["where"], "main")
            self.assertIn("RuntimeError: simulated failure inside the handler", e["error"])
            self.assertIn("Traceback", e["error"])
            self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT")

    def test_a_exit_code_is_zero_even_for_system_exit_and_keyboard_interrupt(self):
        probe = os.path.join(self.sb.root, "probe2.py")
        for exc in ("SystemExit(3)", "KeyboardInterrupt()", "MemoryError()", "RecursionError()", "GeneratorExit()"):
            with open(probe, "wb") as f:
                f.write(("import importlib.util, os\n"
                         "spec = importlib.util.spec_from_file_location('h', %r)\n"
                         "h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)\n"
                         "def boom(p, info):\n    raise %s\n"
                         "h.on_prompt = boom\n"
                         "try:\n    h.main()\nfinally:\n    os._exit(0)\n" % (S.HOOK, exc)).encode("utf-8"))
            cp = S.run_hook(ups("예외 종류 시험"), self.sb.base, hook=probe)
            self.assertEqual((cp.returncode, cp.stdout), (0, b""), exc)
        self.assertEqual(len(self.sb.errors(SID) + self.sb.errors()), 5)

    def test_a_script_ends_with_an_unconditional_exit_zero(self):
        with open(S.HOOK, "rb") as f:
            src = f.read().decode("utf-8")
        tail = src[src.index('if __name__ == "__main__":'):]
        self.assertRegex(tail, r"try:\s+main\(\)\s+finally:\s+os\._exit\(0\)")
        self.assertNotIn("sys.exit(", src.replace("sys.exit(0)", ""))
        for name in re.findall(r"^import (\w+)", src, re.M):
            self.assertIn(name, ("datetime", "hashlib", "json", "os", "re", "sys", "time"))       # standard library only


# =============================================================================== A6
class EventLog(HookCase):
    """A6: events.jsonl - one diagnostic line per hook call, on by default, off by one constant."""

    def test_a6_one_line_per_call_with_what_was_done(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [S.tx_user("질문 1", "p1")])
        self.sb.feed(ups("질문 1", "p1", transcript_path=tx))
        self.sb.feed(ups("작업 중 입력", "p1", transcript_path=tx))
        self.sb.feed(stop("답변 1 입니다. 내용.", "p1", transcript_path=tx))
        self.sb.feed(stop("답변 1 입니다. 내용.", "p1", transcript_path=tx))
        self.sb.feed(stop("요청 없는 답변입니다.", "p2", transcript_path=tx))
        self.sb.feed(ups("/help", "p3"))
        self.sb.feed(ups("서브", "p4", agent_id="a1"))
        self.sb.feed(session_start("resume"))
        self.sb.feed(session_start(pid="p9"))
        self.sb.feed({"hook_event_name": "PreCompact", "session_id": SID})
        E = self.sb.events(SID)
        self.assertEqual([(e["ev"], e["act"]) for e in E], [
            ("UserPromptSubmit", "new_turn"), ("UserPromptSubmit", "append_request"), ("Stop", "answer"), ("Stop", "duplicate_answer"),
            ("Stop", "orphan_turn"), ("UserPromptSubmit", "skip_builtin"), ("UserPromptSubmit", "skip_agent"),
            ("SessionStart", "noop"), ("SessionStart", "inject"), ("PreCompact", "ignored")])
        self.assertEqual([e.get("turn") for e in E], [1, 1, 1, 1, 2, None, None, None, None, None])
        self.assertEqual((E[0]["kind"], E[0]["chars"], E[0]["pid"], E[0]["tx"]), ("user", 4, "p1", os.path.getsize(tx)))
        self.assertEqual((E[2]["src"], E[2]["sha"], E[2]["chars"]), ("payload", False, len("답변 1 입니다. 내용.")))
        self.assertEqual(E[6]["agent"], True)
        self.assertEqual((E[7]["source"], E[8]["source"]), ("resume", "compact"))
        self.assertEqual((E[8]["stage"], E[8]["turns"], E[8]["folded"]), ("full", 2, 0))
        self.assertEqual(E[8]["out"], self.sb.compactions(SID)[0]["chars"])
        for e in E:
            self.assertEqual(e["v"], ci.VERSION)
            self.assertRegex(e["ts"], r"^\d{4}-\d\d-\d\dT")
            self.assertIsInstance(e["ms"], float)
            self.assertEqual(e["keys"], sorted(e["keys"]))
        self.assertEqual(E[0]["keys"], ["cwd", "hook_event_name", "permission_mode", "prompt", "prompt_id", "session_id", "transcript_path"])

    def test_a6_no_prompt_or_answer_text_is_logged(self):
        secret_req, secret_ans = "비밀-요청-표식-XYZZY", "비밀-답변-표식-PLUGH 입니다."
        self.sb.feed(ups(secret_req + " 를 처리해줘"))
        self.sb.feed(stop(secret_ans))
        self.sb.feed(session_start())
        with open(os.path.join(self.sb.sdir(SID), "events.jsonl"), "rb") as f:
            raw = f.read()
        self.assertTrue(all(b < 128 for b in raw))
        for needle in ("XYZZY", "PLUGH", "/work/proj"):
            self.assertNotIn(needle.encode(), raw)
        for line in raw.split(b"\n")[:-1]:
            self.assertLess(len(line), 600)

    def test_a6_diagnostics_never_create_a_session_directory(self):
        for payload in (ups("/clear"), ups("서브", agent_id="a"), session_start("startup"), session_start("clear"),
                        {"hook_event_name": "Notification", "session_id": SID}):
            self.assertIsNone(self.sb.feed(payload))
        self.assertEqual(os.listdir(self.sb.base), [])

    def test_a6_can_be_switched_off_by_the_constant(self):
        self.assertIs(ci.EVENT_LOG, True)                                      # default: on
        ci.EVENT_LOG = False
        try:
            self.sb.feed(ups("질문"))
            self.sb.feed(stop("답변입니다. 내용."))
            self.assertTrue(context_of(self.sb.feed(session_start())))
        finally:
            ci.EVENT_LOG = True
        self.assertEqual(sorted(os.listdir(self.sb.sdir(SID))), ["compactions.jsonl", "index.md", "meta.json", "turns"])

    def test_a6_log_stops_growing_at_the_size_limit(self):
        self.sb.feed(ups("질문"))
        path = os.path.join(self.sb.sdir(SID), "events.jsonl")
        with open(path, "ab") as f:
            f.write(b"x" * (ci.EVENT_LOG_MAX_BYTES + 1))
        size = os.path.getsize(path)
        self.sb.feed(stop("답변입니다. 내용."))
        self.assertEqual(os.path.getsize(path), size)
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 1)                     # recording itself is unaffected

    def test_a6_logging_failures_are_swallowed(self):
        self.sb.feed(ups("질문"))
        path = os.path.join(self.sb.sdir(SID), "events.jsonl")
        os.remove(path)
        os.mkdir(path)
        self.sb.feed(stop("답변입니다. 내용."))
        self.assertEqual(self.sb.turns(SID)[0]["nans"], 1)

    def test_a6_meta_records_the_hook_environment(self):
        self.sb.feed(ups("질문"))
        hook = self.sb.meta(SID)["hook"]
        self.assertEqual(hook, {"version": ci.VERSION, "python": "%d.%d.%d" % sys.version_info[:3], "platform": sys.platform})


# =============================================================================== rebuild / reconcile
class Recovery(HookCase):
    """meta.json is derived data: it can be recomputed from the turn files."""

    def test_turn_file_layout(self):
        self.sb.feed(ups("요청 본문", "prompt-123"))
        self.sb.feed(stop("답변 본문입니다.", "prompt-123"))
        text = self.sb.turn_text(SID, 1)
        self.assertRegex(text, r"\A<!-- ctx-index \| turn 0001 \| session %s \| prompt prompt-123 -->\n"
                               r"\n## ◇ 요청 · \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d · 13B\n\n요청 본문\n"
                               r"\n## ◇ 답변 · \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d · 23B\n\n답변 본문입니다.\n\Z" % SID)

    def test_rebuild_matches_the_original_meta(self):
        tx = os.path.join(self.sb.root, "t.jsonl")
        S.write_transcript(tx, [S.tx_user("대기열 질문", "q2", promptSource="queued")])
        self.sb.feed(ups("## 첫 질문\n\n- 본문", "q1"))
        self.sb.feed(ups("작업 중 입력", "q1"))
        self.sb.feed(stop("안녕하세요!\n\n첫 답변의 의미 있는 문장입니다.", "q1"))
        self.sb.feed(stop("이어진 답변입니다. 둘째.", "q1", stop_hook_active=True))
        self.sb.feed(stop("대기열 질문의 답변입니다.", "q2", transcript_path=tx))
        self.sb.feed(ups("답 없는 질문", "q3"))
        before = self.sb.turns(SID)
        os.remove(os.path.join(self.sb.sdir(SID), "meta.json"))
        self.sb.feed(ups("재구성 뒤의 질문", "q4"))
        after = self.sb.turns(SID)
        self.assertEqual(len(after), 4)
        for a, b in zip(before, after):
            for key in ("n", "pid", "req", "ans", "nreq", "nans", "bytes", "ah"):
                self.assertEqual(a[key], b[key], key)
            self.assertEqual(b["kind"], "rebuilt")
        self.assertEqual([t["status"] for t in after], ["done", "done", "open", "open"])
        self.sb.feed(stop("이어진 답변입니다. 둘째.", "q1"))                   # still recognised as a duplicate
        self.sb.feed(stop("답 없는 질문의 답변이 재구성 뒤에 왔습니다.", "q3"))
        T = self.sb.turns(SID)
        self.assertEqual([(t["pid"], t["nans"]) for t in T], [("q1", 2), ("q2", 1), ("q3", 1), ("q4", 0)])

    def test_rebuild_is_exact_when_text_contains_section_headers(self):
        fake = "인용 시작\n\n## ◇ 답변 · 2026-01-01T00:00:00+09:00 · 3B\n\nabc\n\n## ◇ 추가 요청 (작업 중 입력) · 2026-01-01T00:00:00+09:00\n\n인용 끝"
        self.sb.feed(ups(fake, "p1"))
        self.sb.feed(stop(fake + "\n답변도 같은 인용을 담고 있습니다.", "p1"))
        self.sb.feed(ups("다음 질문", "p2"))
        before = self.sb.turns(SID)
        with open(os.path.join(self.sb.sdir(SID), "meta.json"), "wb") as f:
            f.write(b"damaged")
        self.sb.feed(stop("다음 답변입니다. 내용.", "p2"))
        after = self.sb.turns(SID)
        self.assertEqual([(t["nreq"], t["nans"], t["bytes"]) for t in after[:1]], [(1, 1, before[0]["bytes"])])
        self.assertEqual(after[0]["ah"], before[0]["ah"])

    def test_parse_turn_file_without_sizes_or_with_damage(self):
        legacy = ("<!-- ctx-index | turn 0001 | session s | prompt abcdefgh-1 -->\n"
                  "\n## ◇ 요청 · 2026-11-26T10:00:00+09:00\n\n옛 형식 요청\n"
                  "\n## ◇ 추가 요청 (작업 중 입력) · 2026-11-26T10:00:01+09:00\n\n추가\n"
                  "\n## ◇ 답변 · 2026-11-26T10:00:02+09:00\n\n옛 형식 답변\n").encode("utf-8")
        pid, secs = ci.parse_turn_file(legacy)
        self.assertEqual(pid, "abcdefgh-1")
        self.assertEqual([(a, c.decode("utf-8")) for a, _b, c in secs], [("요청", "옛 형식 요청"), ("추가 요청", "추가"), ("답변", "옛 형식 답변")])
        self.assertEqual(secs[0][1], "2026-11-26T10:00:00+09:00")
        wrong = legacy.replace("+09:00\n\n옛 형식 요청".encode("utf-8"), "+09:00 · 999999B\n\n옛 형식 요청".encode("utf-8"))
        self.assertEqual([c.decode("utf-8") for _a, _b, c in ci.parse_turn_file(wrong)[1]], ["옛 형식 요청", "추가", "옛 형식 답변"])
        for blob in (b"", b"\n", b"no header at all", b"<!-- ctx-index | turn 0001 | session s | prompt - -->\n", os.urandom(500),
                     "\n## ◇ 답변".encode("utf-8"), "\n## ◇ 답변 · 9" .encode("utf-8") + b"9" * 5000 + b"B\n\nx"):
            pid, secs = ci.parse_turn_file(blob)
            self.assertIsInstance(secs, list)
        self.assertEqual(ci.parse_turn_file(b"<!-- ctx-index | turn 0001 | session s | prompt - -->\n")[0], None)

    def test_reconcile_restores_turn_files_missing_from_meta(self):
        self.sb.feed(ups("첫 질문", "p1"))
        self.sb.feed(stop("첫 답변입니다. 내용.", "p1"))
        self.sb.feed(ups("meta 에서 사라질 질문", "p2"))
        meta_path = os.path.join(self.sb.sdir(SID), "meta.json")
        meta = self.sb.meta(SID)
        meta["turns"] = meta["turns"][:1]                                      # a lost update
        with open(meta_path, "wb") as f:
            f.write(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        self.sb.feed(stop("사라졌던 턴의 답변입니다.", "p2"))                  # must not become a second turn
        self.assertEqual(self.sb.turn_files(SID), ["0001.md", "0002.md"])
        self.assertEqual([(t["n"], t["pid"], t["nans"], t["kind"]) for t in self.sb.turns(SID)], [(1, "p1", 1, "user"), (2, "p2", 1, "rebuilt")])
        self.assertEqual([e["where"] for e in self.sb.errors(SID)], ["reconcile"])
        meta = self.sb.meta(SID)
        meta["turns"] = meta["turns"][1:]
        with open(meta_path, "wb") as f:
            f.write(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        body = S.body_lines(context_of(self.sb.feed(session_start())))         # compaction lists every file again
        self.assertEqual([line[:7] for line in body], ["0001.md", "0002.md"])
        self.assertEqual([t["n"] for t in self.sb.turns(SID)], [1, 2])

    def test_new_turn_never_overwrites_an_existing_file(self):
        self.sb.feed(ups("첫 질문", "p1"))
        stray = os.path.join(self.sb.sdir(SID), "turns", "0002.md")
        with open(stray, "wb") as f:
            f.write(b"someone else's turn file")
        self.sb.feed(ups("둘째 질문", "p2"))
        with open(stray, "rb") as f:
            self.assertEqual(f.read(), b"someone else's turn file")
        self.assertEqual([t["n"] for t in self.sb.turns(SID)], [1, 3])
        self.assertIn("turn 0003", self.sb.turn_text(SID, 3).split("\n")[0])

    def test_turn_numbers_beyond_9999_sort_numerically(self):
        d = os.path.join(self.sb.sdir(SID), "turns")
        os.makedirs(d)
        for n in (9998, 9999, 10000, 10001):
            with open(os.path.join(d, "%04d.md" % n), "wb") as f:
                f.write(("<!-- ctx-index | turn %04d | session s | prompt p%d -->\n\n## ◇ 요청 · t · 2B\n\nq%d\n" % (n, n, n % 10)).encode("utf-8"))
        with open(os.path.join(d, "notes.txt"), "wb") as f:
            f.write(b"ignored")
        self.sb.feed(ups("다음 질문", "next"))
        self.assertEqual([t["n"] for t in self.sb.turns(SID)], [9998, 9999, 10000, 10001, 10002])
        body = S.body_lines(context_of(self.sb.feed(session_start())))
        self.assertEqual([line.split(" ")[0] for line in body], ["9998.md", "9999.md", "10000.md", "10001.md", "10002.md"])


# =============================================================================== parity with the lab prototype
@unittest.skipUnless(os.path.isfile(S.PROTO), "lab/proto/ctx_proto.py is not present")
class PrototypeParity(unittest.TestCase):
    """The validated logic was carried over, not reinvented: where behaviour was meant to stay,
    the final hook and the lab prototype agree."""

    @classmethod
    def setUpClass(cls):
        cls.proto = S.load_module("ctx_proto_for_tests", S.PROTO)

    def test_fixed_strings_and_limits_are_unchanged(self):
        for name in ("HEADER", "MAX_CONTEXT_CHARS", "REQ_PREVIEW_CHARS", "ANS_PREVIEW_CHARS", "STORED_PREVIEW_CHARS",
                     "FIRST_COMPACTION_FOLD_TURNS", "SMALL_TURN_BYTES", "BUILTIN_COMMANDS", "NO_ANSWER", "IN_FLIGHT", "NO_REQUEST",
                     "LOCK_WAIT_SECS", "TAIL_BYTES", "TAIL_MAX_BYTES", "PREVIEW_SCAN_CHARS"):
            self.assertEqual(getattr(ci, name), getattr(self.proto, name), name)
        self.assertEqual((self.proto.STAGE1_MINIMAL, ci.STAGE1_MINIMAL), (False, True))   # the one approved difference (A3)

    def test_previews_are_identical(self):
        rnd = random.Random(5)
        pieces = ["안녕하세요!", "## 제목", "- 항목 **굵게** `코드`", "> 인용", "1. 번호", "", "```py", "x = 1", "```", "Sure!", "네, 알겠습니다.",
                  "[링크](http://a/b) 와 ![그림](c.png)", "<tag attr='1'>본문</tag>", "The flake comes from a shared temp dir.",
                  "재시도 로직은 타임아웃 불일치 때문에 중복 전송됩니다.", "~~취소~~ _기울임_ *강조*", "🙂 emoji", "---", "가" * 300]
        for _ in range(1500):
            text = "\n".join(rnd.choice(pieces) for _ in range(rnd.randint(0, 8)))
            self.assertEqual(ci.request_preview(text), self.proto.request_preview(text), text)
            self.assertEqual(ci.answer_preview(text), self.proto.answer_preview(text), text)
            self.assertEqual(ci.is_builtin_command(text), self.proto.is_builtin_command(text), text)

    def test_rendering_is_identical_in_both_stage1_modes(self):
        rnd = random.Random(99)
        for case in range(400):
            n = rnd.randint(1, 320)
            turns = S.make_turns(n, seed=case, small_ratio=rnd.random())
            prev = None if rnd.random() < 0.4 else {"last_turn": rnd.randint(0, n), "last_open": rnd.random() < 0.3}
            inflight = "p%d" % n if case % 7 == 0 else None
            for minimal in (False, True):
                a = ci.render_index(turns, prev, S.WIN_DIR, inflight, minimal=minimal)
                b = self.proto.render_index(turns, prev, S.WIN_DIR, inflight, minimal=minimal)
                self.assertEqual(a[0], b[0], (case, minimal))
                self.assertEqual(a[1]["stage"], b[1]["stage"])

    def test_replay_ends_in_the_same_state(self):
        saved = os.environ.get("CTX_INDEX_DIR")
        for name in S.CAPTURE_NAMES:
            final = S.Replay(name)
            sb = S.Sandbox()
            txdir = os.path.join(sb.root, "tx")
            os.makedirs(txdir)
            outs = []
            with sb:
                for r in final.rows:
                    p = dict(r["payload"])
                    name_ = os.path.basename(p.get("transcript_path") or "")
                    copy = os.path.join(txdir, name_ or "none.jsonl")
                    if r.get("tx_size") is None:
                        if os.path.exists(copy):
                            os.remove(copy)
                    else:
                        with open(copy, "wb") as dst:
                            dst.write(S.read_fixture(os.path.join(S.CAPTURES, "transcripts", name_))[:r["tx_size"]])
                    p["transcript_path"] = copy
                    out = self.proto.handle(p)
                    if out:
                        outs.append(context_of(out).replace(sb.base, "<BASE>"))
                for sid in sb.sessions():
                    want = [(t["n"], t["pid"], t["kind"], t["status"], t["nreq"], t["nans"], t["req"], t["ans"], t["bytes"]) for t in sb.turns(sid)]
                    got = [(t["n"], t["pid"], t["kind"], t["status"], t["nreq"], t["nans"], t["req"], t["ans"], t["bytes"])
                           for t in final.sessions[sid]["meta"]["turns"]]
                    self.assertEqual(got, want, (name, sid))
            self.assertEqual([text.replace(final.sb.base, "<BASE>") for _sid, text in final.outs], outs, name)
            final.close()
        self.assertEqual(os.environ.get("CTX_INDEX_DIR"), saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
