# 개발 작업목록

이 문서는 현재 계획된 개발 작업의 기준 목록입니다. 아키텍처 전체 계획을 복제하지 않고, 다음 두 작업의 진행 상태와 완료 기준만 관리합니다.

상태는 `Planned`(시작 전), `In Progress`(진행 중), `Done`(완료 기준 충족)으로 표시합니다. 작업 완료 시 결과 보고서를 작성하고 `docs/main_spec.md`의 Reports 색인도 갱신합니다.

| 상태 | 작업 | 완료 기준 | 관련 사양 |
| :--- | :--- | :--- | :--- |
| Done | LocalStorage 어댑터 구현 | `ArtifactStorage`의 `put`, `open_read`, `exists`, `materialize`를 구현하고, `put`이 `ArtifactRef`를 반환하며 `outputs/{job_id}/` 구조에 저장합니다. | [스토리지 추상화](architecture/storage.md), [아티팩트 규격](domain/artifacts.md), [구현계획서](plans/local-storage-implementation-plan.md), [결과보고서](reports/local-storage-implementation-report.md) |
| Planned | FastAPI 헬스 체크 구현 | `/health/live`, `/health/ready`, `/health/detail`을 제공합니다. Readiness는 DB·Redis·스토리지 연결을 확인하고, 상세 진단은 CUDA·FFmpeg·MuseScore 정보를 표시합니다. API 프로세스에 없는 GPU·렌더러 의존성을 readiness 실패 조건으로 묶지 않습니다. | [API 명세](backend/api.md), [헬스 체크 명세](infrastructure/health-check.md) |

LocalStorage를 먼저 구현합니다. Readiness 항목이 스토리지 연결 확인을 포함하므로 헬스 체크가 이를 사용할 수 있어야 합니다.
