# W04 Task3 제품 TRANSCRIBE provider 연결

2026-10-04. R4 계획 독립100점, Task1/2 코드 각100점 통과 후 구현했다. 기준 commit은4844773이다.

`build_providers`는 기본 빈 registry를 그대로 반환하고 opt-in 설정에서 TRANSCRIBE만 등록한다. 고정 Python metadata probe와 FFmpeg version probe는 각각5초·bounded stdout으로 실행하며 모델을 import하지 않는다. 실패는 identity가 있는 영구 실패 provider로 처리해 Celery infrastructure 재시도를 유발하지 않는다. 취소는 그대로 전파한다.

BasicPitchProvider는 Python3.12 독립 worker를 고정 bootstrap으로 호출한다. 입력 변환→추론→두 파일 검증→저장 순서이며 runner/repository 계약은 유지한다. 반환 전에 임시 폴더 정리를 기다리고 cancellation을 재확인한다. 반환 전 실패·취소·정리 실패는 확인된 두 Ref를 삭제한다. identity에 pinned 모델·wire schema·WAV 규격·경로·FFmpeg version·size limits를 포함해 설정 변경을 fingerprint로 검출한다.

## 검증

- interface scaffold 행동 RED17 failed/7 passed(25.76s). 추가 실제 runtime 점검 실패 test RED1 failed(.54s): PROVIDER_NOT_CONFIGURED 대신 PROVIDER_FAILED가 필요했다.
- 선택 provider/registry/Celery tests **25 passed**(2.67s). 성공 출력 role·attempt 이름, exit2/3/4, 잘못된 MIDI 저장 금지, 취소 후 임시 폴더 정리, 반환 전 rollback, 중복 worker call1, 설정 변경 INPUT_CHANGED, DB 소유권 loss의 metadata/outbox fence를 확인했다.
- API **232 passed/25 skipped/1 warning**(1.61s). 기존 testclient deprecation warning이며 opt-in DB/Redis는 이 단위에서 제외했다.

실행은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest <tests> -q -p no:cacheprovider --basetemp outputs/.verification-w04/<고유폴더> --tb=short`; API는 독립 project를 지정한다. 실제 환경 probe·root 회귀·독립 리뷰 결과는 아래에 추가한다.

전체 제품 pipeline과 default model은 후속 작업이다. 실제 모델/DB 등록·Linux 회귀는 Task4에서 검증하며, owner 강제 종료와 runner 반환 후 DB fence 거부 파일의 GC는 W11에 남는다.
root 회귀 **308 passed/17 skipped/4 deselected**(11.42s). 실제 설치된 Python3.12 worker와 FFmpeg6.0을 제품 factory의 두 probe로 확인했다. root/API offline lock check 통과, worker lock SHA256 `2d7d8128b0809d4ea759b6fc0d8ea6ba413a596c5aff864bc823b145a443597c` 불변. 독립 코드 리뷰 진행 중이다.
최종 독립 리뷰 **100/100** (/root/w04_provider_review, 2026-10-04, 25/25·25/25·25/25·15/15·10/10), blocker0/important0/minor0. 선택25 passed(2.81s), 관련7파일 회귀88 passed/5 skipped(6.39s), diff 검사와 worker lock 불변을 독립 확인했다. Task4 진행 게이트를 통과했다.
