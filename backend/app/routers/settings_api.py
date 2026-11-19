"""系统设置、大模型在线连通性测试与硬件接入地址路由。"""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import get_current_user, require_admin
from app.config import get_lan_ip, load_settings, mask_secret, save_settings
from app.db import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    home_name: str | None = None
    assistant_name: str | None = None
    llm_provider: Literal["deepseek", "openai", "ollama"] | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    tts_voice_child: str | None = None
    tts_rate_child: str | None = None
    tts_voice_adult: str | None = None
    tts_rate_adult: str | None = None
    asr_mode: Literal["local_or_fallback", "siliconflow"] | None = None
    asr_base_url: str | None = None
    asr_api_key: str | None = None
    asr_model: str | None = None
    voiceprint_api_url: str | None = None
    voiceprint_threshold: float | None = None
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_force_active: bool | None = None
    loudnorm_target_lufs: float | None = None
    music_dl_url: str | None = None
    music_dl_sources: str | None = None


class TestLLMRequest(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


class TestMusicDlRequest(BaseModel):
    music_dl_url: str | None = None


def _public_settings_payload() -> dict[str, Any]:
    s = load_settings()
    lan_ip = get_lan_ip()
    return {
        "home_name": s.home_name,
        "assistant_name": s.assistant_name,
        "onboarding_completed": s.onboarding_completed,
        "llm_provider": s.llm_provider,
        "llm_base_url": s.llm_base_url,
        "llm_model": s.llm_model,
        "has_llm_key": bool(s.llm_api_key.strip()),
        "llm_api_key_masked": mask_secret(s.llm_api_key),
        "tts_voice_child": s.tts_voice_child,
        "tts_rate_child": s.tts_rate_child,
        "tts_voice_adult": s.tts_voice_adult,
        "tts_rate_adult": s.tts_rate_adult,
        "asr_mode": s.asr_mode,
        "asr_base_url": s.asr_base_url,
        "asr_model": s.asr_model,
        "has_asr_key": bool(s.asr_api_key.strip()),
        "asr_api_key_masked": mask_secret(s.asr_api_key),
        "voiceprint_api_url": s.voiceprint_api_url,
        "voiceprint_threshold": s.voiceprint_threshold,
        "quiet_hours_enabled": s.quiet_hours_enabled,
        "quiet_hours_start": s.quiet_hours_start,
        "quiet_hours_end": s.quiet_hours_end,
        "quiet_hours_force_active": s.quiet_hours_force_active,
        "loudnorm_target_lufs": s.loudnorm_target_lufs,
        "music_dl_url": s.music_dl_url,
        "music_dl_sources": s.music_dl_sources,
        "hardware_endpoints": {
            "lan_ip": lan_ip,
            "port": s.server_port,
            "speaker_ws_url": f"ws://{lan_ip}:{s.server_port}/ws/speaker",
            "robot_ota_url": f"http://{lan_ip}:{s.server_port}/xiaozhi/ota/",
            "robot_ws_url": f"ws://{lan_ip}:{s.server_port}/xiaozhi/v1/",
        },
    }


@router.get("")
async def get_settings(_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return _public_settings_payload()


@router.put("")
async def update_settings(
    req: SettingsUpdate,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    s = load_settings()
    data = req.model_dump(exclude_none=True)

    for key in ("llm_api_key", "asr_api_key"):
        if key in data:
            val = data[key].strip()
            if val == "__CLEAR__":
                setattr(s, key, "")
            elif val and "*" not in val:
                setattr(s, key, val)
            data.pop(key)

    for k, v in data.items():
        setattr(s, k, v)
    save_settings(s)

    async with get_db() as conn:
        await conn.execute(
            "UPDATE family_members SET tts_voice = ?, tts_rate = ? WHERE role = 'child'",
            (s.tts_voice_child, s.tts_rate_child),
        )
        await conn.execute(
            "UPDATE family_members SET tts_voice = ?, tts_rate = ? WHERE role = 'adult'",
            (s.tts_voice_adult, s.tts_rate_adult),
        )
        await conn.commit()

    return _public_settings_payload()


@router.post("/test-llm")
async def test_llm_connectivity(
    req: TestLLMRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """在线发送一次最小测试对话，验证大模型 Base URL / Key / Model 连通性与延迟。"""
    s = load_settings()
    base_url = (req.llm_base_url or s.llm_base_url).rstrip("/")
    api_key = req.llm_api_key.strip() if (req.llm_api_key and "*" not in req.llm_api_key) else s.llm_api_key.strip()
    model = req.llm_model or s.llm_model

    if not api_key and s.llm_provider != "ollama":
        return {"ok": False, "latency_ms": 0, "error": "尚未填写 API Key"}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with one word: OK"}],
                    "max_tokens": 12,
                },
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code != 200:
                return {"ok": False, "latency_ms": latency_ms, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            return {"ok": True, "latency_ms": latency_ms, "reply_preview": reply}
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": False, "latency_ms": latency_ms, "error": str(exc)}


@router.post("/test-music-dl")
async def test_music_dl_connectivity(
    req: TestMusicDlRequest,
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """探测多源云音乐引擎（go-music-dl）连通性与可用音源平台。"""
    from app.services.music_dl import check_music_dl_health

    return await check_music_dl_health(url_override=req.music_dl_url)
