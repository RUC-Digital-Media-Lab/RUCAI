from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from secrets import token_urlsafe
from threading import Lock
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings


_bearer = HTTPBearer(auto_error=False)
_session_lock = Lock()
_sessions: dict[str, tuple[datetime, str]] = {}


def create_session(username: str, password: str, settings: Settings) -> Optional[str]:
    if not _is_valid_credential(username=username, password=password, settings=settings):
        return None

    token = token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_ttl_seconds)
    with _session_lock:
        _sessions[token] = (expires, username)
    return token


def _is_valid_credential(username: str, password: str, settings: Settings) -> bool:
    users_file = settings.auth_users_file
    if users_file.exists():
        try:
            raw = json.loads(users_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    if item.get("username") == username and item.get("password") == password:
                        return True
                return False
        except Exception:
            return False

    return username == settings.auth_username and password == settings.auth_password


def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header.",
        )

    token = credentials.credentials
    now = datetime.now(timezone.utc)
    with _session_lock:
        session = _sessions.get(token)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid.",
            )
        expires, username = session
        if expires <= now:
            _sessions.pop(token, None)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid.",
            )

    return username
