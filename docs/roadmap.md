# 개발 현황

이 문서는 현재 진행 상태와 바로 이어서 검토할 작업만 기록합니다. 전체 남은 작업은 [backlog.md](backlog.md), 완료 기록은 [completed-work.md](completed-work.md)에서 관리합니다.

## 진행 중

**W05 — 기본 전사 모델 결정**: 사용자 `다음 작업 진행`으로 착수했습니다. 기존 실행 확인 음원에 정답 MIDI가 없어 별도 평가 데이터가 필요하며, 사용자는 비상업 연구·개인 개발용 평가 범위를 확인했습니다. 두 후보·정답 dataset·metric·실행 환경을 조사했고 평가 설계 방향을 확인 중입니다 ([착수 조사](reports/transcription-model-evaluation-preparation-report.md)). 아직 모델 비교·기본 모델 결정·제품 동작 변경은 수행하지 않았습니다.

## 다음 작업 후보

W05 완료 후 다음 작업 후보는 **W06 — 음원 분리**입니다. 모델 선정 결과를 바탕으로 Demucs 분리와 solo piano bypass를 구현합니다.

작업 시작 시 backlog에서 해당 항목을 제거하고 `진행 중`에 등록합니다. 구현 완료 후에는 [completed-work.md](completed-work.md)에 완료일·결과보고서·리뷰 점수·커밋을 기록하고 이 문서에서 제거합니다. 구현 상세와 검증 결과는 각 작업의 계획서와 결과보고서에만 보관합니다.
