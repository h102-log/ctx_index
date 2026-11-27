#!/bin/bash
# The real Claude Code CLI, fully isolated for the eval: clean environment (env -i), throwaway HOME, the
# autocompact window under test. Never inherits the environment or the login of the session that runs the eval.
#   CTX_EVAL_API=mock  local mock API on MOCK_PORT (no network, no account)
#   CTX_EVAL_API=real  api.anthropic.com with ONE of
#                        CTX_EVAL_OAUTH_TOKEN  a subscription token from `claude setup-token`, passed on as
#                                              CLAUDE_CODE_OAUTH_TOKEN (usage counts against the plan's limits)
#                        CTX_EVAL_API_KEY      an API key, passed on as ANTHROPIC_API_KEY (billed per token)
#                      The names differ from what the CLI reads so the running session's own auth is never touched.
H="${CTX_EVAL_HOME:?set CTX_EVAL_HOME}"
common=(HOME="$H" PATH="$PATH" TERM=xterm LANG=C.UTF-8
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
        CLAUDE_CODE_AUTO_COMPACT_WINDOW="${CLAUDE_CODE_AUTO_COMPACT_WINDOW:?set CLAUDE_CODE_AUTO_COMPACT_WINDOW}")
case "${CTX_EVAL_API:?set CTX_EVAL_API to mock or real}" in
  mock)
    exec env -i "${common[@]}" ANTHROPIC_API_KEY=sk-ant-eval-placeholder-0000000000000000 \
      ANTHROPIC_BASE_URL="http://127.0.0.1:${MOCK_PORT:?}" claude "$@" ;;
  real)
    net=()
    if [ -n "${HTTPS_PROXY:-}" ]; then net+=(HTTPS_PROXY="$HTTPS_PROXY"); fi
    ca="${CTX_EVAL_CA:-/root/.ccr/ca-bundle.crt}"
    if [ -f "$ca" ]; then net+=(NODE_EXTRA_CA_CERTS="$ca" SSL_CERT_FILE="$ca"); fi
    if [ -n "${CTX_EVAL_OAUTH_TOKEN:-}" ]; then
      exec env -i "${common[@]}" "${net[@]}" CLAUDE_CODE_OAUTH_TOKEN="$CTX_EVAL_OAUTH_TOKEN" claude "$@"
    elif [ -n "${CTX_EVAL_API_KEY:-}" ]; then
      exec env -i "${common[@]}" "${net[@]}" ANTHROPIC_API_KEY="$CTX_EVAL_API_KEY" claude "$@"
    fi
    echo "real runs need CTX_EVAL_OAUTH_TOKEN (claude setup-token) or CTX_EVAL_API_KEY" >&2; exit 2 ;;
  *)
    echo "CTX_EVAL_API must be mock or real" >&2; exit 2 ;;
esac
