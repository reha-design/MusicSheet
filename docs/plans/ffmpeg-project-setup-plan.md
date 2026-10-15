# FFmpeg 설치·MusicSheet 적용 계획

## 목표와 범위

현재 확인된 경로에 FFmpeg가 없으므로 **FFmpeg 실행 파일을 설치하고 `FFMPEG_EXECUTABLE`에 그 위치를 설정**한다.

사용자가 선택한 **MusicSheet 전용 portable 설치**로 진행한다. 완료 기준은 설치·프로젝트 환경 적용·실제 WAV 변환 성공이다. Demucs 설치와 추론은 기존 W06 계획의 후속 실행으로 남긴다.

## 1. 버전 고정 설치

- FFmpeg 공식 다운로드 페이지가 안내하는 **Gyan Windows x64 Essentials 9.0.2 ZIP**을 사용한다. [공식 안내](https://ffmpeg.org/download.html), [배포 페이지](https://www.gyan.dev/ffmpeg/builds/)
- 설치 위치는 `C:/Users/user/Documents/Git hub/MusicSheet/outputs/tools/ffmpeg/9.0.2`로 고정한다. `bin` 아래에 `ffmpeg.exe`와 `ffprobe.exe`를 두고 배포본의 라이선스·문서를 보존한다.
- 버전이 명시된 ZIP을 내려받아 다음 고정 SHA256 및 배포자 checksum과 일치하는지 확인한 후 압축을 해제한다.

  ```text
  60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba
  ```

  [배포자 checksum](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip.sha256)

- 다운로드 URL·크기·hash·실행 파일 hash·버전을 설치 manifest에 기록한다. 기존 설치가 있으면 manifest와 일치할 때만 재사용하며, 불일치·실행 파일 누락·버전 오류는 중단한다.

## 2. 프로젝트 환경 적용

- gitignored 로컬 `.env`에 다음 두 값을 같은 **`ffmpeg.exe` 절대경로**로 저장한다.

  | 설정 | 용도 |
  |---|---|
  | `FFMPEG_EXECUTABLE` | 모델 실행·W06 검증 |
  | `FFMPEG_BIN` | API의 FFmpeg 진단 |

- 현재 `.env`가 없으므로 두 설정만 작성한다. 실행 시 기존 파일이 생겨 있다면 백업하고 대상 키만 갱신한다. 중복 키는 임의로 선택하지 않고 중단한다.
- 코드의 자동 `.env` 로딩을 추가하지 않는다. 프로젝트 실행 명령에 `uv run --env-file`을 명시한다.
- 검증과 Demucs 실행용 자식 PowerShell은 `uv run --no-project --no-sync --env-file <환경파일 절대경로>`로 시작한다. 설치 `bin`을 **해당 자식 프로세스 PATH 앞에만 추가**해 `ffmpeg`와 `ffprobe`를 찾도록 한다.
- 자식 프로세스의 두 설정이 설치 manifest 경로와 정확히 일치하는지 검사한다. 상속된 환경변수와 충돌하면 중단한다.
- README·환경 설정 예제·런타임 문서에 실행 방법을 기록한다. Windows 사용자·시스템 환경변수와 PATH, 전사 provider 활성화 설정은 변경하지 않는다. 실행 중인 서비스는 강제 재시작하지 않는다.

## 3. 검증과 실패 처리

- 두 실행 파일의 `-version`이 exit 0이며 버전 9.0.2인지 확인한다.
- 새 자식 프로세스에서 두 환경변수와 `Get-Command ffmpeg`, `Get-Command ffprobe`가 설치 파일을 가리키는지 확인한다.
- 기존 CC0 fixture hash를 확인하고 새 증거 폴더에 **44,100Hz·stereo·PCM16 WAV**로 변환한다. `ffprobe`와 Python 전체 decode로 **705,600 frames·16초**를 확인한다.
- 명령·stdout·stderr·종료 코드·입출력 hash를 보존한다. 설치 helper를 작성하면 hash 불일치·누락 파일·잘못된 경로·버전 불일치의 중단 동작도 검증한다.
- 기존 5개 lock·fixture·W05 manifest·W06 중단 증거를 보존하고 문서 링크·diff·git ignore를 검사한다. 제품 코드 변경이 없으므로 전체 테스트와 모델 benchmark는 반복하지 않는다.
- 실패 시 진단 증거를 보존한다. 설정 적용 중 실패하면 대상 키를 백업 상태로 복구하며 기존 설치와 다른 환경 설정은 보존한다.

## 산출물과 리뷰 게이트

- 실행 시 계획과 결과보고서를 저장하고, 설치·검증 증거는 ignored 실행 폴더에 보존한다. 바이너리와 로컬 환경 파일은 커밋하지 않는다.
- roadmap은 **“FFmpeg 준비 완료·W06 모델 검증 재개 대기”**로 갱신한다. 과거 추론 0회 보고서의 판정은 유지한다.
- **계획 R1 독립 리뷰: 100/100**, 2026-10-15, 항목별 **25/20/20/25/10**, blocker 0 / important 0 / minor 0.
- 설치→환경 적용→최종 검증 각 단위는 독립 리뷰 **95점 이상·미해결 blocker/important 0**이어야 다음 단위로 진행한다. 실행 시작 시 저장 계획의 본문 hash와 검토본을 대조하고 계획·구현 리뷰 점수를 별도로 기록한다.

<!-- APPROVED_PLAN_BODY_END -->

## 실행 기록

- 사용자 실행 승인: 2026-10-15, `PLEASE IMPLEMENT THIS PLAN`.
- 계획 reviewer: `/root/ffmpeg_application_plan_review`; 채팅 R1 100/100, B0/I0/M0. 저장본 대조 및 본문 hash는 별도 독립 확인한다.
- Ruling: 사용자가 지정한 현재 checkout와 portable 경로에서 설치·설정·문서만 변경한다. 기존 미커밋 W06 문서와 ignored 증거를 보존하며 제품 코드·의존성·기존 모델 환경을 변경하지 않는다. 일반 개발 skill의 별도 workspace/전체 suite보다 승인 계획의 실행·검증 범위를 우선한다.
- 저장본 독립 대조: 2026-10-15 `/root/ffmpeg_application_plan_review`, marker 이전 LF/UTF-8 본문 SHA256 `fecf2aee7a2cb14cc306e5d96143e5e18ce865394b92eef76f47d8672a3dca8b`, **100/100 (25/20/20/25/10), B0/I0/M0**. 승인 본문 및 상속 환경 충돌 중단 보충과 의미 동일성을 확인했다.
- 다운로드 클라이언트: sandbox curl DNS 실패(exit6), 허용된 네트워크 curl의 Schannel 폐기 확인 실패(exit35)를 보존했다. 동일 고정 URL을 기본 TLS 검증의 Invoke-WebRequest로 다운로드했다. 인증서 검증 우회·버전 변경은 하지 않았다.
- 단위1: 2026-10-15 `/root/ffmpeg_install_review`, **98/100 (25/25/25/15/8), B0/I0/M1**. 다운로드 wrapper receipt와 native 실행 receipt의 증거 수준 차이를 결과보고서에 명시해 minor를 처리했다. 필수 수정 지적 없이 단위2 진행 승인.
- 단위2 실행 표현: uv0.12.17의 env-file 목록 parser는 whitespace/backslash를 처리하므로 absolute 환경 파일을 forward slash 및 escaped space로 전달한다. 실패4회와 실제 escaped absolute child 성공·상속 충돌2case 거부를 보존했다. 문서의 저장소 root 실행은 `--env-file .env`를 사용한다. API/schema/runtime 선택이나 승인된 설치 범위 변경은 없다.
- 단위2: 2026-10-15 `/root/ffmpeg_environment_review`, **100/100 (25/25/25/15/10), B0/I0/M0**. env helper6case 및 escaped absolute uv child를 독립 재실행했고 상속충돌/원본보존을 대조했다. 단위3 진행 승인.
- 단위3 및 전체 최종: 2026-10-15 `/root/ffmpeg_final_review`, 각각 **100/100 (25/25/25/15/10), B0/I0/M0**. 검토7문서 snapshot SHA256 `4ded99c1031b47e12adfd2b253d70a8c5788d6c01fe7cbbd2bdd7c6f880dd07b`는 최종 점수 감사 기록 추가 전 버전이다. 실제 WAV 전체 decode와 설치·환경·보존 checker를 독립 실행했다. 기존 단위1 98점·단위2 100점과 별도이며 점수를 대체하지 않는다.
- 결과: FFmpeg 준비 완료·W06 모델 검증 재개 대기. 바이너리·로컬 환경·변환 결과는 ignored에 보존했다. Demucs 설치·추론·제품 provider 활성화는 수행하지 않았다. 최종 감사 기록 후 fresh verification을 수행한다.
