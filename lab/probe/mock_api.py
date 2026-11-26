#!/usr/bin/env python3
"""Minimal local mock of the Anthropic Messages API, used only to drive the real
Claude Code CLI offline so that genuine hook payloads can be captured.
Lab tooling for schema probing; not part of the deliverable.

  MOCK_BIG_TOKENS=990000 MOCK_SLOW_SECS=8 python3 mock_api.py [port] [request-log.jsonl]

The request log stores full API request bodies (CLI system prompt included): keep it out of git."""
import json, sys, time, threading, itertools, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = sys.argv[2] if len(sys.argv) > 2 else "requests.jsonl"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
_counter = itertools.count(1)
_lock = threading.Lock()
SLOW_IDS = set()


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(out)


def has_tool_result(content):
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def last_tool_name(messages):
    """Name of the tool the assistant called last (None if its last message called none)."""
    for m in reversed(messages or []):
        if m.get("role") == "assistant":
            names = [b.get("name") for b in m.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
            return names[-1] if names else None
    return None


def last_user(messages):
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return m
    return {"content": ""}


def plan(body):
    """Decide the canned response: list of content blocks + stop_reason + usage."""
    msgs = body.get("messages", [])
    lu = last_user(msgs)
    lt = text_of(lu.get("content"))
    tools = [t.get("name") for t in body.get("tools", []) or []]
    n = next(_counter)
    usage_in = 1200
    # find the last "real" user prompt text (skip pure tool_result messages)
    prompt_text = ""
    for m in reversed(msgs):
        if m.get("role") == "user" and not has_tool_result(m.get("content")):
            prompt_text = text_of(m.get("content"))
            break
    sys_text = body.get("system")
    if isinstance(sys_text, list):
        sys_text = "\n".join(b.get("text", "") for b in sys_text if isinstance(b, dict))
    sys_text = sys_text or ""
    is_compact = ("create a detailed summary" in lt) or ("summary of the conversation" in lt.lower()) or ("summarize" in sys_text.lower() and "conversation" in sys_text.lower() and not tools)
    if is_compact:
        return n, [{"type": "text", "text": "<analysis>mock analysis</analysis>\n<summary>\nMOCK-COMPACT-SUMMARY #%d: the user asked several probe questions.\n</summary>" % n}], "end_turn", usage_in
    if has_tool_result(lu.get("content")):
        if last_tool_name(msgs) == "Read":      # [[READTURN]]: report what the Read of a turn file returned
            got = " ".join(str(b.get("content"))[:200] for b in lu["content"] if isinstance(b, dict) and b.get("type") == "tool_result")
            return n, [{"type": "text", "text": "턴 파일을 읽은 결과입니다 (#%d): %s" % (n, got.replace("\n", " ")[:200])}], "end_turn", usage_in
        return n, [{"type": "text", "text": "## 결과\n\n도구 실행을 마쳤습니다. 최종 답변 #%d 입니다.\n\n- 항목 A\n- 항목 B" % n}], "end_turn", usage_in
    if "[[SLOW]]" in prompt_text:
        SLOW_IDS.add(n)
    if "[[TOOL]]" in prompt_text and "Bash" in tools:
        return n, [{"type": "text", "text": "먼저 도구를 실행해 보겠습니다. (중간 내레이션 #%d)" % n},
                   {"type": "tool_use", "id": "toolu_mock%06d" % n, "name": "Bash", "input": {"command": "echo probe-tool", "description": "probe"}}], "tool_use", usage_in
    if "[[AGENT]]" in prompt_text and ("Agent" in tools or "Task" in tools):
        nm = "Agent" if "Agent" in tools else "Task"
        return n, [{"type": "tool_use", "id": "toolu_mock%06d" % n, "name": nm,
                    "input": {"description": "probe subagent", "prompt": "Reply with the single word SUBAGENT-PONG.", "subagent_type": "general-purpose"}}], "tool_use", usage_in
    if "[[READTURN]]" in prompt_text and "Read" in tools:
        # Act like a model that follows the injected ctx-index table of contents: read the first turn file.
        m = re.search(r"디렉터리: (.+?) \(턴 \d+개\)", "\n".join(text_of(x.get("content")) for x in msgs))
        if m:
            d = m.group(1)
            return n, [{"type": "tool_use", "id": "toolu_mock%06d" % n, "name": "Read",
                        "input": {"file_path": d + ("\\" if "\\" in d else "/") + "0001.md"}}], "tool_use", usage_in
        return n, [{"type": "text", "text": "주입된 목차를 찾지 못했습니다 (#%d)." % n}], "end_turn", usage_in
    if "[[BIG]]" in prompt_text:
        usage_in = int(os.environ.get("MOCK_BIG_TOKENS", "190000"))
    if "[[SLOW]]" in prompt_text:
        SLOW_IDS.add(n)
    if "[[EMPTY]]" in prompt_text:
        return n, [{"type": "text", "text": ""}], "end_turn", usage_in
    head = prompt_text.strip().replace("\n", " ")[:60]
    return n, [{"type": "text", "text": "안녕하세요!\n\n# 답변 %d\n\n요청하신 내용(%s)에 대한 모의 답변입니다. 한글·emoji 🙂 포함.\n\n```python\nprint('ok')\n```" % (n, head)}], "end_turn", usage_in


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.send_header("request-id", "req_mock")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        with _lock, open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "method": "GET", "path": self.path}) + "\n")
        self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "mock"}})

    def do_POST(self):
        ln = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(ln) if ln else b""
        enc = (self.headers.get("content-encoding") or "").lower()
        if enc == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            body = {"_raw": raw[:200].decode("utf-8", "replace")}
        path = self.path.split("?")[0]
        rec = {"t": time.time(), "method": "POST", "path": self.path}
        if path.endswith("/count_tokens"):
            rec["kind"] = "count_tokens"
            with _lock, open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            return self._json(200, {"input_tokens": 1000})
        if not path.endswith("/v1/messages"):
            rec["kind"] = "other"
            with _lock, open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "mock"}})
        n, blocks, stop, usage_in = plan(body)
        rec.update({"kind": "messages", "n": n, "model": body.get("model"), "stream": body.get("stream"),
                    "n_tools": len(body.get("tools") or []), "n_messages": len(body.get("messages") or []),
                    "system": body.get("system"), "messages": body.get("messages"), "reply": blocks, "stop": stop})
        with _lock, open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        model = body.get("model") or "claude-mock"
        usage = {"input_tokens": usage_in, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 50}
        msg = {"id": "msg_mock%08d" % n, "type": "message", "role": "assistant", "model": model, "content": blocks,
               "stop_reason": stop, "stop_sequence": None, "usage": usage}
        if not body.get("stream"):
            return self._json(200, msg)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("request-id", "req_mock%08d" % n)
        self.send_header("connection", "close")
        self.end_headers()

        def ev(name, data):
            self.wfile.write(("event: %s\ndata: %s\n\n" % (name, json.dumps(data, ensure_ascii=False))).encode("utf-8"))
            self.wfile.flush()

        start = dict(msg, content=[], stop_reason=None)
        ev("message_start", {"type": "message_start", "message": start})
        for i, b in enumerate(blocks):
            if b["type"] == "text":
                ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                if b["text"]:
                    if n in SLOW_IDS:
                        ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": "느린 답변 시작… "}})
                        time.sleep(float(os.environ.get("MOCK_SLOW_SECS", "12")))
                    ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}})
            else:
                ev("content_block_start", {"type": "content_block_start", "index": i,
                                           "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
                ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                           "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}})
            ev("content_block_stop", {"type": "content_block_stop", "index": i})
        ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 50}})
        ev("message_stop", {"type": "message_stop"})
        self.close_connection = True


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print("mock api on", PORT, "log", LOG, flush=True)
    srv.serve_forever()
