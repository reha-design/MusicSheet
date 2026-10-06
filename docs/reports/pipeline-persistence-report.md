# W03 Task1 — 단계 실행·발행 대기 저장소 보고서

- 날짜: 2026-10-03 (Asia/Seoul), 기준 `ce2c2c6`, branch `codex/celery-orchestration`
- 범위: pipeline 패키지와 실행 계약, migration v2, outbox 등록·복구, 실행 session, 상태/아티팩트/후속 예약 트랜잭션, root/API 의존성·테스트
- 계획: 사용자 실행 승인 후 dependency 충돌을 발견해 R3 독립99점으로 재평가, blocker/important0.
- 구현 독립 리뷰: R1 **87/100** (22+21+20+15+9), 2026-10-03 `/root/w03_persistence_review`, 기준 `ce2c2c6` 이후 Task1 전체. blocker0/important3/minor1. R2 98점(minor1), R3 **99/100** (25+25+24+15+10), blocker0/important0/minor0. R3는 최신 Task1 전체와 취소 전파 회귀를 평가했다. Task1 완료.

## 구현 결과

StageMessage는 UUID·stage·양의 int generation을 검증한다. outbox는 caller transaction 안에서 중복 없이 예약한다. session은 job PostgreSQL advisory lock과 짧은 row-lock transaction을 사용한다. 성공 metadata·attempt 완료·다음 stage 예약·job progress는 하나의 트랜잭션이다. provider 실행 엔진·Celery 앱·API 자동 예약은 아직 연결하지 않았다.

실패와 중단은 stage별 최초 포함3회, 재예약 대기5·10초를 적용한다. 취소는 CANCELED로 확정하며 terminal 또는 다른 active_attempt_id를 늦은 결과가 덮어쓰지 않는다. 완료 attempt의 fingerprint/output IDs로 중복 재실행을 막는다. 연결 소유권 상실 뒤 상태 쓰기를 금지하고 SQL rollback 오류 뒤에도 원래 연결의 advisory lock만 해제한다.

v2는 기존 행을 유지하고 역사 attempt의 generation을 attempt 값으로 채운다. 중복/비양수 attempt는 적용을 중단한다. 기존 명시적 migration CLI로만 적용하며 과거 PENDING을 자동 실행하지 않는다.

## 검증 증거

RED는 신규 패키지 부재, migration `[1] != [1,2]`, `[] != [2]`를 확인했다. 추가 RED로 미취득 lock·같은 연결 재진입·실패 generation 재실행3건, SQL 오류 뒤 lock 잔류1건을 실제 관찰하고 수정했다.

- focused pipeline: 최초59개, 리뷰 수정 후 **64 passed** (`t1-reviewfix-green`); 추가 확인2개는 아래 full run에 포함.
- root 최종: **126 passed,4 skipped,4 deselected** (`t1-minor-green-root`).
- API full 최종: **224 passed,21 skipped,1 existing Starlette warning** (`t1-minor-green-api`); W02 store/SSE 전체 회귀 포함.
- root/API offline lock --check와 git diff --check 통과.
- 신규 실DB4개(v1 보존/중복 rollback/동시 migration/session 경쟁)는 URL unset skip. 기존 PostgreSQL10+Redis7도 skip. 실제 DB SQL와 동시 실행 성공 경로는 미검증이다. DB double은 snapshot rollback과 persistence effect만 모사하며 실SQL 증거를 대신하지 않는다.

## 의존성과 실행 판단

resolver가 API Redis>=8.1.0과 Celery Redis extra의 `<6.5` 충돌을 확인했다. [Kombu 공식 요구사항](https://raw.githubusercontent.com/celery/kombu/v5.6.2/requirements/extras/redis.txt)을 확인하고 설계·계획을 먼저 갱신해 독립99점을 받았다. API/pipeline을 안정 범위 `redis>=6.4.0,<6.5`로 맞춰 **Celery5.6.3/Kombu5.6.2/Redis6.4.0**을 실제 lock/sync했다. extras 제거·override·pre-release·lock 수동 수정 없이 해결했다. 첫 lock은 sandbox socket10013으로 실패해 authorized lock/sync만 escalation했고 승인됐다. Basic Pitch 환경/lock은 변경하지 않았다.

승인 계획의 기존 작업 폴더/전용 branch를 유지하며 명시적 staging한다. unused StageAttempt wrapper 대신 DB row는 저장소 내부에 한정하고 소비자에게 frozen StageInput/PreparedStage/Transition을 제공한다. 이 판단과 TDD 결과는 plan별 실행 ledger에도 기록한다.

## 다음 단위

R1 important3 처리: YouTube DOWNLOAD 입력을 항상 빈 tuple로 고정해 자기 출력이 fingerprint에 포함되지 않게 했다. 중복 및 중단 후 재시도, 업로드 원본 재사용을 검증했다. lock 취득/해제를 소유한 task로 shield·drain하여 반복 취소 후에도 정리하며, 해제 실패는 원래 연결을 종료해 불확실한 lock을 제거한다. 취득/해제 각각 단일·반복 취소4개와 YouTube 중복1개가 RED→GREEN을 확인했다. 기존 v1 스키마 검사는 전용 v1 fixture로 분리하고 나머지 실DB 검사는 v2를 사용한다. minor1의 오래된 테스트 집계/평가 대기 표기는 이 기록으로 갱신했다. 실DB skip 제한은 유지된다.

R2 minor의 busy 진입 실패 cleanup 도중 취소 전파도 RED1→GREEN으로 수정했다. 최신 R3 독립99점 및 blocker/important 없음 확인 후 Task2 provider 실행·무결성 검사·취소 monitor·W02 이벤트 공유로 진행한다.
