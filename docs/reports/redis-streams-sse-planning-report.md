# W02 Redis Streams 및 SSE 계획 리뷰 보고서

> 날짜: 2026-10-02 · 범위: 설계 승인 기록, 실행 계획 Revision 1–2, 독립 계획 평가와 구현 전 환경 확인

## 결과

[설계 Revision 1](../superpowers/specs/2026-10-02-redis-streams-sse-design.md)에 대한 사용자의 “다음작업진행” 응답을 설계 승인으로 기록했다. [실행 계획 Revision 2](../plans/redis-streams-sse-implementation-plan.md)를 작성하고 독립 계획 리뷰 **100/100**으로 점수 게이트를 통과했다. 미해결 blocker/important/minor는 없다.

구현 단위는 이벤트 저장소, SSE API 및 수명주기, 실 Redis 검증 및 운영 문서다. 주 세션 구현과 단위별 독립 코드 리뷰를 제안한다. 제품 코드·의존성·lockfile은 변경하지 않았으며, 사용자 계획 검토는 아직 대기 중이다. 계획 평가를 구현 리뷰로 대신하지 않는다.

## 독립 리뷰

reviewer: `/root/w02_plan_review`, 평가일: 2026-10-02. 구현 계획 작성자와 별도 subagent가 설계·사양·기존 코드를 검토했다.

| 계획 버전 | 요구사항 25 | 인터페이스 20 | 순서 20 | 검증 25 | 재현성 10 | 합계 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Revision 1 | 23 | 20 | 20 | 22 | 9 | **94** |
| Revision 2 | 25 | 20 | 20 | 25 | 10 | **100** |

Revision 1은 important 1건으로 구현 금지 상태였다. 잘못된 enum으로 변경된 Pydantic 모델의 기본 `model_dump()`가 `input_value` 원문을 경고에 넣는 동작을 reviewer가 재현했다. Revision 2는 `warnings=False`, 일반 예외와 `from None`, sentinel 기반 경고·로그·외부 예외 누출 테스트를 명시했다.

minor 2건도 해소했다. 실제 BLOCK 읽기는 서버의 고유 이름 client가 `xread`로 blocked됨을 확인한 후 발행하도록 바꿨다. 비동기 테스트는 pytest plugin 추가 없이 `asyncio.run()`을 사용하고 client를 같은 loop에서 생성·종료하도록 명시했다. ASGI 2.4의 send 오류 의존 경로에는 별도 disconnect 감시와 취소 검증을 연결했다.

## 검증 및 환경 제약

- 변경 문서의 상대 링크 존재와 `git diff --check`를 확인했다.
- `uv --cache-dir outputs/.uv-cache lock --offline --check` 및 API `--project services/api` lock check가 통과했다. lockfile 변경 없음.
- 기본 uv 실행은 사용자 영역 cache 접근 오류로 시작하지 못했다. workspace cache로 실행했을 때 pytest 기본 임시 폴더 접근 오류(root 35 setup errors, API 61 setup errors)가 발생했다. cache plugin 비활성화와 workspace basetemp로 이 오류를 해소했다.
- Root: `uv --cache-dir outputs/.uv-cache run --offline --no-sync --project . --python 3.13 pytest -q -p no:cacheprovider --basetemp outputs/.verification-w02/root-temp --tb=short` → **59 passed, 4 skipped, 4 deselected**.
- API: 같은 옵션의 `--project services/api pytest services/api/tests`와 basetemp `outputs/.verification-w02/api-temp` → **138 passed, 10 skipped, 13 failed**, 기존 Starlette httpx deprecation warning 1건.
- API 실패는 기존 `test_job_uploads.py`의 성공 등록, 생성 파일명, MIME 무시, 지원 확장자 5종, 용량 초과, DB 실패 보상, cleanup 실패, storage 실패, URI 미노출 사례였다. 모두 multipart 파싱 단계에서 `422`가 반환됐다.
- 기존 API `.venv`에 lockfile로 선언된 `python-multipart`가 미설치임을 package metadata로 확인했다. 직접 생성한 multipart Request의 `form()` 호출도 `AssertionError: The python-multipart library must be installed to use form parsing.`를 재현했다. 환경 sync 전 API suite를 통과로 표시하지 않는다.
- `MUSICSHEET_TEST_REDIS_URL` 미설정으로 실제 Redis 검증은 수행하지 않았다. 새 SSE와 이벤트 코드도 아직 없어 구현 검증으로 간주하지 않는다.

실행 계획에는 기존 lock 기반 sync를 사전 조건으로 추가했다. sync 실패나 실 Redis 미검증은 이후 구현 결과에도 명시해야 한다. 위 cache·테스트 임시 산출물은 ignored `outputs/`에 있으며 커밋 대상이 아니다.
