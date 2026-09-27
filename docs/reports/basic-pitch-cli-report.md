# Basic Pitch inference adapter 및 CLI 구현 보고서

> **상태:** 구현·검증·독립 코드 리뷰 완료 (97/100)<br>
> **일자:** 2026-09-26<br>
> **구현 계획:** [Basic Pitch 독립 worker 구현 계획](../plans/basic-pitch-isolated-worker-implementation-plan.md)<br>
> **환경:** [Basic Pitch worker 환경 구성 보고서](./basic-pitch-worker-environment-report.md)

## 구현 범위

- worker의 직접 의존성으로 `pretty-midi>=0.2.10`을 추가하고 lockfile을 갱신했다. 잠금 버전은 `0.2.11.post0`이다.
- `run_prediction(Path)`가 `basic_pitch.inference.predict`를 호출해 model output, MIDI 및 note tuple을 `PredictionOutput`으로 반환한다. upstream stdout은 stderr로 돌리고 실패를 `InferenceError`로 분류한다.
- `build_result`가 provider provenance, 매핑된 note events, 빈 pedal list를 가진 schema version 1 JSON envelope를 만든다.
- `validate_result_payload`가 backend 공용 schema를 import하지 않고 provider, note, pedal 필드와 시간·범위·finite 조건을 검사한다. invalid result는 `ResultValidationError`다.
- `write_outputs`가 JSON과 선택적 MIDI를 같은 부모 아래 임시 형제 디렉터리에 기록한 뒤 디렉터리 rename으로 공개한다. 경로가 이미 존재하거나 기록 중 실패하면 결과 경로를 게시하지 않고 임시 디렉터리를 정리한다.
- console entry point `basic-pitch-worker`가 필수 `--input-audio`, `--output-dir`을 받고 도움말 및 오류 종료 코드를 포함해 성공 `0`, 입력 오류 `2`, 추론 오류 `3`, 결과/기록 오류 `4`를 반환한다.

## 검증

구현 전에 새 테스트를 실행해 모듈 부재에 따른 RED를 확인했다. 구현 및 `pretty-midi` 직접 의존성/lockfile 갱신 후 worker 디렉터리에서 실행:

```text
uv run --project . --python 3.12 pytest -p no:cacheprovider tests/test_inference.py tests/test_output.py tests/test_cli.py -q
19 passed, 1 warning

uv run --project . --python 3.12 pytest -p no:cacheprovider -q
46 passed, 1 warning
```

테스트는 stdout 격리, provider metadata와 schema 검증, NaN·역전된 시간·잘못된 pedal event 거부, JSON/MIDI 저장, 네 exit code, 기존 출력 경로, 추론·MIDI 기록 실패 후 부분 디렉터리 부재, 실제 console entry point의 `--help` 실행을 확인한다. 남은 warning 한 개는 `resampy`가 발생시키는 `pkg_resources` deprecation warning이다.

독립 코드 리뷰는 97/100으로 95점 기준을 통과했다. 리뷰어는 JSON 검증이 공용 Pydantic schema보다 느슨하지 않고, Windows에서 기존 경로 검사와 동일 부모 디렉터리 rename으로 출력 계약을 지키는 점을 확인했다. 남은 확인 항목은 Task 6에서 Python 3.13 모델로 실물 결과를 검증하는 것이다.

## 제한 사항

이 단계는 mock inference로 adapter 및 artifact contract를 검증했다. 실제 모델 추론, 재배포 가능한 fixture, 결과 JSON의 backend Pydantic 검증은 Task 6에서 확인한다. 출력 대상은 실행마다 새로운 경로여야 한다.
