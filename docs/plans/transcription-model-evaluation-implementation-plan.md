# W05 Transcription Model Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (주 에이전트 구현) 또는 사용자 선택 시 superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. 모든 방식에서 AGENTS.md의 단위별 독립95점 게이트를 유지한다.

**Goal:** 고정 MAESTRO test12개/30초 입력으로 Basic Pitch와 ByteDance의 정확도·실행 신뢰도·CPU 시간을 비교하고 선정/대체 정책 보고서를 만든다.

**Architecture:** 독립 Python3.13 평가기가 정답/metric·manifest·실행 기록·선정을 담당한다. 사전 설치한 Python3.12 후보는 기존 소유 프로세스 경계로 실행하며 데이터 준비와 inference를 분리한다. 제품 registry·schema·API·Celery 동작은 변경하지 않는다.

**Tech Stack:** uv, Python3.13 evaluator, Python3.12 workers, mir_eval0.8.2, NumPy, mido1.3.3, HTTPX0.28.1, stdlib zipfile, FFmpeg, Basic Pitch0.4.0 ONNX CPU, ByteDance inference0.0.6/PyTorch CPU.

**Spec:** [사용자 승인 설계 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md), [전사](../ai/transcription.md), [모델 경계](../ai/model-adapters.md), [정답 이벤트](../domain/note-events.md).

Plan Revision3 · 2026-10-05 · 기준 `7ecfd90`, branch `codex/celery-orchestration`. 설계 R2 사용자 승인: 수정본 제시 뒤 `진행` 응답. **작성된 계획의 검토/실행 확인은 대기**. 권장 방식은 기존 주 에이전트 구현＋단위별 독립 reviewer다. 독립 점수는 마지막 리뷰 기록에서 확인한다. Task1~5는 미시작이다.

## Global Constraints

- evaluator `>=3.13,<3.14`, worker `>=3.12,<3.13`. root/API/기존 Basic Pitch pyproject·locks, selector·공용 schema·registry 변경 금지. evaluator/root/API에 모델 import 금지.
- Basic Pitch0.4.0 source `049dc8a01a170c2370d7b246ec1c2067e060c3bf`, `nmp.onnx`,22050Hz mono. ByteDance0.0.6 source `0226e74cbc805660e34bbd6a8fed2083890ebb88`, `Note_pedal`,16000Hz mono. source/lock/checkpoint/hash/device/dtype/options 고정.
- ByteDance checkpoint171966578bytes·MD5 `22b961b77c1878239fec963362097045`, Zenodo4034264 CC BY4.0. SHA256은 취득 후 계산; 파일명의 F1은 측정값 아님. runtime 설치/다운로드·shell·credential 전달 없음.
- MAESTROv3.0.0/test와 v2.0.0/test 일치·유일 경로·유한 duration>=90. 선정 해시 입력은 ASCII `MusicSheet-W05-R1`＋LF byte0x0A＋UTF8 filename, crop은 ASCII `MusicSheet-W05-R2-CROP`＋같은LF＋UTF8 filename이다. Python 표현은 `b"MusicSheet-W05-R1\n"`, `b"MusicSheet-W05-R2-CROP\n"`. 선정 hash 순 앞12개, crop은 big-endian hash modulo `(floor(duration)-30+1)`. 실패 시 곡/구간 대체 금지.
- PCM16 stereo→float64 mono `(L+R)/2`→swr(filter_size32,phase_shift10,linear_interp1,cutoff0.97,float64)→clip/ties-to-even·포화 PCM_S16LE, no dither. 입력30초, onset `[2,28)`, 양측 metric offset cap30초·절단 수 기록.
- onset50ms·pitch50cents·strictFalse·offset ratio.2/min50ms·Hz 변환. P/R/F1/TP/FP/FN·macro/micro 분리. 빈 reference null, 첫 정확도12개만 집계·nonempty pair>=8.
- 후보당36개 fresh process CPU 직렬 slot. 반복0/2: 녹음 순·각 Basic→ByteDance; 반복1: 녹음 역순·각 ByteDance→Basic. GPU 별도 조건·분모·run ID, CPU 결과로 Linux/CUDA 지원 주장 금지.
- 추론 timeout300초·CPU 세션7200초·실패 자동 재시도0. 진단 slot별 최대1회는 정확도/36회/시간에서 제외하고 budget에는 포함. 첫 accuracy12/12 유효; 같은 모델 오류2회 재현만 운영 부적격. nondeterminism/unresolved는 검토 보류.
- JSON8MiB/MIDI16MiB·일반 파일·비-symlink·strict wire/provenance·유한 값. 원본 note/pedal padding offset<=31초, metric에서는30초로 자름.
- metadata 각각4MiB·ZIP directory/read 최대16MiB·member 해제2GiB·전송6GiB(재시도 포함)·해제8GiB·최소여유10GiB·HTTP 요청60초/취득30분/재시도2회. archive 전체 다운로드 금지.
- raw/derived audio·MIDI·reference 배열·예측·ledger는 ignored `outputs/w05-evaluation/`, weights는 `models/`. tracked manifest/report는 source/license/hash/crop/metrics만 포함, dataset 재배포 없음.

## Review Focus

1. 같은 시각 tempo/note-off/note-on/CC64 충돌: 안정 순서와 재타건·sustain 경계 보존 (Task1 `test_simultaneous_tempo_restrike_pedal`).
2. Windows 경로·case 충돌·symlink: workspace staging 밖 쓰기/읽기와 manifest 변조 거부 (Task2 `test_member_case_collision_and_symlink`).
3. HTTP200·gzip·object 교체: body 소비 전 거부, 제한된 재시도/rollback (Task2 `test_range_200_never_reads_body`).
4. 정상 출력 직후 취소/정리 실패: 자식/I/O 정리 확인 전에 측정 성공 처리 금지 (Task4 `test_cancel_after_valid_output_not_success`).
5. 진단 성공이 실패를 덮거나 float 차이가 winner를 만듦: 원시 ledger 유지·결정성/선정 보류 (Task4 `test_diagnostic_success_preserves_failure`, `test_one_bit_output_change_blocks_selection`).

## 파일 구조·공통 계약

Evaluator: `tools/transcription-eval/src/musicsheet_transcription_eval/`, tests: 같은 프로젝트 `tests/`. CLI `transcription-eval`, module `musicsheet_transcription_eval`. pyproject.toml·uv.lock·README.md·tests/conftest.py를 만든다. 별도 uv 프로젝트이며 sources는 common/storage/pipeline 각각 `../../packages/<name>` path로 명시하고 workspace 의존성 자동 탐색에 맡기지 않는다.

`contracts.py`의 frozen dataclass 계약:

- `Note(pitch:int,onset:float,offset:float,velocity:float|None)`; `Pedal(kind:str,onset:float,offset:float,value:int)`; `Events(notes:tuple[Note,...],pedals:tuple[Pedal,...])`; `Reference(key_release:Events,sustain:Events)`.
- `Metric(tp:int,fp:int,fn:int,precision:float|None,recall:float|None,f1:float|None)`; `ScoredEvents(events:Events,censored_count:int)`.
- `VelocityMatch(mae:float|None,pairs:tuple[tuple[int,int],...],reference_sorted:tuple[Note,...],prediction_sorted:tuple[Note,...])`. pair는 보존한 두 정렬 tuple의 index이며 count는 len(pairs). 보고서가 다른 matching으로 재계산하지 않는다.
- `AudioPreparationReceipt(source_crop_sha256:str,mono_sha256:str,source_rate:int,source_frames:int,start_frame:int,basic_frames:int,piano_frames:int,ffmpeg_version:str,argv:tuple[tuple[str,...],...],pcm_revision:str,elapsed_sec:float)`; `PreparedAudio(basic_audio:Path,piano_audio:Path,receipt:AudioPreparationReceipt)`.
- `ManifestEntry(recording_id:str,audio_filename:str,midi_filename:str,start_sec:int,source_audio_sha256:str,source_midi_sha256:str,basic_audio:Path,piano_audio:Path,basic_audio_sha256:str,piano_audio_sha256:str,reference_path:Path,reference_sha256:str,audio_receipt:AudioPreparationReceipt,audio_receipt_sha256:str)`.
- `Manifest(schema_version:int,selection_revision:str,entries:tuple[ManifestEntry,...],metadata_hashes:dict[str,str],source_receipt:dict[str,object])`. disk의 파일 경로는 run root 상대 경로로 저장하고 읽을 때 root 내부 경로로 검증/해결한다.
- `Candidate(id:str,python:Path,device:str,checkpoint:Path|None,checkpoint_sha256:str|None,lock_sha256:str,source_commit:str)`; `RunRecord(slot_id:str,recording_id:str,candidate_id:str,repeat:int,diagnostic_for:str|None,status:str,attribution:str|None,error_code:str|None,elapsed_sec:float|None,events_sha256:str|None,output_dir:Path|None)`.

status는 `success/model_error/timeout/output_invalid/setup_failed/cancelled/not_run/interrupted`, attribution은 `model/infrastructure/unresolved` 또는 정상/null이다. 입력/checkpoint/source 검증 실패는 setup_failed/infrastructure, classifier가 증거 없이 반환 원인을 판단할 수 없으면 unresolved다. 성공 records도 input hash·candidate receipt·소유 프로세스 cleanup 검증을 참조해야 한다. 모든 contract/manifest/ledger는 integer와 bool을 구분하고 유한 수치·허용 key·relative path·hash 형식을 검사한다.

이 평가 타입을 API/DB에 추가하지 않는다. Task 간 같은 이름/field를 사용한다. CLI 예시는 구현 전까지 목표 명령이다.

## 공통 실행·검증 명령

repo root에서 `outputs/.verification-w05`를 먼저 만든다. 매 실행마다 새로운 절대 workspace basetemp를 쓰고, 예시의 t1-red 등을 재사용하지 않는다. nested 실행도 `UV_CACHE_DIR=outputs/.uv-cache`·`PYTHONUTF8=1`을 적용한다.

```powershell
uv --cache-dir outputs/.uv-cache lock --project tools/transcription-eval --python 3.13
uv --cache-dir outputs/.uv-cache sync --locked --project tools/transcription-eval --python 3.13
uv --cache-dir outputs/.uv-cache run --locked --no-sync --project tools/transcription-eval --python 3.13 python -c "import musicsheet_common, musicsheet_pipeline, mir_eval; from musicsheet_pipeline.basic_pitch.process import run_owned_process; from musicsheet_pipeline.basic_pitch.result import validate_result_files"
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests --collect-only -v
uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/t1-red --tb=short
```

`uv --project`는 cwd를 바꾸지 않으므로 각 pytest 명령에 명시적 `-c`와 repo root 기준 test 경로를 지정한다. collect-only 결과가 해당 프로젝트 tests만 포함하고 verbose header의 config가 해당 pyproject인지 확인한다. Evaluator config addopts는 빈값, live_evaluation은 `MUSICSHEET_W05_LIVE=1`과 모든 경로가 있어야 실행한다. 기본 suite는 network/models/dataset 없이 통과해야 한다. TDD RED는 미구현 import/기대 행동 불일치이며 설치·permission·잘못된 fixture 실패와 구분한다.

각 Task: RED→최소 구현→선택/full GREEN→report/main_spec 색인→독립 코드 리뷰>=95·미해결 blocker/important0→명시적 stage·원자적 commit. 다음 Task는 gate 뒤에만 시작한다. 리뷰는 날짜·정확한 SHA/변경 범위·5개 rubric/total·지적/수정 결과를 기록한다. root/API/기존 Basic Pitch locks는 시작 시 SHA256을 저장하고 각 단위에서 불변 확인한다.

### Task1: 평가 환경·reference·metric

**Files:** evaluator 프로젝트 파일, `contracts.py`, `reference.py`, `metrics.py`, `__init__.py`; tests `test_environment.py`, `test_reference.py`, `test_metrics.py`; `docs/reports/transcription-evaluation-metrics-report.md`. Modify main_spec Reports.

**Interfaces:** `parse_reference(path:Path)->Reference`; `scoring_events(events:Events,*,start_sec:int)->ScoredEvents`; `score_notes(reference:Events,predicted:Events,*,with_offsets:bool)->Metric`; `velocity_mae(reference:Events,predicted:Events)->VelocityMatch`; `aggregate(metrics:Sequence[Metric])->dict[str,object]`.

- [ ] **Step1 실패 테스트:** 설치/import 게이트; synthetic MIDI tempo500000→1000000, velocity0 note-off, CC64>=64, 재타건/동시 이벤트, EOF-open/malformed/symlink, SMPTE/type2 거부. `test_duplicate_prediction_is_fp`: ref1/pred2→TP1/FP1/FN0/F1=2/3. `test_empty_reference_is_null`: F1None/FP2. `test_onset_50ms_boundary`: strictFalse 경계 포함/초과 제외. `test_key_release_and_sustain_differ`: note(.1,.5),pedal(.2,1.0)→key.5/sustain1.0, 다음 재타건.8→sustain.8. `test_crop_preserves_prior_pedal_and_censors_offset`: `[2,28)`·cap30·절단 수. `test_velocity_uses_onset_matching`: offset은 틀려도 onset pair의 MAE/count.

```python
def test_duplicate_prediction_is_fp():
    ref = Events((Note(60, 2.0, 3.0, 80.0),), ())
    pred = Events((Note(60, 2.0, 3.0, 80.0), Note(60, 2.0, 3.0, 80.0)), ())
    result = score_notes(ref, pred, with_offsets=False)
    assert (result.tp, result.fp, result.fn) == (1, 1, 0)
    assert result.f1 == pytest.approx(2 / 3)
```
- [ ] **Step2 RED 확인:** 공통 명령의 test directory를 `tools/transcription-eval/tests/test_reference.py tools/transcription-eval/tests/test_metrics.py`로 교체, config/collect-only 확인 후 t1-red 신규경로. 기대 미구현/행동 FAIL. reference 구현 전 locked sync/import 필수; evaluator_setup_failure에서 모델/data 취득 금지.
- [ ] **Step3 구현:** 직접 dependency는 local3packages, `mir_eval==0.8.2`, `mido==1.3.3`, `numpy>=2,<3`, `httpx==0.28.1`, `soundfile>=0.13,<0.14`, dev pytest>=8. soundfile은 DOUBLE WAV intermediate I/O에만 사용한다. resolved 버전을 독립 lock에 저장. mido tempo map·channel/pitch 상태·안정 track/event 순서. 최대 matching은 pinned mir_eval `match_notes`, VelocityMatch의 정렬 입력·pair index를 보고서까지 동일하게 저장. custom matcher 금지. bool/NaN 거부, Hz 변환·빈값/null·censor/micro/macro는 R2§5/6 준수.
- [ ] **Step4 GREEN:** 선택 테스트→full evaluator, 각각 새 t1-green/full temp. root `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/t1-root --tb=short`. 원래3개 locks 불변 확인.
- [ ] **Step5 보고/리뷰/커밋:** 정확한 명령·RED/GREEN·환경 gate와 독립5rubric 리뷰 기록. >=95 확인 후 `feat(eval): add reference and transcription metrics`.

### Task2: 데이터 취득·manifest·오디오 준비

**Files:** evaluator `dataset.py`, `range_io.py`, `audio.py`, `manifest.py`, `cli.py`, `__main__.py`; tests `test_dataset.py`, `test_range_io.py`, `test_audio.py`, `test_manifest.py`; `docs/evaluations/maestro-w05-manifest.json` (실제 선정 metadata/hash만); `docs/reports/transcription-evaluation-dataset-report.md`. Update evaluatorREADME/main_spec.

**Interfaces:** `selection_digest(audio_filename:str)->str`; `crop_start(duration:float,audio_filename:str)->int`; `select_recordings(v3:Sequence[dict],v2:Sequence[dict])->tuple[dict,...]`; `acquire_members(selection:Sequence[dict],*,source:Path|str,destination:Path,stop:threading.Event)->dict[str,object]`; `RangeReader(url:str,*,client:httpx.Client,stop:threading.Event)`의 `read/seek/tell/close`; `async prepare_audio(source:Path,*,start_sec:int,destination:Path,ffmpeg:Path,cancellation:asyncio.Event)->PreparedAudio`; `async prepare_manifest(selection:Sequence[dict],*,source_root:Path,output_root:Path,metadata_hashes:dict[str,str],source_receipt:dict[str,object],ffmpeg:Path,cancellation:asyncio.Event)->Manifest`; `write_manifest(manifest:Manifest,path:Path)->str`; `load_manifest(path:Path,*,run_root:Path)->Manifest`. 동기 chunk I/O는 run_owned_io, FFmpeg는 run_owned_process로 실행해 취소 시 drain/child 정리를 공유한다. prepare_audio가 AudioPreparationReceipt를 생산하고 prepare_manifest가 canonical JSON hash와 함께 entry에 넣는다. source_frames는 crop의30*source_rate, start_frame은 start_sec*source_rate, target frames는661500/480000이다. version/argv/revision/elapsed 또는frame 수가 누락/불일치면 freeze 거부.

- [ ] **Step1 실패 테스트:** metadata 순서와 무관한 같은12 IDs/crop; v2 불일치·중복·hash 변조·탈출/symlink/case 충돌 거부; 중앙 start 공식 미사용. 유효 local receipt가 있으면 network0. Mock206/200/416/gzip/ETag 변경·truncation·재시도/cap; 200에서 body iterator 호출0. ZIP stored/deflate/forceZIP64(테스트 한정 ZIP64_LIMIT 축소), >4GiB virtual sparse offset·CRC·member/중앙 directory 초과·암호/중복/경로 거부. anti-phase mono0, half-sample rounding/clip, 30초 frame661500/480000. diskspace 부족/중단 시 기존 완료 파일 보존·.part0.

```python
def test_selection_crop_golden_lf_bytes():
    assert (b"MusicSheet-W05-R1\n" + b"2018/fixture.wav").hex() == "4d7573696353686565742d5730352d52310a323031382f666978747572652e776176"
    assert selection_digest("2018/fixture.wav") == "1cc318bdabf2cfde64049eff51d0cb790c6885259d05886a7a0cbe7bd2044165"
    assert hashlib.sha256(b"MusicSheet-W05-R2-CROP\n2018/fixture.wav").hexdigest() == "98d21397be159b5f8a3bed1b994573b99b91d23c1b99450767ea33742f643046"
    assert crop_start(90.0, "2018/fixture.wav") == 3
```

`test_selection_order_golden`의 audio_filename은 **`2018/fixture-00.wav`부터 `2018/fixture-12.wav`까지의 전체 상대 경로**다. 이 유효v2/v3 test metadata에서 선택 순서03,10,11,12,05,09,07,04,08,00,01,02 및 제외06을 확인한다. `test_missing_audio_receipt_refuses_freeze`는 frame/ffmpeg_version/argv/pcm_revision/elapsed 각 필드를 제거하고 manifest freeze가 실패함을 확인한다. receipt hash 변조도 거부한다.
- [ ] **Step2 RED:** 공통 명령의 test directory를 `tools/transcription-eval/tests/test_dataset.py tools/transcription-eval/tests/test_range_io.py tools/transcription-eval/tests/test_audio.py tools/transcription-eval/tests/test_manifest.py`로 교체, config/collect-only 확인 후 새 t2-red. 기대 미구현/행동 FAIL.
- [ ] **Step3 구현:** 공식 metadata `https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0.json`와 v2 대응 URL; v3 ZIP 같은 base의 `maestro-v3.0.0.zip`, member prefix `maestro-v3.0.0/`. 검증된 local source 우선. [Python3.13 zipfile](https://docs.python.org/3.13/library/zipfile.html)이 ZIP64/parser/CRC를 처리하고 [HTTPX streaming](https://www.python-httpx.org/quickstart/)으로 전송한다. RangeReader는 seekable I/O wrapper만 구현, ZIP64 자체 파싱 금지. maxread16MiB/요청chunk<=1MiB, identity encoding/TLS verify/타 origin redirect 금지, status206/range/ETag/길이 확인 후 body. 모든 전송 byte·재시도는 cap에 포함. ZipFile로 선택24개 audio/MIDI만 .part에 stream, CRC/size/hash 확인 후 staging 내부 완료 경로로 이동. `extractall`/무제한read/전체archive testzip 금지. library acceptance 통과 후 실제 취득. 실패 시 acquisition_unavailable, custom parser는 별도 설계/계획/독립 리뷰가 필요.
- [ ] **Step4 GREEN/준비:** 선택/full evaluator 테스트. 목표 CLI `transcription-eval prepare --output-root D:/develop/MusicSheet/outputs/w05-evaluation --manifest D:/develop/MusicSheet/docs/evaluations/maestro-w05-manifest.json --ffmpeg <절대경로> [--local-source <검증된 archive/dir>]`. 설치된 실행기 경로를 탐색/검증하고 기록, 임의 추정 금지. Task1 reference 사용; sorted finite JSON·상대경로·content hash. source receipt는 전체archive 검증인지 부분 CRC/hash인지 구분. 12개 모든 입력/reference/hash 준비 후 freeze; 실패 시 대체 구간 선택 금지.
- [ ] **Step5 보고/리뷰/커밋:** source/license/bytes/time/한도/무결성 보증 범위·실패 기록. 독립>=95 뒤 `feat(eval): prepare fixed Maestro evaluation inputs`.

### Task3: ByteDance 평가 전용 worker·checkpoint

**Files:** `services/ml/piano-amt-worker/{pyproject.toml,uv.lock,README.md}`, `src/musicsheet_piano_amt_worker/{__init__.py,cli.py,audio.py,inference.py,output.py,provenance.py}`, tests `test_boundary.py`, `test_cli.py`, `test_output.py`, `test_inference.py`; evaluator `checkpoint.py`/test_checkpoint.py; `docs/reports/piano-amt-evaluation-worker-report.md`. Existing Basic Pitch files untouched.

**Interfaces:** CLI `piano-amt-worker --input-audio <abs> --output-dir <new abs> --checkpoint <abs> --checkpoint-sha256 <hex> --device cpu`; `run_prediction(audio_path:Path,*,checkpoint:Path,device:str)->dict`; `write_outputs(output_dir:Path,prediction:dict,*,input_sha256:str,checkpoint_sha256:str,device:str)->None`; evaluator `prepare_checkpoint(destination:Path)->dict[str,object]`.

- [ ] **Step1 실패 테스트:** fake backend로 CLIhelp/default tests의 model/network import0; 16000Hz monoPCM16/fullframes; checkpoint 누락/hash/size 오류는 upstream 호출 전 거부. 고정model/source/device·output오류exit4·NaN/bool/비양수 길이·pitch21..108 밖·sustain 이외 pedal 거부. 빈 유효 출력 허용, confidence 조작 없이 wire roundtrip. actual model은 opt-in으로 분리.
- [ ] **Step2 RED:** worker lock/sync Python3.12, `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project services/ml/piano-amt-worker --python 3.12 pytest -c services/ml/piano-amt-worker/pyproject.toml services/ml/piano-amt-worker/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/t3-red --tb=short`. 먼저 같은 config/test 경로로 collect-only/verbose header 확인. mock 행동 FAIL과 설치 실패 구분.
- [ ] **Step3 구현:** package0.1.0/upstream pinned Git source. 첫 호환 probe 조합: `torch==2.10.0`의 공식 `https://download.pytorch.org/whl/cpu` explicit index를 torch에만 연결, numpy>=2,<3/librosa>=0.11,<0.12/soundfile>=0.13,<0.14/torchlibrosa==0.1.0/mido1.3.3/setuptools<81. resolved transitive/wheel hash는 새 lock/receipt 고정. Windows/Python3.12 실제 설치/import 확인 후 지원 주장. CPU 먼저, GPU는 별도 environment/lock receipt로 고정 CPUlock을 바꾸지 않음. fixed Note_pedal/default threshold onset.3/offset.3/frame.1/pedal_offset.2를 upstream 실제 값과 대조. wire version1/source/package/checkpoint/inputhash/device/dtype float32/note/pedal·MIDI, fake calibrated confidence 없음.
- [ ] **Step4 GREEN/probe:** 공식 Zenodo metadata가 반환한 checkpoint URL, <=180MiB 전송·요청60초/총10분·exactsize/MD5/SHA256·.part cleanup. 목적지models/w05. `torch.load(...,map_location='cpu',weights_only=True)`와 expected state shape를 검사 후 constructor 호출. 실패 시 compatibility 기록; global weights_only=False/임의 downgrade 금지. 필요한 좁은 compatibility 변경은 계획 갱신·독립 재평가 후 코드에 반영. mock 전체 worker suite/locked import gate, 기존 CC0 actual smoke를 명시적 경로로 실행. 정확도 미측정. optionalGPU는 별도 환경의 CUDA probe·실제 inference 후에만 기록.
- [ ] **Step5 보고/리뷰/커밋:** 현재 버전 조합은 검증 목표이며 호환성을 미리 주장하지 않음. checkpoint/실행 receipt, ignored models. 독립>=95 뒤 `feat(eval): add isolated piano AMT evaluation worker`.

### Task4: 실행 기록·결정성·집계·선정

**Files:** evaluator `runner.py`, `results.py`, `determinism.py`, `selection.py`, `report.py`; tests `test_runner.py`, `test_results.py`, `test_determinism.py`, `test_selection.py`, `test_report.py`, `fake_worker.py`; modifycli; `docs/reports/transcription-evaluation-runner-report.md`.

**Interfaces:** `async run_slot(candidate:Candidate,entry:ManifestEntry,*,repeat:int,slot_id:str,run_root:Path,cancellation:asyncio.Event)->RunRecord`; `normalize_output(candidate:Candidate,output_dir:Path,*,input_sha256:str,stop:threading.Event)->Events`; `events_hash(events:Events)->str`; `build_schedule(manifest:Manifest,candidates:Sequence[Candidate])->tuple[dict,...]`; `async run_evaluation(manifest:Manifest,candidates:Sequence[Candidate],*,run_root:Path,cancellation:asyncio.Event)->Path`; `select_model(summary:dict)->dict`; `write_report(run_dir:Path,destination:Path)->None`. 출력 검사에는 Candidate 전체를 전달해 checkpoint/source/device의 예상값도 대조한다.

- [ ] **Step1 실패 테스트:** fake worker로 first12/12와 repeat failure 구분; JSON/MIDI 전체검사·provenance/hash/size/NaN/bool·padding31 경계. owned child timeout/cancel-after-output/descendant/drain, monotonic elapsed. nullable/-0/sorted/duplicate hashes·one-bit 차이→nondeterministic; 진단 성공이 실패/첫 accuracy를 대체하지 못함. 36개 순서/not_run/attribution model2회 vs OS1회 vs unresolved. hand-count micro/macro·operational recall 분모. macro Basic.88/Byte.91, micro Basic.92/Byte.88→tradeoff. CI0 교차/1pp/offset/min8/min24/speed20% 경계. invalid first·setup failure·nondeterminism은 winner 금지. 공개 보고서에 secret/raw traceback0.
- [ ] **Step2 RED:** 공통 명령의 test directory를 `tools/transcription-eval/tests/test_runner.py tools/transcription-eval/tests/test_results.py tools/transcription-eval/tests/test_determinism.py tools/transcription-eval/tests/test_selection.py tools/transcription-eval/tests/test_report.py`로 교체, config/collect-only 확인 후 신규 t4-red; actual model 없이 실패 증거 기록.
- [ ] **Step3 실행/검사 구현:** 기존 run_owned_process/run_owned_io·shared cancellation, literal argv·소유한 unique cwd. installedpython `-I -c`로 각각 설치된 CLI main에 전달. Basic 결과는 기존 validate_result_files 후 strict schema; Byte는 evaluator에 strict wire/전체 MIDI validator를 작성하고 기존 Basic validator를 변경하지 않음. 두 모델 모두 event bounds와 input/checkpoint/lock/source를 실행 전 재검사. 생성 파일만으로 성공 처리 금지.
- [ ] **Step4 ledger/선정 구현:** 예정slot을 먼저 저장하고 immutable per-slot JSON을 atomic write, summary에 모든 파일 hash 저장. 기존slot 덮어쓰기 금지; crash slot은 infrastructure/unresolved, fresh accuracy는 새 run ID. 원시36개와 진단을 분리, R2의 success/model-only 분모·primitive attribution 근거·상태 우선순위. 3회 normalized event hash/불일치 F1 범위; 진단은 hash 확인만 가능. bootstrap NumPy Generator(PCG64(seed20261005)),10000 paired resamples·percentile2.5/97.5 linear, 같은 pair indices 사용. R2 macro/micro/offset/speed guard와 min8/min24 준수. preflight4개 비평가 smoke·1.5배 시간 예상 gate, timeout300/총7200·진단 포함, 고정 안전 progress.
- [ ] **Step5 GREEN/보고/리뷰/커밋:** 선택/full evaluator+root 회귀. mock 결과를 actual ML/data 성공으로 주장하지 않음. 독립>=95 뒤 `feat(eval): record reliable comparative model runs`.

### Task5: 실제 비교·최종 검증·결정 기록

**Files:** evaluator tests `test_live_evaluation.py` (opt-in, 기본 skip), `docs/evaluations/transcription-model-selection.md`, `docs/reports/transcription-model-evaluation-report.md`; modify evaluatorREADME, canonical transcription/model-adapters는 상태·결정 링크만, roadmap/completed-work/main_spec.

**Interfaces:** 목표 CLI `transcription-eval run --manifest <tracked> --input-root <ignored> --basic-python <abs> --piano-python <abs> --checkpoint <abs> --checkpoint-sha256 <hex> --output-root <ignored>`→run dir; `transcription-eval report --run-dir <ignored/run-id> --output <tracked report>`→summary hash. `--help`로 모든 목표 명령을 확인한다.

- [ ] **Step1 테스트:** report의 frozen manifest/candidate/slotcount/hash/지표 설명. 실제 설정된 opt-in test는 source/defaultoptions/두 파일/first12·총72 예정slot 상태 확인. 누락 환경은 명시적 skip이며 benchmark PASS로 표시하지 않음. 추가 시 이미 GREEN인 integration은 그대로 기록하고 가짜 RED 금지.
- [ ] **Step2 준비 gate/실행:** evaluator locked sync/import·전체 unit, 12개 input/reference hash freeze, workerCPU lock/checkpoint, 비평가 smoke4개/예상 시간. 목표CLI 한 번의 초기 CPU 세션, silent rerun/adaptive crop 없음. 도구가 계속 실행 중이면<=60초마다 완료/잔여slot·마지막 상태 진행 알림. 중단/revision은 원시ledger 유지·새ID. 불가 후보는 unmeasured/partial/no_selection, W05 미완료. GPU는 준비된 별도 환경과 분리 명령/receipt가 있을 때만 optional 실행.
- [ ] **Step3 최종 검증:** 전체 evaluator/Byte/root/API/기존 Basic worker offline/no-sync suite·매회 새 basetemp. 각 명령은 `pytest -c <project>/pyproject.toml <project>/tests`와 collect-only/config 확인을 사용한다. root는 `-c pyproject.toml tests`/3.13, API`services/api`/3.13, old worker`services/ml/basic-pitch-worker`/3.12, Byte`services/ml/piano-amt-worker`/3.12, evaluator`tools/transcription-eval`/3.13. 각 `uv lock --check --offline --project <path>`와 기존3lockhash 불변. diffcheck/links/추적 바이너리 없음. Linux는 실제 수행한 unit/process 증거만, 소유 child/.part 정리·ignored data/receipt 재현용 보존·공유 서비스 변경 없음.
- [ ] **Step4 보고/선정/리뷰:** first12 onset/sustain/key-release·P/R/F1/macro/micro/velocityMAE pair·CI/censor, 원시36·진단·reliability/determinism·CPU RTF/median/nearest-rankp95·thread/device/version/source/license/한계. R2 상태/fallback 경계, Byte winner는 selected_pending_integration·제품 selector 불변. 두 후보 유효 CPU 비교+결정 근거가 있어야 W05 완료; 미측정/해결 안 된 상태는 roadmap 진행 중 유지. Task5 독립>=95와 전체 변경 fresh review>=95·미해결 important0, 전체 리뷰는 단위 gate를 대체하지 않음.
- [ ] **Step5 커밋:** `docs(amt): record fixed transcription model comparison`, 실제 integration/docs만 명시 stage. models/audio/MIDI/reference 배열/secret 없음. 각 단위/전체 리뷰의 rubric·날짜·SHA·지적 처리 기록.

## 자기 검토·실행 전달

R2§1/2/3→Task1/3, §4/5→Task1/2, §6→Task1/4, §7/8→Task3/4/5, §9/10→전체 gates. Task별 producer/consumer·field명·Review Focus5개 담당 테스트를 대조한다. 새 평가 타입을 기존 API 계약에 섞지 않는다.

권장 방식은 **주 에이전트 구현＋각 Task 독립 reviewer**다. manifest/Events/RunRecord의 연결을 같은 구현 context에서 유지하고 AGENTS.md gate를 지킨다. fresh implementer 위임은 사용자 선택 시만 한다. 현재 feature checkout의 후속 작업으로 계획했으며 시작 시 다른 미커밋 변경이 없는지 다시 확인한다. 새 worktree가 필요하면 using-git-worktrees skill/native tool을 사용하고 기존 설치 실행기의 절대 경로를 명시한다.

## 독립 계획 리뷰 기록

평가자: 작성자와 다른 `/root/w05_plan_review`. 평가일: 2026-10-05. 아래 점수는 구현 전 계획 평가이며, 각 Task의 코드 리뷰 점수를 대신하지 않는다.

| 계획 버전 | 요구 /25 | 범위 /20 | 순서 /20 | 검증 /25 | 재현 /10 | 총점 | 미해결 blocker/important/minor |
|---|---:|---:|---:|---:|---:|---:|---|
| R1 (정정된 최종 평가) | 25 | 18 | 19 | 23 | 9 | 94 | 0/1/2 |
| R2 | 25 | 20 | 20 | 24 | 10 | 99 | 0/0/1 |
| **R3** | **25** | **20** | **20** | **25** | **10** | **100** | **0/0/0** |

리뷰한 SHA256은 R1 `20B4FBC79FB4C83D6DAFAE1BB83900F2147113C1FAEE62DE9510C4D8FECCA27A`, R2 `79166595B2A83C77B6D28798124F686358FD1F5750B624470A369A822E02007B`, R3 `24FBD8B1B7A3CF2F0620E6657FB01C63220876EF6F8BFC2AAB8BF52FBF789335`다. R3 hash는 이 리뷰 기록을 추가하기 전 실행 계획 본문이며, 기록 추가로 요구사항·계약·작업 순서를 변경하지 않았다.

R1의 pytest cwd/config 지적은 모든 독립 프로젝트 테스트 명령에 명시적 `-c`와 repo root 기준 tests 경로를 지정해 해결했다. velocity matching의 정렬 입력·pair index와 오디오 준비 receipt의 producer/consumer 계약도 R2에 추가했다. salt 줄바꿈 지적은 원문 byte 확인으로 reviewer가 철회하여 R1 최초92점은94점으로 정정했다. R2의 마지막 minor인 골든 fixture 상대 경로는 R3에서 `2018/` prefix를 명시해 해결했다. Reviewer는 R3 전체와 골든 선정 순서를 다시 확인했다.

**R3 계획 게이트 통과: 100>=95, 미해결 blocker/important0.** 서면 계획 검토와 사용자 실행 확인 전 Task1을 시작하지 않는다. 권장 실행 방식은 기존 주 에이전트 구현＋각 Task 독립 reviewer다.
