# Infrastructure Spec: Health Check & Model Prefetch

> **Canonical Owner:** `docs/infrastructure/health-check.md`  
> **관련 문서:** [docs/backend/api.md](../backend/api.md)
>
> **구현 상태:** `/health/live`, `/health/ready`, `/health/detail`은 `services/api`에 구현했습니다. 상세 검증과 제한 사항은 [구현 보고서](../reports/fastapi-health-check-implementation-report.md)를 참고합니다. 모델 프리페치는 별도 목표이며 현재 파일이 없습니다.

---

## 1. 목표 Health Check

| Endpoint | 역할 | 점검 대상 |
| :--- | :--- | :--- |
| `/health/live` | Liveness | API 프로세스 생존 |
| `/health/ready` | Readiness | DB, Redis, 스토리지 등 API 의존성 연결 |
| `/health/detail` | Diagnostic | API 호스트에서 확인한 GPU 보고값, FFmpeg, MuseScore 정보 |

### 1.1 API 동작 계약

- API는 모노레포 안의 독립 uv 프로젝트 `services/api`로 구현하고 Python `>=3.13,<3.14`, 독립 `pyproject.toml`, `uv.lock`, `.venv`를 사용합니다. 공용 스키마와 스토리지는 저장소 내부 패키지를 editable dependency로 소비합니다.
- `GET /health/live`는 프로세스가 요청을 처리할 수 있으면 외부 의존성을 조회하지 않고 HTTP `200`과 `{"status":"ok"}`를 반환합니다.
- `GET /health/ready`는 PostgreSQL `SELECT 1`, 애플리케이션 Redis `PING`, `LOCAL_STORAGE_DIR`의 쓰기·삭제 가능 여부를 제한 시간 안에 확인합니다. 모두 정상이면 HTTP `200`, 하나라도 실패하면 HTTP `503`을 반환하며 JSON에 각 검사 상태를 담습니다.
- 연결 설정은 프로세스 환경의 `DATABASE_URL`, `REDIS_URL`, `LOCAL_STORAGE_DIR`에서 읽습니다. `DATABASE_URL` 또는 `REDIS_URL`이 없거나 유효하지 않으면 해당 검사만 `unavailable`로 처리합니다. `LOCAL_STORAGE_DIR`은 미설정 시 `outputs`를 사용하고 모든 상대 경로를 API 작업 디렉터리 기준으로 해석합니다. 설정 오류나 연결 실패는 API 기동을 막지 않습니다. 기본값 경로를 만들 수 없거나 실제 쓰기가 실패하면 storage 검사를 `unavailable`로 처리합니다.
- Readiness 검사는 API 시작을 막지 않습니다. 각 검사는 실패·시간 초과를 독립적으로 처리하고, 응답에는 비밀값, DSN, 로컬 경로 또는 원시 예외 메시지를 포함하지 않습니다.
- LocalStorage 검사는 설정 경로를 만들 수 있는지 확인한 뒤 해당 디렉터리에서 임시 파일을 생성하고 제거합니다. 업무 artifact나 고정 이름 파일은 만들지 않습니다. 파일시스템 호출은 worker thread에서 수행합니다. 1초 제한을 넘으면 응답은 `unavailable`로 끝나지만, 운영체제 파일 호출 자체는 취소할 수 없으므로 임시 파일은 worker가 실행을 마친 뒤 정리됩니다. 파일 호출이 계속 멈춰 있으면 그동안 worker와 임시 파일이 남을 수 있습니다.
- `GET /health/detail`은 `nvidia-smi`가 보고하는 첫 GPU의 이름·driver version·총/가용 메모리(MB), FFmpeg와 MuseScore 버전을 진단합니다. GPU 진단은 API 호스트의 `nvidia-smi` 보고값이며 PyTorch·CUDA 모델 추론 호환성을 증명하지 않습니다. FFmpeg와 MuseScore도 API 호스트의 실행 파일과 첫 버전 줄을 확인합니다. 워커가 별도 호스트나 컨테이너에서 실행되면 해당 워커의 하드웨어·도구 상태를 이 endpoint가 원격으로 확인하지 않습니다.
- 상세 진단은 누락·실패·시간 초과를 각 도구의 `unavailable` 상태로 반환하되 HTTP `200`을 유지합니다. 진단 결과는 readiness 합격 여부에 영향을 주지 않습니다.
- 상세 진단은 명령별 최대 2초로 제한하고, 전체 검사 결과에는 명령 경로나 표준 오류 전문을 노출하지 않습니다. 실행 파일은 선택 환경 변수 `NVIDIA_SMI_BIN`, `FFMPEG_BIN`, `MUSESCORE_BIN`으로 지정할 수 있으며 기본값은 각각 `nvidia-smi`, `ffmpeg`, `MuseScore4`/`musescore`를 `PATH`에서 검색합니다.
- DB와 Redis 접근은 비동기 클라이언트를 사용합니다. Redis 클라이언트는 애플리케이션 수명 동안 공유하고 종료 시 닫습니다. PostgreSQL은 readiness 검사 때 제한 시간의 짧은 연결로 `SELECT 1`을 수행합니다.

### 1.2 응답 형식

Readiness 성공 예시:

```json
{"status":"ready","checks":{"postgres":"ok","redis":"ok","storage":"ok"}}
```

Readiness 실패 예시:

```json
{"status":"not_ready","checks":{"postgres":"ok","redis":"unavailable","storage":"ok"}}
```

상세 진단은 `gpu`, `ffmpeg`, `musescore`별 상태와 확인 가능한 GPU 이름/driver version/메모리 또는 도구 version 요약만 포함합니다. 환경에서 확인할 수 없는 필드는 `unavailable`로 표현하며, endpoint 자체는 진단 자료를 반환하기 위해 HTTP `200`을 사용합니다.

상세 진단 응답 예시:

```json
{
  "gpu": {
    "status": "ok",
    "name": "NVIDIA GeForce RTX 4060",
    "driver_version": "555.42",
    "memory_total_mb": 8192,
    "memory_free_mb": 4096
  },
  "ffmpeg": {"status": "ok", "version": "ffmpeg version 7.1.1"},
  "musescore": {"status": "unavailable"}
}
```

---

## 2. 목표 모델 프리페치

`scripts/prefetch_models.py`는 설계상 사전 다운로드·checksum 검증용 스크립트이며 현재 파일은 없습니다. 아래 명령은 해당 스크립트가 구현된 뒤에만 실행할 수 있습니다.

```bash
uv run python scripts/prefetch_models.py
```
