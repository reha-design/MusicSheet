# 개발 현황

이 문서는 현재 진행 상태와 바로 이어서 검토할 작업만 기록합니다. 전체 남은 작업은 [backlog.md](backlog.md), 완료 기록은 [completed-work.md](completed-work.md)에서 관리합니다.

## 진행 중

**W05 — 기본 전사 모델 결정**: [서면 설계 R2](superpowers/specs/2026-10-05-transcription-model-evaluation-design.md)와 실행 계획 R3를 사용자 승인받았습니다. Task1/2는 각각 독립 코드100점으로 완료했습니다 ([점수 계산](reports/transcription-evaluation-metrics-report.md), [고정 MAESTRO12개 준비](reports/transcription-evaluation-dataset-report.md)). Task3도 [실행 계획 R7](plans/transcription-model-evaluation-implementation-plan.md) 독립99점·코드 재리뷰100점/미해결 지적0으로 완료했습니다. 격리 ByteDance worker·공식 checkpoint·Windows CPU30초 실제 smoke·1개 실제 opt-in 테스트를 통과했고, 초기94점의 MIDI 의미/다운로드 deadline 지적을 보완했습니다. worker71개·평가기147개 회귀 및 captured smoke 바이트 보존을 확인했습니다 ([Task3 보고서](reports/piano-amt-evaluation-worker-report.md)). Task4 비교 실행·검증 원장·선정 보고서도 계획100점/코드100점으로 완료했습니다 ([Task4 보고서](reports/transcription-evaluation-runner-report.md)). 다음은 Task5 실제 모델 비교·기본 모델 결정이며 아직 수행하지 않았습니다.

## 다음 작업 후보

W05 완료 후 다음 작업 후보는 **W06 — 음원 분리**입니다. 모델 선정 결과를 바탕으로 Demucs 분리와 solo piano bypass를 구현합니다.

작업 시작 시 backlog에서 해당 항목을 제거하고 `진행 중`에 등록합니다. 구현 완료 후에는 [completed-work.md](completed-work.md)에 완료일·결과보고서·리뷰 점수·커밋을 기록하고 이 문서에서 제거합니다. 구현 상세와 검증 결과는 각 작업의 계획서와 결과보고서에만 보관합니다.
