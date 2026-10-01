# W04 Basic Pitch `TRANSCRIBE` 통합 설계

> **상태:** 설계 초안 — 대화에서 권장안을 승인받았으며, 이 문서의 사용자 검토 대기
> **작성일:** 2026-10-01 (Asia/Seoul)
> **기준 브랜치:** `codex/redis-streams-sse` (W02/W03 통합)
> **선행 설계:** [Basic Pitch 독립 worker 설계](2026-09-26-basic-pitch-worker-design.md)
> **관련 계획:** [Basic Pitch 독립 worker 구현 계획](../../plans/basic-pitch-isolated-worker-implementation-plan.md)
> **관련 명세:** [전사](../../ai/transcription.md), [모델 어댑터](../../ai/model-adapters.md), [작업 파이프라인](../../architecture/job-pipeline.md), [artifact](../../domain/artifacts.md)

## 1. 목표와 승인된 범위

W03가 제공하는 Celery stage-handler 경계를 사용해 이미 등록된 Basic Pitch 입력을 전사하고, 검증된 JSON 결과와 MIDI를 기존 artifact 저장소 및 PostgreSQL metadata에 등록한다. API와 Celery orchestration은 Python 3.13에 유지하고, 모델 추론은 기존 독립 Python 3.12 Basic Pitch worker 프로세스에서 실행한다.

범위는 `PipelineStage.TRANSCRIBE` 하나다. 입력은 `MODEL_INPUT` 역할의 `amt_22k_mono.wav`이며, 전처리·음원 다운로드·음원 분리·다른 모델 선택은 수행하지 않는다. 앞 단계 handler가 아직 설정되지 않은 상태이므로 이번 변경만으로 신규 작업이 `TRANSCRIBE`까지 진행한다고 가정하지 않는다. 테스트와 직접 호출 검증은 입력 artifact가 이미 등록된 상황을 재현한다.

성공 결과는 `RAW_TRANSCRIPTION` JSON과 `MIDI` 파일을 저장하고 metadata를 등록한 뒤 기존 W03 task lifecycle로 돌아가는 것이다. Basic Pitch를 기본 provider로 승격하거나 전사 정확도를 판정하지 않는다.

## 2. 접근 방식과 결정

### 권장: 단계별 격리 CLI 프로세스

Celery의 `TRANSCRIBE` handler가 Python 3.12의 설치된 `basic-pitch-worker` 실행 파일을 새 프로세스로 한 번 호출한다. 입력과 출력은 W04 attempt 전용 임시 디렉터리를 통하는 파일 계약으로 주고받는다. 호출은 argument 배열과 `shell=False`로 수행한다. 이는 이미 설치·추론이 검증된 worker와 JSON 계약을 재사용하고, Python 3.13 backend에 모델 의존성을 넣지 않는다.

### 검토했으나 선택하지 않은 방법

- **상시 worker daemon/RPC:** 호출별 시작 비용을 줄일 수 있으나 별도 서비스의 수명주기, IPC, 배포 및 장애 복구가 생긴다. 현재 PoC 처리 시간과 W04 단일 단계 범위에는 필요하지 않다.
- **Basic Pitch를 API 프로세스에 직접 import:** Python 3.12 worker와 Python 3.13 backend의 검증된 경계를 깨고 의존성 충돌을 재도입하므로 제외한다.

## 3. 구성 요소와 인터페이스

1. **`BasicPitchTranscriptionHandler`**는 `StageHandler.run(context, report_progress)`를 구현한다. stage가 `TRANSCRIBE`인지 검사하고, 입력 선택, worker 실행, 출력 검증 및 artifact 게시를 담당한다.
2. **`StageContext`의 artifact 게시 포트**는 handler가 동기 worker thread 안에서 사용할 수 있는 좁은 `publish(outputs)` 계약을 제공한다. handler는 asyncpg pool 또는 DB connection을 직접 다루지 않는다. W03 task가 실행 중인 event loop로 게시 요청을 전달하고, concrete publisher가 공용 `ArtifactStorage`와 `ArtifactRepository`를 사용한다.
3. **`WorkerRuntime` 조립부**는 설정의 local storage 경로로 `LocalStorage`를 만들고, 현재 Celery worker가 쓰는 `ArtifactRepository`에 연결한 publisher를 stage context에 주입한다. 저장 후 두 artifact metadata 행은 하나의 PostgreSQL transaction에서 등록한다. DB 스키마는 변경하지 않는다.
4. **worker 실행 설정**은 `BASIC_PITCH_WORKER_EXECUTABLE`로 Python 3.12 console executable 경로를 지정하고, `BASIC_PITCH_WORKER_TIMEOUT_SECONDS`로 양의 제한 시간을 설정한다. timeout 기본값은 300초다. 로컬 검증 기본 경로는 worker 전용 `.venv/Scripts/basic-pitch-worker.exe`이며, 실행 환경이 다르면 절대 경로를 명시한다. 기존 Basic Pitch PoC의 Windows 지원 범위를 넘어 Linux/macOS를 지원한다고 주장하지 않는다.

worker는 `--input-audio <path> --output-dir <새 경로>` 인자를 받는다. 프로세스 실행에 shell을 사용하지 않는다. stdout/stderr 원문은 API 응답, job 상태 또는 progress event에 노출하지 않는다. 임시 로그가 필요하면 attempt 디렉터리 안에만 두고 정리한다.

## 4. 입력, 출력 및 artifact 규칙

### 입력

- `context.artifacts`에서 role이 `MODEL_INPUT`이고 filename이 `amt_22k_mono.wav`인 artifact가 정확히 하나 있어야 한다. 누락, 중복, URI/metadata 불일치는 `BASIC_PITCH_INPUT_INVALID` 영구 오류로 처리한다.
- artifact를 storage adapter의 `materialize`로 attempt 전용 임시 디렉터리에 가져온다. worker는 WAV, mono, 22,050 Hz 입력을 검사하며 자동 리샘플링하지 않는다.
- 입력 artifact 또는 worker 출력 경로를 사용자가 전달한 경로로부터 만들지 않는다. 임시 경로와 고정된 output filename만 사용한다.

### 출력 검증

- `raw_transcription.json`은 공용 `TranscriptionResult.model_validate_json`으로 검증한다. `schema_version`은 1이고 provider ID는 `spotify-basic-pitch`여야 한다. `supports_pedal`은 false이며 `pedal_events`는 빈 배열이어야 한다.
- `transcription.mid`는 존재하고 비어 있지 않아야 하며 Standard MIDI header `MThd`를 가져야 한다. 둘 중 하나라도 없거나 유효하지 않으면 성공으로 취급하지 않는다.
- 성공 시 metadata는 고정 역할·이름 쌍 `RAW_TRANSCRIPTION/raw_transcription.json`, `MIDI/transcription.mid`로 등록한다. producer는 `spotify-basic-pitch`, producer version은 검증된 JSON의 `provider.package_version`을 사용한다. SHA-256, 크기, URI는 storage adapter가 계산한 값을 보존한다.
- JSON과 MIDI를 storage에 쓴 다음 두 metadata 행을 한 DB transaction으로 추가한다. transaction 실패 시 이번 실행에서 기록한 파일은 최선 노력으로 삭제하고, 재시도 가능한 storage 오류는 민감한 상세 없이 `RetryableStageError` 코드로 변환한다.

## 5. 재시도, 취소 및 오류 동작

W03 stage lock은 같은 job/stage 동시 전달을 직렬화한다. handler는 실행 전에 같은 Basic Pitch 출력 쌍이 이미 등록되어 있는지 확인한다. 기존 JSON/MIDI 모두 파일 존재, metadata SHA-256과 실제 내용 일치, 계약 검증, producer 및 이름 검증을 통과하면 worker를 재실행하지 않고 완료한다. metadata가 하나만 있거나 저장 파일이 손상/불일치하면 덮어쓰거나 임의로 복구하지 않고 `BASIC_PITCH_ARTIFACT_CONFLICT` 영구 오류로 실패한다. 출력 기록 직후 worker가 종료되기 전 프로세스가 죽어 DB metadata가 없다면 다음 실행은 동일한 고정 파일 이름에 안전하게 다시 게시할 수 있다.

프로세스는 `Popen`으로 감시한다. 1초 단위 poll에서 현재 stage progress를 갱신해 W03 progress callback이 취소 상태를 감지하도록 한다. handler가 `JobCancellationRequested`를 받으면 child를 terminate하고 짧은 제한 시간 후에도 종료되지 않으면 kill한 뒤 예외를 다시 전달한다. 모든 성공·실패·취소 경로에서 임시 파일과 프로세스를 정리한다. 시간 기반 progress는 실행 중 증가시키되 최대 90으로 제한하고, 검증 및 artifact 등록을 완료한 뒤 W03가 100을 기록하게 한다.

| 조건 | stage 오류 | 분류 |
|---|---|---|
| worker executable 미설정/실행 불가 | `BASIC_PITCH_WORKER_UNAVAILABLE` | 영구 |
| `MODEL_INPUT` 누락·중복·계약 위반, worker exit 2 | `BASIC_PITCH_INPUT_INVALID` | 영구 |
| worker timeout 또는 exit 3 | `BASIC_PITCH_INFERENCE_FAILED` | 재시도 가능 |
| exit 4, JSON/MIDI 누락·schema 위반, artifact 충돌 | `BASIC_PITCH_OUTPUT_INVALID` 또는 `BASIC_PITCH_ARTIFACT_CONFLICT` | 영구 |
| transient storage/DB 연결 장애 | `BASIC_PITCH_ARTIFACT_STORAGE_UNAVAILABLE` | 재시도 가능 |
| cancellation 감지 | W03 `JobCancellationRequested` 경로 | 취소 |

외부로 노출되는 오류는 위 안정 코드만 사용한다. stderr, 파일 절대 경로, 사용자 입력 및 내부 exception 문자열을 job error나 이벤트에 포함하지 않는다.

## 6. 검증 범위와 완료 기준

- **단위 테스트:** handler의 입력 artifact 선택, worker 인자 구성(`shell=False`), 정상 JSON/MIDI 검증, 잘못된 schema/provider 및 MIDI 거부, 각 exit code/timeout 분류, 진행 polling, 취소 시 child terminate/kill, 임시 경로 정리, artifact 게시 성공/실패, 기존 출력 재사용 및 conflict를 fake runner·임시 LocalStorage·fake/테스트 publisher로 확인한다.
- **API/DB 통합 테스트:** 환경이 허용되면 PostgreSQL에 두 metadata 행이 원자적으로 등록되고 transaction 실패 시 행이 남지 않는지 확인한다. 이 테스트는 기존 opt-in PostgreSQL URL로 실행한다. 새 migration은 추가하지 않는다.
- **opt-in 실제 worker 검증:** 기존 `ml_integration` fixture로 독립 Python 3.12 worker를 호출하고, 등록된 `MODEL_INPUT`에서 `RAW_TRANSCRIPTION`과 `MIDI` 출력이 생성·검증되는지 확인한다. API/Celery 전체 chain을 검증하는 테스트로 오인하지 않는다.
- 전체 검증 명령은 계획서에서 확정한다. 목표 집합은 API test suite, root suite, 별도 opt-in Basic Pitch worker test, 설정된 경우 PostgreSQL 통합 테스트다. 구현 단위별 독립 코드 리뷰는 저장소의 95점 gate를 따른다.

완료로 간주하려면 TRANSCRIBE handler가 W03 registry에 연결되고, 올바른 기존 입력에서 두 artifact를 저장하며, 잘못된 입력·worker 오류·timeout·취소를 안전하고 재현 가능하게 분류해야 한다. 재전달은 유효한 결과를 중복 생성하지 않아야 하며, 실패한 경우 성공 metadata나 부분 등록 행을 남겨서는 안 된다.

## 7. 제외 사항과 선행 gate

- DOWNLOAD, PREPROCESS, SEPARATE handler 및 신규 작업의 앞 단계 wiring
- Celery chain/queue/state/retry lifecycle 재설계, 공개 API 추가, DB schema migration
- Basic Pitch를 기본 provider로 선정, 정확도·다른 provider 비교, 페달 검출
- 상시 daemon/RPC, 컨테이너/배포 플랫폼, Linux/macOS 호환성 보증, GPU inference
- POSTPROCESS, RENDER 및 최종 MusicXML/PDF 생성

이 문서는 conversational design approval을 반영한 초안이다. **사용자가 이 문서 내용을 검토·승인하기 전에는 구현 계획이나 제품 코드를 작성하지 않는다.** 문서가 승인되면 `writing-plans` 절차로 `docs/plans/`에 실행 계획을 작성한다. `AGENTS.md`에 따라 독립 reviewer가 현재 계획 버전에 95점 이상을 주고 unresolved blocker/important가 없음을 확인해야만 코드 작업을 시작한다. 구현 단위별 독립 코드 리뷰에도 같은 95점 gate가 적용된다.
