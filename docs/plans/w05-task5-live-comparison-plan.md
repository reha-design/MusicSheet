# W05 Task5 실제 비교 실행 계획

Revision1 · 2026-10-10 KST · BASE `ce84a3b47bd939d3099bd604dbec34380d7a3a0b` · branch `codex/w05-live-comparison`.

**목표:** 승인된 [설계 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md) §5–9와 [상위 계획](transcription-model-evaluation-implementation-plan.md) Task5에 따라 최초 실제 CPU 비교를 실행하고 검증된 기록으로 선정 가능 여부를 판단한다. 구현은 executing-plans 스킬로 주 에이전트가 수행하고 AGENTS.md의 독립 계획/단위/전체 리뷰를 각각 적용한다.

## 범위와 불변 조건

- Task4 CLI/runner/선정 기준을 그대로 소비한다. root/API/provider/schema/selector/workers/5개 lock/manifest/모델 자산 변경 없음. 실제 결과에서 결함을 발견하면 먼저 별도 계획 개정·독립 재평가한다.
- 기존 clean checkout에 feature branch를 사용한다. 설치된 editable 환경과 고정 절대 데이터 경로를 복제하지 않는다. Task4와 같은 격리 방식이다. 증거는 ignored `outputs/.verification-w05/task5-20261010/`, 실제 실행은 `outputs/w05-evaluation/task5-20261010/cpu-<uuid>/`에 보존한다.
- manifest `docs/evaluations/maestro-w05-manifest.json`, input-root `outputs/w05-evaluation/task2-20261006`, 두 worker `.venv/Scripts/python.exe`, checkpoint `models/w05/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth`/SHA256 `c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141`을 고정한다. FFmpeg는 `C:/ffmpeg-6.0-essentials_build/ffmpeg-6.0-essentials_build/bin/ffmpeg.exe`.
- 두 CPU 후보, 12개×3회×2후보=72개 예정 slot, 후보당 비평가 preflight2회, 직렬 fresh process, 자동 재시도0. preflight는 원본 CC0 PCM 반복 후30초 crop이며 silence-tail로 바꾸지 않는다. slot300초/전체7200초와 사전 예상시간 gate를 유지한다. 진단은 기존 규칙만 적용하고 첫 실패를 대체하지 않는다.
- **초기 세션 CLI는 한 번만 실행한다.** 실패/시간 gate/미측정도 결과다. 임의 재실행·입력 변경·sample 축소·한계 변경으로 승자를 만들지 않는다. 새로운 실행이 필요한 수정은 원래 ledger를 보존하고 개정 계획/별도 ID로 구분한다.
- MAESTRO 비상업 연구·개인 개발 평가 승인 범위, 별도 GPU/Linux/실제 YouTube 평가 없음. 실제 결과를 그 범위로 일반화하지 않는다. 모델 평가 중 CPU 부하를 만드는 테스트/병렬 모델 실행은 금지한다.

## 구현 단위: Task5 기록·검증

1. 독립 reviewer가 본 R1 전체를 계획 rubric25/20/20/25/10으로 평가하고 **95점 이상, blocker/important0**일 때 진행한다. 리뷰 버전·SHA256·날짜·점수·지적 처리 기록을 남긴다.
2. `tools/transcription-eval/tests/test_live_evaluation.py`를 추가한다. 기본은 `MUSICSHEET_W05_LIVE=1`이 아니면 명시적 skip. `MUSICSHEET_W05_RUN_DIR`가 없으면 명시적 skip하며 실제 benchmark PASS로 계산하지 않는다. 설정된 경우 절대 경로의 **기존 최초 세션을 검증**하고 모델 추론/설치/다운로드를 다시 실행하지 않는다. `load_verified_run`의 전 artifact/summary/derived 검증과 추가 manifest/CPU 후보/source/options/모델 hash/두 출력 파일/first12/72 예정 상태·preflight 확인을 한다. partial/no_selection 원장은 무결성 PASS와 평가 미완료를 구분한다. source/options/hash는 Task4 상수·고정 설치 영수증과 대조한다. 무결성 테스트 통과가 모델 선정 통과라는 의미가 아님을 테스트/doc에 명시한다. 새 검증 helper 경계는 fixture 기반 정상/변조/누락 환경 테스트로 확인하고 이미 GREEN인 기존 기능에 가짜 RED를 만들지 않는다.
3. 실행 전 5개 lock, manifest, checkpoint, 두 모델 자산 hash와 git BASE를 기록한다. CLI run/report `--help`, evaluator import, frozen manifest 전체 input/reference 검증, 설치 metadata-only probe를 확인한다. 이후 5개 프로젝트 collect-only와 full offline/no-sync suite를 실행한다. 실제 모델 세션과 겹치지 않는다. 실패는 수정 전 원인/계획 범위를 확인한다.
4. 위 gate 후 README의 절대 경로 CLI로 최초 실제 CPU 세션을 실행한다. stdout/stderr를 ignored 로그에 보존하고 실행 프로세스 handle을 소유한다. <=60초 간격으로 완료/예정72·잔여·최신 상태를 전달한다. preflight 진행도 파일/start receipt로 확인한다. Ctrl-C/오류 시 원장·소유 child/.part 정리 상태를 확인하며, CLI exit0만으로 성공 선정이라 부르지 않는다. `summary.json`을 `load_verified_run`으로 다시 검증한다.
5. CLI report로 **새 파일** `docs/evaluations/transcription-model-selection.md`를 생성한다. `docs/reports/transcription-model-evaluation-report.md`에는 명령/실제 run ID와 summary hash/시간/환경/결론/제약을 기록한다. 기본 모델 상태를 정확히 기록한다: Byte winner도 `selected_pending_integration`, 제품 selector 불변. 두 후보 유효 CPU 비교와 결정 근거가 없거나 unresolved/review_required/no_selection이면 **W05 진행 중 유지**하고 미측정 정확도·속도를 수치로 추정하지 않는다.
6. first12 onset/sustain/key-release P/R/F1와 macro/micro/counts, velocity MAE/pairs/censor, paired CI, 원시36 상태·진단·결정성/F1범위, CPU samples/median/p95/RTF, runtime/thread/source/license를 검증한다. 원시 arrays/weights/audio/MIDI/secret은 tracked하지 않는다. 실패 시 공개 보고서는 고정 오류 코드와 관측된 경계만 기술하고 원인을 추측해 model failure로 바꾸지 않는다.
7. evaluator README·canonical `docs/ai/transcription.md`, `docs/ai/model-adapters.md`·main_spec·roadmap·completed-work·상위 계획의 상태/링크를 실제 결과에 맞춰 갱신한다. partial 실행 기록은 완료된 모델 선정과 구분한다. opt-in 기존 원장 검증을 별도로 실행하고 default suite skip와 실제 검증 결과를 분리한다.
8. Task5 전체 변경을 독립 code rubric25/25/25/15/10으로 평가, **95점 이상/B0I0** 확보한다. 지적 수정 시 필요한 RED/GREEN/전체 관련 suite·재리뷰를 적용한다. 이후 별도의 fresh reviewer에게 **전체 W05 Task1–5 현재 코드/사양/보고서/실행 증거** 리뷰를 의뢰하고 95점 이상/B0I0을 확보한다. 두 gate를 서로 대체하지 않는다. 리뷰 중 실제 추론 재실행은 금지한다.
9. `git diff --check`, Markdown 로컬 링크, 5lock/manifest/모델 hash 불변, tracked 바이너리/secret 부재와 소유 프로세스/임시 파일 정리를 확인한다. `docs(amt): record fixed transcription model comparison`으로 명시 stage·commit한다. 기존 사용자 push/PR/병합/완료 branch 정리 승인에 따라 PR 생성·attach·정확 head 확인 후 병합하고 main 동기화·동일 SHA/ancestor 검증 후 해당 branch만 정리한다. 실제 변경/보고가 partial이면 PR에도 W05 미완료를 명시한다.

## 검증 명령과 합격 기준

모든 명령 cwd `D:/develop/MusicSheet`; `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project <P> --python <V> pytest -c <C> <T> --collect-only -v`로 config와 test 경로를 먼저 확인한다. full은 같은 명령의 collect 부분을 `-q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task5-20261010/<unique-name> --tb=short`로 바꾼다.

| P | V | C | T |
|---|---|---|---|
| . | 3.13 | pyproject.toml | tests |
| services/api | 3.13 | services/api/pyproject.toml | services/api/tests |
| services/ml/basic-pitch-worker | 3.12 | services/ml/basic-pitch-worker/pyproject.toml | services/ml/basic-pitch-worker/tests |
| services/ml/piano-amt-worker | 3.12 | services/ml/piano-amt-worker/pyproject.toml | services/ml/piano-amt-worker/tests |
| tools/transcription-eval | 3.13 | tools/transcription-eval/pyproject.toml | tools/transcription-eval/tests |

각 `uv --cache-dir outputs/.uv-cache lock --check --offline --project <P>`는 exit0, collect는 대상 config/tests만, full은 failures0이어야 한다. 의도한 opt-in/외부 환경 skip은 수와 이유를 기록한다. 최종 코드 변경 후 대상 full suite가 필요하며 문서만 변경한 경우 전체 suite를 중복하지 않는다.

실행은 evaluator project의 `transcription-eval run`과 README 고정 인수를 사용한다. report는 `transcription-eval report --run-dir <실제 절대run> --output D:/develop/MusicSheet/docs/evaluations/transcription-model-selection.md`이다. opt-in은 `MUSICSHEET_W05_LIVE=1`, `MUSICSHEET_W05_RUN_DIR=<실제 절대run>`을 일시 설정하고 test_live_evaluation만 실행한 뒤 finally에서 이전 환경을 복원한다. partial이어도72개 예정 terminal과 immutable/hash/상태 정합성이 있어야 하며 고립 start/변조/누락 출력을 성공 처리하지 않아야 한다. 프로세스 crash 등으로 검증 불가능한 원장은 보존하고 report 생성 불가로 기록한다.

## Review / execution ledger

- Plan R1 독립 리뷰: 2026-10-10, `/root/w05_task5_plan_review`, **99/100, B0/I0/M1**. rubric25/20/20/25/9. 리뷰 본문 SHA256 `C6901075ED079B53D0CB5AAE273742B2BF0077D584291B38F41FC56B5C50FB62`. minor는 README의 일반 task5 경로와 날짜 포함 실행 경로의 차이이며 실제 명령에 `task5-20261010`을 명시해 처리한다. 아래 실행 기록만 추가하며 승인된 실행 절차는 변경하지 않는다.
- 기존 runner/report를 소비하는 검증 통합은 최초 실행부터 GREEN(10pass/1skip); 새 모델 동작을 구현하거나 기존 동작의 RED를 만들지 않았다. manifest/order/checkpoint/lock 변조 5경계와 opt-in 누락/상대 경로를 검증했다.
- Task5 code: 2026-10-10 `/root/w05_task5_code_review`, **100/100 (25/25/25/15/10),B0/I0/M0**. 검토 tree `1c5eb8ed307bb0e2b340c72ef32a4c3e77d367d3`, raw snapshot `2BBC251DFD7B4FA1CE0ACDB8CD6DA64C2DA1C2CD1C3D14CC5AE730860816D243`. 독립 captured11pass/default10pass1skip·첫24개 직접 재채점 불일치0. 실제72success/4preflight success/diag0, 제품 연결 대기 경계를 확인했다. 상세 증거는 결과보고서.
- Task5 최종 문서 재확인: 동일 reviewer100/B0I0M0, tree `fbbef25ffd6d16ebc1792d314e8b23abe85f9f97`, snapshot `BB5AEF1D20FED0F7D5ACC87B9AFD0FCE15CCF8683D67C980A78F4A99AE60C6B0`. 구현·test·원장 변경 없음.
- Whole W05: 2026-10-10 별도 fresh `/root/w05_whole_final_review`, **100/100 (25/25/25/15/10),B0/I0/M0**, 같은 최종 tree/snapshot. W05 Task1–5 코드/계약/사양/실제 증거 전체, 독립96pass·Piano71pass1skip, 원본MIDI→정답12/12·첫24재채점24/24 일치. W05 평가·선정 완료 승인. 최종 점수와 통합 감사 기록만 이후 추가한다.
