"""智能音箱主力桥接 WebSocket 网关（支持 Token 鉴权、自动发现配对码、双向播控与状态同步）。"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.gateways.manager import _resolve_stream_url, device_manager
from app.services.brain import process_user_turn
from app.services.tts_asr import synthesize_speech, transcribe_audio
from app.services.voiceprint import identify_speaker

router = APIRouter()


@router.websocket("/ws/speaker")
async def speaker_ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    device_id = websocket.query_params.get("device_id") or f"spk_{id(websocket)}"
    token = websocket.query_params.get("token") or ""
    default_name = websocket.query_params.get("name") or f"新发现音箱 ({device_id})"
    client_ip = websocket.client.host if websocket.client else ""

    try:
        is_paired, dev = await device_manager.register_or_discover_device(
            device_id=device_id,
            device_type="speaker_xiaoai",
            default_name=default_name,
            client_ip=client_ip,
            provided_token=token,
        )
    except PermissionError as exc:
        await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
        await websocket.close(code=4003)
        return

    device_manager.speaker_conns[device_id] = websocket
    if not is_paired:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "pair_required",
                    "device_id": device_id,
                    "pair_code": dev["pair_code"],
                    "message": "请在 EchoMind 网页管理端认领该设备",
                },
                ensure_ascii=False,
            )
        )
    else:
        await device_manager.update_device_state(device_id, online=True, playing_title="已连线，待机中")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "chat")
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            if msg_type == "track_ended":
                await device_manager.advance_device_queue(device_id, delta=1, auto_triggered=True)
                continue
            if msg_type == "progress_report":
                pos = float(msg.get("position_sec") or 0.0)
                await device_manager.report_hardware_progress(device_id, pos)
                continue

            audio_bytes = None
            if msg.get("audio_base64"):
                audio_bytes = base64.b64decode(msg["audio_base64"])

            user_text = str(msg.get("text") or "").strip()
            if not user_text and audio_bytes:
                user_text = await transcribe_audio(audio_bytes, input_ext=msg.get("ext", ".wav"))
            if not user_text:
                await websocket.send_text(json.dumps({"type": "error", "message": "未识别到有效语音内容"}, ensure_ascii=False))
                continue

            speaker = await identify_speaker(audio_bytes=audio_bytes)
            brain_resp = await process_user_turn(user_text, speaker, device_id=device_id)
            tts_path = await synthesize_speech(brain_resp.reply_text, voice=speaker.tts_voice, rate=speaker.tts_rate)

            if brain_resp.play_track and not brain_resp.skip_device_push:
                q_list = brain_resp.queue_tracks or [brain_resp.play_track]
                idx = next((i for i, t in enumerate(q_list) if t.get("id") == brain_resp.play_track.get("id") and t.get("title") == brain_resp.play_track.get("title")), 0)
                await device_manager.push_queue_to_device(
                    device_id=device_id,
                    tracks=q_list,
                    album_id=brain_resp.play_track.get("album_id"),
                    album_title=str(brain_resp.play_track.get("album_title") or ""),
                    start_index=idx,
                    series_id=brain_resp.play_track.get("series_id"),
                    start_position_sec=float(brain_resp.play_track.get("start_position_sec") or 0.0),
                )

            payload = {
                "type": "reply",
                "speaker_name": speaker.name,
                "safety_mode": speaker.safety_mode,
                "user_text": user_text,
                "reply_text": brain_resp.reply_text,
                "tts_url": f"/api/tts-cache/{tts_path.name}",
                "track_url": _resolve_stream_url(brain_resp.play_track),
                "track": brain_resp.play_track,
                "start_position_sec": float((brain_resp.play_track or {}).get("start_position_sec") or 0.0),
                "background_job": brain_resp.background_job,
            }
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    except WebSocketDisconnect:
        pass
    finally:
        device_manager.speaker_conns.pop(device_id, None)
        await device_manager.update_device_state(device_id, online=False, playing_title="离线")
