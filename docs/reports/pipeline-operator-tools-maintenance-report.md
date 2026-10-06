# Pipeline 운영 도구 Task2 — 정체 작업 조회·종료

- 날짜: 2026-10-06. base `7e8488256a54160cd2bd409571cf07926c73c593`.
- 사양/계획: [R1 실행 계획](../plans/pipeline-operator-tools-implementation-plan.md), 독립 계획97/100. Task1 독립99점 통과 이후 실행했다.
- 범위: safe observation/latest attempt 계약, bounded scan, 기존 StageSession 잠금·transaction 종료 전이, DB-only CLI/script, canonical spec, stateful fake 및 실제 DB/Redis 검증.
- 상태: 최초 독립94점의 important1을 수정하고 독립 재리뷰 **99/100**, 미해결 지적0으로 통과했다. 구현자가 자체 점수를 부여하지 않는다.

## 동작

조회는 서버 시간 기준 정체된 PENDING/RUNNING/RETRYING/CANCEL_REQUESTED만 반환한다. NULL timestamp를 제외하고 updated_at/id 오름차순으로 bounded 정렬한다. 최신 attempt는 started_at DESC NULLS LAST/id DESC이며 출력은 관측값5개와 stage/attempt/generation/status/error_code 요약으로 제한한다.

종료는 worker와 같은 UUID 기반 advisory lock과 job row lock을 사용한다. 관측 timestamp/status/stage/active id가 달라지거나 최종 상태·없는 작업·최근 활동이면 무변경이다. 취소 요청은 CANCELED, 나머지는 FAILED/WORKER_STALLED로 종료한다. 모든 RUNNING attempt를 닫고 active id를 해제하며 미발행 outbox를 소비하는 작업은 하나의 transaction이다. 완료 이력/아티팩트는 보존하고 기존 메시지는 terminal SKIP된다. Redis publish는 commit 후이며 실패가 DB 결과를 되돌리지 않는다.

CLI는 database만 요구하고 scan에서 Redis 연결을 생성하지 않는다. help는 환경과 연결을 읽지 않는다. UUID/enum/aware timestamp/age/limit를 연결 전 검증한다. connect2초/command5초/Redis2초 및 기존 owned cleanup을 사용한다. exit0 성공,1인프라·중단,2입력·설정,3무변경. 상세 dependency 예외는 노출하지 않는다.

공개 maintenance/session 복구 함수는 실제 commit을 소유하므로 외부 transaction이 없는 idle connection을 요구한다. 활성 transaction은 job 잠금·SQL·event 전에 고정 ValueError로 거부한다. CLI는 새 connection을 열어 이 조건을 충족한다.

## 검증

| 검증 | 결과 |
| --- | --- |
| 최초 RED | 52failed, maintenance/maintenance_cli 모듈 부재 |
| 첫 집중 회귀 | 109pass/4fail. 새 fixture가 허용하지 않는 delay100을 사용해 기존 계약인10초로 수정 |
| Windows 집중 maintenance/CLI/repository/progress | 113pass/1.76초 (최종 경계6개 추가 전) |
| Linux 최종 동일 집중 | **119pass/1.85초** |
| 리뷰 수정 후 Windows/Linux 집중 | **121pass/1.12초**, **121pass/2.11초** |
| Windows root 전체 | **392pass/11skip/14deselected**,12.77초 |
| API 전체 (opt-in URL 미설정) | **232pass/32skip**, 기존 Starlette deprecation warning1 |
| 실제 Windows PostgreSQL16·Redis7 | **7pass/skip0**,2.98초 |
| 실제 Linux PostgreSQL16·Redis7 | **7pass/skip0**,3.26초 |
| 리뷰 수정 후 Windows/Linux 실제 DB·Redis | **8pass/skip0**,3.25초 / **8pass/skip0**,3.70초 |
| 리뷰 수정 후 root/API 전체 | **394pass/11skip/14deselected** / **232pass/33skip** |
| lock check / CLI script | `uv lock --check --offline` exit0; locked offline editable 재설치1개 후 `musicsheet-maintenance --help` exit0 |
| git diff --check | exit0 |

실제 검증은 이 작업이 소유한 임시 PostgreSQL/Redis와 `musicsheet_test`/disposable marker에 한정한다. scan의 eligible/terminal/fresh/NULL filter, sort/limit 및 최신 attempt timestamp/ID 동률·NULL 경계를 확인했다. 두 connection의 worker lock과 관측값4개 변화 거부, 취소 우선, 모든 RUNNING 종료/완료 history·artifact 보존, outbox 소비, terminal SKIP, Redis payload field와 반복 무변경을 확인했다. SQL trigger로 마지막 outbox 쓰기를 실패시키고 DEFERRABLE INITIALLY DEFERRED constraint trigger로 실제 commit을 실패시켜 네 테이블 snapshot의 원상복구와 advisory unlock을 검증했다. 초기 live rollback fixture의 async generator 수집 오류를 수정한 뒤 모두 재실행했다.

fake에서는 commit fault/최종 SQL fault, Redis 장애, CLI의 오류·exit·DB-only·선택 Redis 회수 및 반복 취소에 대한 cleanup drain도 확인했다. 전체 regression의 skip은 opt-in 환경 미설정 및 Windows Linux/symlink 경계이며 성공으로 세지 않았다. 실제 모델/Celery worker 실행이나 전사 정확도 평가를 이번 단위 검증으로 주장하지 않는다. migration/HTTP/task namespace/queue/Redis field 및 의존성 lock은 변경하지 않았다.

## 리뷰 대상 fingerprint (파일 bytes)

| 파일 | SHA256 |
| --- | --- |
| models.py | 636F9CD4D3A9F7798DA82C85590C905BACF71061AB9561FD1038825A9E02FBC0 |
| repository.py | 08B930D4D5479F5A964E68E497764A4B9DBF7D79E34DFE829BC2DD4B90913470 |
| maintenance.py | C203E5CCC2750DC4BCFF19FC6226518FAFF197172FCC9B88F13A659EA17A1749 |
| maintenance_cli.py | B9798ABA268F75BF2C0108A1B18D5DC55F9FB71946C8B26145D8D67F09D9C020 |
| packages/pipeline/pyproject.toml | C0141F06FB9EBC6691EF30722269CB2C30C8FED5B8EA733AED57AE8CDE466A19 |
| test_maintenance.py | A80F0FE199314739685E440CC5264DDA545A0011F4733DD1AA75B7208CD1F526 |
| test_maintenance_cli.py | D7FC5E84A1C447AAB6D08E504E1B5C076BBA4019ED4CDD171E0008641A5D1EB1 |
| support.py | 6B1A59465CA183A819EE9045E059D7ADB9DCF283F064F1F7749200F4666D729D |
| API test_operator_tools.py | AC70BA557F047B4129C958E52E4652DC9065E7C3B7863BA7681D5A55CC9D785F |

root/API lock bytes는 Task1 보고서 baseline과 같고 Git 변경0이다. 줄바꿈에 따라 checkout 후 byte hash는 달라질 수 있으며 리뷰한 범위는 최종 commit으로도 식별한다.

## 독립 리뷰 및 수정

최초 `/root/operator_maintenance_review`,2026-10-06, base7e84882 대비 staged14파일/+887/-4, binary diff SHA256 `2f5f47ed0feb482a43abef2b56eba44bac3ead9470c9a1395a0166ef3238b881`. 독립 **94/100** (23+24+23+15+9), blocker0/important1/minor0로 게이트 미통과했다. 집중119pass 및 실제 DB7pass/skip0를 독립 재실행했다.

Important1: 외부 transaction에서 내부 transaction은 savepoint만 해제하지만 공개 함수가 terminal 이벤트를 발행한다. 실제 DB의 별도 observer는 RUNNING을 보고 이후 outer rollback이 RUNNING을 복원하여 R1 commit 후 event 계약 위반을 재현했다. 공개 maintenance와 session 전이에 idle connection 사전조건을 추가했다. fake2건은 수정 전 RED2fail, 수정 후 GREEN이며 실제 DB 회귀1건은 외부 transaction에서 쓰기·event·job lock 획득이 없고 rollback 후 상태 보존을 확인한다. 이 수정은 R1의 실제 commit 경계를 구현한 것으로 signature/schema/의존성 변경은 없다. canonical 상태 계약과 README에 조건을 기록했다.

최종 `/root/operator_maintenance_review`,2026-10-06, base7e84882 대비 staged15파일/+975/-4, binary diff SHA256 `c20e79ae27868c19f0e19eac4e0e25db600ca3334ec36ab5ba15414b7c5ee841`. 독립 **99/100** (25+25+24+15+10), blocker0/important0/minor0. 집중121pass/0.99초 및 실제 PostgreSQL·Redis8pass/skip0/3.40초를 독립 재실행했다. 별도 real probe에서 public/direct session 외부 transaction 거부·이벤트0·committed RUNNING 보존·advisory unlock과 driver fault 비밀정보 비노출도 확인했다. 위 fingerprint9개는 최종 재리뷰 당시 실제 bytes와 모두 일치한다. ledger/status 변경만 추가한 뒤 commit한다.
