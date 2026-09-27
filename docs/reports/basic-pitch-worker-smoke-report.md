# Basic Pitch worker 실제 추론 smoke 보고서

> **상태:** 구현·실제 추론·backend schema 검증·독립 코드 리뷰 완료 (97/100)<br>
> **일자:** 2026-09-26<br>
> **구현 계획:** [Basic Pitch 독립 worker 구현 계획](../plans/basic-pitch-isolated-worker-implementation-plan.md)<br>
> **worker 운영:** [Basic Pitch isolated worker README](../../services/ml/basic-pitch-worker/README.md)<br>
> **fixture 사용권:** [audio fixture 출처 및 SHA-256](../../tests/fixtures/audio/README.md)

## 재현 입력과 사용권

- Fixture: `tests/fixtures/audio/basic_pitch_smoke.wav`; 16초, WAV PCM_16, 22,050 Hz mono, 352,800 frames.
- Source: Wikimedia Commons의 “Emotional piano.wav”, recording author triangelx; 원본 Freesound item 189175도 CC0 1.0으로 표시한다. 원본은 44,100 Hz stereo 16-bit PCM, 16초, 2,822,444 bytes다.
- 원본은 두 채널의 평균으로 mono downmix하고 `scipy.signal.resample_poly(up=1, down=2)`로 22,050 Hz에 변환한 뒤 PCM_16 WAV로 저장했다.
- 원본 다운로드 SHA-1은 `E8C449FBA4FE1EB5E67E0923B6B696F2105584C5`이며 Wikimedia Commons structured checksum과 일치한다. 로컬 원본 SHA-256은 `9661F81D37C59F230B324B830AB68C0482336AF3EC117C92E73108FFB4095F15`, checked-in fixture SHA-256은 `2970C7FCA3CCC442C078EB0A4EDB2F788731E9D36F5049CC2558FA68E599366A`다.

## 실행 환경과 결과

- OS: Windows, version `10.0.26200` (registry display `25H2`).
- Backend/runtime validator: CPython `3.13.7`, Pydantic `2.13.5`.
- Worker: CPython `3.12.13`, uv `0.10.11`, Basic Pitch `0.4.0`, source commit `049dc8a01a170c2370d7b246ec1c2067e060c3bf`, ONNX Runtime `1.30.0`, SoundFile `0.14.0`, pretty-midi `0.2.11.post0`.
- ONNX Runtime available providers were Azure and CPU; the pinned Basic Pitch ONNX model loader selects `CPUExecutionProvider` when CUDA is unavailable. An ONNX session check reported `session_providers=["CPUExecutionProvider"]`.
- Timed CLI command exited `0`; wall time from uv process launch through worker completion was `2.016 s` on this machine. This is end-to-end CLI time, not isolated model kernel time.
- The worker wrote a version 1 `raw_transcription.json` and `transcription.mid`. Python 3.13 `TranscriptionResult.model_validate_json` accepted the JSON. The result contains 113 note events with finite timing, MIDI pitch and confidence ranges.
- Selected integration command from repository root: `uv run --project . pytest -m ml_integration tests/integration/test_basic_pitch_worker.py -q` → `4 passed in 2.81s` on the recorded run. Cases covered the real CC0 fixture plus missing input, stereo input, and wrong sample rate.
- Default root command: `uv run --project . pytest -q` → `40 passed, 1 skipped, 4 deselected in 0.30s`; the four `ml_integration` cases are excluded unless selected.

## 판단과 남은 범위

이 결과는 Windows에서 pinned Python 3.12/Basic Pitch/ONNX CPU path가 실제 note event와 MIDI를 만들고, 파일 JSON이 Python 3.13 공용 schema에 맞음을 확인한다. 본 smoke는 작은 fixture의 실행 가능성 확인이며 transcription accuracy benchmark, API/Celery 통합, 제품 기본 provider 채택 근거는 아니다. `resampy`가 `pkg_resources` deprecation warning을 발생시키며, 호환 release가 허용될 때 Task 3의 `setuptools<81` pin을 재검토한다.

독립 코드 리뷰는 97/100으로 95점 기준을 통과했다. 최초 리뷰에서 발견한 canonical runtime/transcription 사양의 상태 불일치를 수정했고, 재리뷰에서 smoke 결과와 두 사양이 일치함을 확인했다. 통합 테스트 내부 provider 직접 확인 및 빈 pedal list assertion은 선택 제안이며 기존 worker boundary 검사와 schema/보고서 증거를 고려해 필수 범위로 추가하지 않았다.
