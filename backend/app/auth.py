"""多用户认证与基于角色（RBAC）的权限依赖模块。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request

from app.db import get_db, now_iso


def hash_password(password: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 + 随机盐生成不可逆密码摘要。"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, salt, hex_digest = stored_hash.split("$", 2)
        if scheme != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
        return hmac.compare_digest(dk.hex(), hex_digest)
    except Exception:
        return False


async def create_user_session(user_id: int, ttl_days: int = 14) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = (now + timedelta(days=ttl_days)).isoformat(timespec="seconds")
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO user_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(timespec="seconds"), expires),
        )
        await conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), user_id))
        await conn.commit()
    return token


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    cookie_tok = request.cookies.get("echomind_token")
    if cookie_tok:
        return cookie_tok.strip()
    return None


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    token = _extract_bearer_token(request)
    if not token:
        return None
    async with get_db() as conn:
        cur = await conn.execute(
            """
            SELECT u.id, u.username, u.display_name, u.role, u.is_active, u.created_at, u.last_login_at, s.expires_at
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ?
            """,
            (token,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        user = dict(row)
        if not user["is_active"] or user["expires_at"] < now_iso():
            return None
        user.pop("expires_at", None)
        return user


async def get_current_user(request: Request) -> dict[str, Any]:
    """要求有效用户登录，未认证返回 401。"""
    user = await get_optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录 EchoMind 账号")
    return user


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """要求管理员权限（role == 'admin'），普通用户返回 403。"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="该操作仅限平台管理员（admin）执行")
    return user
