# ④ 보고: 구현과 검증

> **상태**: ④(훅 본체 · 테스트 스위트 · 측정 스크립트 · 설치 도우미) 구현 완료. Windows 11 실기 검증은 하지 못했고, 7절의 명령으로 확인이 필요합니다.
> **기준**: 2026-11-26, Claude Code 2.1.332(Linux 컨테이너), Python 3.13.18 · 3.12.3. 대상 환경은 Windows 11 · Python 3.12 · Claude Code 2.1.33x입니다.
> **앞 단계**: 과제 명세, 실측 스키마, 승인된 역제안은 [③ 보고서](phase3-report.md)에 있습니다. 이 문서의 "명세"는 ③ 보고서 0절을 가리킵니다.

## 0. 요약

- 승인된 결정(A1~A7 모두 적용, A3는 "같은 구간 안에서 필요한 만큼만", B항 적용, `events.jsonl` 기본 켜짐)대로 구현했습니다.
- 테스트 231개가 Python 3.13과 3.12에서 통과합니다(건너뜀 2개: 아래 4.1). lab 시뮬레이션 두 종과 금지 표현 검사도 통과합니다.
- 실제 CLI(2.1.332)에 설치 도우미로 최종 훅을 등록해 돌린 종단 실행에서, 목차는 압축 전 요청에는 없고 압축 직후 첫 요청에서 한 번 들어갔으며, 턴 귀속은 lab 캡처의 기대와 같았습니다.
- 명세에 없던 위험 두 가지를 실제 CLI로 확인했습니다. (1) 훅 스크립트 파일이 없어지면 `UserPromptSubmit`이 프롬프트를 통째로 막습니다 → 설치 도우미의 등록 형식으로 막았습니다. (2) 턴 파일은 프로젝트 밖에 있어 모델이 읽을 때 권한을 묻습니다 → 문서에 허용 규칙을 적고 역제안으로 남겼습니다(2.4 · 6절).
- Windows에서 직접 확인한 것은 없습니다. 5절에 미검증 항목을, 7절에 Windows PC에서 실행할 명령을 정리했습니다.

## 1. 수행 내용

| 산출물 | 내용 |
|---|---|
| [`hooks/ctx_index.py`](../hooks/ctx_index.py) | 훅 본체. 단일 파일, 표준 라이브러리 전용. 프로토타입의 검증된 로직을 옮기고 A3를 켰으며 `events.jsonl`과 예외 방어를 더했습니다 |
| [`tests/test_ctx_index.py`](../tests/test_ctx_index.py) | 훅 테스트 172개: lab 검사 37개 이식, 원칙 · 보완 필수 사항 · 역제안별 테스트, 접기 · 상한, 예외 방어(별도 프로세스), 프로토타입과의 일치 |
| [`tests/fixtures/captures/`](../tests/fixtures/captures) | 실측 페이로드 픽스처. `lab/captures/v2`와 바이트 단위로 같은 사본이며 테스트가 이를 확인합니다 |
| [`tools/ctx_index_measure.py`](../tools/ctx_index_measure.py) · [테스트 30개](../tests/test_ctx_index_measure.py) | 실사용 측정 스크립트 |
| [`tools/install_hook.py`](../tools/install_hook.py) · [테스트 29개](../tests/test_install_hook.py) | 설치 도우미: 병합 등록, 백업, 기존 훅 보존, 재실행 시 변화 없음, 상태 확인, 제거 |
| [`tests/bench_hook.py`](../tests/bench_hook.py) | 훅 1회 실행 시간 측정(테스트가 아니며 따로 실행) |
| 문서 | README(설치 · 사용 · Windows 확인 절차 · 측정), `CLAUDE.md`(상태 · 명령 · 구조), 이 보고서 |
| 기타 | `.gitattributes`(줄바꿈 고정), lab 모의 API의 `[[READTURN]]` 마커와 `scen_read.py`(턴 파일 읽기 종단 확인용) |

`lab/captures/`와 프로토타입(`lab/proto/ctx_proto.py`), 커밋된 시뮬레이션 출력(`lab/proto/*.out`)은 바꾸지 않았습니다.

## 2. 정한 것과 달라진 것

### 2.1 명세에 없어 직접 정한 것

| 항목 | 정한 내용 | 이유 |
|---|---|---|
| `events.jsonl`의 내용 | 훅 호출 1회에 한 줄. 시각, 훅 버전, 이벤트 이름, 처리 결과(`new_turn` / `append_request` / `recovered_turn` / `answer` / `duplicate_answer` / `no_answer` / `orphan_turn` / `inject` / `empty_index` / `skip_builtin` / `skip_agent` / `noop` / `ignored` / `error`), 턴 번호와 종류, `prompt_id`, 텍스트 길이, 답변 출처(payload / transcript / none), 트랜스크립트 크기, 접기 단계와 주입문 길이, 훅 처리 시간(ms), 페이로드의 **키 이름** 목록 | 실사용에서 필요한 진단은 "어떤 이벤트가 어떤 모양으로 왔고 훅이 무엇을 했는가"입니다. 키 이름 목록은 2.1.33x의 다른 버전에서 스키마가 달라졌는지 보여 주고, 처리 시간은 Windows에서의 훅 지연을 실사용으로 재게 해 줍니다. 프롬프트 · 답변 내용과 cwd는 담지 않습니다(턴 파일에 이미 있고, 중복 저장할 이유가 없습니다) |
| `events.jsonl`의 범위 | 세션 디렉터리가 이미 있을 때만 씁니다. 진단 기록만으로 디렉터리를 만들지 않습니다. 세션당 8MiB를 넘으면 더 쓰지 않습니다. `EVENT_LOG = False`로 끕니다 | 내장 명령이나 등록 대상이 아닌 이벤트 때문에 빈 세션 디렉터리가 생기지 않게 하기 위해서입니다 |
| `agent_id`가 있는 입력의 진단 | 턴 기록 · 주입은 하지 않고(명세 그대로), 세션 디렉터리가 이미 있으면 `skip_agent` 한 줄만 남깁니다 | ③ 보고서 5절이 이 항목의 해소 조건을 "실사용 로그"로 적었습니다. 남기지 않으면 등록 대상 3개 이벤트에 `agent_id`가 실제로 오는지 끝내 알 수 없습니다. 아무것도 쓰지 않기를 원하시면 `EVENT_LOG`를 끄면 됩니다 |
| 설치 도우미의 인터프리터 지정 | 설치를 실행한 Python의 **절대 경로**(`sys.executable`). 가상 환경 안에서 실행했으면 그 뒤의 기본 인터프리터. `--python`으로 바꿀 수 있고, 등록 전에 그 인터프리터가 `-I`로 뜨는지와 버전(3.8 이상)을 확인합니다 | `python`이라는 이름만 등록하면 훅을 띄우는 쪽의 PATH에 좌우되고, Windows에서는 Microsoft Store 안내용 실행 파일이 잡힐 수 있습니다. 설치를 실행한 인터프리터는 적어도 그 컴퓨터에서 동작하는 것이 확인된 것입니다 |
| 측정 스크립트의 서브에이전트 트랜스크립트 | 셉니다. 다만 별도 열로 나누고 부모 세션에 귀속합니다. `--no-subagents`로 제외합니다 | 메인 모델이 턴 파일 조회를 서브에이전트에 맡기면 `Read`는 서브에이전트 트랜스크립트에만 남습니다. 색인을 쓴 것이므로 세되, 메인만의 수치도 보이게 나눴습니다. 서브에이전트 파일의 위치(`<세션>/subagents/agent-<id>.jsonl`)와 항목의 `sessionId`가 부모 세션이라는 점은 2.1.332에서 실측했습니다 |
| 측정 스크립트의 경로 구분자 | `/`와 `\`를 모두, 겹쳐 쓴 경우(`\\`, `//`)와 섞어 쓴 경우까지 인식합니다 | 예상대로 필요했습니다. 트랜스크립트의 JSON을 풀면 Windows 경로는 `\` 하나로, 셸 명령 안에서는 `\\`나 `/`로도 나옵니다. 머리 7종 × 구분자 6종 × 6종 조합을 테스트합니다(`test_c_both_path_separators_and_their_mixtures_count`) |
| 측정의 셈 단위 | 도구 호출 1건을 범주별로 1회. `ctx-index` 경로 세그먼트와 `turns` 세그먼트가 한 호출의 입력에 함께 있으면 턴 파일 참조, `.claude/projects`와 `.jsonl`이 함께 있으면 트랜스크립트 참조. 같은 `tool_use` id는 한 번만. 권한이 거부된 호출도 셉니다 | 경로가 필드 둘로 나뉘는 경우(`Grep`의 `path` + `glob`)와 `cd … && cat turns/…` 꼴까지 잡으려면 "한 호출 안의 동시 출현"이 가장 단순하고 설명 가능한 규칙입니다. fork한 세션은 이력을 복사하므로 id로 중복을 걸러야 합니다 |

### 2.2 프로토타입 · 기존 관례에서 벗어난 것

| 달라진 것 | 이유 |
|---|---|
| 턴 파일의 섹션 머리말에 본문 바이트 수를 적음(`## ◇ 답변 · <시각> · 123B`) | `meta.json`이 손상되면 턴 파일에서 재구성하는데, 답변이 다른 턴 파일을 인용하면 본문 안에 섹션 머리말과 같은 줄이 생깁니다. 바이트 수가 있으면 정확히 나눌 수 있습니다. 본문 자체는 여전히 원문 그대로입니다 |
| `meta.json`에 없는 턴 파일을 다시 넣는 `reconcile()`, 손상된 레코드를 고쳐 읽는 `norm_turn()`, 배타적 생성(`xb`)으로 턴 파일 만들기 | 잠금 대기 시간 초과나 저장 실패 뒤에 턴이 목차에서 빠지거나, 손으로 고친 `meta.json` 때문에 압축 때마다 훅이 실패하는 일을 막습니다 |
| 미리보기에서 `*강조*`를 벗기는 조건을 "앞뒤가 ASCII 글자가 아닐 때"로 완화 | 프로토타입은 `*정리*해줘`처럼 조사가 붙으면 `*`를 남겼습니다(보완 필수 사항 1의 "마크다운 제거"). `a*b*c`나 `*.py` 같은 ASCII 표기는 그대로 둡니다 |
| `prompt_id`가 없는 버전에서, 열린 턴 없이 온 Stop의 텍스트가 직전 기록과 같으면 버림 | 프로토타입은 이 경우 같은 답변으로 새 턴을 만들었습니다(보완 필수 사항 2의 "중복 Stop은 덧붙이지 않습니다") |
| 압축 시점에 `index.md` 스냅샷이나 경계 기록이 실패해도 주입은 함 | 스냅샷은 디버깅용입니다. 편집기가 `index.md`를 잡고 있다는 이유로 목차 주입이 사라지면 안 됩니다. 실패는 `errors.jsonl`에 남깁니다 |
| 세션 ID가 Windows 장치 이름(`NUL.txt` 등)이면 디렉터리 이름 앞에 `_`를 붙임 | 프로토타입은 해시만 뒤에 붙여서 이름의 첫 부분이 여전히 장치 이름이었습니다 |
| 쓸 수 없는 디렉터리에서는 잠금을 2초 기다리지 않음 | 잠금 파일을 만들 수 없는 상황은 기다려도 풀리지 않습니다. 프롬프트마다 2초씩 늦어지는 것을 막습니다 |
| 스크립트를 `os._exit(0)`으로 끝냄, `traceback`을 예외 때만 불러옴, stdin의 BOM · UTF-16 허용, 트랜스크립트 경로가 이상해도(NUL 문자 등) 폴백 읽기가 예외를 내지 않음 | "항상 exit 0"을 인터프리터 종료 단계까지 보장하고(stdout에 쓸 수 없는 상태에서는 Python이 종료 단계의 flush 실패로 0이 아닌 코드를 낼 수 있습니다), 실행 시간을 줄이기 위해서입니다 |
| 등록 형식이 `python3 <경로>`가 아니라 `<python 절대 경로> -I -c <실행기> <경로>` | 2.4의 첫 항목 |
| `.gitattributes`로 줄바꿈을 LF로 고정 | Windows용 git의 기본 설정은 체크아웃할 때 CRLF로 바꿉니다. 재생 픽스처는 바이트 오프셋(`tx_size`)으로 자르므로 줄바꿈이 바뀌면 테스트가 실측과 다른 조건이 됩니다 |
| lab 모의 API에 `[[READTURN]]` 마커 추가 | 주입된 목차의 경로로 턴 파일을 실제로 읽는 흐름을 종단으로 확인하기 위한 lab 도구 변경입니다. 캡처는 건드리지 않았습니다 |

### 2.3 A3 적용으로 달라진 수치

③ 보고서 4절의 표는 "명세 그대로"(구간 전체 접기) 기준입니다. 같은 합성 세션으로 다시 계산한 값은 다음과 같고, 달라진 행만 적습니다. 나머지 행(41턴 이하, 46턴 이상의 2a · 2b · 2c, 경계 40 · 58턴)은 같습니다.

| 상황 | ③ 보고서(명세 그대로) | 최종 훅(A3) |
|---|---|---|
| 첫 압축, 42턴 | 1차, 5,341자, 최근 5턴 접힘(37줄 표시) | 1차, 5,884자, 최근 **2턴** 접힘(40줄 표시) |
| 첫 압축, 43턴 | 1차, 5,522자, 5턴 접힘 | 1차, 5,884자, 3턴 접힘 |
| 첫 압축, 44턴 | 1차, 5,703자, 5턴 접힘 | 1차, 5,884자, 4턴 접힘 |
| 첫 압축, 45턴 | 1차, 5,884자, 5턴 접힘 | 같음 |
| 2회차(경계 40, 당시 진행 중), 58턴 | 1차, 5,705자, `0040.md~0058.md`(19턴) | 1차, 5,885자, `0041.md~0058.md`(18턴). 진행 중이던 40번 턴은 구간에 들어가지만 접을 필요가 없어 줄이 남습니다 |
| 2회차(경계 3), 45턴 | 1차, 522자, 3줄 표시 | 1차, 5,884자, 40줄 표시(③ 보고서 부록 B의 비교 값과 같음) |
| 2회차(경계 20), 120턴 | 1차, 2,849자, 20줄 표시 | 1차, 5,887자, 40줄 표시(부록 B와 같음) |

- 단계가 바뀌는 지점(42 · 46 · 80 · 89턴)과 무작위 3,000세션의 단계 분포(접기 없음 738, 1차 493, 2a 337, 2b 468, 2c 964), 최대 길이 6,000은 lab 결과와 같습니다.
- 종단 흐름(60턴 → 압축 → 30턴 → 압축 → 12턴 → 압축)의 길이는 저장 디렉터리 경로의 길이에 따라 달라집니다. lab과 같은 경로 길이로 환산하면 1 · 2회차가 4,222자 · 4,672자로 lab과 같습니다. 테스트는 고정된 Windows 형식 경로로 렌더링한 값(2a 4,240자 5턴, 2a 4,690자 30턴, 2c 5,998자 49턴)을 비교합니다.

### 2.4 새로 확인한 것 (명세와 실측 사이)

1. **훅 스크립트 파일이 없으면 프롬프트가 차단됩니다.** [실측 · 바이너리] `python <없는 파일>`은 종료 코드 2로 끝나고, 2.1.332는 사용자 설정의 `UserPromptSubmit` 훅이 종료 코드 2를 내면 프롬프트를 막습니다(`UserPromptSubmit operation blocked by hook`, 모델 호출 0회). `Stop` 등 몇몇 이벤트에는 "스크립트 누락"을 알아보고 넘어가는 처리가 있지만 `UserPromptSubmit`은 플러그인 훅일 때만 적용됩니다. 저장소에서 브랜치를 바꾸거나 저장소를 옮기는 것만으로 모든 세션의 프롬프트가 막힐 수 있다는 뜻입니다. 그래서 설치 도우미는 (a) 훅을 `~/.claude/hooks/`로 복사해 그 복사본을 등록하고, (b) `python -I -c <실행기> <경로>` 형식으로 등록합니다. 이 형식에서는 파일이 없을 때 종료 코드가 1이 되어 프롬프트가 그대로 처리됩니다(실제 CLI에서 확인: 모델 호출 1회, 훅 오류 알림만 표시).
2. **턴 파일을 읽을 때 권한을 묻습니다.** [실측] 턴 파일은 프로젝트 디렉터리 밖(`~/.claude/ctx-index/…`)에 있습니다. 모의 모델이 목차의 경로로 `Read`를 호출하자 헤드리스 실행에서는 `permission_denied`가 됐습니다. `~/.claude/settings.json`에 `"permissions": {"allow": ["Read(~/.claude/ctx-index/**)"]}`를 넣으면 프롬프트 없이 읽혔고, 모델이 턴 파일 원문을 받았습니다. 대화형에서는 권한 프롬프트가 뜰 것으로 보입니다(대화형은 확인하지 않음). 권한 설정은 승인된 범위 밖이라 설치 도우미가 건드리지 않고, README에 직접 추가하는 방법을 적었습니다(6절 1번).
3. **실제 트랜스크립트는 lab의 슬림본보다 훨씬 큽니다.** [실측] 원본에는 API 요청 스냅샷 줄이 있어 턴 하나에 100KB 넘게 늘어납니다. 훅의 폴백 읽기는 끝 2MiB로 제한되어 있고, 측정 스크립트는 `tool_use`가 들어 있는 줄만 파싱합니다.

## 3. 명세 항목과 확인 방법

테스트 이름은 `tests/test_ctx_index.py`의 `클래스.메서드`입니다. `lab01`~`lab37`은 `LabReplay.test_labNN_…`으로, `lab/proto/sim_replay.py`의 검사 37개와 순서대로 1:1입니다.

### 핵심 원칙

| 항목 | 확인 |
|---|---|
| 1. 모델 쓰기 금지 | `Principles.test_p1_injection_is_only_the_fixed_header_and_index_lines`(주입문은 고정 머리말 · 디렉터리 줄 · 형식 줄 · 목차 줄뿐), `test_p1_output_carries_nothing_but_additional_context`, `test_p1_header_is_the_fixed_sentence_of_the_spec`. 실사용에서는 측정 스크립트가 ctx-index 아래를 대상으로 한 쓰기 도구 호출을 경고로 보고(`Counting.test_c_write_under_ctx_index_is_reported`) |
| 2. 압축 시점 외 주입 금지 | `Principles.test_p2_*` 4개(별도 프로세스의 stdout 0바이트, compact가 아닌 `source` 11가지, `dispatch()`의 구조적 차단), `ProcessReplay.test_stdout_is_empty_outside_compaction`(실측 페이로드 80건), `Robustness` 전체, 실제 CLI 종단 실행(4.3) |
| 3. 금지 표현 | `Principles.test_p3_forbidden_expression_is_absent_from_the_repository`, `…_from_hook_output`, `CLAUDE.md`의 검사 명령 |
| 4. 세션 ID로 고정된 경로 | `Principles.test_p4_*` 4개(cwd가 바뀌어도 한 디렉터리, 기본 위치가 `~/.claude/ctx-index`, 실제 프로세스의 기본 위치, 이상한 세션 ID도 루트 안), lab01 · lab12 · lab20 · lab21 · lab26 |
| 5. 원문 무손실 저장 후 목차만 주입 | `Principles.test_p5_request_and_answer_bytes_are_stored_verbatim`(CRLF, 끝 공백, emoji, NUL, 코드 펜스, 섹션 머리말처럼 보이는 본문, 10만 자), `test_p5_same_bytes_through_a_real_process`, `test_p5_only_previews_are_injected`, lab10 |

### 완료 기준

| 항목 | 확인 |
|---|---|
| a. 안정성(별도 프로세스로 실행해 종료 코드와 stdout 확인) | `Robustness` 27개. 빈 입력 `test_a_empty_and_blank_input` / 깨진 JSON `test_a_broken_json`, `test_a_json_that_is_not_an_object` / 비UTF-8 바이트 `test_a_non_utf8_bytes` / 필드 누락 `test_a_missing_fields` / 타입 오류 `test_a_wrong_types_everywhere`, `test_a_fuzzed_real_payloads_in_process`(변형 2,000건) / 손상된 `meta.json` `test_a_corrupt_meta_json_is_rebuilt_from_the_turn_files`, `test_a_truncated_meta_json`, `test_a_valid_json_meta_with_damaged_records`, `test_a_meta_json_replaced_by_a_directory`, `test_a_damaged_side_files` / 쓸 수 없는 저장 경로 `test_a_storage_root_under_a_regular_file`, `test_a_storage_root_is_a_regular_file`, `test_a_session_directory_is_a_regular_file`, `test_a_turns_directory_is_a_regular_file`, `test_a_read_only_storage`, `test_a_errors_log_itself_cannot_be_written` / 잠금 경합 `test_a_parallel_hook_processes_do_not_lose_turns`(12개 동시 실행), `test_a_lock_held_by_someone_else`, `test_a_stale_lock_is_broken`, `test_a_lock_is_released_when_the_handler_fails` / `errors.jsonl` 기록 `test_a_exception_inside_a_handler_is_recorded_with_traceback` / exit 0 `test_a_exit_code_is_zero_even_for_system_exit_and_keyboard_interrupt`, `test_a_closed_or_broken_standard_streams`, `test_a_large_and_deep_input`, `test_a_script_ends_with_an_unconditional_exit_zero` |
| b. 정확성 · 상한 | lab 검사 37개 → lab01~lab37. 접기 · 상한 시뮬레이션 → `Folding` 20개(`test_s3_scenarios_with_pinned_numbers`, `test_s3_stage_transitions_with_pinned_numbers`, `test_b_cap_stress_3000_random_sessions`, `test_b_cap_stress_default_mode_and_odd_limits`, `test_b_cap_holds_for_utf16_heavy_previews`, `test_s3_flow_boundary_is_read_before_rendering_and_recorded_after` 등). 실측 페이로드의 주입문 길이는 `LabReplay.test_replay_every_injection_is_within_the_cap_and_well_formed` |
| c. 실사용 효용 측정 | `tests/test_ctx_index_measure.py` 30개. 기대값 일치는 `Counting.test_c_reference_counts_match_the_known_values`(합성 도구 호출 32건의 범주 · 도구별 기대값), `test_c_counts_per_session_and_tool_calls`. 모든 도구(Read, Grep, Glob, Bash, PowerShell, Agent, MCP 도구, 형식이 다른 입력)는 `Classification.test_c_every_case_is_classified_as_expected`, 경로 구분자는 `test_c_both_path_separators_and_their_mixtures_count`, 비슷하지만 아닌 경로는 `test_c_near_misses_are_not_counted` |

### 보완 필수 사항 (문장별)

| 문장 | 확인 |
|---|---|
| 1. 턴 디렉터리 절대 경로는 머리말에 한 번만, 각 줄은 파일명과 크기만 | `IndexDensity.test_s1_directory_once_then_file_name_and_size_per_line`, `test_s1_size_column_is_the_stored_text_size`, lab09 |
| 1. 미리보기는 개행 · 마크다운을 제거해 최대 70/90자 | `test_s1_request_preview_has_no_newlines_or_markdown_and_at_most_70_chars`, `test_s1_answer_preview_is_at_most_90_chars`, `test_s1_counts_of_extra_requests_and_answers_fit_inside_the_limits`, `test_s1_previews_of_huge_or_hostile_text_stay_cheap` |
| 1. 답변 미리보기는 인사말 · 헤더뿐인 첫 줄을 건너뛰고 의미 있는 첫 문장 | `test_s1_answer_preview_skips_greeting_and_header_only_lines`, `test_s1_answer_preview_falls_back_when_nothing_is_meaningful` |
| 2. `index.md`에 덧붙이지 않고 `meta.json`을 턴 번호 기준으로 갱신 | `StateSync.test_s2_index_md_is_a_snapshot_written_only_at_compaction`, `test_s2_meta_is_updated_in_place_by_turn_number` |
| 2. 목차는 SessionStart(compact) 시점에 동적으로 생성 | `test_s2_index_is_rendered_from_current_state_at_compaction` |
| 2. 한 요청에 Stop이 여러 번 오면 같은 턴 파일에 덧붙임 | `test_s2_several_stops_append_to_the_same_turn_file`, lab18 · lab19 |
| 2. Stop이 없던 턴은 "(답변 없음/중단)" | `test_s2_turn_without_stop_is_shown_as_unanswered`, lab22 |
| 2. 내장 슬래시 명령만 제외하고 커스텀 슬래시 명령은 기록 | `test_s2_only_the_builtin_commands_are_skipped`, lab03 · lab04 · lab17 |
| 2. 열린 턴 없이 온 Stop은 새 턴 파일 | `test_s2_stop_without_an_open_turn_creates_a_new_turn_file`, `test_s2_stop_as_first_event_of_a_session`, lab23 |
| 2. 입력에 `agent_id`가 있으면 기록 · 주입 없이 exit 0 | `test_s2_input_with_agent_id_is_neither_recorded_nor_injected` |
| 2. 중복 Stop이나 직전 기록과 같은 폴백 텍스트는 덧붙이지 않음 | `test_s2_duplicate_stop_is_not_appended`, `test_s2_fallback_text_equal_to_the_previous_record_is_dropped`, lab07 |
| 3. 직전 경계를 먼저 읽고, 렌더링한 뒤, 이번 경계를 기록 | `Folding.test_s3_flow_boundary_is_read_before_rendering_and_recorded_after` |
| 3. 넘으면 1차로 직전 압축 이후 구간을 접음(첫 압축이면 최근 5턴) | `test_s3_scenarios_with_pinned_numbers`, `test_s3_first_compaction_folds_at_most_the_newest_five`, `test_s3_in_flight_boundary_turn_belongs_to_the_next_segment`, `test_a3_*` |
| 3. 그래도 넘으면 미리보기 길이를 절반으로 | `test_s3_stage2a_halves_the_previews` |
| 3. 그래도 넘으면 작은 단순 턴부터 접되 초반 핵심 분석 턴은 보존 | `test_s3_stage2b_folds_small_turns_first_and_keeps_early_large_turns` |
| 4. 파일 · stdin · stdout 모두 UTF-8 명시 | `Utf8AndFallbacks.test_s4_hangul_emoji_and_crlf_survive_an_ascii_locale`, `test_s4_stdin_is_read_as_bytes_ascii_escaped_or_raw_utf8`, `test_s4_bom_and_utf16_input_are_tolerated`, `test_s4_files_are_written_in_binary_mode`, `ProcessReplay.test_compaction_output_is_ascii_json_with_the_documented_shape` |
| 4. `last_assistant_message`가 없거나 비면 트랜스크립트의 마지막 어시스턴트 텍스트 | `test_s4_missing_answer_is_taken_from_the_transcript`, `test_s4_empty_or_blank_answer_also_uses_the_transcript`, `test_s4_answer_blocks_of_one_message_are_joined`, `test_s4_fallback_never_takes_another_prompts_answer`, `test_s4_fallback_skips_synthetic_error_and_sidechain_messages`, `test_s4_fallback_reads_only_the_tail_and_widens_when_needed` |
| 4. 불확실한 스키마 필드에는 안전한 폴백 | `test_s4_unusable_transcripts_degrade_to_no_answer`, `test_s4_session_id_fallbacks`, `test_s4_payload_fields_of_unexpected_types`, `test_s4_lone_surrogates_cannot_break_storage`, `StateSync.test_s2_open_done_rule_without_prompt_id` |

### 승인된 역제안

| 항목 | 확인 |
|---|---|
| A1. 턴 귀속을 `prompt_id`로 판정 | `StateSync.test_a1_answers_follow_the_prompt_id_not_the_arrival_order`, `test_a1_late_stop_reaches_an_older_turn`, lab27~lab35 |
| A2. 자동 압축 중인 턴은 "(진행 중)" | `test_a2_in_flight_turn_and_boundary`, `test_a2_interrupted_turn_is_not_called_in_flight`, lab13~lab16 |
| A3. 1차 접기는 같은 구간 안에서 필요한 만큼만 | `Folding.test_a3_spec_literal_versus_as_needed_with_pinned_numbers`, `test_a3_stage1_folds_the_newest_turns_of_its_segment_and_no_more_than_needed`(한 턴 덜 접으면 넘친다는 것까지 확인), `test_s3_defaults` |
| A4. 2c 단계와 최후 절단 | `test_a4_stage2c_extends_the_fold_from_the_newest_turn_backwards`, `test_a4_hard_cut_when_the_header_alone_does_not_fit`, `test_a4_hard_cut_through_the_real_hook` |
| A5. 요청 복원과 작업 알림 표기 | `StateSync.test_a5_*` 6개, lab06 · lab24 · lab29 · lab34 |
| A6. 설치 도우미와 `events.jsonl` | `tests/test_install_hook.py` 29개(병합 `test_i_existing_settings_and_hooks_are_preserved`, 백업 같은 테스트, 중복 방지 `test_i_second_run_changes_nothing` · `test_i_older_registrations_are_updated_not_duplicated`, 제거 `test_i_uninstall_restores_the_previous_settings`, 읽을 수 없는 설정은 건드리지 않음 `test_i_unreadable_settings_are_never_overwritten`, 등록한 명령의 실제 실행 `RegisteredCommand.*`), `EventLog` 7개 |
| A7. 머리말의 형식 줄과 턴 개수 | `Folding.test_a7_header_lines` |
| B. UTF-16 단위로 측정 | `Folding.test_b_cap_holds_for_utf16_heavy_previews`, 상한 테스트 전부(code point와 UTF-16 모두 비교) |
| B. 잠금(최대 2초)과 `meta.json` 원자적 교체 | `Robustness.test_a_lock_*`, `test_a_parallel_hook_processes_do_not_lose_turns`. Windows의 `PermissionError` 재시도 경로는 실행되지 않았습니다(5절) |
| B. 트랜스크립트는 끝 2MiB부터, 미리보기는 앞 20,000자 | `Utf8AndFallbacks.test_s4_fallback_reads_only_the_tail_and_widens_when_needed`, `IndexDensity.test_s1_previews_of_huge_or_hostile_text_stay_cheap` |
| B. stdout JSON은 ASCII 이스케이프 | `ProcessReplay.test_compaction_output_is_ascii_json_with_the_documented_shape`, `test_s4_hangul_emoji_and_crlf_survive_an_ascii_locale` |
| B. 내장 명령 목록에 `/quit` 추가 | `StateSync.test_s2_only_the_builtin_commands_are_skipped` |
| 프로토타입의 로직을 옮겨 썼는가 | `PrototypeParity` 4개: 고정 문자열과 상수, 미리보기, 두 접기 방식의 렌더링 결과, 실측 재생의 최종 상태가 프로토타입과 같음 |

## 4. 검증 방법과 결과

### 4.1 테스트 스위트

| 실행 | 결과 |
|---|---|
| `python3 -m unittest discover -s tests` (Python 3.13.18) | 231개 통과, 건너뜀 2개 |
| `python3.12 -m unittest discover -s tests` (Python 3.12.3) | 231개 통과, 건너뜀 2개 |
| 같은 명령을 비특권 계정(`nobody`)으로 | 231개 통과, 건너뜀 1개 |
| `python3.11 -m unittest discover -s tests` (Python 3.11.18, 참고) | 231개 통과, 건너뜀 2개 |

- 건너뛴 것: `Robustness.test_a_read_only_storage`(root에서는 권한 비트가 적용되지 않음 — 비특권 계정으로 따로 돌려 통과 확인), `RegisteredCommand.test_i_powershell_form_runs_the_hook`(이 컨테이너에 PowerShell이 없음).
- 테스트는 임시 디렉터리만 쓰고, 테스트 프로세스의 `HOME` / `USERPROFILE`을 임시 디렉터리로 돌려놓습니다. 실제 `~/.claude/settings.json`과 `~/.claude/ctx-index/`는 열지 않았습니다.
- 실측 페이로드 80건은 `sim_replay.py`와 같은 방식으로, 각 이벤트를 `tx_size`로 자른 트랜스크립트 사본에 대해 재생합니다. 같은 재생을 `handle()` 직접 호출과 별도 프로세스 두 가지로 하고 결과가 같은지 비교합니다.

### 4.2 lab 시뮬레이션과 금지 표현

| 실행 | 결과 |
|---|---|
| `python3 lab/proto/sim_replay.py` | 37/37 통과, 출력이 커밋된 `sim_replay.out`과 바이트 단위로 같음 |
| `python3 -u lab/proto/sim_fold.py` | 통과, 출력이 `sim_fold.out`과 ms 값만 다름 |
| 두 스크립트를 최종 훅에 대고 실행(프로토타입 자리에 최종 훅을 끼움) | 재생 37/37, 출력이 프로토타입 결과와 같음. 접기 시뮬레이션은 A3로 달라진 한 줄(42턴)과 `events.jsonl` 파일 목록만 다름 |
| `CLAUDE.md`의 금지 표현 검사 | 일치 없음(exit 0) |

### 4.3 실제 CLI 종단 실행

`lab/README.md`의 방식(가짜 HOME, 가짜 API 키, 로컬 모의 API, `run_cli.sh`)으로 Claude Code 2.1.332를 띄우고, **설치 도우미를 가짜 HOME에 대고 실행해** 최종 훅을 사용자 설정으로 등록했습니다. 작업 중인 세션에는 등록하지 않았습니다.

| 시나리오 | 결과 |
|---|---|
| 헤드리스: 일반 → 도구 → 커스텀 슬래시 → `/compact` → 질문 | 모델 요청 6건 중 압축 전 5건(요약 요청 포함)에는 목차가 없고, 압축 직후 첫 요청에 `SessionStart hook additional context: …`로 1건 들어감. 턴 4개, `errors.jsonl` 없음 |
| 헤드리스: 자동 압축 후 수동 압축(`scen_b`) | 턴 5개. 자동 압축 경계 `last_turn=3, last_open=true`, 수동 `4, false`. 진행 중이던 턴의 답변이 같은 턴에 귀속. 요청별 목차 건수는 압축 전 0, 첫 압축 뒤 요청마다 1(같은 한 건이 대화 이력으로 남은 것이며 새로 추가되지 않음), 두 번째 압축 뒤에도 1 |
| TUI: 중첩 대기열(`scen_tui3`) | 턴 5개, 종류 `user, user, user(요청 2건), recovered(요청 2건), orphan` — lab 캡처의 기대와 같음 |
| TUI: 내장 명령 · Esc 중단 · bash 모드 · `/compact` · `/clear`(`scen_tui`) | 내장 명령은 기록되지 않음, 중단된 턴은 "(답변 없음/중단)", bash 모드 턴은 요청이 `!echo bash-mode-probe`로 복원됨, `/clear` 뒤는 새 디렉터리 |
| TUI: 대기열 — 별도 턴 / 흡수(`scen_tui2`) | 턴 3개, 답변이 각자의 턴에 귀속 |
| 헤드리스: 압축 뒤 모의 모델이 목차의 경로로 턴 파일을 `Read`(`scen_read`) | 허용 규칙이 없으면 `permission_denied`. `Read(~/.claude/ctx-index/**)` 규칙을 넣으면 턴 파일 원문을 받음. 측정 스크립트가 두 호출을 턴 파일 참조 2건(도구 `Read`)으로 셈 |
| 훅 파일을 지운 상태(등록 형식 비교) | `python3 <경로>` 형식: 프롬프트 차단, 모델 호출 0회. 설치 도우미 형식: 프롬프트 처리됨, 훅 오류 알림만 표시 |

모든 실행에서 `errors.jsonl`은 생기지 않았고, 트랜스크립트에 훅 오류도 없었습니다. `압축(훅)`과 `압축(CLI)`의 수는 모든 세션에서 같았습니다. 훅을 마지막으로 고친 뒤 최종 파일 그대로를 새 가짜 HOME에 설치해 위 시나리오(대기열 `scen_tui2` 제외)를 다시 돌렸고 결과는 같았습니다.

### 4.4 훅 1회 실행 시간

`tests/bench_hook.py`로 쟀습니다. 이벤트마다 별도 프로세스 40회, 턴 30개가 쌓인 세션, Linux 컨테이너 기준입니다.

| | Python 3.13 | Python 3.12 |
|---|---|---|
| 최종 훅 (세 이벤트 전체 중앙값) | 35.8ms | 37.9ms |
| 최종 훅, 설치 도우미가 등록하는 형식(`-I -c <실행기>`) | 36.3ms | 40.4ms |
| 프로토타입, 같은 조건 | 39.6ms | 43.7ms |
| 인터프리터 기동만(`python -I -c pass`) | 13.5ms | 11.3ms |

③ 보고서의 프로토타입 기준값은 중앙값 42ms였습니다. 최종 훅은 진단 기록을 더하고도 같은 조건의 프로토타입보다 느리지 않습니다. 훅 내부 처리 시간(인터프리터 기동 제외)은 실제 CLI 실행의 `events.jsonl`에서 중앙값 1.7ms였습니다. Windows에서의 시간은 재지 못했습니다(7절 3번).

## 5. 별도 표기 항목

| 항목 | 무엇이 막는가 | 둔 폴백 | 풀리는 조건 |
|---|---|---|---|
| Windows 11 실기 동작 전부 | 검증 환경이 Linux 컨테이너 | 바이트 입출력, 명시적 UTF-8, 바이너리 모드, ASCII 로캘 테스트, `.gitattributes`. 테스트는 표준 라이브러리만으로 Windows에서 돌게 작성(직접 돌려 보지는 못함) | 7절의 1~6번 |
| Windows에서의 훅 명령 형식 | 실기 없음. 바이너리상 `args`가 있으면 Windows에서도 셸 없이 직접 실행함은 확인 | 설치 도우미가 등록 전에 같은 명령을 직접 실행해 보고(`실행 점검`), 실패하면 등록하지 않음. 대비용으로 `--form powershell`, `--form bash` | 7절 4 · 5번 |
| `--form powershell` · `--form bash`(Windows) | PowerShell과 Git Bash가 없음. `bash` 형식은 Linux에서만 실행 확인 | 기본 형식이 아니며 대비용. 테스트가 해당 셸이 있으면 등록한 명령을 그 셸로 실행해 봄(CLI가 셸을 부르는 방식을 흉내 낸 것) | Windows에서 테스트 스위트 실행 |
| 턴 파일 읽기 권한 규칙(Windows) | 실기 없음. 대화형 권한 프롬프트의 모양도 확인하지 않음 | README에 규칙을 직접 추가하는 방법 기재. 없으면 대화형에서 그때그때 허용 | 7절 5번 |
| Windows의 `PermissionError` 재시도 경로 | Linux에서는 그 오류가 나지 않음 | `meta.json` 교체 10회 재시도 후 직접 쓰기, 읽기 6회 재시도 | 실사용 로그(`errors.jsonl`) |
| Windows에서의 훅 지연 | 미측정 | 잠금 대기 최대 2초, 훅 타임아웃 15초 | 7절 3번, 이후 `events.jsonl`의 처리 시간 |
| 2.1.33x 중 332만 실측 | 설치된 버전이 하나뿐 | 불확실한 필드는 모두 폴백 경로. `events.jsonl`이 페이로드의 키 이름을 남겨 차이를 드러냄 | 다른 버전에서 lab 재실행 또는 실사용 로그 |
| 실제 모델 응답 | 계정 · 비용 · 재현성 때문에 모의 API 사용 | 훅 배선은 실제 CLI 그대로. 모델이 실제로 턴 파일을 찾아보는지는 측정 대상 그 자체 | 1~2주 실사용 후 측정 스크립트 |
| 서브에이전트의 `agent_id` | 등록 대상 3개 이벤트에서 관측되지 않음 | 값이 있으면 기록 · 주입 없이 종료, `events.jsonl`에 `skip_agent` | 실사용 로그(측정 보고서의 "agent_id가 있던 훅 입력") |
| 저장 루트 전체에 쓸 수 없는 경우 | 오류를 남길 곳이 없음 | 조용히 exit 0. 세션 디렉터리만 못 쓰는 경우는 루트의 `errors.jsonl`에 기록 | 6절 2번을 적용하면 해소 |
| 훅이 시작을 보지 못한 턴이 자동 압축 시점에 진행 중인 경우 | 그 턴은 `Stop` 때 만들어지므로 해당 압축의 목차에는 없음 | 압축 뒤에도 그 턴은 대화에 남아 있고, 다음 압축부터 목차에 들어감 | 6절 4번 |
| 트랜스크립트 포맷 | 공식 문서에 없음 | 폴백 경로에서만 읽고, 실패하면 "(요청 미기록)" 또는 답변 없음 | 없음(버전마다 재확인) |
| `/clear` · fork 이후 | 새 세션 ID가 발급됨 | 새 색인으로 시작, 이전 색인은 원래 디렉터리에 남음 | 설계상 한계 |
| `prompt_id`가 없는 버전 | 폴백 규칙(open/done)만 적용 | 대기열 입력이 섞이면 귀속이 어긋날 수 있음을 감수 | 해당 버전에서 lab 재실행 |
| 사용자 PC의 기존 `settings.json` | 연결되어 있지 않음 | 병합 등록 + 백업 + `--dry-run`. 읽을 수 없는 JSON이면 바꾸지 않고 멈춤 | 7절 4번의 미리보기 출력 |
| `CLAUDE_CONFIG_DIR`로 설정 위치를 옮긴 환경 | 명세의 경로가 `~/.claude/ctx-index` | 설치 도우미는 그 변수의 `settings.json`을 기본 대상으로 삼지만, 훅의 저장 위치는 명세대로 `~/.claude/ctx-index` | 필요해지면 결정 |
| 기록의 정리 | 명세에 없음 | 자동 삭제 없음. 측정 보고서가 저장 크기를 보여 줌 | 6절 5번 |

## 6. 역제안 (구현하지 않고 남김)

승인된 범위 밖이어서 구현하지 않았습니다.

1. **설치 도우미에 턴 파일 읽기 허용 규칙을 넣는 선택 옵션.** 근거: 2.4의 2번. 허용 규칙이 없으면 헤드리스에서는 턴 파일을 읽지 못하고 대화형에서는 프롬프트가 뜹니다. 색인의 효용이 이 읽기에 달려 있으므로, `--allow-read` 같은 옵션으로 `permissions.allow`에 `Read(~/.claude/ctx-index/**)`를 병합하는 것을 제안합니다. 권한 설정을 바꾸는 일이라 기본 동작으로는 넣지 않는 편이 맞습니다.
2. **저장 루트에 쓸 수 없을 때 임시 디렉터리에 오류 기록.** 지금은 그 경우 아무 흔적 없이 exit 0으로 끝납니다. `tempfile.gettempdir()` 아래 한 파일에 남기면 완료 기준 a의 "예외를 기록"이 이 경우까지 닿습니다. 다만 저장 위치를 `~/.claude/ctx-index/`로 한정한 원칙 4와 닿아 있어 결정이 필요합니다.
3. **2a 단계에서도 필요한 만큼만 접기.** 지금은 미리보기를 절반으로 줄이는 단계에 들어가면 1차 구간이 통째로 접힌 채 남습니다. 합성 세션의 첫 압축 46~70턴에서는 미리보기를 줄인 것만으로 전부 들어가는데도(46턴: 접지 않으면 3,924자, 지금은 5턴을 접어 3,664자) 최근 5턴이 접힙니다. 최근 턴은 압축 직후에 가장 쓸모 있는 줄이므로, 2a에서도 A3와 같은 방식으로 최소한만 접는 것을 제안합니다.
4. **자동 압축 시점에 진행 중인 "훅이 시작을 보지 못한 턴"을 목차에 포함.** 대기열에서 꺼낸 턴이 실행되는 도중에 자동 압축이 일어나면 그 턴은 아직 색인에 없습니다. 압축 시점에 트랜스크립트에서 요청을 복원해 "(진행 중)"으로 넣을 수 있습니다. `/compact` 명령 자신의 항목을 요청으로 오인하지 않게 걸러야 해서 실측이 더 필요합니다.
5. **오래된 세션 디렉터리 정리.** 기록은 계속 쌓입니다. 측정 스크립트에 "N일 넘게 갱신되지 않은 세션 목록 / 삭제" 옵션을 두는 것을 제안합니다.
6. **측정 스크립트에서 주입 이후의 참조만 따로 세기.** 지금은 기간 안의 모든 참조를 셉니다. 세션별 첫 주입 시각 이후의 도구 호출만 따로 세면 "목차를 보고 찾아간 조회"를 더 직접 볼 수 있습니다.

## 7. Windows PC에서 실행할 명령

저장소 루트에서 실행합니다. 자세한 기대 결과는 [README의 Windows 확인 절차](../README.md#windows-확인-절차)에 있습니다.

| 순서 | 명령 | 확인할 것 |
|---|---|---|
| 1 | `py -3.12 -m unittest discover -s tests` | 마지막 줄 `OK (skipped=…)`. 실패나 오류가 있으면 출력 전체 |
| 2 | `py -3.12 lab/proto/sim_replay.py -q` · `py -3.12 -u lab/proto/sim_fold.py` | `37/37 passed`, `ALL FOLD SIMULATIONS PASSED` (선택) |
| 3 | `py -3.12 tests/bench_hook.py` | 훅 1회 실행 중앙값(Linux 36~38ms와 비교) |
| 4 | `py -3.12 tools/install_hook.py --dry-run` 후 `py -3.12 tools/install_hook.py` | Python · 훅 경로가 맞는지, `실행 점검: 통과`, 백업 파일 이름 |
| 5 | 새 Claude Code 세션에서 프롬프트 두세 개 → `/compact` → 과거 턴을 묻는 질문 | 턴 파일 생성과 한글 보존, 평소 주입 없음, 압축 뒤 목차 주입(`index.md`), 모델의 턴 파일 읽기와 권한 프롬프트, `errors.jsonl` 없음 |
| 6 | `py -3.12 tools/ctx_index_measure.py --days 1` | `턴 파일` 행의 횟수, `압축(훅)` = `압축(CLI)`, 훅 처리 시간 |
| 되돌리기 | `py -3.12 tools/install_hook.py --uninstall` | 등록 제거(백업 생성). 기록과 복사된 훅 파일은 남음 |

4번에서 `실행 점검: 실패`가 나오면 설정은 바뀌지 않은 상태입니다. 출력 내용과 함께 `py -3.12 tools/install_hook.py --form powershell`의 결과를 알려 주세요.
