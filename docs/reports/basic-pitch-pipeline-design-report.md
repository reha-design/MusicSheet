# W04 Basic Pitch 제품 파이프라인 설계 착수 보고서

- 날짜: 2026-10-04 (Asia/Seoul)
- 변경 범위: W04 설계 Revision 1, roadmap·backlog·main_spec 색인
- 기준 코드: `84c3a7b`
- 상태: 사용자 서면 설계 검토 대기. 제품 코드·의존성·API·DB·런타임은 변경하지 않았다.

## 산출물

[설계 문서](../superpowers/specs/2026-10-04-basic-pitch-pipeline-design.md)에 Python 3.13 provider → 입력 변환 → Python 3.12 CLI → JSON/MIDI 검사 → 아티팩트 저장 흐름을 작성했다. 명시적 provider 활성화, process 취소·timeout, 부분 저장 정리, 공용 계약 검증과 실제 모델 검증 범위를 포함한다.

작업별 CLI 호출을 추천하고, 변환된 MODEL_INPUT만 받는 방식 및 상주 RPC 서버와 비교했다. 기존 worker의 module entrypoint 부재와 MIDI 생략 가능성, runner가 직전 attempt 출력만 받는 제약을 반영했다. 기본 모델 선정은 W05, 전체 YouTube 실행은 W09다.

## 검토 상태

설계 자체 검토를 완료했다. 서면 설계 승인은 대기 중이다. 독립 실행 계획 리뷰와 구현 리뷰는 미실시이며 점수를 추정하지 않았다. 문서의 동작·검증 기준은 구현할 목표이며 실행 결과가 아니다.

## 검증

- `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w04/design-20261004 --tb=short`: **225 passed, 12 skipped, 4 deselected in 7.01s**.
- skip은 기존 선택적 환경·플랫폼 경로이며, 실제 모델 integration 4개는 기본 marker로 제외됐다. 이번 문서 작업에서 모델·DB·Celery 실제 검증을 다시 실행하지 않았다.
- API와 독립 worker는 제품 변경이 없으므로 이번 문서 작업에서 재실행하지 않았다.
- placeholder 자체 검사에서 미완성 항목 없음. 저장소 오류의 retry 여부와 설정 probe의 시간 제한을 명시해 모호성을 보완했다. `git diff --check`: 통과.

## 다음 단계

사용자가 작성된 설계를 검토한 뒤 실행 계획 작성·독립 리뷰로 진행한다. 구현 시작은 작성된 계획의 사용자 검토와 독립 점수 게이트 통과 후다. W04 전체 완료나 제품 provider 연결 완료로 기록하지 않는다.
