# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트와 현재 상태

`ctx-index`는 Claude Code 훅입니다. 턴마다 요청 · 답변 원문을 훅이 `~/.claude/ctx-index/<session_id>/`에 자동으로 저장하고, 컨텍스트 압축 직후에 그 **목차만** 주입해서 과거 턴의 존재와 원문 세부를 싼 비용으로 되찾게 합니다.

작업 절차는 ① 스키마 확인 → ② 구현 계획 → ③ lab 사전 시뮬레이션 → **[승인 게이트]** → ④ 구현이며, **지금은 ①~③까지만 끝났습니다.**

- **④(훅 본체, 테스트 스위트, 측정 스크립트)는 사용자가 명시적으로 승인하기 전에는 작성하지 않습니다.** 결정이 필요한 역제안(A1~A7)과, "승인"만 받았을 때의 기본 동작은 `docs/phase3-report.md` 6 · 7절에 있습니다.
- `docs/phase3-report.md`가 설계의 기준 문서입니다: 과제 명세와 보완 필수 사항(0절), 실측 이벤트 스키마(2절 · 부록 A), 구현 계획과 제안 파일 구조(3절), 미검증 항목(5절).
- `lab/`은 검증 자료이지 산출물이 아닙니다. `lab/proto/ctx_proto.py`는 설계 검증용 프로토타입이고, 실제 훅은 ④에서 따로 작성합니다.
- 보고서 3 · 7절은 `README.md`를 초기 초안으로 언급하지만, README는 그 뒤 현재 설계와 진행 상황에 맞게 갱신했습니다(설치 · 사용법은 ④에서 추가할 부분).

## 명령

빌드 · 린터 · 패키지 의존성 · 테스트 프레임워크가 없습니다(Python 표준 라이브러리만 사용). 검증 수단은 시뮬레이션 스크립트 두 개이며, 실패하면 0이 아닌 코드로 끝납니다.

```bash
python3 lab/proto/sim_replay.py      # 실측 페이로드 재생, 검사 37개, 1초 미만 (-q: 검사 목록만 출력)
python3 -u lab/proto/sim_fold.py     # 합성 장기 세션의 접기 · 상한, 약 30초
```

- 검사 하나만 골라 실행하는 옵션은 없습니다(둘 다 위에서 아래로 전부 실행). `CTX_LAB_CAPTURES=<디렉터리>`를 주면 `sim_replay.py`가 다른 캡처 디렉터리를 재생합니다.
- 커밋된 `lab/proto/*.out`은 위 두 명령의 stdout이고 보고서 4절 · 부록 B 수치의 근거입니다. 프로토타입이나 시뮬레이션을 바꾸면 `> lab/proto/sim_replay.out`처럼 다시 만들고 보고서 수치도 맞춥니다. 변경이 없을 때 `sim_replay.out`은 바이트 단위로 같고, `sim_fold.out`은 ms 시간 값만 달라집니다.

프로토타입에 이벤트를 직접 넣어 볼 때는 **`CTX_INDEX_DIR`을 반드시 임시 디렉터리로 지정**합니다. 지정하지 않으면 실제 `~/.claude/ctx-index/`에 기록합니다(시뮬레이션 스크립트는 스스로 임시 디렉터리를 씁니다).

```bash
export CTX_INDEX_DIR="$(mktemp -d)"
echo '{"hook_event_name":"UserPromptSubmit","session_id":"demo","prompt_id":"p1","prompt":"질문"}' | python3 lab/proto/ctx_proto.py
echo '{"hook_event_name":"Stop","session_id":"demo","prompt_id":"p1","last_assistant_message":"답변"}' | python3 lab/proto/ctx_proto.py
echo '{"hook_event_name":"SessionStart","session_id":"demo","source":"compact"}' | python3 lab/proto/ctx_proto.py
```

금지 표현 검사(아래 불변식 3)입니다. 일치하는 줄이 없으면 exit 0, 있으면 그 줄을 출력하고 exit 1입니다.

```bash
python3 -c "import subprocess,sys; w=chr(0xC815)+chr(0xBCF8); sys.exit(subprocess.run(['git','grep','-n','-I','--untracked','-e',w]).returncode != 1)"
```

실제 CLI로 훅 페이로드를 다시 채집하는 절차는 `lab/README.md`의 "실측 재캡처"에 있습니다(`claude` CLI 필요, pty · bash를 쓰므로 Linux/macOS 전용, `lab/probe`에서 실행).

## 깨면 안 되는 불변식

보고서 0절의 핵심 원칙과 완료 기준입니다. 바꾸자고 제안할 수는 있지만 임의로 어기지 않습니다.

1. **모델 쓰기 금지.** 모든 기록은 훅이 자동으로 합니다. 모델에게 기록을 시키는 지시나 도구를 넣지 않습니다.
2. **압축 시점 외 주입 금지.** `UserPromptSubmit`과 `Stop` 처리에서는 stdout에 아무것도 쓰지 않습니다(`UserPromptSubmit` · `SessionStart`의 일반 stdout은 컨텍스트에 추가됩니다). 출력은 `SessionStart`의 `source`가 `compact`일 때뿐이며, `sim_replay.py`가 이를 단언합니다.
3. **금지 표현.** U+C815 U+BCF8 두 글자로 된 한국어 낱말은 코드 · 문서 · 훅 출력 · 커밋 메시지 · PR 본문 어디에도 적지 않습니다(이 문서도 코드 포인트로만 가리킵니다). 다른 낱말 안에 두 글자가 이어져 나와도 검사에 걸리므로 피하고, 한국어 문서를 고친 뒤에는 위 검사 명령을 돌립니다.
4. **세션 ID로 고정된 경로.** 저장 위치는 `~/.claude/ctx-index/<session_id>/`뿐이며 브랜치명이나 cwd를 경로에 넣지 않습니다.
5. **원문 무손실 저장, 주입은 목차만.** 턴 파일에는 요청 전문과 최종 답변 원문을 그대로 남깁니다.
6. **항상 exit 0.** 어떤 입력 · 예외에서도 훅은 예외를 `errors.jsonl`에 남기고 정상 종료합니다.
7. **주입문 6,000자 이하.** `additionalContext`는 항상 상수(6,000자) 이하입니다. 프로토타입은 더 엄격한 UTF-16 단위로 잽니다(CLI는 10,000 UTF-16 단위를 넘으면 파일로 빼고 미리보기로 대체).
8. **고정 머리말.** 목차의 머리말(`HEADER`)은 명세에 고정된 문구이므로 바꾸지 않습니다.

대상 환경은 **Windows 11 · Python 3.12 · Claude Code 2.1.33x**인데 검증은 Linux 컨테이너(2.1.332)에서만 했습니다. 그래서 훅 코드는 표준 라이브러리만 쓰고, stdin은 `sys.stdin.buffer`로 바이트를 읽어 UTF-8로 디코딩하며, 파일은 바이너리 모드로 쓰고(개행 변환 없음), stdout JSON은 ASCII 이스케이프로 냅니다. Windows 실기 동작은 전부 미검증입니다.

## 아키텍처

### 훅 (프로토타입 `lab/proto/ctx_proto.py`)

`main()`이 stdin을 읽어 `handle()`로 넘기고, 이벤트별로 `on_prompt`(UserPromptSubmit) / `on_stop`(Stop) / `on_session_start`(SessionStart)가 처리합니다. `agent_id`가 있는 입력(서브에이전트)은 기록 · 주입 없이 끝냅니다. 상태는 `Store`가 세션 디렉터리에 둡니다(세션별 잠금 파일, `meta.json` 원자적 교체).

| 파일 | 역할 |
|---|---|
| `turns/NNNN.md` | 턴 원문. 작업 중 추가 요청과 이어진 답변은 같은 파일에 덧붙임 |
| `meta.json` | 턴별 상태 · 미리보기 · 크기. 목차는 여기서 만들며, 손상되면 턴 파일에서 재구성 |
| `compactions.jsonl` | 압축 경계(그 시점의 마지막 턴 번호). 다음 압축의 1차 접기 구간을 정함 |
| `index.md`, `errors.jsonl` | 마지막 주입문 스냅샷(디버깅용), 예외 기록 |

**턴 귀속은 `prompt_id`로 판정합니다**(역제안 A1). 실제 CLI에서는 `UserPromptSubmit`과 `Stop`이 1:1로 번갈아 오지 않아서, open/done 순서만으로는 답변이 엉뚱한 턴에 붙습니다. 이 부분을 고칠 때는 다음 실측 순서를 염두에 둡니다(보고서 2절 · 부록 A.2).

- 작업 중 입력(대기열): 입력 즉시 *진행 중 턴의* `prompt_id`로 `UserPromptSubmit`이 오고, 나중에 별도 턴으로 실행되면 `UserPromptSubmit` 없이 새 `prompt_id`의 `Stop`만 옵니다.
- bash 모드(`!cmd`)는 `Stop`만 옵니다. Esc 중단은 `Stop`이 오지 않습니다. 다른 Stop 훅이 막으면 같은 `prompt_id`로 `Stop`이 두 번 옵니다.
- 자동 압축은 `UserPromptSubmit → SessionStart(compact) → Stop` 순서라서 압축 시점에 현재 턴이 아직 열려 있습니다.
- 내장 명령(`/clear`, `/compact`, `/help`, `/status`, `/cost`, `/exit`)은 `UserPromptSubmit`이 오지 않고, 커스텀 슬래시 명령은 입력 원문 그대로 옵니다.

그래서 `UserPromptSubmit` 없이 시작된 턴은 `Stop`(또는 다음 `UserPromptSubmit`) 시점에 새 턴으로 만들고 요청을 트랜스크립트에서 복원합니다. `meta.json`의 `kind`가 턴의 출처를 나타냅니다(`user` / `auto` / `recovered` / `orphan` / `rebuilt`). 트랜스크립트 JSONL은 비공식 포맷이므로 이런 폴백 경로에서만 읽습니다.

**목차 렌더링**(`render_index`)은 상한을 넘을 때만 단계적으로 접습니다: `full` → `1`(직전 압축 이후 구간을 한 줄로, 첫 압축이면 최근 5턴) → `2a`(미리보기 70/90자 → 35/45자) → `2b`(500B 미만 턴을 작은 것부터) → `2c`(최신 턴부터 과거로 더 접기) → `cut`(강제 절단). `STAGE1_MINIMAL`은 1차 접기를 "필요한 만큼만" 하는 역제안 A3의 스위치입니다.

`on_session_start`는 **직전 경계 읽기 → 렌더링 → `index.md` 저장 → 이번 경계 기록** 순서를 지켜야 합니다. 경계를 먼저 기록하면 1차 접기 구간이 비게 됩니다.

### 검증 파이프라인 (`lab/`)

이벤트 스키마는 추측이 아니라 실제 CLI에서 채집한 페이로드에 근거합니다. 흐름은 다음과 같습니다.

1. `lab/probe/mock_api.py` — 로컬 모의 Messages API. 프롬프트 안의 마커(`[[TOOL]]`, `[[AGENT]]`, `[[BIG]]`, `[[SLOW]]`, `[[EMPTY]]`)로 응답 형태를 고릅니다(`[[BIG]]`은 사용량을 부풀려 자동 압축을 유발).
2. `lab/probe/run_cli.sh` — 실제 `claude` CLI를 `env -i`, 가짜 HOME, 가짜 API 키로 격리 실행합니다. `drive.py`(헤드리스 stream-json)와 `tui_drive.py`(pty)가 `scen_*` 시나리오를 구동합니다.
3. 프로브 훅이 페이로드를 `PROBE_OUT` 파일에 남깁니다(시나리오마다 `lab/probe/.run/out/<이름>/payloads.jsonl`로 지정). `probe_hook.py`(v1)는 전체 이벤트를, `probe_hook2.py`(v2)는 등록 대상 3개 이벤트와 그 시점의 트랜스크립트 크기(`tx_size`)를 기록합니다.
4. `pack_captures.py`가 경로 · 모델 이름 정규화, 트랜스크립트 슬림화, `tx_size` 재계산을 거쳐 `lab/captures/`로 옮깁니다.
5. `sim_replay.py`가 `captures/v2`의 이벤트를 `tx_size`로 자른 트랜스크립트 사본과 함께 프로토타입의 `handle()`에 재생합니다. `captures/v1`은 재생 입력이 아니라 스키마 근거입니다.

- `lab/probe/settings/*.json`은 `__PROBE__` / `__PROTO__` 자리 표시자가 든 템플릿이고, `setup_lab.py`가 `.run/settings/`로 렌더링합니다.
- `lab/probe/.run/`은 커밋하지 않습니다(모의 API 요청 로그에 CLI 시스템 프롬프트 전문이 남습니다). 캡처는 `pack_captures.py`를 거친 것만 커밋합니다.
- 실험에서 CLI는 항상 `run_cli.sh`로 띄웁니다. 작업 중인 세션의 환경 변수를 물려받은 채 `claude`를 중첩 실행하지 않습니다.
- 스키마는 **2.1.332** 실측입니다. CLI 버전이 바뀌면 문서나 기억에 기대지 말고 재캡처로 확인하고, 보고서에 적는 사실에는 근거 구분([실측] / [바이너리] / [문서])과 미검증 여부를 표기합니다.

## 관례

- 문서(`README.md`, `docs/`, `lab/README.md`)는 한국어, 코드 주석과 docstring은 영어입니다.
- 커밋 메시지는 영어 Conventional Commits 형식(`docs: …`, `chore: …`), PR 본문은 한국어(요약 / 변경 사항 / 검증 / 참고)입니다.
- PR은 `main`에 스쿼시 병합됩니다. 병합된 뒤 같은 브랜치에서 작업을 이어갈 때는 최신 `main`에서 브랜치를 다시 시작합니다(이전 커밋이 `main` 이력에 없기 때문).
