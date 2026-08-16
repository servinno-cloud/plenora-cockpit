import hashlib
import hmac
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db
from .models import Operator, OperatorSession

SESSION_COOKIE = "cockpit_session"
CSRF_COOKIE = "cockpit_csrf"
CSRF_HEADER = "X-CSRF-Token"
password_hasher = PasswordHasher()
attempts: dict[str, deque[float]] = defaultdict(deque)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def subject_digest(value: str, settings: Settings) -> str:
    return hmac.new(
        settings.secret_key.encode(), value.casefold().encode(), hashlib.sha256
    ).hexdigest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def issue_csrf(settings: Settings) -> str:
    raw = secrets.token_urlsafe(32)
    signature = hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{signature}"


def valid_csrf(token: str, settings: Settings) -> bool:
    try:
        raw, signature = token.rsplit(".", 1)
    except ValueError:
        return False
    expected = hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def require_csrf(request: Request, settings: Settings = Depends(get_settings)) -> None:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not hmac.compare_digest(cookie, header) or not valid_csrf(cookie, settings):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")


def rate_limited(key: str, settings: Settings) -> bool:
    now = time.monotonic()
    bucket = attempts[key]
    while bucket and bucket[0] < now - settings.login_rate_window_seconds:
        bucket.popleft()
    if len(bucket) >= settings.login_rate_limit:
        return True
    bucket.append(now)
    return False


def clear_rate_limit(key: str) -> None:
    attempts.pop(key, None)


def ip_prefix(request: Request) -> str | None:
    if not request.client:
        return None
    try:
        address = ipaddress.ip_address(request.client.host)
    except ValueError:
        return None
    network = ipaddress.ip_network(f"{address}/{24 if address.version == 4 else 64}", strict=False)
    return str(network)


def current_session(
    request: Request,
    db: Session = Depends(get_db),
) -> OperatorSession:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    session = db.scalar(
        select(OperatorSession).where(
            OperatorSession.token_hash == digest(raw), OperatorSession.revoked_at.is_(None)
        )
    )
    now = datetime.now(UTC)
    if not session or session.expires_at.replace(tzinfo=UTC) <= now or not session.operator.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return session


def current_operator(session: OperatorSession = Depends(current_session)) -> Operator:
    return session.operator
