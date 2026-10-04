# AI Spec: Automatic Music Transcription (AMT)

> **Canonical Owner:** `docs/ai/transcription.md`  
> **관련 문서:** [docs/domain/note-events.md](../domain/note-events.md), [docs/infrastructure/runtime.md](../infrastructure/runtime.md)

---

## 1. AMT 모델 비교 및 선정

| 모델 | 대상 악기 | 주요 특징 | 실행 방식 및 큐 |
| :--- | :--- | :--- | :--- |
| **ByteDance Piano AMT** (Kong et al.) | 피아노 전용 | 벨로시티·서스테인 페달 출력 후보. 실제 지원 범위는 동일한 fixture로 검증 필요 | Python·PyTorch·CUDA 조합 미확정. 호환성 검증 후 실행 환경과 큐 결정 |
| **Spotify Basic Pitch** | 범용 악기 / 피아노 | 다성부 전사와 pitch bend MIDI 출력. worker JSON note contract는 pitch bend detail을 보존하지 않음 | Windows Python 3.12 + ONNX CPU 독립 CLI와 opt-in TRANSCRIBE 제품 연결·DB 등록 검증 완료. upstream 공식 지원과 기본 모델 채택은 별도 |

### 실행환경 경계

- 백엔드·API·공용 스키마는 루트 Python 3.13 uv workspace에 둡니다. 모델 추론 의존성은 필요한 경우 별도 uv 프로젝트와 프로세스로 격리합니다.
- Python·OS wheel·프레임워크·native library·CUDA 조합을 함께 검증한 모델끼리는 AI 실행환경을 공유할 수 있습니다. 모델마다 무조건 환경을 하나씩 만들지는 않습니다.
- Basic Pitch worker는 `services/ml/basic-pitch-worker`의 독립 Python 3.12 프로젝트에서 설치와 실제 추론을 검증했습니다. 22,050 Hz mono CC0 piano fixture 결과는 root Python 3.13 `TranscriptionResult`에서도 검증됐습니다. 재현 환경과 결과는 [Basic Pitch worker smoke 보고서](../reports/basic-pitch-worker-smoke-report.md)를 참조합니다.
- PR [#201](https://github.com/spotify/basic-pitch/pull/201)은 2026-09-26 확인 시 미병합이므로 이 PoC는 upstream의 공식 Python 3.12 지원을 의미하지 않습니다. Python 3.13 workspace나 기존 런타임 결정을 바꾸지 않습니다.
- 독립 CLI와 제품 factory/provider/runner 경로의 Windows ONNX CPU 추론·version1 JSON/MIDI·실DB 등록을 검증했습니다. Celery runtime에는 factory를 연결했지만 실제 Linux Celery의 모델 실행은 미검증입니다. 정확도 benchmark와 기본 모델 선정은 W05에 남습니다. 최신 제품 경로 증거는 [W04 보고서](../reports/basic-pitch-pipeline-implementation-report.md)에 있습니다.

---

## 2. 모델별 입력 Sample Rate 처리

일괄 44.1kHz로 강제하지 않고, 모델이 요구하는 규격으로 개별 변환하여 불필요한 리샘플링 왜곡을 방지한다.

```text
Canonical Audio (44.1kHz Stereo)
  ├── Separator Input: 44.1kHz Stereo
  ├── ByteDance AMT Input: 16.0kHz Mono (`amt_16k_mono.wav`)
  └── Basic Pitch Input: 22.05kHz Mono (`amt_22k_mono.wav`)
```

---

## 3. 출력 데이터 처리
- 모델의 추론 결과는 온셋, 오프셋, 모델별 activation 및 pitch로 수집되어 [docs/domain/note-events.md](../domain/note-events.md)의 `RawNoteEvent`로 직렬화된다. Activation은 보정된 확률이라고 검증되기 전까지 확률로 부르거나 해석하지 않는다.
- 페달을 실제로 출력하는 provider만 별도의 `PedalEvent`를 만든다. Basic Pitch는 별도 페달 출력을 확인하기 전까지 `supports_pedal=false`와 빈 페달 목록을 사용한다.

## 4. W04 제품 연결 목표 계약

2026-10-04 승인된 [W04 설계 R1](../superpowers/specs/2026-10-04-basic-pitch-pipeline-design.md)에 따른 **구현된 opt-in 계약**이다. `TRANSCRIPTION_PROVIDER=basic-pitch`와 사전 설치된 worker Python·FFmpeg의 절대 경로를 설정하면 TRANSCRIBE만 등록한다. 기본 모델로 선정한 것은 아니다.

- 명시적 `TRANSCRIPTION_PROVIDER=basic-pitch` 설정으로만 TRANSCRIBE provider를 활성화한다. 기본 모델 채택은 W05에서 결정한다.
- 입력은 직전 SEPARATE 완료 attempt의 `SEPARATED_AUDIO` WAV 하나다. 연결부가 작업별 임시 22,050 Hz mono PCM WAV를 준비하며, 다른 규격이면 로컬 FFmpeg로 변환한다. 이미 맞는 PCM 입력은 변환을 생략한다. 임시 모델 입력은 별도 MODEL_INPUT 아티팩트로 등록하지 않는다.
- 설치된 Python 3.12 worker를 별도 프로세스로 호출한다. 요청마다 환경 설치·네트워크 다운로드를 수행하지 않는다. 런타임과 모델 의존성 경계는 [런타임 사양](../infrastructure/runtime.md)을 따른다.
- JSON은 공용 TranscriptionResult schema1·wire 타입·pinned Basic Pitch provenance와 유한 노트 수치를 검사한다. JSON 최대8 MiB, MIDI 최대16 MiB이며 둘 다 일반 파일이고 symlink를 거부한다. MIDI는 전체 파일과 track 종료 구조를 검사하며, 두 결과가 모두 있어야 성공한다. 빈 노트의 유효 결과는 허용한다.
- 출력은 RAW_TRANSCRIPTION·MIDI 두 아티팩트다. attempt별 파일 이름과 producer/version을 사용해 저장한 뒤 기존 runner가 SHA-256·크기·소유권을 검사하고 DB 완료와 후속 단계 예약을 반영한다. 생성 파일만으로 완료 처리하지 않는다.
- 연결부는 정상 취소·시간 초과에 실행한 process tree와 I/O thread를 정리한다. owner 강제 종료의 전체 회수·orphan GC는 W11 범위이며 이 동작이 이미 검증됐다고 가정하지 않는다.
- 실제 모델 검증은 Windows의 기존 CC0 fixture·ONNX CPU 경로를 기준으로 한다. Linux 실제 모델/Celery 검증은 해당 모델 환경 검증이 먼저 필요하다. 정확도 benchmark와 실제 YouTube 전체 변환은 각각 W05·W09 범위다.

실행 단위·명령·독립 점수 게이트는 [W04 실행 계획](../plans/basic-pitch-pipeline-implementation-plan.md)에 기록한다.

## 5. W05 모델 평가 설계

[W05 서면 설계 R2](../superpowers/specs/2026-10-05-transcription-model-evaluation-design.md)는 R1 조건부 승인 리뷰를 반영한 검토 대기 목표 설계다. 승인한 방향은 비상업 연구·개인 개발 범위의 MAESTRO test12개 고정 구간에서 Basic Pitch와 ByteDance의 정확도·시간·실패를 비교하는 것이다. 데이터 선정·정답 offset/페달 의미·metric·실행 조건·선정 및 대체 정책은 해당 설계에서 상세 관리한다. 실제 비교와 기본 모델 선정, ByteDance 제품 연결은 아직 완료되지 않았다.
