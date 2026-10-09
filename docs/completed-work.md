# 완료 작업 색인

이 파일은 roadmap에서 완료된 작업의 짧은 색인입니다. 구현 내용과 검증 세부사항은 각 결과보고서에만 보관합니다.

| 완료일 | 작업 | 최종 리뷰 | 결과보고서 | 주요 커밋 |
| :--- | :--- | :---: | :--- | :--- |
| 2026-09-26 | LocalStorage 아티팩트 어댑터 | 95/100 | [보고서](reports/local-storage-implementation-report.md) | `808ec05` |
| 2026-09-27 | FastAPI 헬스 체크 | 98/100 | [보고서](reports/fastapi-health-check-implementation-report.md) | `d0597b5` |
| 2026-09-27 | PostgreSQL 작업 영속성 기반 | 97/100 | [통합 보고서](reports/postgresql-job-persistence-implementation-report.md) | `4e36383`, `c68798e`, `f3342e1`, `67d76f2`, `6d00243` |
| 2026-09-28 | Job REST API v1 | 96/100 | [보고서](reports/job-rest-api-v1-implementation-report.md) | `8408993`, `46a890d`, `ebce351` |
| 2026-10-03 | W02 Redis Streams 및 SSE | 계획 100/100 · 단위 99/98/100 · 최종 98/100 | [보고서 — 실 Redis 성공 경로 미검증](reports/redis-streams-sse-implementation-report.md) | `c1ca195`, `f675ec9` |
| 2026-10-04 | W03 Celery 오케스트레이션 | 계획99/100 · 단위99/99/99/99 · 최종99/100 | [당시 구현 보고서](reports/celery-orchestration-implementation-report.md) · [후속 실 PostgreSQL·Redis·Linux worker 검증](reports/celery-live-verification-report.md) | `83915c7`, `1d9898f`, `60e1f24`, `1bded7d` |
| 2026-10-04 | W04 Basic Pitch 제품 파이프라인 연결 | 계획100/100 · 단위100/100/100/100 · 전체100/100 | [Windows 실제 모델/DB·Linux 실행기/root 검증](reports/basic-pitch-pipeline-implementation-report.md) | `0381b6f`, `4844773`, `4d0abe8` · 최종 검증 커밋은 보고서 참조 |
| 2026-10-06 | Pipeline 진행률·정체 작업 복구 및 PR #11 정리 | 계획97/100 · 단위99/99 · 전체99/100 | [PR #13 병합·실 DB/Redis·원본 보존](reports/pipeline-operator-tools-integration-report.md) | `7e84882`, `26d5028`, `7f82cf2` · 병합 `2720fcd` |
| 2026-10-10 | W05 전사 모델 평가·고정 피아노 subset 선정 | Task5 계획99/100 · Task1–5 각100/100 · 별도 전체100/100 | [실제 CPU72회·Piano AMT 선정/제품 연결 대기](reports/transcription-model-evaluation-report.md) | 구현·병합 커밋은 보고서 참조 |
