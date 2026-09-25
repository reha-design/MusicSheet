# AI Spec: Model Adapters & Provider Interfaces

> **Canonical Owner:** `docs/ai/model-adapters.md`  
> **관련 문서:** [docs/ai/separation.md](./separation.md), [docs/ai/transcription.md](./transcription.md)
>
> **구현 상태:** 목표 인터페이스 예시입니다. 현재 저장소에는 provider 구현 패키지가 없습니다.

---

## 1. 모델 메타데이터 (ModelInfo & Provenance)

```python
from pydantic import BaseModel

class ModelInfo(BaseModel):
    provider_name: str
    model_name: str
    model_version: str
    device: str
    dtype: str
    sample_rate: int
```

---

## 2. 핵심 Provider 추상 인터페이스

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List
from musicsheet_common.schemas.note_events import RawNoteEvent, PedalEvent
from musicsheet_common.schemas.beats import BeatGrid
from musicsheet_common.schemas.quality import SeparationQuality

# 1. Separator
@dataclass
class SeparationResult:
    stem_path: Path
    quality: SeparationQuality
    is_bypassed: bool
    qc_notes: str

class AudioSeparator(ABC):
    @property
    @abstractmethod
    def info(self) -> ModelInfo:
        pass

    @abstractmethod
    def separate(self, audio_path: Path, target_instrument: str, output_dir: Path) -> SeparationResult:
        pass

# 2. AMT Provider
class AMTProvider(ABC):
    @property
    @abstractmethod
    def info(self) -> ModelInfo:
        pass

    @property
    @abstractmethod
    def supported_instruments(self) -> set[str]:
        pass

    @property
    @abstractmethod
    def supports_polyphony(self) -> bool:
        pass

    @property
    @abstractmethod
    def supports_velocity(self) -> bool:
        pass

    @property
    @abstractmethod
    def supports_pedal(self) -> bool:
        pass

    @abstractmethod
    def transcribe(self, audio_path: Path) -> tuple[List[RawNoteEvent], List[PedalEvent]]:
        pass

# 3. Beat Provider
class BeatProvider(ABC):
    @abstractmethod
    def analyze_beats(self, audio_path: Path) -> BeatGrid:
        pass

# 4. Score Renderer
class ScoreRenderer(ABC):
    @abstractmethod
    def render_pdf(self, musicxml_path: Path, output_pdf_path: Path) -> Path:
        pass
```
