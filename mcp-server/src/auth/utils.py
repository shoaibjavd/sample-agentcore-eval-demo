"""Token extraction from HTTP headers. AgentCore validates the JWT;
we only decode the payload to read claims for role-based access."""

import jwt
from fastmcp.server.dependencies import get_http_headers
from jwt import PyJWTError

from src.auth.models import AccessToken
from src.exceptions import AuthError

ROLES_META_KEY = "Roles"
SCOPES_META_KEY = "Scopes"


def auth_meta(roles: list[str] | str | None = None, scopes: list[str] | str | None = None) -> dict:
    """Build metadata dict for role/scope-gated tools."""
    meta = {}
    if roles:
        meta[ROLES_META_KEY] = [roles] if isinstance(roles, str) else roles
    if scopes:
        meta[SCOPES_META_KEY] = [scopes] if isinstance(scopes, str) else scopes
    return meta


def get_access_token() -> AccessToken:
    """Get the access token from the current HTTP request headers.

    AgentCore has already validated the token. We decode without signature
    verification to extract claims for role-based authorization.
    """
    headers = get_http_headers(include={"authorization"})
    if not headers:
        raise AuthError("No HTTP headers found")

    auth_header = headers.get("Authorization") or headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthError("No Authorization header found")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        claims: dict = jwt.decode(token, options={"verify_signature": False})
    except PyJWTError as e:
        raise AuthError(f"Unable to decode access token: {e}") from e

    # Cognito uses custom:roles (comma-separated string), Entra ID uses roles (list)
    roles = claims.get("roles", [])
    if not roles:
        roles_str = claims.get("custom:roles", "")
        roles = [r.strip() for r in roles_str.split(",") if r.strip()] if roles_str else []

    scopes = []
    for key in ("scp", "scope"):
        val = claims.get(key, "")
        if val:
            scopes = val.split(" ") if isinstance(val, str) else val
            break

    return AccessToken(token=token, roles=roles, scopes=scopes, claims=claims)
