# Domain Spec: Job State Machine

> **Canonical Owner:** `docs/domain/job-state.md`  
> **관련 문서:** [docs/backend/database.md](../backend/database.md), [docs/architecture/job-pipeline.md](../architecture/job-pipeline.md)

---

## 1. JobStatus vs PipelineStage 분리

작업의 생명주기(Status)와 현재 파이프라인 진행 단계(Stage)를 엄격히 분리한다.

```python
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "PENDING"                    # 큐 대기 중
    RUNNING = "RUNNING"                    # 파이프라인 실행 중
    RETRYING = "RETRYING"                  # 일시적 오류로 재시도 대기 중
    COMPLETED = "COMPLETED"                # 전 과정 성공적 완료
    FAILED = "FAILED"                      # 최대 재시도 초과 또는 복구 불가능한 에러
    CANCEL_REQUESTED = "CANCEL_REQUESTED"  # 사용자 취소 요청 접수 (협력적 취소 대기)
    CANCELED = "CANCELED"                  # 워커가 안전하게 취소 작업을 완료함

class PipelineStage(str, Enum):
    DOWNLOAD = "DOWNLOAD"          # 오디오 다운로드/수신
    PREPROCESS = "PREPROCESS"      # Canonical WAV 및 리샘플링
    SEPARATE = "SEPARATE"          # 음원 분리 및 Solo QC
    TRANSCRIBE = "TRANSCRIBE"      # AMT (노트 이벤트 추출)
    POSTPROCESS = "POSTPROCESS"    # 비트 매핑, 필터링, 스마트 퀀타이즈
    RENDER = "RENDER"              # MusicXML 및 PDF 렌더링
```

---

## 2. 상태 전이 규칙 (Transition Rules)

```text
 PENDING ──► RUNNING ──► COMPLETED
    │           │
    └──────┬────┘
           ▼
    CANCEL_REQUESTED ──(worker observes request)──► CANCELED

 RUNNING ──(retryable error)──► RETRYING ──(retry)──► RUNNING
    │                             │
    │                             └──(cancel request)──┐
    └──(cancel request)────────────────────────────────┤
                                                       ▼
                                                CANCEL_REQUESTED
 RETRYING ──(retry limit exceeded)──► FAILED
```

The API accepts cancellation requests only while a job is `PENDING`, `RUNNING`, or `RETRYING`. The conditional database update cannot replace a terminal state. `CANCEL_REQUESTED` is cooperative: a worker later records `CANCELED`; without a worker, the job remains in the requested state until an operator explicitly finalizes a stale observation.

### 운영자 정체 작업 종료

공개 `fail_stalled`/`StageSession.fail_stalled`는 이 복구 transaction의 commit을 직접 소유하므로 외부 transaction이 없는 idle connection을 요구한다. 활성 transaction은 잠금·쓰기·event 발행 전에 ValueError로 거부한다. CLI는 명령마다 새 connection을 생성해 이 조건을 충족한다.

`musicsheet-maintenance scan`은 서버 시간으로 `updated_at`이 지정 시간 이상 지난 비최종 작업을 조회한다. 기본7200초, 범위1~2147483647초; limit 기본100, 범위1~1000. NULL timestamp는 제외하고 updated_at/id 오름차순으로 정렬한다. 최신 attempt는 started_at DESC NULLS LAST/id DESC로 선택한다. source URL, artifact URI, error_detail은 출력하지 않는다.

`fail-stalled`는 job_id/status/current_stage/updated_at/active_attempt_id의 조회값을 요구한다. 현재 worker와 같은 job advisory lock을 얻고 row lock 안에서 모든 관측값과 서버 기준 정체 시간을 재검사한다. 잠금 경합, 관측값 변화, 최신 활동, 최종 상태 또는 없는 작업은 무변경으로 반환한다. CANCEL_REQUESTED는 CANCELED로, 나머지 비최종 상태는 FAILED/WORKER_STALLED로 종료한다. 모든 RUNNING attempt를 FAILED로 닫고 active id를 해제하며 미발행 outbox에 published_at을 기록한다. 완료 이력과 아티팩트는 보존한다. 이 변경은 한 transaction이며 이미 발행된 메시지는 최종 상태 검사에서 SKIP된다. DB commit 후 기존 Redis terminal event를 발행하고 Redis 장애는 커밋 결과를 되돌리지 않는다.

---

## 3. `stage_attempts` 테이블 (운영 및 장애 분석)

AI 파이프라인의 각 단계별 소요 시간, 실패 원인, 모델 버전을 영구 추적한다.

```sql
CREATE TABLE stage_attempts (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) REFERENCES jobs(id) ON DELETE CASCADE,
    stage VARCHAR(20) NOT NULL,
    attempt INT NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL,      -- 'RUNNING', 'COMPLETED', 'FAILED'
    provider VARCHAR(64),             -- e.g., 'ByteDancePianoAMT', 'Demucs-htdemucs_6s'
    model_version VARCHAR(32),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_ms INT,
    error_code VARCHAR(64),
    error_detail TEXT
);
```
