"""音频工程服务：护耳 -16 LUFS 响度均衡、PCM 解码与 60ms Opus 帧解析。"""

from __future__ import annotations

import asyncio
import struct
import tempfile
from pathlib import Path

from app.config import load_settings


async def _run_proc(*args: str) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout, stderr


async def probe_duration_sec(file_path: Path | str) -> float:
    """使用 ffprobe 获取音频时长（秒）。"""
    settings = load_settings()
    code, stdout, _ = await _run_proc(
        settings.ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    )
    if code == 0:
        try:
            return round(float(stdout.decode().strip()), 2)
        except ValueError:
            pass
    return 0.0


async def normalize_audio_to_lufs(
    src_path: Path | str,
    dst_path: Path | str,
    target_lufs: float | None = None,
) -> tuple[bool, float]:
    """将输入音频校准至 -16 LUFS 护耳标准响度，输出 44.1kHz MP3。"""
    settings = load_settings()
    lufs = target_lufs if target_lufs is not None else settings.loudnorm_target_lufs
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    code, _, stderr = await _run_proc(
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(src_path),
        "-vn",
        "-af",
        f"loudnorm=I={lufs}:TP=-1.5:LRA=11",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-b:a",
        "128k",
        str(dst),
    )
    if code != 0 or not dst.exists():
        # 若 loudnorm 滤镜异常（如极端短音频），回退标准转码
        code2, _, stderr2 = await _run_proc(
            settings.ffmpeg_bin,
            "-y",
            "-i",
            str(src_path),
            "-vn",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "128k",
            str(dst),
        )
        if code2 != 0 or not dst.exists():
            raise RuntimeError(
                f"FFmpeg 音频处理失败: {(stderr2 or stderr).decode(errors='ignore')[:300]}"
            )
        dur = await probe_duration_sec(dst)
        return False, dur

    dur = await probe_duration_sec(dst)
    return True, dur


async def decode_to_pcm16(
    audio_bytes: bytes,
    sample_rate: int = 16000,
    input_ext: str = ".webm",
) -> bytes:
    """将任意音频字节（WebM/WAV/MP3/OGG）解码为 16kHz 单声道 16-bit PCM。"""
    settings = load_settings()
    with tempfile.NamedTemporaryFile(suffix=input_ext, delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        code, stdout, stderr = await _run_proc(
            settings.ffmpeg_bin,
            "-y",
            "-i",
            tmp.name,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        )
        if code != 0:
            raise RuntimeError(
                f"音频解码失败: {stderr.decode(errors='ignore')[:200]}"
            )
        return stdout


def _parse_ogg_opus_packets(ogg_bytes: bytes) -> list[bytes]:
    """从 Ogg/Opus 流中提取裸 Opus 帧（跳过 OpusHead 与 OpusTags 头包）。"""
    packets: list[bytes] = []
    pos = 0
    total = len(ogg_bytes)
    pending = bytearray()

    while pos + 27 <= total:
        if ogg_bytes[pos : pos + 4] != b"OggS":
            next_idx = ogg_bytes.find(b"OggS", pos + 1)
            if next_idx == -1:
                break
            pos = next_idx
            continue
        page_segments = ogg_bytes[pos + 26]
        header_end = pos + 27 + page_segments
        if header_end > total:
            break
        seg_table = ogg_bytes[pos + 27 : header_end]
        data_offset = header_end

        for seg_len in seg_table:
            chunk = ogg_bytes[data_offset : data_offset + seg_len]
            data_offset += seg_len
            pending.extend(chunk)
            if seg_len < 255:
                pkt = bytes(pending)
                pending.clear()
                if not (pkt.startswith(b"OpusHead") or pkt.startswith(b"OpusTags")):
                    if pkt:
                        packets.append(pkt)
        pos = data_offset

    if pending:
        pkt = bytes(pending)
        if not (pkt.startswith(b"OpusHead") or pkt.startswith(b"OpusTags")):
            packets.append(pkt)
    return packets


async def encode_file_to_opus_frames(
    file_path: Path | str,
    sample_rate: int = 16000,
    frame_duration_ms: int = 60,
) -> list[bytes]:
    """将本地音频文件编码为 60ms Opus 裸帧列表，直接用于 ESP32 小智协议推流。"""
    settings = load_settings()
    code, stdout, stderr = await _run_proc(
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(file_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "libopus",
        "-b:a",
        "24k",
        "-vbr",
        "off",
        "-frame_duration",
        str(frame_duration_ms),
        "-f",
        "ogg",
        "pipe:1",
    )
    if code != 0:
        raise RuntimeError(
            f"Opus 编码失败: {stderr.decode(errors='ignore')[:200]}"
        )
    return _parse_ogg_opus_packets(stdout)


def pcm16_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """为裸 PCM16 单声道数据封装标准 WAV 头。"""
    data_size = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        data_size,
    )
    return header + pcm_bytes
