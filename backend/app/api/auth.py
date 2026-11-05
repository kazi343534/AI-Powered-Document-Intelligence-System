from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, LoginResponse, UserOut
from ..security import COOKIE_NAME, create_access_token, verify_password
from .deps import client_ip, get_current_user, record_audit

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

_attempts: dict[str, deque[float]] = defaultdict(deque)
_WINDOW = 300
_MAX_ATTEMPTS = 10


def _rate_limit(key: str) -> None:
    now = time.time()
    attempts = _attempts[key]
    while attempts and now - attempts[0] > _WINDOW:
        attempts.popleft()
    if len(attempts) >= _MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    attempts.append(now)


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role)


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> LoginResponse:
    ip = client_ip(request) or "unknown"
    _rate_limit(f"{ip}:{payload.email.lower()}")
    user = db.query(User).filter(User.email == payload.email.lower().strip()).one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    token = create_access_token(user.id, user.role)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.access_token_minutes * 60,
        path="/",
    )
    record_audit(db, user, "auth.login", "user", user.id, ip=ip)
    db.commit()
    _attempts.pop(f"{ip}:{payload.email.lower()}", None)
    return LoginResponse(token=token, user=user_out(user))


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)
