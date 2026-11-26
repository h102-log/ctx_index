#!/usr/bin/env python3
"""Prepare the throwaway run directory used by run_cli.sh / drive.py / tui_drive.py.

  python3 setup_lab.py [--fresh]

Creates (under $CTX_LAB_RUN, default: .run/ next to this file, which is git-ignored):
  home/      fake HOME for the CLI: onboarding done, mock API key approved, test project trusted
  proj/      test project (its own git repository, with the custom slash command /mycmd)
  settings/  hook settings rendered from settings/*.json (absolute script paths filled in)
  out/       where captured hook payloads, driver logs and the mock API request log go

Lab tooling for schema probing; not part of the deliverable.
"""
import json
import os
import shutil
import subprocess
import sys

P = os.path.dirname(os.path.abspath(__file__))
R = os.environ.get("CTX_LAB_RUN") or os.path.join(P, ".run")
PROTO = os.path.join(os.path.dirname(P), "proto")
MOCK_KEY = "sk-ant-mock-0000000000000000"   # must match run_cli.sh; a placeholder, not a credential
MYCMD = "---\ndescription: probe custom command\n---\n커스텀 명령 본문입니다. 인자: $ARGUMENTS\n"


def git(*args):
    subprocess.run(["git", "-C", os.path.join(R, "proj"), "-c", "user.name=lab", "-c", "user.email=lab@example.invalid",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def main():
    if "--fresh" in sys.argv[1:] and os.path.isdir(R):
        shutil.rmtree(R)
    for d in ("home", "proj", "settings", "out"):
        os.makedirs(os.path.join(R, d), exist_ok=True)

    proj = os.path.join(R, "proj")
    if not os.path.isdir(os.path.join(proj, ".git")):
        os.makedirs(os.path.join(proj, ".claude", "commands"), exist_ok=True)
        with open(os.path.join(proj, ".claude", "commands", "mycmd.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(MYCMD)
        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("commit", "-q", "-m", "init")

    conf = os.path.join(R, "home", ".claude.json")
    if not os.path.exists(conf):
        seed = {"hasCompletedOnboarding": True,
                "customApiKeyResponses": {"approved": [MOCK_KEY[-20:]], "rejected": []},
                "projects": {proj: {"allowedTools": [], "hasTrustDialogAccepted": True}}}
        with open(conf, "w", encoding="utf-8") as f:
            json.dump(seed, f, indent=1)

    src = os.path.join(P, "settings")
    for name in sorted(os.listdir(src)):
        with open(os.path.join(src, name), encoding="utf-8") as f:
            text = f.read().replace("__PROBE__", json.dumps(P)[1:-1]).replace("__PROTO__", json.dumps(PROTO)[1:-1])
        with open(os.path.join(R, "settings", name), "w", encoding="utf-8") as f:
            f.write(text)
    print("lab run directory ready:", R)


if __name__ == "__main__":
    main()
