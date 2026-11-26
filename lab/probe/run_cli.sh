#!/bin/bash
# Run the real Claude Code CLI fully isolated: clean environment, throwaway HOME, local mock API.
# Nothing here touches a real account - HOME, the API key and the base URL are all fake.
# Prepare the run directory first with setup_lab.py and start mock_api.py on MOCK_PORT.
P="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
R="${CTX_LAB_RUN:-$P/.run}"
exec env -i HOME="$R/home" PATH="$PATH" TERM=xterm LANG=C.UTF-8 \
  ANTHROPIC_BASE_URL="http://127.0.0.1:${MOCK_PORT:-8765}" ANTHROPIC_API_KEY=sk-ant-mock-0000000000000000 \
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 \
  PROBE_OUT="${PROBE_OUT:-$R/out/payloads.jsonl}" PROBE_INJECT="${PROBE_INJECT:-1}" CTX_INDEX_DIR="${CTX_INDEX_DIR:-}" \
  claude "$@"
