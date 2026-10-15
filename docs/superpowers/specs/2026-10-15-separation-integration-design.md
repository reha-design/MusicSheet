# W06 음원 분리 제품 연결 설계 초안

**Status: Proposed — 사용자 설계 승인 및 제품 구현 계획 리뷰 전.**

작성일: 2026-10-15 · 기준: `7cf277f608039affae597b4c095af2a01867ed25`.

이번 작업은 [W06-0 선행 검증](../../reports/w06-separation-preflight-report.md)이다. FFmpeg 선행 조건 미충족으로 실제 Demucs 추론0회, CPU 지원·출력·취소 미검증이며 제품 연결은 HOLD다. 아래는 구현된 계약이나 Canonical Spec 변경이 아니다. 제품 코드·공용 schema·artifact enum·API·registry는 유지한다.

## 목적과 기존 경계

[음원 분리 사양](../../ai/separation.md)의 Demucs `htdemucs_6s`와 solo piano bypass를 기존 비동기 `StageProvider.run(StageContext) -> tuple[ArtifactRef, ...]` 경계 뒤에 연결한다. 별도 동기 ABC 구현을 제품 연결의 선행 조건으로 강제하지 않는다.

44,100Hz stereo WAV인 `CANONICAL_AUDIO` 하나를 받아 피아노 `SEPARATED_AUDIO` 하나와 분리/QC provenance JSON 하나를 생성하는 방향을 제안한다. 모델 의존성은 backend Python3.13 workspace에 설치하지 않고 검증된 별도 런타임에서 실행한다. 이번 Python3.10 조합은 throwaway 후보이며 채택된 제품 런타임이 아니다. 후속 호환성·실추론 검증 후 필요한 ADR과 독립 lock을 확정한다.

## 출력과 provenance 제안

| 산출물 | 제안 |
|---|---|
| 피아노 오디오 | 별도 SEPARATED_AUDIO WAV; sample rate/channels/frame count/finite 검증과 SHA256·size 기록 |
| 분리/QC 보고 | versioned JSON. 전용 role의 후보명은 `SEPARATION_REPORT`이며 후속 사양 승인·enum/DB 저장/API 호환성 검토 전 사용하지 않는다. |
| 입력 식별 | 원본 CANONICAL_AUDIO artifact ID·SHA256 |
| 출력 식별 | SEPARATED_AUDIO artifact ID·SHA256; 보고서 자체 hash는 ArtifactRef에 기록해 self-hash 순환을 피한다. |
| 모델 출처 | provider/adapter version, upstream full SHA, 모델명, 구성·전체 weight hash, Python/framework/device/dtype/FFmpeg 및 추론 옵션 |
| 우회 결정 | bypass 여부·이유·판별 방법/버전과 판별의 known/unknown 상태. classifier 확률과 분리 품질 score는 서로 다른 값이다. |
| QC | 실제 측정 RMS·peak·silence ratio·rescale 여부/gain. 미측정 종합 score·bleed/artifact는 null 및 측정 상태로 구분한다. |

`SeparationQuality.score`는 현재 공용 schema에서 필수 float이며 null을 받을 수 없다. 위 JSON을 그대로 해당 타입에 넣지 않는다. 새 보고 envelope의 nullable 측정 필드와 기존 타입의 변환/호환성 방식을 후속 Canonical Spec·versioned schema 계획에서 정하고 독립 리뷰한다. unknown을0점 또는 검증된 solo=false로 바꾸지 않는다.

## 다음 단계와 아티팩트 안전성

현재 repository는 직전 완료 attempt의 **전체 출력**을 다음 단계 입력으로 읽고 runner는 provider의 허용 role로 모든 입력을 검증한다. Basic Pitch provider는 SEPARATED_AUDIO 하나만 받으므로 보고 JSON을 추가하면 현재 제품 계약과 충돌한다.

후속 계획에서는 TRANSCRIBE identity가 피아노 오디오와 보고 role을 허용하고, 두 입력 모두 기존 hash 검증·fingerprint에 포함한 뒤 provider 내부에서 정확히 하나의 SEPARATED_AUDIO를 선택하는 방향을 제안한다. 오디오/보고 누락·중복·입출력 hash 불일치를 거부한다. 보고 파일을 검증 전 조용히 버리거나 전체 아티팩트 검증을 약화하지 않는다. 기존 W04 단일 입력과 공존하는 전환 정책은 후속 사양·계획에서 확정한다.

실행은 소유 프로세스·작업별 임시 경로·협력적 취소·timeout·부분 산출물 rollback을 갖춘 기존 패턴을 따른다. worker 결과를 검증한 후 저장하고 기존 runner의 attempt fencing과 commit 경계를 유지한다. 재실행 fingerprint에는 모델·구성/weight·분리/QC 옵션을 포함해야 한다. source/ref를 변조해 캐시를 재사용하지 않는다.

우회가 검증돼 활성화되면 원본 ref의 role/metadata를 바꾸지 않고 CANONICAL_AUDIO 바이트를 별도 SEPARATED_AUDIO 아티팩트로 저장한다. 실제 분리 실행 여부와 우회 출처를 보고서에 남긴다. 자동 판별 미구성·미확신을 검증된 solo로 해석하지 않는다. 현재 자동 우회는 비활성이다.

## 입력·QC 정책과 후속 게이트

무음·상수/DC·손상 WAV·비정상 수치를 추론 전에 검사하는 정책을 후속 사양에 명시해야 한다. Demucs v4.0.1은 입력 표준편차로 정규화하므로0분산 경계를 검토해야 한다. 이는 [공식 source](https://github.com/facebookresearch/demucs/blob/v4.0.1/demucs/separate.py#L158)의 정적 관찰이며 이번 실추론 결과가 아니다. 손상 입력을 재시도로 은폐하거나 비정상 tensor를 정수 WAV로 변환해 정상 출력으로 처리하지 않는다.

PANNs Cnn14 후보는 문헌 조사 결론 **defer**다. 근거·라이선스 미확인·실제 비용 unknown은 [선행 보고서](../../reports/w06-separation-preflight-report.md#panns-cnn14-후보-문헌-조사)에만 상세 기록한다. 분리 후 stem 에너지는 사후 QC 후보이며 분리 전 bypass 근거가 아니다. 실제 solo/mixed/voice 자료의 권리 확인·곡 단위 보정/평가 분리와 false-bypass 허용 기준은 후속 평가 계획의 선행 조건이다.

제품 구현 전에 다음을 충족해야 한다.

1. FFmpeg를 승인 탐색 경로에 준비한 새 run에서 모델 자산·lock·정상2입력/무음·손상·취소·timeout 검증을 수행하고 미해결 결함을 처리한다.
2. 실제 혼합 음악에 대한 분리 품질과 QC 판별의 평가 기준·고정 자료를 별도 계획으로 확정한다. 이번 CC0/sine 대조군을 음악 품질 benchmark로 확대하지 않는다.
3. Canonical separation/artifact/adapter/runtime 사양, 전용 보고 role, QC 미측정 표현과 TRANSCRIBE 입력 선택을 함께 설계·승인한다. 후속 실행 계획은95점 이상/B0I0이어야 한다.
4. 실제 CANONICAL_AUDIO를 공급할 DOWNLOAD/PREPROCESS provider와 Piano AMT 제품 연결 대기를 별도 의존성으로 관리한다. W06 provider 하나로 업로드부터 악보까지의 end-to-end 지원을 주장하지 않는다.

이 초안의 문서 리뷰 통과는 사용자 설계 승인·제품 구현 계획 점수·실제 CPU 지원 검증을 대신하지 않는다.
