# Basic Pitch Python 3.12 예외 ADR 제안 보고서

> **기록 시점 상태:** 제안 문서 작성 당시 사용자 승인 대기 — 현재 ADR 005 승인 및 Windows CPU PoC 완료<br>
> **일자:** 2026-09-26<br>
> **구현 계획:** [Basic Pitch 독립 worker 구현 계획](../plans/basic-pitch-isolated-worker-implementation-plan.md)

## 결과

이 보고서는 ADR 005 제안 당시의 의사결정 기록이다. 당시에는 `Proposed` 상태였고, 범위는 `services/ml/basic-pitch-worker`의 Python `>=3.12,<3.13` 독립 환경과 Basic Pitch ONNX CPU 검증으로 한정했다. 이후 사용자가 범위를 승인해 ADR은 `Accepted`가 되었고 Windows CPU PoC와 실제 추론 검증도 완료했다. root Python 3.13 workspace 및 공용 패키지 제약은 유지한다. 현재 결정과 검증 결과는 [ADR 005](../adr/005-basic-pitch-python-312-exception.md) 및 [worker smoke 보고서](./basic-pitch-worker-smoke-report.md)에 기록되어 있다.

작성 당시 `docs/main_spec.md`는 ADR 005를 승인 대기 항목으로 연결했다. 해당 항목과 이 보고서는 당시 상태를 보존하며 현재 상태를 나타내지 않는다.

## 기준 검증

기존 전체 root 테스트를 저장소 내 전용 pytest 임시 디렉터리와 uv 캐시로 실행했다.

```text
uv run --project . pytest -p no:cacheprovider --basetemp=.superpowers/sdd/basic-pitch-isolated-worker-implementation-plan/pytest-baseline-tmp -q
30 passed, 1 skipped
```

기본 시스템 임시 경로를 사용한 최초 실행은 sandbox가 `C:\Users\user\AppData\Local\Temp\pytest-of-April` 읽기와 `.pytest_cache` 쓰기를 거부해 15개 storage test setup error가 발생했다. 저장소 내 임시 경로로 다시 실행한 기준 결과는 통과했다. uv 기본 cache 경로도 sandbox에서 초기화되지 않아 cache를 저장소의 ignored `temp/uv-cache`로 지정했다.

## 작성 당시 승인 게이트와 현재 결과

보고서 작성 시점에는 ADR 005가 `Proposed`였고, Python 3.12 환경 생성 및 Basic Pitch worker 코드 구현 전에 사용자 승인이 필요했다. 사용자는 2026-09-26에 제안 범위를 승인했고 ADR은 `Accepted`로 갱신되었다. 승인 후 worker를 구현했으며 실제 Windows CPU 추론을 검증했다.
