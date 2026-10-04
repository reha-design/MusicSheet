# W05 전사 모델 평가 실행 계획 리뷰

2026-10-05 · 기준 `7ecfd90` · [사용자 승인 설계 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md) · [실행 계획](../plans/transcription-model-evaluation-implementation-plan.md). 상태: 실행 계획 R3 독립100점 통과, 서면 계획 사용자 검토/실행 확인 대기. 제품 구현 미시작.

## 작성한 실행 단위

Task1 평가 환경·MIDI reference·metric, Task2 고정 데이터 취득/manifest/오디오, Task3 독립 ByteDance worker/checkpoint, Task4 반복 실행/ledger/결정성/선정, Task5 실제 CPU 비교/최종 검증이다. 각 단위에 파일·producer/consumer signature·실패 테스트·명령·합격 기준·독립 코드 리뷰 게이트와 커밋을 지정했다.

최초 evaluator sync/import 실패는 모델 실패와 구분한다. Python 표준 zipfile의 ZIP64 지원과 HTTPX streaming을 우선 검증해 새로운 ZIP64 parser를 범위에서 제외했다 ([Python 공식 문서](https://docs.python.org/3.13/library/zipfile.html), [HTTPX 공식 문서](https://www.python-httpx.org/quickstart/)). 공식 문서의 지원 설명은 취득 acceptance test 통과를 대신하지 않는다. ByteDance Python3.12/PyTorch2.10.0 CPU 조합은 독립 호환 probe 목표이며 설치·safe checkpoint load·실제 실행 후에만 성공을 주장한다 ([PyTorch 배포](https://pypi.org/project/torch/2.10.0/)).

새 evaluator/model 프로젝트를 생성하거나 dependencies·dataset/checkpoint를 설치/취득하지 않았다. root/API/기존 Basic Pitch pyproject·lock 및 제품 동작은 변경하지 않았다. 현재 feature checkout에서 주 에이전트가 구현하고 각 단위 독립 reviewer를 두는 기존 방식을 권장한다.

## 독립 계획 리뷰

AGENTS.md가 요구하는 작성자와 다른 `/root/w05_plan_review`가 2026-10-05에 독립 평가했다. 루브릭은 요구25·범위20·순서20·검증25·재현10이며95점 이상/미해결 blocker·important0이어야 한다. 사용자 설계의 조건부92점은 별도 기록이며 이 계획 점수로 사용하지 않았다.

| 계획 | 요구 /25 | 범위 /20 | 순서 /20 | 검증 /25 | 재현 /10 | 총점 | 미해결 blocker/important/minor |
|---|---:|---:|---:|---:|---:|---:|---|
| R1 (정정) | 25 | 18 | 19 | 23 | 9 | 94 | 0/1/2 |
| R2 | 25 | 20 | 20 | 24 | 10 | 99 | 0/0/1 |
| **R3** | **25** | **20** | **20** | **25** | **10** | **100** | **0/0/0** |

R1 지적과 처리: `uv --project`가 cwd를 바꾸지 않으므로 모든 독립 프로젝트 pytest 명령에 config와 전체 tests 경로를 지정했다. velocity 매칭 pair/정렬 입력 및 오디오 준비 receipt/hash의 producer·consumer 계약도 추가했다. salt의 문자 `\\n`이라는 지적은 원문 byte에 단일 backslash가 있음을 확인하고 reviewer가 철회했다. 이에 따라 최초92점은94점으로 정정되었으며, R1은 여전히95점 미만이라 구현하지 않았다. R2의 fixture 경로 prefix 누락 minor는 R3에서 전체 상대 경로로 보완했다.

R3의 실제 리뷰 SHA256은 `24FBD8B1B7A3CF2F0620E6657FB01C63220876EF6F8BFC2AAB8BF52FBF789335`다. Reviewer가 전체 계획을 다시 읽고 골든 해시/선정 순서를 표준 라이브러리로 확인했다. 리뷰 기록 추가 전 본문 hash이며 요구사항 변경은 없다. 버전별 hash와 처리 결과는 실행 계획 마지막 절에도 보존했다. 구현 시 각 단위의 코드 리뷰95점 게이트는 별도로 적용한다.

## 검증·승인 경계

root 문서 회귀는 **308 passed /17 skipped /8 deselected, 12.27초**다. 실행 명령은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w05/planning-20261005 --tb=short`이며, 새 workspace basetemp를 사용했다. 최종 변경6개 문서의 로컬 링크120개는 누락0, `git diff --check`는 통과했다. 이는 문서 변경의 회귀 검증이며 실제 ML 비교 성공을 의미하지 않는다.

[writing-plans skill](C:/Users/user/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.2/skills/writing-plans/SKILL.md)의 “wait for that review before implementation”에 따라 완성된 계획을 사용자에게 제시하고 구현 전에 실행 확인을 받는다. 서면 설계 승인을 아직 존재하지 않았던 실행 계획 승인으로 확장하지 않는다.
