# FastAPI 헬스 체크 구현 보고서

> **문서 번호:** REPORT-20260927-14
> **작성 일자:** 2026-09-27
> **프로젝트:** MusicSheet
> **구현 상태:** 단계별 검증 및 전체 변경 독립 리뷰 완료

---

## 1. 변경 개요

`services/api`에 루트 uv workspace와 독립된 Python 3.13 FastAPI 프로젝트를 추가했습니다. API는 공용 스키마와 LocalStorage를 저장소 내부 editable dependency로 사용하고 자체 `pyproject.toml`, `uv.lock`, `.venv`를 유지합니다. 루트 `pyproject.toml`과 `uv.lock`은 변경하지 않았습니다.

구현된 endpoint:

| Endpoint | 동작 |
| :--- | :--- |
| `GET /health/live` | 외부 의존성을 조회하지 않고 HTTP 200 `{"status":"ok"}` 반환 |
| `GET /health/ready` | PostgreSQL `SELECT 1`, Redis `PING`, LocalStorage 임시 쓰기·삭제를 동시에 확인. 모두 정상일 때 200, 하나라도 불가하면 503 |
| `GET /health/detail` | GPU·FFmpeg·MuseScore 진단을 부분 결과로 반환. 도구가 없거나 실패해도 HTTP 200 유지 |

Readiness는 각 검사를 1초로 제한하며 검사 상태 외의 DSN, 비밀값, 경로, 예외 문자열을 반환하지 않습니다. Redis 클라이언트 하나를 API lifespan 동안 공유하고 종료할 때 닫습니다. Storage 검사는 `LOCAL_STORAGE_DIR`을 만들고 무작위 임시 파일을 같은 위치에 썼다가 삭제합니다. 기본 디렉터리는 `outputs`이며 상대 경로는 API 프로세스의 작업 디렉터리 기준입니다. 파일시스템 작업은 worker thread에서 수행되므로 timeout 이후 운영체제 호출을 강제 취소할 수 없습니다. 보통은 worker가 끝난 뒤 임시 파일을 삭제하지만 파일 호출이 계속 멈춰 있으면 worker와 파일이 그동안 남을 수 있습니다.

상세 진단은 `nvidia-smi`, FFmpeg, MuseScore를 API 호스트에서 최대 2초씩 실행합니다. GPU 결과는 첫 장치의 이름, driver version, 총/가용 메모리(MB)입니다. 진단은 API 호스트 정보를 보여주며 분리 배포된 worker의 상태를 원격 확인하지 않습니다. `nvidia-smi`가 GPU를 보고해도 PyTorch/CUDA 추론 호환성을 증명하지 않습니다.

## 2. 실행 및 의존성

| 구성요소 | 버전 |
| :--- | :--- |
| Python | 3.13.7 |
| uv | 0.10.11 |
| FastAPI | 0.141.1 |
| asyncpg | 0.31.0 |
| redis-py | 8.1.0 |
| Uvicorn | 0.54.0 |
| pytest | 9.1.1 |
| Starlette TestClient | Starlette 1.7.0, httpx 0.28.1 |

설치·실행 지침과 PowerShell 예제는 [services/api/README.md](../../services/api/README.md)에 있습니다. API 전용 lock은 `services/api/uv.lock`에 기록되어 있습니다.

## 3. 검증 결과

| 검증 | 명령 | 결과 |
| :--- | :--- | :--- |
| API lock 일치 | `uv lock --check` (`services/api`) | 통과, 27 packages resolved |
| API 동기화 | `uv sync --locked --python 3.13` (`services/api`) | 통과 |
| API 전체 테스트 | `uv run --project . --python 3.13 pytest -q` (`services/api`) | 30 passed |
| 저장소 전체 테스트 | `uv run --project . pytest -q` (저장소 루트) | 54 passed, 3 skipped, 4 deselected |
| 공백·충돌 검사 | `git diff --check` | 통과 |
| Root lock 경계 | `pyproject.toml`, `uv.lock` diff 확인 | 변경 없음 |

테스트는 TestClient와 주입된 가짜 의존성을 사용해 세 endpoint의 경로·상태 코드·응답, 설정 누락/오류, 시간 초과, 임시 파일 정리, 비밀값 비노출 및 진단 실패와 readiness 독립성을 확인합니다. 실제 PostgreSQL·Redis·GPU·렌더러 설치는 테스트에 필요하지 않습니다.

현재 Starlette TestClient는 계획에 따라 설치한 `httpx` fallback을 사용하면서 deprecation warning 1건을 출력합니다. 테스트는 통과하며 API 런타임 의존성에는 영향을 주지 않습니다. Starlette가 안내한 `httpx2` 전환은 낮은 우선순위의 개발 의존성 정리 항목입니다.

Compose 기반 수동 readiness 확인은 실행하지 못했습니다. `docker compose -f docker/docker-compose.yml ps`가 Docker Desktop Linux Engine의 named pipe를 찾을 수 없어 실패했습니다. 자동 검증은 외부 서비스 없이 통과했습니다.

## 4. 점수 게이트 기록

계획 revision 4는 구현 전 독립 리뷰 **97/100**을 받았습니다. 계획과 구현 점수 기준은 [AGENTS.md](../../AGENTS.md)에 있으며, 각 구현 단위 점수는 다음과 같습니다.

| 구현 단위 | 독립 코드 리뷰 | blocker/important | 상태 |
| :--- | ---: | :---: | :--- |
| Task 1: 독립 API 프로젝트·liveness·설정 | 98/100 | 없음 | 통과 |
| Task 2: readiness 검사 | 99/100 | 없음 | 통과 |
| Task 3: host diagnostics | 99/100 | 없음 | 통과 |
| Task 4: 문서·최종 통합 | 98/100 | 없음 | 통과 |

구현 단위별 리뷰는 minor 제안을 테스트나 문서 보강으로 처리한 뒤 재리뷰를 받았습니다. 전체 변경 최종 리뷰는 98/100이며 blocker, important, minor 지적 없이 통과했습니다.

## 5. 남은 범위와 제한

- `/health/detail`은 API 호스트의 도구만 조회합니다. 별도 worker 호스트의 진단 상태를 모으는 원격 health 계약은 포함하지 않습니다.
- 실제 Docker Compose 서비스에 대한 readiness 요청은 Docker 데몬을 사용할 수 없어 확인하지 못했습니다.
- Job REST/SSE, Celery 실행 흐름, 모델 inference, 악보 렌더링 및 모델 prefetch는 별도 작업입니다.
