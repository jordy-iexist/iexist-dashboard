from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AuthCredentialsRequest(BaseModel):
    email: str
    password: str


class AuthUserItem(BaseModel):
    id: str
    email: str
    created_at: datetime | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: AuthUserItem
