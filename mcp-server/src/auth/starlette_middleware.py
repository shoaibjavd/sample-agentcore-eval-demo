"""Starlette middleware for JWT claim extraction.

Works with mcp.server.fastmcp.FastMCP (mcp SDK) which doesn't support
the standalone fastmcp middleware system. Instead, we wrap the Starlette
app returned by FastMCP.streamable_http_app().

AgentCore already validates the JWT signature/issuer/expiry. This middleware
only decodes the payload to extract claims for role-based authorization.
"""

import base64
import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.auth.utils import parse_jwt_claims

logger = logging.getLogger(__name__)


class JWTClaimsMiddleware(BaseHTTPMiddleware):
    """Extracts JWT claims from Authorization header and stores on request.state."""

    async def dispatch(self, request: Request, call_next):
        request.state.auth = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                token = auth.removeprefix("Bearer ").strip()
                payload = token.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload))
                request.state.auth = parse_jwt_claims(claims)
                logger.info(
                    "JWT parsed: scopes=%s, roles=%s, is_m2m=%s",
                    request.state.auth.scopes,
                    request.state.auth.roles,
                    bool(request.state.auth.scopes and not request.state.auth.roles),
                )
            except Exception:
                logger.debug("Could not decode JWT payload", exc_info=True)
        return await call_next(request)
