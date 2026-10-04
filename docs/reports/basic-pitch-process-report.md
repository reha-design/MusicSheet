# W04 Task1 — 프로세스 수명과 설정 계약

2026-10-04 · 계획 R4 독립100/100 · 기준 a1fd862.

설치된 모델·FFmpeg를 호출할 공통 실행기와 opt-in 설정을 구현했다. 실제 도구는 소유권이 연결된 gate의 시작 신호 이후에만 실행한다. Windows Job Object는 breakaway를 허용하지 않으며 종료·active count0·gate wait·handle close를 수행한다. Linux에서는 session/group과 leader start-time을 확인하고 SIGTERM 유예 후 필요한 경우 마지막 SIGKILL 한 번만 보낸다. leader가 먼저 사라지면 숫자 group에 다시 신호를 보내지 않고 고정 오류로 실패한다.

생성 중 취소와 반복 취소에도 생성·정리 task를 drain한다. stdout은 4KiB로 제한하며 직접 도구의 완료를 기준으로 수집하므로 자식이 pipe를 상속해도 EOF 교착이 없다. stderr는 수집하지 않고 child 환경은 승인된 운영 키만 상속한다. 미설정 provider와 기존 PipelineSettings 5개 인자 호출을 유지하며 잘못된 selector·상대 경로·누락 경로는 고정 ValueError다.

## 검증

- 기존 root baseline: 225 passed, 12 skipped, 4 deselected.
- TDD: interface scaffold 후 행동 RED 8 failed/17 passed. Windows 기본 임시 폴더의 권한 문제는 저장소 내부의 별도 basetemp로 해결했다. 한글 argv 테스트의 JSON 출력은 ASCII escape로 지정해 Windows 기본 cp949 출력에 의존하지 않는다.
- 추가 연결 실패 RED: 1 failed/26 passed/2 skipped. Job assign 실패에서 gate wait가 끝나지 않는 문제를 발견했다. assign 성공 전에는 owner로 채택하지 않고 실패한 handle을 닫아 미실행 gate를 EOF로 회수하도록 수정했다.
- Windows root: 235 passed/14 skipped/4 deselected (9.17s). 새 Linux 전용 검사2개는 Windows에서 skip이다. Windows 실제 부모·자식 회수, spawn 중 취소, assign 실패, 제한 stdout·환경 경계가 통과했다.
- Linux 선택: 10 passed/1 skipped (21.77s). Windows Job Object 검사만 skip. 실제 SIGTERM을 무시하는 descendant와 gate 보존, 예기치 않은 gate 종료·PID identity 변경의 fail-closed 검사 포함.
- Linux 전체 회귀: 239 passed/10 skipped/4 deselected (23.76s). 소유한 검증 컨테이너를 제거하고 ID 필터 목록이 비어 있음을 확인했다. 독립 구현 리뷰는 아래 최종 기록에서 확정한다.

Windows 검증은 `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w04/task1-root-green --tb=short`으로 실행했다. 각 실행은 고유한 basetemp를 사용한다.

Linux는 Windows .venv·비밀을 제외한 HEAD archive+명시적 변경 파일 snapshot, `python:3.13-slim`, Python3.13.16, uv0.10.11, root `uv sync --locked`로 재현했다. image digest `sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81`. 소유한 container ID `9dac3d251282ceefdddf6cedd5adb645bec3772409e10450a5341c8e88e7baa7`만 사용하며 종료 후 제거한다. root/API/worker dependency lock은 변경하지 않았다.

## 범위와 제한

이번 단위는 실행기와 설정만 제공한다. 실제 모델/provider·WAV·DB 연결은 Task2~4에서 검증한다. Linux child가 스스로 session/group을 탈출한 경우와 owner 강제 종료·orphan GC는 W11 범위다. Windows 모델 검증과 Linux Celery 모델 지원은 이번 실행기 증거로 주장하지 않는다.

## 독립 리뷰

수정 전 Task1 독립 리뷰 **90/100** (/root/w04_process_review, 23/25·21/25·22/25·14/15·10/10), blocker0/important2/minor1. Linux에서 R 수신 직후/Popen 직전 scheduling 지연을 주입하면 SIGTERM을 놓친 도구가 나중에 생성되고 cleanup TimeoutError와 살아 있는 프로세스가 반환되는 문제를 실제 재현했다. 부모 재현 RED1 failed/5.32s, reviewer 독립 재현5.01s와 gate/tool aliveTrue였다.

계획 R4를 작성하고 /root/w04_plan_review가 전체를 **100/100**(25/25·20/20·20/20·25/25·10/10), 지적0으로 재평가했다. gate handler 설치 후 byte-level READY를 확인하고 R 전송 전에 완료-frame reader를 소유한다. Linux는 direct-tool completion과 descendant0이 함께 확인될 때만 EOF를 보내므로 늦게 생성된 도구도5초 유예·마지막 SIGKILL 관리 안에 있다. 내부 cleanup TimeoutError는 고정 PermanentProviderError로 정규화하고, 실행 deadline만 TimeoutError로 유지했다. test monkeypatch는 context에서 복원한다.

수정 후 Linux 선택검사11 passed/1 skipped (26.63s). 실제 늦은 생성 경쟁에서 CancelledError와 gate wait 완료·부모/자식 alive0이 확인됐다. Windows READY는 text CRLF 변환에 의존하지 않도록 bytes로 전송한다. 최종 root 검증과 수정 코드 독립 점수는 아래에 확정한다.

R4 첫 수정 Windows root **236 passed/15 skipped/4 deselected** (9.88s), Linux root **241 passed/10 skipped/4 deselected** (28.79s). Linux root에는 추가 cleanup 분류 검사도 포함되며, 새 프로세스 선택 검사는12 passed/1 Windows-only skip이다. 두 번째 소유 container `1c20b427d9bd185e1e4496dc58df925c4bb47d9de90e19b0df8782b39a88fe03`는 같은 잠긴 소스 환경에서 재검증에 사용한 뒤 제거했다.

R4 첫 코드 재리뷰 **94/100**(23/25·23/25·24/25·14/15·10/10), important1/minor0. 이전 지적은 해결됐으나 direct tool 완료·descendant0일 때 SIGTERM 직후 gate가 예기치 않게 죽으면 EOF 분기의 leader 검사를 건너뛰고 성공 반환하는 경계가 발견됐다. 실제 Linux RED1 failed/.34s(DID NOT RAISE). EOF 직전 leader를 재확인하고 wait의 gate exit는 정상0 또는 계획된 마지막 SIGKILL의 -9와 일치해야 한다. 불일치는 고정 정리 오류이며 추가 group 신호를 보내지 않는다. 이 변경은 기존 R4 fail-closed 요구사항의 구현 누락을 수정한다.

마지막 수정 후 Windows root **236 passed/16 skipped/4 deselected** (9.24s), Linux 선택 **13 passed/1 skipped** (26.72s). 새 검사에서 SIGTERM 직후의 외부 gate SIGKILL은 PermanentProviderError이며 product group 신호는 최초 SIGTERM 하나다. 결정화된 timeout fixture 적용 후 Windows 선택28 passed/4 skipped(2.34s), Windows root236 passed/16 skipped/4 deselected(8.43s), Linux 선택13 passed/1 skipped(25.84s), Linux root242 passed/10 skipped/4 deselected(27.50s)를 확인했다. 마지막 소유 container ID `111446babff3e19e5b11725df4f2fbc90ece57255612aa00f44508044c6e1a52`는 검증 완료 후 삭제하고 ID 필터 목록이 비어 있음을 확인했다.

최종 독립 코드 리뷰 **100/100** (/root/w04_process_review, 2026-10-04, 25/25·25/25·25/25·15/15·10/10), blocker0/important0/minor0. 기준a1fd862 대비 Task1 실행기·gate·Windows Job·설정·fixture·테스트·계획·보고서·색인·roadmap 전체를 검토했다. 이전 지적이 모두 해결돼 Task2 진행 게이트를 통과했다. reviewer의 Windows 선택 재확인은28 passed/4 skipped이며, 부하에 따른 timeout fixture 일시 실패는 실제 준비 후 deadline reschedule로 결정화했다. Task1의 제품 코드·검증·독립 리뷰·보고서를 완료했다.
