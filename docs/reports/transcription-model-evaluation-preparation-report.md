# W05 기본 전사 모델 평가 착수 조사

2026-10-04 · 기준 commit `d0c6c93` · 상태: 자료 조사 및 평가 설계 방향 확인 중. 모델 비교 실행·기본 모델 결정은 아직 수행하지 않았다.

## 목적과 확인한 조건

W04는 모델 호출과 결과 등록의 정확성을 검증했다. W05는 정답 음원과 MIDI로 전사 정확도·처리 시간·실패율을 측정해 기본 모델과 fallback 정책을 결정한다. AGENTS.md의 계획/구현 리뷰100점과 모델 F1은 서로 다른 값이다. 사용자는 평가 데이터를 **비상업 연구·개인 개발용**으로 사용하는 범위를 확인했다.

현재 설치된 후보는 Basic Pitch0.4.0 source `049dc8a01a170c2370d7b246ec1c2067e060c3bf`·독립 Python3.12·ONNX CPU worker다. checked-in `basic_pitch_smoke.wav`는16초 CC0 실행 확인용 음원으로 정답 MIDI가 없다. notes113개 생성 사실을 정확도 점수로 환산할 수 없다. 두 번째 후보 ByteDance Piano AMT의 worker·환경·checkpoint는 아직 저장소에 설치되지 않았다.

## 확인한 공식 자료

| 대상 | 확인 내용 | 근거 |
| :--- | :--- | :--- |
| MAESTRO3 | 실제 피아노 audio/MIDI 정렬, 공식 train/validation/test 구분, CC BY-NC-SA4.0. 전체 archive101GB이므로 평가 subset 취득을 먼저 설계 | [공식 dataset](https://magenta.withgoogle.com/datasets/maestro) |
| 평가 metric | pitch+onset matching과 pitch+onset+offset matching을 구분. 기본 onset50ms, pitch50cents, offset은50ms와 reference duration20% 중 큰 값. 최대 이분 매칭으로 중복 추정을 여러 정답에 중복 인정하지 않음 | [mir_eval transcription](https://mir-eval.readthedocs.io/latest/api/transcription.html) |
| ByteDance 모델 | 원저자는 Python3.7/PyTorch1.4 환경과 MAESTRO2 학습을 기록. 해당 논문의 공개 inference package를 비교 후보로 사용 | [학습/모델 저장소](https://github.com/bytedance/piano_transcription), [inference README](https://github.com/qiuqiangkong/piano_transcription_inference) |
| inference revision | 현재 master commit `0226e74cbc805660e34bbd6a8fed2083890ebb88` (2025-01-26), setup version0.0.6·MIT classifier | [공식 commit metadata](https://api.github.com/repos/qiuqiangkong/piano_transcription_inference/commits/master), [setup.py](https://raw.githubusercontent.com/qiuqiangkong/piano_transcription_inference/0226e74cbc805660e34bbd6a8fed2083890ebb88/setup.py) |
| pretrained checkpoint | 공식 Zenodo record4034264, 공개 CC BY4.0, `CRNN_note_F1=0.9677_pedal_F1=0.9186.pth`,171,966,578bytes, 공개 MD5 `22b961b77c1878239fec963362097045` | [공식 record](https://zenodo.org/records/4034264), [공식 metadata](https://zenodo.org/api/records/4034264) |

checkpoint metadata와 source revision은 public API를 read-only로 확인했다. 파일명에 들어 있는 논문 F1은 이 프로젝트에서 측정한 성능이 아니다. checkpoint 파일 자체는 받지 않았으므로 SHA256과 현재 PyTorch 호환성은 아직 검증하지 않았다. 공식 inference README도 Windows를 미검증으로 표시하므로 실제 실행 후 판단한다.

호스트 read-only 진단에서 NVIDIA GeForce RTX3060·12,288MiB·driver596.21을 확인했다. GPU 존재만으로 PyTorch/CUDA 실행 성공을 주장하지 않는다.

## 제안하는 평가 방향

추천은 **소규모 실제 정답 데이터로 두 후보를 직접 비교**하는 방식이다. MAESTRO3 test split의 서로 다른12개 녹음에서 고정 구간을 사용하고, 선정 manifest·원본/파생 파일 해시·구간·dataset version을 추론 전에 고정한다. 각30초를 제안하며 crop 경계와 pedal/key-release 의미는 서면 설계에서 정확히 정한다. ByteDance 학습 데이터인 MAESTRO2의 split과 대조해 해당 녹음이 train/validation에 속하지 않는지 확인한다. 알려지지 않은 Basic Pitch 학습 중복은 미확인으로 기록한다. 원본 audio/MIDI는 ignored 평가 폴더에 보관하고 MIT 코드 저장소에 dataset을 재배포하지 않는다.

평가 도구와 새로운 후보의 모델 dependency는 독립 환경에 둔다. root/API 및 기존 Basic Pitch lock은 유지한다. 모델은 사전 설치된 환경과 checkpoint를 사용하며 실제 평가 요청에서 자동 다운로드를 하지 않는다. 공식 inference source는 checkpoint가 없거나 작으면 다운로드하므로 adapter가 명시적 파일과 hash를 먼저 확인해야 한다 ([공식 inference.py](https://raw.githubusercontent.com/qiuqiangkong/piano_transcription_inference/0226e74cbc805660e34bbd6a8fed2083890ebb88/piano_transcription_inference/inference.py)).

정확도는 pitch+onset F1과 pitch+onset+offset F1을 각각 기록하며 precision/recall·누락/추가 음표도 함께 남긴다. 페달과 velocity는 실제 지원 후보의 별도 지표로 분리한다. 시간은 audio duration 대비 real-time factor와 모델 cold start/추론 구간을 구분한다. 공통 CPU 비교와 ByteDance의 선택형 GPU 결과는 같은 속도 표의 동일 조건으로 섞지 않는다. 실패는 누락 없이 분모에 포함하며 정상출력 실패·timeout·설정 실패를 구분한다. 임의로 정확도·속도를 합친100점은 만들지 않는다.

측정 전 선정 규칙을 고정하고 측정 후 바꾸지 않는다. 정상 실행·유효 결과를 필수 조건으로 삼고 accuracy를 우선 비교한 뒤 동률이면 처리 시간·설치/운영 복잡도를 판단한다. 작은 subset 결과는 그 평가 범위의 결정 근거로만 사용한다. 후보가 실행되지 못하면 미측정/부적격을 기록하며 다른 모델의 정확도 우위로 꾸미지 않는다. fallback은 실제로 검증하고 제품에 연결된 후보를 대상으로만 정의한다. 기본 모델 선정과 selector의 자동 활성화는 구분한다.

대안은 Basic Pitch 기준선만 먼저 만드는 방법(빠르지만 비교가 남음), 전체 test corpus를 평가하는 방법(대표성이 높지만 취득·실행 비용이 큼)이다. 이번에는 고정 subset의 두 후보 비교를 추천한다.

## 다음 단계와 현재 한계

새 평가 도구·정답 manifest·후보 실행 환경을 추가하는 architectural 작업이다. 적용한 [brainstorming skill](C:/Users/user/.codex/plugins/cache/openai-curated-remote/superpowers/6.4.2/skills/brainstorming/SKILL.md)은 설계 방향→서면 설계 검토→실행 계획 검토의 순서를 요구한다. 현재 요청한 방향 확인은 정답 데이터 기반 비교 범위에 대한 확인이며 제품 구현 승인이나 이미 작성된 계획의 승인이 아니다.

방향 확인 후 crop/reference 의미·subset 취득 제한·metric/집계·후보 환경·fallback/selection 규칙을 서면 설계로 완성한다. 그 설계를 검토한 뒤 실행 가능한 계획을 작성하고 AGENTS.md의 독립95점 게이트를 적용한다. 아직 계획/구현 점수가 없으며 W05가 완료됐다고 표시하지 않는다. 비교 코드·모델 설치·dataset/checkpoint 다운로드·제품 설정 변경은 하지 않았다.

## 문서 변경 검증

root 회귀 **308 passed/17 skipped/8 deselected**(12.33s), `git diff --check` 통과. 실행 명령은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w05/research-docs-ready --tb=short`다. 처음 basetemp 상위 폴더를 만들지 않아 FileNotFoundError setup182건이 발생했으며 폴더 생성 후 같은 코드로 재실행해 통과했다. 이는 제품/모델 평가 실패나 행동 RED가 아니다. 변경은 조사 보고서·진행 현황·색인뿐이다.
