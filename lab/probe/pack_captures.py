#!/usr/bin/env python3
"""Turn raw lab captures into fixtures that are safe to commit.

  python3 pack_captures.py SRC DEST --map OLD=NEW [--map OLD=NEW ...]

SRC holds <name>/payloads.jsonl files written by probe_hook.py / probe_hook2.py.
For every capture this
  * rewrites machine-specific path prefixes (OLD -> NEW, and the dash-slug form the CLI derives
    from a path for its projects directory) and replaces model names with "claude-mock", and
  * when records carry tx_size (probe_hook2.py), writes each referenced transcript to
    DEST/transcripts/ in slim form - only user / assistant / system / queue-operation lines -
    and re-bases every tx_size onto the slim file, so that a replay still sees exactly the
    lines that existed when the hook ran.

Raw transcripts are never copied as they are: they embed CLI-internal prompt snapshots and
API request bodies, and they are an order of magnitude larger.

Lab tooling for schema probing; not part of the deliverable.
"""
import json
import os
import re
import sys

KEEP_TYPES = ("user", "assistant", "system", "queue-operation")
MODEL_NAME = re.compile(rb"claude-[a-z]+-[0-9][A-Za-z0-9.\-]*")   # the mock API serves every model alike
SEEN_MODELS = set()


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def build_maps(pairs):
    maps = []
    for old, new in pairs:
        maps.append((old, new))
        maps.append((slug(old), slug(new)))
    maps.sort(key=lambda m: -len(m[0]))
    return [(o.encode("utf-8"), n.encode("utf-8")) for o, n in maps]


def fix_cut_paths(value, pairs):
    """probe_hook2.py stores 80-char content previews; a path cut off by that limit cannot be
    matched by norm(), so a string ending in a cut-off OLD prefix gets NEW plus an ellipsis."""
    if isinstance(value, dict):
        return {k: fix_cut_paths(v, pairs) for k, v in value.items()}
    if isinstance(value, list):
        return [fix_cut_paths(v, pairs) for v in value]
    if isinstance(value, str):
        for old, new in sorted(pairs, key=lambda p: -len(p[0])):
            for k in range(len(old) - 1, 13, -1):
                if value.endswith(old[:k]):
                    return value[:-k] + new + "…"
    return value


def norm(data, maps):
    for old, new in maps:
        data = data.replace(old, new)
    SEEN_MODELS.update(MODEL_NAME.findall(data))
    return MODEL_NAME.sub(b"claude-mock", data)


class Transcript(object):
    """Slim copy of one transcript plus the mapping original offset -> slim offset."""

    def __init__(self, path, maps):
        self.kept = []
        self.marks = []          # (end offset in the original, end offset in the slim file)
        self.dropped = 0
        orig_end = slim_end = 0
        with open(path, "rb") as f:
            for line in f.read().splitlines(keepends=True):
                orig_end += len(line)
                try:
                    kind = json.loads(line.decode("utf-8")).get("type")
                except Exception:
                    kind = None
                if kind in KEEP_TYPES:
                    out = norm(line, maps)
                    self.kept.append(out)
                    slim_end += len(out)
                else:
                    self.dropped += 1
                self.marks.append((orig_end, slim_end))
        self.orig_size = orig_end
        self.slim_size = slim_end

    def rebase(self, size):
        """Slim size that holds exactly the kept lines complete at original size `size`."""
        out = 0
        for orig_end, slim_end in self.marks:
            if orig_end > size:
                break
            out = slim_end
        return out


def pack(src, dest, pairs):
    maps = build_maps(pairs)
    transcripts = {}
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name, "payloads.jsonl")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rebased = 0
        for row in rows:
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            tp = payload.get("transcript_path")
            if isinstance(row.get("tx_size"), int) and tp:
                if tp not in transcripts:
                    transcripts[tp] = Transcript(tp, maps)
                row["tx_size"] = transcripts[tp].rebase(row["tx_size"])
                rebased += 1
        os.makedirs(os.path.join(dest, name), exist_ok=True)
        with open(os.path.join(dest, name, "payloads.jsonl"), "wb") as f:
            for row in rows:
                row = fix_cut_paths(row, pairs)
                f.write(norm(json.dumps(row, ensure_ascii=False).encode("utf-8"), maps) + b"\n")
        print("%-10s %3d records, %3d tx_size re-based" % (name, len(rows), rebased))
    if transcripts:
        os.makedirs(os.path.join(dest, "transcripts"), exist_ok=True)
    for tp, tx in sorted(transcripts.items()):
        with open(os.path.join(dest, "transcripts", os.path.basename(tp)), "wb") as f:
            f.write(b"".join(tx.kept))
        print("transcript %s: %7d -> %6d bytes (%d lines kept, %d dropped)"
              % (os.path.basename(tp)[:8], tx.orig_size, tx.slim_size, len(tx.kept), tx.dropped))
    print("model names replaced: %d distinct" % len(SEEN_MODELS))


def main(argv):
    pairs, args = [], []
    it = iter(argv)
    for a in it:
        if a == "--map":
            old, _, new = next(it).partition("=")
            pairs.append((old.rstrip("/"), new.rstrip("/")))
        else:
            args.append(a)
    if len(args) != 2 or not pairs:
        sys.exit(__doc__)
    pack(args[0], args[1], pairs)


if __name__ == "__main__":
    main(sys.argv[1:])
