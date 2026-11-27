#!/bin/bash
# The real Claude Code CLI, fully isolated for the eval: clean environment (env -i), throwaway HOME, the
# autocompact window under test. Never inherits the environment of the session that runs the eval.
#   CTX_EVAL_API=mock  local mock API on MOCK_PORT (no network, no account)
#   CTX_EVAL_API=real  api.anthropic.com. With CTX_EVAL_API_KEY set, that key is used; otherwise the request
#                      goes through HTTPS_PROXY, whose saved credential replaces the format-only placeholder.
H="${CTX_EVAL_HOME:?set CTX_EVAL_HOME}"
common=(HOME="$H" PATH="$PATH" TERM=xterm LANG=C.UTF-8
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
        CLAUDE_CODE_AUTO_COMPACT_WINDOW="${CLAUDE_CODE_AUTO_COMPACT_WINDOW:?set CLAUDE_CODE_AUTO_COMPACT_WINDOW}")
PLACEHOLDER=sk-ant-eval-placeholder-0000000000000000
case "${CTX_EVAL_API:?set CTX_EVAL_API to mock or real}" in
  mock)
    exec env -i "${common[@]}" ANTHROPIC_API_KEY="$PLACEHOLDER" ANTHROPIC_BASE_URL="http://127.0.0.1:${MOCK_PORT:?}" claude "$@" ;;
  real)
    net=()
    if [ -n "${HTTPS_PROXY:-}" ]; then net+=(HTTPS_PROXY="$HTTPS_PROXY"); fi
    ca="${CTX_EVAL_CA:-/root/.ccr/ca-bundle.crt}"
    if [ -f "$ca" ]; then net+=(NODE_EXTRA_CA_CERTS="$ca" SSL_CERT_FILE="$ca"); fi
    exec env -i "${common[@]}" "${net[@]}" ANTHROPIC_API_KEY="${CTX_EVAL_API_KEY:-$PLACEHOLDER}" claude "$@" ;;
  *)
    echo "CTX_EVAL_API must be mock or real" >&2; exit 2 ;;
esac
