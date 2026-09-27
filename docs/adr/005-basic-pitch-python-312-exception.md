# ADR 005: Basic Pitch worker 전용 Python 3.12 예외

> **상태:** 승인됨 (Accepted) — 2026-09-26 PoC smoke 검증 통과; 제품 기본 provider 승격은 별도 결정<br>
> **작성일:** 2026-09-26<br>
> **승인일:** 2026-09-26<br>
> **승인 근거:** 사용자가 제안된 worker 단독 Python 3.12 + CPU ONNX PoC 범위를 확인한 뒤 “다음과정 진행”을 지시함.<br>
> **관련 결정:** [ADR 004 — Python 3.13 단일 표준 런타임](./004-python-313-runtime.md)<br>
> **관련 설계:** [Basic Pitch worker 설계](../superpowers/specs/2026-09-26-basic-pitch-worker-design.md)<br>
> **구현 계획:** [Basic Pitch 독립 worker 구현 계획](../plans/basic-pitch-isolated-worker-implementation-plan.md)

## 배경

ADR 004는 현재 backend와 공용 workspace의 표준 런타임을 Python `>=3.13,<3.14`로 정하고 Python 3.12를 프로젝트 지원 범위에서 제외했다. Basic Pitch의 upstream 설치 메타데이터는 Python 3.12를 공식 지원하지 않지만, upstream PR [#201](https://github.com/spotify/basic-pitch/pull/201)은 Python 3.12에서 ONNX 경로를 선택하도록 바꾸는 제안이다. PR 작성자의 설치·추론 결과는 MusicSheet PC에서 재현한 증거가 아니다.

저장소 구조 계획은 Git 모노레포를 유지하되, Python/native dependency 조합이 다른 실행 단위에는 독립 uv 프로젝트를 두기로 확정했다. 이에 따라 Basic Pitch의 호환성을 시험하려면 root Python 3.13 workspace와 분리된 환경이 필요하다. 이 제안은 Python 3.12를 프로젝트 공통 런타임으로 되돌리려는 것이 아니다.

## 제안 결정

1. 예외 대상은 `services/ml/basic-pitch-worker` 한 곳으로 제한하고 Python `>=3.12,<3.13`을 사용한다.
2. worker는 `uv init --no-workspace` 기반의 독립 `pyproject.toml`, `uv.lock`, `.venv`를 가진다. root workspace, root lockfile, `packages/common`, `packages/storage`의 Python 제약은 변경하지 않는다.
3. 검증 경로는 Basic Pitch `0.4.0`의 PR #201 head commit `049dc8a01a170c2370d7b246ec1c2067e060c3bf`와 ONNX Runtime CPU provider로 고정한다. TensorFlow, GPU provider, PyTorch 재구현은 이 예외의 범위에 포함하지 않는다.
4. 현재 pin에서 `resampy 0.4.2`가 실행 중 `pkg_resources`를 import하므로 worker는 `setuptools<81`을 별도 의존성으로 고정한다. [Setuptools 문서](https://setuptools.pypa.io/en/latest/deprecated/pkg_resources.html)는 `pkg_resources` 제거 일정을 안내한다. Basic Pitch가 호환되는 resampy 수정 버전을 허용하면 이 우회 pin을 재검토한다.
5. worker는 Python 3.13 전용 `packages/common`을 설치하거나 import하지 않는다. 프로세스 경계에서 schema version 1 JSON을 기록하며 backend가 `TranscriptionResult`로 검증한다.
6. 사용자가 2026-09-26에 제한된 런타임 예외와 PoC 범위를 승인했다. 이 승인은 좁은 런타임 예외와 검증 범위에 대한 승인일 뿐, Basic Pitch를 기본 provider로 승격하거나 제품 호환성을 보증하는 승인이 아니다.

## Upstream commit 확인

2026-09-26에 [PR #201](https://github.com/spotify/basic-pitch/pull/201)의 head commit을 `049dc8a01a170c2370d7b246ec1c2067e060c3bf`로 확인하고 변경 diff를 검토했다. PR은 아직 open 상태이며 GitHub에 review는 등록되어 있지 않다. diff는 README와 `pyproject.toml`만 변경하며, Basic Pitch `0.4.0`에서 Python 3.12의 기본 backend로 `onnxruntime`을 선택하고 TensorFlow 의존성은 Python 3.12 미만으로 제한한다. 이 commit pin은 승인된 PoC 범위에서만 사용한다.

## 승인 및 PoC 완료 기준

사용자가 2026-09-26에 이 제한적 예외와 실험 범위를 승인했으며 ADR 상태를 `Accepted`로 갱신했다. 이 승인은 **Basic Pitch 호환성 PoC를 구현·실행할 권한**을 부여한다. 설치나 추론 성공을 미리 보증하지 않는다. 아래 항목은 PoC 구현 이후 완료 여부를 판정하는 검증 기준이다.

- PR #201의 변경 내용과 전체 40자리 commit SHA를 위에 기록했다. PoC lockfile과 provenance metadata가 이 ONNX/Python 3.12 변경과 일치해야 한다.
- Windows 개발 PC에서 독립 lockfile을 재현한다. worker는 Python 3.12와 CPU `onnxruntime`을 사용하고 TensorFlow 및 `musicsheet_common`을 설치하지 않아야 한다.
- 사용권과 SHA-256을 기록한 22,050 Hz mono piano fixture로 실제 추론한다. 결과 JSON은 Python 3.13 `TranscriptionResult`에서 검증되고, note event가 유효해야 한다.
- 입력 오류, 추론 오류, 직렬화/기록 오류가 각각 정의한 CLI 종료 코드로 나타나며 실패 실행은 부분 산출물을 게시하지 않아야 한다.
- 실행 명령, OS/Python/uv/package 버전, commit SHA, 실제 ONNX provider, 추론시간과 결과를 작업 보고서에 기록한다.

위 조건을 통과하기 전에는 Python 3.12 Basic Pitch 경로를 지원 완료로 표시하지 않는다. PoC가 실패하면 worker를 지원 대상으로 채택하지 않고 ADR 예외를 철회하거나 대체 AMT 경로를 검토한다. PoC 통과 후에도 제품 기본 provider 승격은 별도 결정으로 남는다.

## 결과와 재검토

승인되면 root workspace는 Python 3.13으로 유지되고 Basic Pitch worker만 별도 환경에서 운용한다. 모노레포 코드 변경은 함께 리뷰할 수 있지만, 런타임·lockfile·가상환경은 분리된다. JSON 경계는 양쪽 Python 런타임 사이의 명시적 호환 계약이 된다.

다음 상황에서 이 예외를 재검토한다.

- Basic Pitch가 Python 3.12를 공식 지원하거나 PR #201의 변경이 upstream 릴리스에 포함된다.
- 설치나 실제 ONNX 추론이 재현되지 않거나 CPU 성능이 요구를 충족하지 않는다.
- 공용 계약 또는 backend 런타임이 바뀌어 별도 프로젝트의 필요성이 달라진다.

검증 실패 시 예외를 철회하거나 대체 AMT 경로를 검토한다. Python 3.12 예외를 이유로 ADR 004의 공통 런타임 결정을 암묵적으로 변경하지 않는다.
