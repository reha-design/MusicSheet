# AI Spec: Model Adapters & Provider Interfaces

> **Canonical Owner:** `docs/ai/model-adapters.md`  
> **관련 문서:** [docs/ai/separation.md](./separation.md), [docs/ai/transcription.md](./transcription.md)
>
> **구현 상태:** 아래 ABC는 목표 인터페이스 예시입니다. 제품 실행은 비동기 `StageProvider` 계약을 사용하며 명시적 설정에서 Basic Pitch TRANSCRIBE provider를 등록합니다. Windows 실제 모델·PostgreSQL 등록과 Linux 실행기·root 회귀를 검증했습니다. 기본 registry는 비활성이며 다른 단계 provider·Linux 실제 모델 운영은 후속 범위입니다. [W04 검증 보고서](../reports/basic-pitch-pipeline-implementation-report.md)를 참조하세요.
>
> **W05 선정 상태:** 실제 고정 피아노 subset CPU 비교에서 Piano AMT를 `selected_for_subset`으로 선정했습니다. 제품 상태는 `selected_pending_integration`이며 위 provider 계약/registry는 바꾸지 않았습니다. [비교 결과와 제품 연결 경계](../reports/transcription-model-evaluation-report.md)를 참조하세요.

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

아래 Python ABC는 **현재 실행환경과 의존성 호환성이 확인된 provider를 같은 프로세스에서 호출할 때** 사용하는 backend-facing 인터페이스다. Python/CUDA 등 실행환경이 다른 모델은 해당 패키지를 백엔드에 직접 import하지 않는다. 별도 uv 프로젝트의 worker를 프로세스 경계로 실행하고, versioned JSON/아티팩트 계약을 백엔드에서 검증한 뒤 아래 공용 타입으로 변환한다. 따라서 isolated worker도 API 관점에서는 같은 `RawNoteEvent`/`PedalEvent` 결과를 제공하지만, worker 내부에서는 `packages/common`을 설치하거나 import하지 않는다.

제품 단계 실행 경계는 기존 `StageProvider.run(StageContext) -> tuple[ArtifactRef,...]`다. 격리 모델 연결부가 이 계약을 구현하며 아래 동기 ABC를 새로 구현하도록 강제하지 않는다. W04의 입력·출력·검증 계약은 [전사 사양](transcription.md#4-w04-제품-연결-목표-계약), 구체적인 설계와 실행 순서는 [승인 설계](../superpowers/specs/2026-10-04-basic-pitch-pipeline-design.md)와 [실행 계획](../plans/basic-pitch-pipeline-implementation-plan.md)을 참조한다.

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
