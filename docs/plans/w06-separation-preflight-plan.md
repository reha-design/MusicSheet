# W06-0 음원 분리 선행 검증 계획

## 목표와 범위

Demucs `htdemucs_6s`의 **Windows CPU 실행 가능성과 출력 계약**을 확인하고, 피아노 솔로 자동 우회 후보와 후속 제품 연결 설계 초안을 제출한다.

이번 완료점은 **선행 검증 보고서**다. 제품 코드·API·DB·provider registry는 변경하지 않는다. 자동 우회 구현, Piano AMT 제품 연결, GPU·FP16·Linux Celery 검증은 후속 작업으로 둔다.

기준 커밋은 `main 7cf277f`다. 계획 제출 당시 Plan Mode에서는 파일 작성·설치·추론을 수행하지 않으며, 사용자의 실행 요청 후 실행 단계에서 진행한다.

## 실행 단위

### 1. 환경·입력·모델 준비

- 실험 환경과 산출물은 저장소의 ignored `outputs/w06-preflight/<run-id>/` 아래에 격리한다. 기존 가상환경은 재사용하지 않는다.
- 후보 조합은 **Python 3.10 / Demucs v4.0.1의 full commit SHA / torch 2.0.1·torchaudio 2.0.2 CPU / numpy 1.26.4**로 고정하고 나머지 의존성은 probe lock으로 잠근다. 설치→import→로컬 모델 load 순서로 검증한다. 이 조합은 실험 후보이며 제품 런타임 승인을 뜻하지 않는다.
- FFmpeg는 `FFMPEG_EXECUTABLE` 절대경로, 미설정이면 PATH에서 확인한다. 도구 부재·설치 실패는 근거를 기록하고 해당 실행을 중단한다. 다른 버전이나 모델로 임의 대체하지 않는다.
- 공식 모델 구성과 전체 weight는 준비 단계에서만 내려받는다. source commit, URL, 라이선스 근거, 구성·weight SHA256을 기록하고 실제 추론에서는 로컬 모델만 사용한다. [공식 소스](https://github.com/facebookresearch/demucs/tree/v4.0.1)
- 기존 CC0 피아노 fixture의 README hash를 확인한 뒤, 원본을 보존하면서 44,100Hz stereo PCM16 WAV로 변환한다.
- 현재 HEAD, OS·CPU·RAM, 실행파일 경로·버전과 기존 5개 lock·fixture·W05 manifest·가용 원장 hash를 기록한다. 접근할 수 없는 원장은 미확인으로 표시한다.

### 2. 실제 실행·출력·실패 경계 검증

- **필수 정상 입력 2개:** 16초 피아노와 피아노+440Hz sine. sine은 phase 0, 피아노 RMS 대비 −6dB로 만들고 합성 peak가 0.99를 넘으면 전체에 공통 gain을 적용한다. recipe·gain·입력 hash를 고정한다. 합성 입력을 실제 혼합 음악 품질의 근거로 사용하지 않는다.
- **별도 진단 입력:** 같은 길이 무음과 payload를 절반 자른 손상 WAV. 손상 파일은 추론 전 container·frame 검사에서 거부한다. 무음의 NaN·실패는 보정하지 않고 후속 제품 입력 검증 요구로 기록한다.
- 정상 2개와 무음 1개를 각각 한 번, 순차 실행한다. CPU/float32, seed 0, shifts 0, segment 7초, overlap 0.25, jobs 0, 실행당 timeout 1,800초로 고정한다.
- 공식 load→normalize→apply→save 흐름을 호출하는 임시 probe에서 **저장 전 tensor의 finite 여부**를 검사한다. 비정상 tensor는 실패 증거로 남기고 유효 stem으로 저장하지 않는다. 저장은 float32 WAV와 `clip-mode=rescale`로 고정한다.
- 정상 실행의 6개 stem 모두 decode, 44,100Hz stereo, 입력과 동일 frame 수, finite samples를 확인한다. 파일별 hash·크기·RMS·peak·silence ratio와 rescale 여부·gain·실행시간을 기록한다. silence ratio는 두 채널 모두 절댓값이 `1e-4` 미만인 frame 비율이다.
- 피아노 입력의 piano stem이 완전 무음이면 실패다. 청취 결과는 주관 관찰로 표시하고 종합 품질·누음·왜곡 점수를 임의 생성하지 않는다.
- 모델 load 후 apply 진입 직전 READY marker를 기준으로, **1초 후 취소하는 실행과 1초 timeout 실행을 각각 추가**한다. 소유 프로세스 트리가 5초 이내 종료되어야 한다. 미종료는 제품 연결 blocker로 남긴다.

### 3. QC 후보 조사·연결 계약·보고

- PANNs Cnn14의 공식 source·checkpoint·라이선스, piano·voice·기타 악기 label, 입력 규격과 비용 근거를 문헌 조사한다. 후보 추론이나 threshold 선정은 하지 않는다. 결론은 `evaluate` 또는 `defer`와 근거로 남긴다. [공식 저장소](https://github.com/qiuqiangkong/audioset_tagging_cnn)
- 분리 후 stem 에너지 비율은 **사후 QC 후보**로만 다룬다. 자동 우회는 비활성으로 유지하며, 실제 solo/mixed/voice 정답셋과 보정·평가 분리를 갖춘 후속 검증을 요구한다.
- 제품 연결 초안은 기존 `StageProvider.run(StageContext) -> tuple[ArtifactRef, ...]`를 유지한다. `CANONICAL_AUDIO` 하나를 받아 피아노 `SEPARATED_AUDIO`와 provenance/QC JSON을 반환하는 방향으로 정리한다.
- JSON에는 schema version, 입력·출력 hash, 모델·weight·runtime·options, bypass 여부·이유, 실측 QC와 미측정 `null`을 제안한다.
- QC 전용 artifact role, 필수 `SeparationQuality.score`의 미측정 표현, TRANSCRIBE 입력 선택·허용 role은 후속 사양 변경 항목으로 명시한다. 우회 시 원본 ref의 role을 수정하지 않고 별도 아티팩트를 저장한다.
- DOWNLOAD/PREPROCESS 미구현과 Piano AMT 제품 연결 대기를 의존성으로 기록한다.

## 검증과 합격 기준

- `uv lock --check --offline --project <probe>`와 모든 실행의 argv·exit·로그·검사 결과를 run manifest에 보존한다.
- 기존 lock·fixture·W05 자료와 제품 소스의 불변을 확인한다. 제품 수정이 필요하면 별도 계획과 독립 점수 게이트를 적용한다.
- **보고서 완료:** 성공·실패·미검증을 증거와 함께 기록하고 QC 조사와 설계 초안을 제출한다.
- **비무음 CPU PASS:** 정상 2개 입력의 tensor·6개 stem 검사 및 취소·timeout 종료 검증을 모두 통과한다. 무음 진단은 별도 판정한다.
- **제품 연결 적합성:** 무음 처리 등 미해결 결함이 있으면 보류한다. CPU PASS를 음악 분리 품질·자동 우회 정확도·GPU 지원 또는 W06 완료로 확대하지 않는다.
- 제품 변경이 없으므로 기존 모델 benchmark와 전체 테스트는 반복하지 않는다.

## 산출물과 리뷰 게이트

실행 단계에서 다음 문서를 저장한다.

- 계획: `docs/plans/w06-separation-preflight-plan.md`
- 결과: `docs/reports/w06-separation-preflight-report.md`
- Proposed 설계: `docs/superpowers/specs/2026-10-15-separation-integration-design.md`

실험 코드·오디오·weight는 ignored 실행 디렉터리에 보존한다. roadmap에 선행 검증 결과를 기록하고 W06 backlog는 유지한다. 기존 미추적 정리 문서 2개는 보존한다.

**계획 R2 독립 리뷰: 100/100, 2026-10-15, blocker 0 / important 0 / minor 0.** Reviewer `/root/w06_preflight_plan_review`; 항목별 **25/20/20/25/10**. R1 92점의 무음 합격 조건과 저장 전 수치 검증 지적 2건을 해결했다. 채팅 R2 전체 및 READY 이후 강제 timeout 1회 보충을 검토했다. 저장본의 시제·경로 표기 및 실행 기록은 아래 별도 감사 기록과 함께 대조한다.

실행 단위 1→2→3마다 산출물과 임시 probe 코드를 독립 리뷰하고, **95점 이상·미해결 blocker/important 0**이어야 다음 단위로 진행한다. 계획 점수와 실행 단위 리뷰 점수는 별도로 기록하며, 저장본의 본문 hash와 리뷰 범위를 대조한다.

<!-- APPROVED_PLAN_BODY_END -->

## 실행 감사 기록

- 사용자 실행 승인: 2026-10-15, `PLEASE IMPLEMENT THIS PLAN`.
- Ruling: 승인된 경로의 현재 checkout에서 문서와 ignored 증거만 작성한다. 제품 구현·branch 변경·추가 worktree·기존 환경 설치를 하지 않는다. 계획의 명시적 격리 위치와 제품 불변 범위가 일반 개발 skill의 workspace/setup/TDD 절차보다 우선한다.
- Ruling: FFmpeg 중단 조건이 충족되면 단위2는 `NOT_RUN`으로 기록하고, 단위1 독립 리뷰 후 단위3의 문헌 조사·문서 작업만 진행한다. 단위1의 증거 리뷰 통과는 모델 준비 또는 CPU 검증 PASS를 뜻하지 않는다.
- 진행 증거와 리뷰 상세: [결과보고서](../reports/w06-separation-preflight-report.md).
- 저장 본문 독립 재평가: 2026-10-15 `/root/w06_unit1_review`, UTF-8/LF marker 이전 본문 SHA256 `300ce4aa119fb8f9f2dcf74907c9447a2afe455345ae526147853d5dd111a99a`, **100/100 (25/20/20/25/10), B0/I0/M0**. 승인 R2와 의미 동일성 확인.
- 단위1 증거 리뷰: 최초94/100의 실행 provenance I1을 수정해 **98/100 (25/25/24/15/9), B0/I0/M0**. 모델 준비/CPU PASS가 아닌 선행조건 중단 증거 범위다.
- 단위2: FFmpeg 선행 조건 미충족으로 **NOT_RUN**, 구현/모델 검증 점수 없음. 단위1 reviewer가 단위3 문헌 조사로 진행을 승인했다.
- 단위3: 2026-10-15 `/root/w06_final_review`, **99/100 (25/25/25/15/9), B0/I0/M0**. 전체 요구사항 별도 리뷰 **98/100 (25/25/24/15/9), B0/I0/M0**. 검토5문서 snapshot SHA256 `b8b6506da7555a0a27a8d3db232d8ea163a2768cd1cbe2188f0fea417d025961`; 점수/처리 감사 기록 추가 전 버전이다. 실제 CPU 검증/단위2 PASS 점수가 아니다. 수정 필수 지적 없음; 명시된 로그·문헌 재현성 한계는 보고서에 남겼다.
- 실행 결과: 선행 조건 미충족 보고·QC 후보 `defer`·Proposed 설계 제출 완료. 실제 검증은 새 run의 FFmpeg 준비부터 재개하며 W06 backlog를 유지한다.
