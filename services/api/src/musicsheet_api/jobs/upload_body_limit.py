"""Bound multipart bodies on the audio upload endpoint before form parsing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]


class UploadRequestTooLarge(Exception):
    pass


class UploadBodyLimitMiddleware:
    """Reject upload bodies over a fixed cap, including chunked requests."""

    def __init__(self, app: Any, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/api/v1/jobs/upload"
        ):
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared_length = int(value)
                except (TypeError, ValueError):
                    continue
                if declared_length > self.max_body_bytes:
                    await self._send_too_large(send)
                    return

        received_bytes = 0
        request_complete = False
        client_disconnected = False
        response_messages: list[ASGIMessage] = []

        async def limited_receive() -> ASGIMessage:
            nonlocal client_disconnected, received_bytes, request_complete
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise UploadRequestTooLarge
                request_complete = not message.get("more_body", False)
            elif message.get("type") == "http.disconnect":
                client_disconnected = True
            return message

        async def capture_response(message: ASGIMessage) -> None:
            response_messages.append(message)

        try:
            await self.app(scope, limited_receive, capture_response)
            while not request_complete and not client_disconnected:
                await limited_receive()
        except UploadRequestTooLarge:
            await self._send_too_large(send)
            return

        for message in response_messages:
            await send(message)

    @staticmethod
    async def _send_too_large(send: Send) -> None:
        body = b'{"detail":"Upload request body is too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
