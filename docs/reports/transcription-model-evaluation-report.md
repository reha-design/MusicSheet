# W05 실제 전사 모델 비교 결과

2026-10-10 KST · [승인 설계 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md) · [Task5 상세 계획 R1](../plans/w05-task5-live-comparison-plan.md).

고정 MAESTRO test12개×30초의 최초 CPU 비교에서 **Piano AMT를 해당 피아노 subset의 정확도 우승 후보로 선정**했다. 상태는 `selected_for_subset`, 근거는 `onset_accuracy`, 제품 상태는 **`selected_pending_integration`**이다. 제품 provider는 기존 명시적 opt-in Basic Pitch를 유지한다. Piano 제품 연결과 자동 fallback은 구현하지 않았다.

## 실제 결과와 해석

| 측정 | Basic Pitch | Piano AMT |
|---|---:|---:|
| 첫12개 onset macro F1 | 0.692689 | 0.970036 |
| onset micro P / R / F1 | 0.737729 / 0.620744 / 0.674200 | 0.978112 / 0.943884 / 0.960693 |
| sustain macro F1 | 0.222778 | 0.828873 |
| key-release macro F1 | 0.116453 | 0.370559 |
| CPU36회 중앙값 / nearest-rank p95 | 2.519367 / 2.736645초 | 72.499053 / 73.552422초 |
| 중앙값 / p95 RTF (30초 입력) | 0.083979 / 0.091221 | 2.416635 / 2.451747 |
| 예정 / 시작 / 성공 / 실패 / 미실행 | 36 / 36 / 36 / 0 / 0 | 36 / 36 / 36 / 0 / 0 |
| 같은 구간3회 동일 event hash | 12/12 | 12/12 |
| native velocity MAE (onset matching pairs) | null, 1,969 pairs | pooled 3.014362, 2,994 pairs |

Piano의 onset macro F1 우세는 **27.7348 percentage points**, paired recording bootstrap95% CI는 **[23.8872,31.8159]pp**이다. sustain 차이 CI도 **[54.0130,67.1327]pp**이며, onset micro guard와 sustain macro guard를 통과했다. 두 후보 paired nonempty12개, empty-reference 제외0, unresolved0, nondeterminism0, gate0으로 승인된 선정 조건을 충족했다. PCG64 seed20261005/10,000회 paired bootstrap·percentile linear를 사용했으며 결과를 보고 기준을 바꾸지 않았다.

Basic Pitch는 이 호스트에서 훨씬 빠르다. CPU 시간은 fresh process 시작·정리·출력 검증을 포함하고 metric 계산을 제외하므로 warm neural inference 속도로 해석하지 않는다. Basic은 ONNX 기본 thread 설정, Piano는 torch intra/inter-op1/1로 실행했으며 동일 thread 조건이라고 가정하지 않는다. 정확도 우승 기준을 충족했으므로 속도로 승자를 바꾸지 않았다. Piano의 key-release macro F1 0.371은 음표 길이의 제품 품질 검증 과제로 남는다.

Velocity MAE는 MIDI velocity1..127 native 값에 대한 절대 오차이며 pooled 값은 각 구간 MAE×pair 수를 합해 전체2,994 pairs로 나눴다. Basic native velocity가 null이므로 MIDI/activation에서 보충하지 않았다. 첫12개 censored prediction0, key-release reference0, sustain reference2이며 scoring onset[2,28), offset cap30의 승인 계약을 적용했다. 원시 matching pair index·정렬 입력·개별 score/RTF·예측 arrays는 ignored 원장에 보존했다. [검증된 자동 생성 보고서](../evaluations/transcription-model-selection.md)에 전체 P/R/F1/counts·구간별 MAE/pairs/censor·CPU sample·source/hash가 있다.

## 실행 증거와 재현

- 최초 세션 ID: `cpu-4859d3f14e324c509a5b36238d0736ae`.
- 원장: `outputs/w05-evaluation/task5-20261010/cpu-4859d3f14e324c509a5b36238d0736ae/` (ignored, 재현용 보존).
- Summary SHA256: `55a54fa1d7d2a970de1c8a27ed758e64e6707579dfd760061be773f9b764f992`.
- Manifest 파일 SHA256: `b3f664dd3c6372216712d3916639df017182c291d4e0f797b35aae3e51c7dfb9`.
- CLI 시작/종료: `2026-10-10T06:48:53.2882174+09:00` / `2026-10-10T07:37:19.8432201+09:00`, exit0. 원장 session elapsed2899.186776초; CLI 전체와 달리 입력 준비 전 단계는 제외한다.
- CC0 원본 PCM 반복 후 crop30 preflight4회 모두 성공. Basic4.765366/2.316158초, Piano99.342728/72.186464초. 보수적 예상5621.837071초<7200초. preflight는 정확도·36회 속도/실패 분모에서 제외했다.
- 본 평가72회 전부 성공, 자동 재시도0, 진단0, size 미검증 artifact0, 소유 `.part`0. 실행 후 Python 모델 자식이 남지 않은 것을 확인했다. 원시 결과·입력·checkpoint·이전 복구 bundle은 보존하고 공유 서비스/Docker는 변경하지 않았다.

Windows, evaluator Python3.13.7, worker Python3.12.13, CPU `Intel64 Family 6 Model 151 Stepping 2, GenuineIntel`, logical cores24, RAM68,572,536,832 bytes. Basic Pitch0.4.0/source `049dc8a01a170c2370d7b246ec1c2067e060c3bf`/ONNX Runtime1.30.0, Piano0.0.6/source `0226e74cbc805660e34bbd6a8fed2083890ebb88`/torch2.10.0+cpu/CPU float32 Note_pedal. 모델·옵션·lock 원본은 자동 보고서/세션 영수증과 일치한다.

실행 cwd `D:/develop/MusicSheet`. 설치·다운로드 없이 사전 준비한12개 input/reference 전체 hash 및 metadata-only 후보 검사를 통과한 후 다음 명령을 **한 번만** 실행했다.

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 transcription-eval run --manifest D:/develop/MusicSheet/docs/evaluations/maestro-w05-manifest.json --input-root D:/develop/MusicSheet/outputs/w05-evaluation/task2-20261006 --basic-python D:/develop/MusicSheet/services/ml/basic-pitch-worker/.venv/Scripts/python.exe --piano-python D:/develop/MusicSheet/services/ml/piano-amt-worker/.venv/Scripts/python.exe --checkpoint "D:/develop/MusicSheet/models/w05/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth" --checkpoint-sha256 c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141 --output-root D:/develop/MusicSheet/outputs/w05-evaluation/task5-20261010 --ffmpeg C:/ffmpeg-6.0-essentials_build/ffmpeg-6.0-essentials_build/bin/ffmpeg.exe
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 transcription-eval report --run-dir D:/develop/MusicSheet/outputs/w05-evaluation/task5-20261010/cpu-4859d3f14e324c509a5b36238d0736ae --output D:/develop/MusicSheet/docs/evaluations/transcription-model-selection.md
```

두 번째 명령은 기존 원장을 검증하고 새 Markdown을 작성한다. 같은 output report를 덮어쓰지 않는다. 입력 변경·silence-tail 교체·sample 축소·임의 재실행을 하지 않았다. CLI exit0 외에 `load_verified_run`의 artifact inventory·hash·start/terminal·72 schedule·metrics·derived decision 검증과 별도 native 출력 재검증을 통과했다. hash는 바이트 정합성 검증이며 서명된 발행자 인증은 아니다.

## 회귀와 captured-session 검증

각 프로젝트의 offline lock check와 명시적 pytest config/test 경로 collect-only를 통과했다. 실제 평가에 테스트 부하가 섞이지 않도록 다음 full suite를 모두 모델 세션 전에 완료했다. 각 실행은 새 basetemp를 사용했다. evaluator는 기존 locked environment를 offline sync했고 공용 metric/process imports를 확인했다.

| 프로젝트 | collect | 실제 full suite | 시간 |
|---|---:|---|---:|
| root Python3.13 | 419 (8 deselected) | 394pass / 17skip / 8deselect | 13.56초 |
| API Python3.13 | 265 | 232pass / 33skip | 2.02초 |
| Basic worker Python3.12 | 46 | 46pass | 22.39초 |
| Piano worker Python3.12 | 72 | 71pass / 1skip | 0.81초 |
| evaluator Python3.13 | 266 | 265pass / 1skip | 174.48초 |

root/API의 skip은 외부 DB/Redis/모델 환경·OS 전용 경계·symlink 권한 등의 조건부 검증이며 이 실행에서 실서비스/Linux 검증으로 계산하지 않는다. Piano worker의 skip은 실제 모델 smoke opt-in이다. evaluator의 skip은 새 captured-session opt-in이다. 기본 suite에서 실제 모델을 실행하지 않았다. 정확한 명령/config는 [상세 계획](../plans/w05-task5-live-comparison-plan.md)의 프로젝트 표를 따른다. 로그는 `outputs/.verification-w05/task5-20261010/`의 collect/full/lock별 파일이다.

실제 세션 종료 후 `MUSICSHEET_W05_LIVE=1`, `MUSICSHEET_W05_RUN_DIR=<위 절대 run 경로>`로 **test_live_evaluation.py만** 실행해 **11pass/8.06초**를 확인하고 환경을 복원했다. 그중10개는 설정 누락/상대 경로·manifest/order/model/lock 변조 경계, 1개는 실제 원장·고정12개 원본/derived/reference·CPU candidate/source/hash·native default options·JSON/MIDI/event hash를 검증한다. 모델 추론을 다시 실행하지 않았다. 무결성 PASS와 benchmark 성공은 별개이며 이번에는 실제72 success와 선정 gate도 모두 통과했다. 새 통합 검증은 최초 실행부터 GREEN이었고 가짜 RED를 만들지 않았다.

5개 lock·frozen manifest 물리 SHA256은 실행 전후 동일하다. 모델 자산 hash도 live test에서 재확인했다. 새 코드는 evaluator tests뿐이며 제품 API/worker/schema/provider/selector/의존성을 바꾸지 않았다. 문서 로컬 링크·diff·추적 바이너리/secret 검사는 통합 전 게이트로 기록한다.

## 범위와 후속 작업

이번 선정은 **비상업 연구·개인 개발용 MAESTRO classical solo piano test12개 고정30초/Windows CPU** 결과에 한정된다. dataset CC-BY-NC-SA-4.0, Piano checkpoint Qiuqiang Kong/Zenodo4034264/CC-BY-4.0. Linux/CUDA 실제 모델, YouTube 전체 곡, 혼합 악기·보컬 성능으로 확대하지 않는다. 실제 YouTube 변환은 W09, 음원 분리와 solo piano bypass는 W06의 별도 범위다.

W05의 두 후보 유효 CPU 비교·선정 근거를 확보하고 Task5 단위와 전체 W05 독립 리뷰를 모두 통과해 평가·선정을 완료했다. Piano를 제품에 적용하려면 별도 연결 계획·schema/capability·작업 취소/시간 제한·실제 출력/DB 등록 검증이 필요하다. 현재 fallback 가능한 provider는 사전 설치·검증·통합된 Basic Pitch의 명시적 설정뿐이며 자동 교체하지 않는다.

## 독립 리뷰·통합

계획 R1은 2026-10-10 `/root/w05_task5_plan_review` **99/100 (25/20/20/25/9),B0/I0/M1**. 리뷰한 본문 SHA256 `C6901075ED079B53D0CB5AAE273742B2BF0077D584291B38F41FC56B5C50FB62`. 실행 root의 README 일반 예시와 날짜 포함 경로 차이를 실제 명령에 명시해 minor를 처리했다.

Task5 독립 코드 리뷰: 2026-10-10 `/root/w05_task5_code_review`, **100/100 (25/25/25/15/10),B0/I0/M0**. BASE `ce84a3b47bd939d3099bd604dbec34380d7a3a0b` 대비 staged10파일/tree `1c5eb8ed307bb0e2b340c72ef32a4c3e77d367d3`, raw snapshot SHA256 `2BBC251DFD7B4FA1CE0ACDB8CD6DA64C2DA1C2CD1C3D14CC5AE730860816D243`. reviewer가 실제 captured11pass/7.64초·default10pass1skip/2.16초를 독립 실행했다. 첫24개 결과를 고정 reference/normalized events로 직접 재채점해 불일치0, baseline hash와 수치/제품 경계 일치를 확인했다. 전체5suite는 구현자 로그를 확인했으며 독립 재실행으로 표현하지 않는다. 미해결 지적0이다.

Task5 최종 문서 변경 재확인: 동일 reviewer **100/100,B0/I0/M0**, tree `fbbef25ffd6d16ebc1792d314e8b23abe85f9f97`, 최종 snapshot SHA256 `BB5AEF1D20FED0F7D5ACC87B9AFD0FCE15CCF8683D67C980A78F4A99AE60C6B0`. 구현·테스트·원장 변화 없이 실제 평가 CPU 환경/제품 대기 상태와 점수 기록만 갱신했으며 추가 테스트를 반복하지 않았다.

별도 fresh 전체 W05 리뷰: 2026-10-10 `/root/w05_whole_final_review`, **100/100 (25/25/25/15/10),B0/I0/M0**. W05 시작 기준 `9d5e66228b87de5a4c439c554dbc4204f714db39`부터 현재 evaluator/Piano worker·계약·tests·승인 R2·Task1–5 계획/보고서·고정 입력·실제 원장·제품 경계를 검토했다. 최종 검토 tree/snapshot은 위 `fbbef25`/`BB5AEF1D…`와 같다. 단위 리뷰와 전체 리뷰를 별도로 평가했다.

전체 reviewer 독립 증거: captured/selection/metrics/reference/determinism **96pass/27.15초**, Piano worker full **71pass1skip/0.76초**. 원본 MIDI12개 전체 파싱→crop/scoring으로 frozen reference12/12 일치, 최초24개 직접 재채점24/24 일치, summary hash·macro·CPU36 samples/median/p95 재집계 일치를 확인했다. 새 basetemp `whole-review-tests-20261010-a`/`whole-review-worker-20261010-a`를 사용했고 추론·다운로드·실제 benchmark 재실행은 하지 않았다. 미해결 지적0으로 W05 평가·선정 완료를 승인했다.

이후 변경은 실제 리뷰 점수·완료 색인·통합 감사 기록뿐이다. 계획 점수와 구현 점수는 모델 F1과 서로 다른 값이다. PR·병합 SHA와 branch 정리 결과는 실제 통합 후 아래에 기록한다.
