"""HTTP guards and prompt-side hardening. Slack events stay public (signature-checked)."""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MAX_BODY = 262_144
_UNLOCKED = {"/api/health"}
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def on_cloud() -> bool:
    return bool(os.environ.get("K_SERVICE"))


def api_token() -> str:
    return (os.environ.get("IKIGAI_API_TOKEN") or "").strip()


def token_ok(got: str, expected: str) -> bool:
    if not expected:
        return False
    a = hashlib.sha256((got or "").encode("utf-8")).digest()
    b = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def _bearer(request: Request) -> str:
    raw = (request.headers.get("x-ikigai-token") or "").strip()
    if raw:
        return raw
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def api_locked(path: str) -> bool:
    if path.rstrip("/") in _UNLOCKED:
        return False
    return path.startswith("/api/") or path.startswith("/mcp/")


def with_security_headers(response: Response) -> Response:
    for key, value in _HEADERS.items():
        response.headers.setdefault(key, value)
    return response


def json_error(status: int, detail: str) -> JSONResponse:
    return with_security_headers(JSONResponse({"detail": detail}, status_code=status))


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str,
    signature: str,
    body: bytes,
    max_age: int = 300,
) -> bool:
    """Fail closed. Rejects missing, forged, or replayed Slack signatures."""
    secret = (signing_secret or "").strip()
    if not secret or secret == "not-set":
        return False
    if not timestamp or not timestamp.isdigit() or not (signature or "").startswith("v0="):
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > max_age:
        return False
    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    expected = "v0=" + digest
    return hmac.compare_digest(expected, signature)


class ApiGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        cl = request.headers.get("content-length") or ""
        if cl.isdigit() and int(cl) > MAX_BODY:
            return json_error(413, "payload too large")

        if on_cloud() and api_locked(path):
            expected = api_token()
            if not token_ok(_bearer(request), expected):
                return json_error(401, "unauthorized")

        response = await call_next(request)
        return with_security_headers(response)
