# 개발 현황

이 문서는 현재 진행 상태와 바로 이어서 검토할 작업만 기록합니다. 전체 남은 작업은 [backlog.md](backlog.md), 완료 기록은 [completed-work.md](completed-work.md)에서 관리합니다.

## 진행 중

**FFmpeg 준비 완료·W06 모델 검증 재개 대기**입니다. 프로젝트 전용9.0.2 설치, 두 로컬 설정과 실제16초 PCM 변환을 확인했습니다. [설치·적용 보고서](reports/ffmpeg-project-setup-report.md)를 참조하세요. 실제 Demucs 추론·출력·취소와 비무음 CPU 지원은 아직 미검증이며 W06 backlog 항목을 유지합니다.

W06-0 선행 검증 보고·QC 조사·Proposed 설계는 완료했습니다(계획100점·단위1 증거98점·단위3 문서99점·전체 준수98점). [당시 FFmpeg 미확보 중단 증거](reports/w06-separation-preflight-report.md)와 [Proposed 제품 연결 초안](superpowers/specs/2026-10-15-separation-integration-design.md)은 그대로 보존합니다.

W05 평가·선정은 Task5 단위100점·별도 전체100점으로 완료했습니다. [실제 비교 결과와 제품 연결 대기 경계](reports/transcription-model-evaluation-report.md)는 완료 색인에서 관리합니다.

## 다음 작업 후보

다음 작업 후보는 **W06 선행 검증 재개**입니다. 준비된 프로젝트 환경을 명시적으로 로드해 새 run-id로 모델 자산·독립 환경·정상/무음/손상·취소/timeout을 검증합니다. 실제 검증과 사양·독립 점수 게이트를 통과한 뒤 Demucs 제품 연결과 solo piano bypass를 구현합니다. W05의 Piano AMT는 평가 subset 선정이며 제품 연결은 별도 후속 작업입니다.

작업 시작 시 backlog에서 해당 항목을 제거하고 `진행 중`에 등록합니다. 구현 완료 후에는 [completed-work.md](completed-work.md)에 완료일·결과보고서·리뷰 점수·커밋을 기록하고 이 문서에서 제거합니다. 구현 상세와 검증 결과는 각 작업의 계획서와 결과보고서에만 보관합니다.
