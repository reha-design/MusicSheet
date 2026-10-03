# W03 Celery 오케스트레이션 계획 리뷰 보고서

- 날짜: 2026-10-03 (Asia/Seoul)
- 코드 기준: `4c86e91`
- 범위: 승인 설계 상태·Canonical Celery/DB 사양 정합성·W03 실행 계획·진행 색인
- 사용자 설계 승인: `w03진행`
- 작성 당시 상태: 계획 Revision 2 독립 리뷰 100점, 사용자 계획 검토 대기, 제품 미변경. 이후 `다음 task 진행`으로 실행 승인됐으며 Task1 작성 중 resolver 충돌을 발견해 R3 재평가99점을 받았다.

## 실행 계획

[W03 계획](../plans/celery-orchestration-implementation-plan.md)은 네 단위로 나눈다: DB 실행/발행 대기 기록, provider 실행과 결과 검증, Celery/dispatcher/API 연결, 실서비스 통합과 운영 문서. 각 단위는 테스트·독립 95점 리뷰·보고서·원자적 commit으로 끝난다. 계획 점수와 구현 점수는 별개로 기록한다.

계획에서 메시지 generation을 attempt와 연결할 DB 컬럼, 중단된 RUNNING의 next-generation 예약, available_at 조기 전달 방지, DB lock 소유권 상실, 실제 worker 테스트의 namespace/프로세스 소유권을 구체화했다. generation 컬럼과 중단 복구는 승인된 동작을 구현 가능한 저장 계약으로 명시한 것으로, 기능 범위를 확장하지 않는다.

실제 YouTube URL로 음원을 다운로드하는 테스트는 이번 범위 밖이다. 테스트 provider로 오케스트레이션을 확인하고 다운로드·모델 provider는 후속 작업에서 연결한다. 제품 registry는 비어 있으며 설정 없는 provider는 실패로 종료한다.

## 독립 리뷰 기록

Reviewer: `/root/w03_plan_review`, 2026-10-03. Revision 1 **94/100** (24/25·18/20·20/20·22/25·10/10), blocker0/important2/minor2. 구현 시작 불가로 판정했다.

- important: CANCEL_REQUESTED까지 발행에서 제외할 수 있는 모호한 조건 → R2에서 제외 enum을 COMPLETED/FAILED/CANCELED로 한정하고 최초·retry 취소 dispatch 테스트 추가.
- important: 동기 integrity 검사가 async monitor를 막을 수 있음 → 모든 storage 검사를 소유 thread에 offload하고 stop/stream close/drain 및 느린 read 회귀를 명시. OS read hard timeout을 보장한다고 주장하지 않음.
- minor: root live suite API migration/SSE 접근 경계 → API 환경 사전 sync·명시적 migration, root version 검사, 소유 API subprocess와 stdlib SSE client 종료 책임 명시.
- minor: provider 입력 target 누락 → StageInput/StageContext target_instrument 및 fingerprint 전달 테스트 추가.

Revision 2 **100/100** (25/25·20/20·20/20·25/25·10/10), blocker0/important0/minor0. 같은 reviewer가 네 지적의 해결을 확인하고 당시 버전의 계획 점수 게이트 통과로 판정했다. 점수는 R2에만 적용된다. 이후 작성된 계획에 사용자 실행 승인을 받았다.

Revision 3 **99/100** (25/25·20/20·20/20·25/25·9/10), blocker0/important0/minor1. 실제 resolver가 Celery Redis extra `<6.5`와 API Redis `>=8.1.0`의 충돌을 확인하여 안정 공통 범위 `>=6.4.0,<6.5`와 W02 회귀 요구로 조정했다. Reviewer는 공식 요구사항과 공개 클라이언트 API를 독립 확인했다. minor인 과거 대기/미착수 상태 문구는 역사와 현재 상태를 구분해 해결했다. 구현 리뷰와 실제 서비스 성공 경로 증거는 별도다.

## 검증

- root: `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w03/plan-r1-root --tb=short`: **59 passed, 4 skipped, 4 deselected**. 기존 symlink 권한 skip과 ML marker 제외.
- `git diff --check`: 통과. 계획·설계·Canonical 변경 문서와 main_spec의 상대 파일 링크 존재 확인: 누락 없음.
- API/live PostgreSQL/Redis/Linux worker 미실행: 이번 단계는 문서 변경이며 제품 구현은 아직 없다.

## 다음 단계

계획의 독립 점수 95 이상, blocker/important 해결, 작성된 실행 계획의 사용자 검토를 마친 후 주 에이전트가 직접 구현한다. 각 단위 독립 리뷰와 전체 최종 리뷰를 수행한다.
