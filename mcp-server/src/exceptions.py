class AuthError(Exception):
    """Raised when authentication fails."""
    pass


class TokenError(Exception):
    """Raised when token acquisition fails."""
    pass
