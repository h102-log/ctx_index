#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctx-index PROTOTYPE - lab artifact used for the pre-approval simulation (step 3).

Not the deliverable hook. It exists to check the turn-attribution state machine, the index
rendering and the two-stage folding against lab data before the real hook is written.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
import traceback

# ----------------------------------------------------------------------------- tunables
MAX_CONTEXT_CHARS = 6000          # cap on hookSpecificOutput.additionalContext
REQ_PREVIEW_CHARS = 70
ANS_PREVIEW_CHARS = 90
STORED_PREVIEW_CHARS = 240        # meta.json keeps longer clean previews; render truncates
PREVIEW_SCAN_CHARS = 20000        # previews never look past this much text (keeps huge inputs cheap)
PREVIEW_LINE_CHARS = 2000         # ...and never clean more than this much of one line
FIRST_COMPACTION_FOLD_TURNS = 5
SMALL_TURN_BYTES = 500
STAGE1_MINIMAL = False            # counter-proposal: fold only as many newest turns as needed
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


# ----------------------------------------------------------------------------- small utils
def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


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
    if not isinstance(sid, str) or not sid.strip():
        return None
    s = re.sub(r"[^A-Za-z0-9._-]", "_", sid.strip()).strip(". ")
    if not s:
        return None
    if s != sid or len(s) > 80 or s.split(".")[0].upper() in _RESERVED:
        s = s[:60] + "-" + hashlib.sha1(sid.encode("utf-8", "replace")).hexdigest()[:8]
    return s


def base_dir():
    return os.environ.get("CTX_INDEX_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "ctx-index")


# ----------------------------------------------------------------------------- previews
_TAG = re.compile(r"</?[A-Za-z][\w:.-]{0,40}(?:\s[^<>]{0,120})?/?>")
_LEAD = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>+\s?|[-*+]\s+(?:\[[ xX]\]\s+)?|\d{1,3}[.)]\s+)+")
_GREET = re.compile(
    r"^(?:안녕하세요|안녕하십니까|반갑습니다|네|넵|예|알겠습니다|좋습니다|좋아요|확인했습니다|물론입니다|물론이죠|감사합니다|"
    r"hello|hi|hey|sure|okay|ok|got it|understood|certainly|of course|great|absolutely|thanks|thank you|alright|"
    r"all right|no problem)(?=[\s!.,~…:)]|$)[\s!.,~…:)]*", re.I)
_WORDCH = re.compile(r"[0-9A-Za-zÀ-ɏͰ-ϿЀ-ӿ぀-ヿ㐀-鿿가-힣]")


def clean_inline(s):
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = _TAG.sub(" ", s)
    s = re.sub(r"`{1,3}", "", s)
    s = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])\*(?=\S)([^*]+?)(?<=\S)\*(?![\w*])", r"\1", s)
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
        return cut(("[작업 알림] " + clean_inline(m.group(1)[:PREVIEW_LINE_CHARS])) if m else "[작업 알림]", STORED_PREVIEW_CHARS)
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
    """First meaningful sentence: skip greeting-only lines, bare headers, rules, code fences."""
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
class Store(object):
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
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lock_path) > LOCK_STALE_SECS:
                        os.remove(self.lock_path)
                        continue
                except OSError:
                    pass
            except OSError:
                pass
            if time.monotonic() >= deadline:
                log_error(self.dir, "lock", "timeout waiting for lock; continuing without it")
                return self
            time.sleep(0.02)

    def __exit__(self, *exc):
        if self.held:
            try:
                os.remove(self.lock_path)
            except OSError:
                pass
        return False

    # -- meta
    def load(self):
        try:
            with open(self.meta_path, "rb") as f:
                meta = json.loads(f.read().decode("utf-8"))
            if not isinstance(meta, dict) or not isinstance(meta.get("turns"), list):
                raise ValueError("unexpected meta shape")
            meta["turns"] = [t for t in meta["turns"] if isinstance(t, dict) and isinstance(t.get("n"), int)]
            return meta
        except FileNotFoundError:
            pass
        except Exception as e:
            log_error(self.dir, "meta", "meta.json unreadable (%r); rebuilding from turn files" % (e,))
            try:
                os.replace(self.meta_path, self.meta_path + ".bad-%d" % int(time.time()))
            except OSError:
                pass
        return {"schema": 1, "session_id": self.sid, "created": now_iso(), "turns": self.rebuild()}

    def rebuild(self):
        turns = []
        try:
            names = sorted(n for n in os.listdir(self.turns_dir) if re.match(r"^\d{4,}\.md$", n))
        except OSError:
            names = []
        for name in names:
            try:
                with open(os.path.join(self.turns_dir, name), "rb") as f:
                    body = f.read().decode("utf-8", "replace")
            except OSError:
                continue
            secs = re.split(r"(?m)^## ◇ (추가 요청|요청|답변)[^\n]*\n\n", body)
            reqs = [secs[i + 1] for i in range(1, len(secs) - 1, 2) if secs[i] in ("요청", "추가 요청")]
            anss = [secs[i + 1] for i in range(1, len(secs) - 1, 2) if secs[i] == "답변"]
            m = re.search(r"prompt ([0-9A-Za-z-]{8,})", body.split("\n", 1)[0])
            turns.append({"n": int(name[:-3]), "pid": m.group(1) if m else None, "status": "done" if anss else "open",
                          "t0": "", "t1": "", "req": request_preview(reqs[0]) if reqs else "",
                          "ans": answer_preview(anss[0]) if anss else "", "nreq": len(reqs), "nans": len(anss),
                          "bytes": sum(len(x.rstrip("\n").encode("utf-8")) for x in reqs + anss), "ah": None, "kind": "rebuilt"})
        return turns

    def save(self, meta):
        meta["updated"] = now_iso()
        data = json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8")
        tmp = "%s.tmp%d" % (self.meta_path, os.getpid())
        with open(tmp, "wb") as f:
            f.write(data)
        for i in range(10):
            try:
                os.replace(tmp, self.meta_path)
                return
            except PermissionError:
                time.sleep(0.02 * (i + 1))
        with open(self.meta_path, "wb") as f:
            f.write(data)
        try:
            os.remove(tmp)
        except OSError:
            pass

    # -- turn files
    def turn_path(self, n):
        return os.path.join(self.turns_dir, "%04d.md" % n)

    def next_n(self, meta):
        n = (meta["turns"][-1]["n"] + 1) if meta["turns"] else 1
        while os.path.exists(self.turn_path(n)):
            n += 1
        return n

    def new_turn(self, meta, pid, kind):
        n = self.next_n(meta)
        with open(self.turn_path(n), "wb") as f:
            f.write(("<!-- ctx-index | turn %04d | session %s | prompt %s -->\n" % (n, self.sid, pid or "-")).encode("utf-8"))
        t = {"n": n, "pid": pid, "status": "open", "t0": now_iso(), "t1": now_iso(), "req": "", "ans": "",
             "nreq": 0, "nans": 0, "bytes": 0, "ah": None, "kind": kind}
        meta["turns"].append(t)
        return t

    def append(self, t, label, text):
        with open(self.turn_path(t["n"]), "ab") as f:
            f.write(("\n## ◇ %s · %s\n\n" % (label, now_iso())).encode("utf-8") + text.encode("utf-8") + b"\n")
        t["bytes"] += len(text.encode("utf-8"))
        t["t1"] = now_iso()

    def append_line(self, name, obj):
        with open(os.path.join(self.dir, name), "ab") as f:
            f.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")

    def last_compaction(self):
        last = None
        try:
            with open(os.path.join(self.dir, "compactions.jsonl"), "rb") as f:
                for line in f:
                    try:
                        o = json.loads(line.decode("utf-8"))
                        if isinstance(o, dict) and isinstance(o.get("last_turn"), int):
                            last = o
                    except Exception:
                        continue
        except OSError:
            pass
        return last


def log_error(sdir, where, msg):
    rec = {"ts": now_iso(), "where": where, "error": msg}
    for d in (sdir, base_dir()):
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "errors.jsonl"), "ab") as f:
                f.write(json.dumps(rec, ensure_ascii=False).encode("utf-8") + b"\n")
            return
        except Exception:
            continue


# ----------------------------------------------------------------------------- transcript access
def tx_size(path):
    try:
        return os.path.getsize(path) if isinstance(path, str) and path else None
    except OSError:
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
        if b'"type":"user"' not in ln and b'"type":"assistant"' not in ln:
            continue
        try:
            e = json.loads(ln.decode("utf-8", "replace"))
        except Exception:
            continue
        if isinstance(e, dict) and e.get("type") in ("user", "assistant") and not e.get("isSidechain"):
            out.append(e)
    return out


def _has_text(e):
    if e.get("type") != "assistant" or e.get("isApiErrorMessage"):
        return False
    msg = e.get("message") or {}
    return msg.get("model") != "<synthetic>" and bool(to_text(msg.get("content")).strip())


def tail_entries(path):
    """Main-chain user/assistant entries from the end of the transcript (bounded, grows only if needed)."""
    size = tx_size(path)
    if not size:
        return []
    span = TAIL_BYTES
    while True:
        start = max(0, size - span)
        try:
            out = _parse_lines(_read(path, start, size - start), start > 0)
        except OSError:
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
    mid = (entries[i].get("message") or {}).get("id")
    j = i
    while j - 1 >= 0 and mid and entries[j - 1].get("type") == "assistant" and (entries[j - 1].get("message") or {}).get("id") == mid:
        j -= 1
    if pid:  # the nearest earlier user entry tells which prompt this text belongs to
        k = j - 1
        while k >= 0 and not (entries[k].get("type") == "user" and entries[k].get("promptId")):
            k -= 1
        if k >= 0 and entries[k].get("promptId") != pid:
            return ""
    texts = (to_text((entries[k].get("message") or {}).get("content")) for k in range(j, i + 1))
    return "\n".join(x for x in texts if x.strip()).strip()


def prompt_request(path, pid, hint):
    """The request text the transcript recorded for prompt `pid` ('' when it is not there).

    `hint` is the transcript size at this session's previous hook event: a turn the hook has not
    seen yet starts right after it, so a short forward read finds its first entry cheaply.
    """
    if not pid or not re.match(r"^[0-9A-Za-z_-]{6,80}$", pid):
        return ""
    size = tx_size(path)
    if not size:
        return ""
    needle = ('"promptId":"%s"' % pid).encode("ascii")
    spans = []
    if isinstance(hint, int) and 0 <= hint < size:
        spans.append((hint, min(size - hint, FORWARD_BYTES)))
    spans.append((max(0, size - TAIL_BYTES), min(size, TAIL_BYTES)))
    for start, length in spans:
        try:
            data = _read(path, start, length)
            if needle not in data:
                continue
            drop = start > 0 and _read(path, start - 1, 1) != b"\n"
        except OSError:
            continue
        parts = []
        for e in _parse_lines(data, drop):
            if e.get("type") == "assistant" and parts:
                break
            if e.get("type") == "user" and e.get("promptId") == pid and not e.get("isMeta") and not e.get("isCompactSummary"):
                c = (e.get("message") or {}).get("content")
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
    if t.get("req"):
        suf = " (+%d)" % (t["nreq"] - 1) if t.get("nreq", 1) > 1 else ""
        req = cut(t["req"], rn - len(suf)) + suf
    else:
        req = "(빈 요청)" if t.get("nreq", 0) else NO_REQUEST
    if t.get("nans", 0) > 0:
        suf = " (+%d)" % (t["nans"] - 1) if t["nans"] > 1 else ""
        ans = cut(t.get("ans") or "(텍스트 없음)", an - len(suf)) + suf
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


def render_index(turns, prev, turns_dir, inflight_pid=None, limit=None, minimal=None):
    limit = MAX_CONTEXT_CHARS if limit is None else limit
    minimal = STAGE1_MINIMAL if minimal is None else minimal
    info = {"stage": "full", "turns": len(turns), "folded": 0, "preview": [REQ_PREVIEW_CHARS, ANS_PREVIEW_CHARS]}
    if not turns:
        return "", dict(info, stage="empty", chars=0)
    rn, an = REQ_PREVIEW_CHARS, ANS_PREVIEW_CHARS
    folded = set()

    def mk(extra=()):
        return build(turns, folded | set(extra), rn, an, turns_dir, inflight_pid)

    def done(text, stage):
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
    if prev is None or prev.get("last_turn", 0) <= 0:
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
        while ulen(text) > limit:
            text = text[:max(0, len(text) - max(1, (ulen(text) - limit)))]
        return done(text, "cut")
    return done(text, "2c")


# ----------------------------------------------------------------------------- event handlers
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


def on_prompt(p):
    prompt = to_text(p.get("prompt"))
    if is_builtin_command(prompt):
        return None
    pid = pid_of(p)
    with Store(session_of(p)) as st:
        meta = st.load()
        last = meta["turns"][-1] if meta["turns"] else None
        tp = p.get("transcript_path")
        if pid and last is not None and last.get("pid") == pid:
            st.append(last, "추가 요청 (작업 중 입력)", prompt)   # typed while that turn was running
            last["nreq"] = last.get("nreq", 0) + 1
            if not last.get("req"):
                last["req"] = request_preview(prompt)
        else:
            # A fresh prompt is not in the transcript yet when this hook runs (verified on 2.1.332).
            # If the transcript already holds a request for this prompt_id, the prompt was typed while a
            # turn the hook never saw start (one taken from the input queue) was running.
            running = prompt_request(tp, pid, meta.get("tx")) if pid else ""
            if running.strip() and running.strip() != prompt.strip():
                t = st.new_turn(meta, pid, "recovered")
                st.append(t, "요청 (트랜스크립트에서 복원)", running)
                t["req"] = request_preview(running)
                st.append(t, "추가 요청 (작업 중 입력)", prompt)
                t["nreq"] = 2
            else:
                t = st.new_turn(meta, pid, "auto" if prompt.lstrip().startswith("<task-notification>") else "user")
                st.append(t, "요청", prompt)
                t["nreq"] = 1
                t["req"] = request_preview(prompt)
        meta["tx"] = tx_size(tp) or meta.get("tx")
        st.save(meta)
    return None


def on_stop(p):
    pid = pid_of(p)
    answer = to_text(p.get("last_assistant_message"))
    src = "payload"
    tp = p.get("transcript_path")
    if not answer.strip():
        answer = last_assistant_text(tail_entries(tp), pid)
        src = "transcript" if answer.strip() else "none"
    with Store(session_of(p)) as st:
        meta = st.load()
        turns = meta["turns"]
        target = None
        if pid:
            for t in reversed(turns):
                if t.get("pid") == pid:
                    target = t
                    break
        elif turns and (turns[-1].get("status") == "open" or p.get("stop_hook_active") is True):
            target = turns[-1]
        h = sha(answer) if answer.strip() else None
        if h and src == "transcript" and h == meta.get("last_ans"):
            h = None                                  # stale fallback: same text as the previous record
        if target is None:                            # Stop without a matching prompt -> its own turn
            req = prompt_request(tp, pid, meta.get("tx")) if pid else ""
            if not h and not req.strip():
                return None
            target = st.new_turn(meta, pid, "orphan")
            if req.strip():
                st.append(target, "요청 (트랜스크립트에서 복원)", req)
                target["nreq"] = 1
                target["req"] = request_preview(req)
        if h and h != target.get("ah"):
            n = target.get("nans", 0) + 1
            st.append(target, "답변" if n == 1 else "답변 (이어짐 %d)" % n, answer)
            target["nans"] = n
            target["ah"] = h
            meta["last_ans"] = h
            if not target.get("ans"):
                target["ans"] = answer_preview(answer)
        target["status"] = "done"
        meta["tx"] = tx_size(tp) or meta.get("tx")
        st.save(meta)
    return None


def on_session_start(p):
    if p.get("source") != "compact":
        return None
    pid = pid_of(p)
    with Store(session_of(p)) as st:
        meta = st.load()
        turns = meta["turns"]
        prev = st.last_compaction()                                   # 1) previous boundary first
        text, info = render_index(turns, prev, st.turns_dir, pid)     # 2) render
        with open(os.path.join(st.dir, "index.md"), "wb") as f:
            f.write((text + "\n\n<!-- %s -->\n" % json.dumps(info, ensure_ascii=False)).encode("utf-8"))
        last = turns[-1] if turns else None                           # 3) record this boundary
        st.append_line("compactions.jsonl", {
            "ts": now_iso(), "last_turn": last["n"] if last else 0,
            "last_open": bool(last and last.get("nans", 0) == 0 and pid and last.get("pid") == pid),
            "turns": len(turns), "chars": info.get("chars", 0), "stage": info.get("stage"), "folded": info.get("folded", 0)})
    if not text:
        return None
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})


def handle(p):
    if not isinstance(p, dict) or p.get("agent_id"):
        return None
    ev = p.get("hook_event_name")
    if ev == "UserPromptSubmit":
        return on_prompt(p)
    if ev == "Stop":
        return on_stop(p)
    if ev == "SessionStart":
        return on_session_start(p)
    return None


def main():
    out = None
    try:
        raw = sys.stdin.buffer.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", "replace")
        out = handle(json.loads(text))
    except BaseException:
        try:
            log_error(base_dir(), "main", traceback.format_exc()[-2000:])
        except BaseException:
            pass
    try:
        if out:
            sys.stdout.buffer.write(out.encode("utf-8"))
            sys.stdout.buffer.flush()
    except BaseException:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
