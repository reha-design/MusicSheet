# LocalStorage 아티팩트 어댑터 구현 보고서

> **문서 번호:** REPORT-20260926-13
> **작성 일자:** 2026-09-26
> **프로젝트:** MusicSheet
> **검증 상태:** 전체 기본 테스트 통과

---

## 1. 변경 개요

`packages/storage`의 `LocalStorage`를 완성해 작업별 `outputs/{job_id}/` 경로에 아티팩트를 기록하고 읽을 수 있게 했습니다.

- `put()`은 `Path` 또는 바이너리 스트림을 최대 64 KiB 청크로 복사합니다. 복사 중 SHA-256과 크기를 계산하고, 같은 디렉터리의 임시 파일을 완성한 뒤 `os.replace()`로 결과를 공개합니다. 파일명 심볼릭 링크가 있으면 대상이 작업 폴더 안인지 확인하고 링크 이름 자체를 교체해 대상 파일을 보존합니다.
- 반환하는 `ArtifactRef`에는 UUID4, `file://` URI, MIME 유형, 크기, SHA-256, producer 정보가 포함됩니다. MIME 유형을 알 수 없으면 `application/octet-stream`을 사용합니다.
- `exists()`와 `open_read()`는 로컬 `file://` URI를 해석하고, URI 경로가 저장소 경계 안에서 `job_id`와 파일명에 대응하는지 확인합니다. 없는 파일은 `exists()`에서 `False`, `open_read()`에서 `FileNotFoundError`로 처리합니다.
- `materialize()`는 충돌 없는 디렉터리와 파일을 `temp_dir` 아래에 만듭니다. 원본을 가리키는 심볼릭 링크를 먼저 시도하고, 운영체제 권한 등으로 링크를 만들 수 없으면 파일을 복사합니다. 원본 파일이 없으면 `FileNotFoundError`를 발생시킵니다.
- `Path` 입력으로 전달된 파일은 닫고, 호출자가 전달한 바이너리 스트림은 열린 상태로 둡니다.

## 2. 검증 결과

| 검증 | 명령 | 결과 |
| :--- | :--- | :--- |
| 스토리지 단위 테스트 | `uv run pytest tests/unit/test_storage.py -q` | 28 passed, 3 skipped |
| 기본 전체 테스트 | `uv run pytest -q` | 53 passed, 3 skipped, 4 deselected |

단위 테스트는 경로·스트림 입력, 청크 제한, 해시와 메타데이터, 부분 파일 정리, URI 경계 검증, 읽기 및 실체화 동작을 확인합니다. 현재 Windows 환경에서는 권한 제약으로 실제 파일·디렉터리 symlink 테스트 3개를 건너뛰며, 결정적 단위 테스트가 in-job symlink 경로 처리와 복사 fallback을 검증합니다. `ml_integration` 테스트 4개는 기본 실행에서 제외되어 있습니다.

## 3. 코드 리뷰

각 함수 단계를 구현한 뒤 독립 리뷰를 받았으며 모두 95점 기준을 통과했습니다.

| 단계 | 점수 | 범위 |
| :--- | ---: | :--- |
| Step 2 | 96/100 | 스트리밍 `put()` 및 ArtifactRef 생성 |
| Step 3 | 97/100 | 안전한 URI 확인, `exists()`, `open_read()` |
| Step 4 | 95/100 | `temp_dir` 안의 symlink 또는 복사본을 반환하는 `materialize()` (수정 후 재리뷰) |
| 최종 리뷰 | 95/100 | 전체 LocalStorage 구현·문서 일관성, 기준 통과 |

## 4. 남은 범위와 후속 보강

- S3 어댑터와 API·Celery 연동은 구현하지 않았습니다.
- MIME 매핑은 운영체제별 차이가 있을 수 있습니다. WAV MIME 정규화와 저장 교체 실패 경로의 직접 테스트가 후속 보강 항목입니다.
- 읽기 경로의 심볼릭 링크·URI 변형별 테스트와 복사 fallback 실패 시 정리 테스트를 더 보강할 수 있습니다. 경로 검증과 실제 파일 열기 사이에 다른 프로세스가 파일시스템을 바꾸는 좁은 TOCTOU 구간은 남아 있습니다. Windows에서 실제 symlink 교체 원자성은 권한 제약으로 직접 확인하지 못했습니다.
