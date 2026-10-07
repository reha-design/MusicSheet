# W05 Task3 — 격리 Piano AMT worker와 공식 checkpoint

2026-10-07 · 기준 `f518ee19a8653feeff04b982dd7fea6c9a6ca0bb` · `codex/w05-piano-amt-worker`.

독립 Python3.12 Windows CPU 환경에 고정 ByteDance Piano AMT 후보와 평가 전용 CLI를 추가했다. 공식 checkpoint의 안전 로딩과 실제30초 CC0 입력의 JSON/MIDI 출력을 검증했다. 제품 provider 등록·selector·API·Celery 동작은 변경하지 않았다. 이번 결과는 **실행 호환성 검증**이며 MAESTRO 정확도·모델 선정 결과가 아니다. R7 독립 계획99점·코드 재리뷰100점/미해결 지적0으로 Task3를 완료했다. Task4/5는 미시작이다.

## 범위와 계약

[승인 설계 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md), [실행 계획 R7](../plans/transcription-model-evaluation-implementation-plan.md)의 Task3다. 새 독립 프로젝트는 `services/ml/piano-amt-worker`, 준비 모듈은 evaluator의 `checkpoint.py`다. evaluator에는 모델을 import하지 않는다. root/API/기존 Basic Pitch의 코드·pyproject·locks 및 Task2 manifest는 보존했다.

- CLI: `piano-amt-worker --input-audio <abs> --output-dir <new abs> --checkpoint <abs> --checkpoint-sha256 <hex> --device cpu`.
- `run_prediction(audio_path:Path,*,checkpoint:Path,device:str)->dict`.
- `write_outputs(output_dir:Path,prediction:dict,*,input_sha256:str,checkpoint_sha256:str,device:str)->None`.
- `prepare_checkpoint(destination:Path)->dict[str,object]`는 모델 없는 준비 단계이며 유효 cache를 network0으로 재검증한다.

입력은16000Hz monoPCM16·완전한1~480000frames다. regular/non-symlink/non-junction 절대경로와 checkpoint exactsize/MD5/SHA256을 먼저 검사한다. model/source 검증 및 import는 추론 시 지연 실행한다. CPUfloat32·torch intra/inter-op1·segment160000·onset.3/offset.3/frame.1/pedal_offset.2를 고정했다. 고정 upstream의 실제 기본값과 실행 시 다시 대조한다. 가중치의 존재·크기 검증 뒤 explicit path를 전달하므로 upstream 누락 파일 다운로드 분기에 들어가지 않는다.

출력 `raw_transcription.json`은 wire version1·source/package/model/checkpoint/inputhash/device/dtype/options/runtime·duration/notes/pedals를 기록한다. confidence를 만들지 않는다. strict int/bool 구분·finite·pitch21..108·velocity1..127·sustain value64..127·`0<=onset<offset<=duration+1`을 검사한다. 빈 출력은 유효하다. JSON8MiB/MIDI16MiB와 전체100000 MIDIevents(tempo/EOT 포함)를 제한한다. MIDI는384ticks/beat·tempo500000, 원래 시간으로 정렬한 뒤 tick을 내림한다. 같은 실제 시각의 note-off/pedal-up을 note-on/pedal-down보다 먼저 기록한다. 양자화 후에도 positive interval이어야 하며 Mido 전체 재파싱으로 channel/pitch·CC64 상태를 복원하고 기대 quantized tuple Counter와 비교한다. unmatched/overlapping/open/zero-tick interval은 OutputValidationError/exit4로 publication 전에 거부하며 raw event를 조정하거나 버리지 않는다. 새 directory에 exclusive publish하며 실패 시 소유 파일만 정리한다.

Exit0은 성공/help,2는 arguments/input/checkpoint setup,3은 모델 추론 exception,4는 원시 출력 검증·publish 오류다. 진단은 입력값/경로/예외 원문을 출력하지 않는다. 모델 imports/network를 금지한 별도 interpreter의 import/help 테스트도 통과했다.

## 설치·출처·가중치 증거

| 항목 | 실제 값 |
|---|---|
| Windows Python | 3.12.13,64bit AMD64, win32 |
| model/package/source | Note_pedal /0.0.6 /`0226e74cbc805660e34bbd6a8fed2083890ebb88` |
| torch / CUDA | 2.10.0+cpu /None, availableFalse |
| numpy/librosa/torchlibrosa | 2.5.3 /0.11.0 /0.1.0 |
| soundfile/mido/setuptools | 0.13.1 /1.3.3 /80.10.2 |
| numba/llvmlite | 0.68.0 /0.50.0 |
| 새 worker lock SHA256 | `3c97296a2ae6af71230cc79117d2b1df4d35ed20c764618fb94235133708b6e5` |
| checkpoint filename | CRNN_note_F1=0.9677_pedal_F1=0.9186.pth |
| checkpoint bytes / MD5 | 171966578 /`22b961b77c1878239fec963362097045` |
| checkpoint SHA256 | `c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141` |
| 취득 / 안전 state probe elapsed | 351.0818649초 /5.3967254초 |
| state 검증 | 540개 exactkeys/shape/dtype/finite,475float32+65int64 |

실제 설치/기본 import와 direct_url의 Git commit을 확인했고 `uv lock --check --offline`은55packages resolved로 통과했다. torch에만 [공식 CPU index](https://download.pytorch.org/whl/cpu)를 연결했다. [고정 inference source](https://raw.githubusercontent.com/qiuqiangkong/piano_transcription_inference/0226e74cbc805660e34bbd6a8fed2083890ebb88/piano_transcription_inference/inference.py)와 [Note_pedal source](https://raw.githubusercontent.com/qiuqiangkong/piano_transcription_inference/0226e74cbc805660e34bbd6a8fed2083890ebb88/piano_transcription_inference/models.py)를 대조했다.

[공식 Zenodo metadata](https://zenodo.org/api/records/4034264)의 record/license/file/size/MD5를 확인하고 metadata가 반환한 `https://zenodo.org/api/records/4034264/files/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth/content`로 취득했다. [릴리스](https://zenodo.org/records/4034264)의 CC BY4.0이며 저자는 Qiuqiang Kong이다. filename의 F1 숫자는 이번 평가의 점수가 아니다. weights는 ignored `models/w05`에 보존하고 공개 저장소에 넣지 않는다. HTTP identity·status200·no redirects/credentials/cookies·metadata4MiB/transfer180MiB·I/O inactivity60초/총10분·exactsize/MD5/SHA256 및 owned .part cleanup을 적용했다. R7은 AsyncClient와 asyncio.timeout으로 headers/body 대기 중에도 전체 deadline을 적용한다. 미캐시 준비는 active event loop 밖에서 sync 함수로 호출한다. 잘못된 기존 cache/다른 .part는 보존한다.

최초 safe `torch.load(...,map_location='cpu',weights_only=True)`는 성공했지만 단일 flat state로 비교한 검사에서 key mismatch가 발생했다. 공식 파일은 `model.note_model`과 `model.pedal_model`에 OrderedDict를 저장하고 pinned load_state_dict도 이를 소비한다. 읽기 전용 진단으로 검증용 평탄화 후540개 tensor가 모두 일치/유한함을 확인했다. **R6 계획을 독립 재평가한 뒤** 정확한 group·stringkey·Tensor·shape·dtype·NaN/Inf 거부를 구현했다. checkpoint 파일 변환·unsafe pickle·weights_only=False·버전 downgrade는 없다. 공식 파일로 safe probe를 재실행해 통과했다.

## 실제 CC0 smoke와 지원 범위

source는 [기존 CC0 fixture 출처](../../tests/fixtures/audio/README.md)의16초 피아노 녹음이다. fixture SHA256 `2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a`,22050Hz monoPCM16·352800frames를 확인했다. float64 WAV→FFmpeg6.0 swr(filter_size32,phase_shift10,linear_interp1,cutoff.97,DOUBLE,no dither)→기존 pcm16 ties-to-even 포화 변환으로16000Hz·256000frames를 만들었다. 파생16초 WAV SHA256은 `17d18e962c1e36aefbce59d891139630eba5666c9ae6f4d18c00192d593fa7bb`다.

첫16초 실제 추론은87notes/10pedals를 냈으나4notes의 offset이19.9899997711까지 늘어나 duration+1=17 한도를 넘었다. pinned upstream은10초 segment padding 후 sample 수로 frame 결과를 slice하므로 padded tail이 남는다. 이 결과는 실패로 보존했다. 첫 CLI는 validation exception을 추론 exception으로 묶어 exit3을 반환했고, RED→GREEN으로 OutputValidationError를 구분해 계획의 exit4로 수정했다. 16초 실패를 유효 성공으로 바꾸지 않는다.

W05의 고정30초 입력 조건을 검증하려고 같은16초 전체 녹음 뒤14초 PCM zero를 붙였다. input480000frames/30초 SHA256 `aa1c2973661d8e9bda6647d9fe2666b0721cdae31afe1811e1b4a3679912f3d9`다. threshold나 모델 출력은 조정하지 않았다. 이 합성 길이 확장은 compatibility smoke이며 MAESTRO12개 선정·입력·manifest를 바꾸지 않는다.

| 실제30초 CPU smoke | 값 |
|---|---|
| 실행 결과 / 소유 자식 정리 | exit0 /run_owned_process 반환 전 확인 |
| monotonic elapsed (설치·취득 제외) | 68.4865956초 |
| notes / pedals / MIDIevents | 87 /10 /196 |
| JSON / MIDI bytes | 8513 /791 |
| JSON SHA256 | `eaf9071fb72a54f8d3ab03fecab6992d155b1d93891c97dc5017e7655f3ea808` |
| MIDI SHA256 | `d630e07f6e32c84f573cdd04b54919129757ae6d618138f734513922f98b7e36` |
| validation | strict wire/provenance/interval＋pre-mido cap＋전체 MIDI parse＋key-release note/pedal count 일치 |

추론 argv는 worker Python의 `-I -m musicsheet_piano_amt_worker.cli`이며 기존 소유 프로세스 gate·WindowsJob·timeout300·제한 env를 사용했다. evaluator는 모델을 import하지 않고 완성 출력만 검사했다. `outputs/w05-evaluation/task3-20261006-smoke`와 검증 원장 `outputs/.verification-w05/task3-20261006/`는 ignored로 보존했다. receipt는 checkpoint/model-probe/smoke-audio/smoke-30s-audio/actual-smoke JSON과 padding-diagnostic JSON이다.

확인된 지원 조건은 **Windows/Python3.12/torch2.10 CPU·이번30초 입력**이다. 짧은 비10초 배수 입력은 upstream padding 때문에 출력 시간 검증에 실패할 수 있다. Linux/CUDA·MAESTRO F1·기본 모델 결정은 미검증이다. 성능 비교·반복 hash·실패 attribution은 Task4/5에서 측정한다.

## TDD·회귀·재현 명령

작업 root는 `D:/develop/MusicSheet`, 공통 env는 PYTHONUTF8=1, cache outputs/.uv-cache다. pytest에 프로젝트별 `-c`·명시적 test path·신규 절대 basetemp를 지정했다. collect-only의 worker header가 Python3.12/worker pyproject이고37tests만 모으는지 먼저 확인했다. checkpoint도 해당 evaluator config로12tests를 수집했다.

RED는 worker33fail/4error·inference1fail/7error·checkpoint12error로 미구현 모듈을 확인했다. Model fake의 kwargs와 HTTPX mock의 SyncByteStream fixture 오류는 설치/제품 실패로 세지 않고 바로잡았다. 이후 raw bool/string3fail, MIDI short-note1fail, R6 정상 nested state1fail, finite NaN/Inf2fail, raw output exit4 분리1fail을 각각 본 뒤 수정했다.

| 최종 기본 회귀 | 결과 |
|---|---|
| 새 worker 전체, 모델/network 없음, R7 | 71pass/1skip(실제 모델 opt-in),0.55초 |
| evaluator 전체, R7 | 147pass,11.39초 |
| root 제품 전체 | 394pass/17skip/8deselected,20.50초 |
| API 전체 | 232pass/33skip,1.59초,기존 Starlette deprecation1 |
| 기존 Basic Pitch worker | 46pass,21.87초,기존 pkg_resources warning1 |

root17skip은 미설정 opt-in 실제환경/플랫폼/링크 조건이며 API33skip은 DB/Redis opt-in이다. 이 회귀로 실제 DB·Linux·Celery live 검증을 새로 수행했다고 주장하지 않는다. 기존4개 lock SHA256은 root90426204…, API786088B4…, Basic2D7D8128…, evaluator9DCA0FCD…로 시작 시 값과 일치했고 manifestB3F664DD…도 불변이다.

실행한 mock/full 명령(아래 label의 basetemp는 재실행 시 새 이름으로 바꾼다):

```powershell
uv --cache-dir outputs/.uv-cache sync --locked --project services/ml/piano-amt-worker --python 3.12
uv --cache-dir outputs/.uv-cache lock --check --offline --project services/ml/piano-amt-worker --python 3.12
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/piano-amt-worker --python 3.12 pytest -c services/ml/piano-amt-worker/pyproject.toml services/ml/piano-amt-worker/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task3-20261007-r7/worker-green --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task3-20261007-r7/eval-green --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task3-20261006/root-final --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/api --python 3.13 pytest -c services/api/pyproject.toml services/api/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task3-20261006/api-final --tb=short
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/basic-pitch-worker --python 3.12 pytest -c services/ml/basic-pitch-worker/pyproject.toml services/ml/basic-pitch-worker/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task3-20261006/basic-pitch-final --tb=short
```

현재 workspace의 ignored 검증 script와 실제 receipt를 재현하는 명령이다. `probe_model.py`는 worker 환경에서만 모델을 import하며 safe load·전체 state gate가 통과해야 model-probe-receipt를 작성한다. owned_smoke는 output destination을 신규 경로로 바꾸고 실행한다. fresh checkout에서 smoke WAV는 위 명시한 FFmpeg 변환과14초 PCM zero 부착 절차로 준비한다.

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 python outputs/.verification-w05/task3-20261006/prepare_checkpoint.py
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/piano-amt-worker --python 3.12 python outputs/.verification-w05/task3-20261006/probe_model.py
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 python outputs/.verification-w05/task3-20261006/owned_smoke.py
$env:MUSICSHEET_W05_LIVE='1'
$env:MUSICSHEET_PIANO_AMT_AUDIO='D:/develop/MusicSheet/outputs/.verification-w05/task3-20261006/smoke-30s-16000.wav'
$env:MUSICSHEET_PIANO_AMT_CHECKPOINT='D:/develop/MusicSheet/models/w05/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth'
$env:MUSICSHEET_PIANO_AMT_CHECKPOINT_SHA256='c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141'
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/piano-amt-worker --python 3.12 pytest -c services/ml/piano-amt-worker/pyproject.toml services/ml/piano-amt-worker/tests/test_live_model.py -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/task3-20261006/live-test --tb=short
```

실제 opt-in test는 **1pass/67.91초**로 통과했다. 합격 기준은 exit0·고정 source/checkpoint/device/dtype·strict JSON·유효 전체 MIDI이며 정확도 합격 기준이 아니다.

## R7 보완 검증

2026-10-07 계획 게이트 후 velocity0·sustain0/63·동일tick note/pedal·동일pitch/pedal overlap 거부 테스트에서 **7fail/27pass**를 먼저 확인했다. HTTP metadata headers/body·weights 첫 chunk 뒤 대기 및 active caller loop 테스트는 **4fail/15pass**였다. 기존 동기 구현은0.1초 전체 deadline에도 각0.50초를 기다렸다. R7 구현 후 worker71pass/1skip·evaluator147pass로 통과했다. 첫 MIDI RED 실행은 새 basetemp의 parent 누락으로 setup error였고 RED 증거에 포함하지 않았다. parent 생성 뒤 행동 불일치7fail만 RED로 기록했다.

deadline 회귀는0.1초 total/0.5초 중간 대기로 in-flight 취소를 검증하고 elapsed<0.4초·후속 yield0·stream/client close·닫힌 loop/pending task0·소유 part0·기존 marker 보존을 확인한다. active loop 거부는 coroutine/network/file 생성0·RuntimeWarning0을 확인해 R7 계획 minor를 처리했다. MIDI 회귀는 velocity1/127·sustain64/127·정확히1tick·동시 다중pitch·재타건·빈 결과를 유지한다.

모델/source/weights/options/locks가 동일하므로 새 신경망 추론과171MB 취득을 반복하지 않았다. 기존 실제30초 추론의 native87notes/10pedals를 새 writer로 `outputs/w05-evaluation/task3-20261007-r7-replay`에 재발행했고 JSON8513bytes/MIDI791bytes와 두 SHA256이 기존 smoke와 **byte-identical**임을 확인했다. evaluator pre-mido gate/strict full parse에서도87notes/10pedals가 일치했다. 새 async transport로 공식 metadata4144bytes를 bounded read하고 record/license/size/MD5/URL을 재검증했으며 client close를 확인했다. 기존 실제 checkpoint는 HTTP client 생성 금지 상태에서 exactsize/MD5/SHA256 재검증을 통과했다.

R7 receipt/script는 ignored `outputs/.verification-w05/task3-20261007-r7/`의 `replay_output.py`, `verify_preparation.py`, `replay-receipt.json`, `preparation-receipt.json`이다. replay destination은 재실행 시 새 경로로 바꾼다.

```powershell
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/piano-amt-worker --python 3.12 python outputs/.verification-w05/task3-20261007-r7/replay_output.py
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 python outputs/.verification-w05/task3-20261007-r7/verify_preparation.py
```

## 독립 리뷰 기록

계획 R5의100점으로 초기 Task3를 시작했고 실제 state probe 뒤 R6로 갱신했다. R6의 독립 reviewer `/root/w05_task3_r6_plan_review`,2026-10-06,본체 SHA256 `61ABE33121F2ACFE30BDB15F744CF6300FCB7AE918978F80A81290B5D8C4E566`,요구25/범위20/순서20/검증24/재현10=99점,blocker0/important0/minor1이었다. minor 실제 probe/opt-in 명령은 위 명령·receipt·합격 기준으로 처리했다. 계획99점은 코드 리뷰 점수를 대체하지 않는다.

R7은2026-10-07 `/root/w05_task3_r7_plan_review`가 본체 SHA256 `0F8E4F27571D11F7F75DDB57DA1A4DCCF71CA5F2E070C3C3A7A74B55F1707754`를 독립 평가했다. 요구25/범위20/순서20/검증24/재현10=**99점**,blocker0/important0/minor1이다. minor active-loop 회귀는 위 RED/GREEN으로 처리했고 승인 후에만 두 제품 보완을 구현했다.

Task3 초기 독립 코드 리뷰는2026-10-07 `/root/w05_task3_final_review`가 시행했다. BASE `f518ee19a8653feeff04b982dd7fea6c9a6ca0bb` 대비 staged22파일 전체, tree `248a946e85710f0962c7a3c1a4387c37eccc3ec9`, 원장 `outputs/.verification-w05/task3-20261006/review-snapshot.json` SHA256 `4E08BB4B742446BAA2D1078F5E02303C291515E0998ADFCCF0F84EFEBDA4E7AE`의22개 파일 hash를 직접 대조했다. 독립 worker62pass/1skip·evaluator143pass·실제 smoke 두 파일 hash 일치를 확인했다.

| 코드 리뷰 | 요구 /25 | 오류 /25 | 검증 /25 | 구조 /15 | 문서 /10 | 총점 | 미해결 blocker/important/minor |
|---|---:|---:|---:|---:|---:|---:|---|
| 초기 R6 구현 | 23 | 23 | 23 | 15 | 10 | **94** | **0/2/0** |
| R7 보완 재리뷰 | 25 | 25 | 25 | 15 | 10 | **100** | **0/0/0** |

important1은 velocity0의 note-off 해석과 동일 tick으로 양자화되는 positive interval 때문에 JSON 음표가 유효한 MIDI 음표로 표현되지 않는 문제다. sustain value<64도 같은 경계를 가진다. important2는 동기 read 중600초 전체 deadline이 즉시 적용되지 않아599초부터658초까지 기다리는 문제다. 주 구현자도 velocity0/동일tick은 memory-only 재현으로 확인했다. R7 계획99점과 위 RED/GREEN으로 두 지적을 보완했고 독립 재리뷰에서 해결을 확인했다.

2026-10-07 KST `/root/w05_task3_final_review`가 BASE `f518ee19a8653feeff04b982dd7fea6c9a6ca0bb` 대비 staged22파일 전체, tree `d1c6936a9b085ccefec8eb57dbad4c98adec8481`를 재검토했다. 새 원장 `outputs/.verification-w05/task3-20261007-r7/review-snapshot.json` SHA256 `C355FE42C1B0E2F90378AA62A540A461C7E3E1224C943106389DECBDD0A5C8A1`의22개 hash와 staged tree를 시작/종료 시 대조했고 코드/index/HEAD 변경은 없었다. 독립 worker71pass/1skip·evaluator147pass·기존 실제 smoke의 메모리 재처리와 재발행 byte equality·strict parse87notes10pedals·staged diffcheck를 확인했다. **코드100점/B0/I0/M0으로 통과**했으며 이 점수는 계획99점과 별도다. 현재 리뷰 결과 기록만 이 검토 snapshot 뒤에 추가했다.

Reviewer가 판단에서 제외한 정상 quantization 오차(384PPQ 명시), 검증 후 외부 파일 교체 경쟁(불변 경로 전제), 문서화된 short padding/Linux/CUDA/정확도 제한, Task4/5 부재는 범위 밖으로 판단한 근거가 타당하여 유지한다. 이는 지적된 MIDI 의미 오류나 hard deadline 실패를 제외하는 근거가 아니다. Task4 runner/선정과 Task5 실제12개 비교는 아직 시작하지 않았다.
