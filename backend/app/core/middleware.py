"""CORS, rate limiting, and security headers."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings


def _client_identifier(request: Request) -> str:
    """Rate-limit key: the real client IP, honouring a trusted proxy.

    Behind Railway's edge, request.client is the proxy and every caller would
    share one bucket. When TRUST_PROXY_HEADERS is set we take the LAST entry of
    X-Forwarded-For — the IP the trusted edge observed and appended (assumes a
    single trusted hop; confirm the hop count against the real deployment). A
    client-forged header is rejected by falling back to the peer address when the
    setting is off, so this is safe to leave false anywhere without a proxy.
    """
    if get_settings().TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return get_remote_address(request)


# Disabled under tests so repeated requests in the suite are not throttled.
limiter = Limiter(
    key_func=_client_identifier,
    enabled=get_settings().ENVIRONMENT != "test",
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


async def _add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    return response


def configure_middleware(app: FastAPI) -> None:
    settings = get_settings()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(BaseHTTPMiddleware, dispatch=_add_security_headers)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        # Explicit, not "*": the CORS spec forbids the wildcard for credentialed
        # requests (allow_credentials=True), so a browser rejects the preflight and
        # never sends the Authorization header. These two cover what every
        # credentialed POST actually sends (Bearer token + JSON body), including
        # /query and the SSE /query/stream.
        allow_headers=["Authorization", "Content-Type"],
    )
