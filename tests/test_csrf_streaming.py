"""Exercise the ASGI <2.4 download path used by Uvicorn, with a process watchdog."""
import asyncio
import io
import subprocess
import sys
from pathlib import Path

import pytest


async def stream_check(spec):
    from starlette.requests import Request
    from starlette.responses import StreamingResponse
    from app.main import CSRFMiddleware

    token = "synthetic-csrf-token-12345678901234567890"
    body = f"csrf_token={token}&confirmed=si".encode()
    parts = [body[:20], body[20:]]
    received = []
    completed = asyncio.Event()
    payload = b"PK\x03\x04synthetic\x00\xff\nworkbook\x00payload"
    scope = {"type": "http", "method": "POST", "path": "/download",
             "asgi": {"version": "3.0", "spec_version": spec},
             "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
             "session": {"csrf_token": token}}

    async def receive():
        if parts:
            chunk = parts.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(parts)}
        await completed.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        received.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            completed.set()

    async def endpoint(scope, receive, send):
        assert await Request(scope, receive).body() == body
        await StreamingResponse(io.BytesIO(payload), media_type="application/octet-stream")(scope, receive, send)

    await CSRFMiddleware(endpoint)(scope, receive, send)
    assert completed.is_set()
    assert b"".join(m.get("body", b"") for m in received if m["type"] == "http.response.body") == payload


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
def test_csrf_post_download_completes_on_both_asgi_paths(spec):
    # asyncio.wait_for cannot stop a receive loop that never yields. A child
    # process makes this regression fail promptly instead of hanging all CI.
    result = subprocess.run([sys.executable, "-m", "tests.test_csrf_streaming", spec],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stream-complete" in result.stdout


def test_csrf_replays_once_and_preserves_real_disconnect():
    from app.main import CSRFMiddleware
    token = "synthetic-csrf-token-12345678901234567890"
    body = f"csrf_token={token}".encode()
    original = [{"type": "http.request", "body": body, "more_body": False}, {"type": "http.disconnect"}]

    async def receive():
        return original.pop(0)

    async def endpoint(scope, replay, send):
        assert await replay() == {"type": "http.request", "body": body, "more_body": False}
        assert await replay() == {"type": "http.disconnect"}

    asyncio.run(CSRFMiddleware(endpoint)(
        {"type": "http", "method": "POST", "path": "/download", "session": {"csrf_token": token},
         "headers": [(b"content-type", b"application/x-www-form-urlencoded")]}, receive, None,
    ))
    assert original == []



def test_csrf_rejects_oversize_body_on_regular_routes_without_content_length(monkeypatch):
    """A non-calculator POST no longer buffers an unlimited request."""
    from types import SimpleNamespace
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", SimpleNamespace(
        csrf_enabled=True, max_upload_size=1024, max_logo_size=1024,
    ))
    payload = b"x" * (1024 + 256 * 1024 + 1)
    calls = []
    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}
    async def send(message):
        calls.append(message)
    async def endpoint(scope, receive, send):
        raise AssertionError("Oversize POST must not reach the application")

    asyncio.run(main_module.CSRFMiddleware(endpoint)(
        {"type": "http", "method": "POST", "path": "/app/companies",
         "session": {"csrf_token": "synthetic-csrf-token"},
         "headers": [(b"content-type", b"application/octet-stream")]},
        receive, send,
    ))
    assert any(message.get("status") == 413 for message in calls)


@pytest.mark.parametrize("length", [b"270000", b"9" * 5000, b"\xb2"])
def test_csrf_rejects_oversize_content_length_without_reading_body(monkeypatch, length):
    from types import SimpleNamespace
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", SimpleNamespace(
        csrf_enabled=True, max_upload_size=1024, max_logo_size=1024,
    ))
    calls = []
    async def receive():
        raise AssertionError("The body should not be read when it is already too large")
    async def send(message):
        calls.append(message)
    async def endpoint(scope, receive, send):
        raise AssertionError("Oversize POST must not reach the application")

    asyncio.run(main_module.CSRFMiddleware(endpoint)(
        {"type": "http", "method": "POST", "path": "/app/companies",
         "session": {"csrf_token": "synthetic-csrf-token"},
         "headers": [(b"content-length", length)]},
        receive, send,
    ))
    assert any(message.get("status") == 413 for message in calls)

if __name__ == "__main__":
    asyncio.run(stream_check(sys.argv[1]))
    print("stream-complete")
