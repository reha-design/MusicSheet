# 개발 현황

이 문서는 현재 진행 상태와 바로 이어서 검토할 작업만 기록합니다. 전체 남은 작업은 [backlog.md](backlog.md), 완료 기록은 [completed-work.md](completed-work.md)에서 관리합니다.

## 진행 중

**PR #11 기능 통합**: [실행 계획](plans/pipeline-operator-tools-implementation-plan.md) R1 독립97점 통과. 단계 진행률 및 운영자 멈춘 작업 조회·종료를 현재 pipeline 구조에 통합하고 기존 PR/브랜치를 정리합니다. W05 작업은 이후 이어갑니다.

**W05 — 기본 전사 모델 결정**: [서면 설계 R2](superpowers/specs/2026-10-05-transcription-model-evaluation-design.md)와 실행 계획 R3를 사용자 승인받았습니다. 코드 리뷰에서 보완한 [실행 계획 R5](plans/transcription-model-evaluation-implementation-plan.md)는 독립100점입니다. Task1 평가 환경·MIDI 정답·점수 계산은62개 테스트와 코드 독립100점으로 완료했습니다 ([Task1 보고서](reports/transcription-evaluation-metrics-report.md)). Task2의 실제 고정 MAESTRO12개·오디오·manifest 준비는128개 테스트·독립 코드100점으로 완료했습니다 ([Task2 보고서](reports/transcription-evaluation-dataset-report.md)). Task3 ByteDance worker·checkpoint가 다음이고, 실제 모델 비교·기본 모델 결정은 아직 수행하지 않았습니다.

## 다음 작업 후보

W05 완료 후 다음 작업 후보는 **W06 — 음원 분리**입니다. 모델 선정 결과를 바탕으로 Demucs 분리와 solo piano bypass를 구현합니다.

작업 시작 시 backlog에서 해당 항목을 제거하고 `진행 중`에 등록합니다. 구현 완료 후에는 [completed-work.md](completed-work.md)에 완료일·결과보고서·리뷰 점수·커밋을 기록하고 이 문서에서 제거합니다. 구현 상세와 검증 결과는 각 작업의 계획서와 결과보고서에만 보관합니다.
