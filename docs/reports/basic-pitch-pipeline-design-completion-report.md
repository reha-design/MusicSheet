# W04 Basic Pitch 제품 연결 설계 완료 보고서

- 날짜: 2026-10-04 (Asia/Seoul)
- 기준 코드: `47981c7` (설계 R1 승인·계획 R2 독립99점 기록)
- 사용자 목표: `설계완료까지 계속해서 진행`
- 산출물: [승인 설계 R1](../superpowers/specs/2026-10-04-basic-pitch-pipeline-design.md), [최종 실행 계획 R3](../plans/basic-pitch-pipeline-implementation-plan.md), canonical 사양·현황·색인
- 판정: **W04 설계·계획 단계 완료**. 제품 연결 구현·신규 테스트·실제 모델/DB 통합 실행은 후속 구현 단계다.

## 남은 설계 지적 처리

계획 R2의 유일한 minor는 Python wave의 PCM 지원 경계를 IEEE float WAV 손상으로 오인할 수 있다는 점이었다. R3는 정상 비PCM WAV를 FFmpeg로 변환하는 경로, 변환 전에 잘린 RIFF/RIFX container/chunk/padding 범위를 검사하는 경로, 정상 float·잘린 float fixture와 합격 assertion을 Task2에 명시했다. root에 SoundFile 등 모델 의존성을 추가하지 않는다.

독립 reviewer `/root/w04_plan_review`가 R3 전체를 승인 설계·canonical 문서·실제 StageProvider/설정/runner/스토리지/worker 계약과 대조했다. 수정은 기존 WAV 변환 설계의 구체화이며 상주 서버·새 API·모델 환경 변경 등 승인 범위 확대가 아님을 확인했다.

| 계획 버전 | 요구사항25 | 구조20 | 순서20 | 검증25 | 재현10 | 합계 | 미해결 지적 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| R1 | 24 | 18 | 20 | 23 | 9 | 94 | important2·minor2, R2에서 해결 |
| R2 | 25 | 20 | 20 | 24 | 10 | 99 | minor1, R3에서 해결 |
| **R3** | **25** | **20** | **20** | **25** | **10** | **100** | **blocker0·important0·minor0** |

위 점수는 독립 **계획** 리뷰 점수다. 구현 리뷰 점수 또는 실제 모델 실행 결과로 사용하지 않는다.

## 요구사항별 설계 완료 감사

완료 판정은 작성된 문서의 계약·검증 계획·리뷰 근거를 대상으로 한다. 아래 미래 테스트와 명령은 실행 계획에 정의돼 있다는 증거이며 제품 구현이 통과했다는 증거가 아니다.

| 설계 완료 요건 | 현재 문서 근거 | 확인 결과 |
| :--- | :--- | :--- |
| 목표·범위·선행 조건과 대안 비교 | 설계 §1~2·§8, 계획 Goal/Architecture/Global Constraints | W04 전사 연결과 W05/W09/W11 후속 범위를 구분, CLI 추천 이유 명시 |
| 입력·출력·설정 계약 | 설계 §3~4, 전사 사양 §4, 계획 인터페이스·Task2~3 | 직전 stem1개,22.05kHz mono, 결과2개, opt-in/절대 경로/attempt 이름 정의 |
| Python·모델·의존성·캐시 경계 | 설계 §4, 런타임 사양, 계획 Global Constraints·Task2~3 | Python3.13/3.12 분리, pinned provenance, mido만 backend 추가, fingerprint 조건 정의 |
| 파일·모듈·타입·실행 순서 | 계획 파일 경계/인터페이스·Task1~4 | 명명된 제품/테스트/보고서 파일, signature, 소비·산출 의존성과 단위 순서 지정 |
| PCM/float WAV 변환과 손상 입력 | 계획 R3 Task2 Step1/3 | float 변환과 잘린 float 거부 테스트·frame/sample/channel 합격 기준 명시 |
| JSON/MIDI 검증·빈 결과·입력 경계 | 설계 §5, 계획 Task2 | wire 타입/중복 key/NaN/provenance/고유note ID/크기/symlink/track 종료/빈 notes 정의 |
| 실패·재시도·공개 오류 | 설계 §6, 계획 Global Constraints·Task3 | exit2/3/4·내용 오류·timeout 매핑, probe 실패의 영구 실패, 비밀 비노출 명시 |
| 프로세스 생성·취소·반복 취소·출력 pipe 경계 | 계획 Task1·Review Focus | 시작 gate, Job Object, Linux leader 보존, EOF 분리, 종료/소유권 실패 fixture 지정 |
| I/O thread·부분 저장·반환 직전 rollback | 계획 Task2~3·Review Focus | thread drain, 성공 Ref 기록, 저장2 실패·반환 직전 취소/임시 정리 실패의 rollback 정의 |
| DB 완료·캐시 재사용·취소/ownership fence | 설계 §7, 계획 Task3~4 | metadata2/outbox1 및 취소/연결 상실 metadata0/outbox0, 재호출0 조건 정의 |
| 실제 모델·플랫폼별 검증 | 설계 §7, 계획 Task4·명령 표 | Windows fixture 모델+DB 필수, Linux process 검증 필수, Linux 모델 미검증을 별도로 표시 |
| 재현 명령·환경·격리·정리 | 계획 실행 명령/재현 조건 | root/API/worker/lock/실모델/DB/Linux 명령과 합격 기준, marked DB·owned container 회수 정의 |
| 설계 승인·독립 계획 리뷰·단위 코드 리뷰 게이트 | 설계 §9, 계획 metadata/리뷰 표 | 설계 승인 기록, R3 독립100점·지적0, 구현 단위별 독립95점 별도 적용 |
| 문서 상태와 구현 완료의 구분 | main_spec·roadmap·전사/어댑터/런타임, 본 보고서 | 제품 registry 미연결 상태 유지, W04 전체를 completed-work에 완료 등록하지 않음 |

제품/신규 테스트 파일과 향후 코드 보고서의 실제 생성은 실행 계획의 구현 deliverable이다. 이번 목표에서 해당 파일이 아직 없다는 사실을 설계 누락 또는 제품 구현 완료로 잘못 해석하지 않는다. 설계에 남은 미정 계약·미해결 리뷰 지적은 없다.

## 이번 단계의 실제 검증

- `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w04/design-final-20261004 --tb=short`: **225 passed, 12 skipped, 4 deselected in 6.18s**, exit0.
- 기본 회귀만 실행했다. 신규 provider·IEEE float 변환·모델/DB/Linux process 테스트는 아직 구현 전이며 실행하지 않았다. API·독립 worker는 제품 변경이 없어 이번 문서 작업에서 재실행하지 않았다.
- `git diff --check`: 통과. 문서8개·로컬 링크122개를 검사해 실제 파일 대상이 존재함을 확인했다. 최종 계획 R3·구현 단위4개·독립100점·미해결 지적0 및 float 입력 경계 테스트 선언을 확인했고 TODO/TBD/FIXME 미완성 항목은 없다.
- 제품 코드·pyproject·lock·환경 설정 파일·DB schema 변경 없음. 이번 goal에서 제품 의존성을 설치하거나 서비스를 시작하지 않았다.

## 인계 상태

W04 설계·실행 계획 작성과 독립 계획 점수 게이트를 완료했다. 제품 구현은 네 단위의 RED/GREEN·별도 독립 코드 리뷰·보고서·commit을 순서대로 수행하는 다음 단계다. 실제 구현 전 최종 작성 계획에 대한 사용자 검토·실행 방식 선택을 확인한다. 이 인계 조건은 이번 `설계완료까지` 목표의 미완료 설계 항목이 아니다.
