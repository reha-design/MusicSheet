# Basic Pitch 독립 worker 구현 계획

> **진행 상태:** Task 1–6 완료; 최종 통합 리뷰 96/100 통과; 커밋 완료

> **For agentic workers:** 구현 전에 `superpowers:subagent-driven-development`(권장) 또는 `superpowers:executing-plans`를 사용한다. 각 작업은 체크박스로 추적하며, 각 작업을 끝낼 때 독립 검증한다.

**Goal:** Python 3.13 backend와 독립적인 Python 3.12 + ONNX Basic Pitch CLI worker 및 버전이 명시된 JSON 결과 계약을 구현한다.

**Architecture:** Git 모노레포와 현재 root uv workspace는 유지한다. `services/ml/basic-pitch-worker`만 `--no-workspace` uv 프로젝트로 두며 Python 3.13 backend와는 파일 기반 JSON 계약으로 통신한다. worker는 `packages/common`을 설치하거나 import하지 않고, backend의 Pydantic 모델이 결과를 검증한다.

**Tech Stack:** Python 3.13 / Pydantic v2 backend schema, Python 3.12 / uv / Basic Pitch 고정 Git commit / `onnxruntime` CPU / `soundfile` / `pretty_midi` worker, pytest.

**Spec:** [저장소 및 uv 실행환경 구조 결정](repository-and-uv-environment-structure-plan.md), [Basic Pitch worker 설계](../superpowers/specs/2026-09-26-basic-pitch-worker-design.md), [Python 3.13 런타임 ADR 004](../adr/004-python-313-runtime.md)

## Global Constraints

- root, `packages/common`, `packages/storage`는 Python `>=3.13,<3.14`와 현재 uv workspace를 유지한다.
- Basic Pitch worker는 `services/ml/basic-pitch-worker`에서 Python `>=3.12,<3.13`, 독립 `pyproject.toml`/`uv.lock`/`.venv`를 사용하고 `uv init --no-workspace`로 workspace 자동 편입을 차단한다.
- worker는 `packages/common`에 의존하지 않는다. 프로세스 경계 결과는 `schema_version: 1` JSON이며 backend가 `TranscriptionResult`로 검증한다.
- 입력은 WAV, mono, 22,050 Hz여야 한다. worker는 리샘플링하지 않는다. ONNX Runtime CPU만 사용하며 TensorFlow, PyTorch 재구현, GPU provider는 범위에 넣지 않는다.
- Basic Pitch는 설계 문서의 PR #201 변경을 검토하고 전체 40자리 commit SHA로 고정한다. 모델 및 패키지 버전, source commit은 결과 metadata에 기록한다.
- worker 제품 코드를 시작하기 전에 ADR 005를 `Accepted`로 승인해야 한다. 계획서 승인이나 설계 검토만으로 ADR 승인을 대신하지 않는다.
- 종료 코드는 성공 `0`, 입력 오류 `2`, 추론 오류 `3`, 직렬화/기록 오류 `4`다. 결과는 전부 준비한 뒤 공개하여 실패 시 부분 산출물을 남기지 않는다.
- 최초 구현 세션에서는 `.git` 쓰기 권한이 없어 커밋을 미뤘다. 현재 세션에서 사용자가 전체 변경 마무리와 커밋을 명시 요청했으므로, 독립 리뷰와 검증 통과 후 미커밋 범위를 커밋한다.
- 구현 각 Task 종료 시 `docs/reports/` 결과 보고서를 만들고 `docs/main_spec.md`의 색인을 갱신한다. 최초 실행에서는 커밋 권한이 없어 결과를 작업 폴더에 유지했으며, 이번 전체 통합 리뷰 통과 후 사용자 요청에 따라 커밋한다.

## Review Focus

- 파일은 WAV 헤더가 있으나 payload가 손상된 경우: 추론 전 입력 오류 `2`로 거부한다 (`test_rejects_corrupt_wav_payload`).
- mono가 아니거나 22,050 Hz가 아닌 경우: 자동 변환 없이 입력 오류 `2`로 거부한다 (`test_rejects_wrong_channels_and_sample_rate`).
- 음표 시간 역전, NaN/무한대, 범위 밖 pitch/amplitude 또는 미지원 schema version: 결과 JSON을 거부한다 (`test_raw_note_event_rejects_non_finite_values`, `test_mapping_rejects_invalid_note_values`, `test_transcription_result_rejects_unsupported_schema_version`).
- 추론/기록 중 실패하거나 출력 경로에 기존 결과가 있는 경우: 부분 결과를 게시하거나 기존 데이터를 덮어쓰지 않는다 (`test_cli_does_not_publish_partial_output`, `test_cli_rejects_existing_output_directory`).
- upstream Basic Pitch가 stdout에 진행 메시지를 출력하는 경우: worker 자동화의 stdout 계약을 오염시키지 않도록 stderr로 보낸다 (`test_prediction_output_is_redirected_to_stderr`).

---

## 파일 경계

| 경로 | 책임 |
| :--- | :--- |
| `docs/adr/005-basic-pitch-python-312-exception.md` | Basic Pitch에 한정한 Python 3.12 예외, 승인 상태, 검증 및 재검토/종료 조건 |
| `packages/common/musicsheet_common/schemas/transcription_result.py` | JSON envelope와 provider provenance/capability schema |
| `packages/common/musicsheet_common/schemas/note_events.py` | 기존 note/pedal 이벤트의 시간 순서 검증 |
| `services/ml/basic-pitch-worker/pyproject.toml`, `uv.lock`, `.python-version` | worker의 독립 Python 및 의존성 잠금 |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/__init__.py` | worker 패키지 경계 |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/provenance.py` | 확인된 Basic Pitch full SHA 및 provider metadata 상수 |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/audio.py` | WAV 계약 확인 및 디코딩 검사 |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/mapping.py` | upstream note tuple을 JSON note event로 변환 |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/inference.py` | Basic Pitch 공식 inference API 호출과 출력 stream 처리 |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/output.py` | 결과 envelope 구성, JSON/MIDI 임시 기록 및 원자적 공개 |
| `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/cli.py` | argument 파싱, 오류 분류와 종료 코드 |
| `services/ml/basic-pitch-worker/tests/` | worker 단위 테스트 |
| `tests/integration/test_basic_pitch_worker.py` | 독립 worker 실행 및 backend schema 검증 smoke test |
| `tests/fixtures/audio/basic_pitch_smoke.wav` 및 동반 라이선스 안내 | 재현 가능한 짧은 합법적 piano fixture |
| `docs/superpowers/specs/2026-09-26-basic-pitch-worker-design.md` | 확정된 worker 경로와 명령의 설계 기준 |
| `docs/main_spec.md` | 계획/ADR 링크 색인 |

## 구현 작업

### Task 1: 구조 결정 반영 및 ADR 005 승인 게이트

**Files:**
- Create: `docs/adr/005-basic-pitch-python-312-exception.md`
- Create: `docs/reports/basic-pitch-runtime-exception-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:**
- Produces: worker의 표준 경로 `services/ml/basic-pitch-worker`; ADR 005는 처음 `Proposed` 상태로 작성한다.

- [x] ADR 005에 Python 3.12 예외의 단일 대상, 미병합 Basic Pitch commit 출처, CPU ONNX 범위, PoC 통과 기준, 실패 시 지원 보류, upstream 지원 변화 시 재검토 조건을 기록한다. 첫 작성 상태는 `Proposed`다.
- [x] `main_spec.md`에서 Proposed ADR을 색인하고, 확정된 구조 계획 및 본 구현 계획과의 링크가 유지되는지 확인한다.
- [x] ADR proposal과 근거를 결과 보고서에 기록한다. 이 문서 작업 후 Task 2의 backend schema 변경은 진행할 수 있지만, worker 프로젝트/제품 코드 작업은 ADR 수락 전까지 보류한다.

### Task 2: backend `TranscriptionResult` 계약

**Files:**
- Create: `packages/common/musicsheet_common/schemas/transcription_result.py`
- Modify: `packages/common/musicsheet_common/schemas/note_events.py`
- Modify: `packages/common/musicsheet_common/schemas/__init__.py`
- Modify: `packages/common/musicsheet_common/__init__.py`
- Test: `tests/unit/test_schemas.py`
- Create: `docs/reports/transcription-result-contract-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:**
- Produces: `ProviderMetadata` 및 `TranscriptionResult` Pydantic 모델을 `musicsheet_common.schemas`와 `musicsheet_common` 최상위에서 export한다.
- `ProviderMetadata`: `id`, `package_version`, `source_commit`, `model_asset`, `supports_pedal`, `confidence_semantics` 필드. Basic Pitch confidence semantics는 `uncalibrated_note_activation_mean`이다.
- `TranscriptionResult`: `schema_version: Literal[1]`, `provider: ProviderMetadata`, `note_events: list[RawNoteEvent]`, `pedal_events: list[PedalEvent]`.

- [x] 실패 테스트 `test_transcription_result_accepts_v1_and_roundtrips_json`, `test_transcription_result_rejects_unsupported_schema_version`, `test_raw_note_event_rejects_offset_before_onset`, `test_raw_note_event_rejects_non_finite_values`, `test_pedal_event_rejects_offset_before_onset`, `test_pedal_event_rejects_non_finite_values`를 추가한다.
- [x] 실행: `uv run --project . pytest tests/unit/test_schemas.py -q`; 새 테스트가 구현 부재/검증 부재로 실패하는지 확인한다.
- [x] 두 event 모델에 `offset_sec >= onset_sec` 검증과 non-finite float 거부를 추가하고 envelope를 schema 버전 1로 제한한다. note activation과 `amt_confidence`의 기존 0–1 제약을 유지한다.
- [x] 실행: `uv run --project . pytest tests/unit/test_schemas.py -q`; 대상 테스트가 통과하고 root 환경/lockfile에 Python 3.12 의존성이 추가되지 않았는지 확인한다.

### Task 3: 독립 uv worker 프로젝트 및 Basic Pitch 의존성 고정

**Files:**
- Create: `services/ml/basic-pitch-worker/pyproject.toml`
- Create: `services/ml/basic-pitch-worker/uv.lock`
- Create: `services/ml/basic-pitch-worker/.python-version`
- Create: `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/__init__.py`
- Create: `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/provenance.py`
- Create: `services/ml/basic-pitch-worker/tests/`
- Test: `services/ml/basic-pitch-worker/tests/test_worker_dependency_boundary.py`
- Create: `docs/reports/basic-pitch-worker-environment-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:**
- Consumes: Accepted 상태인 ADR 005 및 Task 2의 JSON 필드 계약.
- Produces: `basic-pitch-worker = "musicsheet_basic_pitch_worker.cli:main"` console entry point metadata와 Python `>=3.12,<3.13` 프로젝트. CLI module은 Task 5에서 구현한다.

- [x] worker project나 제품 코드를 만들기 전에 ADR 005를 사용자에게 제시해 명시 승인을 받는다. 승인이 없으면 이 Task에서 멈추며 Python 3.12 예외 구현을 시작하지 않는다.
- [x] 승인되면 ADR 상태를 `Accepted`로 갱신하고 근거·범위·승인일을 ADR 및 `main_spec.md`에 기록한다.
- [x] PR #201의 head commit을 upstream에서 확인하여 전체 40자리 SHA를 얻고, upstream review가 없는 점을 기록한 뒤 diff를 직접 검토한다. 변경은 설계된 ONNX/Python 3.12 dependency marker와 일치한다.
- [x] 새 프로젝트 시작 명령은 `uv init --package --no-workspace --python 3.12 services/ml/basic-pitch-worker`로 고정하고 생성된 프로젝트가 root workspace에 편입되지 않는지 확인한다. 아래 `uv sync`가 worker 전용 `.venv`와 `uv.lock`을 만든다.
- [x] worker project metadata에 `requires-python = ">=3.12,<3.13"`, `basic-pitch` Git source의 전체 SHA, CPU `onnxruntime`, `soundfile`, `setuptools<81`, pytest 및 `basic-pitch-worker` entry point를 선언한다. `resampy 0.4.2`의 `pkg_resources` runtime import을 위한 setuptools pin은 호환 release가 허용되면 제거한다. TensorFlow와 `packages/common`은 dependency graph에서 제외한다.
- [x] `uv sync --project services/ml/basic-pitch-worker --python 3.12`와 `uv run --project services/ml/basic-pitch-worker --python 3.12 python -c "import sys; assert sys.version_info[:2] == (3, 12)"`를 실행해 lockfile과 Python 선택을 확인한다.
- [x] `test_worker_dependency_boundary.py`에 Python 3.12, `onnxruntime` 존재 및 `CPUExecutionProvider` 사용 가능, `basic_pitch.inference` import 가능, TensorFlow 미설치, `musicsheet_common` 미설치, Basic Pitch 버전/source commit 일치와 Python 3.12에서 ONNX backend 선택 검사를 작성한다.
- [x] pytest는 root 설정이 worker 바깥 테스트까지 수집하지 않도록 worker 디렉터리에서 `uv run --project . --python 3.12 pytest -q`로 실행한다. 별도로 root에서 `uv sync --project .` 후 root `.venv`가 worker dependency를 받지 않는지 확인한다.

### Task 4: 입력 WAV 검사 및 note event 변환

**Files:**
- Create: `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/audio.py`
- Create: `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/mapping.py`
- Test: `services/ml/basic-pitch-worker/tests/test_audio.py`
- Test: `services/ml/basic-pitch-worker/tests/test_mapping.py`
- Create: `docs/reports/basic-pitch-audio-mapping-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:**
- Produces: `validate_input_audio(path: Path) -> AudioInfo` 및 `map_note_events(note_events: Iterable[Sequence[object]]) -> list[dict[str, object]]`.
- `AudioInfo(sample_rate: int, channels: int, frames: int)`; note IDs는 `bp-000001`부터 입력 순서대로 부여한다.

- [x] RIFF/RIFX 생성형 임시 파일로 `test_rejects_missing_file`, `test_rejects_corrupt_wav_payload`, `test_rejects_truncated_rifx_payload`, `test_rejects_wrong_channels_and_sample_rate`, `test_accepts_nonempty_22050_hz_mono_wav`, `test_accepts_nonempty_22050_hz_mono_rifx_wav`를 작성하고 구현 전 실패를 확인한다.
- [x] worker 디렉터리를 현재 작업 경로로 두고 `uv run --project . --python 3.12 pytest -p no:cacheprovider tests/test_audio.py -q`에 해당하는 테스트를 구현 전 실행했다.
- [x] `soundfile`로 WAV 형식·존재·비어 있지 않은 frame 수·22,050 Hz·1채널을 확인하고, RIFF chunk 길이와 payload 전체의 block 단위 decode로 잘림을 검증한다. mismatch는 전용 `InvalidAudioError`로 알린다.
- [x] 같은 worker 명령으로 `test_audio.py`를 통과시킨다.
- [x] mapping 실패 테스트 `test_maps_activation_and_uncalibrated_confidence`, `test_mapping_rejects_invalid_note_values`, `test_mapping_generates_stable_ids`를 작성하고 구현 전 실패를 확인한다.
- [x] worker 디렉터리에서 해당 mapping 테스트를 구현 전 실행해 실패를 확인했다.
- [x] 공식 API note tuple의 `(start, end, pitch, amplitude, pitch_bend_values)`에서 시간/음높이/amplitude를 추출한다. `activation=amplitude`, `amt_confidence=amplitude`, `velocity_prediction=None`, `source_chunk=None`으로 기록하고 pitch bend는 현재 공용 계약에서 표현하지 않으므로 버린다.
- [x] 모든 숫자의 finite 여부 및 float 변환 overflow, `0 <= onset <= offset`, MIDI pitch `0..127`, amplitude `0..1`을 확인한 뒤 결과를 반환한다. worker 전체 suite를 통과시켰다.

### Task 5: inference adapter, 원자적 산출 및 CLI

**Files:**
- Create: `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/inference.py`
- Create: `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/output.py`
- Create: `services/ml/basic-pitch-worker/src/musicsheet_basic_pitch_worker/cli.py`
- Test: `services/ml/basic-pitch-worker/tests/test_inference.py`
- Test: `services/ml/basic-pitch-worker/tests/test_output.py`
- Test: `services/ml/basic-pitch-worker/tests/test_cli.py`
- Create: `docs/reports/basic-pitch-cli-report.md`
- Modify: `docs/main_spec.md`

**Interfaces:**
- Produces: `run_prediction(audio_path: Path) -> PredictionOutput`, `build_result(prediction: PredictionOutput, *, package_version: str, source_commit: str) -> dict[str, object]`, `validate_result_payload(result: Mapping[str, object]) -> None`, `write_outputs(output_dir: Path, result: dict[str, object], midi_data: pretty_midi.PrettyMIDI | None) -> None`, `main(argv: Sequence[str] | None = None) -> int`.
- `PredictionOutput`은 `model_output: object`, `midi_data: pretty_midi.PrettyMIDI | None`, `note_events: Sequence[Sequence[object]]` 필드를 가진 frozen dataclass다.
- CLI 인자: 필수 `--input-audio`, 필수 `--output-dir`; 출력 디렉터리는 실행마다 새 경로여야 한다.

- [x] `pretty_midi`를 worker의 직접 의존성으로 선언하고 lockfile/환경을 갱신했다. 검증 테스트는 mock 중심으로 작성했으며 성공/error exit, JSON edge case, MIDI 기록 및 실제 console entry point 도움말 호출도 포함했다.
- [x] 구현 전 worker 테스트 실행에서 inference/output/CLI 모듈 부재에 따른 RED를 확인했다.
- [x] `run_prediction`은 `basic_pitch.inference.predict(audio_path)`의 `(model_output, midi_data, note_events)` 결과를 사용하고 upstream 진행 출력을 stderr로 보낸다. 추론 예외를 CLI가 분류 가능한 `InferenceError`로 감싼다.
- [x] output module은 `id="spotify-basic-pitch"`, 설치된 package version, Task 3의 고정 SHA, `model_asset="nmp.onnx"`, `supports_pedal=False`, `confidence_semantics="uncalibrated_note_activation_mean"`, note list 및 빈 pedal list로 schema_version 1 envelope를 만든다. Python 3.12 worker에서는 `packages/common`을 import하지 않는다.
- [x] `validate_result_payload`는 schema version 1, provider 필수 metadata, note/pedal 필드, 유한한 값, note의 시간·pitch·activation/confidence 범위를 검사한다. `write_outputs`는 JSON을 공개하기 전에 검증하며 실패를 `ResultValidationError`로 알린다.
- [x] JSON과 반환된 MIDI의 `.write(path)` 결과를 같은 파일시스템의 임시 형제 디렉터리에 완성하고, 출력 대상 경로가 아직 없을 때 디렉터리 단위 rename으로 공개한다. 기존 출력 디렉터리는 덮어쓰지 않고 실패 시 임시 디렉터리를 정리한다.
- [x] `main`은 입력 검증 실패 `2`, 모델 로딩/추론 실패 `3`, schema 직렬화/기록 실패 `4`, 성공 `0`으로 반환한다. 성공 JSON은 `raw_transcription.json`; 검증된 MIDI가 있으면 `transcription.mid`로 둔다.
- [x] worker 디렉터리에서 `uv run --project . --python 3.12 pytest -p no:cacheprovider -q`로 전체 검증을 완료했다. 네 종료 코드, 도움말 entry point, 출력 stream, MIDI/JSON 기록 및 부분 산출물 차단을 확인했다.

### Task 6: 재현 가능한 end-to-end smoke 및 운영 문서

**Files:**
- Create: `services/ml/basic-pitch-worker/README.md`
- Create: `tests/fixtures/audio/basic_pitch_smoke.wav`
- Create: `tests/fixtures/audio/README.md` (출처, 사용권, SHA-256)
- Create: `tests/integration/test_basic_pitch_worker.py`
- Create: `docs/reports/basic-pitch-worker-smoke-report.md`
- Modify: `.gitignore`
- Modify: `pyproject.toml` (integration marker 등록 및 기본 수집 제외)
- Modify: `docs/main_spec.md`
- Modify: 필요 시 `docs/infrastructure/runtime.md`, `docs/ai/transcription.md`, `docs/ai/model-adapters.md`

**Interfaces:**
- Consumes: worker CLI 및 Task 2의 Python 3.13 `TranscriptionResult` 검증 모델.
- Produces: 사용권과 checksum이 기록된 짧은 22,050 Hz mono piano WAV로 실행하는 선택형 `ml_integration` smoke test 및 실행 방법.

- [x] 재배포 가능한 CC0 piano recording을 fixture로 선정하고 출처·license·SHA-256을 기록했다. `.gitignore`에서 `tests/fixtures/audio/basic_pitch_smoke.wav`와 동반 README만 허용한다.
- [x] Python 3.13 root 통합 테스트가 worker Python 3.12 CLI를 subprocess로 실행한다. 성공 코드, JSON, backend `TranscriptionResult.model_validate_json`, 유효 note event, MIDI 파일을 확인한다.
- [x] 누락 파일과 잘못된 채널/샘플레이트가 `2`를 반환하고 결과 디렉터리를 공개하지 않는 통합 사례를 `ml_integration` marker로 분리했다.
- [x] worker README에 독립 설치/실행 명령, Python·Basic Pitch 전체 commit·onnxruntime 버전, CPU provider, 입력/output 계약, 종료 코드 및 제한 사항을 기록했다. root `uv sync`가 worker를 설치하지 않는 점도 명시했다.
- [x] smoke 실행 OS, Python/uv/package 버전, 전체 source SHA, fixture, ONNX provider, worker 호출 wall time, note count, JSON schema 결과와 MIDI 생성을 보고서에 기록했다. API/Celery 통합이나 다른 모델 환경은 추가하지 않았다.
- [x] root pytest 설정에 `ml_integration` marker를 등록하고 기본 수집에서 제외했다. 선택 명령은 `uv run --project . pytest -m ml_integration tests/integration/test_basic_pitch_worker.py -q`다.
- [x] 일반 root 검증과 선택 smoke 명령을 실행하고 `docs/reports/`에 각각의 결과를 기록했다.

## 완료 조건

- root Python 3.13 workspace와 lockfile이 worker 의존성으로부터 독립되어 있다.
- ADR 005 승인 이후에만 worker 제품 코드를 구현했고, worker는 Python 3.12에서 ONNX CPU 경로를 사용한다.
- 공용 Pydantic schema가 version 1 결과를 검증하고 미지원 버전 및 시간 역전을 거부한다.
- CLI 실패 코드와 원자적 출력 계약이 단위/통합 테스트에서 재현된다.
- 실제 Basic Pitch 추론 smoke, fixture 사용권, full SHA, 실행환경과 결과가 문서화된다.

## 계획 자체 점검

- **스펙 범위:** 독립 uv 프로젝트, 런타임 예외 ADR, JSON contract, WAV 입력, Basic Pitch mapping, ONNX 경로, CLI 종료 코드, 원자적 출력, end-to-end 증거 및 문서 반영을 Task 1–6에 연결했다.
- **인터페이스 정합성:** Python 3.13 schema는 `RawNoteEvent`/`PedalEvent`를 사용하고 Python 3.12 worker는 같은 필드의 JSON만 만든다. worker 경로는 확정된 `services/ml/basic-pitch-worker`로 정규화한다.
- **예외 입력 검토:** 손상 파일, 잘못된 sample rate/channel, 잘못된 숫자/시간/pitch, 미지원 schema, 추론 실패 및 출력 충돌을 소유 테스트에 연결했다.
- **실행 경계:** 계획 저장과 구조 확정은 구현/ADR 승인과 구분했다. ADR 승인이 없으면 worker 코드 작업은 시작하지 않는다.
