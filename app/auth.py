from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import os
from secrets import token_urlsafe
from threading import Lock
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings


_bearer = HTTPBearer(auto_error=False)
_session_lock = Lock()
_sessions: dict[str, tuple[datetime, str]] = {}
_student_sessions: dict[str, tuple[datetime, int]] = {}


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


def hash_password(password: str) -> str:
    iterations = 200_000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iter_text, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_text)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_student_session(instance_id: int, settings: Settings) -> str:
    token = token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_ttl_seconds)
    with _session_lock:
        _student_sessions[token] = (expires, instance_id)
    return token


def require_student_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header.",
        )

    token = credentials.credentials
    now = datetime.now(timezone.utc)
    with _session_lock:
        session = _student_sessions.get(token)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Student session expired or invalid.",
            )
        expires, instance_id = session
        if expires <= now:
            _student_sessions.pop(token, None)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Student session expired or invalid.",
            )
    return instance_id
