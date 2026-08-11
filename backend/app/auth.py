from datetime import datetime, timedelta, timezone
import secrets
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .database import row


security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int, token_type: str = "access", team_id: int | None = None) -> str:
    """Create an HS256 JWT. Access and refresh lifetimes are intentionally separate."""
    if token_type not in {"access", "refresh"}:
        raise ValueError("Unsupported token type")
    now = datetime.now(timezone.utc)
    lifetime = (
        timedelta(minutes=settings.jwt_expire_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_expire_days)
    )
    payload = {
            "sub": str(user_id),
            "iat": now,
            "exp": now + lifetime,
            "type": token_type,
            "jti": secrets.token_urlsafe(18),
        }
    if team_id is not None:
        payload["team_id"] = int(team_id)
    return jwt.encode(
        payload,
        settings.secret_key,
        algorithm="HS256",
    )


def create_access_token(user_id: int, team_id: int | None = None) -> str:
    return create_token(user_id, "access", team_id)


def create_refresh_token(user_id: int, team_id: int | None = None) -> str:
    return create_token(user_id, "refresh", team_id)


def issue_tokens(user_id: int, team_id: int | None = None) -> dict:
    """Return the complete token pair expected by web and API clients."""
    return {
        "access_token": create_access_token(user_id, team_id),
        "refresh_token": create_refresh_token(user_id, team_id),
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
        "refresh_expires_in": settings.refresh_token_expire_days * 24 * 60 * 60,
        "team_id": team_id,
    }


def decode_refresh_token(refresh_token: str) -> dict:
    """Validate a refresh token and return its payload or raise a 401."""
    try:
        payload = jwt.decode(refresh_token, settings.secret_key, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            raise ValueError("not a refresh token")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(401, "刷新令牌无效或已过期，请重新登录") from exc
    team_id = payload.get("team_id")
    return {**payload, "user_id": user_id, "team_id": int(team_id) if team_id is not None else None}


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]) -> dict:
    if not credentials:
        raise HTTPException(401, "请先登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=["HS256"])
        # Old access tokens without a type remain valid during deployment;
        # refresh tokens can never be used as API credentials.
        if payload.get("type", "access") != "access":
            raise ValueError("refresh token cannot authenticate API calls")
        user = row("SELECT id,username,nickname,phone,avatar,created_at FROM users WHERE id=?", (int(payload["sub"]),))
    except (jwt.PyJWTError, ValueError, KeyError):
        user = None
    if not user:
        raise HTTPException(401, "登录状态已失效")
    team_id = payload.get("team_id")
    user["team_id"] = int(team_id) if team_id is not None else None
    return user


CurrentUser = Annotated[dict, Depends(current_user)]
