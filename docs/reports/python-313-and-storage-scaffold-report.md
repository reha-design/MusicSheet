# Python 3.13 런타임 전환 및 스토리지 패키지 기반 구현 보고서

> **문서 번호:** REPORT-20260926-01  
> **작성 일자:** 2026-09-26  
> **프로젝트:** MusicSheet (AI Audio-to-Score Transcription Pipeline)  
> **검증 상태:** 30 passed, 1 skipped (100% 통과)

---

## 1. 변경 개요

1. **Python 3.13 단일 표준 런타임 전환 (ADR 004):**
   - 개발 환경의 시스템 런타임(CPython 3.13.7)에 맞춰 프로젝트 표준 런타임을 Python 3.13으로 상향 조정했습니다.
   - 루트 및 패키지 `pyproject.toml`, `.python-version`, `uv.lock`, 관련 가이드/아키텍처 문서 및 ADR을 일괄 동기화했습니다.
   - ADR 004(`docs/adr/004-python-313-runtime.md`)를 신설하여 3.13 채택 사유와 향후 AI provider 의존성 호환성 범위를 명문화했습니다.

2. **스토리지 패키지 스캐폴딩 및 안전한 경로 해석 구현 (Step 0 & Step 1):**
   - `packages/storage/` 패키지 스캐폴딩 및 워크스페이스 연동을 완료했습니다.
   - `ArtifactStorage(ABC)` 공통 인터페이스(`put`, `open_read`, `exists`, `materialize`)를 정의했습니다.
   - `LocalStorage` 어댑터의 `__init__`, `_resolve_job_dir`, `_resolve_file_path`를 구현했습니다.
   - 디렉터리 자동 생성(`outputs/{job_id}/`)과 경로 순회 공격(`..`, 절대 경로, 드라이브 문자, null byte, symlink 탈출)에 대한 보안 검증을 적용했습니다.

---

## 2. 변경 파일 목록

| 파일 경로 | 작업 내용 |
| :--- | :--- |
| `docs/adr/004-python-313-runtime.md` | Python 3.13 표준 런타임 채택 ADR 신설 |
| `docs/adr/001-python-runtime.md` | ADR 004에 의해 대체됨 명시 |
| `docs/plans/local-storage-implementation-plan.md` | LocalStorage 단계별 점진적 구현 계획서 추가 |
| `packages/storage/pyproject.toml` | `musicsheet-storage` 패키지 메타데이터 정의 |
| `packages/storage/musicsheet_storage/__init__.py` | 패키지 공개 인터페이스 노출 |
| `packages/storage/musicsheet_storage/base.py` | `ArtifactStorage` 추상 베이스 클래스 정의 |
| `packages/storage/musicsheet_storage/local.py` | `LocalStorage` 초기화 및 보안 경로 해석 구현 |
| `tests/unit/test_storage.py` | 스토리지 인터페이스 및 경로 보안 단위 테스트 추가 |
| `tests/test_project_baseline.py` | Python 3.13 런타임 및 워크스페이스 패키지 버전 일관성 테스트 갱신 |
| `pyproject.toml`, `packages/common/pyproject.toml` | Python 3.13 제약 및 스토리지 워크스페이스 멤버 등록 |
| `uv.lock`, `.python-version` | 3.13 락파일 및 가상환경 버전 동기화 |
| `README.md`, `docs/main_spec.md`, `docs/roadmap.md`, `docs/infrastructure/runtime.md`, `docs/architecture/system.md` | Python 3.13 및 스토리지 구현 현황 반영 |

---

## 3. 검증 결과

- **테스트 명령:** `uv run pytest`
- **테스트 결과:** `30 passed, 1 skipped in 0.37s`
- **주요 검증 항목:**
  - Python 3.13 런타임 및 워크스페이스 패키지 의존성 일치 검증 (`test_project_baseline.py`)
  - `ArtifactStorage` 추상 메서드 규격 및 인스턴스화 차단 검증 (`test_storage.py`)
  - 로컬 스토리지 job 디렉터리 자동 생성 및 격리 검증
  - 상대 경로(`..`), 절대 경로, 윈도우 드라이브 경로, symlink 탈출 차단 보안 검증
