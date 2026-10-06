# PR #11 기능 통합·브랜치 정리

2026-10-06 · base main `1b3a1e3fab426f8456ef9de630547b8fae315e4d` · 구현 branch `codex/pipeline-operator-tools`.

상태: 계획 독립97점·Task1/Task2/전체 구현 각각 독립99점으로 구현·검증 완료. GitHub 통합과 소유 환경 정리 단계다. 열린 PR 개수로 작업 완료를 판정하지 않는다.

## 통합 범위와 기존 PR 처리

PR [#11](https://github.com/reha-design/MusicSheet/pull/11)의 head는 `2bc50a12ea704dd6580fcd7827b03602b2d71337`, 공통 조상은 `148040c333d797492ef74611b2a860c1eda8ac2a`다. 검토 당시 main 전용27개/PR 전용19개 commit, 원래 PR 변경49파일이며 PR은 OPEN/CONFLICTING이었다. 현재 main과의 통합 준비도 독립 리뷰64/100(Critical1/Important3)은 원래 W03 점수와 다른 평가다.

| PR #11 기능/차이 | 최종 구현의 처리 |
| --- | --- |
| Redis/SSE | 현재 공용 event store의 `payload`, SSE `progress`/`stream_error` 계약 유지 |
| Celery start_job/chain, API 등록 후 직접 broker 발행 | main의 `pipeline.tasks.*`, generation, 원자적 등록+outbox와 여섯 단계 실행 사용 |
| 같은 migration v2에 다른 컬럼 | main v1/v2를 유지하고 새 migration/컬럼 없이 구현 |
| stage별 SHA 잠금 | 기존 worker와 동일한 UUID 첫8바이트 기반 job advisory lock 재사용 |
| 단계 내부 progress | 현재 StageContext optional callback, active attempt/stage/generation 증가 전이와 commit 후 직렬화 event 발행으로 구현 |
| 정체 작업 scan/fail-stalled | bounded scan과 관측값5개, nonblocking job lock+row lock, atomic job/attempt/outbox 종료로 구현 |
| CELERY_VISIBILITY_TIMEOUT 노출 | 선택 후보로 보류. 현재 broker/result/app 세 설정3600 일관성 유지 |
| 손상 Redis entry 건너뛰기 | 선택 계약 대안으로 보류. 기존 오류 응답 계약 유지 |
| 이전 W04 설계/계획 | 원본 이력을 보존하고 현재 main의 승인 W04 Basic Pitch 구현·독립 실행 계약 사용 |

최초64점 지적은 별도 실행 구조의 병합을 배제하고 위 migration/task/event/lock 경계를 현재 구조에 맞추어 해소했다. 위 두 고유 기능의 구현은 [R1 설계](../superpowers/specs/2026-10-06-pipeline-operator-tools-design.md)와 [실행 계획](../plans/pipeline-operator-tools-implementation-plan.md)의 독립97점 게이트 이후 수행했다. W05 모델 비교는 이번 범위에서 수행하지 않았다.

## 보존과 복구

원본 PR의 전체 이력을 로컬 `outputs/reviews/pr11-redis-streams-sse-2bc50a1.bundle`로 보존했다. `git bundle verify`는 완전한 이력 및 원래 ref/head를 확인했다. SHA256 `339B6B1927EFE1C4CE68783E5960B410FDD2233EE581A5170FF8D5F8C8FFDBEE`다. 원본 감사 기록은 `outputs/reviews/pr11-integration-audit-20261006.md`에 있으며 이 보고서가 Git에 보존되는 기능별 처리 기록이다. bundle/audit는 outputs ignore 규칙에 따라 로컬 산출물이다.

필요하면 `git clone outputs/reviews/pr11-redis-streams-sse-2bc50a1.bundle <복구 폴더>`로 원본 이력을 별도 checkout에서 읽을 수 있다. bundle은 remote-tracking ref를 담으므로 기본 branch가 자동 선택되지 않으면 `git switch --detach 2bc50a12ea704dd6580fcd7827b03602b2d71337`로 원래 head를 선택한다. 기존 PR/원격 branch 정리는 새 구현의 병합·보존을 확인한 뒤 수행한다.

## 검증과 환경

| 검증 | 최종 결과 |
| --- | --- |
| Windows root | 394pass/11skip/14deselected |
| Windows API (opt-in URL 미설정) | 232pass/33skip, 기존 deprecation warning1 |
| Windows/Linux 변경 코드 집중 | maintenance/CLI/repository/progress121pass 각각 |
| Windows 실제 DB·Redis | operator tool8pass/skip0 |
| Linux 실제 DB·Redis | operator tool8pass/skip0 |
| lock/script/diff | root lock check exit0, 실제 새 CLI help exit0, diff whitespace exit0 |

Task1 최초23fail, Task2 최초52fail에서 구현 부재를 확인했고 이후 경계·취소·ownership·rollback을 검증했다. 정확한 단위 검증과 reviewer 범위/hash는 [progress report](pipeline-operator-tools-progress-report.md), [maintenance report](pipeline-operator-tools-maintenance-report.md)에 있다. 이번 실행을 실제 Celery prefork worker 검증·실제 모델 재추론·정확도 비교로 확대하지 않는다. 기존 [Celery live report](celery-live-verification-report.md)와 [W04 실제 모델 연결 report](basic-pitch-pipeline-implementation-report.md)는 별도 증거다.

Windows는 사용자 개발 환경의 경로·cleanup·기존 회귀를, Linux는 운영 실행 환경의 async/잠금·DB/Redis 계약을 확인한다. 이번 Linux 확인은 변경 코드와 실제 DB suite이며 root 전체 동일 건수를 주장하지 않는다. Windows11skip은 opt-in DB2, Linux 경계4, symlink5이며 API33skip은 별도로 실행한 실제 operator8건과 기존 DB/Redis25건의 환경 opt-in이다.

소유한 임시 환경은 `musicsheet-operator-{pg,redis,linux}-8f5fdc13` 및 network `musicsheet-operator-8f5fdc13`다. PostgreSQL16 host65504, Redis7-alpine host65513 DB2를 사용하고 `musicsheet_test`/`MUSICSHEET_DISPOSABLE_TEST_DB_V1` marker를 쓰기 전 확인했다. 다른 container `study_postgres`는 변경하지 않았다.

- Python3.13 Linux image ID `sha256:5024f48ba9441d4b13a95d3945abc6365538e3a31109833367a1923523c6efed`.
- PostgreSQL image ID `sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`.
- Redis image ID `sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99`.
- Linux는 repository read-only mount와 정확한 기존 API environment의 비workspace package39개를 사용했다. requirements snapshot `outputs/.verification-operator-tools/requirements-linux.txt` SHA256 `E62ED682A00A8C984ED13A9B61190B9D7D8C68DDF9A3FC6AEEFC539FF9143786`. Celery5.6.3/Kombu5.6.2/redis-client6.4.0/asyncpg0.31.0 유지. root/API/model/eval 환경의 의존성 변경 없음.

재현 명령(root/API는 Windows 및 기존 uv environment):

```text
uv run --project . --offline --no-sync --python 3.13 pytest tests -q -ra -m "not ml_integration and not celery_integration" -p no:cacheprovider
uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests -q -ra -p no:cacheprovider
# owned disposable DB/Redis URL을 MUSICSHEET_TEST_DATABASE_URL / MUSICSHEET_TEST_REDIS_URL로 설정
uv run --project services/api --offline --no-sync --python 3.13 pytest services/api/tests/integration/test_operator_tools.py -q -p no:cacheprovider
uv lock --check --offline
uv run --project . --offline --no-sync --python 3.13 musicsheet-maintenance --help
```

Linux 집중은 `docker exec`의 PYTHONPATH를 `/repo/packages/common:/repo/packages/storage:/repo/packages/pipeline:/repo/services/api/src`, PYTHONDONTWRITEBYTECODE=1로 설정하고 working directory `/repo`에서 `python -m pytest tests/pipeline/test_maintenance.py tests/pipeline/test_maintenance_cli.py tests/pipeline/test_repository.py tests/pipeline/test_progress.py -q -p no:cacheprovider --basetemp=/tmp/operator-t2-reviewed`를 실행했다. 실제 API suite는 같은 명령 환경에서 test path를 operator integration으로 바꾸고 DB/Redis URL host를 소유 container 이름으로 설정했다.

## 게이트 및 마무리 기록

- 계획 R1: 독립97/100, blocker0/important0.
- Task1: 독립99/100, 미해결 지적0, commit `7e8488256a54160cd2bd409571cf07926c73c593`.
- Task2: 독립99/100, 미해결 지적0, commit `26d50283dc0e9c768440cbe15be33d3935d5a347`.
- Task2 최초94점의 important1(outer transaction savepoint 후 terminal event 발행)은 idle connection 사전조건 및 fake2/실DB1 회귀로 수정했다. 외부 transaction 거부는 원래 R1 actual commit 후 발행을 강제한다. reviewer가 집중121pass·실DB8pass 및 별도 direct session/driver fault probe를 독립 재실행해99점으로 재평가했다.
- 전체 독립 리뷰: `/root/operator_final_integration_review`,2026-10-06, **99/100** (25+25+24+15+10), blocker0/important0/minor0. base1b3a1e3 → HEAD26d5028 + staged문서5개,24파일/+1596/-9. 전체 binary diff SHA256 `88c179f9f92b5ebd249b6b0c41458c99f211da8123fed6be178a2b3da06ad07d`, staged문서diff `16ba5aafe8d4b810d9571815c3f3ebc36a642b99e7c2a4df80334f83244d298d`.
- 독립 전체 검증: 집중149pass (직접 Python2.80초 및 uv offline/no-sync/no-cache2.62초), 실제 operator8pass/skip0/3.29초. 동일 job의 scan→worker progress→LOCK_HELD→OBSERVATION_CHANGED→취소 재조회→CANCELED commit/event→outbox소비→늦은 delivery/progress SKIP probe를 통과하고 소유 job/연결을 회수했다. migration/HTTP/task/queue/event 구현과 uv lock4개 변경0을 확인했다.
- 최종 리뷰 당시 통합 보고서 SHA256 `41F230ED5D4E04BBDCE993549DCA72C636C14C7B5A00257B0E925A1A24CB2AC4`, 실행 계획 `542930D0804230ED7852C663FFD24D104C7AC2FBA8904D2B853D8CE68E8B729F`, 설계R1 `4A74C4DCCE868C19E91D60D71DBC319F36CB039143EF1E376B6C8B68A9715D18`. 이후 변경은 평가/상태 ledger 및 완료 색인이다.
- 새 PR 생성·병합, main sync, 기존 PR11 close/원격 branch 삭제, 소유 환경 정리: 대기.
