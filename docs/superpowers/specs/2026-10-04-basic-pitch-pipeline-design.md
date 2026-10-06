# W04 — Basic Pitch 제품 파이프라인 연결 설계

- Revision: 1 · 작성일: 2026-10-04 (Asia/Seoul)
- 상태: 2026-10-04 `다음작업 진행`으로 서면 설계 R1 승인. 실행 계획 R4 독립100점·Task1~4 구현 각100점·전체 독립 리뷰100점. Windows 실제 모델/DB·Linux 실행기/root 검증 완료.
- 기준 코드: `84c3a7b` (W03 실제 Linux worker 후속 검증 완료)
- 요구사항: [W04 진행 현황](../../roadmap.md), [전사](../../ai/transcription.md), [모델 어댑터](../../ai/model-adapters.md), [런타임](../../infrastructure/runtime.md), [아티팩트](../../domain/artifacts.md)
- 선행 계약: [독립 worker 설계](2026-09-26-basic-pitch-worker-design.md), [worker 실제 추론 증거](../../reports/basic-pitch-worker-smoke-report.md), [W03 설계](2026-10-03-celery-orchestration-design.md)

## 1. 목표와 현재 상태

사용자의 요청은 완료된 Celery 검증 다음 작업을 진행하는 것이다. 현황 문서의 다음 작업인 W04를 선택했다. 성공 기준은 Python 3.13 단계 실행기가 별도 Python 3.12 Basic Pitch worker를 호출하고, version 1 JSON과 MIDI를 검증한 뒤 기존 스토리지·DB 아티팩트 경로에 등록하는 것이다.

설계 시작 기준의 `packages/pipeline`에는 `StageProvider`와 runner가 구현돼 있었지만 제품 registry는 비어 있었다. 구현·검증 현황은 [W04 결과보고서](../../reports/basic-pitch-pipeline-implementation-report.md)에 기록한다. `services/ml/basic-pitch-worker`는 실제 Windows ONNX CPU 추론을 통과한 독립 CLI이며, 입력은 22,050 Hz mono WAV다. runner는 직전 완료 attempt의 출력만 다음 단계 입력으로 전달하고, 성공한 출력의 SHA-256·크기·job 소유권·producer·attempt 접두사를 검사한다. 따라서 URL이나 사용자가 전달한 로컬 경로를 모델 CLI 입력으로 직접 사용하지 않는다.

이번 설계의 가정은 Basic Pitch를 명시적으로 활성화할 수 있는 첫 전사 provider로 연결한다는 것이다. 기본 모델 선정은 W05에서 평가한다. 기존 Celery·Kombu·Redis 버전, Python 3.13 표준 환경과 ADR 005의 모델 환경 예외를 유지한다.

## 2. 접근 방식 비교

| 방식 | 장점 | 비용·제약 | 선택 |
| :--- | :--- | :--- | :--- |
| 단계마다 독립 CLI 실행 + 연결부에서 입력 변환 | 기존 worker·프로세스 경계를 재사용하고 작업별 실패·취소를 격리한다 | 매 호출 모델 로딩 비용, subprocess 수명 관리가 필요하다 | **추천** |
| 미리 변환된 `MODEL_INPUT`만 수용 | 연결부가 간단하다 | 아직 없는 선행 provider가 분리 후 22.05kHz 변환을 반드시 수행해야 한다. W04만으로 실제 분리 음원 연결을 검증하기 어렵다 | 보류 |
| 상주 모델 서버와 RPC 호출 | 모델을 재사용할 수 있다 | 서버 readiness·통신·인증·배포·요청별 취소 계약이 추가된다 | 별도 성능 근거가 생기면 재검토 |

## 3. 구성과 데이터 흐름

`packages/pipeline` 안에 모델 의존성을 import하지 않는 Basic Pitch 연결부를 둔다. 역할은 설정 검증, subprocess 수명 관리, 입력 변환, 결과 검사, 저장으로 나눈다. 기존 `StageProvider.run(StageContext)`와 `ArtifactStorage` 인터페이스를 사용한다. 미래의 동기 `AMTProvider` ABC 예시를 구현하기 위해 공용 계약을 다시 만들지 않는다.

```text
TRANSCRIBE StageContext
  → 직전 SEPARATE attempt의 SEPARATED_AUDIO 하나 선택
  → 작업 전용 임시 디렉터리에 materialize
  → FFmpeg: 로컬 WAV → 22,050 Hz mono PCM WAV
  → 별도 Python 3.12: 기존 Basic Pitch CLI
  → version 1 JSON 및 MIDI 검사
  → LocalStorage.put: attempt별 JSON·MIDI 두 파일
  → 기존 runner 무결성 검사와 DB 완료 트랜잭션
```

입력은 `SEPARATED_AUDIO` 하나인 WAV로 제한한다. 22.05kHz mono PCM 입력은 규격 확인 후 재변환 없이 사용할 수 있다. 그 외 로컬 WAV는 FFmpeg로 변환한다. 다른 선행 role, 입력 0개·중복·여러 stem은 영구 오류다. 향후 SEPARATE provider는 선택한 대상 stem 하나를 다음 단계에 전달해야 한다. 다른 입력 계약이 필요하면 W06 계획에서 W04 계약을 명시적으로 갱신한다.

모델 입력은 이 작업의 임시 파일이며 별도 `MODEL_INPUT` 아티팩트로 등록하지 않는다. 출력 role은 정확히 `RAW_TRANSCRIPTION`, `MIDI` 두 개다. 파일 이름은 `attempt_{attempt_id}_raw_transcription.json`, `attempt_{attempt_id}_transcription.mid`다. producer는 연결부의 `ProviderIdentity`와 일치하며 모델 자체 provenance는 JSON envelope에 보존한다.

## 4. 설정·런타임·캐시 경계

- `TRANSCRIPTION_PROVIDER` 미설정은 현재와 같이 TRANSCRIBE provider 미구성이다. `basic-pitch`를 명시적으로 설정했을 때만 factory가 provider를 만든다. 알 수 없는 값은 안전한 설정 오류다.
- 활성화에는 설치된 Python 3.12 인터프리터의 절대 경로 `BASIC_PITCH_PYTHON`과 FFmpeg 실행 파일의 절대 경로 `FFMPEG_EXECUTABLE`이 필요하다. 상대 경로·없는 실행 파일·지원하지 않는 런타임은 명시적 오류다. 경로와 원본 예외를 공개 오류에 포함하지 않는다.
- import 시 프로세스 생성·파일 저장·모델 import·네트워크 요청을 하지 않는다. 기존 설정 생성자의 호출 호환성을 유지한다. registry는 설정으로 만든 불변 매핑이며 runner에 주입한다.
- 요청마다 `uv sync`나 패키지 다운로드를 수행하지 않는다. 독립 worker 환경을 사전에 설치하고 lock을 검증한다. root·API 환경에는 Basic Pitch·ONNX Runtime·TensorFlow·pretty-midi를 추가하지 않는다.
- 기존 worker CLI 함수를 고정된 bootstrap 코드로 호출한다. Python 경로와 argv를 분리하고 shell을 사용하지 않는다. bootstrap은 Python 3.12 여부와 설치된 worker 버전을 확인한 뒤 `cli.main()`을 호출한다. 기존 CLI 모듈에 `python -m` entrypoint가 있다고 가정하지 않는다.
- MIDI 검사는 경량 parser `mido==1.3.3`을 pipeline 직접 의존성으로 추가해 수행한다. 이는 모델 환경에서 이미 사용 중인 버전이며, root Python 3.13 호환성·lock 변경은 구현 때 실제 검증한다. 모델 inference 의존성을 root로 가져오는 근거로 사용하지 않는다.
- provider fingerprint에는 연결부 버전, Basic Pitch `0.4.0`·source commit `049dc8a01a170c2370d7b246ec1c2067e060c3bf`·`nmp.onnx`, schema 1, 입력 변환 규격, 실행 파일 경로와 확인한 FFmpeg 버전, 결과 크기 제한을 포함한다. 모델 환경은 배포 중 불변으로 취급한다. 같은 경로의 환경·도구를 바꾸면 연결부 버전 또는 설정을 갱신해 이전 캐시를 재사용하지 않는다.

## 5. 입력·결과 검증

FFmpeg는 표준 입력을 받지 않고 로컬 파일 프로토콜만 허용하며 WAV decoder와 PCM WAV 출력을 명시한다. source URL이나 artifact URI를 FFmpeg argv에 직접 넣지 않는다. 변환 성공 후 PCM WAV의 sample rate·채널·비어 있지 않은 frame·실제 읽을 수 있는 frame 수를 검사하고, 변환 실패를 모델 성공으로 처리하지 않는다.

모델 output-dir는 해당 attempt의 임시 root 아래 존재하지 않는 새 디렉터리로 전달한다. JSON·MIDI는 정해진 파일 이름의 일반 파일이어야 하며 symlink·디렉터리·임시 root 밖 경로는 거부한다. JSON은 최대 8 MiB, MIDI는 최대 16 MiB다. 제한값은 연결부의 결과 읽기·파싱을 제한하는 정책이며 API 업로드 제한을 바꾸지 않는다.

JSON은 UTF-8로 크기를 제한해 읽고 중복 key, NaN·Infinity를 거부한 뒤 공용 `TranscriptionResult`로 검증한다. 문자열을 숫자로 조용히 변환하는 등 공용 schema의 coercion에 의존하지 않도록 version·bool·정수·수치의 wire 타입을 검사한다. schema 1, 정확한 pinned provider provenance, `supports_pedal=false`, 빈 pedal 목록, 고유한 nonempty note_id를 확인한다. 빈 note 목록은 무음 등의 정상 결과로 허용한다. timing·pitch·activation·confidence·velocity는 공용 노트 계약을 만족해야 한다. 모델 confidence를 정확도나 보정된 확률로 표시하지 않는다.

MIDI는 파일 전체를 경량 parser로 읽어 header·track·event의 구조가 읽히는지 확인한다. 잘린 파일·잘못된 event·track 종료 누락은 거부한다. note가 없는 유효 MIDI는 허용한다. 이 검사는 JSON과 MIDI의 음악적 동등성 또는 악보 정확도 평가가 아니다. 기존 worker는 MIDI 생략을 허용하지만 W04의 제품 provider는 JSON과 MIDI가 모두 있어야 성공한다.

두 결과를 모두 검사한 뒤 저장을 시작한다. 연결부는 정확히 두 `ArtifactRef`를 반환하고 runner의 기존 무결성 검사·완료 트랜잭션을 통과해야 DB에서 결과를 공개한다. 모델 파일이 만들어졌다는 사실만으로 stage를 완료하지 않는다.

## 6. 실패·취소·자원 소유권

- worker exit 2는 입력 오류, 3은 모델/추론 오류, 4는 결과 생성 오류로 분류한다. 실행 파일 누락·다른 Python 버전·잘못된 JSON/MIDI·누락된 출력도 영구 오류다. 기존 `PermanentProviderError` 또는 `InvalidArtifact`를 통해 runner의 공개 오류 계약을 유지한다. child stderr, 경로, 환경 값은 API·SSE에 노출하지 않는다.
- 확인되지 않은 추론 오류를 무조건 재시도하지 않는다. 기존 DB·broker 인프라 retry 정책은 유지한다. 저장소 I/O 실패도 기존 `PermanentProviderError` 경로의 영구 실패로 처리하며, 자동 provider retry를 추가하지 않는다. 검증 실패는 `InvalidArtifact`다.
- 설정 구성 시 실행 파일/version probe는 각각 5초로 제한하고 소유한 프로세스를 정리한다. stage의 전체 provider 실행 시간 제한은 runner의 기존 1,800초를 사용하며 변환·추론·검증·저장을 포함한다. timeout과 작업 취소는 같은 정리 경로를 따른다.
- 연결부가 생성한 child만 종료한다. 취소 event와 task cancellation을 모두 감지하고, subprocess 생성 중 취소도 소유권을 회수한다. 반복 취소가 정리 작업을 중단하지 않도록 drain한다. 종료 요청 후 5초 안에 종료하지 않으면 강제 종료하고 `wait()` 완료를 확인한다.
- POSIX에서는 작업별 process group, Windows에서는 소유한 Job Object를 사용해 정상 취소·timeout 시 실행한 process tree를 정리한다. Windows Job Object 연결 실패는 child를 회수한 뒤 실패 처리한다. stdout/stderr를 무제한 메모리에 쌓지 않는다.
- materialize·파일 검사·스토리지 저장처럼 동기 I/O를 별도 thread로 수행할 때는 완료를 기다린 뒤 임시 root를 삭제한다. 취소 후 새 저장을 시작하지 않으며 부분 저장된 이 attempt의 결과는 정리한다. 다른 attempt나 이미 등록된 입력은 삭제하지 않는다.
- OS 강제 종료·Celery child SIGKILL 중에도 임시 파일과 모델 프로세스가 자동 회수된다고 보장하지 않는다. W03의 DB ownership fence는 늦은 결과 등록을 막지만 orphan 파일의 GC나 owner death에 따른 모든 프로세스 회수는 별도 운영 범위다. 이 제한을 실제 장애 복구 보고서에서 숨기지 않는다.

## 7. 검증과 합격 기준

| 검증 층 | 내용 | 합격 기준 |
| :--- | :--- | :--- |
| 설정·경계 | opt-in, 기존 설정 호환성, 잘못된 path/runtime, 모델 import 금지 | 비활성 상태의 기존 동작 유지, 잘못된 구성은 성공 처리하지 않음 |
| subprocess·변환 | argv, 실제 작은 WAV 변환, exit 오류, timeout, 시작/실행/정리 중 반복 취소, descendant 정리 | shell 미사용, 22.05kHz mono 입력, owned child 및 thread 종료 후 반환 |
| 결과·저장 | 정상/빈 결과, wire 타입, provenance, 크기 제한, symlink, 잘린 MIDI, 두 번째 저장 실패, 저장 중 취소 | 두 파일이 모두 검증돼야 성공, 실패·취소는 DB 공개 결과 없음 |
| runner·DB 통합 | 완료한 SEPARATE attempt를 가진 격리 job에서 TRANSCRIBE 실행, fingerprint 재사용·입력 변경·취소 fence | 실제 output metadata 등록, 완료/다음 단계 outbox는 기존 runner 계약대로 원자적 반영 |
| 실제 모델 | checked-in CC0 16초 fixture, 설치된 Python 3.12 + ONNX CPU worker + Python 3.13 provider | JSON·MIDI 생성/공용 schema/스토리지 해시를 통과, note 이벤트와 빈 pedal 목록 확인 |
| 회귀 | root, API, 독립 worker tests 및 lock 경계 | 기존 통과 범위 유지, 새 실패 없음, 필요한 환경 부재는 미검증으로 기록 |

실제 모델 검증은 현재 증거가 있는 Windows 환경부터 수행한다. checked-in fixture를 사용하며, 연결부의 44.1kHz stereo 변환은 별도의 생성 WAV로 실제 FFmpeg 검증한다. fixture를 역변환한 오디오의 정확도를 원본 fixture 정확도로 주장하지 않는다. 모델 없이 종료를 제어하는 subprocess fixture로 늦은 종료·반복 취소·descendant 처리를 재현한다. 실제 모델 호출과 제어용 fixture 결과를 구분해 보고한다.

Linux의 Celery 실제 worker 검증은 독립 Python 3.12 모델 설치와 ONNX CPU 조합 검증이 선행돼야 한다. 기존 W03의 Linux 테스트 provider 성공을 Linux Basic Pitch 성공으로 간주하지 않는다. W04 완료 보고서에 OS별 실제 모델/runner/DB/Celery 검증 범위를 별도로 적는다. PostgreSQL 검증은 전용 임시 환경을 만들며 다른 프로젝트 DB를 사용하지 않는다.

## 8. 포함하지 않는 후속 범위

W04는 DOWNLOAD·PREPROCESS·SEPARATE 제품 provider, 웹 UI, PDF 생성, 새 API, DB migration, 기본 AMT 선정·fallback, 정확도 benchmark, GPU/CUDA, 상주 모델 서버를 추가하지 않는다. 전체 작업을 실행하면 아직 미구성인 선행 단계에서 실패할 수 있다. TRANSCRIBE 연결 성공을 전체 제품 end-to-end 완료로 기록하지 않는다.

실제 YouTube URL의 다운로드부터 악보까지 테스트는 W09 전체 통합 범위다. W04에서는 네트워크 입력 대신 재현 가능한 fixture로 실제 모델 경계를 확인한다. 이후 W05는 동일 평가 입력으로 모델 선택, W06은 stem 입력 계약, W11은 운영 배포·owner death·orphan 정리를 다룬다.

## 9. 승인·리뷰 상태

> 아래는 설계 완료 시점의 기록이다. 이후 R4 구현과 실환경 검증은 완료됐으며 최신 상태는 문서 상단과 W04 결과보고서를 따른다.

자체 검토는 기존 CLI entrypoint, 입력 sample rate, 직전 attempt 입력 제한, MIDI 생략 가능성, Windows/Linux 증거 차이와 강제 종료 한계를 설계에 반영했다. 제품 동작은 아직 변경하지 않았다.

사용자 서면 설계 R1은 2026-10-04 `다음작업 진행`으로 승인됐다. 관련 canonical spec을 갱신하고 [실행 계획 R3](../../plans/basic-pitch-pipeline-implementation-plan.md)을 작성했다. 독립 계획 리뷰는 **100/100**, blocker0/important0/minor0으로 통과했고 [설계 완료 보고서](../../reports/basic-pitch-pipeline-design-completion-report.md)에 요구사항별 근거를 기록했다. 사용자 목표 `설계완료까지 계속해서 진행`에 해당하는 설계·계획 단계는 완료했다. 제품 구현 시작 전 작성된 실행 계획의 사용자 검토·실행 방식 선택이 필요하며, 구현 단위별 독립 코드 리뷰에도 별도로 95점 게이트를 적용한다. 구현은 아직 시작하지 않았다.
