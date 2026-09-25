# ADR 003: ArtifactRef 기반 Storage 추상화

> **상태:** 승인됨 (Accepted)  
> **일자:** 2026-09-25  

## 배경
- `get_file_path() -> Path` 방식은 로컬 파일시스템에 종속되어 S3 등 클라우드 객체 스토리지 도입 시 추상화가 깨진다.

## 결정
- 메타데이터를 담은 `ArtifactRef` 모델을 도입하고, `put()`, `open_read()`, `materialize(temp_dir)` 인터페이스를 채택한다.
- CLI 도구(FFmpeg, MuseScore)가 로컬 파일을 요구할 때만 `materialize()`를 통해 로컬 임시 파일로 실체화한다.

## 결과
- 로컬 스토리지(`outputs/`)와 클라우드 S3(`s3://bucket/...`)를 비즈니스 로직 변경 없이 투명하게 교체할 수 있다.
