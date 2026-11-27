#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local stand-in for the Messages API, used only to check the eval pipeline end to end for free.
It measures nothing about any model: every answer is scripted.

    MOCK_KEY=<probe key.json> MOCK_PROBE_MODE=oracle|null|wrong|search python3 mock_eval_api.py PORT LOG

- usage: input tokens = request characters / MOCK_CHARS_PER_TOKEN (default 3.0) x MOCK_TOKEN_SCALE (default 1),
  so the CLI's own autocompact logic fires as the conversation grows, as it would with the real API.
- compaction: a summary that lists the first 150 characters of every user message (the real prompt asks
  for "All user messages"), so short user statements survive compaction and long pastes do not.
- build turns: a short canned reply; the "highest p99" request gets the endpoint actually read off the table.
- probes (questions listed in MOCK_KEY): oracle answers the gold, null says it does not know, wrong gives a
  wrong value, search first runs Grep over the turn directory named in the injected index (or, without
  one, over the transcript the CLI points to) and then answers the gold.
LOG gets one line of metadata per request (sizes, kind, reply head), never the request bodies.
"""
import itertools
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
LOG = sys.argv[2] if len(sys.argv) > 2 else "mock-requests.jsonl"
CPT = float(os.environ.get("MOCK_CHARS_PER_TOKEN", "3.0"))
SCALE = float(os.environ.get("MOCK_TOKEN_SCALE", "1"))
MODE = os.environ.get("MOCK_PROBE_MODE", "oracle")
KEY = {}
if os.environ.get("MOCK_KEY"):
    for p in json.load(open(os.environ["MOCK_KEY"], encoding="utf-8")):
        KEY[p["question"]] = p
HEADER = "이 세션에서 있었던 턴의 목록입니다"
_counter = itertools.count(1)
_lock = threading.Lock()


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def strip_reminders(text):
    return re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S).strip()


def has_tool_result(content):
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def last_prompt(msgs):
    for m in reversed(msgs):
        if m.get("role") == "user" and not has_tool_result(m.get("content")):
            t = strip_reminders(text_of(m.get("content")))
            if t:
                return t
    return ""


def probe_answer(p, mode):
    kind = p["kind"]
    if mode == "null":
        return "모르겠습니다."
    if mode == "wrong":
        if kind == "negative":
            return "consumer-group-7 입니다."
        if kind == "verbatim":
            return "재시도 정책 관련해서 몇 가지를 확인하자고 하셨습니다."
        return "%s 입니다." % ((p.get("distractors") or ["0000"])[0])
    if kind == "negative":
        return "그런 내용은 이 세션 기록에서 찾을 수 없습니다."
    if kind == "verbatim":
        return "원문은 다음과 같습니다.\n\n> %s" % p["gold_text"]
    return "확인해 보니 `%s`입니다." % p["gold"][0]


def highest_p99(prompt):
    best = None
    for line in prompt.splitlines():
        parts = line.split(",")
        if len(parts) == 7 and parts[1].startswith("/") and parts[5].isdigit():
            if best is None or int(parts[5]) > best[1]:
                best = (parts[1], int(parts[5]))
    return best


def plan(body):
    msgs = body.get("messages") or []
    n = next(_counter)
    size = len(json.dumps(body.get("system"), ensure_ascii=False)) + len(json.dumps(body.get("tools"), ensure_ascii=False)) \
        + len(json.dumps(msgs, ensure_ascii=False))
    usage_in = int(size / CPT * SCALE)
    lu = msgs[-1] if msgs else {}
    lt = text_of(lu.get("content"))
    tools = [t.get("name") for t in body.get("tools") or []]
    if "create a detailed summary" in lt:
        users = [strip_reminders(text_of(m.get("content"))) for m in msgs[:-1] if m.get("role") == "user" and not has_tool_result(m.get("content"))]
        listed = "\n".join("   - %s" % u.replace("\n", " ")[:150] for u in users if u)
        return n, "compact", [{"type": "text", "text": "<analysis>mock</analysis>\n<summary>\n1. Primary Request and Intent: mock session.\n"
                                                        "6. All user messages:\n%s\n</summary>" % listed}], "end_turn", usage_in
    prompt = last_prompt(msgs)
    p = KEY.get(prompt)
    if p is not None:
        if has_tool_result(lu.get("content")) or MODE != "search":
            return n, "probe", [{"type": "text", "text": probe_answer(p, "oracle" if MODE == "search" else MODE)}], "end_turn", usage_in
        blob = "\n".join(text_of(m.get("content")) for m in msgs)
        m = re.search(r"디렉터리: (.+?) \(턴 \d+개\)", blob)
        path = m.group(1).strip() if m else None
        if path is None:
            t = re.search(r"read the full transcript at: (\S+\.jsonl)", blob)
            path = t.group(1) if t else None
        if path and "Grep" in tools:
            return n, "probe-search", [{"type": "tool_use", "id": "toolu_eval%06d" % n, "name": "Grep",
                                        "input": {"pattern": "trace|code=|ms", "path": path, "output_mode": "count"}}], "tool_use", usage_in
        return n, "probe", [{"type": "text", "text": probe_answer(p, "oracle")}], "end_turn", usage_in
    if has_tool_result(lu.get("content")):
        return n, "after-tool", [{"type": "text", "text": "도구 결과를 확인했습니다."}], "end_turn", usage_in
    if "p99_ms가 가장 높은 행" in prompt:
        best = highest_p99(prompt)
        text = "표 전체에서 p99_ms가 가장 높은 행은 `%s`, %dms입니다." % best if best else "표를 읽지 못했습니다."
        return n, "build-derived", [{"type": "text", "text": text}], "end_turn", usage_in
    if "'확인'이라고만 답해 줘" in prompt:
        return n, "tail", [{"type": "text", "text": "확인"}], "end_turn", usage_in
    return n, "build", [{"type": "text", "text": "확인했습니다. 눈에 띄는 점을 짧게 정리했습니다. (모의 답변 #%d)" % n}], "end_turn", usage_in


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "mock"}})

    def do_POST(self):
        ln = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(ln) if ln else b""
        if (self.headers.get("content-encoding") or "").lower() == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        body = json.loads(raw.decode("utf-8")) if raw else {}
        path = self.path.split("?")[0]
        if path.endswith("/count_tokens"):
            return self._json(200, {"input_tokens": int(len(raw) / CPT * SCALE)})
        if not path.endswith("/v1/messages"):
            return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "mock"}})
        n, kind, blocks, stop, usage_in = plan(body)
        with _lock, open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "n": n, "kind": kind, "model": body.get("model"), "bytes": len(raw),
                                "usage_in": usage_in, "n_messages": len(body.get("messages") or []),
                                "reply": json.dumps(blocks, ensure_ascii=False)[:200]}, ensure_ascii=False) + "\n")
        model = body.get("model") or "claude-mock"
        usage = {"input_tokens": usage_in, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 40}
        msg = {"id": "msg_eval%08d" % n, "type": "message", "role": "assistant", "model": model, "content": blocks,
               "stop_reason": stop, "stop_sequence": None, "usage": usage}
        if not body.get("stream"):
            return self._json(200, msg)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()

        def ev(name, data):
            self.wfile.write(("event: %s\ndata: %s\n\n" % (name, json.dumps(data, ensure_ascii=False))).encode("utf-8"))
            self.wfile.flush()

        ev("message_start", {"type": "message_start", "message": dict(msg, content=[], stop_reason=None)})
        for i, b in enumerate(blocks):
            if b["type"] == "text":
                ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}})
            else:
                ev("content_block_start", {"type": "content_block_start", "index": i,
                                           "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
                ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                           "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}})
            ev("content_block_stop", {"type": "content_block_stop", "index": i})
        ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 40}})
        ev("message_stop", {"type": "message_stop"})
        self.close_connection = True


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print("eval mock api on %d (mode %s, %d probes)" % (PORT, MODE, len(KEY)), flush=True)
    srv.serve_forever()
