# W05 Task4 Comparative Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 주 에이전트가 구현하고 AGENTS.md의 독립 계획/코드95점 게이트를 적용한다. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고정 입력과 설치된 두 CPU worker를 직렬 실행하고 원시 실패·결정성·정확도·시간을 분리한 검증 가능한 ledger와 선정 결과를 만든다.

**Architecture:** 기존 Python3.13 evaluator에 strict 출력 정규화, binary 이벤트 hash, 소유 프로세스 runner, 순수 집계/선정, 검증된 ledger 기반 Markdown report를 추가한다. 후보 Python3.12는 별도 프로세스로만 호출한다. Task1 reference/metric·Task2 manifest/audio·Task3 worker/checkpoint를 소비한다.

**Tech Stack:** 기존 uv/stdlib/NumPy/mir_eval/mido/FFmpeg와 common/pipeline run_owned_process/run_owned_io. dependency·lock 추가 없음.

**Spec:** [사용자 승인 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md) §5–9, [상위 실행 계획](transcription-model-evaluation-implementation-plan.md) Task4. Detail Revision3,2026-10-08 KST. BASE `245f175f7a051e1fdc124b02827d4d15b2662781`, branch `codex/w05-comparative-runner`. R1의 worker exit 귀속/미시작 slot 조건과 R3의 초과 크기 원시 파일 보존 경계를 구체화했다.

## Global Constraints

- Task4만 구현/검증한다. 실제 MAESTRO 모델 추론72회와 선정/기본 모델 결정은 Task5다. fake 결과를 실제 benchmark로 보고하지 않는다.
- root/API/기존 workers·전사 provider/schema/selector/locks·고정 MAESTRO manifest 불변. evaluator에 모델 import/설치/다운로드 없음. source/hash/device/options는 R2/R7 고정값 유지.
- CPU 두 후보만 받는다. 후보당36회/전체72회 예정; repeat0/2 manifest순 Basic→Piano,repeat1 역순 Piano→Basic. 직렬/fresh process, 자동 재시도0.
- 추론 timeout300초/세션7200초(4회 preflight와 진단 포함), process 종료·자손/I/O drain/출력 검사 완료까지 monotonic elapsed. 다운로드/설치·입력 준비·metric 계산은 모델 elapsed에서 제외. RTF=elapsed/30, nearest-rank p95.
- MIDI16MiB/전체100000event raw gate가 기존 Basic validator 및 모든 Mido 객체보다 선행한다. JSON8MiB strict duplicate/NaN/bool 검증. event/cell cap EvaluationLimitError→infrastructure/invalid benchmark/no_selection. 결과를 자르거나 샘플링하지 않는다.
- onset[2,28),offset cap30/원본offset<=31. 첫 반복12개만 정확도, 나머지는 반복/시간. 빈 valid 출력은 정상, 실패는 빈 출력 아님. paired nonempty>=8.
- 현 checkpoint/source/설치 경로는 불변으로 유지한다. 새 worktree로 absolute editable·data 경로를 복제하지 않고 clean checkout의 feature branch를 쓴다. ignored ledger/증거는 `outputs/.verification-w05/task4-20261008/`; 실행 산출물은 `outputs/w05-evaluation/`.

## Review Focus

1. 정상 output 직후 취소/cleanup exception을 성공으로 저장하지 않는다 — `test_cancel_after_valid_output_not_success`, `test_runner_cleanup_failure_not_model_error`.
2. 진단 성공이 첫 실패·예정36회/정확도 분모를 바꾸지 않는다 — `test_diagnostic_success_preserves_failure`.
3. 재현 가능한 model failure와 환경 실패를 구분한다 — `test_reproduction_requires_same_input_and_error`, `test_evaluator_limit_invalidates_selection`.
4. hash가 같아도 반복 수가 부족하면 자동 선정하지 않는다 — `test_incomplete_determinism_blocks_selection`, `test_one_bit_output_change_blocks_selection`.
5. ledger/summary/output 변조와 secret 문자열이 공개 보고서로 통과하지 않는다 — `test_report_rejects_tampered_artifact`, `test_public_report_no_raw_diagnostics`.

## 파일과 계약

Modify evaluator `contracts.py`, `cli.py`, README, 상위계획 Task4 진행, main_spec/roadmap. Create evaluator `results.py`, `determinism.py`, `selection.py`, `runner.py`, `session.py`, `report.py`; tests `test_results.py`, `test_determinism.py`, `test_selection.py`, `test_runner.py`, `test_report.py`, `fake_worker.py`, 공통 test fixture. `session.py`는 preflight/집계/ledger orchestration을 runner 단일 파일에서 분리한다. Tracked report `docs/reports/transcription-evaluation-runner-report.md`.

`Candidate` frozen: 기존 계획 id/python/device/checkpoint/checkpoint_sha256/lock_sha256/source_commit에 `lock:Path`, `runtime:dict`를 추가한다. id는 `basic_pitch/piano_amt`, device cpu, source 각 고정 commit, Python/lock/checkpoint 절대경로·해시64hex. Basic checkpoint도 설치된 nmp.onnx의 명시적 path/hash를 채운다. runtime은 metadata probe 영수증(Python/version/package/source/backend/옵션·thread정보)이며 model import를 하지 않는다. Byte torch cpu 배포는 worker와 metadata로 대조한다. Basic의 runtime thread는 upstream_default/unknown으로 남기며 같은 thread수라고 주장하지 않는다.

`RunRecord` frozen: 상위계획의 slot_id/recording_id/candidate_id/repeat/diagnostic_for/status/attribution/error_code/elapsed_sec/events_sha256/output_dir에 `started:bool`, `exit_code:int|None`, `evidence:tuple[str,...]`, `files:dict[str,str]`, `metrics:dict|None`를 추가한다. strict ID/enums/int/finite/hash·필수 상태 조합 검사. evidence/error_code는 코드 allowlist이며 외부 exception/stdout/경로를 넣지 않는다. files는 run root 상대 경로→SHA256, metrics는 아래 첫 실행/반복 schema다.

### A. 출력·hash

`normalize_output(candidate,output_dir,*,input_sha256,stop)->Events`:
- regular/unlinked paths·size 먼저, MIDI raw gate bytes는 후속 validator 전에 해제. Basic은 기존 validate_result_files 후 exact JSON top/provider/note key 및 bool/finite/positive interval/offset31을 추가 검사한다. Basic native JSON velocity_prediction/null을 사용하고 activation/confidence를 score로 쓰지 않는다. MIDI 구조 전체 검사는 기존 validator를 재사용하며 JSON과 정확한 시간 동등성은 요구하지 않는다.
- Piano wire exact keys/schema/sourceURL/commit/package/model/checkpoint filename/hash/inputhash/device/dtype/options/runtime/thread/duration30을 대조한다. notes pitch21..108/velocity1..127·sustain64..127·quantized positive interval 검사. Mido 전체 의미 parse의 key-release notes/pedals와 JSON quantized 이벤트 Counter를 대조한다. JSON raw timestamps를 metric/hash에 유지한다.
- 원본 JSON/MIDI와 정규화 events JSON을 보존한다. events hash는 binary 규약이며 JSON hash와 구분한다. `events_hash(Events)->str`: note/pedal 구획·count, 각 필드 little-endian binary64, null 별도 tag, -0→0; 사전식 정렬/null-first/pedal UTF8, duplicates 유지. 표준 struct/SHA256, tolerance0.

`score_output(entry,events)`는 검증된 reference JSON(기존 key_release/sustain ScoredEvents exact schema)을 읽고 prediction scoring_events(start0)를 적용한다. onset/key-release/sustain 각각 Metric dict, velocity MAE/pairs/정렬된 양 입력, reference/predicted censored/count를 저장한다. 최초12개 metric 및 반복별 F1 범위를 보존한다. reference file/hash를 실행 전에 재검사한다.

### B. 후보 준비·실행

`async prepare_candidates(basic_python,piano_python,checkpoint,checkpoint_sha256,*,cwd,cancellation)->tuple[Candidate,...]`: 고정 repo worker locks를 hash하고 각 Python을 `-I -c`의 작은 metadata-only probe로 실행한다. Python3.12/각 distribution version/direct_url pinned commit과 모델 자산 위치를 확인한다. Basic nmp.onnx hash·Byte checkpoint exactsize/MD5/SHA256을 기록한다. backend와 OS/CPU/core/RAM은 세션 metadata에 기록한다. argv literal, allowlist env/run_owned_process, stdout cap 안의 strict JSON. 모델 import·fallback 설치 없음. CLI는 사용자 지정 실행기만 사용한다.

`async run_slot(candidate,entry,*,repeat,slot_id,run_root,cancellation,timeout_sec=300,diagnostic_for=None)->RunRecord`:
1. 입력 WAV PCM16/mono/rate/정확30초 frame·hash, reference hash, candidate lock/checkpoint/source/runtime receipt를 owned I/O로 재검증한다. 준비 실패는 startedFalse/setup_failed/infrastructure다. existing slot/cwd/output 거부.
2. unique private `slots/<slot_id>/` cwd와 immutable `starts/<slot_id>.json`을 만든 뒤 process 시작 직전 clock을 잰다. installed Python `-I -c`로 각 CLI main(argv) 호출. Basic args2개, Piano checkpoint/hash/device 포함. 모델 argv 구성은 production 내부 고정 함수이며 fake-worker는 tests에서 이 경계만 바꾼다.
3. timeout은 process+owned I/O 출력 검증의 전체 경계다. process가 반환해야 자손정리가 확인된 것. output 생성만으로 성공 아님. 취소는 성공보다 우선. elapsed는 출력 검증/정리 후까지; metric 계산은 밖에서 수행하되 metric cap이면 success로 저장하지 않는다.
4. exit2→setup_failed/infrastructure,3→model_error/unresolved,4/exit0 후 malformed/missing output→output_invalid/unresolved. unexpected exit/timeout→unresolved. 기존 CLI3/4는 import/환경/I/O와 모델 원인을 합치므로 종료 코드나 같은 validation 오류의 반복만으로 model 승격하지 않는다. 설치/입력 gate 통과도 원인 증거를 대신하지 않는다. spawn/cleanup/permission/명시된 환경·입력·hash 문제→infrastructure, cap→infrastructure/evaluation_limit가 우선이다. 실제 model-attributed 판정은 독립 검증된 primitive cause를 가진 evidence가 있어야 하며 현 worker CLI가 그 증거를 제공하지 않으면 unresolved를 유지한다. 집계 fixture의 명시적 model cause는 가상 증거임을 표시하며 실제 CLI로 같은 원인이 검증됐다고 주장하지 않는다. error_code/evidence 정적 코드만 기록한다.
5. 실패나 취소에서도 소유 자식/I/O drain을 기다리고 원시 output·start 기록을 보존한다. 별도 `.part`만 정리한다. raw traceback/worker stderr를 ledger에 쓰지 않는다. 모델 결과 유효성 확인 후 metrics/events/artifact hashes를 기록한다.

### C. 세션·ledger

`build_schedule(manifest,candidates)->tuple[dict,...]`는 정확한 두 후보/12입력/72slot을 검증한다.
`async run_evaluation(manifest,candidates,*,manifest_path,input_root,ffmpeg,run_root,cancellation)->Path`: manifest_path를 load_manifest로 다시 확인해 준비·hash·고정 selection과 전달 manifest를 대조한다. run_root는 새 절대경로다. 중단된 이전 root를 resume/덮어쓰기하지 않는다. 새 run ID에서 first accuracy를 다시 시작해야 한다.

- session/manifest/candidate/environment receipts와72개 예정 schedule을 실행 전에 고정한다. 세션 시작/각 slot 전 budget·취소를 확인한다. run_root/source relative path와 파일 hash를 기록한다.
- preflight: tracked CC0 fixture(고정 SHA2970c7…/22050Hz monoPCM16)의 원본 PCM을 반복 연결해 정확30초로 crop한다. stereo 양 채널에 같은 신호를 넣은 source를 기존 prepare_audio(start0)로 변환하여 두 규격을 얻는다. FFmpeg version/argv/input/hash/실제frame 영수증을 남긴다. Task3의 silence-tail smoke를 재사용하지 않는다.
- 후보별2회 fresh process preflight는 첫 metrics/36분모/시간 통계에서 제외한다. 실패이면 preflight_failure, 예상 `1.5*36*(basic최대+piano최대)>7200`이면 budget_preflight_failure. 모든 benchmark slot을 not_run으로 남긴다. preflight4회 실행 시간은 session7200에 포함하며 input 준비 시간은 별도 기록한다.
- run_owned_process/run_owned_io와 공유 cancellation으로 모든 작업을 drain한다. max per-slot timeout은 min300,남은budget. 도구 task 취소/KeyboardInterrupt도 현재 slot cancelled, 나머지 not_run 기록을 drain해서 publish한다. crash로 terminal record가 없는 start는 report가 interrupted/infrastructure로 판정하며 complete/winner를 만들지 않는다.
- terminal `records/<slot_id>.json`은 exclusive temp+link로 no-overwrite atomic publish한다(기존 atomic_write의 replace는 이 용도에 사용하지 않음). starts와schedule은 immutable. summary에 모든 schedule/start/terminal/normalized/raw 파일 hash를 기록한다. source/reference의 영수증과 예상 hash는 시작 session에 포함한다.
- 초과 크기 raw 파일 때문에 finalization에서 무한 hash I/O를 하지 않는다. raw JSON8MiB/MIDI16MiB 이내의 파일만 bounded hash하며, 초과 파일은 그대로 보존하고 `unverified_artifacts`에 run-relative path/실제size/고정 reason=size_limit만 기록한다. 이는 full hash 검증을 주장하지 않는 예외이며 evaluation_limit/infrastructure/no_selection gate를 반드시 세운다. 보고서는 해당 파일의 일반파일·경로·size를 재확인하고 미검증 상태를 표시하며 winner를 만들지 않는다. 유효 파일/모든ledger는 계속 full hash 검증한다. symlink/비일반파일은 report에서 거부한다. regression은 작은 monkeypatched raw-size cap으로 finalization이 body를 hash/read하지 않음과 no_selection 보존을 확인한다.
- 예정 반복을 모두 실행한 뒤 recording/candidate의3개 성공 hash가 부족하고 primitive cause 증거가 확인된 같은 model error2회가 아직 없으면 실패 slot당최대1회 진단한다. 성공3개 확보 시 멈춘다. 진단은 독립 ID/diagnostic_for로 연결하고 원시 실패를 유지한다. 첫 정확도·36분모·속도에서 제외, budget에는 포함한다. 같은 recording/input/candidate/source/hash/primitive cause의 model-attributed 독립2회만 reproducible failure이며 다른 input/원인으로 합치지 않는다. generic exit3/4·동일validation실패 횟수는 이 근거가 아니며 unresolved default를 override하지 않는다. 현 CLI의 원인 분류 한계를 보고서에 기록한다.
- safe progress: 완료/예정72·고정 candidateID/status만 출력, <=60초 장시간 slot은 UI commentary로 진행을 알린다. stdout/exception/사용자경로는 공개 출력에 포함하지 않는다.

### D. 집계·선정·보고

summary version1은 gates/host/manifest/candidates/records/artifacts와 model별 `first_runs`(recordingID→3metric/velocity/censor 또는null), `determinism`(recordingID→status/hashes/F1range), `elapsed_sec`(유효 성공 nondiagnostic만), `reliability`(scheduled36/started/success/status별counts/not_run/raw failure율/model-only분모/infra·unresolved제외count), `operationally_ineligible`와 재현 근거를 담는다. operational recall=첫 성공TP합/예정12reference합; 실패를 metric0 빈예측으로 생성하지 않는다. 두 reference 종류 각각 집계한다.

`select_model(summary)->dict`는 metric counts/fields/finite/modelIDs/12동일IDs/분모/상태를 검증하고 원시 첫 metrics로 macro/micro/paired값을 계산한다. summary가 gate 실패·첫 반복 누락·not_run·cap/invalid benchmark이면 no_selection. 그 후 재현 부적격/결정성/미해결 원인→tradeoff→winner 순서로 처리한다. first accuracy가 실패하면 진단으로 복구되지 않으므로 no_selection이 우선이며, later reproducible failure의 후보 부적격은 별도 표시한다. 한 후보만 나중에 부적격이고 다른 후보가 비교가능/결정적이면 정확도 winner 없이 provisional 운영안으로 기록한다.

- hash3개 동일→deterministic_observed, 불일치→nondeterministic_output, 부족→determinism_incomplete. 불일치/부족/미해결 원인은 selection_requires_review. 원시 실패율은 그대로 유지한다.
- nonempty paired>=8. NumPy Generator(PCG64(20261005)),10000개 paired 재표본 indices를 onset/sustain에 공통 적용한다. percentile2.5/97.5 methodlinear. macro효과>=.01/CI0미포함만 우위. micro 역전>=.01, onsetwinner sustainmacro열세>.01, sustainwinner onsetmicro열세>=.01이면tradeoff.
- 우위 없으면 CPU성공표본 각각>=24, median20%차이를 운영 근거로 사용하고 양micro역전guard 유지. 부족이면selection_requires_review, 뚜렷한차이없으면Basic provisional_operational_default. 경계 비교는 보고된 decimal 수치로 Decimal(str(value)) 차이를 사용해 의도된1pp/20% 경계를 float subtraction 오차로 바꾸지 않는다. event hash에는 tolerance가 없다.
- decision에는 status/winner/reason/pairedN/CI/accuracy_winner/product_status를 기록한다. Byte 선택이면 product_status=selected_pending_integration, selector 자동변경 없음.

`write_report(run_dir,destination)`는 strict summary canonical hash와 referenced ledger/artifacts를 모두 재검증하고, ledger에서 재계산한 집계/결정과 대조한다. relative path 탈출/변조/중복slot/누락terminal record/최종원장 불완전은 거부하며 winner 보고서를 만들지 않는다. startedTrue에는 start가 필수이고 startedFalse의 setup_failed/not_run에는 start가 없어도 정상이다. orphan start(terminal 없음)는 interrupted/infrastructure로 판정하며 complete/winner를 만들지 않는다. 정상적으로 기록된 preflight failure/준비 실패/취소·미시작 세션은 no_selection 보고서를 만들 수 있다. destination은 새 regular `.md`, atomic no-overwrite. 공개 표는 고정 headings/상태/recordingID·수치·hash만 사용하고 raw stdout/exception/경로/임의 runtime 문자열을 삽입하지 않는다. per-recording/첫accuracy/repeats/실패·진단/CPU개별시간·median/p95/velocitypair·censor/준비시간/source/license/지원한계/선정 근거를 구분한다.

CLI `run --manifest --input-root --basic-python --piano-python --checkpoint --checkpoint-sha256 --output-root --ffmpeg`와 `report --run-dir --output`를 추가한다. output-root 아래 새로운uuid run을 만들고 기존run은 건드리지 않는다. CLIrun은 cancellation을 세션으로 전달하고 safe JSON status/runID/hash를 출력한다. 설정 실패4,취소130,완료0(선정불가여도 기록된 세션완료는0),help0. prepare 기존계약 유지. ffmpeg는 명시적 경로 또는 검증된 PATH resolve이며 설치하지 않는다.

## 구현·검증 단계 (하나의 Task4 구현 단위)

- [x] 계획 본문 SHA와 독립5rubric 평가>=95/B0I0를 기록한다. 이전 계획 점수 재사용 금지.
- [x] contracts/output/hash/selection 테스트를 먼저 작성하고 RED를 본다. Worker output fixtures는 독립 Mido/JSON으로 만든다. hash golden binary를 손으로 고정하고 null/-0/sort/duplicates/one-bit를 검사한다. 양후보cap가 Basic validator/Mido보다 앞섬, provenance/options/hash/bool/NaN/duration/padding31·overlap·missing/truncation를 확인한다. 선택 손계산 fixture는12개 중8이상nonempty·first/repeats구분·macro/micro반전·CIcross0/1pp/offset/24표본/20% guard·Bytepending을 검사한다.
- [x] 최소 contracts/results/determinism/selection 구현 후 선택 GREEN. 새로운 production동작은 대응 RED가 있어야 한다.
- [x] runner/session/report/CLI 테스트 RED. fake worker를 실제 소유 프로세스로 실행해 success/exit3/invalid/timeout/cancel/자손정리/cleanup failure와 elapsed를 검증한다. Python testfixture만 사용하고 actual weights/network 금지. 순수 세션 orchestration 테스트는 run_slot 경계만 fake로 대체하고 schedule/immutable ledger/first accuracy·진단·budget·not_run/repro/선정을 실제 코드로 검증한다. slot별process tests는 소유 process boundary를 교체하지 않는다. preflight audio 반복연결은 실제 PCM byte/hash/frame 경계검사와 기존 FFmpeg tests로 검증한다.
- [x] R1 리뷰 회귀: 동일 generic exit3/4를 두 번 기록해도 operationally_ineligible가 되지 않고 unresolved가 model-only 분모에서 제외됨을 검사한다. preflight failure/startedFalse setup_failed/not_run은 start 없이 no_selection 보고서를 만들 수 있으며 startedTrue missing start와 orphan start는 불완전/중단으로 거부됨을 확인한다.
- [x] 최소 runner/session/report/CLI 구현 후 선택 GREEN. metric event/cell cap→infrastructure invalidbenchmark, output검증후cancel, partial/crashrecord·기존root/파일보존을 검사한다.
- [x] evaluator 전체와 root 회귀, CLIhelp/import no models, diffcheck/docslinks/5locks+manifest 불변. 검증 parent 먼저 생성하고 매번 새 절대basetemp/config/testpath를 사용한다. 기본 Windows suite 증거만 지원 주장한다.
- [x] 보고서/상위Task4체크/README/index/roadmap에 RED/GREEN/정확명령/실제범위/계획·코드score기록. 전체 staged파일 SHA snapshot으로 독립 코드리뷰>=95/B0I0. 문제 수정 시 새 RED/GREEN·재리뷰. 그 뒤 원자적 commit `feat(eval): record reliable comparative model runs`.
- [ ] 기존 사용자 통합 요청에 따라 PR/merge/동일tree·main동기화/작업branch정리. Task5는 시작하지 않는다.

### 실행 명령과 합격 기준

```powershell
$env:PYTHONUTF8='1'
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests --collect-only -q
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests/test_results.py tools/transcription-eval/tests/test_determinism.py tools/transcription-eval/tests/test_selection.py tools/transcription-eval/tests/test_runner.py tools/transcription-eval/tests/test_report.py -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task4-20261008/t4-red --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task4-20261008/t4-full --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -c pyproject.toml tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task4-20261008/t4-root --tb=short
```

Expected RED: missing Task4 symbols/modules/behavior, fixture/setup/permission errors는 제외. GREEN: 해당project만collect, 모든 기본tests통과와 실제 model/network0. root기본opt-in skip은실제검증아님. report에는 fake evidence임을표시. Task3 live/data 취득반복 금지. `uv lock --check --offline` evaluator/두worker/root/API와 SHA baseline 불변, gitdiffcheck, 새doclink전부존재. 외부서비스/Docker변경없음.

## 독립 계획 리뷰

2026-10-08 `/root/w05_task4_plan_review`: Revision1 SHA256 `326E75E78941442914E9C39E1BCA0F541D1AA32D2D298AFA4F2636E7BE97421D`, 요구24/범위18/순서20/검증22/재현10=94점,B0/I1/M1로 미통과. important generic exit3/4→model 귀속은 Revision2에서 unresolved 기본/primitive cause 증거 필수로 수정했다. minor는 startedTrue에만 start 필수, 미시작 terminal 허용, orphan start 중단 처리로 보완했다. 두 대응 회귀를 명시했다. Revision2 별도 reviewer 재평가 대기. >=95와 미해결 blocker/important0 전에는 Task4 코드를 작성하지 않는다.

2026-10-08 `/root/w05_task4_plan_review`: Revision2 본문 SHA256 `E57AA5507C251F355CFADD755DE20BE288466FF0C052AB8CD1488FA971745463`, 요구25/범위20/순서20/검증25/재현10=**100점**,B0/I0/M0. R1 두 지적의 계약·회귀 및 전체 계획/사양/현재 구현을 재대조했다. **R2 계획 게이트 통과 후 출력/hash/선정/단일slot 구현 시작**. 이 승인 기록 전 본문 hash이며 코드 리뷰와 별도다. 세션 finalization 구현 전에 R3의 raw oversize 예외 계약을 추가했으며 해당 새 계약은 R3 재평가 뒤에만 구현한다.

2026-10-08 `/root/w05_task4_plan_review`: Revision3 본문 SHA256 `77FE2973EC3FADB58375A344416E032F3FECFAD9B3BC04AEF30B3584F5591DE6`, 요구25/범위20/순서20/검증25/재현10=**100점**,B0/I0/M0. 전체 계획과 bounded hash/미검증원본/no_selection 예외를 다시 검토했다. **R3 승인 후 세션 finalization 계약 구현 시작**. 승인 기록 전 hash이며 코드 리뷰 별도다.

## 독립 코드 게이트

2026-10-09 `/root/w05_task4_final_review`: 최초89점(22/21/23/14/9),B0/I4/M0, tree `f5126e51dfd37ffe83cd57412ee9a2415705214d`. 수치1pp 경계·MIDI byte cap 귀속·metrics 전체 strict 검증·필수 공개 지표 누락을 RED/GREEN으로 보완했다. 최종 재평가 **100점(25/25/25/15/10),B0/I0/M0**,22파일/tree `30f31010de484ac965ba63af91e6ff9f4e8da26f`, snapshot SHA256 `023901AB80E56EA07C15EEDCDC9362BF528FF976B8E31CCD5ECF9E1F19F9C7A4`. 최종evaluator255pass77.42초, root394pass17skip8deselected28.08초. 리뷰어 독립254pass75.56초·최종 경계24pass5.47초. 세부 지적 처리와 재현 명령은 [결과보고서](../reports/transcription-evaluation-runner-report.md)에 있다. Task5 실제 비교는 시작하지 않았다.
