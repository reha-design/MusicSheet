# Basic Pitch worker 환경 구성 보고서

> **상태:** 구현·검증·독립 코드 리뷰 완료 (96/100)<br>
> **일자:** 2026-09-26<br>
> **구현 계획:** [Basic Pitch 독립 worker 구현 계획](../plans/basic-pitch-isolated-worker-implementation-plan.md)<br>
> **결정:** [ADR 005 — Basic Pitch worker 전용 Python 3.12 예외](../adr/005-basic-pitch-python-312-exception.md)

## 범위와 upstream 고정

- 사용자가 2026-09-26에 승인한 범위에 따라 `services/ml/basic-pitch-worker`만 Python `>=3.12,<3.13`을 사용하는 독립 uv 프로젝트로 구성했다. root backend와 공용 workspace의 Python 3.13 설정은 그대로 유지한다.
- [Basic Pitch PR #201](https://github.com/spotify/basic-pitch/pull/201)의 head commit `049dc8a01a170c2370d7b246ec1c2067e060c3bf`를 확인했다. 패키지 버전은 `0.4.0`이다.
- PR은 확인 시점에 open 상태이고 GitHub review가 등록되지 않았다. commit diff를 직접 확인했으며 `README.md`와 `pyproject.toml`만 변경한다. Python 3.12에서는 TensorFlow 의존성을 제외하고 기본 ONNX Runtime 의존성을 선택하는 수정이다. 이 pin은 PoC 범위에 한정한다.

## 구성

- `.python-version`은 `3.12`이며, worker 전용 `pyproject.toml`, `uv.lock`, `.venv`를 생성했다.
- `basic-pitch`는 전체 SHA `049dc8a01a170c2370d7b246ec1c2067e060c3bf`로 고정했다. worker dependency는 CPU `onnxruntime`, `soundfile`, `setuptools<81`, 개발 그룹의 pytest를 포함한다. `resampy 0.4.2`는 runtime에서 `pkg_resources`를 가져오므로 setuptools 81 미만으로 제한했다. [Setuptools의 pkg_resources 안내](https://setuptools.pypa.io/en/latest/deprecated/pkg_resources.html)를 참고했으며, 호환 가능한 resampy 수정 버전이 허용되면 pin을 재검토한다.
- `provenance.py`에 Basic Pitch 버전/SHA, 모델 파일명, provider id, pedal 지원 여부, confidence 의미를 기록했다.
- TensorFlow와 `musicsheet_common`은 worker dependency에 없으며 import되지 않는지 테스트한다.
- uv가 51개 잠금 후보를 해석했고, Windows Python 3.12 환경에는 43개 배포판을 설치했다. 설치 확인 버전은 Basic Pitch `0.4.0`, ONNX Runtime `1.30.0`, SoundFile `0.14.0`, setuptools `80.10.2`, pytest `9.1.1`이다.

## 검증

worker 디렉터리에서 실행한 결과:

```text
uv sync --locked --project . --python 3.12
Resolved 51 packages; checked 43 installed packages

uv run --project . --python 3.12 pytest -p no:cacheprovider --basetemp=<repo-local-temp> -q
8 passed, 1 warning
```

독립 리뷰는 96/100으로 95점 기준을 통과했다. 리뷰는 pinned commit 및 ONNX/Python 경계, root 환경 격리, inference API import를 확인했다. console entry point 실행 검증은 CLI module을 구현하는 Task 5에서 수행한다.

추가 확인:

- 실제 interpreter는 CPython `3.12.13`이다.
- ONNX Runtime에서 `CPUExecutionProvider`를 사용할 수 있다.
- `basic_pitch.TF_PRESENT`는 `False`, `basic_pitch.ONNX_PRESENT`는 `True`다.
- `basic_pitch.inference.predict`를 import할 수 있다. `resampy`가 사용하는 `pkg_resources` 관련 deprecation warning 1개가 남는다.
- root에서 `uv sync --project .`를 다시 실행한 뒤 worker distribution들이 root 환경에 설치되지 않았음을 확인했다. root `pyproject.toml`과 `uv.lock`도 변경되지 않았다.
- 전체 테스트를 root에서 실행하면 root pytest 설정이 backend 테스트까지 수집한다. worker 전체 테스트는 worker 디렉터리를 현재 작업 경로로 두고 실행한다.

## 현재 PC의 실행 설정

기본 uv cache와 Python discovery 경로가 현재 Windows sandbox에서 접근 거부되어, worker 검증 시 cache와 uv 관리 Python을 저장소의 무시된 임시 경로로 지정했다. CPython `3.12.13`은 `temp/uv-python` 아래에 설치했으며, 기존 사용자 Python shim은 덮어쓰지 않았다. 이 설정은 개발 PC 권한 문제를 우회하기 위한 실행 설정이며 worker 프로젝트 경계에는 포함되지 않는다.

## 남은 검증

이 task는 의존성 경계, ONNX backend 선택, inference API import까지만 확인했다. 22,050 Hz mono piano fixture를 이용한 실제 추론, 결과 JSON 검증, CLI 오류 처리 및 산출물 검증은 후속 task에서 수행한다. pyproject에 console entry point는 선언되어 있지만 CLI module은 Task 5에서 구현하므로 그 전까지 실행할 수 없다. 따라서 이 보고서는 Python 3.12 호환성이나 제품 지원 완료를 주장하지 않는다.
