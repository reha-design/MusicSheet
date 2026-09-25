# Architecture Spec: Storage Abstraction

> **Canonical Owner:** `docs/architecture/storage.md`  
> **관련 문서:** [docs/domain/artifacts.md](../domain/artifacts.md), [docs/adr/003-storage-abstraction.md](../adr/003-storage-abstraction.md)

---

## 1. 아티팩트 디렉터리 레이아웃 (`outputs/{job_id}/`)

모든 중간 산출물과 최종 결과물은 `job_id`별 격리된 폴더에 저장된다.

```text
outputs/{job_id}/
├── source_original.mp4        # 다운로드/업로드 원본
├── canonical.wav              # 44.1kHz, 32-bit Float Stereo 마스터 음원
├── separator_input.wav        # Demucs 입력 (44.1kHz Stereo)
├── separated_piano.wav        # 분리된 피아노 오디오 (Bypass 시 canonical 링크)
├── amt_16k_mono.wav           # ByteDance 모델용 16kHz Mono 오디오
├── raw_notes.json             # AMT 순수 출력 (RawNoteEvent[])
├── cleaned_notes.json         # Dynamic Filter/QC 완료된 CleanNoteEvent[]
├── quantized_score.json       # Beat/Bar/Staff/Voice 매핑된 ScoreNote[]
├── control_events.json        # Sustain Pedal (CC64) 등 ControlEvent[]
├── result.mid                 # 표준 MIDI 파일
├── result.musicxml            # 표준 MusicXML 악보
├── result.pdf                 # MuseScore 렌더링 벡터 PDF 악보
└── manifest.json              # 전체 처리 시간, 모델 정보, Quality Score 리포트
```

---

## 2. Storage 추상 인터페이스

로컬 파일시스템 경로(`Path`)에 직접 의존하지 않고 `ArtifactRef`를 매개로 하여, 로컬 스토리지와 향후 S3/클라우드 스토리지를 완전히 동일한 코드로 제어한다.

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO
from packages.common.schemas.artifacts import ArtifactRef, ArtifactRole

class ArtifactStorage(ABC):
    @abstractmethod
    def put(
        self, 
        job_id: str, 
        filename: str, 
        role: ArtifactRole, 
        source: BinaryIO | Path, 
        producer: str, 
        producer_version: str
    ) -> ArtifactRef:
        """스토리지에 저장하고 메타데이터가 담긴 ArtifactRef를 반환한다."""
        pass

    @abstractmethod
    def open_read(self, artifact: ArtifactRef) -> BinaryIO:
        """아티팩트의 읽기 전용 바이너리 스트림을 반환한다."""
        pass

    @abstractmethod
    def exists(self, artifact: ArtifactRef) -> bool:
        """아티팩트의 존재 여부를 검사한다."""
        pass

    @abstractmethod
    def materialize(self, artifact: ArtifactRef, temp_dir: Path) -> Path:
        """
        CLI 기반 도구(FFmpeg, MuseScore)가 로컬 물리 파일 경로를 요구할 때
        임시 디렉터리에 실체화(다운로드 또는 심볼릭 링크)하여 로컬 경로를 반환한다.
        """
        pass
```
