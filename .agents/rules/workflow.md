# MusicSheet Agent Workflow Rules

MusicSheet 프로젝트에서 작업하는 모든 AI 에이전트는 다음 워크플로우 사이클을 반드시 준수해야 한다.

## 1. 진입점 및 컨텍스트 라우팅
- 모든 작업 시작 시 `docs/main_spec.md`를 읽고 작업 유형에 해당하는 2~4개의 세부 Canonical Spec만 로드한다.

## 2. 작업 완료 사이클 (필수)
모든 Task는 다음 4단계 사이클을 거쳐야 완료로 인정된다:
1. **구현 (Implementation):** Spec에 정의된 스키마와 설계를 바탕으로 구현한다.
2. **테스트 검증 (TDD Verification):** 반드시 `uv run pytest`로 자동화 테스트를 실행하여 `PASSED`를 확인한다.
3. **결과보고서 작성 (Report Generation):** Task 완료 시 `docs/reports/`에 커밋 단위 작업 결과보고서를 작성하고 `docs/main_spec.md`의 Reports 색인에 추가한다.
4. **원자적 커밋 (Atomic Commit):** 테스트와 보고서가 완료되면 해당 작업 관련 파일만 명시적으로 스테이징하여 Conventional Commit 규격으로 커밋한다.
