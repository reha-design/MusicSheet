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
[PENDING]
   │
   ▼
[RUNNING] ───(에러 발생 시)───► [RETRYING] ───(재시도 초과)───► [FAILED]
   │                               ▲
   │ (정상 단계 전이)                │
   │ (DOWNLOAD ➔ ... ➔ RENDER) ─────┘
   │
   ├──(취소 요청 시)──► [CANCEL_REQUESTED] ───► [CANCELED]
   │
   ▼
[COMPLETED]
```

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
