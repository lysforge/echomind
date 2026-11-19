"""网页端实时对话抽屉与全局状态广播网关（/ws/web）。"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.gateways.manager import _resolve_stream_url, device_manager
from app.services.brain import process_user_turn
from app.services.tts_asr import synthesize_speech, transcribe_audio
from app.services.voiceprint import identify_speaker

router = APIRouter()


@router.websocket("/ws/web")
async def web_ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await device_manager.register_web(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            audio_bytes = None
            if msg.get("audio_base64"):
                audio_bytes = base64.b64decode(msg["audio_base64"])

            sim_member_id = msg.get("simulated_member_id")
            if sim_member_id is not None:
                sim_member_id = int(sim_member_id)

            target_device_id = str(msg.get("device_id") or "")
            user_text = str(msg.get("text") or "").strip()
            if not user_text and audio_bytes:
                user_text = await transcribe_audio(audio_bytes, input_ext=msg.get("ext", ".webm"))
            if not user_text:
                user_text = "你好"

            speaker = await identify_speaker(
                audio_bytes=audio_bytes,
                input_ext=msg.get("ext", ".webm"),
                simulated_member_id=sim_member_id,
            )
            brain_resp = await process_user_turn(user_text, speaker, device_id=target_device_id or "web-console")
            tts_path = await synthesize_speech(brain_resp.reply_text, voice=speaker.tts_voice, rate=speaker.tts_rate)

            if brain_resp.play_track and target_device_id:
                await device_manager.update_device_state(
                    target_device_id,
                    playing_title=f"正在播放：{brain_resp.play_track['title']}",
                )

            await websocket.send_text(
                json.dumps(
                    {
                        "type": "turn_result",
                        "user_text": user_text,
                        "reply_text": brain_resp.reply_text,
                        "motion": brain_resp.motion_command,
                        "speaker": speaker.__dict__,
                        "memory_scope_used": brain_resp.memory_scope_used,
                        "used_llm": brain_resp.used_llm,
                        "tts_url": f"/api/tts-cache/{tts_path.name}",
                        "play_track": brain_resp.play_track,
                        "track_url": _resolve_stream_url(brain_resp.play_track),
                        "learned_item": brain_resp.learned_item,
                    },
                    ensure_ascii=False,
                )
            )
    except WebSocketDisconnect:
        pass
    finally:
        device_manager.unregister_web(websocket)
