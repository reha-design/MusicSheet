# W04 Basic Pitch 제품 연결 계획 리뷰 보고서

- 날짜: 2026-10-04 (Asia/Seoul)
- 기준 코드: `ef21c57`
- 변경 범위: 실행 계획 R2, 설계 승인 기록, canonical 목표 계약·현재 상태, 진행 현황·색인
- 상태: 서면 설계 R1 승인. 계획 R2 독립 **99/100** 통과, 사용자 실행 계획 검토·실행 방식 선택 대기. 제품 구현 미착수.

## 실행 계획

[W04 실행 계획](../plans/basic-pitch-pipeline-implementation-plan.md)을 작성했다. 프로세스 수명과 설정, 입력·결과·저장, 제품 provider/factory/runtime, 실제 모델·DB 통합의 네 단위로 나눴다. 단위별 테스트·독립 리뷰·보고서·commit을 정의하고 각 코드 리뷰도 95점 이상일 때만 다음 단위를 진행한다.

Windows 실제 모델 및 PostgreSQL 아티팩트 등록과 Linux의 owned subprocess 검증은 필수로 계획했다. 기본 모델 선택·정확도 benchmark·실제 YouTube 전체 변환·Linux 실제 모델/Celery는 별도 증거와 환경이 필요한 범위다. 현 단계에서 실제 모델 또는 DB 연결이 완료됐다고 기록하지 않는다.

## 독립 계획 리뷰와 처리

Reviewer: `/root/w04_plan_review`, 작성자와 다른 에이전트. 계획·승인 설계·실제 runner/repository/tasks/config/artifacts/common schema/LocalStorage/worker CLI를 대조했다.

- R1 **94/100**: 요구사항24/25, 구조18/20, 순서20/20, 검증23/25, 재현9/10. blocker0, important2, minor2.
- Important1: 직접 tool 종료와 stdout EOF를 분리하지 않으면 출력 통로를 상속한 descendant가 정상 종료를 막을 수 있다. R2는 poll/wait로 완료를 확인하고 nonblocking bounded capture를 사용하며 실제 상속 fixture를 추가했다.
- Important2: group SIGTERM이 gate leader도 종료시켜 소유권 확인이 모호했다. R2는 gate no-op signal handler, descendant 정리 후 leader 종료, 마지막 SIGKILL 이후 재신호 금지, 조기 gate 종료의 명시적 cleanup 실패를 정의했다.
- Minor1: 두 put 성공 이후 provider 반환 전 취소·temp cleanup 실패에서도 두 Ref를 rollback하도록 보완했다.
- Minor2: Linux container 소스 전달·잠금 환경 설치·검증·회수 명령을 추가하고 승인 설계 상태를 실제 승인 기록으로 갱신했다.
- R2 **99/100**: 요구사항25/25, 구조20/20, 순서20/20, 검증24/25, 재현10/10. blocker0, important0, minor1. 독립 reviewer가 R1 지적의 해결과 승인 설계 범위 준수를 확인했다.
- 남은 minor는 유효한 비PCM WAV를 손상으로 오인하지 않고 FFmpeg로 변환하는 IEEE float fixture 보강 권고다. Task2 입력 준비 구현·코드 리뷰에서 확인한다. 미해결 blocker/important가 없는 계획 점수 통과와 사용자 실행 계획 검토는 구분한다.

## 문서 정합성

전사 사양에 W04 목표 입력/출력·검증 경계를 추가했다. 모델 어댑터 사양의 “provider 패키지 없음”, 런타임 사양의 “API/Celery 없음”은 현재 구현 상태로 바로잡았다. 새로운 목표 설정과 provider 연결은 아직 구현 전임을 명시했다. 설계 승인 기록은 2026-10-04 사용자 `다음작업 진행`이다.

## 검증

- `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w04/planning-20261004 --tb=short`: **225 passed, 12 skipped, 4 deselected in 6.14s**.
- skip/제외는 기존 선택적 통합·플랫폼 경로다. 이번 문서 작업에서 API·독립 worker 회귀, 실제 모델·DB·Linux process 검증을 다시 실행하지 않았다. 해당 검증은 향후 구현 단위에 정의됐다.
- `git diff --check`: 통과. 계획의 TODO/TBD/FIXME 미완성 항목 없음. 제품 코드·dependency/lock·API·DB schema를 변경하지 않았다.

## 다음 단계

독립 계획 리뷰 **99/100**, blocker/important0을 확인했다. 작성된 계획을 사용자에게 제시하며 권장 실행은 주 에이전트 구현과 단위별 독립 reviewer 조합이다. 구현 방식 선택과 계획 검토 후 실행을 시작한다. 구현 리뷰 점수는 아직 없다.
