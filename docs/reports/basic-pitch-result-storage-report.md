# W04 Task2 — WAV 준비·결과 검증·저장

2026-10-04 · 실행 계획R4 독립100점 · 기준0381b6f.

단일 SEPARATED_AUDIO 입력을 owned I/O에서 materialize하고 RIFF/RIFX container·chunk·padding 범위를 검사한다. PCM은 전체 frame을 block 단위로 읽어 선언된 frame 수를 확인한다. 22,050Hz mono PCM은 그대로 사용하며, 유효한 다른 WAV는 argv로 분리한 로컬 FFmpeg로 변환한다. 잘린 IEEE float를 decoder가 복구해 입력 오류를 숨기지 않도록 변환 전에 container 범위를 검사한다.

JSON은 최대8MiB, MIDI는 최대16MiB의 일반 파일만 읽는다. symlink·중복 JSON key·NaN/Infinity·문자열 숫자·bool 숫자·중복 note_id·잘못된 provenance·페달 결과를 거부한다. nullable 선택 필드와 unknown field는 공용 version1 계약과 호환된다. MIDI header/track/frame 범위를 먼저 검사하고 VLQ를4byte로 제한한 뒤 mido의 전체 파일 parser와 EOT 검사를 통과시킨다. 빈 notes의 유효 결과도 허용한다.

두 결과를 모두 검증한 후 stop-aware64KiB reader로 attempt별 이름과 identity producer/version을 저장한다. 성공 Ref는 동기 thread 안에서 즉시 기록하며 취소·실패 시 thread를 drain한 다음 확인된 Ref를 삭제한다. 저장2 전에 stop을 재확인한다. 삭제 실패는 원시 exception 없이 고정 PermanentProviderError로 실패하며 부분 성공을 반환하지 않는다.

## 검증

- interface scaffold의 행동 RED: **50 failed/1 skipped** (10.69s). 처음 byte fixture의 자동 id가 Windows 경로 길이를 초과한 setup 오류는 짧은 명시 id로 수정했다.
- 두 결과를 저장 전에 검증하는 추가 RED:1 failed/.27s. 검증 전에 첫 put으로 진입하던 동작을 preflight validation으로 수정했다.
- 최초 GREEN50 passed/1 skipped(1.34s), 최종 선택 **51 passed/1 skipped**(1.11s), root **287 passed/17 skipped/4 deselected**(11.52s). symbolic link를 만들 권한이 없는 Windows 환경에서의 symlink 검사1개는 skip이며, 나머지 경계는 통과했다. 실제 FFmpeg6.0의 stereo44.1kHz PCM·IEEE float32를22,050Hz/mono/PCM16으로 변환하고 비어 있지 않은 전체 frame을 확인했다.
- API 회귀 **232 passed/25 skipped/1 warning** (1.99s). 실DB/Redis opt-in 검증은 이 단위에서 실행하지 않았다. 기존 FastAPI/Starlette testclient deprecation 경고1개다.
- resolver root33/API44 packages에 **mido1.3.3만 추가**, 기존 package version 변경0. root/API locked sync 및 offline `uv lock --check` 성공. Celery5.6.3/Kombu5.6.2/Redis6.4.0 유지.
- worker lock SHA256 `2d7d8128b0809d4ea759b6fc0d8ea6ba413a596c5aff864bc823b145a443597c` 불변. 모델 패키지를 root/API에 설치하거나 import하지 않는다.

명령은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest <선택tests 또는 전체> -q -p no:cacheprovider --basetemp outputs/.verification-w04/<고유폴더> --tb=short`. API는 `--project services/api ... pytest services/api/tests`를 사용한다. 변환 test는 FFMPEG_EXECUTABLE 또는 PATH의 설치된 실행기를 사용하며 미설치 환경에서의 skip을 실제 변환 통과로 계산하지 않는다.

## 독립 리뷰·제한

Task2 코드·설정·lock·검증·보고서 전체를 독립 평가하며95점·blocker/important0 이후 Task3로 넘어간다. 평가 날짜·항목별 점수·지적 처리는 최종 기록에 추가한다.

첫 독립 리뷰 **94/100** (/root/w04_result_storage_review, 2026-10-04, 24/25·22/25·23/25·15/15·10/10), important1. loop가 취소를 thread stop으로 전달하기 전에 저장1이 반환하면 취소 후 저장2를 시작할 수 있었다. event-only/task-only scheduling 지연의 실제 RED **2 failed/.60s**에서 두 번째 put 호출을 확인했다. rollback은 수행됐지만 새 저장 금지 계약을 충족하지 못했다.

각 put 시작 전 thread는 loop.call_soon_threadsafe로 허가를 요청한다. loop의 callback이 cancellation event와 원래 task의 새 cancel 요청을 확인하고 future로 허가·거부한다. 따라서 loop가 지연된 동안 새 put을 시작하지 않고, asyncio 객체를 다른 thread에서 직접 조작/조회하지 않는다. 허가가 put 시작의 소유권 예약 시점이며 이후 취소는 진행 중 put을 drain·rollback한다. 양쪽 취소 검사에서 put1개·Ref 삭제·CancelledError가 확인돼 선택 **53 passed/1 skipped**(1.42s)다. 코드 재리뷰 및 수정 후 전체 회귀는 아래에 기록한다.

수정 후 root **289 passed/17 skipped/4 deselected**(11.62s), API **232 passed/25 skipped/1 warning**(2.01s). dependency/lock 추가 변경0, `git diff --check` 오류0. 독립 재리뷰 진행 중이다.

최종 독립 코드 리뷰 **100/100** (/root/w04_result_storage_review, 2026-10-04, 25/25·25/25·25/25·15/15·10/10), blocker0/important0/minor0. 기준0381b6f 대비 Task2 제품3파일·테스트4파일·dependency/lock·계획 기록·보고서·색인 전체를 평가했다. 이전 취소 fence 지적은 해결됐고 Task3 진행 게이트를 통과했다. reviewer 독립 재실행은 선택53 passed/1 skipped(1.26s), root289 passed/17 skipped/4 deselected(10.53s), API232 passed/25 skipped/1 warning(2.03s), root/API lock 및 worker hash 검사 통과다.

동기 materialize/put 자체가 OS I/O에서 막힌 경우 thread가 돌아올 때까지 drain한다. 이는 실행 timeout의 hard wall-clock 보장이 아니다. put이 Ref를 반환하기 전에 저장 후 오류를 내는 경우 확인되지 않은 파일, owner 강제 종료 및 runner 반환 후 DB fence에서 거부된 파일의 GC는 W11 범위다. 제품 provider·실제 모델/DB 연결은 Task3~4에서 검증한다.
