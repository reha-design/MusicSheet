# W05 전사 모델 평가 설계

2026-10-05 · Revision 2 · **R1 조건부 승인 리뷰 반영, 수정본 검토 대기**. R1의 사용자 리뷰는 표기92/100·blocker0·important6·minor3이었다. 실행 계획 독립95점 게이트는 아직 수행하지 않았다. 이 문서는 목표 설계이며 실행된 benchmark 결과가 아니다.

## 1. 목적과 범위

실제 피아노 음원과 정답 MIDI로 Basic Pitch와 ByteDance Piano AMT를 동일 조건에서 비교하고, MusicSheet의 기본 전사 모델과 대체 정책을 결정한다. 사용자가 확인한 데이터 사용 범위는 **비상업 연구·개인 개발용 평가**다. 성공 산출물은 재현 가능한 입력 manifest, 후보별 정확도·시간·실패 기록, 근거가 있는 선정 결정이다. AGENTS.md의 계획/코드 리뷰 점수와 모델 정확도 F1은 서로 다른 값이다.

선택한 접근은 MAESTRO test 녹음 12개의 고정 30초 구간 비교다. Basic Pitch만 평가하면 비교 결정을 못 하고, 전체 corpus는 취득·실행 비용이 커서 이번 범위에서 제외한다. 이번 결과는 소규모 클래식 피아노 subset의 잠정 근거다. YouTube 음원, 혼합 악기, 분리 결과, 전체 곡 성능으로 일반화하지 않는다.

평가 도구와 후보 실행 환경을 추가한다. 제품 API·DB·공용 note schema·Celery 라우팅과 현재 opt-in Basic Pitch 동작은 이 작업의 변경 대상이 아니다. ByteDance의 제품 StageProvider 등록, 모델 selector 자동 활성화, 실패 시 자동 모델 전환 구현은 후속 연결 작업이다. 이번에는 전환 조건과 지원 상태를 문서로 결정한다.

관련 canonical 사양: [전사](../../ai/transcription.md), [모델 경계](../../ai/model-adapters.md), [노트·페달](../../domain/note-events.md). W04의 실행/검증 증거는 [제품 연결 보고서](../../reports/basic-pitch-pipeline-implementation-report.md)에 있다.

## 2. 구성과 의존성 경계

| 구성 | 책임과 입력/출력 | 실행 경계 |
| :--- | :--- | :--- |
| Dataset 준비 | 공식 metadata·선정 규칙 → 12개 manifest·원본 무결성 기록·모델별 WAV·정답 이벤트 | 독립 평가 프로젝트, 명시적 준비 명령 |
| Reference/metric | 정답 MIDI·검증된 예측 이벤트 → 녹음별 TP/FP/FN·P/R/F1·집계 | 모델을 import하지 않는 평가 프로세스 |
| 후보 실행 | 설치된 실행기·checkpoint·WAV → 후보별 원본 결과·상태·시간 | 소유한 별도 프로세스, 네트워크 설치 없음 |
| 보고/선정 | 고정 manifest·전체 실행 기록 → 비교 표·선정 상태·대체 정책 | 실행 이후, 원시 기록을 덮어쓰지 않음 |

평가 프로젝트는 `tools/transcription-eval`의 독립 Python 3.13 uv 프로젝트로 만든다. 평가 dependency와 lock을 여기서 관리한다. `musicsheet-common`·`musicsheet-pipeline` 및 그 로컬 package dependency를 명시적 path source로 사용해 기존 결과 검사와 소유 프로세스 실행기를 재사용한다. `mir_eval`·수치 계산 dependency를 root/API에 추가하지 않는다. 모델 inference package도 평가 프로세스에 import하지 않는다.

Python 3.13 유지 이유는 재사용하는 common/pipeline의 `requires-python=">=3.13,<3.14"` 계약이다. evaluator를 3.12로 낮추면 이 계약을 깨거나 검증된 실행기/결과 검사를 복제해야 한다. 실행 계획의 **첫 준비 게이트**에서 독립 평가 프로젝트의 `uv sync --locked`와 common·pipeline·실제 사용할 소유 프로세스/결과 검증 모듈·mir_eval import 및 합성 fixture 평가를 확인한다. 실패는 `evaluator_setup_failure`이며 모델 실패로 세지 않는다. 이 게이트 통과 전 모델 설치나 dataset 취득을 시작하지 않는다.

Basic Pitch는 기존 `services/ml/basic-pitch-worker` Python 3.12·ONNX CPU 설치와 CLI를 사용한다. ByteDance는 `services/ml/piano-amt-worker` 독립 환경의 **평가 전용 CLI**로 감싼다. 새 환경은 Python 3.12 CPU 호환성부터 검증하고, 성공한 Python/PyTorch/dependency 조합을 lock과 실행 영수증에 고정한다. 실패하면 해당 조합의 설치/실행 실패를 보고한다. 검증 없이 Python 3.7/PyTorch 1.4로 전체 프로젝트를 낮추거나 기존 Basic Pitch 환경을 바꾸지 않는다.

root/API/기존 Basic Pitch의 pyproject·lock 변경은 범위 밖이다. 실행 가능한 정확한 명령·파일별 작업 순서·환경 probe 및 독립 리뷰 단위는 서면 설계 승인 후 `docs/plans/`의 계획에서 정한다.

## 3. 후보의 식별과 사전 준비

| 후보 | 고정 식별자 | 준비/실행 조건 |
| :--- | :--- | :--- |
| Basic Pitch | 0.4.0, source `049dc8a01a170c2370d7b246ec1c2067e060c3bf`, `nmp.onnx` | 기존 Python 3.12 worker, ONNX CPU, 22,050 Hz mono. 설치 lock·모델 파일 SHA256·호출 옵션 기록 |
| ByteDance | inference 0.0.6 source `0226e74cbc805660e34bbd6a8fed2083890ebb88`, `Note_pedal` | 독립 CPU 환경, 16,000 Hz mono, 명시적 checkpoint. 지원 확인 후 GPU를 별도 조건으로 실행 |

ByteDance checkpoint는 [공식 Zenodo record 4034264](https://zenodo.org/records/4034264)의 `CRNN_note_F1=0.9677_pedal_F1=0.9186.pth`를 사용한다. 공개 크기 171,966,578 bytes·MD5 `22b961b77c1878239fec963362097045`를 먼저 대조하고 취득 파일의 SHA256을 계산한다. 이름에 포함된 논문 F1을 프로젝트 평가 점수로 사용하지 않는다. checkpoint는 CC BY 4.0이며 dataset의 이용 조건과 별도로 기록한다 ([metadata](https://zenodo.org/api/records/4034264)).

후보 실행 전 준비 단계에서 source revision, package/lock hash, checkpoint hash, 실행기 절대 경로, device, dtype, 실제 옵션을 고정한다. ByteDance wrapper는 파일의 존재·일반 파일 여부·크기·hash를 검사한 후 명시적 checkpoint 경로와 고정 `Note_pedal`을 전달한다. upstream의 누락 파일 자동 다운로드 경로에 진입하지 않는다 ([고정 inference source](https://raw.githubusercontent.com/qiuqiangkong/piano_transcription_inference/0226e74cbc805660e34bbd6a8fed2083890ebb88/piano_transcription_inference/inference.py)).

PyTorch checkpoint loading 호환성은 준비 probe로 검증한다. 불일치 시 전역 보안 설정을 낮추거나 알 수 없는 pickle을 로드하지 않는다. 모델 전용 호환 조치가 필요하면 공식 출처·무결성·좁은 변경 범위와 검증을 실행 계획에 반영하고 해당 계획을 다시 독립 평가한다. 추론 threshold는 각 후보의 고정 upstream 기본값을 사용하며 평가 결과를 보고 튜닝하지 않는다.

## 4. 데이터 선정·취득·고정

MAESTRO v3.0.0의 공식 test만 사용한다. ByteDance가 MAESTRO2 학습을 기록하므로 같은 녹음이 v2.0.0에서도 test인지 공식 metadata로 확인한다. v3 metadata를 v2와 파일 경로로 대조하고, 누락·중복·split 불일치 행은 부적격으로 기록한다. Basic Pitch 학습 중복은 확인되지 않은 한 미확인으로 표시한다 ([MAESTRO 공식 설명·배포](https://magenta.withgoogle.com/datasets/maestro), [ByteDance 학습 저장소](https://github.com/bytedance/piano_transcription)).

선정 규칙은 다음과 같으며 예측 전에 적용한다.

1. v3/test와 v2/test가 일치하고 metadata duration이 유한한 90초 이상인 녹음을 모집단으로 삼는다. 정규화한 상대 `audio_filename`과 `midi_filename`의 일치·유일성을 확인한다.
2. 각 행의 `SHA256(UTF8("MusicSheet-W05-R1\n" + audio_filename))` 오름차순으로 정렬하고 앞의 12개를 선택한다. 동률은 audio_filename 순이다. 정확도·모델 출력·주관적 청취로 곡을 고르지 않는다.
3. crop 위치는 곡 선택과 다른 salt로 결정한다. `available = floor(metadata_duration) - 30`, `crop_hash = SHA256(UTF8("MusicSheet-W05-R2-CROP\n" + audio_filename))`, `start = int.from_bytes(crop_hash.digest(), "big") % (available + 1)`이다. 입력은 `[start, start+30)`다. 모든 곡의 중앙을 고르지 않고 가능한 정수 시작 위치에 결정적으로 분산한다. 유한12개 subset의 대표성이나 통계적 완전 무편향을 보장하지는 않는다. 원본 WAV에서 해당 구간과 규격이 유효한지 확인하고, 데이터 오류나 취득 실패 시 다른 구간/곡으로 바꾸지 않고 준비 실패를 기록한다.
4. 파일 취득 후 원본/파생 SHA256·실제 frame 수·metadata hash·split 대조·crop·source URL·선정 규칙 revision을 manifest에 고정한다. 모델별 WAV와 reference를 모두 만든 뒤 manifest hash를 확정하고 이후 추론한다.

공식 v3/v2 JSON metadata와 v3 archive를 사용한다. 취득 우선순위는 **① 검증된 로컬 archive/추출본 → ② 기존 Range/ZIP library → ③ 별도 custom 취득 단위**다. 로컬 전체 archive는 공식 전체 SHA256을 대조한다. 추출본은 신뢰 가능한 archive 검증/추출 영수증과 member hash를 확인하며 출처 불명 파일을 검증 완료로 다루지 않는다. 전체 archive를 자동 다운로드하지 않는다. 2026-10-04 공식 ZIP header probe에서 `206`, `Content-Range: bytes 0-0/108445099632`를 확인했지만 이것은 library 적합성이나 부분 추출 성공의 증거가 아니다.

로컬 데이터가 없으면 실행 계획의 취득 단위에서 기존 library의 source/version/license·ZIP64·streaming/cap 지원을 조사하고 아래 acceptance test로 검증한다. 라이브러리가 통과하면 좁은 전송/무결성 wrapper만 작성한다. 모두 부적합하면 `acquisition_unavailable`로 기록한다. custom ZIP64 parser는 benchmark/metric과 묶어 구현하지 않는다. 필요성이 확인된 경우 별도 설계·실행 계획·독립95점 리뷰를 가진 취득 단위로 분리한 뒤 진행한다. 이번 설계가 검증되지 않은 library 사용이나 custom 구현을 자동 허용하는 것은 아니다.

취득기는 ZIP/ZIP64 central directory와 member header를 검증하고 상대 경로만 허용한다. 절대 경로·`..`·symlink·암호화·중복 member·허용하지 않은 압축 방식과 범위/길이 불일치를 거부한다. range 요청의 `206`·정확한 Content-Range·고정 object ETag/총 길이를 검사한다. `200` 전체 응답은 스트리밍 header 단계에서 중단하고 archive 전체를 읽지 않는다. member CRC32·압축/해제 크기 확인 후 SHA256을 계산하고 staging 파일을 완료 경로로 이동한다. 부분 취득에서는 공식 전체 archive SHA256을 검증했다고 주장하지 않는다.

취득 한도는 metadata 각각 4 MiB, ZIP directory 16 MiB, member 하나의 해제 크기 2 GiB, 선택 member의 전송 합계 6 GiB·해제 합계 8 GiB다. 누적 한도는 재시도 전송도 포함하며 다운로드 전/중 모두 적용한다. 최소 여유 공간 10 GiB를 확인한다. 각 HTTP 요청 timeout 60초·취득 전체 30분, 오류 재시도 최대 2회다. 서버/object 변화·cap 초과·무결성 실패 시 준비를 중단하고 기존 완료 파일을 손상시키지 않는다. 원본 archive 전체 다운로드로 우회하지 않는다.

원본/파생 WAV·MIDI·reference 이벤트·예측 원본·checkpoint는 ignored `outputs/w05-evaluation/` 또는 `models/`에 둔다. 추적할 manifest에는 경로·구간·해시·라이선스·출처 metadata만 담고 정답 note 배열을 넣지 않는다. MAESTRO CC BY-NC-SA 4.0 데이터는 MIT 코드에 포함해 재배포하지 않으며 평가 보고서에 dataset version과 논문 출처를 명시한다.

## 5. 오디오와 정답 의미

원본 stereo PCM의 같은 시작 frame에서 정확히30초를 crop한다. 원본 PCM16 값을32768로 나누어 float64 intermediate로 변환하고 원본 sample rate에서 `mono = (L + R) / 2`로 downmix한다. 다른 원본 PCM subtype은 무단 변환하지 않고 준비 실패로 기록한다. float64 mono WAV를 공유 중간 입력으로 고정하고 FFmpeg `swr`의 filter_size32·phase_shift10·linear_interp1·cutoff0.97·float64 output에서 각 후보 규격으로 한 번만 resample한다. 최종 sample은 `[-1,1]`로 clip 후 `round_ties_to_even(sample*32768)`을 int16 범위로 포화시켜 little-endian `PCM_S16LE` WAV로 저장한다. dithering은 사용하지 않는다. FFmpeg version·설정·PCM 변환 코드 revision·명령·frame 수를 기록하고 반올림 경계 fixture로 검증한다. RMS/peak gain normalization, source separation, denoise, tempo 변경을 하지 않는다. 두 후보가 같은 source crop을 받았는지 manifest로 검사한다.

입력은 30초지만 평가할 onset 구간은 crop 좌표 **[2, 28)**다. 앞/뒤 2초는 모델 문맥용이다. 정답과 예측 모두 같은 onset 구간으로 선별하며, 정답을 보고 예측을 제거하거나 octave·음역 밖 추정을 버리지 않는다. 0~127 pitch의 유효 예측은 모두 대상이다. 원본 결과는 유지하며 변환된 metric 입력을 별도로 보관한다.

MIDI는 전체 recording을 먼저 parse한다. 모든 track을 절대 tick 순으로 병합하고 tempo map을 적용한다. `note_on velocity=0`은 note-off로 처리하며 channel/pitch별 활성 음표를 추적한다. 동일 시각 이벤트는 원본의 안정적인 track/event 순서를 유지한다. 같은 channel/pitch의 겹친 note-on, 짝 없는 note-off, EOF까지 열린 note/pedal, 비양수 note 길이는 malformed reference로 거부한다. crop에서 열렸다는 이유로 원본의 정상 이벤트를 거부하지 않는다.

정답 note-off는 **건반 해제(key release)**다. ByteDance 학습 target은 sustain CC64로 offset을 연장하므로 두 reference 관점을 따로 만든다. 근거는 training source `1ade7dcd4348add669a67c6e6282456c8c6633bd`의 [TargetProcessor/extend_pedal](https://raw.githubusercontent.com/bytedance/piano_transcription/1ade7dcd4348add669a67c6e6282456c8c6633bd/utils/utilities.py)다.

- **key-release reference:** MIDI note-on/note-off를 그대로 사용한다.
- **sustain reference:** CC64 value >=64의 누름 구간 안에서 해제된 note를 해당 pedal 해제까지 연장한다. 동일 channel/pitch의 다음 재타건이 그보다 이르면 다음 onset에서 끝낸다. 경계가 같으면 추가 연장하지 않는다. 원본 전체의 pedal 상태를 사용하며 crop 시작에 pedal이 이미 눌려 있어도 보존한다. CC66/67에 의한 추가 연장은 하지 않고 이 한계를 표시한다.

두 reference를 crop 좌표로 옮긴 후 offset은 crop 끝 30초까지만 공통으로 자른다. 예측 offset도 같은 상한으로 자르되 원본 유효성 검사는 먼저 수행한다. 잘린 정답/예측 개수와 비율을 별도로 보고한다. 이 제한으로 offset metric은 30초 관측 범위의 지표이며 전체 지속음을 측정한 값이 아니다. onset 구간 밖에서 시작한 긴 음표의 인위적 새 onset을 만들지 않는다.

## 6. 정확도 지표와 집계

`mir_eval.transcription`의 최대 일대일 매칭으로 TP를 계산한다. MIDI pitch는 `440 * 2**((pitch-69)/12)` Hz로 변환한다. onset 허용 50 ms, pitch 허용 50 cents, `strict=False`를 고정한다. offset 포함 시 reference duration의 20%와 50 ms 중 큰 값을 허용한다. 입력 순서를 바꿔도 합계가 같아야 하며 중복 예측은 여러 번 맞았다고 세지 않는다 ([공식 metric 설명](https://mir-eval.readthedocs.io/latest/api/transcription.html)).

| 지표 | 용도 |
| :--- | :--- |
| pitch+onset P/R/F1 (`offset_ratio=None`) | 주 정확도 지표: 음높이와 시작 시각 |
| pitch+onset+offset P/R/F1, sustain reference | 공통 보조 지표: 관측 범위의 지속 길이 |
| pitch+onset+offset P/R/F1, key-release reference | 건반 해제 기준의 별도 진단; sustain 지표와 구분 |
| TP/FP/FN·예측/정답 수·경계 절단 수 | 누락·추가 음표 및 관측 한계 설명 |

녹음별 값과 전체 micro 합계(`TP`, `FP=pred-TP`, `FN=ref-TP`)를 모두 보존한다. macro F1은 동일 가중치의 녹음별 평균이며 micro와 구분한다. 3회 반복 실행을 36개의 독립 정확도 표본으로 합산하지 않는다. 첫 실행의 12개 결과를 정확도 기준으로 사용하고 반복은 안정성/시간 확인용이다.

실행된 유효 빈 예측은 정상 결과로 평가하며 reference가 있으면 TP0/FN 전체다. reference가 없는 구간은 P/R/F1을 `null`로 기록하고 FP 수를 보고하며 macro에서 제외한 개수를 명시한다. paired 비교는 양 후보가 유효한 동일한 nonempty-reference 녹음만 사용하며 8개 미만이면 선정 불가다. runtime 실패는 원인·상태와 함께 보존하며 성공-only 정확도와 구분해 예정된 12개 기준의 operational recall(`첫 반복의 성공 실행 TP 합계 / 예정 12개 reference note 합계`)을 별도로 계산한다. 실패를 성공한 빈 예측으로 위장하지 않는다. 준비 실패 후보는 정확도 `not_measured`이며 다른 모델의 정확도 우위 근거가 아니다.

페달/velocity는 원본 출력·지원 상태를 남긴다. velocity MAE는 **pitch+onset (`offset_ratio=None`) 일대일 matching**의 pair만 사용하고 reference의 MIDI1~127 값과 예측의 해당 scale 값을 비교한다. 이벤트를 pitch/onset/offset/velocity 순으로 정렬한 후 pinned `mir_eval.transcription.match_notes`가 반환한 pair를 사용하며 pair index·count를 저장한다. 동률 해를 고르는 새 matcher를 만들지 않고 같은 fixture/version에서 pair 재현성을 검사한다. matched pair가 없으면 MAE는 `null`이며 임의 평균 velocity를 넣지 않는다. confidence/activation은 정확도 F1이 아니며 후보 간 같은 척도로 비교하지 않는다. ByteDance에 존재하지 않는 calibrated confidence를 만들지 않는다. Basic Pitch의 pedal 미지원은 `unsupported`이며 pedal F1=0을 임의 부여하지 않는다. 별도의 pedal F1은 이번 최소 비교 범위에 넣지 않는다.

## 7. 실행 조건·시간·실패

공통 비교는 **같은 Windows 호스트의 CPU, 직렬 실행**이다. 후보별 runtime 기본 thread 설정과 실제 가능한 thread 정보·CPU/core·RAM·OS·실행기/라이브러리 version을 기록한다. 서로 다른 backend가 동일 thread 수로 실행됐다고 가정하지 않는다. ByteDance GPU는 CUDA probe 성공 후 별도 표에 기록하며 CPU 표의 속도 순위와 합치지 않는다. Linux 실행기 회귀가 Linux 모델 benchmark 성공을 뜻하지 않는다.

각 모델/녹음은 새 프로세스로 3회 실행한다(후보당 예정 36회). 반복 0/2는 manifest 순서에서 각 녹음마다 Basic Pitch→ByteDance를 실행하고, 반복 1은 녹음 역순에서 각 녹음마다 ByteDance→Basic Pitch를 실행한다. 병렬 모델 추론은 하지 않는다. GPU 실행이 추가되면 별도 run ID·예정 36회 분모를 사용한다. CPU와 GPU 정확도가 같다고 가정하지 않는다.

반복 결과는 **결정성 검사**를 수행한다. 원본 유효성 검사를 통과한 crop 전체의 note `(pitch,onset,offset,velocity)`와 pedal `(type,onset,offset,value)`만 정규화한다. ID·timestamp·device/timing metadata는 제외하고, 유한 수치는 IEEE754 binary64 little-endian(음의0은0), null은 별도 tag로 직렬화한다. 이벤트는 필드 순서의 사전식으로 정렬하되 nullable 필드는null이 수치보다 먼저 오며 pedal type은UTF8 byte 순이다. note/pedal 구획과 개수를 포함해 SHA256을 계산한다. 중복 이벤트는 제거하지 않는다. 같은 입력/device에서 성공한3회 hash가 같으면 `deterministic_observed`다. 정확한 hash가 다르면 `nondeterministic_output`을 기록하고 각 반복 F1·최솟값/최댓값을 진단한다. 사후 tolerance를 도입하지 않는다. 첫 실행만 대표 정확도로 사용해 자동 선정하는 것을 중단하고 `selection_requires_review`로 남긴다. 반복 부족은 `determinism_incomplete`이며 성공/결정성으로 추정하지 않는다.

입력 준비 시간은 crop/downmix/resample wall time으로 별도 기록한다. 모델 `elapsed_sec`는 준비된 입력에서 프로세스 시작 직전부터 종료·자식 정리·출력 검증 완료까지 monotonic clock으로 잰다. **RTF = elapsed_sec / 30**이며 다운로드·설치 시간은 제외한다. 중앙값과 개별 36개 시간을 제공하고 p95는 오름차순 표본의 `ceil(0.95*n)`번째 값(nearest rank)으로 계산한다. 작은 표본의 보조값으로만 표시한다. 현재 CLI는 모델을 상주시켜 측정하지 않으므로 이를 warm inference 시간이나 순수 neural network 연산 시간으로 부르지 않는다.

한 추론의 timeout은 300초, CPU 세션 총 실행 예산은 2시간이다. 한 실행 실패를 자동 재시도하지 않으며 이미 예정된 반복은 별도 실행으로 남긴다. 전체 예산/사용자 취소로 실행 못 한 slot은 `not_run`으로 기록하고 완전 비교로 선정하지 않는다. 모델 예외, timeout, 출력 누락, wire/schema/수치 오류, 설정/준비 실패, 사용자 취소를 구분한다. failure rate는 실제 시작한 실행 분모와 예정 36회 중 미실행 개수를 함께 표시한다.

시작 전에 기존 CC0 smoke fixture에서 만든 고정30초 비평가 입력(원본을 이어붙여30초 crop, hash 기록)을 후보별 fresh process로2회 실행한다. 모델 loading/output/정리와 시간을 확인하고 `1.5 * 36 * (Basic Pitch smoke 최대 elapsed + ByteDance smoke 최대 elapsed)`가2시간 이하인지 검사한다. 준비/다운로드 시간은 별도다. 이 추정은 곡 난이도에 따른 시간 보장이 아니며 실제 budget stop은 유지한다. probe failure 또는 예상 초과이면 benchmark를 시작하지 않고 `preflight_failure`/`budget_preflight_failure`를 기록한다. 예산을 늘리거나 표본을 줄이려면 예측 전 계획 revision으로 처리한다. smoke는 평가/36회 성공률/정확도 분모에 포함하지 않는다.

**benchmark validity와 model reliability를 분리한다.** 첫 accuracy 반복12개가 모두 유효하고, 입력·환경·runner 검증이 통과해야 정확도 비교 가능이다. 반복1/2의 실패는 원시 성공률과 원인별 횟수로 남기며 단1회 실패로 모델을 운영 부적격이라 하지 않는다. 실패마다 `model`·`infrastructure`·`unresolved` attribution과 근거를 기록한다. 입력/hash나 runner/환경 검증 실패는 infrastructure다. 고정 입력/환경·정상 runner에서 같은 모델 오류가 독립 실행2회 이상 발생하면 reproducible model failure다. attribution이 미해결이면 model failure라고 추정하지 않는다.

재현 여부는 예정 반복을 먼저 사용하며 부족하면 실패 slot별 진단 실행 최대1회만 허용한다. 진단 실행은 별도 ID로 남기고 실패 slot을 성공으로 교체하지 않는다. 정확도·36회 분모·속도 표에서 제외하고 세션 총 budget에는 포함한다. 원시 실패율에는 예정된 모든 시작 실행을 포함하고, model-only 실패율은 model-attributed 실패 수/(원인 미해결·infrastructure를 제외한 시작 실행 수)로 분모와 함께 보고한다. 분모0이면 `null`이다. 진단 성공 출력은 결정성 확인에만 사용할 수 있으며 원래 실패/추가 실행을 숨기지 않는다. infrastructure/unresolved slot은 속도 표에서 제외한 사유/개수를 밝힌다. 성공 slot만 모아36/36 성공처럼 표현하지 않는다.

기존 W04 소유 프로세스 실행기·allowlist 환경·Windows Job/Linux group 정리를 재사용한다. shell 실행·서비스 credential 전달·요청 중 모델 다운로드를 하지 않는다. 취소/timeout에서 자식 종료와 owned 임시 파일 정리를 기다리고, 미완성 결과로 metric을 계산하지 않는다. blocking I/O drain으로 timeout 반환이 지연될 수 있다는 기존 한계도 남긴다.

ByteDance 평가 wire는 version1·고정 provenance·input hash·device·notes(pitch/onset/offset/velocity)·pedals를 명시한다. 출력 JSON은 최대 8 MiB, MIDI는 최대 16 MiB이고 둘 다 일반 파일·비-symlink다. NaN/Infinity·bool을 수치로 허용하지 않으며 pitch/velocity 범위와 `0 <= onset < offset`을 검사한다. note/pedal offset의 모델 padding 허용치는 입력 끝에서 1초까지로 한정하고 metric 변환에서 30초로 자른다. 그보다 큰 시각은 invalid output이다. 공용 제품 schema를 확장하는 대신 평가 쪽에서 Basic Pitch의 기존 TranscriptionResult와 이 평가 wire를 같은 metric 입력으로 정규화한다.

## 8. 사전 고정한 선정과 대체 정책

1. 첫 accuracy 반복12/12 유효와 evaluator/input/runner gate를 **비교 가능 조건**으로 삼는다. 예정36개 slot의 상태·reliability는 별도로 보고한다. 재현 가능한 model failure만 `operationally_ineligible`로 분류한다. 단발 모델 실패나 미해결 원인, infrastructure 실패로 반복/결정성 검증이 부족하면 `selection_requires_review`이며 단순 운영 부적격으로 단정하지 않는다. 미실행 slot·첫 반복 실패·invalid benchmark는 `no_selection`이다. 빈 유효 예측은 정확도에 그대로 반영한다.
2. 두 후보 비교 가능하고 녹음별 성공3회(진단 성공을 포함할 수 있음) 출력이 결정적인 경우, 첫 반복12개 녹음의 pitch+onset macro F1 차이를 paired bootstrap10,000회, seed20261005, percentile95% interval로 비교한다. 차이 절댓값0.01 이상이고 interval이0을 포함하지 않을 때만 이번 subset의 명확한 우위로 간주한다. 최소8개 nonempty-reference pair 조건은 유지한다. 이 구간은 작은 subset의 불확실성 표시이며 모집단 보장으로 표현하지 않는다.
3. onset macro 우위 후보가 **onset micro F1에서0.01 이상 낮거나**, sustain offset macro F1에서0.01을 초과해 낮으면 `tradeoff_requires_review`다. 그렇지 않으면 `selected_for_subset`이다. key-release 진단도 함께 제시한다. micro 충돌은 사전 고정한 effect-size guard이며 유의성 검정을 했다고 표현하지 않는다.
4. onset 차이가 위 기준을 충족하지 못하면 sustain offset에 같은 paired 규칙을 적용한다. sustain macro winner가 sustain micro에서0.01 이상 낮거나 onset micro에서0.01 이상 낮으면 역시 `tradeoff_requires_review`다. 그것도 구별되지 않으면 성공/유효 CPU 시간 표본이 후보별24개 이상일 때만 중앙값20% 차이를 운영 우선안 근거로 사용한다. 시간 표본 부족이면 `selection_requires_review`다. 시간 우선 후보도 onset/sustain micro가0.01 이상 낮으면 `tradeoff_requires_review`다. 충돌이 없고 시간 차이가 작으면 기존 Basic Pitch를 `provisional_operational_default`로 유지한다. 정확도 우위를 주장하지 않는다.
5. 한 후보의 재현 가능한 model failure가 확인되면 다른 비교 가능·결정성 검증 후보를 잠정 운영안으로 기록하되 정확도 winner라고 하지 않는다. 후보의 준비 실패·미측정·원인 미해결 상태에서는 추천 근거와 남은 문제를 기록하고 기본 모델 결정은 보류한다. GPU-only 성공은 공통 CPU 비교를 대신하지 않는다.

선정 상태가 충돌하면 `invalid/no_selection` → `operationally_ineligible` 원인 확인 → `selection_requires_review` → `tradeoff_requires_review` → winner/tie-break 순으로 처리한다. infrastructure 실패가 진단에서 해소됐더라도 원시 실패 기록은 유지하며, first accuracy run 실패를 진단 성공으로 대체하지 않는다. 결정성 해시가 같아도 반복 신뢰도가100%라고 주장하지 않는다.

최종 결정 기록에는 manifest/run hashes·정확도·속도·실패·12개 subset 한계·환경 지원·선정 상태·필요한 제품 연결을 포함한다. 선정 규칙을 예측 후 바꾸면 새 revision/run으로 표시하고 기존 결과를 유지한다. root/API·기존 worker locks 및 제품 selector의 자동 변경은 하지 않는다.

fallback 정책은 **설치·실제 실행·출력 검증·제품 연결까지 완료한 provider**에만 적용할 수 있다. 현재 그런 후보는 명시적으로 구성된 Basic Pitch다. ByteDance가 benchmark winner여도 제품 연결 전에는 `selected_pending_integration`으로 표시한다. 제품 연결 후 자동 fallback을 도입할 때에는 후보의 일시 실행 장애만 대상이며, 취소·잘못된 입력·무결성 실패에 모델을 바꾸어 성공으로 덮지 않는다. 이번 W05에서는 자동 전환 코드를 추가하지 않는다.

## 9. 검증과 완료 조건

실행 계획은 다음 실패 사례와 합격 기준을 포함해야 한다.

- evaluator locked sync/import·합성 metric 게이트. 선정/crop hash 재현·v2/v3 split 불일치·중복/경로 오류·manifest 변경 거부. 로컬 영수증/library 우선 및 ZIP64/Range cap·200 응답·object 변경·CRC·경로 탈출·중단 파일 정리.
- tempo 변경·velocity0 note-off·페달 선행 상태·재타건·CC64 경계·말단 절단·정답 오류. pitch/onset/offset 허용 경계·최대 일대일 matching·추가/누락/중복·empty-reference·failed-run 집계를 손으로 확인 가능한 합성 fixture로 검증.
- 실제 모델 없는 기본 suite에서 optional dependency import/다운로드를 하지 않음. fake worker로 malformed JSON/MIDI·provenance/hash 불일치·timeout·취소·자식 수명·실행 순서·시간/분모·단발/재현/model/infrastructure/unresolved attribution을 검증. 반복 hash 일치/불일치·중복 보존·진단 출력과 첫 accuracy slot 분리·budget preflight·macro/micro 반전을 검증.
- 별도 opt-in 실제 환경 probe·설치 lock 검증 후 두 후보/동일 manifest CPU 실행. GPU는 별도 probe와 보고. 기존 root/API/Basic Pitch 회귀·lock 불변 확인.
- 단위별 결과보고서·재현 명령·실제 RED/수정/재검증·독립 리뷰를 남김. AGENTS.md에 따라 실행 계획 95점 이상·미해결 blocker/important0, 각 구현 단위도 별도 95점 이상이어야 다음 단위로 진행.

W05 비교 완료는 고정 dataset·두 후보 측정/실패 원인·전체 실행 기록·선정 상태·대체 정책·한계가 재현 가능한 보고서로 남았을 때다. 환경 실패를 보고한 상태와 두 후보의 유효 비교 성공을 구분하며 미측정 후보가 남으면 기본 모델 결정 완료로 표시하지 않는다. 실제 모델의 Windows/Linux/CUDA 지원은 각 실행 증거가 있는 조건에서만 주장한다.

## 10. 현재 상태와 승인 경계

방향 승인: 비상업 평가, 두 후보, MAESTRO test12개 고정 구간, 정확도/시간/실패를 분리한 비교. R1 사용자 조건부 승인에서 important6·minor3을 검토해R2로 수정했다. Python3.12 evaluator 제안은 저장소의3.13 package 계약 때문에 그대로 적용하지 않고 제안의 대안인 초기 compatibility gate를 채택했다. 나머지 지적의 반영 위치·검증은 [R2 리뷰 처리 보고서](../../reports/transcription-model-evaluation-design-review-report.md)에 기록한다. 이번 문서의 자기 검토와 사용자 표기 점수는 작성되지 않은 실행 계획의 독립 점수를 대신하지 않는다.

이 문서 작성 시점에는 dataset/checkpoint 취득, ByteDance 설치, benchmark 구현·실제 비교를 수행하지 않았다. 다음 단계는 **이 서면 설계 사용자 검토 후 실행 계획 작성과 독립 평가**다. 제품 기능 구현 승인이나 모델 선정 성공을 미리 기록하지 않는다.
