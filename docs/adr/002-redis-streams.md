# ADR 002: Replayable SSE를 위한 Redis Streams 채택

> **상태:** 승인됨 (Accepted)  
> **일자:** 2026-09-25  

## 배경
- 곡당 30초~2분이 걸리는 긴 파이프라인 동안 브라우저가 일시적으로 새로고침되거나 네트워크가 끊길 수 있다.
- 기존 Redis Pub/Sub은 At-most-once 방식으로, 끊긴 순간의 진행률 이벤트를 유실하여 UI 상태가 멈추는 문제가 발생한다.

## 결정
- Redis Pub/Sub 대신 **Redis Streams (`XADD`)**를 채택하고, SSE 엔드포인트에서 `Last-Event-ID`를 지원하여 재접속 시 유실된 이벤트를 복원(Replay)한다.

## 결과
- 네트워크 단절 후 복귀 시에도 프로그레스 바가 즉시 최신 상태로 복구된다.
