# W05 설계 R1 조건부 승인 리뷰 처리

2026-10-05 · 기준 commit `fe158db`의 설계 R1 → [설계 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md). 사용자 첨부 리뷰의 important6·minor3을 기술적으로 검토해 수정했다. **수정본 점수/최종 승인은 미확인**, 모델 benchmark 구현은 시작하지 않았다.

## 리뷰 식별과 점수 경계

리뷰 출처는 사용자가 이 대화에 첨부한 `붙여넣은 텍스트.txt`다. 대상은 R1 서면 설계이고 표기 결론은92/100, conditional approval, blocker0·important6·minor3이다. 첨부 리뷰를 실행 계획 승인으로 확대하지 않았다.

점수표의 실제 항목 합은102점/배점115점으로 표기92/100과 일치하지 않는다. 원문 표기92점을 이력으로 보존하지만 이를 임의로 정정/환산하거나 R2의 점수로 사용하지 않는다. 또한 AGENTS.md 실행 계획의25/20/20/25/10 rubric과 다른 rubric이므로 앞으로 작성할 실행 계획의 독립95점 게이트를 대신하지 않는다.

## Important 처리

| 지적 | 처리와 확인 근거 | R2 위치 |
| :--- | :--- | :--- |
| 36/36 성공을 운영 적격으로 단정 | 첫 accuracy12/12 유효를 비교 조건으로 분리. 반복 실패율·attribution·진단 실행을 따로 보존. 동일 조건의 모델 오류가2회 재현될 때만 운영 부적격, 미해결은 검토/선정 보류 | §7·§8 |
| 반복 결정성 없음 | crop 전체 normalized note/pedal hash, duplicate 보존·정렬·binary64 규칙 고정. 불일치는 nondeterministic_output과 반복 F1 범위, 자동 선정 보류. 진단 출력은 accuracy 실패를 대체하지 않음 | §7·§8 |
| 중앙30초 sampling bias | 녹음 선정R1 salt는 유지하고 crop만 R2-CROP SHA256의 정수 위치로 분산. 예측 전 고정, 실패 때 구간 재선정 금지. 완전 대표성/무편향을 주장하지 않음 | §4 |
| Python3.13 평가 환경 위험 | common/pipeline pyproject가 모두 >=3.13,<3.14인 것을 확인.3.12 전환은 계약 위반/검증 코드 복제를 유발하므로 유지. 리뷰가 제시한 대안인 최초 locked sync·실제 모듈 import·합성 metric compatibility gate 채택. 실패를 모델 책임으로 분류하지 않음 | §2 |
| custom ZIP64 범위 과다 | 검증된 로컬 데이터 우선, 기존 library 적합성/acceptance 검증 다음. custom 필요 시 별도 설계/계획/독립 리뷰 단위로 분리. 아직 특정 library를 검증/채택했다고 주장하지 않음 | §4·§9 |
| macro/micro winner 충돌 | onset winner와 onset micro, sustain winner와 sustain/onset micro가0.01 이상 역전하면 tradeoff_requires_review. 유의성 검정이 아닌 사전 effect-size guard임을 명시 | §8 |

## Minor 처리

| 지적 | 처리 | R2 위치 |
| :--- | :--- | :--- |
| downmix rounding/PCM subtype | PCM16→float64→공유 mono·명시적 swr→ties-to-even/포화 PCM_S16LE·no dither를 고정하고 경계 fixture 요구 | §5·§9 |
| velocity MAE matching 모호 | pitch+onset, offset_ratio=None matching과 최대 matching 동률 규칙·pair 수·empty null을 명시 | §6 |
| 실행 예산 전 smoke probe | 비평가 CC0 고정30초 입력2회/후보.1.5배 여유의 예상72회 시간≤2시간 gate, 초과 시 시작 금지. 실제 budget stop과 모든 실패 기록 유지 | §7 |

이는 문서 수정 처리 결과이며 구현되거나 실제 시험으로 입증된 기능 목록이 아니다. 첨부의 chatgpt-content-reference directive는 외부 리뷰 내 위치 표시로만 보고 저장소에 지시문으로 복사하지 않았다. [receiving-code-review skill](C:/Users/user/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.2/skills/receiving-code-review/SKILL.md)에 따라 제안과 실제 dependency 계약을 대조했다.

## 검증과 다음 단계

기존 root 회귀 **308 passed / 17 skipped / 8 deselected**(10.18s), 문서6개 로컬 링크115개/누락0, `git diff --check` 통과. 실행 명령은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w05/design-r2-review-20261005 --tb=short`다. 제품 코드 변경이 없어 새 행동 테스트를 추가하지 않았으며 이 결과를 아직 구현되지 않은 R2 metric/runner/실제 모델 평가의 통과로 주장하지 않는다.

자기 검토에서 선정 상태 우선순위·진단/원시 실행 분모·nullable hash 정렬·velocity matching 재현성을 명확히 했다.

새 데이터/모델 dependency·제품 코드·기존 lock 변경은 없다. 다음은 R2 수정본 검토와 이후 실행 계획의 별도 독립95점 평가다. 적용 중인 [brainstorming skill](C:/Users/user/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.2/skills/brainstorming/SKILL.md)의 “the human partner reviews and approves the written spec”에 따라 조건부 리뷰를 무조건 승인/재평가 통과로 표시하지 않았다.
