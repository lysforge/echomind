"""语音合成（EdgeTTS 双语慢速 + macOS say 离线优雅降级）与语音识别封装。"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import edge_tts
import httpx

from app.config import DATA_DIR, load_settings
from app.services.audio_norm import decode_to_pcm16, normalize_audio_to_lufs, pcm16_to_wav_bytes

TTS_CACHE_DIR = DATA_DIR / "tts_cache"


async def _fallback_offline_tts(text: str, out_mp3: Path, rate_str: str) -> bool:
    """当 EdgeTTS 遇到网络抖动或离线环境时，降级使用 macOS Tingting 或安全提示音。"""
    settings = load_settings()
    say_bin = shutil.which("say")
    if say_bin:
        aiff_tmp = out_mp3.with_suffix(".aiff")
        wpm = "155" if "-" in (rate_str or "") else "185"
        try:
            proc = await asyncio.create_subprocess_exec(
                say_bin,
                "-v",
                "Tingting",
                "-r",
                wpm,
                "-o",
                str(aiff_tmp),
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0 and aiff_tmp.exists():
                ff = await asyncio.create_subprocess_exec(
                    settings.ffmpeg_bin,
                    "-y",
                    "-i",
                    str(aiff_tmp),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-b:a",
                    "96k",
                    str(out_mp3),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await ff.communicate()
                aiff_tmp.unlink(missing_ok=True)
                if ff.returncode == 0 and out_mp3.exists():
                    return True
        except Exception:
            aiff_tmp.unlink(missing_ok=True)

    # 极端无 say 环境：生成温和的双音和弦 MP3，保证流程绝不崩溃
    ff = await asyncio.create_subprocess_exec(
        settings.ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=523:duration=0.4",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-b:a",
        "64k",
        str(out_mp3),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await ff.communicate()
    return out_mp3.exists()


async def synthesize_speech(
    text: str,
    voice: str | None = None,
    rate: str | None = None,
    output_path: Path | None = None,
    normalize_lufs: bool = False,
) -> Path:
    """使用 EdgeTTS 合成中文或中英双语慢速语音，网络异常时自动离线降级。"""
    settings = load_settings()
    TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target_voice = voice or settings.tts_voice_child
    target_rate = rate or settings.tts_rate_child

    if output_path is None:
        output_path = TTS_CACHE_DIR / f"tts_{uuid.uuid4().hex[:12]}.mp3"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    raw_tmp = output_path.with_suffix(".raw.mp3") if normalize_lufs else output_path
    ok = False
    for attempt in range(2):
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=target_voice,
                rate=target_rate,
            )
            await communicate.save(str(raw_tmp))
            if raw_tmp.exists() and raw_tmp.stat().st_size > 0:
                ok = True
                break
        except Exception:
            if attempt == 0:
                await asyncio.sleep(0.25)

    if not ok:
        ok = await _fallback_offline_tts(text, raw_tmp, target_rate)
        if not ok:
            raise RuntimeError("语音合成主备引擎均不可用")

    if normalize_lufs:
        await normalize_audio_to_lufs(raw_tmp, output_path)
        raw_tmp.unlink(missing_ok=True)

    return output_path


async def transcribe_audio(
    audio_bytes: bytes,
    input_ext: str = ".webm",
) -> str:
    """将音频字节转写为文字（优先使用配置的 SiliconFlow SenseVoiceSmall 中英混说接口）。"""
    settings = load_settings()
    if settings.asr_mode == "siliconflow" and settings.asr_api_key.strip():
        pcm = await decode_to_pcm16(audio_bytes, sample_rate=16000, input_ext=input_ext)
        wav_bytes = pcm16_to_wav_bytes(pcm, sample_rate=16000)
        url = settings.asr_base_url.rstrip("/") + "/audio/transcriptions"
        headers = {"Authorization": f"Bearer {settings.asr_api_key.strip()}"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    headers=headers,
                    data={"model": settings.asr_model},
                    files={"file": ("speech.wav", wav_bytes, "audio/wav")},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return str(data.get("text", "")).strip()
        except Exception:
            pass
    return ""
