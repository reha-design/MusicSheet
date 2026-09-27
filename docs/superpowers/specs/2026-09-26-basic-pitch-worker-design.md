# 백엔드·AI 실행환경 분리 및 Basic Pitch worker 설계

> **상태:** 구현 기준 설계 — ADR 005 승인 및 Windows CPU PoC 검증 완료<br>
> **작성일:** 2026-09-26<br>
> **관련 보고서:** [Basic Pitch Python 3.13 호환성 보고서](../../reports/basic-pitch-python-313-compatibility-report.md), [Python 3.12 단일화 결과보고서](../../reports/python-312-unification-report.md)<br>
> **관련 결정:** [ADR 004 — Python 3.13 단일 표준 런타임](../../adr/004-python-313-runtime.md)

## 1. 목표와 결정 범위

MusicSheet의 백엔드 workspace는 Python 3.13으로 유지하고, 모델 추론은 백엔드와 독립된 실행환경에서 수행한다. 모델별로 Python·운영체제·프레임워크·CUDA 의존성이 호환되면 AI 실행환경을 공유할 수 있다. 호환성을 확인하지 않은 모델을 한 환경에 묶지는 않는다. 이 설계의 첫 대상은 Python 3.12에서 ONNX 경로를 시험하는 Basic Pitch worker다.

- **백엔드 환경:** 루트 uv workspace의 Python `>=3.13,<3.14`. API, 파이프라인 조정, 공용 스키마 및 저장소 경계를 담당한다.
- **AI 실행환경:** 각 호환성 그룹이 독립 uv 프로젝트·lockfile·`.venv`를 갖는다. 백엔드와 모델 패키지를 직접 import하지 않고 프로세스 경계로 호출한다.
- **Basic Pitch:** Python `>=3.12,<3.13`과 ONNX Runtime을 사용하는 독립 worker 후보. 설치·실제 추론을 검증하기 전에는 프로젝트 지원이나 기본 AMT provider로 확정하지 않는다.
- **ADR 004 예외:** ADR 004는 Python 3.12를 현재 프로젝트 지원 범위에서 제외한다. worker 구현에 앞서 ADR 005에서 Basic Pitch worker만의 런타임 예외, 검증 조건 및 재검토/종료 조건을 승인·기록한다. 이는 Python 3.12를 공통 런타임으로 되돌리는 결정이 아니다.
- **다른 모델:** 별도 환경을 미리 늘리지 않는다. ByteDance Piano AMT를 Basic Pitch와 공유할지는 재현 가능한 의존성 및 추론 검증 후 결정한다.
- **하드웨어 범위:** 가상환경과 프로세스 분리는 Python 패키지와 실행 경계를 격리한다. 같은 PC에서 공유하는 GPU, GPU 메모리, CUDA 드라이버 및 CPU 자원은 격리하지 않는다.

이번 범위는 독립 worker의 설치·CLI·결과 계약을 정의한다. 공용 API, Celery task, 상시 실행 서비스, 배포 컨테이너 및 모델 우열 결정은 포함하지 않는다.

## 2. 저장소 현황과 근거

루트 `pyproject.toml`은 Python `>=3.13,<3.14`와 `packages/common`, `packages/storage`로 구성한 uv workspace를 선언한다. uv workspace 멤버는 단일 lockfile과 공통 Python 제약을 공유한다. 그러므로 Python 3.12 worker는 루트 workspace 멤버가 아니라 독립 프로젝트로 둔다. uv 문서는 별도 프로젝트를 각자의 환경과 잠금으로 관리할 수 있고, `uv init --no-workspace`로 상위 workspace 자동 탐색을 피할 수 있다고 설명한다. [uv workspace 문서](https://docs.astral.sh/uv/concepts/projects/workspaces/) · [uv CLI reference](https://docs.astral.sh/uv/reference/cli/)

ADR 004가 현재 승인된 런타임 결정이며 ADR 001을 대체한다. 2026-09-25 결과보고서는 Python 3.12에서 ByteDance와 Basic Pitch의 의존성 해결을 주장하지만, 현재 저장소에는 그 보고서가 언급한 모델별 lockfile, 재현 명령, 입력 fixture 또는 추론 로그가 없다. 별도의 Basic Pitch 호환성 보고서는 실제 설치·추론을 수행하지 않았다고 명시한다. 따라서 과거 결과보고서의 주장을 현재 검증 증거로 간주하지 않고, 재현 가능한 PoC 전까지 ADR 004와 이번 worker의 제한된 예외를 기준으로 한다. 이 설계는 Python 3.12 단일화가 불가능하다는 결론을 내리는 문서가 아니다. 공유환경은 두 모델 모두의 검증이 통과하면 다시 평가할 수 있다.

Basic Pitch 공식 설치 안내는 Python 3.7–3.11을 열거하며 현재 공식 지원 범위에 Python 3.12를 포함하지 않는다. upstream PR [#201](https://github.com/spotify/basic-pitch/pull/201)은 3.12에서 동봉 ONNX 모델을 기본 선택하도록 dependency marker를 바꾸는 미병합 제안이다. 2026-09-26 확인 시 PR은 열려 있고 단일 commit `049dc8a`를 가리킨다. PR 작성자는 Python 3.12.3의 깨끗한 설치와 end-to-end 추론을 기록했지만, 이는 MusicSheet 환경에서 재현한 결과가 아니다. 이 경로를 사용하면 구현 시 전체 commit SHA를 확인해 고정하고, 출처와 수정 내용을 lockfile 및 worker 문서에 남긴다. [Basic Pitch PR #201](https://github.com/spotify/basic-pitch/pull/201)

현재 전사 사양은 ByteDance의 PyTorch 버전을 확정하지 않았고, Basic Pitch 입력을 22.05 kHz mono로 지정한다. 이 설계도 해당 입력 계약을 사용한다. 모델 실행환경을 정할 때는 Python 버전만 비교하지 말고 OS wheel 가용성, 프레임워크 및 CUDA 조합까지 함께 검증한다.

## 3. 환경 및 프로세스 구조

```text
MusicSheet backend (루트 uv workspace, Python 3.13)
  ├─ API / 파이프라인 조정 / 공용 스키마·저장소
  └─ 입력·출력 파일과 versioned JSON 계약으로 worker 호출
       └─ AI runtime compatibility group (독립 uv 프로젝트)
            └─ Basic Pitch worker (Python 3.12, ONNX Runtime, CPU 우선)

다른 AI 모델은 의존성 호환성 검증 후 기존 AI 환경에 합치거나
별도의 compatibility group으로 추가한다.
```

| 경로 | 책임 |
| :--- | :--- |
| `services/ml/basic-pitch-worker/pyproject.toml` | Python 3.12 제약, 고정 의존성, CLI entry point |
| `services/ml/basic-pitch-worker/uv.lock` | worker만의 재현 가능한 의존성 해석 |
| `services/ml/basic-pitch-worker/.venv/` | worker 전용 Python 환경(생성물, 저장소에 커밋하지 않음) |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/` | 입력 검사, Basic Pitch 호출, JSON/MIDI 산출 |
| `services/ml/basic-pitch-worker/README.md` | 환경 생성, 실행, 지원 한계와 문제 해결 |
| `packages/common/musicsheet_common/schemas/transcription_result.py` | 백엔드가 검증하는 versioned 결과 envelope; worker 의존성으로 설치하지 않음 |
| `docs/ai/transcription.md` | provider별 입력·출력·런타임의 canonical 사양 |
| `docs/infrastructure/runtime.md` | 백엔드 표준 런타임과 모델별 예외 원칙 |

독립 프로젝트 생성 시 uv의 `--no-workspace`를 사용해 부모 workspace 탐색으로 루트 멤버에 편입되는 것을 막는다. 환경 설치와 실행은 프로젝트 경로를 명시한다.

```powershell
uv python install 3.12
uv init --package --no-workspace --python 3.12 services/ml/basic-pitch-worker
uv sync --project services/ml/basic-pitch-worker --python 3.12
uv run --project services/ml/basic-pitch-worker --python 3.12 basic-pitch-worker `
  --input-audio <amt_22k_mono.wav> `
  --output-dir <job-output-dir>
```

루트 `uv sync`와 `uv.lock`에는 worker 의존성을 넣지 않는다. 반대로 worker 동기화가 루트 `.venv`를 변경하지 않는지도 검증한다. 별도 프로젝트로 만든다는 사실만으로 GPU 드라이버나 메모리가 분리되지는 않는다.

`pyproject.toml`은 `basic-pitch-worker = "musicsheet_basic_pitch_worker.cli:main"` console script를 선언한다. `--package`는 이 entry point를 worker 환경에 설치할 수 있도록 패키지로 만든다.

```toml
[project.scripts]
basic-pitch-worker = "musicsheet_basic_pitch_worker.cli:main"
```

## 4. Basic Pitch 의존성 및 실행 정책

- Python `>=3.12,<3.13`, Windows 개발 PC, CPU용 ONNX Runtime을 첫 검증 대상으로 한다. 실제 ONNX provider 선택 여부는 환경 probe로 확인한다.
- TensorFlow SavedModel, TensorFlow 2.16+/Keras 3 포팅, PyTorch 재구현, GPU ONNX provider는 첫 단계에서 제외한다.
- PR #201의 변경을 사용할 때에는 PR 제목이나 branch 이름이 아니라 전체 commit SHA로 고정한다. upstream에 공식 배포 버전이 나오면 공식 패키지로 바꾸는 변경을 별도로 검토한다.
- 검증되지 않은 ByteDance PyTorch/CUDA 조합을 Basic Pitch 환경의 의존성으로 추가하지 않는다. Python, OS wheel, 프레임워크, native library, CUDA provider 조합과 실제 추론이 모두 호환되는 경우에만 환경을 공유한다.
- CPU 추론 속도는 PoC에서 측정해 기록한다. 처리량이 실제 병목일 때만 GPU 또는 상시 worker를 별도 설계한다.

## 5. CLI 입력 및 산출물 계약

첫 단계는 한 프로세스 실행당 하나의 입력을 처리하는 CLI다. 현재 파이프라인 구현이 없으므로 이 CLI를 실행할 상위 adapter는 미래 구성요소이며, 이번 설계에서 구현된 것으로 간주하지 않는다.

```text
basic-pitch-worker \
  --input-audio <amt_22k_mono.wav> \
  --output-dir <새 작업별 디렉터리>
```

### 입력

- `--input-audio`는 읽을 수 있는 WAV 파일이며, 전사 사양의 `amt_22k_mono.wav`처럼 22,050 Hz mono로 전처리된 모델 입력을 받는다.
- worker는 파일 존재, 디코딩 가능 여부, 채널 수와 sample rate를 검사하고 계약에 맞지 않으면 추론 전에 실패한다. worker 안에서 리샘플링하거나 원본 전체 파이프라인을 재구현하지 않는다.
- `--output-dir`는 해당 실행에만 쓰는 새 작업 디렉터리다. 오래된 결과와 현재 실행 결과가 섞이지 않게 한다.

### 성공 산출물

- `raw_transcription.json`은 다음 envelope를 사용하며 `note_events`의 각 원소는 `packages/common/musicsheet_common/schemas/note_events.py`의 `RawNoteEvent`, `pedal_events`의 각 원소는 `PedalEvent`에 맞춘다. 저장소가 별도 `CONTROL_EVENTS` artifact를 만들 때는 backend가 이 envelope에서 pedal 목록을 꺼낸다.
- versioned envelope는 `packages/common`의 `TranscriptionResult` Pydantic 모델로 정의한다. 이 모델은 `schema_version`, provider provenance/capability metadata, `note_events`, `pedal_events`를 검증한다. worker는 이 Python 3.13 전용 패키지를 설치하거나 import하지 않고 계약에 맞는 JSON만 쓴다.
- `schema_version`이 consumer가 지원하지 않는 값이면 결과 전체를 거부한다. 각 note event는 onset/offset 초, MIDI pitch, activation 0–1 범위를 지키며 offset은 onset보다 빠를 수 없다.

```json
{
  "schema_version": 1,
  "provider": {
    "id": "spotify-basic-pitch",
    "package_version": "0.4.0",
    "source_commit": "<고정한 전체 commit SHA>",
    "model_asset": "nmp.onnx",
    "supports_pedal": false,
    "confidence_semantics": "uncalibrated_note_activation_mean"
  },
  "note_events": [],
  "pedal_events": []
}
```

- 모델 note amplitude/activation은 `activation`에 보존한다. 현재 `RawNoteEvent.amt_confidence`가 필수이므로 같은 0–1 값을 채우되, `confidence_semantics`로 **보정된 확률이 아닌 activation 평균의 대용값**임을 명시한다. downstream은 이 값을 확률로 해석하지 않는다. Basic Pitch의 note creation 코드가 amplitude를 note frame activation 평균으로 계산하는 방식에 근거한다. [Basic Pitch note creation](https://github.com/spotify/basic-pitch/blob/main/basic_pitch/note_creation.py)
- Basic Pitch 출력에서 별도 페달 이벤트를 제공하지 않는 경우 `pedal_events`는 빈 배열이며 provider metadata의 `supports_pedal`은 false다. MIDI 파일은 추론 API가 만들고 검증에 성공한 경우에만 `transcription.mid`로 포함한다.
- JSON과 MIDI는 임시 파일에 기록한 뒤 완료 시 이름을 바꿔 공개한다. 실패한 실행이 부분 파일을 성공 산출물처럼 남겨서는 안 된다.

### 종료와 실패

| 종료 코드 | 의미 |
| :--- | :--- |
| `0` | 산출물을 모두 기록하고 계약 검사를 통과함 |
| `2` | 입력 경로, 형식, sample rate 또는 채널 계약 위반 |
| `3` | 모델 로딩 또는 추론 실패 |
| `4` | JSON 직렬화, schema 검증 또는 산출물 기록 실패 |

오류와 사람이 읽는 로그는 stderr에 기록한다. stdout은 자동화 계약으로 사용하지 않는다. 부모 adapter가 만들어질 때 종료 코드, 산출물 존재·크기·schema version·필수 필드를 함께 검사하고 timeout을 별도 실패로 처리한다. 부모 adapter의 구현·timeout 정책은 이번 범위가 아니다.

## 6. 검증 및 완료 기준

구현 완료를 주장하기 전에 Windows 개발 PC에서 아래 항목을 재현한다.

1. `uv init --no-workspace`로 만든 worker가 루트 workspace 멤버가 아니며 독립 `uv.lock`과 `.venv`를 가진다.
2. 루트 `uv sync`는 Python 3.12를 요구하거나 worker 의존성을 설치하지 않고, worker 동기화는 루트 환경을 수정하지 않는다.
3. worker의 Python이 3.12이고, 고정한 Basic Pitch 소스와 ONNX Runtime이 설치되며 TensorFlow가 설치되지 않는다. runtime probe에서 ONNX model asset과 ONNX backend 선택을 기록한다.
4. 출처·사용권·SHA-256을 기록한 짧은 피아노 WAV fixture(22,050 Hz mono)를 사용해 end-to-end 추론을 수행한다. 저장소에 재현 가능한 fixture가 없으므로 PoC가 이를 선정하거나 생성해 관리한다. 실제 출력에서 비어 있지 않은 note event, 유효한 시간·pitch·activation 범위 및 MIDI 생성 여부를 기록한다. MIDI 생성은 upstream API가 지원하는 경우에만 완료 조건에 포함한다.
5. 실제 공용 `RawNoteEvent`, `PedalEvent`, `TranscriptionResult` Pydantic 스키마가 Python 3.13 환경에서 JSON envelope와 모든 event를 검증한다. 이 검증은 `docs/domain/note-events.md`의 코드 예시만으로 대체하지 않는다.
6. 없는 파일, 깨진 WAV, 잘못된 sample rate/channel, 기록 불가 출력 경로에서 지정한 비영(非零) 코드가 나오며 성공 JSON이 생성되지 않는다.
7. 수행한 명령, Python·uv·패키지 버전, 전체 source commit SHA, fixture 식별 정보, backend 선택, 실행시간, 산출물 schema 검증 결과를 README 또는 PoC 결과 기록에 남긴다.

PR 작성자의 3.12.3 결과는 PoC를 시작할 근거이지 MusicSheet의 검증 완료 증거가 아니다. 완료 기준을 통과해도 Basic Pitch를 기본 provider로 승격하지 않는다. 모델 비교와 실제 pipeline adapter 통합은 별도 결정이다.

worker 제품 코드 구현 전 ADR 005에서 ADR 004의 좁은 예외를 기록하고 승인한다. 이 설계 문서 검토는 해당 ADR이나 구현 계획의 승인으로 간주하지 않는다.

## 7. 위험, 되돌림 및 범위 제외

- **미병합 upstream patch:** 설치 소스가 바뀌거나 접근 불가하면 해당 고정을 갱신해 검토하기 전까지 PoC를 멈춘다. TensorFlow로 자동 전환해 성공으로 처리하지 않는다.
- **환경 분리 비용:** 환경마다 저장공간·설치시간이 추가된다. 호환성 증거가 생기면 모델을 같은 AI 환경에 합칠 수 있으나 백엔드 의존성을 AI 프레임워크와 결합하지 않는다.
- **구형 Python 3.12 결과 보고서와 현재 ADR 충돌:** Python 3.12 단일화 보고서는 과거 결과로 보존한다. ADR 004를 대체하지 않으며, 그 보고서에만 있는 모델 호환성 주장은 재현 전 현재 지원 상태로 사용하지 않는다.
- **공유 GPU:** 별도 `.venv`와 CLI 프로세스는 GPU 메모리 경쟁을 방지하지 않는다. 동시성 제한은 향후 실제 worker scheduler의 책임이다.
- **후속 범위:** API/Celery adapter, daemon/HTTP/gRPC/queue consumer, 컨테이너, GPU ONNX, TensorFlow/Keras 포팅, PyTorch 자체 구현 또는 학습, 페달 검출, 양손 분리, 리듬 양자화 및 악보 렌더링은 제외한다.
