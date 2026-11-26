# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트와 현재 상태

`ctx-index`는 Claude Code 훅입니다. 턴마다 요청 · 답변 원문을 훅이 `~/.claude/ctx-index/<session_id>/`에 자동으로 저장하고, 컨텍스트 압축 직후에 그 **목차만** 주입해서 과거 턴의 존재와 원문 세부를 싼 비용으로 되찾게 합니다.

작업 절차 ① 스키마 확인 → ② 구현 계획 → ③ lab 사전 시뮬레이션 → [승인 게이트] → ④ 구현까지 끝났습니다. **남은 것은 Windows 11 실기 검증과 1~2주 실사용 측정입니다.**

- 산출물은 `hooks/ctx_index.py`(훅 본체), `tools/install_hook.py`(설치 도우미), `tools/ctx_index_measure.py`(측정 스크립트), `tests/`(테스트 스위트)입니다.
- `docs/phase3-report.md`는 설계의 기준 문서입니다: 과제 명세와 보완 필수 사항(0절), 실측 이벤트 스키마(2절 · 부록 A), 역제안 A1~A7 · B항(6절). A1~A7과 B항은 모두 승인되어 적용했습니다(A3는 "같은 구간 안에서 필요한 만큼만").
- `docs/phase4-report.md`는 ④의 결과입니다: 명세에 없어 정한 것(2절), 명세 항목과 테스트의 대응 표(3절), 검증 결과(4절), 미검증 항목(5절), 구현하지 않고 남긴 역제안(6절).
- `lab/`은 검증 자료이지 산출물이 아닙니다. `lab/proto/ctx_proto.py`는 설계 검증용 프로토타입이며 고치지 않습니다(테스트가 최종 훅과 결과를 비교합니다). `lab/captures/`는 근거 자료이므로 내용을 바꾸지 않습니다.
- 명세(보고서 0절), 승인된 A1~A7, B항 밖에서 동작이나 범위를 바꾸는 변경은 구현하지 않고 제안으로 남깁니다.

## 명령

빌드 · 린터 · 패키지 의존성이 없습니다(Python 표준 라이브러리만 사용). 테스트는 `unittest`입니다.

```bash
python3 -m unittest discover -s tests                 # 전체 231개, 약 1분 30초
python3 -m unittest discover -s tests -k Folding      # 이름으로 고르기(클래스나 메서드 이름의 일부)
python3 -m unittest tests.test_ctx_index.Folding.test_a7_header_lines   # 테스트 하나
python3.12 -m unittest discover -s tests              # 대상 버전인 3.12로도 돌립니다
python3 tests/bench_hook.py                           # 훅 1회 실행 시간(테스트 아님)
```

lab 시뮬레이션은 프로토타입을 대상으로 하며 그대로 통과해야 합니다. 실패하면 0이 아닌 코드로 끝납니다.

```bash
python3 lab/proto/sim_replay.py      # 실측 페이로드 재생, 검사 37개, 1초 미만 (-q: 검사 목록만 출력)
python3 -u lab/proto/sim_fold.py     # 합성 장기 세션의 접기 · 상한, 약 30초
```

- 커밋된 `lab/proto/*.out`은 위 두 명령의 stdout이고 ③ 보고서 수치의 근거입니다. 프로토타입을 바꾸지 않는 한 `sim_replay.out`은 바이트 단위로 같고, `sim_fold.out`은 ms 시간 값만 달라집니다.
- `tests/fixtures/captures/`는 `lab/captures/v2/`의 사본입니다(테스트가 둘이 같은지 확인합니다). 재생 테스트는 `sim_replay.py`와 같은 방식으로 각 이벤트를 `tx_size`로 자른 트랜스크립트 사본에 대해 실행합니다.

훅에 이벤트를 직접 넣어 볼 때는 **`CTX_INDEX_DIR`을 반드시 임시 디렉터리로 지정**합니다. 지정하지 않으면 실제 `~/.claude/ctx-index/`에 기록합니다(테스트는 스스로 임시 디렉터리와 가짜 HOME을 씁니다).

```bash
export CTX_INDEX_DIR="$(mktemp -d)"
echo '{"hook_event_name":"UserPromptSubmit","session_id":"demo","prompt_id":"p1","prompt":"질문"}' | python3 hooks/ctx_index.py
echo '{"hook_event_name":"Stop","session_id":"demo","prompt_id":"p1","last_assistant_message":"답변"}' | python3 hooks/ctx_index.py
echo '{"hook_event_name":"SessionStart","session_id":"demo","source":"compact"}' | python3 hooks/ctx_index.py
```

설치 도우미와 측정 스크립트도 실제 `~/.claude`를 건드리지 않게 경로를 지정해서 시험합니다.

```bash
python3 tools/install_hook.py --settings "$(mktemp -d)/settings.json" --dry-run
python3 tools/ctx_index_measure.py --projects <트랜스크립트 디렉터리> --ctx-dir "$CTX_INDEX_DIR"
```

금지 표현 검사(아래 불변식 3)입니다. 일치하는 줄이 없으면 exit 0, 있으면 그 줄을 출력하고 exit 1입니다. 테스트 스위트에도 같은 검사가 들어 있습니다.

```bash
python3 -c "import subprocess,sys; w=chr(0xC815)+chr(0xBCF8); sys.exit(subprocess.run(['git','grep','-n','-I','--untracked','-e',w]).returncode != 1)"
```

실제 CLI로 훅 페이로드를 다시 채집하거나 최종 훅을 실제 CLI에 등록해 종단 실행하는 절차는 `lab/README.md`에 있습니다(`claude` CLI 필요, pty · bash를 쓰므로 Linux/macOS 전용).

## 깨면 안 되는 불변식

③ 보고서 0절의 핵심 원칙과 완료 기준입니다. 바꾸자고 제안할 수는 있지만 임의로 어기지 않습니다. 각 항목을 확인하는 테스트는 ④ 보고서 3절에 있습니다.

1. **모델 쓰기 금지.** 모든 기록은 훅이 자동으로 합니다. 모델에게 기록을 시키는 지시나 도구를 넣지 않습니다.
2. **압축 시점 외 주입 금지.** `UserPromptSubmit`과 `Stop` 처리에서는 stdout에 아무것도 쓰지 않습니다(`UserPromptSubmit` · `SessionStart`의 일반 stdout은 컨텍스트에 추가됩니다). 출력은 `SessionStart`의 `source`가 `compact`일 때뿐입니다. `dispatch()`가 두 이벤트의 반환값을 버리므로 구조적으로도 출력할 수 없습니다.
3. **금지 표현.** U+C815 U+BCF8 두 글자로 된 한국어 낱말은 코드 · 문서 · 훅 출력 · 커밋 메시지 · PR 본문 어디에도 적지 않습니다(이 문서도 코드 포인트로만 가리킵니다). 다른 낱말 안에 두 글자가 이어져 나와도 검사에 걸리므로 피하고, 한국어 문서를 고친 뒤에는 위 검사 명령을 돌립니다.
4. **세션 ID로 고정된 경로.** 저장 위치는 `~/.claude/ctx-index/<session_id>/`뿐이며 브랜치명이나 cwd를 경로에 넣지 않습니다.
5. **원문 무손실 저장, 주입은 목차만.** 턴 파일에는 요청 전문과 최종 답변 원문을 바이트 그대로 남깁니다.
6. **항상 exit 0.** 어떤 입력 · 예외에서도 훅은 예외를 `errors.jsonl`에 남기고 정상 종료합니다. 스크립트는 `os._exit(0)`으로 끝납니다.
7. **주입문 6,000자 이하.** `additionalContext`는 항상 상수(6,000자) 이하입니다. 더 엄격한 UTF-16 단위로 잽니다(CLI는 10,000 UTF-16 단위를 넘으면 파일로 빼고 미리보기로 대체).
8. **고정 머리말.** 목차의 머리말(`HEADER`)은 명세에 고정된 문구이므로 바꾸지 않습니다.

대상 환경은 **Windows 11 · Python 3.12 · Claude Code 2.1.33x**인데 검증은 Linux 컨테이너(2.1.332)에서만 했습니다. 그래서 훅과 도구는 표준 라이브러리만 쓰고, stdin은 `sys.stdin.buffer`로 바이트를 읽어 UTF-8로 디코딩하며, 파일은 바이너리 모드로 쓰고(개행 변환 없음), stdout JSON은 ASCII 이스케이프로 냅니다. 테스트도 추가 설치 없이 Windows에서 돌도록 유지합니다(POSIX 전용 검사는 건너뛰게 표시). **Windows에서 직접 확인하지 못한 동작은 통과로 적지 않고 "미검증"으로 적습니다.**

## 아키텍처

### 훅 (`hooks/ctx_index.py`)

`main()`이 stdin을 읽어 `handle()`로 넘기고, `dispatch()`가 이벤트별로 `on_prompt`(UserPromptSubmit) / `on_stop`(Stop) / `on_session_start`(SessionStart)를 부릅니다. `agent_id`가 있는 입력(서브에이전트)은 기록 · 주입 없이 끝냅니다. 상태는 `Store`가 세션 디렉터리에 둡니다(세션별 잠금 파일, `meta.json` 원자적 교체).

| 파일 | 역할 |
|---|---|
| `turns/NNNN.md` | 턴 원문. 작업 중 추가 요청과 이어진 답변은 같은 파일에 덧붙임 |
| `meta.json` | 턴별 상태 · 미리보기 · 크기. 목차는 여기서 만들며, 손상되면 턴 파일에서 재구성 |
| `compactions.jsonl` | 압축 경계(그 시점의 마지막 턴 번호). 다음 압축의 1차 접기 구간을 정함 |
| `index.md` | 마지막 주입문 스냅샷(디버깅용) |
| `events.jsonl` | 훅 호출마다 한 줄인 진단 기록. 키 이름 · 크기 · 처리 결과만 담고 프롬프트 · 답변 내용은 담지 않음. `EVENT_LOG` 상수로 끔 |
| `errors.jsonl` | 예외 기록. 세션 디렉터리에 쓸 수 없으면 `~/.claude/ctx-index/errors.jsonl`에 남김 |

**턴 귀속은 `prompt_id`로 판정합니다**(A1). 실제 CLI에서는 `UserPromptSubmit`과 `Stop`이 1:1로 번갈아 오지 않아서, open/done 순서만으로는 답변이 엉뚱한 턴에 붙습니다. 이 부분을 고칠 때는 다음 실측 순서를 염두에 둡니다(③ 보고서 2절 · 부록 A.2).

- 작업 중 입력(대기열): 입력 즉시 *진행 중 턴의* `prompt_id`로 `UserPromptSubmit`이 오고, 나중에 별도 턴으로 실행되면 `UserPromptSubmit` 없이 새 `prompt_id`의 `Stop`만 옵니다.
- bash 모드(`!cmd`)는 `Stop`만 옵니다. Esc 중단은 `Stop`이 오지 않습니다. 다른 Stop 훅이 막으면 같은 `prompt_id`로 `Stop`이 두 번 옵니다.
- 자동 압축은 `UserPromptSubmit → SessionStart(compact) → Stop` 순서라서 압축 시점에 현재 턴이 아직 열려 있습니다.
- 내장 명령(`/clear`, `/compact`, `/help`, `/status`, `/cost`, `/exit`)은 `UserPromptSubmit`이 오지 않고, 커스텀 슬래시 명령은 입력 원문 그대로 옵니다.

그래서 `UserPromptSubmit` 없이 시작된 턴은 `Stop`(또는 다음 `UserPromptSubmit`) 시점에 새 턴으로 만들고 요청을 트랜스크립트에서 복원합니다. `meta.json`의 `kind`가 턴의 출처를 나타냅니다(`user` / `auto` / `recovered` / `orphan` / `rebuilt`). 트랜스크립트 JSONL은 비공식 포맷이므로 이런 폴백 경로에서만 읽고, 읽기 실패는 모두 "찾지 못함"으로 처리합니다.

**목차 렌더링**(`render_index`)은 상한을 넘을 때만 단계적으로 접습니다: `full` → `1`(직전 압축 이후 구간의 최신 턴부터 필요한 만큼 한 줄로, 첫 압축이면 최근 5턴 안에서) → `2a`(미리보기 70/90자 → 35/45자) → `2b`(500B 미만 턴을 작은 것부터) → `2c`(최신 턴부터 과거로 더 접기) → `cut`(강제 절단). `STAGE1_MINIMAL = True`가 승인된 A3이고, `False`로 두면 명세 문구 그대로 구간 전체를 접습니다.

`on_session_start`는 **직전 경계 읽기 → 렌더링 → `index.md` 저장 → 이번 경계 기록** 순서를 지켜야 합니다. 경계를 먼저 기록하면 1차 접기 구간이 비게 됩니다. 스냅샷이나 경계 기록이 실패해도(편집기가 파일을 잡고 있는 경우 등) 오류만 남기고 주입은 합니다.

프로토타입과 다른 점은 다음뿐이며, 나머지는 테스트(`PrototypeParity`)가 같음을 확인합니다.

- A3를 켰고(`STAGE1_MINIMAL`), `events.jsonl`을 추가했습니다(A6).
- 턴 파일의 섹션 머리말에 본문의 바이트 수를 적습니다(`## ◇ 답변 · <시각> · 123B`). 본문에 섹션 머리말처럼 보이는 줄이 있어도(다른 턴 파일을 인용한 답변) `parse_turn_file()`이 정확히 나눕니다.
- `meta.json`에 없는 턴 파일을 다시 넣는 `reconcile()`(압축 시점, 그리고 `Stop`이 제 턴을 찾지 못했을 때), 손상된 레코드를 고쳐 읽는 `norm_turn()`, 중복 없는 턴 번호를 보장하는 배타적 파일 생성이 있습니다.
- 한글 조사 앞뒤의 `*강조*`도 미리보기에서 벗깁니다(프로토타입은 ASCII가 아닌 글자가 붙으면 남겼습니다).

### 설치 도우미 (`tools/install_hook.py`)

`settings.json`의 세 이벤트에 훅을 병합 등록합니다(백업, 기존 훅 보존, 재실행 시 변화 없음). 기억할 점은 세 가지입니다.

- 등록 명령은 `<python 절대 경로> -I -c <LAUNCHER> <훅 경로>`입니다. `python <훅 경로>` 형태는 훅 파일이 없을 때 종료 코드 2로 끝나고, Claude Code는 `UserPromptSubmit` 훅의 종료 코드 2를 프롬프트 차단으로 처리합니다(2.1.332 실측 · 바이너리 확인). `LAUNCHER`는 Windows 명령줄 인용에서 망가질 글자(큰따옴표, 역슬래시 등)를 쓰지 않습니다.
- 기본은 훅을 `<settings 디렉터리>/hooks/ctx_index.py`로 복사해 그 복사본을 등록합니다. 저장소의 브랜치 전환이 실행 중인 세션의 훅을 바꾸지 않게 하기 위해서입니다.
- 등록 전에 그 명령을 임시 디렉터리 상대로 한 번 실행하고(`self_test`), 실패하면 설정을 바꾸지 않습니다. 권한 설정(`permissions`)은 건드리지 않습니다.

### 측정 스크립트 (`tools/ctx_index_measure.py`)

트랜스크립트의 모든 `tool_use` 입력에서 문자열을 모아 분류합니다(`classify_text`): `ctx-index` 경로 세그먼트와 `turns` 세그먼트가 함께 있으면 턴 파일 참조, `.claude/projects`와 `.jsonl`이 함께 있으면 트랜스크립트 참조입니다. 경로 구분자는 `/`와 `\` 모두, 도구 호출 1건을 1회로 세고, 같은 `tool_use` id는 한 번만 셉니다(fork한 세션은 이력을 복사). 서브에이전트 트랜스크립트(`<세션>/subagents/agent-*.jsonl`)는 별도 열로 세고 부모 세션에 귀속합니다. 읽기 전용입니다.

### 검증 파이프라인 (`lab/`)

이벤트 스키마는 추측이 아니라 실제 CLI에서 채집한 페이로드에 근거합니다. 흐름은 다음과 같습니다.

1. `lab/probe/mock_api.py` — 로컬 모의 Messages API. 프롬프트 안의 마커(`[[TOOL]]`, `[[AGENT]]`, `[[BIG]]`, `[[SLOW]]`, `[[EMPTY]]`, `[[READTURN]]`)로 응답 형태를 고릅니다(`[[BIG]]`은 사용량을 부풀려 자동 압축을 유발, `[[READTURN]]`은 주입된 목차의 경로로 첫 턴 파일을 `Read`).
2. `lab/probe/run_cli.sh` — 실제 `claude` CLI를 `env -i`, 가짜 HOME, 가짜 API 키로 격리 실행합니다. `drive.py`(헤드리스 stream-json)와 `tui_drive.py`(pty)가 `scen_*` 시나리오를 구동합니다.
3. 프로브 훅이 페이로드를 `PROBE_OUT` 파일에 남깁니다(시나리오마다 `lab/probe/.run/out/<이름>/payloads.jsonl`로 지정). `probe_hook.py`(v1)는 전체 이벤트를, `probe_hook2.py`(v2)는 등록 대상 3개 이벤트와 그 시점의 트랜스크립트 크기(`tx_size`)를 기록합니다.
4. `pack_captures.py`가 경로 · 모델 이름 정규화, 트랜스크립트 슬림화, `tx_size` 재계산을 거쳐 `lab/captures/`로 옮깁니다.
5. `sim_replay.py`가 `captures/v2`의 이벤트를 `tx_size`로 자른 트랜스크립트 사본과 함께 프로토타입의 `handle()`에 재생합니다. `captures/v1`은 재생 입력이 아니라 스키마 근거입니다. 같은 재생을 최종 훅에 대해 하는 것이 `tests/test_ctx_index.py`의 `LabReplay`입니다.

- `lab/probe/settings/*.json`은 `__PROBE__` / `__PROTO__` 자리 표시자가 든 템플릿이고, `setup_lab.py`가 `.run/settings/`로 렌더링합니다. 최종 훅의 종단 실행은 템플릿 대신 설치 도우미를 가짜 HOME에 대고 실행해 등록합니다(`lab/README.md`).
- `lab/probe/.run/`은 커밋하지 않습니다(모의 API 요청 로그에 CLI 시스템 프롬프트 전문이 남습니다). 캡처는 `pack_captures.py`를 거친 것만 커밋합니다.
- 실험에서 CLI는 항상 `run_cli.sh`로 띄웁니다. 작업 중인 세션의 환경 변수를 물려받은 채 `claude`를 중첩 실행하지 않고, 작업 중인 세션에는 훅을 등록하지 않습니다.
- 스키마는 **2.1.332** 실측입니다. CLI 버전이 바뀌면 문서나 기억에 기대지 말고 재캡처로 확인하고, 보고서에 적는 사실에는 근거 구분([실측] / [바이너리] / [문서])과 미검증 여부를 표기합니다.

## 관례

- 문서(`README.md`, `docs/`, `lab/README.md`)는 한국어, 코드 주석과 docstring은 영어입니다. 도구가 사용자에게 보여 주는 메시지(설치 도우미, 측정 보고서)는 한국어입니다.
- 커밋 메시지는 영어 Conventional Commits 형식(`feat: …`, `docs: …`, `chore: …`), PR 본문은 한국어(요약 / 변경 사항 / 검증 / 참고)입니다.
- PR은 `main`에 스쿼시 병합됩니다. 병합된 뒤 같은 브랜치에서 작업을 이어갈 때는 최신 `main`에서 브랜치를 다시 시작합니다(이전 커밋이 `main` 이력에 없기 때문).
- `.gitattributes`가 줄바꿈을 LF로 고정합니다. 재생 픽스처는 바이트 오프셋으로 자르므로 CRLF로 바뀌면 안 됩니다.
- 테스트는 실제 홈 디렉터리를 쓰지 않습니다. `tests/support.py`가 테스트 프로세스의 `HOME` / `USERPROFILE`을 임시 디렉터리로 돌려놓으며, 새 테스트도 `Sandbox`나 명시적인 임시 경로만 씁니다.
- 고정된 수치를 비교하는 접기 테스트는 `lab/proto/sim_fold.py`와 같은 합성 세션 생성기를 씁니다. 기대값은 승인된 동작(A3 켬) 기준으로 계산한 값이며, 렌더링을 바꾸면 ④ 보고서의 수치와 함께 다시 계산합니다.
