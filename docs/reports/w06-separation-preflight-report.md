# W06-0 음원 분리 선행 검증 보고서

평가일: 2026-10-15 · 기준: `main 7cf277f608039affae597b4c095af2a01867ed25`.

## 판정

**선행 조건 미충족 — 실제 Demucs CPU 검증은 미실행이다.** `FFMPEG_EXECUTABLE`은 미설정이며 PATH에도 `ffmpeg` application이 없다. [승인 계획](../plans/w06-separation-preflight-plan.md)의 도구 부재 중단 조건을 적용했다. 임의 설치·다른 경로 탐색·모델 대체를 하지 않았다.

| 구분 | 결과 |
|---|---|
| 단위1 환경·입력 준비 | 필수 FFmpeg 미확보; 증거 수집 완료, 모델 준비 미실행 |
| 단위2 실제 모델 실행·출력·취소·timeout | NOT_RUN — 선행 조건 미충족 |
| 비무음 CPU 검증 | NOT_VERIFIED; 성공 실행 0회 |
| 제품 연결 적합성 | HOLD — 실행·출력·취소 근거 없음 |
| W06 전체 완료 | 아니오; backlog 유지 |
| 단위3 QC 문헌 조사·설계 초안 | 문헌 조사·Proposed 초안 제출 완료; 독립99/100 |

## 환경·입력 증거

로컬 증거 디렉터리: `outputs/w06-preflight/20261015-prerequisites-01/` (git ignored).

- `collect.ps1`: 실행 가능한 환경·hash 수집 명령. `manifest.json`에 Python argv/exit/output, 도구 탐색 결과와 미실행 목록을 보존했다.
- OS: `Microsoft Windows 10.0.26200`, X64; processor identifier `Intel64 Family 6 Model 170 Stepping 4, GenuineIntel`; 논리 CPU 22개. CIM 접근 불가로 CPU 상품명·물리 RAM은 미확인이다. OS marketing name을 추정하지 않았다.
- Python: 절대 경로의 uv 관리 CPython **3.10.21**을 `-I -B -c`로 실행해 exit 0을 확인했다. 기존 모델 가상환경은 사용하지 않았다.
- FFmpeg: 환경 설정 `null`, PATH application `null`. 시스템 전체에 FFmpeg가 없다고 단정하지 않으며 승인된 탐색 경로에서 미발견이다.
- CC0 fixture SHA256: `2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a`, README 기대값과 일치. 변환·합성 입력 생성은 하지 않았다.
- `tracked-before.json`: 당시 추적 파일 전체의 bytes/SHA256. 기존 root/API/Basic/Piano/evaluator 5개 lock과 W05 manifest를 별도 manifest 항목에도 기록했다.
- W05 원장: 이 checkout의 `outputs/w05-evaluation`은 없다. 이전 보고서의 `D:/develop/.../cpu-4859d3f14e324c509a5b36238d0736ae` 경로는 접근 거부되어 원장 불변을 확인하지 못했다. W05 manifest hash 보존과 실제 원장 재검증을 구분한다.
- 첫 수집 시 원장 경로의 접근 거부가 terminating error로 전파됐다. `collection-attempt1.log`는 **0 bytes**로 오류를 담지 못했다. 접근 불가를 `null`과 error로 기록하도록 수정한 두 번째 수집은 manifest를 생성했지만 `collection-display-attempt2.log`는 OrderedDictionary 표시 오류로 모든 필드가 null이다. 표시를 수정한 세 번째 수집의 `collection.log`와 manifest가 최종 증거다. 모델 실행 오류가 아니다.
- `collection-tool-receipts.json`에는 채팅의 실제 `exec_command` 결과에서 옮긴 invocation, tool chunk ID와 outer shell exit(1/0/0)를 출처와 함께 기록했다. 첫 오류 원문은 tool 결과에서 전사했으며 원본 shell 로그로 표현하지 않는다. collector는 PowerShell 프로세스 내부 호출로 별도 native exit를 수집하지 않았으므로 null이다. Python subprocess의 exit 0과 구분한다. 첫 두 시점의 collector source hash는 미수집이다.

모델 source full SHA·구성/weight inventory·license 검증, 모델 다운로드·probe 설치·lock 생성/검사·import/load는 FFmpeg 선행 조건에서 중단해 미실행이다. 따라서 `uv lock --check --offline --project <probe>` 실행 증거도 없다. 정상 입력 2개·무음·손상 WAV·취소·timeout·stem 검증은 모두 미실행이다. 모델 weight 다운로드 0개, 추론 0회, 생성 stem 0개다.

## 실행 및 리뷰 기록

- 계획 R1: 92/100, B0/I2/M0. 무음 진단과 필수 정상 성공 분리, tensor 저장 전 finite 검사를 보완했다.
- 채팅 계획 R2: `/root/w06_preflight_plan_review`, 2026-10-15, **100/100 (25/20/20/25/10), B0/I0/M0**. READY 이후 강제 timeout 실행 1회 보충까지 검토했다. 구현 점수가 아니다.
- 저장 계획 본문: `<!-- APPROVED_PLAN_BODY_END -->` 앞부분을 UTF-8 BOM 없이 LF로 정규화한 SHA256 `300ce4aa119fb8f9f2dcf74907c9447a2afe455345ae526147853d5dd111a99a`. 사용자 실행 요청을 반영해 Plan Mode 문장의 시제를 바꾸고 산출물 경로를 저장소 상대 표기로 저장했다. 요구사항·후보 조합·합격 기준은 유지한다.
- 독립 단위 리뷰와 최종 검증은 아래 기록을 추가한다. 현재 미기록 단위는 통과로 간주하지 않는다.

### 저장 계획 및 단위1 독립 리뷰

Reviewer `/root/w06_unit1_review`, 2026-10-15:

- 저장 계획 본문을 새로 평가해 **100/100 (25/20/20/25/10), B0/I0/M0**. 위 본문 SHA256과 승인 R2의 의미 동일성을 확인했다. 과거 채팅 리뷰 점수의 소급 검증이 아니라 저장본의 독립 평가다.
- 단위1 최초 **94/100 (25/24/22/15/8), B0/I1/M0**. 첫 로그의 실제 크기와 중간 표시 오류, collector invocation/exit 출처가 불완전하다는 I1을 받았다.
- 보완 후 **98/100 (25/25/24/15/9), B0/I0/M0**. 빈 로그·null 표시·최종 로그를 구분하고 tool 전사 자료의 한계와 별도 collector exit 미수집을 명시해 I1을 해결했다. reviewer는 과거 tool 원문 자체를 독립 대조할 수 없다는 한계도 남겼다.
- 검토 범위: 저장 계획, collector, manifest, 실행 영수증, 로그와 선행조건 중단 보고. collector SHA256 `a3c874122eb515b044f6bb6a0af479d728d92fbfcd977dff1d1af71f8c450402`, receipt SHA256 `97d905051c2b359aa4c3f7121c2423e0389d9e936751660028749bd89d1ce405`, manifest SHA256 `1e12e8feebfb3941669393cd6836271e0971295e07e4c554660afe4318f87bcf`.
- 추적 파일317개 변경0, 5개 lock·fixture·W05 manifest·기존 미추적2개 hash/bytes 보존과 FFmpeg 미발견을 독립 확인했다. 단위3 문헌 조사로 진행하는 게이트를 통과했다. **단위2는 NOT_RUN이고 CPU 검증은 미통과**다.

## PANNs Cnn14 후보 문헌 조사

조사일 2026-10-15. weight 다운로드·설치·추론·정확도 평가를 하지 않았다. 아래 source는 조사 시점의 공식 master이며 실행용 full SHA를 고정한 상태가 아니다.

| 항목 | 확인 결과와 출처 |
|---|---|
| 역할 | AudioSet audio tagging 후보. 원본 음원에서 사용할 수 있는 clip 단위 모델이며 솔로 전용 판별기로 검증된 것은 아니다. [README](https://github.com/qiuqiangkong/audioset_tagging_cnn/blob/master/README.md) |
| 코드 라이선스 | MIT; copyright/notice 보존 조건. 모델 weight 권리와 별도로 취급한다. [LICENSE.MIT](https://github.com/qiuqiangkong/audioset_tagging_cnn/blob/master/LICENSE.MIT) |
| 공식 checkpoint | `Cnn14_mAP=0.431.pth`, Zenodo DOI `10.5281/zenodo.3987831`; 공개 목록은327.4MB, MD5 `541141fa2ee191a88f24a3219fff024e`. 다운로드/로컬 SHA256 검증은 하지 않았다. [발행자 모델 목록](https://zenodo.org/records/3987831) |
| weight 라이선스 | **미확인**. 조회된 Zenodo HTML의 Rights/License 값이 추출되지 않았고 `/api/records/3987831` 조회도 실패했다. 코드 MIT를 weight에 자동 적용하지 않는다. 모델 평가 착수 전 발행자 권리 표시를 확인해야 한다. |
| 입력 | 공식 tagging CLI는32,000Hz mono로 load하며 window1024/hop320/mel64/fmin50/fmax14000을 기본값으로 둔다. 별도16kHz checkpoint와 혼용하지 않는다. CPU branch가 존재하지만 현재 PC 성능은 미측정이다. [inference.py](https://github.com/qiuqiangkong/audioset_tagging_cnn/blob/master/pytorch/inference.py) |
| 관련 label | CSV에는 `Speech`(0), `Singing`(27), `Guitar`(140), `Bass guitar`(142), `Piano`(153), `Electric piano`(154), `Drum kit`(162)가 있다. label index는 관찰값이며 후속 실행에서는 source/CSV hash와 함께 고정해야 한다. [공식 label CSV](https://github.com/qiuqiangkong/audioset_tagging_cnn/blob/master/metadata/class_labels_indices.csv) |
| 출력 해석 | Cnn14는 각 class에 sigmoid를 적용한 clipwise 출력을 만든다. 따라서 piano 점수가 높다는 이유만으로 다른 악기가 없거나 solo 확률이 높다고 해석할 수 없다. 이는 source 구조에서 도출한 판단이다. [Cnn14 구현](https://github.com/qiuqiangkong/audioset_tagging_cnn/blob/master/pytorch/models.py#L128) |
| 비용 근거 | 327.4MB는 발행자 checkpoint 전송 크기이며 RAM/VRAM 사용량이 아니다. 실제 CPU 지연·peak RAM·추가 전처리 비용은 **unknown**이다. 원본 분류 비용이 Demucs 절약 비용보다 작다는 증거도 없다. |

**후보 결론: `defer`.** 관련 label과 CPU 경로는 조사할 근거가 있지만, weight 권리 표시·현재 런타임·솔로 정확도·추론 비용이 미검증이다. 실제 평가 계획에서 권리 확인, 고정 source/checkpoint/label hash, solo/mixed/voice 정답셋, 곡 단위 보정/평가 분리, false-bypass와 탐지 비용 기준을 먼저 확정한다. AudioSet mAP를 MusicSheet의 solo 정확도나 제품 합격 점수로 사용하지 않는다.

분리 후 stem 에너지는 이미 분리 연산을 수행한 뒤의 진단량이므로 사전 연산 생략의 근거가 될 수 없다. 사후 QC 후보로만 남기며 자동 우회는 비활성이다. 분리 종합 score·bleed/artifact 점수는 이번에 측정하지 않아 null/unknown으로 제안한다. 기존 필수 score 모델에0을 넣어 실제 측정을 가장하지 않는다.

제품 연결 계약과 필요한 후속 사양 변경은 [Proposed 설계 초안](../superpowers/specs/2026-10-15-separation-integration-design.md)에 정리했다. 이 보고서는 CPU 지원이나 제품 연결을 승인하지 않는다.

## 문서·원본 보존 검증

`outputs/w06-preflight/20261015-prerequisites-01/verify.ps1` 실행 결과는 `verification-before-review.json`에 기록했다. 결과는 PASS이며 모델 실행 PASS와 별개다.

- baseline 추적317개 중 변경은 `docs/main_spec.md`와 `docs/roadmap.md`뿐이다. 나머지315개 추적 파일은 byte hash가 같다.
- 기존5lock·fixture·W05 manifest·미추적 정리 문서2개의 hash/bytes, 총9개 보호 receipt가 일치한다. 접근 불가 W05 실제 원장은 이 검증에 포함하지 않는다.
- 계획 승인 본문 hash, collection receipt hash, 실행0회/weight0개/CPU미검증 상태를 확인했다.
- 새 W06 문서3개 및 현황/색인 문서의 로컬 파일·디렉터리 링크가 존재한다. fragment anchor와 원격 URL의 지속 가용성을 보증하는 검사는 아니다.
- 새 문서 whitespace, `git diff --check`, expected untracked 범위, 증거 디렉터리 git ignore를 확인했다. 첫 link checker는 기존의 유효한 `./reports/` 디렉터리 링크를 file-only 검사로 잘못 거부했다. 파일·디렉터리 target 모두 허용하도록 checker를 수정해 통과했으며 기존 문서를 불필요하게 변경하지 않았다.
- 제품 변경이 없는 승인 범위에 따라 전체 테스트·모델 benchmark는 실행하지 않았다. 환경 미준비를 skip된 모델 테스트의 성공으로 계산하지 않는다.

## 단위3 및 전체 독립 리뷰

2026-10-15 `/root/w06_final_review`:

| 리뷰 | 요구사항·동작 | 오류·경계·보안 | 검증 증거 | 구조·유지보수 | 문서·재현성 | 합계 | 지적 |
|---|---:|---:|---:|---:|---:|---:|---|
| 단위3 문헌 조사·계약 초안·보고 | 25 | 25 | 25 | 15 | 9 | **99/100** | B0/I0/M0 |
| 전체 W06-0 요구사항 준수 | 25 | 25 | 24 | 15 | 9 | **98/100** | B0/I0/M0 |

검토 범위는 계획·보고·Proposed 설계·roadmap·main_spec 5문서 및 ignored collector/verification script/manifest/receipts/snapshot/logs/literature sources다. `review-snapshot.json`의 5개 hash/bytes를 독립 대조했고 snapshot SHA256은 `b8b6506da7555a0a27a8d3db232d8ea163a2768cd1cbe2188f0fea417d025961`이다. 이 snapshot은 최종 점수·상태 감사 기록을 덧붙이기 전 문서 버전이다.

Reviewer가 `verify.ps1`를 읽고 재실행해 PASS를 확인했으며 제품·5lock·fixture·W05 manifest·backlog 대상 `git diff --exit-code`도 exit0이었다. FFmpeg 미발견을 다시 확인했고 공식 PANNs/Zenodo source와 현재 provider/input/quality/fingerprint 계약을 대조했다. 미해결 수정 지적은 없다. 차감은 mutable master/미보존 raw source, 첫 두 collector source hash/원본 오류 로그 미수집이라는 명시된 재현성 한계다.

**계획100점·단위1 증거98점·단위3 문서99점·전체 준수98점은 서로 별도다. 단위2와 실제 모델 지원은 미검증이며 제품 연결 승인·W06 완료가 아니다.** Reviewer는 snapshot 보존 및 실제 점수/처리 결과의 감사 기록 추가를 승인했다. 최종 감사 기록 후 동일 verification을 다시 수행한다.

## 재개 조건

실제 실행을 재개하려면 사용 가능한 FFmpeg 절대경로를 `FFMPEG_EXECUTABLE`로 제공하거나 PATH에서 확인할 수 있어야 한다. 새 run-id에 환경·hash 증거를 기록하고 단위1 준비부터 진행한다. 기존 미실행 증거를 덮어쓰지 않는다. 다른 후보 조합·기능 범위로 변경하려면 계획을 갱신하고 독립 재평가한다.
