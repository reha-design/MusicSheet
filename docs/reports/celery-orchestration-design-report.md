# W03 Celery 오케스트레이션 설계 착수 보고서

- 날짜: 2026-10-03 (Asia/Seoul)
- 변경 범위: W03 설계 Revision 1, 진행 현황·backlog·main_spec 색인
- 기준 코드: W02 완료 `2d39ed9`
- 상태: 사용자 설계 검토 대기. 제품 코드·API 동작·runtime·DB schema는 변경하지 않았다.

## 산출물과 결정

[설계 문서](../superpowers/specs/2026-10-03-celery-orchestration-design.md)에 DB outbox 기반 등록·단계 전달, CPU/AI 큐, attempt 기록과 실행 소유권, 재시도 한도, 취소 경쟁, 커밋 후 W02 이벤트 발행을 정리했다. 실제 provider는 W04–W08에 연결한다. provider 미설정은 명시적 실패이며 제품 경로에서 테스트 결과를 성공으로 만들지 않는다.

직접 canvas chain 발행과 수동 CLI 전달을 비교하고 outbox 방식을 추천했다. 승인되면 Canonical Celery의 단계 연결 문구·DB v2 사양을 먼저 갱신하고 docs/plans 실행 계획을 작성한다. 독립 계획 리뷰와 단위별 구현 리뷰는 각각 95점 이상이어야 한다.

## 리뷰와 승인 상태

설계 자체 검토에서 stale 실행 결과, bool generation, 예약 없는 메시지, generation 증가, worker 중단의 재시도 한도, DB 장애의 retry 지연을 구체화했다. 독립 실행 계획 리뷰 및 구현 리뷰는 **미실시**이며 점수를 추정하지 않았다. 사용자 설계 승인은 아직 없다.

## 검증

- `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w03/design-20261003-r2 --tb=short`: **59 passed, 4 skipped, 4 deselected**. skip은 기존 Windows symlink 권한 제한이며 ML integration은 기본 marker로 제외됐다.
- 최초 검증은 pytest basetemp 상위 폴더가 없어 35개 fixture 준비 오류가 발생했다. 상위 폴더를 생성하고 새 basetemp로 재실행해 통과했다. 제품 코드는 수정하지 않았다.
- `git diff --check`: 통과. 설계의 TODO/TBD placeholder 없음.
- live PostgreSQL/Redis/Linux Celery worker는 이번 문서 작업에서 실행하지 않았다. API는 제품 변경이 없으므로 이번 문서 작업에서 재실행하지 않았다.

## 다음 단계

사용자가 작성된 설계를 검토한 후 실행 계획 작성·독립 리뷰로 진행한다. 구현 시작은 별도의 작성된 계획 검토와 점수 게이트 통과 후다.
