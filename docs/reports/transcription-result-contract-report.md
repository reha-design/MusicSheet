# TranscriptionResult 계약 구현 보고서

> **상태:** 구현·검증 및 독립 코드 리뷰 완료 (96/100)<br>
> **일자:** 2026-09-26<br>
> **구현 계획:** [Basic Pitch 독립 worker 구현 계획](../plans/basic-pitch-isolated-worker-implementation-plan.md)

## 변경 내용

- `ProviderMetadata`와 `TranscriptionResult` schema version 1 모델을 추가하고 `musicsheet_common.schemas` 및 `musicsheet_common`에서 export했다.
- `RawNoteEvent`와 `PedalEvent`는 offset이 onset보다 앞서는 값을 거부하고, 시간/신뢰도/activation 값의 NaN·무한대를 거부한다.
- Basic Pitch worker는 아직 생성하지 않았고, Python runtime 제약·root lockfile은 변경하지 않았다.

## 검증

테스트는 구현 전 실패를 확인했다. 최초 추가 테스트는 결과 모델 export 부재, note/pedal 시간 역전, 무한 시간값을 잡았다. 별도 테스트로 pedal 무한값 거부와 package root export를 먼저 실패시킨 뒤 구현했다.

```text
uv run --project . pytest -p no:cacheprovider --basetemp=<repo-local-temp> tests/unit/test_schemas.py -q
19 passed

uv run --project . pytest -p no:cacheprovider --basetemp=<repo-local-temp> -q
40 passed, 1 skipped
```

현재 sandbox가 기본 AppData uv cache와 pytest temp/cache 경로를 제한해 `UV_CACHE_DIR`와 `--basetemp`를 저장소 아래의 전용 임시 위치로 지정했다. root `pyproject.toml`과 `uv.lock`은 변경하지 않았다.

## 제한 사항

`TranscriptionResult`는 현재 schema version `1`만 받는다. 결과의 provider metadata는 필수이며, note/pedal event는 기존 공용 모델을 사용한다. 추후 계약 변경은 schema version을 올리고 별도 호환성 검토가 필요하다.

## 독립 코드 리뷰

- 점수: **96/100** — 구현 task의 95점 기준 통과.
- 제안 사항: `source_commit`을 공용 schema에서 40자리 SHA로 검증할 수 있다. 이번 계약은 여러 provider에 사용할 metadata로 계획되어 있어 비어 있지 않은 값만 요구한다. Basic Pitch 전체 SHA의 정확성은 worker dependency/provenance task에서 고정·검증한다.