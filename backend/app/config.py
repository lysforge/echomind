"""EchoMind 配置管理与路径解析。"""

from __future__ import annotations

import json
import os
import shutil
import socket
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("ECHOMIND_DATA_DIR", str(ROOT_DIR / "data")))
MEDIA_DIR = DATA_DIR / "media"
MEDIA_RAW_DIR = MEDIA_DIR / "raw"
MEDIA_TRACKS_DIR = MEDIA_DIR / "tracks"
VOICEPRINTS_DIR = DATA_DIR / "voiceprints"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "echomind.db"
WEB_DIST_DIR = ROOT_DIR / "web" / "dist"


def _find_ffmpeg() -> str:
    for candidate in ("/opt/homebrew/bin/ffmpeg", shutil.which("ffmpeg") or ""):
        if candidate and Path(candidate).exists():
            return candidate
    return "ffmpeg"


def _find_ffprobe() -> str:
    for candidate in ("/opt/homebrew/bin/ffprobe", shutil.which("ffprobe") or ""):
        if candidate and Path(candidate).exists():
            return candidate
    return "ffprobe"


def _find_yt_dlp() -> str:
    venv_yt = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "yt-dlp"
    if venv_yt.exists():
        return str(venv_yt)
    return shutil.which("yt-dlp") or "yt-dlp"


def ensure_directories() -> None:
    """确保所有运行期目录存在。"""
    for d in (DATA_DIR, MEDIA_DIR, MEDIA_RAW_DIR, MEDIA_TRACKS_DIR, VOICEPRINTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def get_lan_ip() -> str:
    """探测宿主机局域网 IP，供智能音箱与机器人连接使用。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.5)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        sock.close()
    return "127.0.0.1"


class SettingsModel(BaseModel):
    """全局可持久化设置。"""

    home_name: str = "我的家"
    assistant_name: str = "小音"
    onboarding_completed: bool = False

    llm_provider: Literal["deepseek", "openai", "ollama"] = "deepseek"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    tts_voice_child: str = "zh-CN-XiaoyiNeural"
    tts_rate_child: str = "-12%"
    tts_voice_adult: str = "zh-CN-XiaoxiaoNeural"
    tts_rate_adult: str = "+0%"

    asr_mode: Literal["local_or_fallback", "siliconflow"] = "local_or_fallback"
    asr_base_url: str = "https://api.siliconflow.cn/v1"
    asr_api_key: str = ""
    asr_model: str = "FunAudioLLM/SenseVoiceSmall"

    voiceprint_api_url: str = ""
    voiceprint_threshold: float = Field(default=0.78, ge=0.4, le=0.98)

    quiet_hours_enabled: bool = True
    quiet_hours_start: str = "21:30"
    quiet_hours_end: str = "07:00"
    quiet_hours_force_active: bool = False

    loudnorm_target_lufs: float = -16.0
    server_port: int = 8090
    public_base_url: str = ""
    music_dl_url: str = Field(default_factory=lambda: os.environ.get("ECHOMIND_MUSIC_DL_URL", "http://127.0.0.1:18080"))
    music_dl_sources: str = "netease,qq,kugou,kuwo,migu,bilibili"
    # 真·小米小爱音箱直连配置（参考 XiaoMusic / MiService）
    mi_user: str = ""
    mi_pass: str = ""
    mi_poll_enabled: bool = False
    mi_poll_interval_sec: float = Field(default=2.0, ge=1.0, le=15.0)
    mi_trigger_keywords: str = "播放,采集,下载,继续听,跳到,下一集,上一集,暂停,停止,重播,快进,倒退"
    ffmpeg_bin: str = Field(default_factory=_find_ffmpeg)
    ffprobe_bin: str = Field(default_factory=_find_ffprobe)
    yt_dlp_bin: str = Field(default_factory=_find_yt_dlp)


def mask_secret(value: str) -> str:
    """密钥脱敏，避免回显完整密钥。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def load_settings() -> SettingsModel:
    """读取设置文件，不存在则返回默认配置。"""
    ensure_directories()
    if SETTINGS_FILE.exists():
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return SettingsModel(**raw)
        except Exception:
            pass
    settings = SettingsModel()
    save_settings(settings)
    return settings


def save_settings(settings: SettingsModel) -> SettingsModel:
    """写入设置到磁盘。"""
    ensure_directories()
    SETTINGS_FILE.write_text(
        settings.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return settings
