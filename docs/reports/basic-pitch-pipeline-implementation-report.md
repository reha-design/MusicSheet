# W04 Basic Pitch 제품 파이프라인 연결 검증

2026-10-04 · 실행 계획 R4 독립100/100. Task1~4 구현은 각각 독립100/100, 전체 변경도 독립100/100으로 통과했다. 기본 모델 선정은 W05다.

## 구현 결과

Python3.13 orchestration runtime이 명시적 설정에서 TRANSCRIBE만 활성화하고 사전 설치된 Python3.12 worker를 별도 프로세스로 호출한다. 기본 registry는 비활성이다. WAV 구조와 전체 frame 확인, 필요 시 FFmpeg22050Hz mono PCM 변환, pinned provenance/wire JSON·전체 MIDI 구조 확인을 거쳐 두 결과를 attempt별 LocalStorage에 저장한다.

부모는 Windows Job Object 또는 Linux process group으로 실행기와 자식을 소유하며 stdout EOF 대신 private READY/완료 frame으로 direct tool 완료와 descendant0을 함께 확인한다. 취소 시 I/O thread를 drain하고 확인된 Ref를 rollback한다. 결과 반환 전에 임시 폴더 정리와 cancellation을 재확인한다. 기존 runner의 fingerprint·SHA/size·DB 소유권 fence와 stage 완료/outbox transaction을 유지했다. Celery5.6.3·Kombu5.6.2·Redis Python client6.4.0은 변경하지 않았다.

## 실제 검증

| 환경/대상 | 결과 | 의미 |
| :--- | :--- | :--- |
| Windows 실제 제품 모델/provider | 첫 실행1 passed/40.55s, 전체 ML5 passed/6.31s | product factory→isolated ONNX CPU→JSON/MIDI Ref. 기존 CLI4개+새 provider1개 |
| Windows 실제 PostgreSQL16 | 최종3 passed/3.40s | 실제 모델 등록·중복 call1, 제어용 blocking child 취소·연결 loss fence |
| Windows root | 308 passed/17 skipped/8 deselected,12.92s | 정상 unit 회귀; 실제 ML/DB는 위 별도 명령에서 실행 |
| Windows API | 232 passed/25 skipped/1 warning,1.96s | opt-in API DB/Redis 제외; 기존 testclient deprecation |
| Windows 모델 worker | 46 passed/1 warning,3.90s | 독립 Python3.12 worker 회귀; 기존 pkg_resources deprecation |
| Linux subprocess | 13 passed/1 skipped,26.00s | 실제 process group 수명·취소·EOF/timeout 검증, Windows Job test 제외 |
| Linux root | 313 passed/12 skipped/8 deselected,29.57s | locked root 전체, symlink 경계도 실행; Windows 전용·실서비스·미설치 FFmpeg 등 skip |
| root/API/worker 환경·locks | locked offline sync/check 모두 exit0 | mido1.3.3은 root/API만 추가, 모델 package root/API 없음, worker lock 불변 |

Windows Python3.13 orchestration과 Python3.12 worker, FFmpeg6.0을 사용했다. fixture는 CC0 `basic_pitch_smoke.wav`, SHA256 `2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a`. 실제 JSON은 schema1, Basic Pitch0.4.0 source `049dc8a01a170c2370d7b246ec1c2067e060c3bf`, nmp.onnx, nonempty notes·빈 pedal을 확인한다. 두 Ref의 파일 크기·SHA·producer/version·attempt 이름도 확인한다.

실DB는 본 작업이 만든 PostgreSQL16 ID `51968c14e67e5595a6b21faf68c8f0d30f59d2bad4060b88d9668bbe2a845ea7`, image `sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`다. `127.0.0.1`의 임의 port에 전용 `musicsheet_test`를 만들고 database comment marker와 API migration1/2를 명시 적용했다. 공유 DB·기존 volume는 사용하지 않았다. 각 UUID job은 선행3개 완료 attempt를 기존 runner로 준비한다. TRANSCRIBE 성공은 metadata2·output IDs2·POSTPROCESS outbox1·job RUNNING/TRANSCRIBE다. 전체 job 완료로 표시하지 않는다. 취소·connection termination은 추가 metadata0·POSTPROCESS0이며 자식 종료·임시 폴더 제거를 확인한다. fixture finally가 자신의 job rows·connection·storage temp를 정리한다.

Linux는 전용 container ID `742c4ba782211f2143bde9c779354430d69bd53e9913b0f51274ffadfb44cfe8`, image `sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81`, Python3.13.16·uv0.10.11이다. git archive HEAD에 명시 tracked 변경과 새 테스트를 덮어쓴 snapshot만 전달하고 Windows .venv·.git·outputs·tmp·DB credentials를 제외했다. install/sync/version/process/root 각 exit0, finally 제거와 inspect 실패로 absence를 확인했다. 모델/API 환경은 설치하지 않았다. 처음 Linux 검증 도구의 Windows cp949 decoding 오류는 UTF8 명시로 수정했으며 실패 container `f5c3120fee4fae6e0ffdf0dd629bd49f87851231847bf546e160ed506b308fe8`도 제거했다.

## 재현과 실패 기록

명령은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project <. 또는 services/api 또는 services/ml/basic-pitch-worker> --python <3.13 또는3.12> pytest <tests> -q -p no:cacheprovider --basetemp outputs/.verification-w04/<고유폴더> --tb=short`다. 실제 모델은 selector·두 실행기 절대 경로를 설정하고 `-m ml_integration tests/integration`, 실DB는 `-m 'ml_integration or pipeline_db_integration' tests/pipeline/integration/test_basic_pitch_stage.py`를 사용했다. root pytest 기본 addopts는 두 marker를 제외한다.

기존 CLI tests의 nested uv에는 workspace cache `UV_CACHE_DIR`와 `PYTHONUTF8=1`을 전달했다. 누락 시 기본 사용자 cache 권한 오류와 cp949 stderr decoding으로 ML1failed/4passed가 발생했고, 환경 수정 뒤5passed로 확인했다. 새 제품 provider는 request 중 uv를 호출하지 않는다. 새 integration module의 첫 collection 오류는 tests/integration package marker를 추가해 같은 이름의 unit module과 충돌을 막았다. 실제 제품 모델·DB tests는 추가 시 이미 GREEN이므로 행동 RED를 꾸며 기록하지 않았다. 제품 Task1~3의 실제 RED와 수정은 각 보고서에 있다.

root/API/worker offline lock checks 및 locked sync 성공. worker lock SHA256 `2d7d8128b0809d4ea759b6fc0d8ea6ba413a596c5aff864bc823b145a443597c` 불변. root/API dependency에는 TensorFlow/PyTorch/Basic Pitch/ONNX Runtime을 추가하지 않았다.

## 독립 리뷰 및 범위

Task1~4 및 W04 전체는 각100/100, blocker0/important0/minor0. Task4와 전체 독립 평가 결과·전용 DB 최종 정리 증거는 아래와 같다. 계획 점수와 구현 점수는 별도로 기록한다.

실제 Linux Celery의 Basic Pitch 모델 실행은 검증하지 않았다. 기존 W03 Linux worker8개 검증은 테스트 provider의 orchestration 증거이며 이번 Windows 모델 증거와 합쳐 Linux 모델 지원으로 주장하지 않는다. 실제 YouTube 전체 변환은 W09, default 모델·정확도/속도 비교는 W05, 미구성 다운로드/분리/후처리/렌더링은 후속 작업이다. 동기 I/O 자체가 막히면 반환까지 drain하므로 timeout은 hard wall-clock이 아니다. 강제 owner death·자발적 session escape·확인되지 않은 put 파일과 반환 후 DB fence에서 거부된 파일의 orphan GC는 W11에 남는다.

Task4 독립 코드 리뷰 **100/100** (/root/w04_live_integration_review, 2026-10-04, 25/25·25/25·25/25·15/15·10/10), blocker0/important0/minor0. reviewer 실제 DB3 passed/3.38s, root308 passed/17 skipped/8 deselected/11.42s, diffcheck0. 설계문서의 과거 기록과 최종 DB timing 표기를 수정·확인했다. 기준4d0abe8 대비 Task4 전체를 평가했다.

전용 PostgreSQL의 jobs0을 확인한 뒤 저장한 container ID와 name을 대조해 해당 ID만 제거했다. inspect 실패로 absence를 확인했고 ignored postgres.env/database.url의 삭제와 미존재를 확인했다. 두 Linux container와 전용 DB는 모두 정리됐다. 공유 서비스는 변경하지 않았다.


W04 전체 독립 리뷰 **100/100** (/root/w04_whole_review, 2026-10-04, 25/25·25/25·25/25·15/15·10/10), blocker0/important0/minor0. a1fd862 대비 Task1~3 commit와 미커밋 Task4/최신 문서 전체를 평가했다. reviewer root308 passed/17 skipped/8 deselected/11.03s, root/API/worker lock·worker hash·diffcheck 통과. Windows 실제 모델/DB는 실행/독립 기록을 검토했고 Linux는 원본 logs를 확인했다. 리뷰에서 재실행하지 않은 항목을 직접 실행으로 주장하지 않는다.

실행 중 판단 기록: 승인 계획에 명시된 기존 feature checkout에서 구현했고 AGENTS.md에 따라 각 단위별 독립 게이트를 유지했다. 공유 test helper와 integration package marker는 테스트 재현을 위한 추가 파일이다. private READY/완료 handshake 보완은 R4 계획을 독립 재평가한 뒤 구현했다. 각 put은 loop가 취소 fence를 확인해 시작을 허가하는 시점에 소유권을 예약하며 이후 취소는 진행 중 작업을 drain/rollback한다. owner death/session escape/orphan GC와 Linux 실제 모델/Celery는 후속 범위로 유보한다. W04 실행 ledger와 review package는 최종 commit 후 ignored tmp/w04-20261004-final로 보존하고 이 계획의 임시 skill workspace만 정리한다.

주요 구현 커밋: `0381b6f`(프로세스 수명), `4844773`(WAV/검증/저장), `4d0abe8`(provider/runtime). Task4 검증·완료 기록은 이 보고서를 추가한 `test(pipeline): verify Basic Pitch stage integration` 커밋에 포함한다.
