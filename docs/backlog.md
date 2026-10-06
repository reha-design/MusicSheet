# 남은 작업

이 문서는 아직 시작하지 않은 작업의 요약 목록입니다. 각 작업을 시작할 때 관련 사양을 확인하고 별도 구현 계획을 작성합니다. 계획 독립 리뷰에서 95/100 이상을 받고 blocker/important 지적이 없어야 구현을 시작합니다.

## W06: 음원 분리

상태: `Planned` · 권장 선행 작업: W03, W05

완료 기준: Demucs 기반 분리와 solo piano bypass를 구현하고, 분리 품질 및 생성 stem을 아티팩트로 기록합니다.

사양: [음원 분리](ai/separation.md), [모델 어댑터](ai/model-adapters.md), [아티팩트](domain/artifacts.md)

## W07: 리듬·템포·퀀타이즈

상태: `Planned` · 권장 선행 작업: W05

완료 기준: 전사 note event를 tempo·meter 정보와 정렬하고 박자와 음표 길이가 정해진 악보 데이터로 변환합니다.

사양: [리듬 분석](ai/rhythm.md), [퀀타이즈](ai/quantization.md), [노트 이벤트](domain/note-events.md), [악보 모델](domain/score-model.md)

## W08: 악보 생성 및 렌더링

상태: `Planned` · 권장 선행 작업: W07

완료 기준: 악보 모델을 MusicXML로 직렬화하고 PDF·미리보기 이미지를 만들어 다운로드 가능한 아티팩트로 등록합니다.

사양: [악보 모델](domain/score-model.md), [모델 어댑터](ai/model-adapters.md), [아티팩트](domain/artifacts.md)

## W09: 전체 파이프라인 통합

상태: `Planned` · 권장 선행 작업: W01–W08

완료 기준: 검증 음원으로 입력 등록부터 분리·전사·퀀타이즈·렌더링까지 end-to-end 실행을 확인하고 실패·재시도·재실행을 검증합니다.

사양: [전체 시스템](architecture/system.md), [작업 파이프라인](architecture/job-pipeline.md), [작업 상태](domain/job-state.md)

## W10: 웹 앱

상태: `Planned` · 권장 선행 작업: W01, W02, W08

완료 기준: 작업 등록, 진행률·오류 확인, 악보 미리보기 및 결과 다운로드를 제공합니다.

사양: [전체 시스템](architecture/system.md), [API](backend/api.md), [아티팩트](domain/artifacts.md)

## W11: 운영 및 배포 구성

상태: `Planned` · 권장 선행 작업: W03–W10

완료 기준: API·worker 컨테이너, 모델 프리페치, 환경 설정, 장애 복구 및 운영 진단 절차를 구축합니다.

사양: [런타임](infrastructure/runtime.md), [컨테이너](infrastructure/docker.md), [헬스 체크](infrastructure/health-check.md)

선택 검토 후보: PR #11의 `CELERY_VISIBILITY_TIMEOUT` 환경 설정 노출 및 손상 Redis entry 건너뛰기. 현재 세 visibility 설정3600과 손상 batch 오류 계약은 유지한다. 실제 운영 요구가 확인되면 세 설정의 일관성 또는 event 손실·재접속 동작을 별도 사양·계획·독립 점수 게이트로 검토한다. 이번 [운영 도구 통합](reports/pipeline-operator-tools-integration-report.md)의 미완료 필수 기능으로 취급하지 않는다.

## W12: S3 스토리지 확장

상태: `Planned` · 권장 선행 작업: LocalStorage 사용 흐름 검증 완료

완료 기준: 기존 `ArtifactStorage` 계약을 따르는 S3 어댑터를 구현하고 LocalStorage와 동일한 저장·조회 동작을 검증합니다.

사양: [스토리지 추상화](architecture/storage.md), [아티팩트](domain/artifacts.md)
