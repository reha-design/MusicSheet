# Pipeline 운영 도구 Task1 — 실행 진행률

- 날짜: 2026-10-06. 기준 `1b3a1e3fab426f8456ef9de630547b8fae315e4d`.
- 계획: [R1 실행 계획](../plans/pipeline-operator-tools-implementation-plan.md), 독립97/100 (25+19+20+24+9), blocker0/important0.
- 범위: optional StageContext async callback, active attempt/generation의 증가 진행률 전이, runner callback 수명·직렬화, Basic Pitch 처리 이정표, 기존 이벤트 저장 계약.
- 상태: 구현·검증 및 독립 단위 리뷰 **99/100** 통과. 자체 구현 점수 없음.

## 동작

현재 RUNNING job/attempt와 stage/active ID/generation이 일치할 때만 0~99의 정수 진행률을 저장한다. 반복·역행·취소·최종 상태·오래된 callback은 무변경이다. 100은 결과 검증·DB 완료 이후 기존 runner가 기록한다. 동시 callback의 DB 갱신과 commit 후 SSE 발행을 함께 직렬화한다. DB 장애는 InfrastructureUnavailable로 전달하고 Redis 실패는 DB 결과를 되돌리지 않는다.

Basic Pitch는 입력 준비20, 모델 실행70, 결과 검증85, 파일 저장95를 보고한다. 시간 예측·전사 정확도가 아니며 결과 artifact/metadata 공개는 기존 runner 완료 transaction을 따른다. 기존 직접 StageContext 생성자와 모델 실행 계약은 유지한다.

## 검증

| 검증 | 결과 |
| --- | --- |
| test_progress.py 최초 RED | 23failed. callback field/session method/연결 부재를 확인 |
| 첫 GREEN 시도 | 84pass/2fail. 새 테스트가 서로 다른 UUID fixture의 경로를 사용한 문제를 확인해 테스트 경로만 수정 |
| progress/runner/repository/Basic Pitch 집중 회귀 | **86pass**, 2.15초 |
| Linux 동일 집중 회귀 | **86pass**, 1.90초. read-only repo/Python3.13 container, 기존 API environment의 정확한 package version 설치 |
| 독립 리뷰 보강 이후 집중 회귀 | Windows **89pass**, 2.23초 / Linux **89pass**, 1.95초. runner의 direct/wrapped/swallowed DB 장애 전파3개 보존 |
| 실제 PostgreSQL·Redis progress integration | **1pass/skip0**, 0.84초. 실제60% commit/overall10, payload field 읽기, 반복/역행 timestamp 무변경, generation 변경 및 취소 차단 |
| Windows root 회귀 | 보강 전331pass, 보강 후 **334pass/11skip/14deselected** |
| Windows API 회귀 (opt-in URL 미설정) | **232pass/26skip**, 기존 deprecation warning1 |
| git diff --check | exit0 |

명령은 계획의 offline/no-sync root/API pytest를 사용했다. 집중 실행에 `-p no:cacheprovider`를 추가해 기존 cache 권한 경고를 배제했다. live DB는 이 작업 소유의 PostgreSQL16 container이며 `musicsheet_test`/disposable marker를 확인했다. Redis7-alpine 전용 container DB2의 해당 job key만 생성·삭제했다. 전체 모델 재실행이나 실제 Celery worker를 이번 단위에서 검증한 것으로 주장하지 않는다.

## 리뷰 대상 fingerprint

| 파일 | SHA256 (검토 시 파일 bytes) |
| --- | --- |
| contracts.py | F62C5EBF1765DF4934700E0ECC151FF134C69AC6E30BBB7A6D5ED75D57E87012 |
| repository.py | CA551578D633C41FD71C52553AB5B43359811EF4F11CEF383CE0324FF9269D37 |
| runner.py | 5047C8CEC73FAEC7AD8631E4A6DE931FF914D2CCBA21F0703081523642C360DC |
| basic_pitch/provider.py | 92E4033D362233CFFA41ED09EA463E84447D2EAAB6322A40C9D6709AD06ECE49 |
| tests/pipeline/test_progress.py (리뷰 보강 후) | DCC0D228FDD74412B692AC153B7462D8857B825088AD62E8EB8C4B62F004E595 |
| API integration/test_operator_tools.py (리뷰 보강 후) | 6E0AD158328A6BB5C26155892B3D81248B4CDCACC30DB0F421C83C1A78891A54 |

독립 reviewer의 minor2개를 처리했다. 실제 DB 취소 검증은 generation이 유효한 상태에서 먼저 수행하도록 분리했고 재실행1pass/skip0(0.73초)다. callback DB 오류를 provider가 그대로 전파·다른 오류로 감싸거나 삼켜도 runner가 InfrastructureUnavailable로 전달하며 상태 rollback과 잠금/listener 회수를 지키는3개 회귀를 추가했다. 제품 코드 fingerprint는 위 초기 버전과 같다.

root/API/model lock 파일은 Git 변경이 없다. main checkout 후 bytes 기준 root90426204499C971BC1150DFF500BD170D3089C49C9DB85D897D85CE41AA0BCF8, API786088B447224F48F5A27364CD3621CC56A79AEB1BBC1D0212DF50E5451854E6, model2D7D8128B0809D4EA759B6FC0D8EA6BA413A596C5AFF864BC823B145A443597C다. 이전 checkout의 줄바꿈별 hash와 Git 변경을 혼동하지 않는다.

## 독립 구현 리뷰

`/root/operator_progress_review`, 2026-10-06, 계획/spec R1 기준. base `1b3a1e3...` 대비 최종 staged12파일(+535/-4), 제품4개와 테스트2개의 위 SHA256를 검토했다. 점수25+25+24+15+10 = **99/100**, 미해결 blocker0/important0/minor0. 초기 minor2개는 위 테스트 보강으로 처리했고 독립 집중 재실행89pass/2.13초다.

추가 독립 probe에서 Basic Pitch95% callback 실패의 출력2개 회수와 진행 이벤트 발행 중 취소·늦은 callback 차단·잠금/listener 회수를 확인했다. 실제 서비스 검증은 executor 증거를 검토했으며 reviewer가 별도로 재실행하지 않았다. 미구현 Task2, 모델 정확도/실제 모델 재실행, 실제 Celery worker 전체 실행은 이 단위 판정에 포함하지 않았다.
