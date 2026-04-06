import base64
import hashlib
import hmac

from fastapi import HTTPException, Request

from .config import (
    ATTEMPT_WINDOW_SEC,
    AUTH_GUEST_PASSWORD_HASH,
    AUTH_GUEST_USERNAME,
    AUTH_PASSWORD_HASH,
    AUTH_USERNAME,
    LOCKOUT_SEC,
    MAX_ATTEMPTS,
    _attempts,
    _lockouts,
)


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split('$', 3)
        if algo != 'pbkdf2_sha256':
            return False
        iterations = int(iters)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def client_key(request: Request, username: str) -> str:
    ip = request.headers.get('x-forwarded-for', '').split(',')[0].strip() or (request.client.host if request.client else 'unknown')
    return f'{ip}:{username.lower()}'


def prune_attempts(key: str, now: float) -> None:
    q = _attempts[key]
    while q and now - q[0] > ATTEMPT_WINDOW_SEC:
        q.popleft()


def is_locked(key: str, now: float) -> bool:
    until = _lockouts.get(key)
    if until and now < until:
        return True
    if until and now >= until:
        _lockouts.pop(key, None)
    return False


def register_failed_attempt(key: str, now: float) -> None:
    q = _attempts[key]
    q.append(now)
    prune_attempts(key, now)
    if len(q) >= MAX_ATTEMPTS:
        _lockouts[key] = now + LOCKOUT_SEC
        q.clear()


def require_session(request: Request) -> str:
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail='Unauthorized')
    return user


def check_login(username: str, password: str) -> bool:
    # Primary admin login
    if username == AUTH_USERNAME:
        pass_ok = verify_password(password, AUTH_PASSWORD_HASH) if AUTH_PASSWORD_HASH else False
        return bool(pass_ok)

    # Guest login
    if username == AUTH_GUEST_USERNAME:
        pass_ok = verify_password(password, AUTH_GUEST_PASSWORD_HASH) if AUTH_GUEST_PASSWORD_HASH else False
        return bool(pass_ok)

    return False
