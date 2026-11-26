# lab — ③ 사전 검증 자료

`ctx-index` 훅을 구현하기 전에 실제 Claude Code의 훅 이벤트 스키마를 확인하고 설계를 미리 시험해 본 자료입니다. 보고서는 [`docs/phase3-report.md`](../docs/phase3-report.md)에 있습니다.

**이 디렉터리는 최종 산출물이 아닙니다.** `proto/ctx_proto.py`는 설계 검증용 프로토타입이며, 훅 본체 · 테스트 스위트 · 측정 스크립트는 승인 후(④)에 따로 작성합니다.

## 구성

| 경로 | 내용 |
|---|---|
| `proto/ctx_proto.py` | 프로토타입 훅(턴 귀속 상태 기계, 목차 렌더링, 접기) |
| `proto/sim_replay.py` · `sim_replay.out` | 실측 페이로드 재생 시뮬레이션과 그 결과(37/37) |
| `proto/sim_fold.py` · `sim_fold.out` | 합성 장기 세션의 접기 · 상한 시뮬레이션과 그 결과 |
| `captures/v1/` | 전체 훅 이벤트 캡처(스키마 근거). `probe_hook.py`로 채집 |
| `captures/v2/` | 등록 대상 3개 이벤트 캡처 + 훅 실행 시점의 트랜스크립트 크기. `probe_hook2.py`로 채집. 재생 시뮬레이션의 입력 |
| `captures/v2/transcripts/` | 위 캡처가 참조하는 세션 트랜스크립트의 슬림본 |
| `probe/` | 캡처 도구: 모의 Messages API, CLI 격리 실행기, 헤드리스 · TUI 드라이버, 시나리오, 프로브 훅 |

캡처와 시나리오의 대응은 다음과 같습니다(Claude Code 2.1.332에서 채집).

| 캡처 | 시나리오 | 내용 |
|---|---|---|
| a | `drive.py scen_a` | 일반 / 도구 / 서브에이전트 / 커스텀 슬래시 / 브랜치 전환 / `/compact` / 내장 명령 / 빈 답변 / `/clear` |
| b | `drive.py scen_b` | 자동 압축(모의 사용량 `MOCK_BIG_TOKENS`)과 수동 압축 |
| c | `scen_c.sh` | Stop 훅 차단으로 Stop 2회, `--resume`, `--continue`, `--fork-session` |
| d | `tui_drive.py scen_tui` | TUI: 내장 명령, Esc 중단, bash 모드, `/compact`, `/clear`, `/exit` |
| e | `tui_drive.py scen_tui2` | TUI: 작업 중 입력(대기열) — 별도 턴 / 진행 중 턴에 흡수 |
| stacked (v2) | `tui_drive.py scen_tui3` | TUI: 중첩 대기열, 유휴 상태의 일반 · 커스텀 슬래시 |
| headless (v2) | `drive.py scen_g` | 일반 / 커스텀 슬래시 / 백그라운드 서브에이전트 알림 |
| f (v1) | `probe-settings-exec.json` | `command` + `args`(셸 없는 실행) 형식 훅 |

## 시뮬레이션 실행 (Python 표준 라이브러리만 필요)

```bash
python3 lab/proto/sim_replay.py
```

```bash
python3 -u lab/proto/sim_fold.py
```

두 스크립트 모두 실패가 있으면 0이 아닌 코드로 끝납니다. `sim_fold.py`는 30초가량 걸립니다.

## 실측 재캡처 (Claude Code CLI 필요, Linux/macOS)

CLI 버전이 바뀌면 스키마를 다시 확인할 때 씁니다. 실제 CLI를 빈 HOME · 가짜 API 키 · 로컬 모의 API로 격리 실행하므로 계정과 비용이 들지 않습니다.

```bash
cd lab/probe && python3 setup_lab.py --fresh
```

```bash
MOCK_BIG_TOKENS=990000 MOCK_SLOW_SECS=8 python3 mock_api.py 8765 .run/out/requests.jsonl &
```

```bash
mkdir -p .run/out/headless && PROBE_SETTINGS=probe-settings2.json PROBE_OUT=$PWD/.run/out/headless/payloads.jsonl python3 drive.py scen_g
```

```bash
mkdir -p .run/out/stacked && PROBE_OUT=$PWD/.run/out/stacked/payloads.jsonl python3 tui_drive.py scen_tui3
```

```bash
PROBE_OUT=$PWD/.run/out/c/payloads.jsonl ./scen_c.sh
```

프로토타입을 실제 훅으로 등록해 종단 실행을 보려면 다음과 같이 합니다.

```bash
CTX_INDEX_DIR=$PWD/.run/out/e2e-ctx PROBE_SETTINGS=proto-settings.json python3 drive.py scen_e2e
```

채집한 캡처를 커밋할 수 있는 형태로 정리합니다.

```bash
python3 pack_captures.py .run/out ../captures/v2 --map "$PWD/.run=/lab/probe" --map "$PWD=/lab/probe" --map "$(dirname "$PWD")=/lab"
```

- 시나리오마다 `PROBE_OUT`을 `<이름>/payloads.jsonl`로 나눠 두어야 `pack_captures.py`가 캡처별로 묶습니다.
- 전체 이벤트를 보려면 `PROBE_SETTINGS=probe-settings.json`(v1 프로브)을 씁니다.
- 브랜치 전환 시나리오(`scen_a`)는 테스트 프로젝트에 브랜치를 만들므로, 다시 돌리기 전에 `setup_lab.py --fresh`로 초기화합니다.
- `sim_replay.py`의 stacked 검사 한 건은 모의 API의 답변 일련번호("답변 9", "답변 10")에 묶여 있어, 새로 채집한 캡처에서는 번호가 달라질 수 있습니다.

## 캡처 정리 규칙

커밋된 캡처는 원본을 `pack_captures.py`로 정리한 것입니다.

- **경로 · 모델 이름 정규화**: 채집한 기기의 절대 경로를 `/lab/probe/…`로 바꿨습니다(CLI가 프로젝트 디렉터리 이름으로 쓰는 대시 표기도 같이). CLI가 요청한 모델 이름은 `claude-mock`으로 바꿨습니다(모의 API는 모델을 구분하지 않습니다). 그 밖의 값(세션 ID, `prompt_id`, 시각, 프롬프트와 응답)은 그대로입니다.
- **트랜스크립트 슬림화**: `user` / `assistant` / `system` / `queue-operation` 줄만 남겼습니다. 원본에는 CLI 내부 프롬프트 스냅샷과 API 요청 본문이 들어 있어 그대로 커밋하지 않습니다(11개 합계 약 2.5MB → 약 0.2MB).
- **`tx_size` 재계산**: 훅 실행 시점의 트랜스크립트 크기를 슬림본 기준으로 다시 계산했습니다. 원본의 `tx_size`는 71건 모두 줄 경계였고, 프로토타입은 `user` / `assistant` 줄만 읽으므로 재생 결과는 원본과 같습니다. 원본으로 돌린 결과와 비교하면 작업 알림 턴의 크기 표기(경로 길이 차이)만 다릅니다.

## 주의

- `run_cli.sh`는 `env -i`로 환경을 비우고 실행합니다. 실제 계정이나 작업 중인 세션의 환경 변수를 물려받은 채로 CLI를 중첩 실행하지 마세요.
- `probe/.run/`은 커밋하지 않습니다(`.gitignore`에 있음). 모의 API 요청 로그에 CLI 시스템 프롬프트 전문이 남습니다.
- `sk-ant-mock-…` 값은 형식만 맞춘 자리 표시자이며 실제 자격 증명이 아닙니다.
- 캡처 도구는 pty와 bash를 쓰므로 Windows에서는 동작하지 않습니다. 시뮬레이션 두 개는 OS와 무관합니다(Windows 실행은 미검증).
