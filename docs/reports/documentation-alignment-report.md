# 문서 정합성 패치 보고서

> **작성 일자:** 2026-09-26
> **범위:** 현재 구현과 목표 설계를 구분하고 문서 예제·운영 안내를 실제 저장소와 정렬

## 변경 요약

- README를 현재 저장소 기반 단계에 맞추고, 미구현 API·worker·모델 다운로드를 목표 구성으로 구분했습니다. 최신 main의 MIT 라이선스 결정과 LICENSE 파일을 반영했습니다.
- 공용 스키마 import 예시를 실제 패키지 경로로 수정했습니다.
- Celery/Kombu broker, result backend, 애플리케이션 Redis Streams를 구분하고, Redis DB 예시를 각각 0, 1, 2로 정리했습니다.
- 제한된 Stream 재생 범위와 PostgreSQL 최신 상태 조회 동작을 명시했습니다.
- Docker Compose 복사 예시를 제거하고 실제 설정 파일을 단일 기준으로 참조하게 했습니다.
- 최신 main의 Python 3.12 단일 표준 런타임 결정을 반영하고, 서비스·health-check·prefetch 명령은 미구현 목표 구성으로 표시했습니다.
- 리뷰 후속: 목표 아키텍처 그림에서 broker → worker → event Streams → SSE 흐름을 분리해 표시하고, XADD 예제에 `MAXLEN ~ 100`을 적용했습니다.
- PR 기준 브랜치의 최신 MIT 라이선스 및 Python 3.12 단일 런타임 변경을 보존하도록 문서를 조정했습니다.

## 검증

- Markdown 내부 링크, import 경로, README 빠른 시작의 미구현 실행 경로를 정적 검사했습니다.
- 문서 전용 변경이므로 애플리케이션 테스트는 추가하거나 실행하지 않았습니다.
