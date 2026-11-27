#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Programmatic grader of the autocompact retention eval (no model judge, deterministic).

    python3 lab/eval/grade.py --selftest     push known-good, known-bad and empty answers through the grader

grade(probe, answer) returns {"correct": 0|1, "abstained": 0|1, "wrong": 0|1, "hedged": 0|1,
"coverage": float|None, "note": str}; exactly one of correct / abstained / wrong is 1.

  value probes      correct when a gold value stands alone in the answer (gen_scenarios.standalone, the
                    same matcher the generator used to plant it) and the answer does not list two or more
                    of the probe's distractors (listing candidates is not recalling one)
  verbatim          correct when at least VERBATIM_MIN of the original request appears in the answer, in
                    order (difflib matching blocks over whitespace-normalised text)
  negative          correct when the answer says the thing is not in the record; anything else is wrong
  otherwise         abstained when the answer says it cannot find / does not know, else wrong

An empty answer is not graded here: the runner records it as an error, not as a model answer.
"""
import difflib
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_scenarios import build_all, standalone  # noqa: E402

VERBATIM_MIN = 0.90
ABSTAIN = re.compile(
    r"찾(을 수|지 못|지 않|을수|아볼 수 없|아지지 않)|확인(할 수|되지|이 안|하지 못|할수)|알 수 없|모르(겠|는|며|고)|기억(이 나지|나지|하지 못|할 수 없)"
    r"|(언급|논의|공유|결정|등장|제시|기재|기록)(되|된|하|이 되)지 않"
    r"|(기록|대화|세션|목록|내용|이력|로그)\S{0,4}\s*(에서|에는|상|엔)?\s*(는\s*)?(없|남아 있지 않|보이지 않|나오지 않)"
    r"|(언급|이야기|논의|공유|결정|정한|정해|말씀|말한|알려 주신|알려주신|주신)\S{0,6}\s*(적|바|내용|기록)\S{0,3}\s*(이|은|는)?\s*없"
    r"|(등장|나오|보이|존재)하?지 않|없었|없습니다|없어요|없네요|없는 것 같|없던 것"
    r"|not (found|mentioned|in the)|no record|don'?t (know|have|see)|could ?n[o']t find|can'?t find|cannot find|no mention",
    re.IGNORECASE)


def norm(text):
    text = unicodedata.normalize("NFC", text or "")
    return text.replace("\r\n", "\n")


def flat(text):
    """Whitespace-normalised text without quote marks, for the verbatim comparison."""
    text = norm(text)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)              # markdown block quotes
    text = re.sub(r"[`\"'“”‘’「」『』]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def coverage(gold, answer):
    g, a = flat(gold), flat(answer)
    if not g:
        return 0.0
    sm = difflib.SequenceMatcher(None, g, a, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / float(len(g))


def abstains(answer):
    return bool(ABSTAIN.search(norm(answer)))


def grade(probe, answer):
    answer = norm(answer)
    out = {"correct": 0, "abstained": 0, "wrong": 0, "hedged": 0, "coverage": None, "note": ""}
    kind = probe["kind"]
    if kind == "negative":
        if abstains(answer):
            out["correct"], out["note"] = 1, "declined: not in the record"
        else:
            out["wrong"], out["note"] = 1, "answered something that never came up"
        return out
    if kind == "verbatim":
        cov = coverage(probe["gold_text"], answer)
        out["coverage"] = round(cov, 3)
        if cov >= VERBATIM_MIN:
            out["correct"], out["note"] = 1, "quoted %.0f%% of the request in order" % (cov * 100)
        elif abstains(answer):
            out["abstained"], out["note"] = 1, "said it could not find the request (coverage %.0f%%)" % (cov * 100)
        else:
            out["wrong"], out["note"] = 1, "not the original wording (coverage %.0f%%)" % (cov * 100)
        return out
    mode = probe.get("match", "token")
    hits = [g for g in probe["gold"] if standalone(answer, g, mode)]
    listed = [d for d in probe.get("distractors", []) if standalone(answer, d, mode)]
    if hits and len(listed) >= 2:
        out["hedged"] = 1
    if hits and not out["hedged"]:
        out["correct"], out["note"] = 1, "gold %s present" % hits[0]
    elif abstains(answer):
        out["abstained"], out["note"] = 1, "said it could not find it"
    else:
        out["wrong"], out["note"] = 1, ("listed %d candidates" % (len(listed) + len(hits))) if out["hedged"] else "gold absent"
    return out


def _wrong_value(probe):
    if probe.get("distractors"):
        return probe["distractors"][0]
    g = probe["gold"][0]
    digits = [i for i, c in enumerate(g) if c.isdigit()]
    if digits:
        i = digits[-1]
        return g[:i] + str((int(g[i]) + 1) % 10) + g[i + 1:]
    return g + "x"


def selftest():
    """Oracle, null, wrong and hedged answers for every probe of every scenario (eval-audit 'harness tested
    on known-good and known-bad'). Returns the number of failures."""
    fails, n = 0, 0
    for sc in build_all():
        for p in sc["probes"]:
            cases = []
            if p["kind"] == "negative":
                cases += [("그런 내용은 이 세션 기록에서 찾을 수 없습니다.", "correct"),
                          ("%s 이야기는 한 적이 없어요." % p["absent_word"], "correct"),
                          ("이번 세션에서 %s는 언급되지 않았습니다." % p["absent_word"], "correct"),
                          ("턴 파일을 확인했지만 찾아볼 수 없었습니다.", "correct"),
                          ("모르겠습니다.", "correct"),
                          ("payment-consumers 입니다.", "wrong"),
                          ("", "wrong")]
            elif p["kind"] == "verbatim":
                g = p["gold_text"]
                cases += [("원문은 다음과 같습니다.\n\n> %s" % g, "correct"),
                          ("```\n%s\n```" % g, "correct"),
                          ("재시도 정책을 바꾸기 전에 타임아웃 차이, idempotency key, 알림 채널 세 가지를 확인하자고 하셨습니다.", "wrong"),
                          (g[: len(g) // 2], "wrong"),
                          ("그 요청은 기록에서 찾을 수 없습니다.", "abstained"),
                          ("", "wrong")]
            else:
                g = p["gold"][0]
                unit = "ms" if p["kind"] == "decision_reason" else ("번" if p["kind"] == "user_fact" else "")
                cases += [("확인해 보니 `%s`%s입니다." % (g, unit), "correct"),
                          ("%s%s" % (g, unit), "correct"),
                          ("모르겠습니다.", "abstained"),
                          ("기록에서 찾을 수 없습니다.", "abstained"),
                          ("%s입니다." % _wrong_value(p), "wrong"),
                          ("", "wrong")]
                if len(p.get("distractors", [])) >= 2:
                    cases.append(("%s, %s, %s 중 하나입니다." % (g, p["distractors"][0], p["distractors"][1]), "wrong"))
            for answer, expect in cases:
                n += 1
                got = grade(p, answer)
                label = [k for k in ("correct", "abstained", "wrong") if got[k]]
                if label != [expect] or sum(got[k] for k in ("correct", "abstained", "wrong")) != 1:
                    fails += 1
                    print("FAIL %s/%s expected %s got %s for %r" % (sc["id"], p["id"], expect, label, answer[:80]))
    print("grader self-test: %d answers, %d failures" % (n, fails))
    return fails


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(1 if selftest() else 0)
    print(__doc__)
