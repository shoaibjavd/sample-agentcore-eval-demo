from typing import Any

from pydantic import BaseModel


class AccessToken(BaseModel):
    token: str
    roles: list[str]
    scopes: list[str]
    claims: dict[str, Any]
