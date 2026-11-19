"""多用户认证与管理员 RBAC 用户管理路由。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth import (
    _extract_bearer_token,
    create_user_session,
    get_current_user,
    get_optional_user,
    hash_password,
    require_admin,
    verify_password,
)
from app.db import get_db, now_iso

router = APIRouter(prefix="/api", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminUserCreate(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: Literal["admin", "user"] = "user"


class AdminUserPatch(BaseModel):
    display_name: str | None = None
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    new_password: str | None = None


@router.get("/auth/status")
async def auth_status(request: Request) -> dict[str, Any]:
    """返回平台是否已初始化超级管理员，以及当前登录用户信息。"""
    async with get_db() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM users")
        user_count = int((await cur.fetchone())[0] or 0)
    user = await get_optional_user(request)
    return {
        "initialized": user_count > 0,
        "user_count": user_count,
        "user": user,
    }


@router.post("/auth/register")
async def register_user(req: RegisterRequest, response: Response) -> dict[str, Any]:
    uname = req.username.strip()
    if len(uname) < 2 or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符，密码至少 4 位")

    async with get_db() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM users")
        count = int((await cur.fetchone())[0] or 0)
        role = "admin" if count == 0 else "user"

        cur_dup = await conn.execute("SELECT id FROM users WHERE username = ?", (uname,))
        if await cur_dup.fetchone():
            raise HTTPException(status_code=400, detail="该用户名已存在")

        display = req.display_name.strip() or uname
        pw_hash = hash_password(req.password)
        cur_ins = await conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (uname, display, pw_hash, role, now_iso()),
        )
        user_id = int(cur_ins.lastrowid)
        await conn.commit()

    token = await create_user_session(user_id)
    response.set_cookie("echomind_token", token, httponly=True, samesite="lax")
    return {
        "token": token,
        "user": {"id": user_id, "username": uname, "display_name": display, "role": role, "is_active": 1},
    }


@router.post("/auth/login")
async def login_user(req: LoginRequest, response: Response) -> dict[str, Any]:
    uname = req.username.strip()
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE username = ?", (uname,))
        row = await cur.fetchone()
    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="该账号已被管理员禁用")

    token = await create_user_session(int(row["id"]))
    response.set_cookie("echomind_token", token, httponly=True, samesite="lax")
    return {
        "token": token,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "is_active": row["is_active"],
        },
    }


@router.post("/auth/logout")
async def logout_user(request: Request, response: Response) -> dict[str, str]:
    token = _extract_bearer_token(request)
    if token:
        async with get_db() as conn:
            await conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            await conn.commit()
    response.delete_cookie("echomind_token")
    return {"status": "logged_out"}


@router.get("/auth/me")
async def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


# ================= 管理员专属：用户管理 =================

@router.get("/admin/users")
async def admin_list_users(_admin: dict[str, Any] = Depends(require_admin)) -> list[dict[str, Any]]:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, last_login_at FROM users ORDER BY id ASC"
        )
        return [dict(r) for r in await cur.fetchall()]


@router.post("/admin/users")
async def admin_create_user(
    req: AdminUserCreate,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    uname = req.username.strip()
    if len(uname) < 2 or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="用户名至少 2 位，密码至少 4 位")
    async with get_db() as conn:
        cur_dup = await conn.execute("SELECT id FROM users WHERE username = ?", (uname,))
        if await cur_dup.fetchone():
            raise HTTPException(status_code=400, detail="用户名已存在")
        display = req.display_name.strip() or uname
        cur = await conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (uname, display, hash_password(req.password), req.role, now_iso()),
        )
        await conn.commit()
        return {"id": cur.lastrowid, "username": uname, "display_name": display, "role": req.role, "is_active": 1}


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    req: AdminUserPatch,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        target = dict(row)

        # 保护系统至少留有一名活跃管理员
        if target["role"] == "admin" and (req.role == "user" or req.is_active is False):
            cur_cnt = await conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1")
            if int((await cur_cnt.fetchone())[0] or 0) <= 1:
                raise HTTPException(status_code=400, detail="不能降权或禁用平台唯一一名活跃管理员")

        display = req.display_name.strip() if req.display_name is not None else target["display_name"]
        role = req.role if req.role is not None else target["role"]
        is_active = int(req.is_active) if req.is_active is not None else target["is_active"]
        pw_hash = hash_password(req.new_password) if (req.new_password and len(req.new_password) >= 4) else target["password_hash"]

        await conn.execute(
            "UPDATE users SET display_name = ?, role = ?, is_active = ?, password_hash = ? WHERE id = ?",
            (display, role, is_active, pw_hash, user_id),
        )
        if not is_active:
            await conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        await conn.commit()

        return {
            "id": user_id,
            "username": target["username"],
            "display_name": display,
            "role": role,
            "is_active": is_active,
            "updated_by": admin["username"],
        }


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前正在登录的管理员自己")
    async with get_db() as conn:
        cur = await conn.execute("SELECT role FROM users WHERE id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        await conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await conn.commit()
    return {"status": "deleted"}
