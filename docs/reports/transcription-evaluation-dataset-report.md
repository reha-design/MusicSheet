# W05 Task2 — 고정 데이터·오디오·manifest 준비

2026-10-06 · BASE `d7e91c52d3644e99ab62ead8fc8b44aec07b3004` · [실행 계획 R5](../plans/transcription-model-evaluation-implementation-plan.md) 독립 계획100/100. 사용자 `다음 과정 진행해`에 따라 Task2를 구현하고 실제 고정 입력12개를 준비했다. 최종 독립 코드 리뷰100점·미해결 지적0으로 단위 게이트를 통과했다.

## 구현 및 무결성 경계

독립 Python3.13 평가기에 dataset/range_io/audio/manifest/prepare CLI를 추가했다. v3와 v2의 test split·MIDI 경로가 일치하고 duration>=90인 후보를 filename salted SHA256 순서로 정렬해12개를 고정한다. 별도 crop salt와 big-endian modulo로30초 시작점을 정하며 실패한 녹음/구간을 대체하지 않는다. 모델 실행 전에 선정한다.

공식 source는 [MAESTRO](https://magenta.withgoogle.com/datasets/maestro)의 v3.0.0 WAV/MIDI, CC BY-NC-SA4.0이며 사용자 승인 용도는 비상업 연구·개인 개발용 평가다. v2/v3 공식 metadata 원문을 보관하고 해시를 고정한다. 검증된 local archive 또는 receipt가 있는 extracted directory를 우선 사용할 수 있다. 전체 archive SHA256 검증과 부분 Range 취득의 CRC/member SHA256 검증을 구분한다. 부분 취득을 전체 archive SHA256 검증으로 주장하지 않는다.

[Python3.13 zipfile](https://docs.python.org/3.13/library/zipfile.html)이 ZIP64·중앙 directory·CRC를 처리한다. 직접 ZIP64 parser를 작성하지 않았다. HTTPX streaming은 identity/206/Content-Range/길이/동일 ETag를 body 전에 확인한다. 200/416/redirect/gzip/object 변경은 거부한다. 1MiB 캐시로 작은 ZIP 연속 읽기를 묶고 재시도까지 전송량에 포함한다. source receipt는 schema/license/URL/무결성 주장/bytes/hash/CRC/24개 member 집합을 검사한다.

상한은 metadata4MiB, 단일 ZIP read16MiB, Range 요청1MiB, member2GiB, transfer6GiB, decoded8GiB, free10GiB, request60초, acquisition30분, 재시도2회다. stop-aware chunk I/O는 기존 W04 run_owned_io로 종료까지 소유한다. 완료된 source를 보존하고 소유한 .part만 삭제한다. 불완전 취득의 재시작은 새 output root를 사용한다.

원본 stereo PCM16의 같은30초 crop을 float64 mono로 downmix하고 [FFmpeg swr](https://ffmpeg.org/ffmpeg-resampler.html)의 filter_size32/phase_shift10/linear_interp1/cutoff0.97/float64/no dither로 resample한다. clip·ties-to-even·포화 PCM_S16LE로 정확히661500/480000frames를 생성한다. FFmpeg version/두 argv/PCM revision/source crop·mono SHA/frames/elapsed receipt를 보존한다. FFmpeg child는 W04 run_owned_process로 timeout/cancel/drain을 처리한다.

고정 manifest는 relative path/hash/receipt만 추적하며 WAV·MIDI·reference note 배열은 ignored outputs에 둔다. 입력 준비 후 ignored manifest를 먼저 로드 검증한 다음 tracked manifest를 발행한다. loader는 wrapper·receipt 해시, metadata와 고정 선정/구간, 원본24개와 derived/reference 파일 해시, 비링크 workspace 경로를 검사한다. CLI 경로 탈출은 network 전에 거부한다.

## 검증 기록

데이터 출처 논문은 Hawthorne et al., [Enabling Factorized Piano Music Modeling and Generation with the MAESTRO Dataset](https://openreview.net/forum?id=r1lYRjC9F7), ICLR2019다. 사용자 승인 평가 목적과 데이터의 비상업 조건을 유지한다.

모든 테스트는 repo root에서 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project tools/transcription-eval --python 3.13 pytest -c tools/transcription-eval/pyproject.toml tools/transcription-eval/tests -q -p no:cacheprovider --basetemp D:/develop/MusicSheet/outputs/.verification-w05/<고유명> --tb=short`를 사용했다.

| 검증 | 고유 basetemp | 결과 |
|---|---|---|
| Task1 baseline | t2-baseline | 62 passed |
| Task2 RED | t2-red | 미구현 module collection4 errors |
| 초기 GREEN | t2-first-green | 47 passed |
| local directory RED | t2-local-dir-red | trusted extraction 복사 미지원1 failed |
| cache/CLI RED | t2-cache-cli-red | 요청33회 및 CLI 미구현2 failed |
| CLI 경로 RED | t2-cli-path-red | path escape가 network 호출1 failed |
| source fence RED | t2-original-hash-red | 원본 MIDI 변조 미감지1 failed |
| 경계 보완 GREEN | t2-fences-green | 114 passed |
| 추가 경계 | t2-boundaries | 125 passed/열 metadata 순서 fixture1 failed |
| 취득 전 전체 GREEN | t2-pre-live | 126 passed, 9.57초 |
| loader 취소 RED | t2-loader-cancel-red | stop 인자 미지원1 failed |
| loader 취소 GREEN | t2-loader-cancel-green | 126 passed, 10.46초 |
| Windows ACL RED | t2-acl-red4 | 임시 파일 ACL의 최종 파일 전파1 failed |
| audio ACL GREEN | t2-acl-green | 10 passed, 3.59초 |
| 최종 전체 evaluator | t2-final-full | 128 passed, 13.17초 |
| 기존 root 회귀 | t2-root | 308 passed/17 skipped/8 deselected, 12.79초 |

metadata 순서 fixture는 canonical JSON의 숫자 key가 사전 순서로 직렬화된 결과를 입력 순서와 비교한 테스트 오류였다. 사양인 고정 선정 결과를 비교하도록 수정했다. ZIP symlink/encryption/CRC/unsupported compression/member·decoded cap, >4GiB virtual ZIP64, 중앙 directory read cap, ETag 변경·truncation/retry, 취득 중 취소/완료 보존, 실제 FFmpeg 프레임, 두 번째 변환 실패·child 취소·crop 초과를 검증했다.

evaluator locked offline sync와 lock check 성공. root/API/기존 Basic Pitch lock SHA256은 각각 `200C167EC3E4E092A5693F8F2187ECA91A6D8A5EC8D159353B1D0B5A5C748CEC`, `0FDFE6C2A4C585AD8C741D4EDA71DDA52DBDA602F6DA0D7B0D1FE91DF6428EAA`, `2D7D8128B0809D4EA759B6FC0D8EA6BA413A596C5AFF864BC823B145A443597C`로 이전 값과 일치했다.

## 실제 준비 및 독립 코드 리뷰

실제 명령은 evaluator README의 prepare 명령과 같으며 output root는 `D:/develop/MusicSheet/outputs/w05-evaluation/task2-20261006`, 추적 manifest는 [maestro-w05-manifest.json](../evaluations/maestro-w05-manifest.json)이다. 설치된 FFmpeg 경로를 Get-Command로 확인해 `C:/ffmpeg-6.0-essentials_build/ffmpeg-6.0-essentials_build/bin/ffmpeg.exe`를 지정했고 version은 `6.0-essentials_build-www.gyan.dev`다. 공식 metadata/선택24개 member만 취득했다. 모델/체크포인트 실행은 없다.

| 실제 준비 증거 | 값 |
|---|---|
| 입력 / 정답 | 12개 고정30초, 후보별12개 WAV 및12개 reference |
| 원본 archive 크기 | 108445099632 bytes |
| 전송량 / decode 합계 | 583451654 /683029070 bytes (약556.4 /651.4MiB) |
| archive ETag | `"41941abdcd786c8066d532002e3b79b9"` |
| 무결성 보증 | `partial_zip_crc_sha256`, 전체 archive SHA256 미검증 |
| payload SHA256 | `d77612969580f472da66a6af20fa0607f38c615ba1c3ad66ef2d17e7cfa42593` |
| manifest file SHA256 | `b3f664dd3c6372216712d3916639df017182c291d4e0f797b35aae3e51c7dfb9` |
| metadata v3 SHA256 | `f587488423d7c0abd0858ac6f1a2a0ea0482e85519eee774a90eb3feb6bd1e04` |
| metadata v2 SHA256 | `c75d1c78282dc033de00714e5aeadde0628ce5002560b3550b38cb0913fbe55f` |
| 실제 PCM / frame | 원본44100Hz11개·48000Hz1개 stereo; 출력 monoPCM16 22050Hz661500 /16000Hz480000 모두일치 |
| MIDI 전체 event 최대 | 43978 <100000 |
| crop reference note 범위 | 74~535,12/12 비어 있지 않음 (matching cell의 예측쪽 적합성은 Task4/5에서 확인) |
| audio monotonic elapsed 합계 | 7.1911484초, 모델 추론 시간이 아님 |
| 취득 시각 간격 | 약302.465초 (v3 metadata file mtime→source receipt mtime; process monotonic 총시간 측정값과 구분) |
| 최종 재검증 시간 / .part | 1.5713초 /0개 |

검증 스크립트와 상세 receipt는 ignored `outputs/.verification-w05/verify-task2-actual.py`, `outputs/w05-evaluation/task2-20261006/task2-verification.json`에 보존했다. 실제 취득 직후 elevated 생성 WAV에 tempfile.mkdtemp의 Windows private DACL이 이동으로 남아 sandbox 재로드가 PermissionError로 실패했다. ACL을 실제 Get-Acl로 확인하고 비어 있지 않은 principal 집합을 비교하는 회귀로 재현했다. 처음 ACL probe는 PowerShell 확장 property를 잘못 사용해 빈 결과를 반환했으므로 성공 증거로 채택하지 않았다. .NET GetAccessRules로 고쳐 실제 RED를 확인한 뒤 최종파일을 정상 부모 디렉터리에서 exclusive 생성/chunk copy하도록 수정했다. 중간 복사 오류도 소유 목록으로 rollback한다. 준비된24개 WAV는 SHA256 일치를 확인하며 동일 byte 파일로 재생성했다. 이후 **일반 sandbox**에서 metadata/원본/파생/reference/hash/frame/MIDI 상한 전체 재검증에 성공했으며 manifest와 오디오 해시는 변경하지 않았다.

독립 reviewer `/root/w05_task2_review`의 초기 리뷰는 요구25/오류24/검증21/구조15/문서5=90점, blocker0/important0/minor2였다. 실제 준비 증거와 문서가 진행 중이므로 완료 게이트를 보류했다. 독립126 tests(11.22초), basetemp `t2-reviewer-20261006-a`를 실행했다. minor1 loader stop 전파는 RED→GREEN으로 해결했고, minor2 write_manifest가 serialization만 수행한다는 경계는 README에 기록했다. 공식 CLI는 pending→load 검증→publish를 수행한다.

| 코드 리뷰 | 요구 /25 | 오류 /25 | 검증 /25 | 구조 /15 | 문서 /10 | 총점 | 미해결 blocker/important/minor |
|---|---:|---:|---:|---:|---:|---:|---|
| 초기 (실제 준비·문서 진행 중) | 25 | 24 | 21 | 15 | 5 | 90 | 0/0/2 |
| 최종 및 portability 재대조 | 25 | 25 | 25 | 15 | 10 | **100** | **0/0/0** |

평가일2026-10-06, `/root/w05_task2_review`, BASE d7e91c52 대비 Task2 범위다. 독립 전체128 tests(12.95초, `t2-reviewer-20261006-b`)와 일반 제한 계정 actual loader/hash/24 WAV frame 검증 exit0를 확인했다. 이후 test의 pwsh 선택적 의존성/절대경로와 README 두 파일만 보완해 독립1 passed/10 deselected(2.41초, `t2-reviewer-20261006-c`) 및 최신20파일 hash 재대조를 받았다. 점수100과 미해결0을 다시 확인했다.

정확한 review scope는 evaluator pyproject/uv.lock/README, contracts 및 새6개 module(__main__/audio/cli/dataset/manifest/range_io), test_environment 및 새4개 tests(audio/dataset/manifest/range_io), 실제 manifest, 이번 report/main_spec/roadmap/실행 계획의20개 파일이다. 첫 최종 snapshot `outputs/.verification-w05/task2-final-review-snapshot.json` SHA256은 `36DBF239110212E8D616D57259360B6389157FB00A405EC1357E57FFEA9E5E6D`, 두 파일 보완 후 최신 `task2-final-review-snapshot-b.json` SHA256은 `2E1E995FFF0A3EDB2AC0D02A33F95CE81FE3BCA15A87FDC1F7D0613FC460EAB8`다. 각 원장은20개 파일의 개별 SHA256을 보존하며 reviewer가 직접 대조했다. 주요 최종 hash는 audio `A0C373C43C06BA1041F1A2A2E35235301134602CB025B4EAE9DABF0C46CA4756`, cli `6E268219F7FB4CB2EA6037F86B40DA4D2057CF8D974BE21321A5F1BF3C0BEC6E`, manifest loader `F9741EC8A7863DD66CD20720390FA6E0F3AF92A558EAAE1911044D84D11B6AEC`, test_audio `1EA01C82AF741A334C99DEC2FB84EE44AC8A9D3FBE19FE75702494A594AA9CAC`다. 이 리뷰 기록 추가와 계획/roadmap 상태 갱신은 계약·코드 변경이 아니다.

**Task2 코드 게이트100>=95·미해결 blocker/important0 통과.** 계획100점과 코드100점은 별도다. 로컬 문서 링크105개 누락0/diffcheck를 확인했고 원본·오디오·MIDI·reference 배열은 추적하지 않는다. 이 Task2의 실제 Windows 증거로 Linux 데이터 준비나 모델 추론의 검증을 주장하지 않는다.

Task3 ByteDance worker/checkpoint, Task4 runner/선정, Task5 실제 비교가 남아 있다. 이번 Task2는 실제 평가 입력 준비이며 모델 정확도·선정 결과를 측정하지 않는다.
