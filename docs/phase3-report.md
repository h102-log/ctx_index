# ③ 보고: 선행 확인 · 구현 계획 · Lab 사전 시뮬레이션

> **상태**: ①~③ 완료. ④(훅 본체 · 테스트 스위트 · 측정 스크립트 구현)는 **승인 대기**이며, 이 저장소에는 아직 최종 훅이 없습니다.
> **기준**: 2026-11-26, Claude Code 2.1.332(Linux 컨테이너), Python 3.13.18. 대상 환경은 Windows 11 · Python 3.12 · Claude Code 2.1.33x입니다.
> **근거 자료**: [`lab/`](../lab/README.md) — 실측 캡처, 프로토타입, 시뮬레이션 스크립트와 실행 결과.

## 0. 과제 요약

Claude Code 2.1.33x에서 컨텍스트 압축 이후에도 과거 턴의 존재와 원문 세부를 싼 비용으로 추적할 수 있게 하는 턴 색인 훅 `ctx-index`를 설계 · 검증 · 구현합니다.

**핵심 원칙(훼손 금지)**

1. 모델 쓰기 금지 — 모든 기록은 훅이 자동으로 수행합니다.
2. 작업 중 지시 주입 금지 — 압축 시점 외에는 컨텍스트에 아무것도 주입하지 않습니다.
3. 특정 표현 사용 금지 — 머리말과 모든 출력 · 문서에 해당합니다. 그 단어는 이 저장소 어디에도 적지 않으며, 검사할 때는 코드 포인트(U+C815 U+BCF8)로 조합합니다.
4. 브랜치명을 제외한 세션 ID 고정 경로 사용 — `~/.claude/ctx-index/<session_id>/`
5. 원문 무손실 저장 후, 압축 시 목차만 주입

**완료 기준**

- a. 안정성: 어떤 예외 상황에서도 훅은 예외를 `errors.jsonl`에 기록하고 항상 exit 0으로 끝납니다.
- b. 정확성 · 상한: 모든 시뮬레이션 엣지 케이스를 통과하고, `hookSpecificOutput.additionalContext` 문자열 길이가 항상 6,000자(상수) 이하입니다.
- c. 실사용 효용 측정: 1~2주 실사용 후 활용도를 재는 스크립트. Read뿐 아니라 Grep, Bash 등 모든 도구 호출 입력에서 ctx-index 하위 `turns/` 경로 참조와 `.claude/projects/` 하위 `.jsonl` 트랜스크립트 참조를 셉니다.
- 기계적인 파일 생성보다 실제 이벤트 스키마 정합성, 데이터 무손실, 안정성을 우선합니다.

**저장 구조**: `~/.claude/ctx-index/<session_id>/` 아래에 `turns/0001.md …`(요청 전문 + 최종 답변 원문), `meta.json`(턴 번호, 시각, 상태 open/done, 요청/답변 요약 조각, 원문 바이트 크기), `compactions.jsonl`(압축 시점의 마지막 턴 번호와 시각), `errors.jsonl`, `index.md`(디버깅용 목차 스냅샷). 등록 이벤트는 UserPromptSubmit, Stop, SessionStart(matcher: `compact`)입니다.

**고정 머리말**: "이 세션에서 있었던 턴의 목록입니다. 결과의 요약이 아니며 빠진 것이 있을 수 있습니다. 세부가 필요하면 아래 디렉터리의 해당 턴 파일을 직접 읽으세요."

**보완 필수 사항(코드와 테스트에 모두 반영)**

1. 목차 밀도: 턴 디렉터리 절대 경로는 머리말에 한 번만, 각 줄은 파일명과 크기만 표기. 요청/답변 미리보기는 개행 · 마크다운을 제거해 최대 70/90자. 답변 미리보기는 인사말 · 헤더뿐인 첫 줄을 건너뛰고 의미 있는 첫 문장을 씁니다.
2. 상태 동기화: `index.md`에 덧붙이지 않고 `meta.json`을 턴 번호 기준으로 갱신하며, 목차는 SessionStart(compact) 시점에 동적으로 만듭니다. 한 요청에 Stop이 여러 번 오면 같은 턴 파일에 덧붙입니다. Stop이 없던 턴은 "(답변 없음/중단)"으로 표시합니다. 비대화성 내장 슬래시 명령(`/clear`, `/compact`, `/help`, `/status`, `/cost`, `/exit`)만 제외하고 커스텀 슬래시 명령은 기록합니다. 열린 턴 없이 온 Stop은 새 턴 파일을 만듭니다. 입력에 `agent_id`가 있으면 기록 · 주입 없이 exit 0. 중복 Stop이나 직전 기록과 같은 폴백 텍스트는 덧붙이지 않습니다.
3. 접기 2단계: SessionStart(compact)에서 `compactions.jsonl`의 직전 경계를 먼저 읽고, 렌더링한 뒤, 이번 경계를 기록합니다. 6,000자를 넘으면 1차로 직전 압축 이후 구간을 한 줄로 접고(첫 압축이면 최근 5턴), 그래도 넘으면 2차로 미리보기 길이를 절반으로 줄이고, 그래도 넘으면 작은 단순 턴(예: 500바이트 미만)부터 접되 초반 핵심 분석 턴은 보존합니다.
4. Windows UTF-8: 파일 · stdin(`sys.stdin.buffer`) · stdout 모두 UTF-8을 명시합니다. Stop에서 `last_assistant_message`가 없거나 비면 `transcript_path`에서 마지막 어시스턴트 텍스트를 뽑습니다. 불확실한 스키마 필드에는 안전한 폴백을 둡니다.

**절차**: ① 실제 이벤트 스키마와 기존 훅 설정 확인 → ② 세부 계획 → ③ lab 데이터 사전 시뮬레이션 → **[승인 게이트]** → ④ 훅 본체, 시뮬레이션 테스트 스위트, 측정 스크립트 작성과 테스트 실행.

---

## 1. 수행 내용

- **① 스키마 · 환경 확인**
  - 설치된 Claude Code **2.1.332** 바이너리에서 훅 입출력 스키마를 직접 확인하고 공식 문서와 대조했습니다.
  - 실제 CLI를 빈 HOME과 로컬 모의 API로 격리 구동해 훅 페이로드를 채집했습니다. 헤드리스(stream-json)와 대화형 TUI(pty 구동)를 모두 돌렸고, 실제 계정과 작업 세션에는 영향이 없습니다.
- **② 구현 계획**: 3절입니다.
- **③ 사전 시뮬레이션**: 프로토타입([`lab/proto/ctx_proto.py`](../lab/proto/ctx_proto.py))에 실측 페이로드를 재생하고, 합성 장기 세션으로 접기와 상한을 확인했습니다.
- **기존 훅 설정**: 검증에 쓴 컨테이너에는 환경 관리용 `SessionStart` · `Stop` 훅만 있었고 충돌은 없습니다(훅은 이벤트별로 누적 실행됩니다). 사용자 Windows PC의 설정은 확인하지 못했습니다(5절).

**먼저 알아 둘 점**: 명세의 open/done 상태 기계만으로는 실제 2.1.332에서 답변이 엉뚱한 턴에 붙는 경우가 있습니다. 작업 중에 다음 프롬프트를 입력하는 흔한 사용 패턴이 그렇습니다. 페이로드의 `prompt_id`로 귀속하면 해결되며, 이 변경은 승인이 필요합니다(역제안 A1).

## 2. 확인된 이벤트 스키마 (2.1.332 실측)

| 항목 | 결과 |
|---|---|
| 공통 필드 | `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `hook_event_name`. 메인 스레드에는 `agent_id` 키 자체가 없음 |
| `prompt_id` | UserPromptSubmit과 그 턴의 Stop에 같은 값이 옴 |
| Stop | `last_assistant_message`는 마지막 텍스트만 담김(도구 호출 전 내레이션 제외). 텍스트가 비면 키가 생략됨 |
| SessionStart(compact) | `source:"compact"`. 출력은 `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":…}}` |
| 주입 상한 | CLI는 10,000(UTF-16 단위)을 넘으면 파일로 빼고 미리보기로 대체함 |
| session_id 유지 | 브랜치 전환, 수동 · 자동 압축, `--resume`, `--continue`에서 유지. `/clear`와 `--fork-session`은 새 ID |
| 내장 명령 | `/clear /compact /help /status /cost /exit` 모두 UserPromptSubmit 미발화(TUI 6종 모두, 헤드리스는 `/exit` 제외 5종 확인). 커스텀 명령은 입력 원문 그대로 옴 |
| Esc 중단 | Stop이 오지 않음 |
| Stop 훅 차단 | 같은 `prompt_id`로 Stop이 2회 옴(두 번째는 `stop_hook_active:true`) |

명세가 예상하지 못한 순서도 네 가지 확인했습니다.

1. **자동 압축**은 `UserPromptSubmit → SessionStart(compact) → Stop` 순서입니다. 압축 시점에 현재 턴이 아직 열려 있습니다.
2. **작업 중 입력(대기열)**은 입력 즉시 진행 중 턴의 `prompt_id`로 UserPromptSubmit이 옵니다. 이후 별도 턴으로 처리되면 UserPromptSubmit 없이 새 `prompt_id`의 Stop만 옵니다. 도구 경계에서 흡수되면 Stop은 한 번뿐입니다.
3. **bash 모드(`!cmd`)**는 UserPromptSubmit 없이 Stop만 옵니다.
4. **백그라운드 작업 완료 알림**은 `<task-notification>…` 프롬프트로 UserPromptSubmit이 옵니다. 사람 입력과 구분할 `source` 필드는 2.1.332 페이로드에 없습니다.

세부 필드와 근거 구분은 부록 A에 있습니다.

## 3. 구현 계획

**파일 구조(제안)**

- `hooks/ctx_index.py`: 훅 본체(단일 파일, 표준 라이브러리 전용)
- `tests/test_ctx_index.py`와 `tests/fixtures/`: 시뮬레이션 테스트와 실측 페이로드
- `tools/ctx_index_measure.py`: 실사용 측정 스크립트
- `README.md`: 현재의 PreCompact 초안을 새 설계로 교체

**상태 전이**

| 이벤트 | 조건 | 처리 |
|---|---|---|
| 공통 | `agent_id` 있음 | 기록 · 주입 없이 exit 0 |
| UserPromptSubmit | 내장 명령 | 기록 안 함 |
| | 직전 턴과 `prompt_id` 같음 | 그 턴 파일에 "추가 요청(작업 중 입력)"으로 덧붙임 |
| | 그 외 | 새 턴(open) |
| Stop | `prompt_id`가 일치하는 턴 있음 | 그 턴에 답변 덧붙임(동일 텍스트면 무시), done |
| | 일치하는 턴 없음 | 새 턴 파일 생성 |
| | 텍스트 없음 | 트랜스크립트 폴백. 직전 기록과 같으면 버림 |
| SessionStart | `source`가 compact | 직전 경계 읽기 → 렌더링 → `index.md` 저장 → 이번 경계 기록 → 출력 |
| | 그 외 | 무출력 |

`prompt_id`가 없는 버전에서는 명세의 open/done 규칙으로 동작합니다.

**접기**

- 0단계: 전체 렌더링이 상한 이하면 그대로 씁니다.
- 1차: 직전 압축 이후 구간을 한 줄로 접습니다. 첫 압축이면 최근 5턴입니다.
- 2a: 미리보기를 35/45자로 줄입니다.
- 2b: 500B 미만 턴을 작은 것부터 접습니다.
- 2c(추가): 그래도 넘으면 최신 턴부터 과거 방향으로 더 접고, 마지막에는 강제 절단합니다.

**UTF-8 · 예외 방어**

- stdin은 바이트로 읽어 UTF-8로 디코딩하고, 파일은 바이너리 모드로 씁니다(개행 변환 없음).
- UserPromptSubmit과 Stop에서는 stdout에 아무것도 쓰지 않습니다.
- 최상위에서 모든 예외를 `errors.jsonl`에 남기고 항상 exit 0으로 끝냅니다.
- `meta.json`이 손상되면 턴 파일에서 재구성합니다.

**측정 스크립트**: 트랜스크립트의 모든 도구 호출 입력에서 `ctx-index/…/turns/` 참조와 `.claude/projects/…​.jsonl` 참조를 도구별 · 세션별로 셉니다. 압축 횟수, 주입 횟수, 접기 단계 분포, 오류 수도 함께 냅니다.

## 4. 검증 방법과 결과

**실측 페이로드 재생: 37/37 통과.** 각 이벤트는 훅 실행 시점 크기로 자른 트랜스크립트 사본에 대해 재생했습니다([`lab/proto/sim_replay.py`](../lab/proto/sim_replay.py), 결과 [`sim_replay.out`](../lab/proto/sim_replay.out)).

| 캡처 | 내용 | 결과 |
|---|---|---|
| a | 일반, 도구, 서브에이전트, 커스텀 슬래시, 브랜치 전환, 압축, 빈 답변, clear | 원 세션 턴 8개, 내장 명령 미기록, 빈 답변 Stop이 이전 답변을 끌어오지 않음 |
| b | 자동 압축 후 수동 압축 | 진행 중 턴이 "(진행 중)"으로 표시되고, 뒤늦은 Stop이 같은 턴에 귀속 |
| c | Stop 2회, resume, continue, fork | 턴 1개에 답변 2건, resume · continue는 같은 디렉터리 |
| d | TUI: Esc 중단, bash 모드 | 중단 턴은 "(답변 없음/중단)", bash 모드는 새 턴 파일 |
| e, stacked | 대기열과 중첩 대기열 | 모든 답변이 제 턴에 귀속 |
| headless | 일반, 커스텀 슬래시, 백그라운드 서브에이전트 알림 | 턴 5개 모두 UserPromptSubmit으로 생성, 답변 1건씩 귀속 |

**접기 · 상한(합성 세션, 소형 턴 30%)** — [`lab/proto/sim_fold.py`](../lab/proto/sim_fold.py), 결과 [`sim_fold.out`](../lab/proto/sim_fold.out)

| 상황 | 단계 | 길이 | 결과 |
|---|---|---|---|
| 첫 압축, 41턴 이하 | 접기 없음 | 상한 이하(40턴 5,819자) | 전부 표시 |
| 첫 압축, 42~45턴 | 1차 | 5,341~5,884 | 최근 5턴 접힘 |
| 첫 압축, 46~79턴 | 2a | 3,664~ | 미리보기 35/45 |
| 첫 압축, 80~88턴 | 2b | ~5,997 | 소형 턴 접힘 |
| 첫 압축, 89턴 이상 | 2c | ~5,924 | 110턴 기준 52줄 유지 |
| 2회차(경계 40), 58턴 | 1차 | 5,885 | `0041.md~0058.md` 한 줄 |

- 무작위 세션 3,000개(턴 1~3,000개, emoji · 장문 한 줄 · 긴 경로 포함)가 모두 6,000 이하였습니다. 최대값은 정확히 6,000입니다(code point와 UTF-16 단위 모두 검사).
- 60턴 → 압축 → 30턴 → 압축 흐름에서 1회차는 `0056~0060`, 2회차는 `0061~0090`이 접혔고, 경계 읽기 → 렌더링 → 기록 순서도 확인했습니다.

**실제 CLI 종단 실행**: 프로토타입을 훅으로 등록해 돌렸습니다. 목차는 압축 직후 첫 요청에만 들어갔고, 압축 전 요청 5건에는 없었습니다.

**비UTF-8 로캘(ASCII 강제)**: 한글 · emoji · CRLF가 그대로 저장됐습니다. 잘못된 입력 7종은 모두 exit 0에 stdout이 비어 있었습니다. 훅 1회 실행은 중앙값 42ms입니다(Linux 기준).

**미검증**: Windows 실기 동작 전부, 실제 모델 응답, 332 외의 2.1.33x 버전입니다.

## 5. 별도 표기 항목

| 항목 | 원인 | 선택한 폴백 | 해소 조건 |
|---|---|---|---|
| Windows 11 실기 동작 | 검증 환경이 Linux 컨테이너 | 바이트 입출력과 명시적 UTF-8, ASCII 로캘 테스트로 대체 | Windows에서 테스트 스위트 1회 실행 |
| 사용자 PC의 기존 `settings.json` | PC가 연결되어 있지 않았음 | 기존 훅을 덮어쓰지 않는 등록 방식 안내 | 파일 내용 공유 또는 PC 연결 |
| Windows 훅 명령 형식 | 셸이 Git Bash 유무에 따라 달라짐 | 셸을 거치지 않는 `command`+`args` 형식(Linux에서만 동작 확인) | Windows에서 1회 확인 |
| 서브에이전트의 `agent_id` | 등록 대상 3개 이벤트에서는 관측되지 않음(바이너리 코드로만 확인) | 값이 있으면 즉시 종료 | 실사용 로그 |
| 트랜스크립트 포맷 | 공식 문서에 없음 | 폴백 경로에서만 쓰고, 실패하면 "(요청 미기록)" | 없음(버전마다 재확인) |
| `/clear` · fork 이후 | 새 session_id가 발급됨 | 새 색인으로 시작, 이전 색인은 원래 디렉터리에 남음 | 설계상 한계 |
| 2.1.33x 중 332만 실측 | 설치된 버전이 하나뿐 | 불확실한 필드는 모두 폴백 경로를 둠 | 다른 버전에서 랩 재실행 |
| 실제 모델이 아닌 모의 API | 계정 · 비용 · 재현성 | 훅 배선은 실제 CLI 그대로. 자동 압축 임계값과 시점은 모의 사용량으로 유발 | 실사용 로그(`errors.jsonl`, 측정 스크립트) |
| `prompt_id`가 없는 버전 | 폴백 규칙(open/done)만 적용됨 | 대기열 입력이 섞이면 귀속이 어긋날 수 있음을 감수 | 해당 버전에서 랩 재실행 |
| Windows에서의 훅 지연 | 미측정(Linux 중앙값 42ms) | 잠금 대기 최대 2초, 훅 타임아웃 15초 설정 | Windows에서 측정 |

## 6. 역제안

**A. 승인이 필요한 것(명세 문구와 달라짐)**

1. **턴 귀속을 `prompt_id` 기준으로 판정.** 명세대로면 대기열 사용 시 Q1의 답변이 Q2 턴에 붙고 Q1은 "중단"으로 표시됩니다.
2. **자동 압축 중인 현재 턴은 "(진행 중)"으로 표시.** 명세대로면 처리 중인 요청이 "(답변 없음/중단)"으로 주입됩니다.
3. **1차 접기를 같은 구간 안에서 필요한 만큼만.** 경계 3 · 총 45턴에서 명세대로는 3줄(522자)만 남고, 이 방식은 40줄(5,884자)이 남습니다.
4. **2c 단계와 최후 절단 추가.** 명세의 2b까지만으로는 긴 세션에서 "항상 6,000자 이하"를 보장하지 못합니다.
5. **UserPromptSubmit 없이 시작된 턴의 요청을 트랜스크립트에서 복원**하고, 작업 알림 턴은 `[작업 알림] …`으로 기록.
6. **추가 산출물**: `tools/install_hook.py`(settings.json 병합 등록, 백업)와 진단용 `events.jsonl`.
7. **머리말에 한 줄 추가**: `형식: 파일 크기 | 요청 → 답변`과 턴 개수.

**B. 명세 범위 안의 안전 강화(이견이 없으면 적용)**

- 상한을 UTF-16 단위로 측정합니다. emoji가 많아도 CLI의 10,000 상한에 걸리지 않습니다.
- 세션별 잠금 파일(최대 2초 대기)과 `meta.json` 원자적 교체를 씁니다. Windows의 `PermissionError`는 재시도합니다.
- 트랜스크립트는 끝 2MiB부터 읽고 필요할 때만 32MiB까지 넓힙니다. 미리보기는 앞 20,000자만 봅니다.
- stdout JSON은 ASCII 이스케이프로 냅니다. 콘솔 코드페이지의 영향을 받지 않습니다.
- 내장 명령 목록은 명세의 6개에 `/quit`만 더합니다.

## 7. 승인 요청 (미결정)

아래가 정해지면 ④로 넘어갑니다. 별도 지시 없이 "승인"만 주어지면 A1~A7을 모두 적용하되 `events.jsonl`은 기본 켜짐 · 상수로 끌 수 있게 하고, 3절의 파일 구조로 진행합니다.

1. A1~A5 적용 여부(특히 A3: 명세 그대로 또는 필요한 만큼)
2. A6의 설치 도우미와 `events.jsonl` 포함 여부
3. A7 머리말 추가 줄, 파일 구조, README 교체 여부

---

## 부록 A. 스키마 상세

근거 구분: **[실측]** `lab/captures/`의 훅 페이로드에서 관측, **[바이너리]** 2.1.332 실행 파일 정적 분석, **[문서]** 공식 문서.

### A.1 이벤트별 입력 키 (`lab/captures/` 전체 집계)

| 이벤트 | 건수 | 항상 있는 키 | 있을 때만 |
|---|---|---|---|
| UserPromptSubmit | 67 | `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `hook_event_name`, `prompt` | — |
| Stop | 67 | `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `effort`, `hook_event_name`, `stop_hook_active`, `background_tasks`, `session_crons` | `last_assistant_message`(65건) |
| SessionStart | 19 | `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `source` | `model`(10), `prompt_id`(8, compact일 때), `context_tokens` · `estimated_cache_write_usd` · `prompt_cache_likely_expired` · `seconds_since_last_response`(3) |
| PreCompact | 4 | 공통 + `prompt_id`, `trigger`(manual/auto), `custom_instructions` | — |
| PostCompact | 4 | 공통 + `prompt_id`, `trigger`, `compact_summary` | — |
| SubagentStart | 1 | 공통 + `prompt_id`, `agent_id`, `agent_type` | — |
| SubagentStop | 5 | Stop의 키 + `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message` | — |
| UserPromptExpansion | 1 | UserPromptSubmit의 키 + `expansion_type`, `command_name`, `command_args`, `command_source` | — |
| SessionEnd | 11 | 공통 + `prompt_id`, `reason` | — |

- 표의 "공통"은 `session_id`, `transcript_path`, `cwd`, `hook_event_name`입니다.
- `source` 값은 startup, resume, clear, compact, fork가 관측됐습니다. [실측]
- `prompt_id`는 프로세스의 첫 사용자 입력 전(startup · resume · clear · fork의 SessionStart)에는 없습니다. [실측]
- 새 세션의 첫 프롬프트 시점에는 `transcript_path`가 가리키는 파일이 아직 없습니다. [실측] 값 자체가 빈 문자열일 수도 있습니다. [바이너리, 미관측]
- `scratchpad_dir`, UserPromptSubmit의 `session_title` · `source`는 스키마에는 있으나 2.1.332 페이로드에서는 관측되지 않았습니다. [바이너리]
- 원격 호출 형태에서는 `session_id`가 `served:<id>` 꼴일 수 있어 Windows 경로용으로 정리해야 합니다. [바이너리, 미관측]
- 훅 프로세스 환경 변수: `CLAUDE_PROJECT_DIR`, `CLAUDECODE=1`, `CLAUDE_CODE_ENTRYPOINT`(cli / sdk-cli), `CLAUDE_EFFORT`, `CLAUDE_ENV_FILE`(일부 이벤트). [실측]

### A.2 발화 규칙

- UserPromptSubmit이 오는 경우: 직접 입력한 프롬프트, 커스텀 슬래시 명령(입력 원문 그대로. 별도로 UserPromptExpansion도 발화), `<task-notification>…` 자동 턴(새 `prompt_id`, `<summary>` 태그 포함), 작업 중 입력(입력 시점에 진행 중 턴의 `prompt_id`로). [실측]
- UserPromptSubmit이 오지 않는 경우: 내장 명령(`/help`, `/status`, `/cost`, `/compact`, `/clear`, `/exit`), bash 모드 `!cmd`. [실측]
- Stop: 발화 전에 트랜스크립트가 먼저 기록됩니다. Esc 중단에서는 오지 않습니다. 다른 Stop 훅이 막으면 같은 `prompt_id`로 두 번 옵니다. bash 모드 턴과, 대기열에 있다가 별도 턴으로 실행된 프롬프트(트랜스크립트의 `promptSource: "queued"`)에서는 UserPromptSubmit 없이 옵니다. [실측]
- 수동 `/compact`: PreCompact → SubagentStop(`agent_type` 빈 값) → SessionStart(compact) → PostCompact. UserPromptSubmit과 Stop은 없습니다. [실측]
- 자동 압축: UserPromptSubmit → PreCompact → SessionStart(compact) → PostCompact → Stop(같은 `prompt_id`). [실측]
- UserPromptSubmit 시점에는 그 프롬프트의 `prompt_id`를 가진 사용자 항목이 트랜스크립트에 아직 없습니다(TUI · 헤드리스, 커스텀 슬래시와 작업 알림 포함). 이미 있다면 훅이 시작을 보지 못한 턴(대기열에서 꺼낸 턴)이 진행 중이라는 뜻입니다. [실측]

### A.3 출력

- SessionStart의 `additionalContext`는 압축 직후 첫 모델 요청에만 `SessionStart hook additional context: <텍스트>` 형태로 들어갑니다. [실측, 모의 API 요청 로그]
- `hookEventName`이 이벤트와 다르면 오류입니다. 10,000(UTF-16 단위)을 넘으면 파일로 저장되고 2,000자 미리보기로 대체됩니다. [바이너리]
- UserPromptSubmit · SessionStart에서 일반 stdout은 컨텍스트에 추가되므로, 훅은 UserPromptSubmit과 Stop에서 아무것도 출력하지 않아야 합니다. [문서]

### A.4 트랜스크립트 JSONL (비공식 포맷, 폴백 경로에서만 사용)

- 한 줄에 JSON 하나, 구분자 공백 없음(`"type":"user"`, `"promptId":"…"`), UTF-8 원문. [실측]
- 어시스턴트 응답은 콘텐츠 블록마다 한 줄로 나뉘고 같은 `message.id`를 공유합니다. 도구 호출은 어시스턴트의 `tool_use` 블록입니다. [실측]
- 사용자 프롬프트 항목은 문자열 content와 `promptId`, `promptSource`(typed / queued / sdk / system)를 가집니다. 도구 결과는 리스트 content입니다. `isSidechain`, `isMeta`, `isCompactSummary` 플래그가 있습니다. [실측]
- `system` 항목(`compact_boundary`, `stop_hook_summary`, `local_command`), 첨부 항목(`hook_additional_context`, `queued_command`), 항목별 `gitBranch`. 서브에이전트 트랜스크립트는 `<세션>/subagents/agent-<id>.jsonl`입니다. [실측]

### A.5 훅 설정

- `{"type":"command","command":…,"args":[…],"shell":"bash"|"powershell","timeout":<초>,"async":…}`. `args`가 있으면 셸을 거치지 않습니다(Linux에서 동작 확인: 캡처 v1/f). [바이너리 · 문서 · 실측]
- 기본 셸은 bash이고, Git Bash가 없는 Windows에서는 PowerShell입니다. 기본 타임아웃은 600초(UserPromptSubmit은 30초)입니다. [바이너리 · 문서, Windows 미검증]
- 같은 이벤트의 훅은 모두 실행되므로 기존 훅과 공존합니다. [문서]

## 부록 B. 시뮬레이션 수치 (`lab/proto/sim_fold.out`)

- 단계 전환 지점(첫 압축, 턴 수를 1부터 늘림): 42턴에서 1차, 46턴에서 2a, 80턴에서 2b, 89턴에서 2c.
- 300턴 첫 압축: 2c, 5,923자, 온전한 줄 52개(0003~0082 범위) + 접힌 줄 22개.
- 2회차(경계 40, 당시 진행 중) 58턴: 1차, 5,705자, `0040.md~0058.md`(19턴) — 진행 중이던 경계 턴을 구간에 포함.
- 3회차(경계 140) 400턴: 2c, 5,923자.
- 경계가 0턴으로 기록된 뒤 60턴: 첫 압축으로 취급, 2a, 4,645자.
- 스트레스 3,000세션 단계 분포: 접기 없음 738, 1차 493, 2a 337, 2b 468, 2c 964. 단일 렌더 최장 45ms. 7,000자 디렉터리 경로에서는 강제 절단으로 6,000자.
- 1차 접기 비교(명세 그대로 / 필요한 만큼): 경계 3 · 45턴에서 3줄 522자 / 40줄 5,884자, 경계 20 · 120턴에서 20줄 2,849자 / 40줄 5,887자. 구간이 작으면 결과가 같습니다.
- 종단 흐름(프로토타입 훅 호출): 60턴 → 압축 1(2a, 4,222자, `0056~0060` 접힘) → 30턴 → 압축 2(2a, 4,672자, `0061~0090` 접힘) → 12턴 → 압축 3(2c, 5,980자). cwd가 바뀌어도 세션 디렉터리는 하나이고, `index.md`는 마지막 주입문과 같습니다.
