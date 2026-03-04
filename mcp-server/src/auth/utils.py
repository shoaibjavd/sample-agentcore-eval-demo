import logging
from contextvars import ContextVar

from src.auth.models import AccessToken
from src.exceptions import AuthError

logger = logging.getLogger(__name__)

ROLES_META_KEY = "auth_roles"
SCOPES_META_KEY = "auth_scopes"

_access_token_context: ContextVar[AccessToken | None] = ContextVar("access_token", default=None)


def auth_meta(roles: list[str] | None = None, scopes: list[str] | None = None) -> dict:
    """Helper to create auth metadata for tools/resources/prompts."""
    meta = {}
    if roles:
        meta[ROLES_META_KEY] = roles
    if scopes:
        meta[SCOPES_META_KEY] = scopes
    return meta


def get_access_token() -> AccessToken:
    """Get the current access token from context."""
    token = _access_token_context.get()
    if token is None:
        raise AuthError("No access token found in context")
    return token


def set_access_token(token: AccessToken) -> None:
    """Set the access token in context."""
    _access_token_context.set(token)


def parse_jwt_claims(claims: dict) -> AccessToken:
    """
    Parse JWT claims into AccessToken.
    Extracts roles from custom:roles claim (Cognito) and scopes from scp claim.
    """
    # Extract scopes
    scopes = []
    if "scp" in claims:
        scp = claims["scp"]
        scopes = scp if isinstance(scp, list) else scp.split() if isinstance(scp, str) else []
    elif "scope" in claims:
        scope = claims["scope"]
        scopes = scope.split() if isinstance(scope, str) else scope if isinstance(scope, list) else []

    # Extract roles from custom:roles (Cognito) or roles (Entra ID)
    roles = []
    if "custom:roles" in claims:
        roles_str = claims["custom:roles"]
        roles = [r.strip() for r in roles_str.split(",")] if roles_str else []
    elif "roles" in claims:
        r = claims["roles"]
        roles = r if isinstance(r, list) else [r] if isinstance(r, str) else []

    return AccessToken(
        token=claims.get("jti", ""),
        roles=roles,
        scopes=scopes,
        claims=claims
    )
