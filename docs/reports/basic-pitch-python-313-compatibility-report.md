# Basic Pitch 평가 및 Python 3.13 호환성 보고서

> **문서 번호:** REPORT-20260926-02<br>
> **작성 일자:** 2026-09-26<br>
> **프로젝트:** MusicSheet<br>
> **검토 기준:** Spotify Basic Pitch 공식 저장소 `main` 브랜치 (패키지 버전 0.4.0)

## 1. 결론

**Basic Pitch는 Python 3.13 workspace에 바로 추가할 수는 없지만, Python 3.12 환경과 ONNX 의존성 마커 패치를 조합하면 현실적으로 사용할 수 있는 경로가 있습니다.** 현재 upstream 설치 안내는 Python 3.7–3.11을 호환 환경으로 열거합니다. 메타데이터도 Python 3.8–3.11 classifier만 표시하고, Python 3.12에서 TensorFlow `<2.15.1`을 요구하는 조건과 ONNX 선택 조건이 충돌합니다. 다만 upstream의 미병합 PR #201은 Python 3.12에서 기존 ONNX 모델을 기본 선택하도록 의존성 마커만 변경하는 방안을 제시하며, PR 작성자는 Python 3.12.3에서 설치와 실제 추론을 확인했다고 기록했습니다. [공식 설치 안내](https://github.com/spotify/basic-pitch/blob/main/README.md) · [공식 패키지 메타데이터](https://github.com/spotify/basic-pitch/blob/main/pyproject.toml) · [미병합 PR #201](https://github.com/spotify/basic-pitch/pull/201)

따라서 **먼저 Python 3.12 환경에서 PR #201과 같은 ONNX 마커 변경을 적용해 독립 PoC를 수행**하는 것을 권고합니다. 성공하면 프로젝트 전체 런타임을 3.12로 맞출지, Python 3.13에서 분리 worker로 호출할지 결정할 수 있습니다. 이 접근은 Basic Pitch를 시험할 때 더 호환성이 낮은 Python 3.13에 직접 포팅하는 것보다 변경 범위가 작습니다. PR은 아직 병합되지 않았고 이번 작업에서 독립 재현하지 않았으므로, 공식 지원이 확인된 것으로 간주하지는 않습니다.

## 2. Basic Pitch 개요와 MusicSheet 적합성

Basic Pitch는 Spotify가 공개한 경량 자동 음악 전사(AMT) 라이브러리입니다. 공식 README는 악기 비종속, 다성부 지원, 피치 벤딩 검출을 설명하고, 입력 오디오에서 MIDI와 note event를 생성하는 사용법을 제공합니다. 또한 한 번에 한 악기를 처리할 때 가장 잘 동작한다고 안내합니다. [공식 README](https://github.com/spotify/basic-pitch/blob/main/README.md)

MusicSheet에 적용할 때의 장점과 검증 항목은 다음과 같습니다.

| 항목 | 평가 |
| :--- | :--- |
| 빠른 기준선 구축 | 기존 모델과 추론 API를 활용하므로 자체 모델 학습 없이 비교 기준을 만들 수 있음 |
| 다성부 피아노 전사 | 후보로 시험할 수 있으나, 악기 비종속이라는 설명만으로 피아노 특화 모델보다 정확하다고 볼 수 없음 |
| 출력 | 공식 사용법은 MIDI, note event 및 raw model output 저장을 보여 줌 |
| 피치 벤딩 | 공식 설명에서 지원함. 피아노 악보 변환 시 필요한 표현인지 별도 정책이 필요함 |
| 페달·악보 의미 | 공식 README에서 별도 sustain pedal event 출력을 확인하지 못함. `PedalEvent`, 양손 분리, 리듬 정리는 후처리와 별도 검증 대상으로 둠 |
| 입력 규격 | 현재 MusicSheet 사양의 22.05 kHz mono 입력이 upstream 사용법과 실제 추론에서 맞는지 PoC로 검증 필요 |

공식 문서는 음원 종류와 설치·사용 방식을 설명하지만, MusicSheet의 목표 데이터에 대한 정확도나 ByteDance 피아노 전사 대비 우위를 보장하지 않습니다. 모델 선택은 동일한 평가 음원으로 note onset/offset 및 pitch 정확도, 코드 누락·오검출, 추론 시간과 메모리 사용량을 비교한 뒤 결정해야 합니다.

## 3. Python 3.13 호환성 분석

| 근거 | upstream 설정 | Python 3.13에서의 의미 |
| :--- | :--- | :--- |
| 설치 안내 | 호환 Python: 3.7–3.11 | Python 3.13은 명시된 지원 범위 밖 |
| 패키지 classifier | Python 3.8, 3.9, 3.10, 3.11 | 3.13 호환성 분류가 없음. classifier 누락만으로 설치 불가를 단정할 수는 없음 |
| Windows ONNX 의존성 | `onnxruntime` 조건은 `python_version < '3.11'` | Python 3.13에서는 이 조건이 선택되지 않음 |
| Windows TensorFlow 의존성 | `tensorflow>=2.4.1,<2.15.1` 조건은 Python `>=3.11` | 3.13에서 TensorFlow 경로를 요구하지만, Basic Pitch 공식 문서는 3.13 조합을 지원 대상으로 확인하지 않음 |
| Python 3.12 TensorFlow 호환성 | TensorFlow `<2.15.1`에는 CPython 3.12 wheel이 없으며 Python 3.12 지원은 TensorFlow 2.16부터 시작 | 현재 마커를 그대로 쓰면 기본 설치 경로가 맞지 않음. PR #201은 3.12에서 TensorFlow 의존성을 피하고 포함된 ONNX 모델을 쓰도록 제안 |
| Python 3.12/Keras 3 포팅 | 별도 PR #194는 TensorFlow 2.16+, Keras 3 대응과 TFLite/LiteRT 경로 변경 제안 | 가능하지만 모델 로딩·Keras API·의존성·테스트 변경까지 포함해 ONNX 마커 변경보다 범위가 큼 |
| 현재 프로젝트 런타임 | Python `>=3.13,<3.14` | 직접 의존성으로 통합하려면 별도 설치와 실제 추론 증거가 필요 |

README는 Python 3.11 이상에서 TensorFlow를 기본 모델 런타임으로 사용한다고 설명합니다. 그러므로 기존 AI 사양의 “Basic Pitch는 ONNX Runtime 사용”이라는 고정 설명은 현재 공식 동작과 맞지 않습니다. Windows의 ONNX 선택은 Python 3.11 미만에 조건부이고, ONNX를 별도로 강제한다고 해서 Python 3.13 호환성이 입증되는 것도 아닙니다. TensorFlow 공식 설치표는 Python 3.12 wheel을 2.16.2부터 열거하며, TensorFlow 2.15.0의 PyPI wheel 목록은 CPython 3.9–3.11까지입니다. [Basic Pitch 공식 런타임 안내](https://github.com/spotify/basic-pitch/blob/main/README.md) · [Basic Pitch 의존성 조건](https://github.com/spotify/basic-pitch/blob/main/pyproject.toml) · [TensorFlow 설치 안내](https://www.tensorflow.org/install/pip) · [TensorFlow 2.15.0 배포 파일](https://pypi.org/project/tensorflow/2.15.0/)

## 4. 도입 경로

1. **우선 권고 — Python 3.12 + ONNX 마커 패치 PoC:** 별도 Python 3.12 환경에서 PR #201을 검토해 의존성 마커를 적용하고, TensorFlow 대신 `onnxruntime`과 Basic Pitch에 포함된 ONNX 모델이 선택되는지 확인합니다. 깨끗한 설치, 모델 로딩, 실제 오디오 추론, MIDI/note event 출력을 검증하고 lockfile로 재현성을 고정합니다.
2. **프로젝트 통합:** PoC가 통과하면 프로젝트 표준 런타임을 Python 3.12로 되돌리거나, Python 3.13 앱에서 별도 3.12 worker를 호출하는 방안을 결정합니다. 전자는 ADR 004, 패키지 제약, lockfile, CI/테스트 갱신이 필요하고 후자는 별도 프로세스 경계를 설계해야 합니다.
3. **대안 — TensorFlow 2.16+/Keras 3 포크:** 미병합 PR #194는 3.12 지원을 위해 TensorFlow/Keras API 수정, 기존 SavedModel의 대체 추론 경로, 의존성 갱신 및 테스트를 제안합니다. TensorFlow backend가 꼭 필요하지 않다면 ONNX 우선 경로보다 변경 규모가 큽니다.

## 5. 검증 범위와 다음 결정

- 확인한 저장소: MusicSheet의 `docs/ai/transcription.md`, `docs/infrastructure/runtime.md`, ADR 004 및 Basic Pitch 공식 `README.md`와 `pyproject.toml`.
- 현재 workspace에는 Basic Pitch를 설치하거나 lockfile에 추가하지 않았으며, 실제 오디오 추론은 실행하지 않았습니다. 따라서 본 문서는 공식 메타데이터와 현재 프로젝트 사양을 비교한 호환성 평가입니다.
- 다음 도입 판단은 Python 3.12 + ONNX 격리 PoC의 설치 성공 여부만으로 끝내지 말고, 테스트 오디오에서 note event 품질과 페달/양손 후처리 요구, Windows 재현성을 함께 확인해야 합니다.
- 공식 `main`은 아직 Python 3.12/3.13을 지원한다고 선언하지 않습니다. 미병합 PR #201은 Python 3.12 ONNX 경로의 유력한 구현 참고자료이지, 검토·병합된 공식 지원으로 간주하지 않습니다.
- 본 보고서의 실제 설치·추론은 수행하지 않았습니다. Python 3.12를 설치하고 패치를 적용한 뒤 독립 PoC를 통과해야 호환성 판단을 갱신할 수 있습니다.
