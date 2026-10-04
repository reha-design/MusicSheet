# W04 Basic Pitch Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (주 에이전트 구현) 또는 사용자 선택 시 superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. 어느 방식이든 AGENTS.md의 단위별 독립 리뷰 95점 게이트를 유지한다.

**Goal:** Python 3.13 TRANSCRIBE 단계에서 독립 Python 3.12 Basic Pitch를 실행하고 검증된 JSON·MIDI를 기존 아티팩트·DB 계약으로 등록한다.

**Architecture:** 작업별 subprocess 연결부가 WAV 규격 변환, 모델 CLI 호출, 결과 검증, 저장을 수행한다. 소유한 process tree와 I/O thread를 모두 회수한 후 반환하며 기존 runner의 fingerprint·DB 완료·취소 fence를 재사용한다.

**Tech Stack:** Python 3.13 backend, Python 3.12 isolated ONNX CPU worker, FFmpeg, mido 1.3.3, uv, pytest, LocalStorage, asyncpg/PostgreSQL 16.

**Spec:** [사용자 승인 설계 R1](../superpowers/specs/2026-10-04-basic-pitch-pipeline-design.md), [전사](../ai/transcription.md), [모델 어댑터](../ai/model-adapters.md), [런타임](../infrastructure/runtime.md), [아티팩트](../domain/artifacts.md).

- Plan Revision: 4 · 2026-10-04 (Asia/Seoul) · 기준 `a1fd862`, branch `codex/celery-orchestration`. R4는 Task1 독립 구현 리뷰의 Linux 시작/취소 경쟁을 반영한 private gate 준비·완료 handshake 보완이며 공개 provider 계약과 Task2~4 범위는 유지한다.
- 사용자 서면 설계 승인: 2026-10-04 `다음작업 진행` (설계 R1 제시 후 응답).
- 독립 계획 리뷰: R1 **94/100** → R2 **99/100** → R3 **100/100**, blocker0/important0/minor0. R3 전체에 대한 독립 재리뷰로 설계·계획 단계를 완료했다. 아래 실행 승인 이후 제품 구현을 진행한다.
- 작성된 실행 계획의 사용자 실행 승인: 2026-10-04 `다음 과정 진행`. 주 에이전트 구현 + 각 단위 독립 reviewer 방식으로 실행한다.
- R4 독립 계획 재평가: **100/100**, blocker0/important0/minor0 (2026-10-04, /root/w04_plan_review). 계획 게이트와 별도로 Task1 수정 코드95점·미해결 blocker/important0 확인 전 다음 구현 단위를 시작하지 않는다.
- 설계 단계 목표 `설계완료까지 계속해서 진행`은 완료했다. 현재 W04 제품 구현을 실행하며 단위별 검증·독립 코드 리뷰 점수는 각각 기록한다.

## Global Constraints

- backend `>=3.13,<3.14`, isolated worker `>=3.12,<3.13`; worker package `0.1.0`, Basic Pitch `0.4.0`, source `049dc8a01a170c2370d7b246ec1c2067e060c3bf`, `nmp.onnx`, ONNX CPU, schema integer `1`.
- `supports_pedal=false`, `pedal_events=[]`, confidence semantics `uncalibrated_note_activation_mean`. 모델 activation을 보정된 확률 또는 정확도로 부르지 않는다.
- `TRANSCRIPTION_PROVIDER` unset/empty는 비활성, 정확한 `basic-pitch`만 활성. 절대 경로 `BASIC_PITCH_PYTHON`, `FFMPEG_EXECUTABLE` 필요. 기존 5필드 PipelineSettings 호출 호환성 유지.
- 입력은 정확히 하나의 `SEPARATED_AUDIO` WAV; 22,050 Hz mono PCM이 아니면 FFmpeg 변환. 직전 SEPARATE 완료 attempt의 DB 입력만 소비한다. MODEL_INPUT은 임시 파일이며 저장하지 않는다.
- 출력은 정확히 RAW_TRANSCRIPTION·MIDI 두 개; `attempt_{attempt_id}_raw_transcription.json`, `attempt_{attempt_id}_transcription.mid`; identity producer/version 일치. JSON 최대 `8*1024*1024`, MIDI 최대 `16*1024*1024` bytes, 둘 다 일반 파일이며 symlink 거부.
- provider timeout `1800`초, 구성 probe 각각 `5`초, 종료 유예 `5`초. 취소 정리를 위해 I/O thread drain을 기다리는 시간은 실행 timeout의 hard wall-clock 보장이 아니다. 기존 동기 storage 호출이 멈추면 해당 OS I/O가 돌아온 후 정리한다.
- root/API에서 모델 패키지를 import/설치하지 않는다. 새 직접 의존성은 pipeline의 `mido==1.3.3`뿐. root/API lock은 resolver로 갱신하고 기존 Celery/Kombu/Redis 제약·worker lock은 변경하지 않는다.
- import는 프로세스·네트워크·저장 부작용 없음. argv 분리·shell 미사용. 원본 exception/child stdout·stderr/경로/환경 값은 공개 로그·DB error·API·SSE·Celery retry exception에 노출하지 않는다.
- 설정 오류·worker exit 2/3/4·저장 I/O는 영구 실패 `PROVIDER_FAILED`; 결과 내용/누락/크기/형식 오류는 `ARTIFACT_INVALID`; timeout은 기존 `PROVIDER_TIMEOUT`. 신규 retry 정책 없음.
- 다운로드·분리·렌더링 provider, API/DB migration, 기본 모델 선정, 정확도 benchmark, 전체 YouTube 실행, 상주 서버는 범위 밖. 강제 owner death의 전체 자원 회수·orphan GC는 W11 범위다.
- 계획과 각 구현 단위 독립 리뷰 각각 >=95/100, blocker0/important0 후 다음 단위. 관련 파일만 명시적 stage·보고서·Conventional Commit, push/PR/merge 없음.

## Review Focus

R4 Task1 보완: gate는 Python SIGTERM handler 설치 후 byte-level `READY\n`을 전송한다. parent는 READY를 확인하고 완료-frame reader를 생성한 뒤에만 R을 전송한다. release 전 취소는 actual tool이 없으므로 stdin EOF와 gate wait로 회수한다. release 후 Linux SIGTERM 정리에서는 **descendant0 AND direct-tool completion reader.done()**가 모두 확인될 때만 EOF로 gate를 종료한다. Popen 직전 scheduling 지연에도 늦게 생성된 tool은 유예5초와 마지막 SIGKILL의 소유권에 포함된다. cleanup의 내부 timeout은 고정 PermanentProviderError이며 실행 deadline만 TimeoutError다. 실패 테스트의 identity monkeypatch는 context로 항상 복원한다.

추가 필수 검증 `test_cancel_after_release_before_tool_spawn_reaps_late_tool`: 실제 gate를 복제한 test-only 파일에서 R 수신 직후/Popen 직전 .5초 지연과 marker만 삽입한다. marker 이후 cancellation을 전달해 CancelledError·gate wait 완료·actual parent/child alive0을 확인하고 finally에서 test가 소유한 PID를 회수한다. Linux 실제 RED는1 failed/5.32s(cleanup TimeoutError), 수정 후 선택/root 회귀를 다시 확인한다. READY는 Windows text newline 변환을 피하도록 bytes로 보낸다. 별도 `test_cleanup_timeout_is_permanent`에서 원시 sentinel 없이 내부 cleanup deadline을 고정 오류로 정규화하는 것도 확인한다.

1. 프로세스 생성 await 중 취소 또는 Windows job 연결 실패: 실제 tool 실행 전에 소유권 확보, 생성 완료를 회수하고 owned tree 종료 (Task1).
2. 설정 probe 실패가 runtime 예외로 빠져 Celery 무한 retry: 실패 provider를 TRANSCRIBE에만 반환해 runner가 영구 실패를 기록하고 다른 stage 동작 유지 (Task3).
3. 취소 중 storage.put가 반환한 Ref를 잃는 경쟁: thread가 기록한 성공 Ref를 drain 후 정리하고 저장2를 시작하지 않음 (Task2/3).
4. JSON 숫자 문자열/bool·중복 key·provenance 위조 또는 MIDI header만 정상: 공용 schema 전 wire 검사·전체 MIDI 읽기·track 종료 검사 (Task2).
5. 모델 성공 직후 DB ownership 상실 또는 재실행: 늦은 metadata 등록0, 같은 fingerprint 캐시에서 모델 재호출0, 다른 구성은 INPUT_CHANGED (Task3/4).

## 파일 경계와 인터페이스

새 제품 모듈은 `packages/pipeline/musicsheet_pipeline/basic_pitch/`에 모은다. `__init__.py`는 공개 연결부 symbol만 노출하고 외부 작업을 하지 않는다.

- `process.py`: `ProcessResult(returncode:int, stdout:bytes)`; `async run_owned_process(argv:Sequence[str], *, cwd:Path, cancellation:asyncio.Event, timeout:float|None=None, capture_stdout:bool=False) -> ProcessResult`. 실제 tool stdout capture는 최대4096 bytes, control frame 최대8192 bytes. 과대 출력·잘못된 frame·시작 실패는 고정 `PermanentProviderError`; cancellation은 CancelledError; deadline은 TimeoutError.
- `_process_gate.py`: stdlib만 사용하는 고정 로컬 launcher. parent의 시작 byte를 받기 전 actual argv를 실행하지 않는다. **직접 tool의 poll()/wait 완료**를 frame 생성 조건으로 사용하며 inherited stdout EOF를 기다리지 않는다. capture할 때 POSIX nonblocking/select와 Windows PeekNamedPipe로 ready bytes만 읽고 최대4096 bytes를 유지하며 그 이후는 버린다. tool 종료 시 현재 읽을 수 있는 bytes를 수집하고 reader pipe를 닫아 returncode·bounded stdout·overflow의 version1 JSON frame을 전달한다. stdout/stderr/stdio는 명시 전달하여 tool이 gate의 control stdout을 상속하지 않게 한다. frame 이후 parent 종료 지시/EOF까지 gate는 살아 있다. argv payload를 shell/eval로 실행하지 않는다.
- `windows_job.py`: 내부 `WindowsJob`가 ctypes Win32 handle을 소유하고 assign/terminate/active-process-count/close를 제공한다. Windows에서만 Win32 API를 로드한다. breakaway 금지, kill-on-close, 비상속 handle, ctypes argtypes/restype를 명시한다.
- `audio.py`: `async prepare_input(context:StageContext, temp_root:Path, settings:BasicPitchSettings) -> Path`. role/count 검사, materialize, PCM WAV 검사 또는 변환, 변환 후 검사를 담당한다.
- `result.py`: `validate_result_files(output_dir:Path, *, stop:threading.Event) -> tuple[Path,Path]`. 크기 제한·strict JSON·공용 TranscriptionResult·MIDI 검사, 모든 내용 오류는 InvalidArtifact.
- `io.py`: `async run_owned_io(operation:Callable[[threading.Event],T], *, cancellation:asyncio.Event) -> T`; `async store_outputs(context:StageContext, files:tuple[Path,Path], *, identity:ProviderIdentity) -> tuple[ArtifactRef,...]`. 소유한 thread drain과 부분 성공 Ref 정리를 담당한다.
- `provider.py`: `BasicPitchProvider(settings:BasicPitchSettings, *, ffmpeg_version:str, setup_ok:bool=True)` implements StageProvider. `identity` 이름 `spotify-basic-pitch`, 연결부 version `0.1.0`; `async run(context:StageContext)->tuple[ArtifactRef,...]`.
- `config.py`에 frozen `BasicPitchSettings(python:Path, ffmpeg:Path)` 및 PipelineSettings 마지막 optional field `basic_pitch:BasicPitchSettings|None=None` 추가. 기존 positional 인자5개 유지.
- 기존 `providers.py`: `async build_providers(settings:PipelineSettings) -> Mapping[PipelineStage,StageProvider]`. 비활성은 기존 PROVIDERS empty 상수 반환; 활성은 bounded probe 후 TRANSCRIBE만 mappingproxy에 등록. 예상된 probe 실패는 `setup_ok=False`, `ffmpeg_version='unavailable'`의 안전한 실패 provider로 반환한다. raw exception을 보관하지 않는다.

### Task 1: 소유한 subprocess 실행·취소와 모델 설정 계약

**Files:** Create `basic_pitch/{__init__,process,_process_gate,windows_job}.py`, `tests/pipeline/test_basic_pitch_process.py`, `tests/pipeline/process_fixture.py`; Modify `config.py`, `tests/pipeline/test_contracts.py`. 보고서 `docs/reports/basic-pitch-process-report.md`와 main_spec 색인.

**Interfaces:** 위 ProcessResult/run_owned_process/WindowsJob/BasicPitchSettings. 이후 모든 모델·FFmpeg/probe 호출은 이 실행기로 통일한다.

- [x] **Step1 — RED 테스트:** `test_provider_config_is_opt_in_and_preserves_five_argument_constructor`에서 미설정 basic_pitch=None, 활성 경로 절대값, unknown/provider·상대 path·누락 path 고정 ValueError. `test_process_argv_is_literal`은 공백/한글/특수문자 인자가 그대로 전달되고 별도 명령이 실행되지 않음을 assert. `test_cancel_before_gate_release_never_launches_tool`은 시작 gate가 닫힌 상태의 tool marker0을 assert.
- [x] **Step2 — RED 실행:** `uv run --project . pytest tests/pipeline/test_basic_pitch_process.py tests/pipeline/test_contracts.py -q`; 새 interface 부재/실제 동작 assertion 실패를 기록한다. import 실패만 있다면 interface scaffold 이후 행동 assertion RED도 확인한다.
- [x] **Step3 — 소유권 구현:** create_subprocess_exec 자체를 task로 소유·shield하고 반복 취소에도 생성 완료를 drain한다. POSIX는 별도 session/process group; Windows는 gate PID를 소유한 Job Object에 assign한 후에만 시작 byte를 보낸다. assign 실패는 gate를 종료·wait한 뒤 실패한다. stdlib gate는 worker/model bootstrap과 FFmpeg를 똑같이 감싼다. stderr는 DEVNULL, stdout은 제한 control frame으로 수집하며 자식의 무한 출력은 제한된 메모리로 drain한다.
- [x] **Step4 — 종료 구현:** 정상/실패/취소/timeout 모두 tree를 정리한다. Linux gate는 tool spawn 전 SIGTERM **무시 disposition이 아닌 Python no-op handler**를 설치하여 자신은 살아 있고 exec된 tool은 정상 signal disposition을 사용하게 한다. parent는 gate PID의 `/proc` start-time/session/group identity를 시작 전에 기록한다. 종료 시 gate가 살아 있음을 확인하고 group SIGTERM을 한 번 보낸 뒤, gate를 제외한 active descendant가0이 될 때까지 최대5초 기다린다. direct-tool completion frame과 모든 descendant 종료가 함께 확인되면 stdin EOF로 gate를 종료·wait한다. frame이 아직 없으면 Popen 전이라도 유예 종료까지 소유권을 유지한다. descendant가 남으면 identity를 다시 확인해 group SIGKILL을 **마지막 group 신호로 한 번만** 보내고, 이후 재신호 없이 reap·종료 확인한다. 종료 중 gate가 예기치 않게 먼저 죽거나 identity가 바뀌면 숫자 PGID에 추가 신호를 보내지 않고 고정 cleanup 오류를 보고한다. 정상 정리 성공으로 기록하지 않는다. Linux 검증은 `/proc`를 사용하며 다른 POSIX OS는 W04 지원으로 주장하지 않는다. 자발적으로 setsid/setpgid한 descendant의 회수는 보장하지 않는다. Windows는 TerminateJobObject→최대5초 active-process-count0 확인→gate wait→handle close다. 다른 PID/group 또는 process 이름 전체를 대상으로 종료하지 않는다.
- [x] **Step5 — GREEN 경계 검증:** `test_cancel_during_spawn_drains_created_process`, `test_repeated_cancel_reaps_parent_and_grandchild`, `test_timeout_kills_uncooperative_descendant`, `test_normal_exit_with_grandchild_inheriting_stdout_completes_without_provider_timeout`, `test_gate_remains_alive_during_sigterm_grace_period`, `test_unexpected_gate_exit_never_signals_reused_group`, `test_job_assignment_failure_is_closed`, `test_probe_overflow_is_bounded`, `test_child_environment_excludes_database_secret`. normal-exit stdout fixture는 capture_stdout=True이고 종료5초 grace를 포함해10초 이내 완료하며 child/descendant alive0을 assert한다. unexpected-gate fixture의 탈출 child는 test가 별도로 기록한 소유권으로 finally 회수한다. child 환경은 PATH/SystemRoot/WINDIR/COMSPEC/TEMP/TMP/HOME/USERPROFILE/APPDATA/LOCALAPPDATA/LANG/LC_ALL만 상속하고 그 외는 전달하지 않는다. test fixture는 PID·ready marker와 제한 deadline을 사용하며 finally에서 생성한 자원을 회수한다.
- [x] **Step6 — 리뷰·commit:** Task1 선택 테스트 + root 회귀, Windows 실제 descendant 검사 및 Linux 별도 Python3.13 container에서 같은 선택 테스트를 실행한다. 해당 플랫폼을 실행하지 못하면 Task1 플랫폼 게이트를 통과 처리하지 않는다. 독립 reviewer >=95/blocker0/important0, 보고서·색인, `feat(pipeline): own transcription process lifecycles`.

### Task 2: WAV 준비·JSON/MIDI 검증과 취소 가능한 저장

**Files:** Create `basic_pitch/{audio,result,io}.py`, `tests/pipeline/{test_basic_pitch_audio,test_basic_pitch_result,test_basic_pitch_io}.py`; Modify `packages/pipeline/pyproject.toml`, root `uv.lock`, `services/api/uv.lock`. 보고서 `docs/reports/basic-pitch-result-storage-report.md`와 main_spec 색인.

**Interfaces:** 위 prepare_input/validate_result_files/run_owned_io/store_outputs. Task1의 run_owned_process·BasicPitchSettings와 기존 ArtifactStorage·TranscriptionResult·InvalidArtifact를 사용한다.

- [x] **Step1 — RED 테스트:** 잘린/빈 WAV·틀린 role/count는 모델 실행 전에 실패. `test_22050_mono_pcm_skips_conversion`과 `test_stereo_44100_is_converted_to_22050_mono`에서 실제 frame/sample rate/channel을 assert. `test_ieee_float_wav_uses_ffmpeg_instead_of_rejecting_wave_error`는 작은44.1kHz stereo IEEE float32 RIFF fixture를 stdlib struct로 생성하고 변환 후22,050Hz/mono/PCM16/비어 있지 않은 frames를 assert한다. `test_truncated_float_wav_fails_before_model`은 data chunk 크기보다 짧은 payload에서 모델 호출0을 assert한다. 결과 테스트는 pinned provenance의 정상/빈 notes 성공과 문자열 숫자·bool pitch·중복 note_id/key·NaN·Infinity·비어 있지 않은 pedal·잘못된 provenance·누락 MIDI·과대 파일·symlink 실패를 고정한다. MIDI는 header만 정상/잘린 track/종료 없는 track/후행 bytes와 정상 빈 notes 파일을 구분한다.
- [x] **Step2 — RED 실행:** `uv run --project . pytest tests/pipeline/test_basic_pitch_audio.py tests/pipeline/test_basic_pitch_result.py tests/pipeline/test_basic_pitch_io.py -q`.
- [x] **Step3 — dependency/input 구현:** pipeline mido==1.3.3을 resolver로 root/API lock에 반영하고 locked sync한다. prepare_input은 materialize를 owned thread에서 수행한다. RIFF/RIFX 입력은 chunk header/payload/padding과 선언한 container/data 범위가 실제 파일 안에 있는지 먼저 검사하여 잘린 float WAV도 변환으로 감추지 않는다. `wave`의 PCM 검사는 block 단위 읽기로 header frame 수와 실제 읽힌 수를 비교한다. 읽을 수 있는 PCM이22,050Hz mono이면 재사용한다. `wave.Error`만으로 손상이라고 판단하지 않으며 유효한 IEEE float 등 비PCM WAV는 FFmpeg로 디코드한다. FFmpeg argv는 `-nostdin -hide_banner -loglevel error -protocol_whitelist file,pipe -f wav -i <materialized> -vn -ac 1 -ar 22050 -c:a pcm_s16le <new-temp-wav>`; 기존 파일 overwrite·임의 URL·decoder 자동 선택을 하지 않는다. 변환 후 PCM WAV는 같은 frame 검사를 통과해야 하며 decoder 실패/빈 출력은 모델 전에 영구 실패다. input의 선언 MIME만으로 WAV라고 판단하지 않는다.
- [x] **Step4 — result 구현:** output_dir와 두 filename lstat·resolve 검사 후 크기+1까지 bounded read, UTF-8/duplicate key/parse_constant 거부, schema 1 및 provider/notes의 wire 타입 검사, 공용 model 검증. 선택적 nullable activation/velocity/source_chunk 허용, source_chunk는 null 또는 정확한 int. unknown JSON field는 기존 version1 공용 schema와 같이 허용하지만 알려진 field 검사를 회피하지 못한다. `mido.MidiFile(file=BytesIO(data), clip=False)`로 전체 파일을 읽고 stream 끝/유효 format·track 수/각 track 마지막의 end_of_track 한 개를 확인한다. MIDI/JSON의 note 개수 일치는 요구하지 않는다.
- [x] **Step5 — I/O 구현 및 GREEN:** run_owned_io는 thread stop event와 asyncio cancellation event를 연결하고 shield+drain한다. 현재 materialize 호출은 자체 stop 인자가 없으므로 호출 완료까지 기다린다. put은 stop을 확인하는 bounded binary reader로 파일을 전달한다. thread 내부에서 성공 Ref를 즉시 기록하고 exception/cancel 시 drain 후 기록된 Ref를 storage.delete한다. 저장2 전에 stop 재확인. 성공 전 두 결과 검사, 취소 후 반환 없음. `test_cancel_during_put_keeps_returned_ref_for_rollback`, `test_second_put_failure_deletes_first`, `test_blocked_materialize_drains_before_temp_cleanup`, `test_cleanup_failure_is_sanitized`를 threading.Event로 결정적으로 검증한다. delete 실패는 고정 오류/로그로 표시하며 부분 Ref를 성공으로 반환하지 않는다; 확인되지 않은 put/프로세스 강제 종료 orphan 파일은 W11 제한으로 기록한다.
- [x] **Step6 — 리뷰·commit:** Task2 선택 tests·root/API 회귀·root/API `uv lock --check`·worker lock 불변 확인, 실제 FFmpeg 변환 실행, 모델 dependency 경계 검사. >=95 독립 리뷰, 보고서/색인, `feat(pipeline): validate and store isolated transcription outputs`.

### Task 3: 제품 provider·factory·Celery runtime 연결

**Files:** Create `basic_pitch/provider.py`, `tests/pipeline/{test_basic_pitch_provider,test_basic_pitch_registry}.py`; Modify `providers.py`, `tasks.py`, `tests/pipeline/test_celery_tasks.py`, `.env.example`, README. 보고서 `docs/reports/basic-pitch-provider-report.md`와 main_spec 색인. runner/repository 공용 계약은 변경하지 않는다.

**Interfaces:** BasicPitchProvider와 build_providers. runtime(settings)의 기존 resources.providers에 factory 결과를 넣고 resource 생성/close loop 소유권을 유지한다.

- [ ] **Step1 — RED:** `test_only_transcribe_is_enabled`, `test_disabled_provider_performs_no_probe`, `test_runtime_probe_failure_fails_transcribe_without_celery_retry`, `test_provider_preserves_exact_output_roles_and_attempt_names`, `test_failed_validation_stores_nothing`, `test_exit_2_3_4_are_permanent`, `test_cancel_cleans_workspace_after_children_and_io`, `test_import_does_not_spawn_or_import_model`. 고정 secret sentinel이 formatted traceback/로그/DB detail에 없음을 assert한다.
- [ ] **Step2 — RED 실행:** `uv run --project . pytest tests/pipeline/test_basic_pitch_provider.py tests/pipeline/test_basic_pitch_registry.py tests/pipeline/test_celery_tasks.py -q`.
- [ ] **Step3 — factory 구현:** Python probe는 configured interpreter의 `-I -c <fixed-code>`로 sys.version_info[:2], importlib.metadata의 worker0.1.0/basic-pitch0.4.0, ONNXRuntime 존재를 확인한다. 실제 model import는 probe에서 하지 않는다. FFmpeg `-version` 첫 줄을 bounded capture로 확인한다. 각각5초, 예상 오류는 setup_ok=False의 identity 있는 provider로 반환해 TRANSCRIBE attempt가 영구 실패한다. cancellation은 실패 provider로 바꾸지 않고 전파한다. unknown selector/상대 path 같은 정적 설정 오류는 from_env에서 고정 ValueError로 거부한다.
- [ ] **Step4 — provider 구현:** identity configuration에 pinned 모델/JSON/변환 규격·경로·확인 FFmpeg version·크기 제한·adapter version을 넣는다. 작업 전용 TemporaryDirectory의 root 아래 prepare_input→기존 CLI→validate_result_files→store_outputs 순서. 모델 argv는 configured Python `-I -c <fixed bootstrap> --input-audio <path> --output-dir <absent-path>`; bootstrap은 Python3.12/worker version 재확인 후 `from musicsheet_basic_pitch_worker.cli import main; raise SystemExit(main())`. uv/download 호출 없음. child code0만 결과검사 진입, code2/3/4와 기타 nonzero는 PermanentProviderError. store_outputs가 반환한 Ref는 provider가 보유하고 cancellation 재확인 및 temp root cleanup을 성공한 후에만 runner로 반환한다. 그 전 exception/cancel/cleanup 실패는 두 Ref도 rollback한다. cleanup 실패의 원시 경로/exception은 고정 PermanentProviderError로 바꾼다. runner에 반환한 뒤 DB fence에서 거부된 파일의 GC는 W11 제한으로 구분한다.
- [ ] **Step5 — runner GREEN:** 기존 DB double에서 테스트용 선행 provider로 DOWNLOAD/PREPROCESS/SEPARATE를 완료하고 실제 provider 연결부에는 제어용 worker 결과를 사용한다. `test_duplicate_fingerprint_does_not_invoke_worker_twice`, `test_changed_configuration_fails_input_changed`, `test_cancel_or_lost_ownership_never_commits_outputs`, `test_runtime_bad_model_does_not_block_other_stage_provider_lookup`, `test_cancel_after_both_puts_before_return_rolls_back_both`, `test_temp_cleanup_failure_before_return_rolls_back_both`; metadata2·POSTPROCESS outbox1·전체 job RUNNING을 assert한다. template provider를 제품 registry에 넣지 않는다. 제품 등록이 끝나도 전체 pipeline이나 default model이 구현됐다고 표시하지 않는다.
- [ ] **Step6 — 리뷰·commit:** 선택 tests·root/API 회귀·config/lock 경계, 실제 환경 probe, 독립 >=95 리뷰·보고서·색인. `.env.example` 비활성 default와 절대 경로 예시, worker preinstall 절차/현재 platform 범위/미구성 stage를 README에 기록. `feat(pipeline): connect Basic Pitch to transcription stages`.

### Task 4: 실제 모델·DB 등록 검증과 최종 정합성

**Files:** Create `tests/integration/test_basic_pitch_provider.py`, `tests/pipeline/integration/basic_pitch_support.py`, `tests/pipeline/integration/test_basic_pitch_stage.py`; Modify root pyproject pytest marker, `tests/test_project_baseline.py` 필요 시 marker 기대값, README·worker README, canonical 문서 상태, roadmap/completed-work/main_spec. 보고서 `docs/reports/basic-pitch-pipeline-implementation-report.md`.

**Interfaces:** 제품 build_providers/BasicPitchProvider/run_stage 그대로 사용. marker `ml_integration`, DB 검증은 새 `pipeline_db_integration`; default addopts에서 후자도 제외. `MUSICSHEET_TEST_DATABASE_URL` 명시 환경과 DB marker guard를 공통 test helper에서 사용하며 api import를 root 제품에 추가하지 않는다.

- [ ] **Step1 — 실제-model RED:** CC0 fixture SHA256 `2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a`를 확인하고, 실제 product factory→provider→LocalStorage를 통해 JSON/MIDI 두 Ref·nonempty notes·pinned provider·빈 pedal·SHA/size/attempt filename을 검사한다. 테스트 선언 후 실제 실행해 행동 RED를 확인하며 기존 unit implementation에서 이미 GREEN이면 RED를 꾸며 기록하지 않는다.
- [ ] **Step2 — DB fixture:** 별도 postgres16 container, loopback의 임의 port, DB `musicsheet_test`, `current_database()`와 `shobj_description` marker `MUSICSHEET_DISPOSABLE_TEST_DB_V1`를 확인한다. API migration v1/v2를 명시 실행한 뒤 root tests는 asyncpg 연결만 사용한다. 테스트마다 UUID job/source/stem과 선행 stage 완료를 테스트 helper로 준비한다. 직접 fake completed row만 넣어 fingerprint를 우회하지 않고 기존 runner로 선행 test providers를 완료한다. enqueue된 POSTPROCESS는 소비하지 않는다.
- [ ] **Step3 — live DB GREEN:** `test_real_model_transcribe_commits_two_artifacts`에 ml_integration+pipeline_db_integration 두 marker, `test_cancel_during_transcribe_has_no_registered_outputs`와 `test_transcribe_db_ownership_loss_fences_completion`은 후자 marker와 제어용 blocking child 사용. 성공 시 attempt COMPLETED+output IDs2+metadata2+POSTPROCESS outbox1+job RUNNING/TRANSCRIBE, 중복 재전달 worker call1. 실패/취소/connection loss 시 신규 metadata0·후속 outbox0. thread/process marker로 상태를 기다리고 각 wait<=30초, finally에서 owned process·connection·job rows·temp files를 정리한다.
- [ ] **Step4 — 플랫폼·회귀:** 아래 명령 표 모두 실행해 실제 결과를 기록한다. Windows 실제 ONNX CPU 모델/provider와 실DB를 필수 실행한다. Linux에서는 Task1 process 선택 tests 및 root 회귀를 필수 실행한다. Linux의 실제 Basic Pitch/Celery 검증은 Python3.12 모델 환경을 먼저 설치·검증한 경우에만 별도 실행하고 결과를 구분한다; 미실행이면 Linux 실제 모델 미검증이라고 명시한다. Windows 테스트를 Linux Celery 지원 근거로 쓰지 않는다.
- [ ] **Step5 — 리뷰·완료 commit:** 단위 Task4 >=95 리뷰 후 전체 변경 독립 리뷰 >=95/blocker0/important0. root/API/worker lock 검사, docs 상태와 실행 증거 일치, report/index, roadmap에서 W04 제거·completed-work에 점수/일자/commit 추가. `test(pipeline): verify Basic Pitch stage integration`. 최종 report는 모델 통합·DB·Celery·OS별 증거 및 강제 owner death/orphan 한계를 별도로 기록한다.

## 실행 명령과 재현 조건

모든 명령은 repo root에서 실행한다. cache 또는 권한 문제 때만 이전 작업과 같이 `uv --cache-dir outputs/.uv-cache run --offline --no-sync ...`를 사용하고 정확한 실행 형태를 보고한다. basetemp 상위 폴더는 먼저 만들고 기존 경로를 재사용해 다른 산출물을 삭제하지 않는다.

| 목적 | 명령 | 합격 기준 |
| :--- | :--- | :--- |
| root 환경 | `uv sync --locked --project . --python 3.13` | mido1.3.3 설치, 모델 package 없음 |
| API 환경 | `uv sync --locked --project services/api --python 3.13` | 동일 pipeline lock 해석 성공 |
| worker preinstall | `uv sync --locked --project services/ml/basic-pitch-worker --python 3.12` | 기존 lock 불변, 실행 가능; request runtime에서 호출 금지 |
| root 회귀 | `uv run --project . pytest -q` | FAIL0; 선택적 integration 제외/skip 사유 기록 |
| API 회귀 | `uv run --project services/api pytest services/api/tests -q` | FAIL0; 실DB 증거 별도 기록 |
| worker 회귀 | `uv run --project services/ml/basic-pitch-worker pytest services/ml/basic-pitch-worker/tests -q` | FAIL0 |
| 실제 모델/provider | `uv run --project . pytest -m ml_integration tests/integration -q` | 기존4+새 실제 provider 모두 PASS, skip을 실제 검증으로 계산하지 않음 |
| 실제 모델+DB | `uv run --project . pytest -m 'ml_integration or pipeline_db_integration' tests/pipeline/integration/test_basic_pitch_stage.py -q` | Windows 실모델1·취소·소유권 loss 모두 PASS |
| Linux subprocess/회귀 | 아래 격리 container 절차의 `uv run --locked --project . pytest tests/pipeline/test_basic_pitch_process.py -q` 및 `uv run --locked --project . pytest -q` | 실제 Linux 선택 tests/회귀 PASS, ML 환경 없음 |
| 각 lock | `uv lock --check --project .`, `uv lock --check --project services/api`, `uv lock --check --project services/ml/basic-pitch-worker` | 변경 필요 없음, worker lock hash 기존과 동일 |
| 문서·commit | `git diff --check` 및 명시 파일 staging 후 `git diff --cached --check` | 오류0·허용 scope 파일만 포함 |

실제-model 명령에는 활성 selector와 설치된 Python3.12·FFmpeg 절대 경로를 지정한다. CI 기본 unit 경로는 테스트 중 설치나 다운로드를 하지 않는다. 필수 통합 검증은 필요한 도구가 없으면 명시 FAIL/미완료로 취급하고 default suite의 opt-in skip과 구분한다.

전용 container/네트워크/파일 이름은 `musicsheet-w04-<random>` 또는 `tmp/w04-<date>-<random>/`로 제한하고 생성 결과 ID를 기록한다. DB credentials는 ignored 임시 env file로 전달하고 출력/문서에 남기지 않는다. API migration 예: `uv run --project services/api musicsheet-migrate` (해당 전용 DATABASE_URL을 환경으로 주입). finally에서 자신이 생성한 container만 제거하고 secret file 삭제를 확인한다. 공유 `study_postgres`와 기존 DB·volume는 사용/변경하지 않는다. 기존 W03 harness의 Linux 전용 process 코드를 Windows DB fixture에서 그대로 사용하지 않는다.

운영 Linux Celery 모델 환경·실제 YouTube 전체 변환·정확도 benchmark는 이번 필수 명령 표에 포함하지 않는다. 해당 미검증 항목이 있더라도 Windows 실제 모델/DB 등록과 Linux process 검증이라는 W04의 완료 범위를 명확히 유지한다.

Linux 재현은 Docker `python:3.13-slim`에 잠긴 root 소스와 변경 테스트만 전달한다. repo를 Windows .venv와 함께 bind mount하지 않는다. 소스는 `git archive HEAD`에 해당 Task의 명시적 staged tracked 파일을 덮어쓴 snapshot으로 만들고 `.git/.venv/outputs/tmp`를 제외한다. Windows에서 `docker create --name musicsheet-w04-<random> --workdir /work --entrypoint sleep python:3.13-slim infinity`로 소유한 ID를 기록하고, `docker start <owned-id>`, `docker cp <snapshot>/. <owned-id>:/work` 후 실행한다. container 안에서는 `python -m pip install uv==0.10.11`, `uv sync --locked --project . --python /usr/local/bin/python`, 위 선택 명령과 root 회귀 명령을 순서대로 실행한다. 각 `docker exec`의 exit code와 image ID·Python/uv 버전을 기록한다. network 설치가 불가하면 필수 Linux 검증 미완료로 남긴다. 모델 프로젝트와 API를 설치하지 않으며 shared 서비스에 연결하지 않는다. finally에서 해당 ID에만 `docker rm -f <owned-id>`를 적용하고 container가 사라졌는지 확인한다. 임시 snapshot과 로그는 ignored 작업 폴더에 보관하고 비밀은 전달하지 않는다.

## 리뷰 기록

| 날짜 | 종류 | 버전/범위 | Reviewer | 항목별 점수 | 합계 | 지적·처리 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-10-04 | 계획 | R1 전체 | /root/w04_plan_review | 24/25 · 18/20 · 20/20 · 23/25 · 9/10 | 94/100 | important2: stdout EOF 교착·SIGTERM leader 보존. minor2: 반환 직전 rollback·Linux 재현/설계 상태. R2 보완 후 재평가 |
| 2026-10-04 | 계획 | R2 전체 | /root/w04_plan_review | 25/25 · 20/20 · 20/20 · 24/25 · 10/10 | 99/100 | blocker0/important0/minor1. R1 지적 모두 해결. 비PCM WAV→FFmpeg 경로의 IEEE float 변환 test 보강 권고는 Task2 구현 리뷰에서 확인 |
| 2026-10-04 | 계획 | R3 전체 | /root/w04_plan_review | 25/25 · 20/20 · 20/20 · 25/25 · 10/10 | 100/100 | blocker0/important0/minor0. R2 WAV 경계 지적 해결, 승인 설계 범위 준수·설계 산출물 완결성 확인 |
| 2026-10-04 | 계획 | R4 전체 | /root/w04_plan_review | 25/25 · 20/20 · 20/20 · 25/25 · 10/10 | 100/100 | blocker0/important0/minor0. private READY·완료-frame handshake·cleanup timeout 분류·Linux scheduling race 검사 보완. 공개 provider/Task2~4 범위 유지 |
| 2026-10-04 | 구현 | Task1 수정 전, a1fd862 대비 미커밋 실행기/설정/테스트/보고서/색인 | /root/w04_process_review | 23/25 · 21/25 · 22/25 · 14/15 · 10/10 | 90/100 | blocker0/important2/minor1. Linux 늦은 생성 누수·cleanup timeout 오분류, test identity 복원. R4 계획100점 후 수정 코드 검증·재리뷰 중 |
| 2026-10-04 | 구현 | Task1 R4 첫 수정, 동일 a1fd862 대비 전체 | /root/w04_process_review | 23/25 · 23/25 · 24/25 · 14/15 · 10/10 | 94/100 | blocker0/important1/minor0. 이전 지적 해결; EOF 직전 leader 재확인·예상 gate exit 검사가 누락. Linux RED1failed/.34s 후 기존 fail-closed 계약 구현 보완·재리뷰 |
| 2026-10-04 | 구현 | Task1 최종, a1fd862 대비 실행기/설정/테스트/보고서/색인 전체 | /root/w04_process_review | 25/25 · 25/25 · 25/25 · 15/15 · 10/10 | 100/100 | blocker0/important0/minor0. 90/94점 지적과 Windows timeout fixture 부하 민감성 모두 해결. Windows root236/16skip/4deselect·Linux root242/10skip/4deselect, 선택28/4skip·13/1skip |
| 2026-10-04 | 구현 | Task2 첫 구현, 0381b6f 대비 제품3/test4/dependency/lock/report/index | /root/w04_result_storage_review | 24/25 · 22/25 · 23/25 · 15/15 · 10/10 | 94/100 | blocker0/important1/minor0. event/task 취소 전달이 loop 지연 때 저장2를 막지 못함. 실제 두 방식 RED2failed/.60s 후 put 시작 허가를 loop의 취소 fence로 보완·재리뷰 |
| 2026-10-04 | 구현 | Task2 최종, 동일0381b6f 대비 전체 | /root/w04_result_storage_review | 25/25 · 25/25 · 25/25 · 15/15 · 10/10 | 100/100 | blocker0/important0/minor0. put 허가 fence·두 취소 경쟁 해결, reviewer 선택53/1skip·root289/17skip/4deselect·API232/25skip/1warning, locks 통과 |

구현 기록은 단위 완료 때 이 표에 별도로 추가한다. 계획 점수를 코드 점수로 사용하지 않는다. 계획의 실질 변경은 revision 증가와 재리뷰 후 진행한다.

## 참고한 1차 문서

- [Python3.13 asyncio subprocess](https://docs.python.org/3.13/library/asyncio-subprocess.html): Windows Proactor 사용 및 argv 분리 subprocess 경계.
- [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects): child job 상속·breakaway·kill-on-close·nested jobs·active process 회계. Job Object가 만료될 때만 signal되는 동작을 일반 종료 완료 신호로 오해하지 않는다.
- [Mido Standard MIDI Files](https://mido.readthedocs.io/en/stable/files/midi.html): 파일 전체 읽기와 track/event 표현. tolerant parsing에 의존하지 않고 설계상 종료 검사를 추가한다.
