# W05 Task1 — 평가 환경·MIDI 정답·점수 계산

2026-10-05 · BASE `9d5e662` · [실행 계획 R5](../plans/transcription-model-evaluation-implementation-plan.md) 독립100/100 · 사용자 실행 승인: R3 제시 후 `다음 작업 진행`. 상태: Task1 구현·검증 및 독립 코드 재리뷰100점 완료.

## 구현 범위

`tools/transcription-eval`을 독립 Python3.13 uv 프로젝트로 추가했다. local common/storage/pipeline 경로를 명시하고 기존 source와 일치하도록 editable=true로 고정했다. 새 lock에는 mir_eval0.8.2, mido1.3.3, NumPy2.5.3, SciPy1.18.1, HTTPX0.28.1, soundfile0.13.1, pytest9.1.1이 설치됐다. 모델 라이브러리·dataset·checkpoint는 취득하지 않았다. 초기 설치는 `C:/python/python.exe` CPython3.13.7을 명시했다. 이는 sandbox의 managed Python discovery 접근 제한을 피하는 기존 실행기 지정이며 Python 버전 변경이 아니다.

frozen 평가 타입은 bool/NaN/Infinity·범위·비양수 interval·일대일 pair index 및 MAE 일관성을 검사한다. 제품 공용 schema에 추가하지 않았다. reference는 최대16MiB 일반 MIDI 파일을 전체 검사하고 type0/1·PPQN만 허용한다. track size/end-of-track·최대4byte VLQ·trailing byte·링크 경로·meta type7bit와 고정 payload 길이·전 track/EOT 포함100,000event 상한을 검사한 뒤 mido로 parse한다. `read_validated_midi_bytes`는 객체 생성 없이 raw gate만 제공해 후속 Task4의 후보 출력 선검사에도 사용한다. 절대 tick/track/event의 안정 순서와 Fraction 기반 tempo map으로 초를 계산한다. channel/pitch별 note 상태와 CC64>=64 상태를 보존하며 열린/겹친/짝 없는 이벤트를 거부한다. 건반 해제와 sustain 정답을 별도로 만들고 동일 channel/pitch 재타건에서 연장을 제한한다. CC66/67은 sustain 연장에 사용하지 않는다.

metric은 [pinned mir_eval 최대 매칭](https://mir-eval.readthedocs.io/latest/api/transcription.html)으로 pitch를 Hz로 변환하고 onset50ms/pitch50cents/strict=False, optional offset20%/최소50ms를 적용한다. `[2,28)` onset 선별·30초 offset 절단과 개수를 반환한다. 중복 예측은 FP로 계산하고 빈 정답은 P/R/F1 null 및 FP를 남긴다. macro와 합계 TP/FP/FN 기반 micro는 별도다. velocity는 같은 onset matching의 정렬 입력과 pair index를 보존한다. pair가 없거나 matching pair 중 velocity가 누락되면 MAE null을 반환하고 전체 pair 목록을 유지한다.

reference×prediction 상한1,000,000cells는 onset/offset/velocity 공통으로 NumPy 배열 생성과 mir_eval 호출 전에 검사한다. event/cell cap 초과는 `EvaluationLimitError(ValueError)`이며 truncate/sample하지 않는다. runner의 infrastructure/invalid benchmark/no_selection 연결은 Task4 회귀로 검증할 예정이며 이번 Task1에서 이미 실행했다고 주장하지 않는다. 실제 데이터의 상한 적합성은 Task2/4 gate에서 확인한다.

## 검증 증거

모든 테스트는 repo root에서 config/test 경로를 명시하고 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project <project> --python 3.13 pytest`로 실행했다. 테스트 공통 suffix는 `-q -p no:cacheprovider --basetemp <절대경로> --tb=short`이며 매 실행의 basetemp는 서로 다른 `D:/develop/MusicSheet/outputs/.verification-w05/<name>`이다. collect-only는 대신 `--collect-only -v`를 사용했다.

| 단계 | config·test 경로 / basetemp | 결과 |
|---|---|---|
| 기존 baseline | `-c pyproject.toml tests` / `t1-baseline-20261005` | 308 passed /17 skipped /8 deselected, 11.04초 |
| lock/sync/import | 새 evaluator만 lock·locked sync, shared process/result import | 성공 |
| 환경 gate | `-c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests/test_environment.py` / `t1-env-20261005` | 1 passed, 0.27초 |
| RED | 같은 config, `test_reference.py test_metrics.py` 전체 경로 / `t1-red-20261005` | reference/contracts 미구현으로 collection2 errors |
| 선택 GREEN | 같은 두 test 경로 / `t1-green-20261005` | 44 passed, 1.36초 |
| 전체 evaluator | 같은 config, `tools/transcription-eval/tests` / `t1-full-20261005` | 45 passed, 1.28초 |
| collect-only | 같은 config/tests, `--collect-only -v` | evaluator config/rootdir·45개만 수집 |
| 기존 root 회귀 | `-c pyproject.toml tests` / `t1-root-20261005` | 308 passed /17 skipped /8 deselected, 12.79초 |
| meta 회귀 RED | evaluator config, 두 test 파일 / `t1-review-meta-red` | 잘못된 meta8개 미거부로8 failed |
| cap/MAE 회귀 RED | 두 test 파일, `-k 'event_cap or cell_cap or inconsistent_mae'` / `t1-review-resource-red` | downstream 호출/모순 MAE로7 failed·경계2 passed |
| meta/MAE GREEN | 두 test 파일, `-k 'fixed_meta or inconsistent_mae'` / `t1-review-meta-green` | 11 passed, 1.80초 |
| 보완 전체 GREEN | evaluator 전체 tests / `t1-review-full-green` | 62 passed, 1.30초 |
| 최종 evaluator | evaluator 전체 tests / `t1-final-full` | 62 passed, 1.38초 |
| 최종 root 회귀 | `-c pyproject.toml tests` / `t1-final-root` | 308 passed /17 skipped /8 deselected, 11.51초 |

root/API/기존 Basic Pitch의 세 lock SHA256은 실행 전과 일치했다 (순서대로 `200C167E…C748CEC`, `0FDFE6C2…6428EAA`, `2D7D8128…443597C`; 전체값은 실행 ledger와 기존 기록에 보존). evaluator `uv --cache-dir outputs/.uv-cache lock --check --offline --project tools/transcription-eval --python C:/python/python.exe`는 성공했다. `git diff --check`도 통과했다. 링크 검사와 독립 코드 리뷰의 정확한 범위/hash·5항목 점수·지적 처리는 완료 후 아래에 기록한다. RED는 설치/권한 실패가 아니라 계획된 미구현 import 실패였다.

## 독립 코드 리뷰

평가자 `/root/w05_task1_review`, 2026-10-05. 최초 Task1 코드는 요구24/오류21/검증23/구조14/문서10=**92점**, blocker0/important2/minor1로 다음 Task gate를 통과하지 못했다. 리뷰 snapshot manifest SHA256은 `32FD440A95B0869BFDCA78EBE14D5162298E0A2A6C2497CBC877A7A1DE4DF6AC`이며 코드·테스트·환경12파일을 식별한다. Reviewer는 별도45 tests(1.22초)와 small malformed/resource probes를 실행했다.

important1은 mido가 고정 meta의 초과 payload를 무시하는 문제이며 raw fixed length/type 검사와8개 RED→GREEN으로 해결했다. important2는16MiB 안에서도 mido 객체·dense matching이 커지는 문제다. 구현 전에 사양/계획을 갱신했다. 계획 R4는96점(24/19/20/23/10)이어도 후보 출력 경로 important1 때문에 미통과였고, R5에서 두 후보 raw 선검사·typed cap 오류·Task4 fake-worker 연결 회귀를 추가해 독립100점(25/20/20/25/10), 지적0을 받은 뒤 cap을 구현했다. 계획의 정확한 버전/hash는 계획 마지막 절에 기록했다.

minor1의 모순 MAE는 pair/velocity completeness와 MAE 재계산 일관성 검사,3개 RED→GREEN으로 해결했다. 같은 reviewer가 보완 Task1 전체를 별도 snapshot으로 재리뷰했다.

| 코드 리뷰 | 요구 /25 | 오류 /25 | 검증 /25 | 구조 /15 | 문서 /10 | 총점 | 미해결 blocker/important/minor |
|---|---:|---:|---:|---:|---:|---:|---|
| 최초 | 24 | 21 | 23 | 14 | 10 | 92 | 0/2/1 |
| **보완 재리뷰** | **25** | **25** | **25** | **15** | **10** | **100** | **0/0/0** |

평가일2026-10-05, reviewer `/root/w05_task1_review`. 보완 리뷰 범위는 BASE9d5e662 대비 Task1 evaluator 전체·검증/보고서·관련 상태/계획/설계 변경이다. snapshot manifest SHA256 `8E2D53A4CAF44BE6E433265FBB1780EE26F83789B4F24E3A83DA3AC368A15D22`의12파일을 직접 대조했고 독립62 tests(1.32초)를 재실행했다. 해당 명령은 표의 evaluator full 명령과 같고 basetemp는 `t1-independent-review-20261005-b`다. 핵심 코드 SHA256은 contracts `501A25D6B9E1CC0B2A334432F988E8E28A905812659830F75898A22CA9E96FF4`, reference `C3589060DB07E87551DF19458713B51B4371A46E5BB4FF5DDB98FA2419A027A7`, metrics `4CCC84152AB251259EBD411728AED79D85F728C1C76ECC0C9120766BE92F9BF7`이다. 이 기록 추가는 코드/계약 변경이 아니다.

**Task1 코드 게이트100>=95·미해결 blocker/important0 통과.** 변경5개 문서의 로컬 링크109개 누락0과 diffcheck를 확인했다. reviewer가 판단 보류한 실제 데이터 cap 적합성/오디오, 후보 출력 선검사·ledger 연결, 모델 설치/정확도/선정은 각각Task2/4/3~5의 준비·검증 gate로 넘기며 성공으로 간주하지 않는다. 계획100점과 코드100점은 별도 평가다.

## 남은 범위

Task2 데이터·오디오·manifest, Task3 ByteDance worker/checkpoint, Task4 실행/선정, Task5 실제 비교가 남아 있다. 이번 합성 테스트 통과는 실제 모델 정확도나 선정 결과를 의미하지 않는다. 기존 root/API/Basic Pitch pyproject·lock·제품 provider 동작은 유지한다.
