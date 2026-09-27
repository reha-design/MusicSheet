# 저장소 및 uv 실행환경 구조 계획서

> **문서 상태:** 구조 결정 확정 — 2026-09-26<br>
> **작성일:** 2026-09-26<br>
> **관련 문서:** [Python 런타임 사양](../infrastructure/runtime.md), [Basic Pitch worker 설계](../superpowers/specs/2026-09-26-basic-pitch-worker-design.md), [공용 아티팩트 계약](../domain/artifacts.md)<br>
> **범위:** Git 저장소와 Python 실행환경의 구조 결정. 코드 이동·패키지 설치·런타임 변경은 이 계획의 검토와 구현 계획 이후에 진행한다.

## 1. 결론

**MusicSheet는 Git 모노레포를 유지하고, 서비스 실행 경계에 따라 독립 uv 프로젝트를 둔다.** Git 저장소와 uv workspace는 서로 다른 선택이다. 한 Git 저장소에서 각 프로젝트가 자기 `pyproject.toml`, `uv.lock`, `.venv`를 가질 수 있다. 그러므로 환경 의존성이 다르다는 이유만으로 Git 저장소까지 나눌 필요는 없다.

초기 목표 구조는 API, backend worker, ML 실행환경의 독립 프로젝트다. 각 서비스가 실제로 생길 때 자체 lockfile과 가상환경을 둔다. 존재하지 않는 서비스를 위해 빈 프로젝트를 미리 만들지는 않는다. API와 backend worker가 나중에 하나의 배포 단위로 정리되면 합치는 선택도 재평가한다. ML 모델은 무조건 하나씩 환경을 갖는 대신, Python·OS·native library·프레임워크·CUDA 조합이 검증된 모델끼리 compatibility group으로 묶는다. **Basic Pitch Python 3.12 + ONNX는 우선 독립 AI 프로젝트의 후보**이며, 기존 설계는 [Basic Pitch worker 설계](../superpowers/specs/2026-09-26-basic-pitch-worker-design.md)를 따른다.

멀티레포는 팀 소유권, 릴리스, 배포 또는 보안 경계까지 독립되어야 할 때 다시 검토한다. 현재 단계에서는 API·worker·스키마를 함께 바꾸기 쉬운 모노레포의 이점이 더 크다.

## 2. 용어와 선택지

| 구조 | Git 저장소 | uv lockfile / 가상환경 | 맞는 상황 | MusicSheet 판단 |
| :--- | :---: | :--- | :--- | :--- |
| uv workspace | 1개 | workspace 단위로 lockfile과 보통 하나의 `.venv` 공유 | 패키지들이 같은 Python 범위와 의존성 해석을 공유할 때 | 현재 기반 코드에는 편리하지만, 다른 Python/native stack을 요구하는 AI 실행환경까지 묶지 않음 |
| 독립 uv 프로젝트 모노레포 | 1개 | 프로젝트별 `pyproject.toml`, `uv.lock`, `.venv` | 코드는 함께 변경하지만 실행환경은 다를 때 | **권장 목표** |
| 멀티레포 | 여러 개 | repo/project별 | 팀·릴리스·배포가 실제로 독립될 때 | 지금은 보류 |

uv workspace는 멤버가 공통 Python 제약과 lockfile을 공유한다. 각 프로젝트를 독립 환경으로 만들려면 uv가 상위 workspace를 자동 탐색해 편입하지 않도록 `uv init --no-workspace`로 생성한다. 같은 저장소 안의 로컬 패키지를 의존성으로 추가할 때도 workspace 멤버가 되지 않도록 `uv add --no-workspace`를 사용한다. [uv workspace 문서](https://docs.astral.sh/uv/concepts/projects/workspaces/) · [uv CLI reference](https://docs.astral.sh/uv/reference/cli/)

## 3. MusicSheet 현황과 호환성 제약

- 루트 `pyproject.toml`은 Python `>=3.13,<3.14` uv workspace이며, `packages/common`과 `packages/storage`를 멤버로 포함한다.
- `packages/common`과 `packages/storage`도 현재 `>=3.13,<3.14`를 요구한다. 두 패키지는 Python 3.13 backend 프로젝트에서만 현재 설정 그대로 사용할 수 있다.
- API, Celery worker, ML 모델 실행 모듈은 아직 구현되지 않았다. 따라서 지금 모든 서비스 디렉터리와 가상환경을 만들면 실행 코드 없이 관리 대상만 늘어난다.
- Python 3.12 Basic Pitch worker는 공용 스키마를 직접 import할 수 없다. 프로세스 경계에서 versioned JSON/파일 계약을 주고받고, Python 3.13 backend가 `packages/common` 스키마로 결과를 검증한다. `common`의 Python 제약을 낮추려면 별도 호환성 검증과 결정이 필요하다.
- 기존 Python 3.12 통합 보고서와 승인된 ADR 004의 차이는 worker 설계에서 다뤘다. 이 계획은 그 보고서를 현재 AI 호환성의 재현 증거로 간주하지 않는다.

## 4. 목표 디렉터리 예시

아래는 한 저장소 안에서 서비스별 환경을 관리하는 **목표 예시**다. 각 프로젝트는 실제 서비스 구현 시점에 추가한다. `services/ml/`은 독립 uv 프로젝트 또는 여러 호환성 그룹을 담는 디렉터리일 수 있으며, 그 자체가 하나의 공유 환경일 필요는 없다.

```text
musicsheet/                         # Git repository (monorepo)
├── services/
│   ├── api/                        # API 프로젝트, 자체 uv.lock/.venv
│   ├── worker/                     # 오케스트레이션 프로젝트, 자체 uv 환경
│   └── ml/
│       ├── basic-pitch-worker/     # Python 3.12 + ONNX 후보, 독립 환경
│       └── <compatible-group>/     # 검증된 조합이 생길 때만 추가
├── packages/
│   ├── common/                     # 도메인 스키마/계약 패키지
│   └── storage/                    # backend 저장소 패키지
├── docs/
└── tools/                          # 필요 시 repo-wide 검증 도구
```

환경 구분은 다음 원칙을 따른다.

| 실행 단위 | 계획 런타임 | 환경 경계 |
| :--- | :--- | :--- |
| API/backend | Python 3.13 | 공용 Pydantic schema와 backend 의존성 |
| orchestration worker | Python 3.13 우선 | 실제 서비스 경계로 구현되면 자체 프로젝트를 기본으로 함; 하나의 backend 배포 단위로 합쳐질 때만 API와 환경 통합을 재검토 |
| Basic Pitch worker | Python 3.12 후보 | ONNX 의존성 및 Basic Pitch 호환성 PoC용 독립 프로젝트 |
| ByteDance 등 추가 모델 | 미정 | 실제 검증 후 기존 AI compatibility group에 합치거나 새 프로젝트 생성 |

**프로젝트 개수는 레포 개수와 같을 필요가 없다.** 각 실행 단위가 별도 버전·의존성·배포를 요구할 때에만 자체 환경을 준다.

## 5. `common` 및 로컬 패키지 의존성

Python 3.13 서비스는 monorepo 내부 패키지를 개발 중 editable path dependency로 사용할 수 있다. 예를 들어 `services/api`에서 `packages/common`까지 상대 경로를 기준으로 연결한다.

```toml
[tool.uv.sources]
musicsheet-common = { path = "../../packages/common", editable = true }
```

동일한 연결은 프로젝트 디렉터리에서 다음처럼 추가할 수 있다. `--no-workspace`는 로컬 경로 패키지가 상위 workspace 멤버가 되지 않게 한다.

```powershell
cd services/api
uv add --editable --no-workspace ../../packages/common
```

현재 `packages/common`은 Python `>=3.13,<3.14`이므로 Python 3.12 ML 프로젝트에서 위 경로를 재사용하면 안 된다. ML worker와 backend 사이에는 versioned JSON/Artifact 계약을 사용한다. 공용 라이브러리를 낮은 Python 버전에서도 쓰려는 결정은 별도 검증 후에만 한다. 배포 시 로컬 path dependency를 계속 쓰려면 서비스 빌드 컨텍스트에 `packages/common`을 포함해야 한다. 모노레포 밖에서 독립 배포하게 되면 wheel/registry 배포 등 별도 공급 방식을 선택한다.

## 6. 단계별 전환 계획

### 단계 0 — 현재 작업공간 유지

- Git 모노레포와 기존 Python 3.13 workspace를 유지한다.
- `packages/common`과 `packages/storage`는 기존 테스트/개발 흐름이 실제로 유지되는 동안 workspace에서 사용한다.
- Basic Pitch 별도 프로젝트 제안은 루트 lockfile을 오염시키지 않는 첫 runtime 예외로 다룬다. Python 3.12 환경은 실 PoC와 ADR 005 승인 전까지 지원 완료로 기록하지 않는다.

### 단계 1 — 서비스가 구현될 때 프로젝트 경계 지정

- API 또는 backend worker 구현 시작 시 의존성·Python 제약·실행/배포 단위를 확인한다.
- API와 orchestration worker가 독립 프로세스·서비스로 구현되면 각각 자체 uv 프로젝트로 만든다. 두 구성요소가 하나의 배포/운영 단위로 확정되면 환경을 공유할지 비교한다.
- ML 모델은 지원 Python, Windows/Linux wheel, native library, PyTorch/TensorFlow/ONNX 및 CUDA provider 조합을 확인한 후 호환성 그룹을 정한다.
- 각 독립 프로젝트는 `uv init --no-workspace`, 자체 `pyproject.toml`, `uv.lock`, `.venv`로 관리한다. 의존성 동기화·검증 명령은 `uv --project <path> ...`처럼 프로젝트를 명시해 실행한다.

### 단계 2 — workspace 해체 필요성 재평가

- 독립 API/worker 프로젝트가 실제 생성되어 각각의 lock과 venv를 쓰고, common/storage의 path dependency 및 전체 테스트 명령이 재현되면 루트 uv workspace를 제거할지 결정한다.
- root `pyproject.toml`을 제거하거나 repo-wide tooling 프로젝트로 바꾸기 전에, baseline 테스트·schema 패키지·CI/사용 명령을 어디서 실행할지 결정한다.
- workspace를 해체해도 Git monorepo는 유지한다. 독립 프로젝트 간 lockfile은 각 서비스의 dependency graph를 관리한다.

### 단계 3 — 멀티레포 조건 확인

다음 조건 가운데 지속적인 요구가 생겼을 때만 저장소 분리를 제안한다.

- 서로 다른 팀이 각 repo를 소유하고 독립적으로 변경·리뷰한다.
- API/worker/ML의 배포 및 릴리스 주기가 지속적으로 분리되어 있다.
- `common`을 버전 패키지로 배포하고 소비자가 명시적으로 버전을 고정해야 한다.
- 접근 권한·보안·라이선스 요구가 repo 단위 분리를 필요로 한다.

조건이 확인되면 Git dependency/tag 또는 package registry를 포함한 버전 정책, 호환성 규칙 및 마이그레이션 비용을 비교한다. 해당 조건이 없으면 monorepo를 유지한다.

## 7. 확정 결정 및 구현 연결

사용자 확인에 따라 아래 방향을 확정한다.

1. Git monorepo를 유지하고, 실제 실행 경계에 따라 독립 uv 프로젝트를 둔다.
2. 현재 root workspace는 바로 해체하지 않는다. Basic Pitch 및 향후 서비스가 실제 구현될 때 별도 프로젝트를 추가한다.
3. Python 3.12 ML worker는 Python 3.13 `common`을 import하지 않고 versioned JSON 계약을 사용한다.
4. API와 orchestration worker의 환경은 서비스/배포 경계가 확인된 시점에 결정한다. 빈 프로젝트는 미리 만들지 않는다.

첫 실행 단위의 구체적 절차는 [Basic Pitch 독립 worker 구현 계획](./basic-pitch-isolated-worker-implementation-plan.md)을 따른다. Python 3.12 예외는 ADR 005의 명시 승인 후에만 worker 제품 코드로 진행한다. 이 구조 확정 자체는 ADR 005 승인이나 Basic Pitch의 호환성 검증 완료를 뜻하지 않는다. 멀티레포 분리와 root uv workspace 제거는 해당 전환 조건이 실제로 생겼을 때 별도 검토한다.
