# FFmpeg 프로젝트 전용 설치·적용 보고서

작업일: 2026-10-15 · 시작 HEAD `7cf277f608039affae597b4c095af2a01867ed25`.

[승인 계획](../plans/ffmpeg-project-setup-plan.md)에 따라 Windows x64 Gyan Essentials9.0.2의 MusicSheet 전용 portable 설치·환경 적용·실제 WAV 변환을 수행했다. 단위별 리뷰와 최종 검증은 아래 별도로 기록하며 미기록 리뷰를 통과로 간주하지 않는다. Demucs 설치·추론과 전사 provider 활성화는 이번 범위가 아니다.

## 단위1: 설치 증거

- 설치 root: `outputs/tools/ffmpeg/9.0.2/`; 실행 파일 `bin/ffmpeg.exe`, `bin/ffprobe.exe`. `LICENSE`, `README.txt`, `doc`, `presets` 등 원래 배포 파일45개를 전부 보존했다. `installation.json`은 원래 배포본과 별도로 추가한 로컬 inventory다.
- archive: `https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip`, **114,768,076 bytes**.
- 고정 SHA256/배포자 checksum/실제 ZIP: 모두 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`로 일치. TLS 기본 인증서 검증을 사용했다. 이 비교를 별도 서명 검증으로 표현하지 않는다.
- ffmpeg SHA256: `3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec`.
- ffprobe SHA256: `f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52`.
- 두 실행 파일 모두 `-version` **exit0**, `9.0.2-essentials_build-www.gyan.dev`를 출력했다. 전체 stdout/stderr와 argv/exit/hash를 별도 receipt로 보존했다.
- ZIP 내 entry의 해제 경로가 staging 내부인지 확인하고 고정 hash 확인 후 해제했다. 최종 이동의 source와 destination을 프로젝트 내부로 검증하고 기존 설치가 없을 때만 Move-Item으로 정규화했다.

로컬 실행 증거: `outputs/ffmpeg-setup/20261015-install-01/`. `start.json`, 작업 전323개 파일 snapshot, W06 기존 증거12개 snapshot, process/user/machine 환경 snapshot과 다운로드·해제·버전 receipt가 있다. 환경 snapshot은 ignored 로컬 증거이며 출력/커밋하지 않는다.

첫 sandbox curl은 DNS 제한으로 exit6, 네트워크 허용 curl은 Schannel `CRYPT_E_NO_REVOCATION_CHECK`로 exit35였다. 실패 명령과 stdout/stderr를 보존했다. 기본 TLS 검증의 Invoke-WebRequest로 **같은 고정 URL**을 받아 checksum과 ZIP hash를 대조했다. `SkipCertificateCheck`, TLS 검증 비활성, 자동 버전 변경은 사용하지 않았다.

### 설치 검증 helper

ignored `validate-install.ps1`는 절대 설치 root·manifest version/pin·원본45개 inventory의 hash/bytes·필수 실행 파일/라이선스/README·실제 실행 버전을 검증한다. `test-install-validation.ps1`의 **6개 case PASS**: 실제 설치, 상대 root 거부, 다른 버전 거부, 누락 exe 거부, 파일 hash 변조 거부, archive pin 변조 거부. 부정 case는 별도 fake manifest/빈 폴더를 사용해 실제 설치를 변경하지 않았다. 결과는 `install-validation-tests.json`이다.

## 리뷰 기록

- 계획 저장본: `/root/ffmpeg_application_plan_review`, 2026-10-15, **100/100 (25/20/20/25/10), B0/I0/M0**.
- 승인 본문 SHA256: marker 이전 LF/UTF-8 `fecf2aee7a2cb14cc306e5d96143e5e18ce865394b92eef76f47d8672a3dca8b`.
- 단위1·단위2·단위3 및 최종 점수는 각각 실제 독립 리뷰 후 기록한다. 계획 점수는 구현 점수를 대신하지 않는다.

### 단위1 독립 리뷰

2026-10-15 `/root/ffmpeg_install_review`: **98/100 (25/25/25/15/8), B0/I0/M1**, 단위2 진행 승인. 범위는 설치/manifest/배포45파일/다운로드·해제·버전 receipt/두 helper/6-case 증거/보존 snapshot이다. reviewer가 ZIP hash/배포 checksum과45파일hash/크기, 실제 두 실행 파일 version/exit, W06증거12개 불변과 환경 미적용을 독립 확인했다.

Minor1 처리: Invoke-WebRequest receipt는 URI/client/default TLS/취득시각/catch 성공 상태를 기록한 PowerShell wrapper 결과이며, 별도 native process argv/exit/원본 stdout/stderr를 수집한 자료가 아니다. 버전 실행 receipt와 증거 수준을 구분한다. 관찰된 checksum 도구 shell은 chunk `87a3d9` exit0, ZIP 도구 shell 완료는 chunk `a60c25` exit0이며 이는 이 채팅 tool 결과에 대한 참조다. 재다운로드는 하지 않았다. 이 문서 설명 보완으로 범위를 명시했으며 점수를 임의 상향하지 않는다. 필수 수정 지적은 없다.

## 단위2: 환경 적용

로컬 `.env`를 신규 생성해 `FFMPEG_EXECUTABLE`과 `FFMPEG_BIN` 두 키만 기록했다. 같은 `C:/Users/user/Documents/Git hub/MusicSheet/outputs/tools/ffmpeg/9.0.2/bin/ffmpeg.exe` 경로를 quoted 값으로 저장했다. 환경 파일 SHA256 `83301a7668eb4c35e6197cfe3a4721bfc2c3b311ed9b97bff176f30e5a591e6d`, 적용 receipt는 `env-apply.json`이다. 기존 파일이 없었으므로 실제 backup/rollback은 필요하지 않았다. CreateNew 쓰기로 뜻하지 않은 기존 파일 덮어쓰기를 방지했다.

ignored env-text helper의 **6-case PASS**: 두 키 신규 생성, 다른 키/주석/CRLF 보존, 중복 키 거부, 대소문자 혼합 중복 거부, 상대 경로 거부, 닫히지 않은 quote 거부. 실제 파일 생성은 설치 재검증 후 수행했다. existing-file 경로는 원본 bytes를 ignored 증거에 백업하고 쓰기 직전 변경 여부를 확인하는 절차로 준비했으며 실제 existing-file 교체/rollback을 수행했다고 주장하지 않는다.

### 별도 자식 프로세스 환경 확인

`uv run --offline --no-project --no-sync --env-file <escaped absolute .env> --python <기존 Python3.13.15> -- pwsh -NoProfile -File check-child-env.ps1 ...`를 실행했다. 기존 Python 실행 파일을 선택했고 UV cache는 새 ignored run 폴더에 한정했다. 모델 환경 설치·프로젝트 dependency sync는 하지 않았다.

- `child-environment-escaped.json`: **exit0**, 자식 PID37756, 두 키 절대경로/동일 값 확인, manifest 실행 파일 hash 대조, 자식 PATH의 두 tool 해석과9.0.2/exit0 확인. 원본 stdout/stderr는 같은 prefix의 `.stdout.log`/`.stderr.log`에 보존했다.
- `inherited-conflict-tests.json`: 각 키에 다른 상속값을 넣은 별도 child2개가 **exit1/ConfigurationMismatch**로 거부됐다. 잘못된 상속값을 fallback이나 자동 덮어쓰기로 숨기지 않았다.
- `environment-preservation.json`: 부모 tool process 및 Windows User/Machine의 PATH/두 FFmpeg 키를 시작 snapshot과 대조해 **불변** 확인. PATH 추가는 child 내부에서만 수행했다.
- `.env.example`, README, runtime 문서에 두 설정의 역할과 명시적 `--env-file .env`/프로젝트 자식 셸 실행을 기록했다. 실제 API/worker를 기동·재시작하거나 TRANSCRIPTION_PROVIDER를 활성화하지 않았다.

처음 absolute `--env-file` 인자는 backslash/공백이 uv의 env-file 목록 parser에 의해 분리돼 exit2였다. ProcessStartInfo.ArgumentList와 forward slash만으로도 같은 실패가 재현됐고 literal quote를 추가하는 시도도 실패했다. 이 기록은 `child-environment-command.json`, `child-environment-argumentlist.*`, `child-environment-forwardslash.*`, `child-environment-quoted.*`에 보존했다. [upstream 구현](https://github.com/astral-sh/uv/pull/15815/files)의 whitespace/backslash 처리와 대조해 **forward slash로 바꾸고 공백을 `\ `로 escape한 절대경로**를 전달한 뒤 통과했다. 현재 uv는0.12.17이다. README에서는 저장소 root의 상대 `.env`를 사용해 추가 escape가 필요 없게 안내한다.

이는 실행 인자 표현의 수정이며 계획의 절대 환경 파일·프로젝트 전용 범위는 유지한다. runtime/제품 코드/의존성 변경으로 우회하지 않았다.

단위2 독립 리뷰: 2026-10-15 `/root/ffmpeg_environment_review`, **100/100 (25/25/25/15/10), B0/I0/M0**. env helper6case와 escaped absolute uv child를 직접 재실행해 PASS/exit0(PID12128, `review-unit2-environment.*`)를 확인했다. README relative env-file child(PID32556)와 상속 충돌2case 증거를 대조했다. baseline323개 중 승인 문서4개 외319개, W06증거12개 불변과 `git diff --check`를 확인했고 단위3 진행을 승인했다.

`--no-sync`는 `--no-project`와 함께 사용할 때 효과가 없다는 uv 경고가 원본 stderr에 있다. 이 실행의 환경 비동기화 근거는 프로젝트 발견 제외·offline·기존 Python 지정 및 실제 명령 범위이며 해당 경고를 숨기지 않았다.

## 단위3: 실제 WAV 변환

적용된 `.env`를 escaped absolute 인자로 로드한 새로운 uv→PowerShell child(PID33100)에서 PATH/두 설정/실행 파일 hash를 확인하고 실제 변환했다. `convert-fixture.ps1`는 원본 hash를 먼저 확인하고 `-n`으로 기존 결과 덮어쓰기를 막았다. `run-native.ps1`의 ProcessStartInfo.ArgumentList로 공백 포함 경로를 전달하고 argv/stdout/stderr/exit/time을 분리해 보존했다.

| 검사 | 실측 결과 |
|---|---|
| FFmpeg 변환 | exit0, `pcm_s16le`, 44,100Hz, stereo |
| ffprobe | exit0, audio stream1개, codec/rate/channels/duration 일치 |
| Python3.13.15 wave 전체 decode | exit0, 2byte sample, 705,600 frames, 16.0초, 압축 NONE |
| 원본 fixture SHA256 | `2970c7fca3ccc442c078eb0a4edb2f788731e9d36f5049cc2558fa68e599366a`, 실행 전후 동일 |
| 출력 WAV 크기 | 2,822,478 bytes |
| 출력 WAV SHA256 | `572e6ed6e87cb3b79f7ad193e05f636f4ac082868febdf8e43ebb2a18d5e36cb` |

결과는 ignored `fixture-44100-stereo.wav`와 `conversion-result.json`이다. `wav-smoke.*`, `ffmpeg-conversion.*`, `ffprobe-output.*`, `python-wave-decode.*`에 실제 명령과 원본 stdout/stderr·종료 코드를 기록했다. `.env`나 바이너리·결과 오디오를 추적 파일에 추가하지 않았다.

**FFmpeg 설치·환경 적용·기본 PCM 변환 증거를 확보했다. Demucs 실제 추론은 여전히0회이며 W06 CPU 지원·분리 품질·취소 검증은 별도 재개 대상이다.** 이전 W06 중단 보고서와 당시 ignored 증거는 수정하지 않는다.

## 최종 보존·문서 검증

`verify-final.ps1`의 `verification-before-review.json`은 PASS다. 시작 working snapshot323개 중 변경 허용 문서는 환경 예제·README·runtime·main_spec·roadmap·이번 계획6개이며 나머지317개는 hash가 같다. 기존5lock·fixture·W05 manifest·이전 W06 계획/보고/Proposed 설계·미추적 정리 문서를 보존했고, 이전 ignored W06증거12개도 hash/bytes가 같다.

부모 process/User/Machine의 PATH·두 FFmpeg 변수 불변, 설치45파일 inventory와 실제 두 tool 버전, 로컬 `.env` hash·ignore, 변환 WAV hash/receipt, 승인 본문 hash, 문서 로컬 target 존재, `git diff --check`, 예상 untracked 범위를 확인했다. 링크 fragment/원격 URL의 지속 가용성, 실제 API/worker 기동, 접근 불가 W05 실제 원장 재검증은 범위가 아니다. 전체 suite/모델 benchmark는 승인 범위에 따라 미실행이다.

일회성 수집·검증 helper는 ignored run 폴더에만 두었다. 최종 보존 checker의 Git inventory는 한 번 읽어 재사용하도록 정리했으며 기준·합격 조건은 변경하지 않았다. 단위3/전체 독립 리뷰 결과는 검토본 snapshot과 함께 아래 감사 기록에 추가한다.

## 최종 독립 리뷰 및 완료 판정

2026-10-15 `/root/ffmpeg_final_review`:

| 리뷰 | 요구사항 | 오류·경계·보안 | 검증 | 구조 | 문서·재현성 | 합계 | 지적 |
|---|---:|---:|---:|---:|---:|---:|---|
| 단위3 실제 변환·최종 검증 | 25 | 25 | 25 | 15 | 10 | **100/100** | B0/I0/M0 |
| 전체 승인 계획 준수 | 25 | 25 | 25 | 15 | 10 | **100/100** | B0/I0/M0 |

검토7문서와 hash/bytes는 `review-snapshot.json`에 보존했다. snapshot SHA256 `4ded99c1031b47e12adfd2b253d70a8c5788d6c01fe7cbbd2bdd7c6f880dd07b`는 이 최종 점수 감사 기록 추가 전 버전이다. scope는 계획·보고·환경 예제·README·runtime·main_spec·roadmap 및 ignored 설치/설정/변환/검증 helper와 실제 receipts/산출물/보존 snapshot이다.

Reviewer가 `verify-final.ps1`를 독립 실행해 exit0/PASS(UTC07:21:14)를 확인했다. 실제 출력 WAV에 기존 Python의 `verify-wav.py`를 직접 재실행해 전체705,600 frames/16초 및 hash를 확인했으며 변환을 다시 수행하지 않았다. ZIP/설치45파일·두 tool version, 실제 변환3개 프로세스 exit0, 원본·환경·기존 W06 증거 보존, child 충돌 거부, 문서의 현재 설정 계약을 대조했다. 미해결 지적은 없다.

**설치98점·환경100점·실제 변환100점·별도 전체100점으로 이번 FFmpeg 설치·적용 계획을 완료했다.** 계획100점과 단위/전체 점수는 별도다. 단위1의 다운로드 receipt 수준 minor 설명은 그대로 보존한다. 최종 점수/감사 기록 추가 후 fresh verification 결과는 ignored `verification-final.json`에 기록한다.

현재 사용할 설정은 프로젝트 `.env`의 두 절대경로다. 저장소 root에서 명시적 `uv run --env-file .env`와 필요한 child-only PATH 절차로 실행한다. 사용자·시스템 환경변수와 실행 중 서비스는 변경하지 않았다. **W06 Demucs 실제 모델 검증은 재개 대기이며 이번에 수행하지 않았다.**
