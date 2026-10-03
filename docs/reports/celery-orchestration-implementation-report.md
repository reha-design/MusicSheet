# W03 Celery 오케스트레이션 구현 통합 보고서

- 기간: 2026-10-03~2026-10-04 (Asia/Seoul), branch `codex/celery-orchestration`
- 설계 승인 `w03진행`, 실행 승인 `다음 task 진행`.
- 현재: Task1~4 각 독립99점, Task4 검증 harness·운영 문서 단위 게이트 통과. 전체 리뷰 대기.

## 결과와 증거 제한

등록·단계 예약이 PostgreSQL 상태와 원자적으로 연결되고, dispatcher가 여섯 Celery task와 CPU I/O·AI·render 큐로 전달한다. job advisory lock, active attempt fencing, fingerprint 및 output reference 재사용, stage별3회 provider attempt,5·10초 durable retry와 협력적 취소를 구현했다. DB 커밋 뒤 공유 W02 이벤트 store가 SSE 상태를 전달하며 Redis 실패는 DB 결과를 되돌리지 않는다. 제품 registry는 비어 있다. 실제 YouTube/AI/렌더 provider는 W04 이후이며 end-to-end 주소 검증은 후속 W09 범위다.

실행 환경 root/API 각각 Python3.13.7, uv0.10.11, Celery5.6.3/Kombu5.6.2/Redis6.4.0. Basic Pitch Python3.12 환경/lock은 변경하지 않았다. 기존 Redis8.1 제약과 Kombu `<6.5` 충돌은 계획 R3 독립 재평가 후 공통 안정 범위로 해결했다.

Task4는 opt-in 실SQL 검사와 Linux prefork concurrency2 worker process suite를 추가했다. startup ping·API health, 실제 SSE 읽기, 정상6단계·한 번 retry·중복·동시 lock 경쟁·kill/redelivery·실행 중 cancel·발행후 commit 실패·broker proxy cut/recovery를 코드로 마련했다. test-only provider는 임시 실제 파일을 만들며 앱 factory로만 주입한다. root는 API를 import하지 않고 API uv 환경의 소유한 subprocess를 사용한다.

현재 Windows 호스트이며 live PostgreSQL/Redis URLs가 unset이다. **실 SQL 성공·실제 broker ACK/requeue·Linux kill/redelivery·실 SSE+worker 통합 성공은 실행하지 못했다.** 단위/eager 통과와 opt-in 코드 작성은 이 성공 증거를 대체하지 않는다. 공유 Redis/DB/WSL/Docker는 설치·기동하지 않았다. 실제 운영 visibility3600초와 test5초는 다르다.

namespace와 UUID jobs, 소유 process groups만 정리한다. root는 schema reset/migration하지 않고 이름·comment·version2를 확인한다. API 실DB suite의 reset은 기존 marked disposable guard를 따른다. 명령과 ACL·순서·제한은 [pipeline README](../../packages/pipeline/README.md)에 기록했다. 강제중단할 수 없는 OS read와 cooperative provider, orphan files, at-least-once 전달 및 event loss 제한도 설명했다.

## 계획·단위 리뷰

| 범위/버전 | 독립 reviewer·평가일 | 점수 | 지적과 처리 |
| --- | --- | --- | --- |
| 계획R1/R2/R3 | w03_plan_review ·2026-10-03 | 94→100→99 | 취소 dispatcher enum·동기 validation/thread·API live 경계·target·Redis 안정제약 및 문서상태 해결 |
| Task1 R1/R2/R3, base ce2c2c6 | w03_persistence_review ·2026-10-03 | 87→98→99 | YouTube 자기 출력 fingerprint, 취득/해제 중 취소 lock 누수, v1 exact schema fixture, cleanup 취소 전파; RED→GREEN |
| Task2 R1/R2, base83915c7 | w03_runner_review ·2026-10-03 | 94→99 | 실제 파일 InterruptedError와 내부 stop 분리, 고정 이벤트 경고; RED→GREEN |
| Task3 R1/R2, base1d9898f | w03_dispatch_review ·2026-10-03 | 92→99 | send_task optional backend 선호출 제외, API와 worker tilde 경로 일치; RED→GREEN |
| Task4 R1, base60e1f24 | w03_live_review ·2026-10-04 | 24+23+22+15+10 = **94** | important2: 부모 종료 뒤 자식 group 정리 누락, Windows SIGKILL 회귀 실패. 종료 부모·잔존 자식 RED 확인 후 session identity 검증/잔존 group 종료 및 portable signal9 주입으로 수정. R2 해결 확인 |
| Task4 R2, base60e1f24 | w03_live_review ·2026-10-04 | **99** (25+25+24+15+10) | important2 해결 확인, blocker0/important0/minor0. 독립 helper8/root219/API232 및 locks/diff 통과 |
| W03 전체, base2d39ed9 | 대기 | 미평가 | 필수 지적0·95점 이상 게이트 예정 |

단위99점은 각각25+25+24+15+10이다. 실서비스 검증 증거 부족의1점 감점은 필수 코드 지적이 아니며 각 단위 blocker/important/minor0으로 종료했다. 상세 증거는 [Task1](pipeline-persistence-report.md), [Task2](pipeline-stage-runner-report.md), [Task3](celery-dispatch-api-report.md)에 있다.

## Task4 검증

도구 helper 부재 RED, repository root 경로 RED, broker prefix를 transport connection에 반영하는 경계 검증을 수행했다. 반복 취소 중 cleanup과 raw primary 예외 context가 같이 노출되는 RED를 관찰해 공유 owned cleanup cancellation에 `from None`을 추가했다. thread/socket observer·프로세스·Redis·DB cleanup은 별도 owned task로 drain하며 primary 오류를 고정 note로 보존한다. configured invalid URL의 subprocess fail에서 secret sentinel/traceback 비노출도 확인했다. Task4 R1 지적2개를 수정해 helper8개 통과, full root **219 passed/12 skipped/4 deselected** (`t4-r2-root`), API **232 passed/25 skipped/기존 Starlette warning1** (`t4-r2-api`), root/API offline lock check 및 diff check 통과. root skip은 기존 symlink4+새 Linuxworker8, API skip은 PostgreSQL18+Redis7이다. Task4 R2 독립99점으로 통과했고, 전체 W03 리뷰는 별도 진행한다.

브랜치/폴더 유지, 명시적 staging과 원자적 commits. push/PR/merge는 하지 않는다. W04 provider 구현이 다음 기능 단위다.
