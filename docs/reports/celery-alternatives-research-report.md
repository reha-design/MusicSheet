# Celery 대체 라이브러리 조사 — MusicSheet

- 조사일: 2026-10-04, Asia/Seoul.
- 범위: 공식 문서·릴리스·의존성 선언과 현재 W03 코드의 비교. 라이브러리 설치·교체·실 broker 시험은 수행하지 않았다.
- 결론: **교체 후보를 하나 먼저 검증한다면 Dramatiq**, 비동기 실행 구조를 우선한다면 **Taskiq + RedisStreamBroker**가 비교 대상이다. 아래 추천과 변경 비용은 조사자의 판단이며 구현 계획/코드 독립 리뷰 점수가 아니다.

## 현재 구조에서 필요한 기능

MusicSheet는 Celery의 chain/chord/result backend로 파이프라인 상태를 관리하지 않는다. PostgreSQL outbox와 repository가 단계 순서·3회 provider attempt·5/10초 예약·멱등성·취소를 관리하고, `run_stage`는 async 함수다. Celery는 전달·worker 실행·인프라 재시도 경계를 맡는다.

따라서 비교 기준은 세 큐의 CPU I/O·GPU AI·render 분리, JSON 메시지, DB 커밋 이후 ACK, worker 강제 종료 후 재전달, broker 장애 중 메시지 보존, task별 자원 정리와 Python3.13 지원이다. 큐 라이브러리의 retry는 DB가 관리하는 provider attempt와 분리해야 한다. 동일 상태를 두 엔진에서 관리하면 재시도 횟수와 취소가 어긋날 수 있다.

근거 코드: [Celery factory](../../packages/pipeline/musicsheet_pipeline/celery_app.py), [dispatcher](../../packages/pipeline/musicsheet_pipeline/dispatcher.py), [runtime adapter](../../packages/pipeline/musicsheet_pipeline/tasks.py), [runner](../../packages/pipeline/musicsheet_pipeline/runner.py).

## 후보 비교

| 후보 | 공식 지원 기능 | MusicSheet에서의 핵심 확인 사항 | 변경 비용 판단 |
| --- | --- | --- | --- |
| **Dramatiq** | Redis/RabbitMQ broker, actor별 retry/backoff, 큐별 실행, middleware | 기존 동기 adapter 방식 재사용 가능. thread/process 동시성, 장시간 AI 실행, infrastructure retry 발행 실패의 ACK 여부 검증 | 중간; 직접 교체 우선 후보 |
| **Taskiq + taskiq-redis** | async task, retry middleware, Redis Streams ACK, ACK 시점 선택, worker 동시성 설정 | async runner와 잘 맞음. Stream broker의 pending reclaim과 장시간 task idle 설정, 자원 scope를 검증해야 함 | 중간; 비동기 우선 후보 |
| **RQ** | Redis 작업 큐, retry, stop command, 여러 큐, SpawnWorker | 표준 worker의 job 실행 격리와 모델 초기화 비용. abandoned job은 FailedJobRegistry로 이동하므로 현재 재전달 계약을 별도 맞춰야 함 | 중간; 단순 운영 대안 |
| **Huey** | 가벼운 task queue, 여러 storage, retry/schedule, process/thread 실행 | 중단된 실행이 기본적으로 유실될 수 있어 DB 기반 복구 보강 필요. async runner에는 동기 wrapper 필요 | 중간~높음; 현재 장애 복구 요구에는 후순위 |
| **arq** | asyncio + Redis, Retry/defer, worker 종료 시 작업 재실행, abort | 유지보수 전용 상태이고 Redis client 상한이 더 낮음 | 중간; 신규 전환 우선 후보에서 제외 |
| **Temporal Python SDK** | Workflow/Activity/Worker, 취소·timeout·versioning | Temporal Service 또는 Cloud와 workflow 설계가 추가됨. 기존 DB 상태 머신과 권한/역할을 다시 설계해야 함 | 높음; 장기 workflow 요구가 커질 때 검토 |

각 기능의 근거: [Dramatiq guide](https://dramatiq.io/guide.html), [Taskiq middleware](https://taskiq-python.github.io/available-components/middlewares.html), [Taskiq worker/ACK](https://taskiq-python.github.io/guide/cli.html), [RQ retries/abandoned jobs](https://python-rq.org/docs/exceptions/), [RQ workers](https://python-rq.org/docs/workers/), [Huey guide](https://huey.readthedocs.io/en/latest/guide.html), [Huey recipes](https://huey.readthedocs.io/en/latest/recipes.html), [arq retry/abort](https://arq-docs.helpmanual.io/), [Temporal Python guide](https://docs.temporal.io/develop/python).

## Redis 클라이언트 버전 제약

여기서 버전은 Redis 서버가 아니라 Python client인 redis-py다. 선언된 범위에 8.1이 포함되는 것과 실제 장애 복구가 검증되는 것은 별개다.

| 확인한 버전/소스 | redis-py 제약 | 8.1.0에 대한 판단 |
| --- | --- | --- |
| 현재 Celery5.6.3 / Kombu5.6.2 | Kombu extra `>=4.5.2,<6.5` (특정 구버전 제외) | 현재 조합에서는 불가 |
| Dramatiq2.2.1 released tag | `>=4.0,<9.0` | 선언상 허용; 실제 조합 시험 필요 |
| taskiq-redis1.2.4 released tag | `>=8.0.0,<9`, Taskiq `>=0.13.0` | 선언상 허용; 현재6.4 floor/upper bound 갱신 필요 |
| RQ 공식 master metadata | `>=5.0.1` | 상한 없음. 채택할 release metadata/lock을 추가 확인해야 함 |
| arq0.28.0 released tag | `redis[hiredis]>=4.2.0,<6` | 불가; 현재6.4와도 충돌 |

근거: [Kombu5.6.2](https://raw.githubusercontent.com/celery/kombu/v5.6.2/requirements/extras/redis.txt), [Dramatiq2.2.1 setup](https://raw.githubusercontent.com/Bogdanp/dramatiq/v2.2.1/setup.py), [taskiq-redis1.2.4 metadata](https://raw.githubusercontent.com/taskiq-python/taskiq-redis/1.2.4/pyproject.toml), [RQ master metadata](https://raw.githubusercontent.com/rq/rq/master/pyproject.toml), [arq0.28.0 metadata](https://raw.githubusercontent.com/python-arq/arq/v0.28.0/pyproject.toml).

PyPI에서 확인한 현재 릴리스는 [Dramatiq2.2.1](https://pypi.org/project/dramatiq/), [Taskiq0.13.0](https://pypi.org/project/taskiq/), [taskiq-redis1.2.4](https://pypi.org/project/taskiq-redis/), [RQ2.12.0](https://pypi.org/project/rq/)다. 배포되지 않은 master의 선언은 release 검증으로 대신 사용하지 않는다.

## Taskiq에서 특히 확인할 경계

공식 [taskiq-redis README](https://github.com/taskiq-python/taskiq-redis)는 PubSub/ListQueue broker가 ACK를 지원하지 않고 worker가 처리 중 종료되면 메시지가 유실될 수 있다고 설명한다. MusicSheet 후보는 **RedisStreamBroker**로 한정한다.

[1.2.4 Redis broker 소스](https://raw.githubusercontent.com/taskiq-python/taskiq-redis/1.2.4/taskiq_redis/redis_broker.py)를 읽으면 `listen()`이 새 메시지를 못 받았을 때 `continue`하고, pending `XAUTOCLAIM`은 새 메시지를 처리한 뒤 수행한다. **소스상으로는 다른 새 메시지가 없는 큐에서 orphan pending 복구가 지연될 가능성이 있다.** 실제 재현은 하지 않았으며, ACK 지원만으로 Celery의 worker-loss 재전달과 동등하다고 판단하지 않는다.

또한 같은 소스의 기본 pending idle 기준은10분이며 reclaim lock timeout 기본은 None이다. 현재 provider timeout30분과 맞추지 않으면 정상 장시간 실행을 재수거하거나, 강제 종료한 reclaimer가 잠금을 남길 수 있다. idle/lease/lock expiry와 worker kill을 함께 검증해야 한다. 수정 또는 별도 reclaimer가 필요하다면 변경 범위와 운영 비용에 포함한다.

CPU 연산은 async event loop를 막지 않도록 격리한다. [Taskiq CLI](https://taskiq-python.github.io/guide/cli.html)는 sync 함수에 thread pool을 기본 사용하고 CPU 작업에 process pool 선택을 안내한다. [timeout 설명](https://taskiq-python.github.io/guide/getting-started.html#timeouts)은 sync 함수에 TimeoutError가 나도 실제 연산이 계속될 수 있음을 밝힌다. 현재 Python3.12 Basic Pitch subprocess 경계와 협력적 취소를 유지하는 쪽을 우선 검토한다.

## 보존할 부분과 교체할 부분

- **보존 가능:** PostgreSQL migration/repository/outbox, `StageMessage`, artifact 무결성 검사, async `run_stage`, API 최초 예약, SSE 이벤트 store. 이것은 현재 코드 경계에 근거한 판단이다.
- **교체 필요:** Celery 앱·task decorator·CLI, `CeleryPublisher`, Celery Retry/Reject adapter, 설정 및 의존성/lock, worker 운영 명령, 실제 worker harness.
- **재설계 필요:** 재시도 발행 실패 때 원본 메시지 보존, DB 커밋 뒤 ACK, broker result와 DB 상태의 역할, 정상 실행 중 pending 재수거 방지, worker/thread/process 종료 및 GPU 동시성.

## 전환 검증의 합격 조건

교체 구현 전 별도 설계/실행 계획과 독립95점 게이트가 필요하다. 아래는 검증 후보이며 승인된 전환 계획은 아니다.

1. Python3.13에서 후보·redis-py8.1의 정확한 release 조합을 resolver로 확인하고 root/API lock을 재현한다.
2. 정상6단계, 중복 전달, 두 worker lock 경쟁, cancel/complete race에서 기존 DB·아티팩트 결과를 유지한다.
3. 실행 중 worker group SIGKILL 후 **추가 작업을 발행하지 않아도** 미완료 메시지가 정해진 시간 안에 복구되는지 확인한다.
4. broker cut 중 retry 발행 실패 및 outbox publish후 DB commit 실패에서 메시지가 사라지지 않고 중복도 안전한지 확인한다.
5. 장시간 AI 실행이 lease/idle 기준을 넘겨도 불필요한 반복 실행을 막고, 실제 모델 subprocess 취소·종료를 관찰한다.
6. DB 완료 이후 ACK 이전 종료·이벤트 발행 실패를 유도하고 committed stage 재연산·terminal 상태 역전이 없는지 확인한다.
7. worker 강제 종료·반복 취소에서 DB 연결, Redis pool, 소유 process group·threads가 정리되는지 확인한다.

## 추천 판단

**Dramatiq를 첫 교체 실험 대상으로 추천한다.** 현재 필요한 Redis 작업 전달·재시도 경계와 비교하기 쉽고 released metadata가 redis-py8.1을 허용한다. 모델 실행 동시성과 ACK/재전달은 시험을 통과해야 한다. [Dramatiq interrupt 문서](https://dramatiq.io/advanced.html)는 thread interrupt가 GIL 및 system call 제약을 받는다고 명시하므로 강제 AI 중단을 자동 보장한다고 보지 않는다.

**Taskiq는 비동기 구조를 단순화하려는 경우의 비교 후보**다. async runner를 직접 호출할 수 있고 최신 client 범위가 명확하지만, 위 RedisStreamBroker 복구 경계를 먼저 해결/검증해야 한다. 이 확인 없이 새 큐 기능을 운영 성공으로 간주하지 않는다.

arq는 [공식 README](https://github.com/python-arq/arq)에 유지보수 전용 상태가 명시돼 있고 `<6` 제약도 있으므로 최신 Redis client 제약 해소를 위한 선택으로 추천하지 않는다. Huey의 중단 작업 복구 추가 비용과 Temporal의 별도 서비스·workflow 이관 비용을 고려하면 현재 W03 직접 교체 후보에서는 후순위다.

라이브러리별 성능·GPU 처리량·운영 비용을 실측하지 않았다. 비교표의 추천/변경 비용은 기능과 현재 코드 구조에 근거한 평가이며, benchmark나 운영 안정성 인증으로 해석하지 않는다. 이번 조사에서는 제품 동작과 dependencies/lock을 변경하지 않았다.
