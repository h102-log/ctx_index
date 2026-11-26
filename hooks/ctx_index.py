#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctx-index - turn index hook for Claude Code (2.1.33x).

Registered for three hook events (tools/install_hook.py writes the registration):

  UserPromptSubmit        store the request verbatim in a per-turn file
  Stop                    append the final answer verbatim to that turn's file
  SessionStart[compact]   print a table of contents of the stored turns as additionalContext

Everything is kept under ~/.claude/ctx-index/<session_id>/ - the session id alone fixes the
path; neither the branch nor the working directory is part of it:

  turns/NNNN.md       one file per turn: full request + final answer, appended as they arrive
  meta.json           per-turn state, previews and sizes; the index is rendered from this
  compactions.jsonl   one line per compaction (last turn at that moment = next fold segment)
  index.md            snapshot of the last injected index (debugging aid)
  events.jsonl        one diagnostic line per hook call, without prompt/answer text (EVENT_LOG)
  errors.jsonl        exceptions

Contract (docs/phase3-report.md, section 0):
  * The hook does all the recording. The model is never asked to write anything.
  * stdout stays empty except for SessionStart with source == "compact".
  * additionalContext never exceeds MAX_CONTEXT_CHARS, measured in UTF-16 code units.
  * Whatever the input, the process exits 0; exceptions are recorded in errors.jsonl.

Standard library only. Meant for Windows 11 / Python 3.12 as much as for POSIX: stdin and
stdout are used as bytes, every file is written in binary mode as UTF-8 (no newline
translation), and the JSON printed on stdout is ASCII-escaped so that the console code page
cannot damage it.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time

VERSION = "1.0.0"

# ----------------------------------------------------------------------------- tunables
MAX_CONTEXT_CHARS = 6000          # cap on hookSpecificOutput.additionalContext
REQ_PREVIEW_CHARS = 70
ANS_PREVIEW_CHARS = 90
STORED_PREVIEW_CHARS = 240        # meta.json keeps longer clean previews; rendering truncates
PREVIEW_SCAN_CHARS = 20000        # previews never look past this much text (keeps huge inputs cheap)
PREVIEW_LINE_CHARS = 2000         # ...and never clean more than this much of one line
FIRST_COMPACTION_FOLD_TURNS = 5
SMALL_TURN_BYTES = 500
STAGE1_MINIMAL = True             # stage 1 folds only as many of the newest turns of its segment as needed
                                  # (False = fold the whole segment, the literal wording of the spec)
EVENT_LOG = True                  # write events.jsonl diagnostics; set to False to turn them off
EVENT_LOG_MAX_BYTES = 8 * 1024 * 1024   # stop appending to one session's events.jsonl beyond this
BUILTIN_COMMANDS = frozenset(("clear", "compact", "help", "status", "cost", "exit", "quit"))
HEADER = ("이 세션에서 있었던 턴의 목록입니다. 결과의 요약이 아니며 빠진 것이 있을 수 있습니다. "
          "세부가 필요하면 아래 디렉터리의 해당 턴 파일을 직접 읽으세요.")
LOCK_WAIT_SECS = 2.0
LOCK_STALE_SECS = 30.0
TAIL_BYTES = 2 * 1024 * 1024
TAIL_MAX_BYTES = 32 * 1024 * 1024
FORWARD_BYTES = 4 * 1024 * 1024

NO_ANSWER = "(답변 없음/중단)"
IN_FLIGHT = "(진행 중)"
NO_REQUEST = "(요청 미기록)"
EMPTY_REQUEST = "(빈 요청)"
NO_TEXT = "(텍스트 없음)"
TASK_NOTE = "[작업 알림]"

# section labels used inside turn files
SEC_REQUEST = "요청"
SEC_REQUEST_RECOVERED = "요청 (트랜스크립트에서 복원)"
SEC_REQUEST_EXTRA = "추가 요청 (작업 중 입력)"
SEC_ANSWER = "답변"
SEC_ANSWER_MORE = "답변 (이어짐 %d)"


# ----------------------------------------------------------------------------- small utils
def now_iso():
    try:
        return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    except Exception:
        return time.strftime("%Y-%m-%dT%H:%M:%S")


def ulen(s):
    """Length in UTF-16 code units (what the CLI's JS .length measures); always >= len(s)."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def fix_text(s):
    """Make a str safely UTF-8 encodable (lone surrogates -> U+FFFD)."""
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        return s.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def to_text(v):
    """Text of a payload field whose type is not guaranteed (str, content-block list, anything)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return fix_text(v)
    if isinstance(v, list):
        parts = []
        for b in v:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif isinstance(b, str):
                parts.append(b)
        return fix_text("\n".join(parts))
    try:
        return fix_text(json.dumps(v, ensure_ascii=False))
    except Exception:
        return fix_text(str(v))


def sha(text):
    return hashlib.sha1(text.strip().encode("utf-8", "replace")).hexdigest()


_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def safe_session_id(sid):
    """Directory name for a session id; ids that are not plain file names get a hash suffix."""
    if not isinstance(sid, str) or not sid.strip():
        return None
    s = re.sub(r"[^A-Za-z0-9._-]", "_", sid.strip()).strip(". ")
    if not s:
        return None
    reserved = s.split(".")[0].upper() in _RESERVED       # Windows device names, with or without extension
    if s != sid or len(s) > 80 or reserved:
        s = ("_" if reserved else "") + s[:60] + "-" + hashlib.sha1(sid.encode("utf-8", "replace")).hexdigest()[:8]
    return s


def base_dir():
    """~/.claude/ctx-index (CTX_INDEX_DIR overrides it; meant for tests)."""
    d = os.environ.get("CTX_INDEX_DIR")
    if not d:
        d = os.path.join(os.path.expanduser("~"), ".claude", "ctx-index")
    return os.path.abspath(d)


def session_of(p):
    sid = safe_session_id(p.get("session_id"))
    if not sid:
        tp = p.get("transcript_path")
        if isinstance(tp, str) and tp:
            sid = safe_session_id(os.path.splitext(os.path.basename(tp.replace("\\", "/")))[0])
    return sid or "unknown-session"


def pid_of(p):
    v = p.get("prompt_id")
    return v if isinstance(v, str) and v else None


def _jsonl(rec):
    try:
        return json.dumps(rec, ensure_ascii=False).encode("utf-8") + b"\n"
    except Exception:
        return json.dumps(rec).encode("ascii") + b"\n"


def log_error(where, msg, sid=None):
    """Append to <session dir>/errors.jsonl, or to the root errors.jsonl when that is not possible."""
    rec = {"ts": now_iso(), "v": VERSION, "where": where, "error": fix_text(str(msg))}
    dirs = []
    try:
        root = base_dir()
        if sid:
            rec["session"] = sid
            dirs.append(os.path.join(root, sid))
        dirs.append(root)
    except Exception:
        return False
    for d in dirs:
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "errors.jsonl"), "ab") as f:
                f.write(_jsonl(rec))
            return True
        except Exception:
            continue
    return False


# ----------------------------------------------------------------------------- previews
_TAG = re.compile(r"</?[A-Za-z][\w:.-]{0,40}(?:\s[^<>]{0,120})?/?>")
_LEAD = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>+\s?|[-*+]\s+(?:\[[ xX]\]\s+)?|\d{1,3}[.)]\s+)+")
_GREET = re.compile(
    r"^(?:안녕하세요|안녕하십니까|반갑습니다|네|넵|예|알겠습니다|좋습니다|좋아요|확인했습니다|물론입니다|물론이죠|감사합니다|"
    r"hello|hi|hey|sure|okay|ok|got it|understood|certainly|of course|great|absolutely|thanks|thank you|alright|"
    r"all right|no problem)(?=[\s!.,~…:)]|$)[\s!.,~…:)]*", re.I)
_WORDCH = re.compile(r"[0-9A-Za-zÀ-ɏͰ-ϿЀ-ӿ぀-ヿ㐀-鿿가-힣]")


def clean_inline(s):
    """One line of text with markdown / tag syntax removed and whitespace collapsed."""
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = _TAG.sub(" ", s)
    s = re.sub(r"`{1,3}", "", s)
    s = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", s)
    s = re.sub(r"(?<![0-9A-Za-z_*])\*(?=\S)([^*]+?)(?<=\S)\*(?![0-9A-Za-z_*])", r"\1", s)
    s = re.sub(r"(?<![\w_])_(?=\S)([^_]+?)(?<=\S)_(?![\w_])", r"\1", s)
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    s = _LEAD.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def cut(s, n):
    if n <= 0:
        return ""
    return s if len(s) <= n else s[:max(0, n - 1)].rstrip() + "…"


def request_preview(text):
    t = text.lstrip()
    if t.startswith("<task-notification>"):
        m = re.search(r"<summary>(.*?)</summary>", t[:PREVIEW_SCAN_CHARS], re.S)
        note = (TASK_NOTE + " " + clean_inline(m.group(1)[:PREVIEW_LINE_CHARS])) if m else TASK_NOTE
        return cut(note, STORED_PREVIEW_CHARS)
    if t.startswith("<bash-input>"):
        m = re.match(r"<bash-input>(.*?)</bash-input>", t[:PREVIEW_SCAN_CHARS], re.S)
        if m:
            return cut("!" + re.sub(r"\s+", " ", m.group(1)).strip(), STORED_PREVIEW_CHARS)
    parts = []
    total = 0
    for line in text[:PREVIEW_SCAN_CHARS].splitlines():
        c = clean_inline(line[:PREVIEW_LINE_CHARS])
        if c:
            parts.append(c)
            total += len(c) + 1
            if total > STORED_PREVIEW_CHARS:
                break
    return cut(" ".join(parts), STORED_PREVIEW_CHARS)


def answer_preview(text):
    """First meaningful sentence: skips greeting-only lines, bare headers, rules and code fences."""
    in_code = False
    first_header = first_any = first_code = ""
    for raw in text[:PREVIEW_SCAN_CHARS].splitlines():
        st = raw.strip()[:PREVIEW_LINE_CHARS]
        if st.startswith("```") or st.startswith("~~~"):
            in_code = not in_code
            continue
        if not st:
            continue
        if in_code:
            first_code = first_code or clean_inline(st)
            continue
        is_header = bool(re.match(r"^#{1,6}\s", st))
        c = clean_inline(st)
        if not c:
            continue
        if is_header:
            first_header = first_header or c
            continue
        m = _GREET.match(c)
        if m:
            rest = c[m.end():].strip()
            if len(rest) < 8:
                first_any = first_any or c
                continue
            c = rest
        if len(_WORDCH.findall(c)) < 4:
            first_any = first_any or c
            continue
        return cut(c, STORED_PREVIEW_CHARS)
    return cut(first_header or first_any or first_code, STORED_PREVIEW_CHARS)


def is_builtin_command(prompt):
    m = re.match(r"^\s*/([A-Za-z][\w:-]*)(?=\s|$)", prompt)
    return bool(m) and m.group(1).lower() in BUILTIN_COMMANDS


# ----------------------------------------------------------------------------- storage
_TURN_FILE = re.compile(r"^(\d{4,})\.md$")
_SECTION = re.compile(("\n## ◇ (추가 요청|요청|답변)([^\n]*)\n\n").encode("utf-8"))
_SECTION_SIZE = re.compile((" · (\\d{1,12})B$").encode("utf-8"))
_SECTION_TS = re.compile((" · (\\d{4}-\\d\\d-\\d\\dT[0-9:.+-]+)").encode("utf-8"))
_HEADER_PID = re.compile(rb"\| prompt ([0-9A-Za-z_.:-]{1,80}) -->")


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _str(v):
    return fix_text(v) if isinstance(v, str) else ""


def norm_turn(t):
    """One meta.json turn record coerced to the expected shape: a damaged or hand-edited
    record must not be able to break rendering."""
    pid, ah = t.get("pid"), t.get("ah")
    return {"n": t["n"], "pid": pid if isinstance(pid, str) and pid else None,
            "status": "done" if t.get("status") == "done" else "open",
            "t0": _str(t.get("t0")), "t1": _str(t.get("t1")),
            "req": _str(t.get("req")), "ans": _str(t.get("ans")),
            "nreq": _int(t.get("nreq")), "nans": _int(t.get("nans")), "bytes": _int(t.get("bytes")),
            "ah": ah if isinstance(ah, str) and ah else None, "kind": _str(t.get("kind")) or "user"}


def parse_turn_file(data):
    """Split the bytes of a turn file into (prompt id or None, [(label, timestamp, body bytes)]).

    append() writes every section as "\\n## <mark> <label> · <time> · <N>B\\n\\n" + body + "\\n".
    The byte count makes the split exact even when a body itself contains lines that look
    like section headers (an answer quoting another turn file); sections without a usable
    count are split at the next header instead.
    """
    nl = data.find(b"\n")
    m = _HEADER_PID.search(data if nl < 0 else data[:nl])
    pid = m.group(1).decode("ascii") if m else None
    if pid == "-":
        pid = None
    sections = []
    pos = 0
    while True:
        m = _SECTION.search(data, pos)
        if not m:
            break
        start = m.end()
        end = None
        ms = _SECTION_SIZE.search(m.group(2))
        if ms:                                # trusted only if the body is followed by what append() wrote
            e = start + int(ms.group(1))
            if data[e:e + 1] == b"\n" and (e + 1 == len(data) or _SECTION.match(data, e + 1)):
                end = e
        if end is None:                       # no trustworthy size: the body runs to the next header
            nxt = _SECTION.search(data, start)
            end = nxt.start() if nxt else len(data)
            if end > start and data[end - 1:end] == b"\n":
                end -= 1
        mt = _SECTION_TS.search(m.group(2))
        sections.append((m.group(1).decode("utf-8"), mt.group(1).decode("ascii") if mt else "", data[start:end]))
        pos = end
    return pid, sections


class Store(object):
    """One session's directory. Use as a context manager: it holds the session lock."""

    def __init__(self, sid):
        self.sid = sid
        self.dir = os.path.join(base_dir(), sid)
        self.turns_dir = os.path.join(self.dir, "turns")
        self.meta_path = os.path.join(self.dir, "meta.json")
        self.lock_path = os.path.join(self.dir, ".lock")
        self.held = False
        os.makedirs(self.turns_dir, exist_ok=True)

    # -- lock
    def __enter__(self):
        deadline = time.monotonic() + LOCK_WAIT_SECS
        blocked = 0
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lock_path) > LOCK_STALE_SECS:
                        os.remove(self.lock_path)     # left behind by a killed hook process
                        continue
                except OSError:
                    pass
            except OSError as e:
                # Windows reports a lock file that is being deleted right now this way: retry. But a
                # directory that cannot be written at all is not worth the full wait - the caller's
                # own write is going to fail and be recorded anyway.
                if not os.path.exists(self.lock_path):
                    blocked += 1
                    if blocked >= 5:
                        log_error("lock", "cannot create the session lock (%r); continuing without it" % (e,), self.sid)
                        return self
            if time.monotonic() >= deadline:
                log_error("lock", "timeout waiting for the session lock; continuing without it", self.sid)
                return self
            time.sleep(0.02)

    def __exit__(self, *exc):
        if self.held:
            self.held = False
            try:
                os.remove(self.lock_path)
            except OSError:
                pass
        return False

    # -- meta
    def _read_meta(self):
        for i in range(6):
            try:
                with open(self.meta_path, "rb") as f:
                    return f.read()
            except PermissionError:                   # Windows: briefly held open by another process
                if i == 5:
                    raise
                time.sleep(0.02 * (i + 1))

    def load(self):
        try:
            meta = json.loads(self._read_meta().decode("utf-8"))
            if not isinstance(meta, dict) or not isinstance(meta.get("turns"), list):
                raise ValueError("unexpected meta.json shape")
            turns, seen = [], set()
            for t in meta["turns"]:
                if isinstance(t, dict) and isinstance(t.get("n"), int) and not isinstance(t.get("n"), bool) \
                        and t["n"] >= 1 and t["n"] not in seen:
                    seen.add(t["n"])
                    turns.append(norm_turn(t))
            turns.sort(key=lambda t: t["n"])
            meta["turns"] = turns
            if not isinstance(meta.get("tx"), int) or isinstance(meta.get("tx"), bool):
                meta["tx"] = None
            if not isinstance(meta.get("last_ans"), str):
                meta["last_ans"] = None
            return meta
        except FileNotFoundError:
            pass
        except Exception as e:
            log_error("meta", "meta.json unreadable (%r); rebuilding it from the turn files" % (e,), self.sid)
            try:
                os.replace(self.meta_path, self.meta_path + ".bad-%d" % int(time.time()))
            except OSError:
                pass
        turns = self.rebuild()
        last = [t["ah"] for t in turns if t["ah"]]
        return {"schema": 1, "session_id": self.sid, "created": now_iso(), "turns": turns,
                "tx": None, "last_ans": last[-1] if last else None}

    def turn_numbers(self):
        try:
            names = os.listdir(self.turns_dir)
        except OSError:
            return []
        return sorted(int(m.group(1)) for m in (_TURN_FILE.match(n) for n in names) if m)

    def rebuild_turn(self, n):
        """meta record for turn n recomputed from its file (None when the file cannot be read)."""
        try:
            with open(self.turn_path(n), "rb") as f:
                data = f.read()
        except OSError:
            return None
        pid, sections = parse_turn_file(data)
        reqs = [s[2].decode("utf-8", "replace") for s in sections if s[0] != SEC_ANSWER]
        anss = [s[2].decode("utf-8", "replace") for s in sections if s[0] == SEC_ANSWER]
        return {"n": n, "pid": pid, "status": "done" if anss else "open",
                "t0": sections[0][1] if sections else "", "t1": sections[-1][1] if sections else "",
                "req": request_preview(reqs[0]) if reqs else "", "ans": answer_preview(anss[0]) if anss else "",
                "nreq": len(reqs), "nans": len(anss), "bytes": sum(len(s[2]) for s in sections),
                "ah": sha(anss[-1]) if anss and anss[-1].strip() else None, "kind": "rebuilt"}

    def rebuild(self):
        return [t for t in (self.rebuild_turn(n) for n in self.turn_numbers()) if t]

    def reconcile(self, meta):
        """Re-add turn files that meta.json does not list (an update lost after a lock timeout
        or a crash between creating the file and saving meta). Returns how many were added."""
        known = set(t["n"] for t in meta["turns"])
        added = [t for t in (self.rebuild_turn(n) for n in self.turn_numbers() if n not in known) if t]
        if added:
            meta["turns"].extend(added)
            meta["turns"].sort(key=lambda t: t["n"])
            log_error("reconcile", "meta.json did not list %d turn file(s); re-added from turns/: %s"
                      % (len(added), ", ".join("%04d" % t["n"] for t in added[:20])), self.sid)
        return len(added)

    def save(self, meta):
        meta["updated"] = now_iso()
        meta["hook"] = {"version": VERSION, "python": "%d.%d.%d" % sys.version_info[:3], "platform": sys.platform}
        data = json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8")
        tmp = "%s.tmp%d" % (self.meta_path, os.getpid())
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            for i in range(10):
                try:
                    os.replace(tmp, self.meta_path)   # atomic: readers see the old or the new file
                    return
                except PermissionError:               # Windows: the target is open in another process
                    time.sleep(0.02 * (i + 1))
            with open(self.meta_path, "wb") as f:     # last resort: not atomic, but not lost
                f.write(data)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    # -- turn files
    def turn_path(self, n):
        return os.path.join(self.turns_dir, "%04d.md" % n)

    def new_turn(self, meta, pid, kind):
        n = (meta["turns"][-1]["n"] + 1) if meta["turns"] else 1
        head_pid = re.sub(r"[^0-9A-Za-z_.:-]", "_", pid)[:80] if pid else "-"
        while True:
            head = "<!-- ctx-index | turn %04d | session %s | prompt %s -->\n" % (n, self.sid, head_pid)
            try:
                with open(self.turn_path(n), "xb") as f:     # exclusive: never reuse a number that has a file
                    f.write(head.encode("utf-8"))
                break
            except FileExistsError:
                n += 1
        t = {"n": n, "pid": pid, "status": "open", "t0": now_iso(), "t1": now_iso(), "req": "", "ans": "",
             "nreq": 0, "nans": 0, "bytes": 0, "ah": None, "kind": kind}
        meta["turns"].append(t)
        return t

    def append(self, t, label, text):
        body = text.encode("utf-8")
        ts = now_iso()
        with open(self.turn_path(t["n"]), "ab") as f:
            f.write(("\n## ◇ %s · %s · %dB\n\n" % (label, ts, len(body))).encode("utf-8") + body + b"\n")
        t["bytes"] = t.get("bytes", 0) + len(body)
        t["t1"] = ts

    def append_line(self, name, obj):
        with open(os.path.join(self.dir, name), "ab") as f:
            f.write(_jsonl(obj))

    def last_compaction(self):
        last = None
        try:
            with open(os.path.join(self.dir, "compactions.jsonl"), "rb") as f:
                for line in f:
                    try:
                        o = json.loads(line.decode("utf-8"))
                        if isinstance(o, dict) and isinstance(o.get("last_turn"), int) \
                                and not isinstance(o.get("last_turn"), bool):
                            last = o
                    except Exception:
                        continue
        except OSError:
            pass
        return last


# ----------------------------------------------------------------------------- transcript access
# The transcript JSONL is an undocumented format. It is read only on fallback paths (an
# answer missing from the Stop payload, a turn that started without UserPromptSubmit), and
# every failure here degrades to "nothing found".
_TX_LINE = re.compile(rb'"type"\s*:\s*"(?:user|assistant)"')


def tx_size(path):
    try:
        return os.path.getsize(path) if isinstance(path, str) and path else None
    except (OSError, ValueError):             # ValueError: a path with an embedded NUL
        return None


def _read(path, start, length):
    with open(path, "rb") as f:
        f.seek(start)
        return f.read(length)


def _parse_lines(data, drop_first):
    lines = data.split(b"\n")
    if drop_first:
        lines = lines[1:]
    out = []
    for ln in lines:
        if not _TX_LINE.search(ln):
            continue
        try:
            e = json.loads(ln.decode("utf-8", "replace"))
        except Exception:
            continue
        if isinstance(e, dict) and e.get("type") in ("user", "assistant") and not e.get("isSidechain"):
            out.append(e)
    return out


def _message(e):
    m = e.get("message")
    return m if isinstance(m, dict) else {}


def _has_text(e):
    if e.get("type") != "assistant" or e.get("isApiErrorMessage"):
        return False
    msg = _message(e)
    return msg.get("model") != "<synthetic>" and bool(to_text(msg.get("content")).strip())


def tail_entries(path):
    """Main-chain user/assistant entries from the end of the transcript (bounded; grows only if needed)."""
    size = tx_size(path)
    if not size:
        return []
    span = TAIL_BYTES
    while True:
        start = max(0, size - span)
        try:
            out = _parse_lines(_read(path, start, size - start), start > 0)
        except (OSError, ValueError):
            return []
        if start == 0 or span >= TAIL_MAX_BYTES or any(_has_text(e) for e in out):
            return out
        span *= 4


def last_assistant_text(entries, pid):
    """Text of the last assistant message that has text; '' when that text belongs to another prompt."""
    i = len(entries) - 1
    while i >= 0 and not _has_text(entries[i]):
        i -= 1
    if i < 0:
        return ""
    mid = _message(entries[i]).get("id")
    j = i
    while j - 1 >= 0 and mid and entries[j - 1].get("type") == "assistant" and _message(entries[j - 1]).get("id") == mid:
        j -= 1
    if pid:  # the nearest earlier user entry tells which prompt this text belongs to
        k = j - 1
        while k >= 0 and not (entries[k].get("type") == "user" and entries[k].get("promptId")):
            k -= 1
        if k >= 0 and entries[k].get("promptId") != pid:
            return ""
    texts = (to_text(_message(entries[k]).get("content")) for k in range(j, i + 1))
    return "\n".join(x for x in texts if x.strip()).strip()


def prompt_request(path, pid, hint):
    """The request text the transcript recorded for prompt `pid` ('' when it is not there).

    `hint` is the transcript size at this session's previous hook event: a turn the hook has
    not seen yet starts right after it, so a short forward read finds its first entry cheaply.
    """
    if not pid or not re.match(r"^[0-9A-Za-z_-]{6,80}$", pid):
        return ""
    size = tx_size(path)
    if not size:
        return ""
    needle = pid.encode("ascii")
    spans = []
    if isinstance(hint, int) and not isinstance(hint, bool) and 0 <= hint < size:
        spans.append((hint, min(size - hint, FORWARD_BYTES)))
    spans.append((max(0, size - TAIL_BYTES), min(size, TAIL_BYTES)))
    for start, length in spans:
        try:
            data = _read(path, start, length)
            if needle not in data:
                continue
            drop = start > 0 and _read(path, start - 1, 1) != b"\n"
        except (OSError, ValueError):
            continue
        parts = []
        for e in _parse_lines(data, drop):
            if e.get("type") == "assistant" and parts:
                break
            if e.get("type") == "user" and e.get("promptId") == pid and not e.get("isMeta") and not e.get("isCompactSummary"):
                c = _message(e).get("content")
                if isinstance(c, str) and c.strip():
                    parts.append(fix_text(c))
        if parts:
            return "\n".join(parts)
    return ""


# ----------------------------------------------------------------------------- rendering
def fmt_size(b):
    if b >= 1024 * 1024:
        return "%.1fMB" % (b / 1048576.0)
    return "%.1fKB" % (max(b / 1024.0, 0.1) if b > 0 else 0.0)


def turn_line(t, rn, an, inflight_pid):
    """One index line: file name and size only, then the request and answer previews."""
    if t.get("req"):
        suf = " (+%d)" % (t["nreq"] - 1) if t.get("nreq", 1) > 1 else ""
        req = cut(t["req"], rn - len(suf)) + suf
    else:
        req = EMPTY_REQUEST if t.get("nreq", 0) else NO_REQUEST
    if t.get("nans", 0) > 0:
        suf = " (+%d)" % (t["nans"] - 1) if t["nans"] > 1 else ""
        ans = cut(t.get("ans") or NO_TEXT, an - len(suf)) + suf
    elif inflight_pid and t.get("pid") == inflight_pid:
        ans = IN_FLIGHT
    else:
        ans = NO_ANSWER
    return "%04d.md %s | %s → %s" % (t["n"], fmt_size(t.get("bytes", 0)), req, ans)


def fold_line(group):
    size = fmt_size(sum(t.get("bytes", 0) for t in group))
    if len(group) == 1:
        return "%04d.md %s (접힘)" % (group[0]["n"], size)
    return "%04d.md~%04d.md %s (%d턴 접힘)" % (group[0]["n"], group[-1]["n"], size, len(group))


def build(turns, folded, rn, an, turns_dir, inflight_pid):
    """The index text: fixed header, the directory (absolute path, once) and one line per turn or folded run."""
    head = [HEADER, "디렉터리: %s (턴 %d개)" % (turns_dir, len(turns)),
            "형식: 파일 크기 | 요청 → 답변" + (" · '접힘'은 미리보기만 생략한 구간이며 파일은 그대로 있음" if folded else "")]
    body = []
    i = 0
    while i < len(turns):
        if turns[i]["n"] in folded:
            j = i
            while j + 1 < len(turns) and turns[j + 1]["n"] in folded:
                j += 1
            body.append(fold_line(turns[i:j + 1]))
            i = j + 1
        else:
            body.append(turn_line(turns[i], rn, an, inflight_pid))
            i += 1
    return "\n".join(head + body)


def hard_cut(text, limit):
    while ulen(text) > limit:
        text = text[:max(0, len(text) - max(1, ulen(text) - limit))]
    return text


def render_index(turns, prev, turns_dir, inflight_pid=None, limit=None, minimal=None):
    """(index text, info). The text never exceeds `limit` UTF-16 code units.

    Folding happens only when the full index does not fit, one stage at a time:
      full  everything shown
      1     the newest segment collapses into one line: the turns since the previous compaction,
            or the newest FIRST_COMPACTION_FOLD_TURNS on the first one. With `minimal` only as
            many of the newest turns of that segment as needed are folded.
      2a    previews halved
      2b    turns under SMALL_TURN_BYTES folded, smallest first (early large turns stay)
      2c    folding extended from the newest remaining turn towards the past
      cut   hard truncation - only when the header alone does not fit
    """
    limit = MAX_CONTEXT_CHARS if limit is None else limit
    minimal = STAGE1_MINIMAL if minimal is None else minimal
    info = {"stage": "full", "turns": len(turns), "folded": 0, "preview": [REQ_PREVIEW_CHARS, ANS_PREVIEW_CHARS]}
    if not turns:
        return "", dict(info, stage="empty", chars=0, utf16=0)
    rn, an = REQ_PREVIEW_CHARS, ANS_PREVIEW_CHARS
    folded = set()

    def mk(extra=()):
        return build(turns, folded | set(extra), rn, an, turns_dir, inflight_pid)

    def done(text, stage):
        if ulen(text) > limit:                # cannot happen for stages 1-2c; kept as the last line of defence
            text, stage = hard_cut(text, limit), "cut"
        info.update(stage=stage, folded=len([t for t in turns if t["n"] in folded]), preview=[rn, an],
                    chars=len(text), utf16=ulen(text))
        return text, info

    def min_k(cands):
        """Smallest k such that folding cands[:k] fits; None if even all of them do not."""
        if ulen(mk(cands)) > limit:
            return None
        lo, hi = 0, len(cands)
        while lo < hi:
            mid = (lo + hi) // 2
            if ulen(mk(cands[:mid])) <= limit:
                hi = mid
            else:
                lo = mid + 1
        return lo

    text = mk()
    if ulen(text) <= limit:
        return done(text, "full")

    # ---- stage 1: fold the newest segment (since the previous compaction; newest 5 on the first compaction)
    if prev is None or _int(prev.get("last_turn")) <= 0:
        seg = [t["n"] for t in turns[-FIRST_COMPACTION_FOLD_TURNS:]]
        info["segment"] = "first-compaction: newest %d" % len(seg)
    else:
        start = prev["last_turn"] + (0 if prev.get("last_open") else 1)
        seg = [t["n"] for t in turns if t["n"] >= start]
        info["segment"] = "since turn %d (%d turns)" % (start, len(seg))
    newest_first = sorted(seg, reverse=True)
    if minimal:
        k = min_k(newest_first)
        if k is not None:
            folded |= set(newest_first[:k])
            return done(mk(), "1")
    folded |= set(seg)
    text = mk()
    if ulen(text) <= limit:
        return done(text, "1")

    # ---- stage 2a: halve the previews
    rn, an = REQ_PREVIEW_CHARS // 2, ANS_PREVIEW_CHARS // 2
    text = mk()
    if ulen(text) <= limit:
        return done(text, "2a")

    # ---- stage 2b: fold small simple turns first (smallest first, newer first on ties)
    small = [t["n"] for t in sorted((t for t in turns if t["n"] not in folded and t.get("bytes", 0) < SMALL_TURN_BYTES),
                                    key=lambda t: (t.get("bytes", 0), -t["n"]))]
    k = min_k(small)
    if k is not None:
        folded |= set(small[:k])
        return done(mk(), "2b")
    folded |= set(small)

    # ---- stage 2c (guarantee): extend the fold backwards from the newest remaining turn
    rest = [t["n"] for t in sorted((t for t in turns if t["n"] not in folded), key=lambda t: -t["n"])]
    k = min_k(rest)
    if k is not None:
        folded |= set(rest[:k])
        return done(mk(), "2c")
    folded |= set(rest)
    text = mk()
    if ulen(text) > limit:  # pathological (e.g. absurdly long directory path): hard cut
        return done(hard_cut(text, limit), "cut")
    return done(text, "2c")


# ----------------------------------------------------------------------------- event handlers
def find_turn(turns, pid):
    for t in reversed(turns):
        if t.get("pid") == pid:
            return t
    return None


def on_prompt(p, info):
    prompt = to_text(p.get("prompt"))
    info["chars"] = len(prompt)
    if is_builtin_command(prompt):
        info["act"] = "skip_builtin"
        return
    pid = pid_of(p)
    tp = p.get("transcript_path")
    sid = session_of(p)
    if not isinstance(p.get("prompt"), str):
        log_error("schema", "UserPromptSubmit without a string 'prompt' (type %s); recorded what could be read"
                  % type(p.get("prompt")).__name__, sid)
    with Store(sid) as st:
        meta = st.load()
        last = meta["turns"][-1] if meta["turns"] else None
        if pid and last is not None and last.get("pid") == pid:
            st.append(last, SEC_REQUEST_EXTRA, prompt)        # typed while that turn was running
            last["nreq"] = last.get("nreq", 0) + 1
            if not last.get("req"):
                last["req"] = request_preview(prompt)
            t, act = last, "append_request"
        else:
            # A fresh prompt is not in the transcript yet when this hook runs (verified on 2.1.332).
            # If the transcript already holds a request for this prompt_id, the prompt was typed while a
            # turn the hook never saw start (one taken from the input queue) was running.
            running = prompt_request(tp, pid, meta.get("tx")) if pid else ""
            if running.strip() and running.strip() != prompt.strip():
                t, act = st.new_turn(meta, pid, "recovered"), "recovered_turn"
                st.append(t, SEC_REQUEST_RECOVERED, running)
                t["req"] = request_preview(running)
                st.append(t, SEC_REQUEST_EXTRA, prompt)
                t["nreq"] = 2
            else:
                kind = "auto" if prompt.lstrip().startswith("<task-notification>") else "user"
                t, act = st.new_turn(meta, pid, kind), "new_turn"
                st.append(t, SEC_REQUEST, prompt)
                t["nreq"] = 1
                t["req"] = request_preview(prompt)
        meta["tx"] = tx_size(tp) or meta.get("tx")
        st.save(meta)
    info.update(act=act, turn=t["n"], kind=t.get("kind"))


def on_stop(p, info):
    pid = pid_of(p)
    tp = p.get("transcript_path")
    answer = to_text(p.get("last_assistant_message"))
    src = "payload"
    if not answer.strip():                            # key omitted when the last message has no text
        answer = last_assistant_text(tail_entries(tp), pid)
        src = "transcript" if answer.strip() else "none"
    info.update(src=src, chars=len(answer))
    with Store(session_of(p)) as st:
        meta = st.load()
        turns = meta["turns"]
        target = None
        if pid:
            target = find_turn(turns, pid)
        elif turns and (turns[-1].get("status") == "open" or p.get("stop_hook_active") is True):
            target = turns[-1]                        # no prompt_id in this version: open/done rule of the spec
        h = sha(answer) if answer.strip() else None
        if h and src == "transcript" and h == meta.get("last_ans"):
            h = None                                  # stale fallback: same text as the previous record
        if target is None and pid and st.reconcile(meta):
            target = find_turn(turns, pid)            # the turn file existed; only meta.json had lost it
        act = None
        if target is None:                            # Stop without a matching prompt -> its own turn
            if h and not pid and h == meta.get("last_ans"):
                info["act"] = "duplicate_answer"      # repeated Stop: must not become a turn of its own
                return
            req = prompt_request(tp, pid, meta.get("tx")) if pid else ""
            if not h and not req.strip():
                info["act"] = "noop"
                return
            target, act = st.new_turn(meta, pid, "orphan"), "orphan_turn"
            if req.strip():
                st.append(target, SEC_REQUEST_RECOVERED, req)
                target["nreq"] = 1
                target["req"] = request_preview(req)
        if h and h != target.get("ah"):
            n = target.get("nans", 0) + 1
            st.append(target, SEC_ANSWER if n == 1 else SEC_ANSWER_MORE % n, answer)
            target["nans"] = n
            target["ah"] = h
            meta["last_ans"] = h
            if not target.get("ans"):
                target["ans"] = answer_preview(answer)
            act = act or "answer"
        else:
            act = act or ("duplicate_answer" if h else "no_answer")
        target["status"] = "done"
        meta["tx"] = tx_size(tp) or meta.get("tx")
        st.save(meta)
    info.update(act=act, turn=target["n"], kind=target.get("kind"))


def on_session_start(p, info):
    src = p.get("source")
    info["source"] = src if isinstance(src, str) else None
    if src != "compact":
        info["act"] = "noop"
        return None
    pid = pid_of(p)
    with Store(session_of(p)) as st:
        meta = st.load()
        added = st.reconcile(meta)
        turns = meta["turns"]
        prev = st.last_compaction()                                   # 1) previous boundary first
        text, r = render_index(turns, prev, st.turns_dir, pid)        # 2) render
        if ulen(text) > MAX_CONTEXT_CHARS:
            text = hard_cut(text, MAX_CONTEXT_CHARS)
        # The snapshot and the boundary are bookkeeping: a failure there (a file locked by an editor,
        # say) is recorded but must not cost the injection itself.
        try:
            with open(os.path.join(st.dir, "index.md"), "wb") as f:   # snapshot, overwritten every time
                f.write((text + "\n\n<!-- %s -->\n" % json.dumps(r, ensure_ascii=False)).encode("utf-8"))
        except Exception as e:
            log_error("index", "index.md snapshot not written (%r)" % (e,), st.sid)
        last = turns[-1] if turns else None                           # 3) record this boundary
        try:
            st.append_line("compactions.jsonl", {
                "ts": now_iso(), "last_turn": last["n"] if last else 0,
                "last_open": bool(last and last.get("nans", 0) == 0 and pid and last.get("pid") == pid),
                "turns": len(turns), "chars": len(text), "utf16": ulen(text),
                "stage": r.get("stage"), "folded": r.get("folded", 0)})
        except Exception as e:
            log_error("compactions", "compaction boundary not recorded (%r)" % (e,), st.sid)
        if added:
            try:
                st.save(meta)
            except Exception as e:
                log_error("meta", "meta.json not saved after re-adding turn files (%r)" % (e,), st.sid)
    info.update(act="inject" if text else "empty_index", stage=r.get("stage"), out=len(text), utf16=ulen(text),
                folded=r.get("folded", 0), turns=len(turns))
    if not text:
        return None
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})


def dispatch(p, info):
    ev = p.get("hook_event_name")
    if p.get("agent_id"):                 # subagent context: no recording, no injection
        info["act"] = "skip_agent"
        return None
    if ev == "UserPromptSubmit":
        on_prompt(p, info)
        return None                       # nothing may be printed here: stdout would enter the context
    if ev == "Stop":
        on_stop(p, info)
        return None
    if ev == "SessionStart":
        return on_session_start(p, info)
    info["act"] = "ignored"
    if not isinstance(ev, str) or not ev:
        log_error("schema", "hook input without a usable hook_event_name (keys: %s)"
                  % ", ".join(sorted(str(k) for k in p.keys())[:40]), None)
    return None


def log_event(p, info, ms):
    """One line of diagnostics per hook call: what arrived and what the hook did with it.
    Holds key names, sizes and ids only - never prompt or answer text - and never creates a
    session directory by itself."""
    try:
        sdir = os.path.join(base_dir(), session_of(p))
        if not os.path.isdir(sdir):
            return
        path = os.path.join(sdir, "events.jsonl")
        try:
            if os.path.getsize(path) > EVENT_LOG_MAX_BYTES:
                return
        except OSError:
            pass
        ev = p.get("hook_event_name")
        rec = {"ts": now_iso(), "v": VERSION, "ev": ev if isinstance(ev, str) else None,
               "act": info.get("act"), "ms": round(ms, 1)}
        pid = pid_of(p)
        if pid:
            rec["pid"] = pid[:80]
        for k in ("turn", "kind", "src", "chars", "source", "stage", "out", "utf16", "folded", "turns", "err"):
            if info.get(k) is not None:
                rec[k] = info[k]
        if ev == "Stop":
            rec["sha"] = p.get("stop_hook_active") is True
        if p.get("agent_id"):
            rec["agent"] = True
        rec["tx"] = tx_size(p.get("transcript_path"))
        rec["keys"] = sorted(str(k)[:60] for k in list(p.keys())[:80])
        with open(path, "ab") as f:
            f.write(json.dumps(rec).encode("ascii") + b"\n")
    except BaseException:
        pass


def handle(p):
    """Process one hook payload (a dict). Returns the text for stdout, or None for no output."""
    t0 = time.perf_counter()
    info = {"act": None}
    try:
        return dispatch(p, info)
    except BaseException as e:
        info["act"], info["err"] = "error", type(e).__name__
        raise
    finally:
        if EVENT_LOG:
            log_event(p, info, (time.perf_counter() - t0) * 1000.0)


def decode_stdin(raw):
    """(text, lossy). The CLI sends UTF-8; a BOM or UTF-16 from an intermediate shell is tolerated."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16"), False
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace"), True


def main():
    out = None
    payload = None
    try:
        text, lossy = decode_stdin(sys.stdin.buffer.read())
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("hook input is not a JSON object (%s)" % type(payload).__name__)
        if lossy:
            log_error("stdin", "hook input was not valid UTF-8; undecodable bytes were replaced", session_of(payload))
        out = handle(payload)
    except BaseException:
        try:
            import traceback
            sid = session_of(payload) if isinstance(payload, dict) else None
            log_error("main", traceback.format_exc()[-4000:], sid)
        except BaseException:
            pass
    try:
        if out:
            sys.stdout.buffer.write(out.encode("ascii", "backslashreplace"))
            sys.stdout.buffer.flush()
    except BaseException:
        pass


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)       # exit code 0 no matter what, even if interpreter shutdown would fail (closed stdout)
