"""声纹识别、重置与儿童安全隔离引擎（支持全龄成长阶段动态适配）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from app.config import load_settings
from app.db import compute_age_label, get_db, recommend_age_stage
from app.services.audio_norm import decode_to_pcm16, pcm16_to_wav_bytes


@dataclass
class SpeakerContext:
    member_id: int | None
    name: str
    nickname: str
    role: str  # 'child' | 'adult'
    birth_date: str
    age_label: str
    age_stage: str  # 'S1_0_3' .. 'S6_ALL'
    english_stage: str  # 'Pre_A1' | 'A1' | 'A2' | 'B1' | 'B2_PLUS' | 'adult'
    confidence: float
    safety_mode: str  # 'child_safe' | 'adult_private'
    tts_voice: str
    tts_rate: str
    matched_by: str  # 'voiceprint' | 'simulated' | 'failsafe_default'


def extract_acoustic_embedding(pcm_bytes: bytes, sample_rate: int = 16000) -> list[float]:
    """基于中心化梅尔谱包络、MFCC 与基频（F0）分布提取 64 维 L2 归一化声纹向量。"""
    if len(pcm_bytes) < 3200:
        return []

    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if np.max(np.abs(samples)) < 1e-4:
        return []

    pre_emphasis = 0.97
    emphasized = np.append(samples[0], samples[1:] - pre_emphasis * samples[:-1])

    frame_len = int(0.025 * sample_rate)
    hop_len = int(0.010 * sample_rate)
    if len(emphasized) < frame_len:
        return []

    num_frames = 1 + (len(emphasized) - frame_len) // hop_len
    frames = np.lib.stride_tricks.as_strided(
        emphasized,
        shape=(num_frames, frame_len),
        strides=(emphasized.strides[0] * hop_len, emphasized.strides[0]),
    ).copy()

    energies = np.mean(frames**2, axis=1)
    energy_thresh = max(float(np.percentile(energies, 35)), 1e-5)
    active_frames = frames[energies >= energy_thresh]
    if len(active_frames) < 5:
        active_frames = frames

    window = np.hamming(frame_len).astype(np.float32)
    windowed = active_frames * window

    n_fft = 512
    mag = np.abs(np.fft.rfft(windowed, n=n_fft)) ** 2

    def hz_to_mel(hz: float) -> float:
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def mel_to_hz(mel: float) -> float:
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    n_mels = 28
    mel_points = np.linspace(hz_to_mel(80.0), hz_to_mel(7600.0), n_mels + 2)
    hz_points = np.array([mel_to_hz(float(m)) for m in mel_points])
    bins = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    fbank = np.zeros((n_mels, mag.shape[1]), dtype=np.float32)
    for m in range(1, n_mels + 1):
        f_left, f_center, f_right = bins[m - 1], bins[m], bins[m + 1]
        if f_center > f_left:
            for k in range(f_left, f_center):
                fbank[m - 1, k] = (k - f_left) / (f_center - f_left)
        if f_right > f_center:
            for k in range(f_center, min(f_right, mag.shape[1])):
                fbank[m - 1, k] = (f_right - k) / (f_right - f_center)

    mel_spec = np.log1p(np.dot(mag, fbank.T) + 1e-6)
    mel_centered = mel_spec - np.mean(mel_spec, axis=1, keepdims=True)
    mel_env = np.mean(mel_centered, axis=0)

    k_idx = np.arange(1, 17, dtype=np.float32)[:, None]
    n_idx = np.arange(n_mels, dtype=np.float32)[None, :] + 0.5
    dct_mat = np.cos(np.pi / n_mels * k_idx * n_idx)
    mfcc = np.dot(dct_mat, np.mean(mel_spec, axis=0))

    min_lag = int(sample_rate / 480)
    max_lag = int(sample_rate / 75)
    f0_vals: list[float] = []
    for frm in active_frames[:100]:
        ac = np.correlate(frm, frm, mode="full")[len(frm) - 1 :]
        if ac[0] <= 1e-8:
            continue
        seg = ac[min_lag : min(max_lag, len(ac))]
        if len(seg) > 0:
            peak_lag = int(np.argmax(seg)) + min_lag
            if seg[peak_lag - min_lag] > 0.25 * ac[0]:
                f0_vals.append(sample_rate / peak_lag)

    f0_centers = np.linspace(80.0, 420.0, 20, dtype=np.float32)
    f0_hist = np.zeros(20, dtype=np.float32)
    if f0_vals:
        for f0 in f0_vals:
            f0_hist += np.exp(-0.5 * ((f0_centers - f0) / 22.0) ** 2)
        f0_hist = f0_hist / (np.max(f0_hist) + 1e-6) * 2.5

    vec = np.concatenate([mel_env, mfcc * 0.6, f0_hist]).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm < 1e-8:
        return []
    vec = vec / norm
    return [round(float(x), 6) for x in vec]


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    a = np.asarray(v1, dtype=np.float32)
    b = np.asarray(v2, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-8:
        return 0.0
    return float(np.dot(a, b) / denom)


async def _try_external_voiceprint_identify(wav_bytes: bytes) -> dict[str, Any] | None:
    settings = load_settings()
    if not settings.voiceprint_api_url.strip():
        return None
    url = settings.voiceprint_api_url.rstrip("/") + "/voiceprint/identify"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(url, files={"file": ("speech.wav", wav_bytes, "audio/wav")})
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        return None
    return None


async def enroll_member_voiceprint(
    member_id: int,
    audio_bytes: bytes,
    input_ext: str = ".webm",
) -> dict[str, Any]:
    pcm = await decode_to_pcm16(audio_bytes, sample_rate=16000, input_ext=input_ext)
    vec = extract_acoustic_embedding(pcm, sample_rate=16000)
    if not vec:
        raise ValueError("录音声音太小或过短，请靠近麦克风录制 3～5 秒清晰语音。")

    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM family_members WHERE id = ?", (member_id,))
        member = await cur.fetchone()
        if not member:
            raise ValueError("未找到对应的家庭成员")

        old_vec = json.loads(member["voiceprint_vector"] or "[]")
        old_samples = int(member["voiceprint_samples"] or 0)
        if old_vec and len(old_vec) == len(vec) and old_samples > 0:
            merged = (np.asarray(old_vec) * old_samples + np.asarray(vec)) / (old_samples + 1)
            norm = float(np.linalg.norm(merged))
            if norm > 1e-8:
                merged = merged / norm
            final_vec = [round(float(x), 6) for x in merged]
            new_samples = old_samples + 1
        else:
            final_vec = vec
            new_samples = 1

        await conn.execute(
            "UPDATE family_members SET voiceprint_vector = ?, voiceprint_samples = ? WHERE id = ?",
            (json.dumps(final_vec), new_samples, member_id),
        )
        await conn.commit()

        return {
            "member_id": member_id,
            "name": member["name"],
            "voiceprint_samples": new_samples,
            "vector_dim": len(final_vec),
        }


async def clear_member_voiceprint(member_id: int) -> dict[str, Any]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT id FROM family_members WHERE id = ?", (member_id,))
        if not await cur.fetchone():
            raise ValueError("家庭成员不存在")
        await conn.execute(
            "UPDATE family_members SET voiceprint_vector = '[]', voiceprint_samples = 0 WHERE id = ?",
            (member_id,),
        )
        await conn.commit()
    return {"member_id": member_id, "voiceprint_samples": 0, "has_voiceprint": False}


def _ctx_from_member(member: dict[str, Any], confidence: float, matched_by: str) -> SpeakerContext:
    is_adult = member["role"] == "adult"
    birth_date = str(member.get("birth_date") or "")
    age_stage = str(member.get("age_stage") or recommend_age_stage(birth_date))
    return SpeakerContext(
        member_id=member["id"],
        name=member["name"],
        nickname=member["nickname"],
        role=member["role"],
        birth_date=birth_date,
        age_label=compute_age_label(birth_date),
        age_stage=age_stage,
        english_stage=str(member.get("english_stage") or ("adult" if is_adult else "Pre_A1")),
        confidence=confidence,
        safety_mode="adult_private" if is_adult else "child_safe",
        tts_voice=member["tts_voice"],
        tts_rate=member["tts_rate"],
        matched_by=matched_by,
    )


async def identify_speaker(
    audio_bytes: bytes | None = None,
    input_ext: str = ".webm",
    simulated_member_id: int | None = None,
) -> SpeakerContext:
    settings = load_settings()

    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM family_members ORDER BY id ASC")
        members = [dict(r) for r in await cur.fetchall()]

    child_default = next(
        (m for m in members if m["role"] == "child"),
        {
            "id": None,
            "name": "儿童安全模式",
            "nickname": "同学",
            "role": "child",
            "birth_date": "",
            "age_stage": "S6_ALL",
            "english_stage": "Pre_A1",
            "tts_voice": settings.tts_voice_child,
            "tts_rate": settings.tts_rate_child,
        },
    )

    if simulated_member_id is not None:
        if simulated_member_id == 0:
            return SpeakerContext(
                member_id=None,
                name="未识别访客（安全降级）",
                nickname="访客",
                role="child",
                birth_date=str(child_default.get("birth_date") or ""),
                age_label=compute_age_label(child_default.get("birth_date")),
                age_stage=str(child_default.get("age_stage") or "S6_ALL"),
                english_stage=str(child_default.get("english_stage") or "Pre_A1"),
                confidence=0.0,
                safety_mode="child_safe",
                tts_voice=settings.tts_voice_child,
                tts_rate=settings.tts_rate_child,
                matched_by="failsafe_default",
            )
        target = next((m for m in members if m["id"] == simulated_member_id), None)
        if target:
            return _ctx_from_member(target, 0.99, "simulated")

    if audio_bytes and len(audio_bytes) > 1000:
        try:
            pcm = await decode_to_pcm16(audio_bytes, sample_rate=16000, input_ext=input_ext)
            ext_res = await _try_external_voiceprint_identify(pcm16_to_wav_bytes(pcm, 16000))
            if ext_res and ext_res.get("speaker_id"):
                matched = next(
                    (m for m in members if str(m["id"]) == str(ext_res["speaker_id"]) or m["name"] == ext_res["speaker_id"]),
                    None,
                )
                score = float(ext_res.get("score", 0.0))
                if matched and score >= settings.voiceprint_threshold:
                    return _ctx_from_member(matched, round(score, 3), "voiceprint")

            query_vec = extract_acoustic_embedding(pcm, sample_rate=16000)
            if query_vec:
                best_member = None
                best_score = -1.0
                for m in members:
                    if int(m.get("voiceprint_samples") or 0) <= 0:
                        continue
                    stored_vec = json.loads(m.get("voiceprint_vector") or "[]")
                    score = cosine_similarity(query_vec, stored_vec)
                    if score > best_score:
                        best_score = score
                        best_member = m

                if best_member and best_score >= settings.voiceprint_threshold:
                    return _ctx_from_member(best_member, round(best_score, 3), "voiceprint")
        except Exception:
            pass

    ctx = _ctx_from_member(child_default, 0.0, "failsafe_default")
    if child_default.get("id") is not None:
        ctx.name = f"{child_default.get('name')}（安全模式）"
    ctx.safety_mode = "child_safe"
    return ctx
