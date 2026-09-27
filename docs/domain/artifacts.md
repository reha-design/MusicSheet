# Domain Spec: Artifacts

> **Canonical Owner:** `docs/domain/artifacts.md`  
> **관련 문서:** [docs/architecture/storage.md](../architecture/storage.md)

---

## 1. ArtifactRole 및 메타데이터 명세

```python
from enum import Enum
from pydantic import BaseModel

class ArtifactRole(str, Enum):
    SOURCE_ORIGINAL = "SOURCE_ORIGINAL"            # 다운로드/업로드 원본 파일
    CANONICAL_AUDIO = "CANONICAL_AUDIO"            # 44.1kHz Stereo 마스터 WAV
    MODEL_INPUT = "MODEL_INPUT"                    # 모델별 요구 규격 (16kHz, 22.05kHz Mono)
    SEPARATED_AUDIO = "SEPARATED_AUDIO"            # 분리된 피아노 오디오
    RAW_TRANSCRIPTION = "RAW_TRANSCRIPTION"        # versioned TranscriptionResult JSON (provider metadata + RawNoteEvent[])
    CLEANED_TRANSCRIPTION = "CLEANED_TRANSCRIPTION"# CleanNoteEvent[] JSON
    QUANTIZED_SCORE = "QUANTIZED_SCORE"            # ScoreNote[] JSON
    CONTROL_EVENTS = "CONTROL_EVENTS"              # PedalEvent[] JSON
    MIDI = "MIDI"                                  # 표준 MIDI (.mid)
    MUSICXML = "MUSICXML"                          # 표준 MusicXML (.musicxml)
    PDF = "PDF"                                    # 완성된 악보 PDF (.pdf)

class ArtifactRef(BaseModel):
    id: str
    job_id: str
    role: ArtifactRole
    filename: str
    uri: str                   # file:///... 또는 s3://...
    mime_type: str
    size_bytes: int
    sha256: str                # 멱등성 및 무결성 검증용 해시
    producer: str              # e.g., 'ByteDancePianoAMT'
    producer_version: str
```

`RAW_TRANSCRIPTION`은 provider provenance와 schema version, `RawNoteEvent[]`, `PedalEvent[]`를 담는 `TranscriptionResult` JSON envelope다. 저장 단계에서 기존 `CONTROL_EVENTS` artifact가 필요하면 해당 envelope의 pedal 목록을 별도 추출한다. 분리된 파일이 있더라도 envelope는 worker 결과의 검증 가능한 원본이다.

---

## 2. 멱등성 검증 원칙 (SHA-256 Caching)

- Task 재실행 시, 이미 유효한 아티팩트(동일한 SHA-256 및 정상 파일 크기)가 등록되어 있으면 해당 단계를 생략(Bypass)하고 즉시 다음 파이프라인 단계로 진행한다.
- 이를 통해 네트워크 단절, 프로세스 재시작 시 중복 GPU 연산 비용을 원천 차단한다.
