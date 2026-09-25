# ADR 001: Python 3.12 기본 런타임 및 레거시 모델 격리

> **상태:** 승인됨 (Accepted)  
> **일자:** 2026-09-25  

## 배경
- Python 3.10은 2026년 10월 EOL을 앞두고 있으며, 최신 MIR 핵심 라이브러리(`librosa 1.0+`, 최신 NumPy/SciPy/PyTorch)는 Python $\ge$ 3.12를 요구한다.
- 반면 피아노 전사 오픈소스인 ByteDance `piano_transcription_inference`는 Python 3.7/PyTorch 1.x 시절에 아카이빙된 레거시 모델이다.

## 결정
1. 프로젝트 전체의 기본 런타임은 **Python 3.12**를 사용한다.
2. ByteDance 등 레거시 모델은 전체 스택을 낮추지 않고, `uv`를 활용한 독립 Worker 환경(Python 3.10 + `numpy==1.26.4`)으로 완전 격리한다.

## 결과
- 메인 웹/API 및 최신 MIR 생태계의 성능과 장기 지속성을 보장한다.
- 레거시 패키지로 인한 의존성 지옥(Dependency Hell)을 원천 분리한다.
