# ADR 004: Python 3.13 단일 표준 런타임 채택

> **상태:** 승인됨 (Accepted)  
> **일자:** 2026-09-26  
> **대체 대상:** [ADR 001](./001-python-runtime.md)

## 배경
- 개발 PC에서 사용 가능한 시스템 런타임은 CPython 3.13.7이며, 기존 Python 3.12 가상환경은 접근할 수 없는 uv 관리 설치 경로를 가리켜 실행할 수 없다.
- 현재 공용 스키마와 스토리지 workspace의 의존성은 Python 3.13에서 테스트할 수 있다.
- AI provider 의존성은 아직 workspace에 포함되지 않았다. 특히 Spotify Basic Pitch의 upstream 메타데이터는 Python 3.8–3.11만 분류하고 TensorFlow를 `<2.15.1`로 제한한다 ([공식 pyproject](https://github.com/spotify/basic-pitch/blob/main/pyproject.toml), [설치 안내](https://github.com/spotify/basic-pitch/blob/main/README.md)).

## 결정
1. 프로젝트의 단일 표준 런타임을 Python 3.13으로 올리고 모든 workspace 패키지에 `>=3.13,<3.14`를 적용한다.
2. `.python-version`, 테스트, README와 런타임 문서를 Python 3.13 기준으로 맞춘다.
3. 이 결정은 현재 workspace 구성요소의 3.13 사용을 승인한다. 향후 AI provider는 실제 설치·추론 호환성을 확인한 뒤 추가하며, Basic Pitch의 3.13 호환성은 별도 확인 전까지 미지원 상태로 둔다.

## 결과
- 개발 환경에서 별도 Python 3.12 설치를 요구하지 않고 현재 Python 3.13 런타임을 사용할 수 있다.
- Python 3.12 런타임은 프로젝트 지원 범위에서 제외된다.
- Basic Pitch를 포함한 AI 스택은 별도 호환성 검증이 필요하며, 현재 workspace 테스트 결과만으로 지원을 주장하지 않는다.
