# ADR 001: Python 3.12 단일 표준 런타임 채택

> **상태:** 승인됨 (Accepted - 개정)  
> **일자:** 2026-09-25  

## 배경
- Python 3.10은 2026년 10월 공식 EOL(End of Life)을 앞두고 있으며, 최신 MIR 핵심 라이브러리(`librosa 1.0+`, 최신 NumPy/SciPy/PyTorch)는 Python $\ge$ 3.12를 요구한다.
- 피아노 전사 모델(ByteDance Piano AMT 및 Spotify Basic Pitch)의 호환성을 검증한 결과, PyTorch 2.x 네이티브 가중치 로딩 및 `onnxruntime` 경량 추론 엔진을 통해 Python 3.12 환경에서 완벽히 구동 가능함을 확인하였다.

## 결정
1. 프로젝트 전체의 런타임을 **Python 3.12 단일 표준 런타임**으로 일원화한다.
2. 불필요한 Python 3.10 레거시 격리 환경 및 `legacy_amt_queue`를 완전히 제거하고, 모든 AI 추론(Demucs 분리 및 피아노 AMT 전사)을 `gpu_ai_queue` 단일 워커로 통합한다.

## 결과
- 멀티 파이썬 설치(`uv python install 3.10`) 및 워커 프로세스 중복 실행에 따른 개발/운영 복잡도를 원천 제거한다.
- 단일 `python:3.12-slim` 컨테이너 기반으로 Docker 배포 이미지 크기 및 빌드 오버헤드를 대폭 절감한다.
- EOL이 임박한 구버전 Python 의존성을 조기 차단하여 장기적인 유지보수 안정성을 확보한다.
