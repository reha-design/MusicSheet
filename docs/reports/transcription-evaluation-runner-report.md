# W05 Task4 비교 실행기·검증 원장

2026-10-09 KST · BASE `245f175f7a051e1fdc124b02827d4d15b2662781` · branch `codex/w05-comparative-runner`.

상태: Task4 구현·회귀·독립 코드 게이트 완료. [상세 계획 R3](../plans/w05-task4-comparative-runner-plan.md)는 독립100점/B0/I0/M0으로 승인됐다. 코드 리뷰도 별도로100점/B0I0M0을 받았다. **실제 MAESTRO 비교와 기본 모델 결정은 Task5이며 아직 실행하지 않았다.** 아래 세션·선정 증거는 가상 worker/가상 예측을 사용하는 자동화 검증이다.

## 구현 결과

- `run`은 설치된 두 CPU worker와 고정12입력을 사용해 후보당36개/전체72개 예정 slot을 먼저 고정한다. 반복0/2는 입력 순 Basic→Piano, 반복1은 역순 Piano→Basic이다. 직렬 fresh process이며 자동 재시도는 없다.
- 실행 전 Python/package/source/backend 버전과 Basic 모델 위치를 metadata-only 프로세스로 재검사한다. WAV 형식·정확30초·입력/reference·lock/checkpoint hash도 재검사한다. 준비 실패는 추론 시작 전 infrastructure로 기록한다.
- 원시 MIDI16MiB/100000event gate를 Mido/기존 validator보다 먼저 적용한다. JSON8MiB·provenance·유한 수·양의 interval·padding31초와 Piano의 고정 MIDI timebase/tempo 및 JSON/MIDI 의미 일치를 검사한다. 평가 상한 초과는 모델 실패로 집계하지 않는다.
- 정규화 note/pedal을 binary64·구획/count·nullable tag·정렬·중복 보존 규약으로 SHA256 처리한다. tolerance 없이 반복 결과를 비교한다.
- 시작 영수증, terminal record, 원시 출력, 정규화 이벤트와 summary를 새 run root에 저장한다. 원장 publish는 exclusive 임시파일+link로 기존 파일을 교체하지 않는다. 중단된 run은 자동 resume하지 않는다.
- generic worker exit3/4는 모델·환경 원인을 확정하지 못하므로 unresolved다. 같은 exit의 반복만으로 모델 부적격을 선언하지 않는다. 실제 model 귀속에는 검증된 primitive cause가 필요하다.
- 최초12회만 정확도에 사용한다. 반복·진단은 첫 실패나 예정36회 분모를 대체하지 않는다. 진단은 실패 slot당최대1회이며 시간·정확도·원시 실패율 분모에서 제외한다.
- 선택은 paired nonempty 최소8개, PCG64 seed20261005/10000 paired bootstrap/linear95% CI,1pp macro 효과와 micro/offset guard를 적용한다. 빈 정답의 FP도 micro에 포함한다. 속도 판단은 성공표본 최소24개와 median20% 차이를 요구한다.
- 후보별2회 CC0 preflight는 원본 PCM을 반복한 뒤30초 crop한다. Task3의 silence-tail smoke와 다르다. `1.5*36*(각 후보 최대 시간 합)` 예상치가7200초를 넘으면 benchmark를 시작하지 않는다.
- slot300초·세션7200초, 외부 취소·자손 정리·I/O drain을 관리한다. metric 계산 시간은 모델 elapsed에서 제외하며 metric 자체 오류는 infrastructure다. CPU elapsed는 시작·정리·출력 검증을 포함하고 RTF=elapsed/30이다.
- 정상 파일은 full SHA256, 초과 크기 원시 출력은 바이트를 보존하되 body hash 없이 path/size/고정 사유만 남긴다. 이 경우 evaluation_limit/no_selection을 강제한다. 보고서는 미검증 상태를 표시한다.
- `report`는 summary hash·파일 inventory·start/terminal 연결·예정72개·진단 연결·normalized hash와 집계/선정을 재검산한 뒤 새 Markdown을 생성한다. 변조·orphan start·누락 기록은 보고서 생성을 거부한다. 외부 경로·stderr·traceback을 공개 보고서에 넣지 않는다.

## 검증 증거

| 검증 | 결과 |
|---|---|
| evaluator 기존 baseline |147pass|
| pure 신규 RED |49fail: 신규 모듈/기능 부재|
| runner/report 신규 RED |25fail: 신규 모듈/명령 부재|
| 후속 경계 RED→GREEN |1pp Decimal 평균, 빈 정답 FP micro, onset winner guard, MIDI tempo, metric 귀속, 환경 보고, 설치 소스 변경|
| evaluator 최종 전체 |255pass/77.42초|
| root 기본 전체 |394pass/17skip/8deselected/28.08초|
| 실제 설치 metadata-only 확인 |두 후보 source/package/backend/checkpoint/lock 확인; 모델 import·추론·취득0|
| 환경/입력 보존 |5개 lock check offline exit0, baseline5lock+고정manifest SHA 일치|

root skip/deselected는 기본 opt-in·플랫폼 조건이며 실제 DB/모델 성공으로 세지 않는다. 이번 검증은 Windows에서 수행했다. Linux/CUDA 모델 실행 또는 정확도 수치를 새로 주장하지 않는다. fake worker 실제 프로세스로 success/exit3/exit4/malformed/missing/timeout/cancel/자손 정리를 확인했고, 세션 테스트로 preflight 실패·budget·외부 task 취소·71개 not_run·초과 원본 no_selection·보고서 변조 거부를 검증했다. 실제 FFmpeg preflight에서 반복된 PCM 바이트와 정확한 frame 수를 확인했다.

검증 경로: ignored `outputs/.verification-w05/task4-20261008/`. 최종 명령은 저장소 root에서 실행했다.

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task4-20261008/full-release --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -c pyproject.toml tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task4-20261008/root-final --tb=short
```

재실행 시 새 basetemp를 사용한다. 실행/report 명령과 설치 조건은 [평가기 README](../../tools/transcription-eval/README.md)에 있다.

## 환경과 지원 경계

metadata-only 확인: Python3.12.13, Basic Pitch0.4.0/source `049dc8a01a170c2370d7b246ec1c2067e060c3bf`/ONNX Runtime1.30.0, Piano0.0.6/source `0226e74cbc805660e34bbd6a8fed2083890ebb88`/torch2.10.0+cpu. Basic `nmp.onnx` SHA256 `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec`, Piano checkpoint SHA256 `c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141`.

공용/API/기존 workers·제품 provider/selector/schema·locks·frozen manifest는 변경하지 않았다. 제품 전사는 여전히 opt-in Basic Pitch다. Piano가 향후 선정되더라도 `selected_pending_integration`이며 자동 교체/fallback은 하지 않는다. MAESTRO는 비상업 연구·개인 개발 평가용 CC-BY-NC-SA-4.0, Piano checkpoint는 Qiuqiang Kong/Zenodo4034264/CC-BY-4.0이다. 원본 데이터·예측 배열·가중치를 Git에 추가하지 않는다.

설치 editable/data의 절대경로를 보존하기 위해 기존 checkout의 feature branch에서 작업했다. 별도 checkout은 환경·입력 경로 재구성이 필요하다. Task4를 독립 단위로 닫으며 실제 benchmark는 다음 Task5에서 수행한다.

## 독립 코드 리뷰·통합

2026-10-09 `/root/w05_task4_final_review` 최초 독립 **89/100** (요구22/오류21/검증23/구조14/문서9),B0/I4/M0. 대상 staged22파일 tree `f5126e51dfd37ffe83cd57412ee9a2415705214d`, raw-file snapshot SHA256 `A71B70659EDE24561102E1A82A97E3E011808DDD3015FC22F27657976793A4C7`. reviewer도 evaluator237pass/50.62초를 독립 실행했지만 suite 밖의 아래 문제를 재현했으므로 통합하지 않았다.

| Important | 처리·재현 회귀 |
|---|---|
| sustain macro 정확1pp 열세를 float 평균 오차로 보류 | 원시F1별 Decimal 차이 평균; 경계 아래/정확/위3개 검사 |
| MIDI byte cap을 unresolved로 분류해 후속 실행 지속 | parser 전 명시적 EvaluationLimitError; 실제 fake process와 남은71개 not_run 검사 |
| hash 일치 metrics의 census/velocity 문자열·범위·index 미검증 | 공통 full metric validator를 성공 기록 생성/집계/재독해에 적용; exact keys, bool 제외 정수/범위, pair/index/MAE/정렬/population 검사 |
| 공개 P/R·실패 원인·제외 분모와 두 reference operational recall 누락 | P/R/F1·gate·상태/귀속/코드·진단 연결·CPU 제외 개수와 key_release/sustain 각각의TP/예정분모 표시 |

지적 재현 테스트는 수정 전10fail/2pass, 수정 후12pass였다. 기존 worker/metrics/reference 구현은 바꾸지 않고 Task4 소비 경계를 보완했다. 추가 생성 경계4개와 reference별 다른TP 회귀를 포함한 preflight 실패 표시1fail과 paired 평균 효과1fail도 같은 지적 범위로 보완했다. 최종 전체 검증은255pass/77.42초로 통과했다. AGENTS.md의 명시적 미달 점수 재리뷰 규칙이 실행 스킬의 일반적인 재리뷰 생략 지침보다 우선한다.

범위 판단: 실제72회 비교는 Task5, Linux/CUDA 모델 지원은 별도 실제 증거가 필요하다. 모든 파일과 checksum을 함께 다시 작성하는 공격자에 대한 서명 진본성은 이번 계약에 없다. 원장 hash는 바이트 일관성 검증이며 신뢰된 발행자 인증을 주장하지 않는다. 해당 요구가 생기면 별도 신뢰 anchor와 실행/계획 검토가 필요하다. strict 수치 계약은 이 한계와 관계없이 강제한다.

최종 독립 재평가: 2026-10-09 `/root/w05_task4_final_review`, **100/100** (25/25/25/15/10),B0/I0/M0. BASE 대비 staged22파일 전체/tree `30f31010de484ac965ba63af91e6ff9f4e8da26f`, raw snapshot SHA256 `023901AB80E56EA07C15EEDCDC9362BF528FF976B8E31CCD5ECF9E1F19F9C7A4`. reviewer 독립254pass/75.56초와 최종 변경 경계24pass/5.47초, 구현자 최종전체255pass/77.42초를 구분해 확인했다. 미해결 지적0으로 통합 승인했다. 이후 변경은 이 점수·실제 결과·완료 체크와 통합 감사 기록뿐이다. 계획100점과 코드100점은 서로 별도 게이트이며 모델 F1이 아니다.
