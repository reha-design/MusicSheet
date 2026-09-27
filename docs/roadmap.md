# 개발 작업목록

이 문서는 현재 계획된 개발 작업의 기준 목록입니다. 아키텍처 전체 계획을 복제하지 않고, 작업의 진행 상태와 완료 기준만 관리합니다. 구현 시작 전 계획은 [저장소 작업 지침](../AGENTS.md)의 95점 게이트를 통과해야 하며, 구현 단위 사이에도 별도 코드 리뷰 95점 게이트를 적용합니다.

상태는 `Planned`(시작 전), `In Progress`(진행 중), `Done`(완료 기준 충족)으로 표시합니다. 작업 완료 시 결과 보고서를 작성하고 `docs/main_spec.md`의 Reports 색인도 갱신합니다.

| 상태 | 작업 | 완료 기준 | 관련 사양 |
| :--- | :--- | :--- | :--- |
| Done | LocalStorage 어댑터 구현 | `ArtifactStorage`의 `put`, `open_read`, `exists`, `materialize`를 구현하고, `put`이 `ArtifactRef`를 반환하며 `outputs/{job_id}/` 구조에 저장합니다. | [스토리지 추상화](architecture/storage.md), [아티팩트 규격](domain/artifacts.md), [구현계획서](plans/local-storage-implementation-plan.md), [결과보고서](reports/local-storage-implementation-report.md) |
| Done | FastAPI 헬스 체크 구현 | 독립 `services/api`가 `/health/live`, `/health/ready`, `/health/detail`을 제공합니다. Readiness는 DB·Redis·스토리지 쓰기 가능성을 검사하고, 상세 진단은 API 호스트의 GPU·FFmpeg·MuseScore 정보를 best-effort로 표시합니다. | [API 명세](backend/api.md), [헬스 체크 명세](infrastructure/health-check.md), [구현 계획](plans/fastapi-health-check-implementation-plan.md), [결과 보고서](reports/fastapi-health-check-implementation-report.md) |
| In Progress | PostgreSQL 작업 영속성 기반 구현 | 버전 관리되는 마이그레이션으로 `jobs`, `stage_attempts`, `artifacts` 및 migration ledger를 만들고, API의 선택적 DB pool과 `JobRepository`의 작업 생성·조회·진행상태 갱신을 검증합니다. 계획 독립 리뷰 99/100. | [데이터베이스 명세](backend/database.md), [작업 상태 명세](domain/job-state.md), [API 명세](backend/api.md), [구현 계획](plans/postgresql-job-persistence-implementation-plan.md) |

PostgreSQL 작업 영속성 구현은 승인된 계획의 세 단계와 구현 단위별 독립 코드 리뷰 게이트를 순서대로 통과한 뒤 완료로 표시합니다.
