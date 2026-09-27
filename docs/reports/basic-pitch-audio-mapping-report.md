# Basic Pitch 입력 WAV 검사 및 note event 매핑 보고서

> **상태:** 구현·검증·독립 코드 리뷰 완료 (97/100)<br>
> **일자:** 2026-09-26<br>
> **구현 계획:** [Basic Pitch 독립 worker 구현 계획](../plans/basic-pitch-isolated-worker-implementation-plan.md)<br>
> **환경:** [Basic Pitch worker 환경 구성 보고서](./basic-pitch-worker-environment-report.md)

## 구현 범위

- `audio.py`에 `AudioInfo`, `InvalidAudioError`, `validate_input_audio(path)`를 추가했다.
- 입력 경로가 파일인지 확인하고 little-endian RIFF와 big-endian RIFX WAVE chunk 길이를 파일 경계와 대조한다. 손상된 header, 빠진 data chunk, 잘린 chunk payload를 추론 전에 거부한다.
- `soundfile`로 WAV 형식, 양수 frame 수, 22,050 Hz, mono를 확인한다. payload는 최대 65,536 frame 단위로 읽어 전체를 메모리에 적재하지 않고 decode 가능 여부를 검증한다.
- `mapping.py`에 `map_note_events`를 추가했다. Basic Pitch의 `(start, end, pitch, amplitude, pitch_bend_values)` tuple을 입력 순서대로 `bp-000001` 형식의 RawNoteEvent dict로 만든다.
- 유한한 시간/amplitude, float 변환에서의 overflow, `0 <= start <= end`, 정수 MIDI pitch `0..127`, amplitude `0..1`을 확인한다. `activation`과 `amt_confidence`에 amplitude를 넣고, `velocity_prediction`과 `source_chunk`는 `None`으로 둔다. 현재 공용 계약에 없는 pitch bend는 사용하지 않는다.

## 검증

실행 전 테스트에서 `audio` 및 `mapping` 모듈 부재로 수집 단계에서 실패하는 RED를 확인했다. 이어서 RIFF 길이를 정상처럼 고쳤지만 data chunk가 잘린 케이스를 추가해 기존 접근이 이를 놓치는 것을 재현하고, chunk 길이 검사 후 통과함을 확인했다.

worker 디렉터리에서 실행:

```text
uv run --project . --python 3.12 pytest -p no:cacheprovider tests/test_audio.py tests/test_mapping.py -q
19 passed

uv run --project . --python 3.12 pytest -p no:cacheprovider -q
27 passed, 1 warning
```

남은 warning 한 개는 Task 3에서 기록한 upstream `resampy`의 `pkg_resources` deprecation warning이다. WAV 읽기 검증은 truncation과 구조상 잘못된 RIFF chunk를 검출하지만, 일반 PCM WAV에는 payload checksum이 없으므로 값이 바뀌어도 유효한 sample로 해석되는 임의의 bit corruption을 검출한다고 주장하지 않는다.

독립 코드 리뷰는 97/100으로 사용자 기준 95점을 통과했다. reviewer는 RIFF/RIFX 검사와 event mapping이 계획 및 `RawNoteEvent` 계약에 맞는 것을 확인했다. 빠진 data chunk, 불완전한 header, 홀수 길이 chunk padding 테스트는 선택적 보강 항목으로 남겼으며 코드 검사상 차단 이슈는 없었다.

## 범위 밖

Basic Pitch 추론, JSON envelope 검증 및 파일 공개는 Task 5에서 구현한다. 재배포 가능한 piano fixture를 사용한 실제 모델 실행은 Task 6에서 확인한다. 이 보고서는 worker가 오디오를 성공적으로 전사했다고 의미하지 않는다.
