#!/usr/bin/env python3
"""
EchoMind 智能音箱通用桥接客户端（适配树莓派 / Linux / macOS / Open-XiaoAI 节点）。
能力：
  - 支持 start_position_sec 精确断点续播（mpv --start / ffplay -ss）
  - 播放期间每 5 秒向中枢上报 progress_report 精确秒数
  - 收到采集完成语音播报(type=play)且 restore_after=True 时，播报完毕自动恢复刚才的故事/音乐续播
  - 单集自然播完自动发 track_ended 触发中枢跨季无缝连播
  - 支持 --interactive 在终端直接键入语音指令测试（或结合录音脚本上行音频）

用法：
  python3 echomind_xiaoai_agent.py --server ws://192.168.1.10:8090/ws/speaker --device-id spk_xxx --token xxx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

try:
    import websockets
except ImportError:
    print("请先安装 websockets: pip install websockets", file=sys.stderr)
    sys.exit(1)


def _find_player() -> list[str] | None:
    for cmd in (
        ["mpv", "--no-video", "--really-quiet"],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
        ["mpg123", "-q"],
        ["afplay"],
    ):
        if shutil.which(cmd[0]):
            return cmd
    return None


class AudioPlayer:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.volume = 50
        self.player_cmd = _find_player()
        self.manual_stopped = False
        self.current_url: str = ""
        self.start_offset_sec: float = 0.0
        self.started_ts: float = 0.0
        self.is_announcement: bool = False
        self.pending_restore: tuple[str, float] | None = None

    def current_position_sec(self) -> float:
        if self.proc is None or self.proc.poll() is not None:
            return self.start_offset_sec
        return max(0.0, self.start_offset_sec + (time.time() - self.started_ts))

    def stop(self) -> None:
        self.manual_stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def set_volume(self, vol: int) -> None:
        self.volume = max(0, min(100, int(vol)))
        if sys.platform == "darwin" and shutil.which("osascript"):
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {self.volume}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def play_url(self, full_url: str, start_sec: float = 0.0, is_announcement: bool = False) -> None:
        self.stop()
        self.manual_stopped = False
        self.is_announcement = is_announcement
        self.current_url = full_url
        self.start_offset_sec = max(0.0, float(start_sec or 0.0))
        self.started_ts = time.time()

        if not self.player_cmd:
            print(f"[EchoMind Agent] 未检测到 mpv/ffplay/afplay，收到播放指令: {full_url} (start={self.start_offset_sec:.1f}s)")
            return

        cmd = list(self.player_cmd)
        if cmd[0] == "mpv":
            cmd.append(f"--volume={self.volume}")
            if self.start_offset_sec > 1.0:
                cmd.append(f"--start={self.start_offset_sec:.1f}")
            cmd.append(full_url)
        elif cmd[0] == "ffplay":
            if self.start_offset_sec > 1.0:
                cmd.extend(["-ss", f"{self.start_offset_sec:.1f}"])
            cmd.append(full_url)
        elif cmd[0] == "afplay":
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            with urlopen(full_url, timeout=15) as r:
                tmp.write(r.read())
            tmp.close()
            cmd.append(tmp.name)
        else:
            cmd.append(full_url)
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def play_announcement_with_restore(self, announce_url: str, restore_after: bool) -> None:
        if restore_after and self.current_url and self.proc and self.proc.poll() is None and not self.is_announcement:
            self.pending_restore = (self.current_url, self.current_position_sec())
        else:
            self.pending_restore = None
        self.play_url(announce_url, start_sec=0.0, is_announcement=True)

    def poll_natural_finish(self) -> str | None:
        """
        检测自然播放结束：
        - 返回 'restored'：通知播报结束并已自动恢复原音频续播；
        - 返回 'track_ended'：正文音频自然播完，应通知中枢推下一集；
        - 返回 None：仍在播放或人工打断。
        """
        if self.proc is None:
            return None
        rc = self.proc.poll()
        if rc is None:
            return None
        self.proc = None
        if self.manual_stopped:
            self.manual_stopped = False
            return None
        if self.is_announcement:
            self.is_announcement = False
            if self.pending_restore:
                prev_url, prev_pos = self.pending_restore
                self.pending_restore = None
                print(f"[EchoMind Agent] 播报完成，自动恢复原音频续播 ({prev_pos:.1f}s)...")
                self.play_url(prev_url, start_sec=prev_pos, is_announcement=False)
                return "restored"
            return None
        return "track_ended" if rc == 0 else None


async def run_agent(server_ws: str, device_id: str, token: str, name: str, interactive: bool = False) -> None:
    parsed = urlparse(server_ws)
    http_base = f"{'https' if parsed.scheme == 'wss' else 'http'}://{parsed.netloc}"
    query = urlencode({"device_id": device_id, "token": token, "name": name})
    sep = "&" if "?" in server_ws else "?"
    ws_url = f"{server_ws}{sep}{query}"
    player = AudioPlayer()

    async def _watch_playback(ws) -> None:
        last_report = 0.0
        while True:
            await asyncio.sleep(0.5)
            event = player.poll_natural_finish()
            if event == "track_ended":
                try:
                    await ws.send(json.dumps({"type": "track_ended"}))
                    print("[EchoMind Agent] 本集播放完成，已通知中枢推进下一集/跨季连播。")
                except Exception:
                    return
            elif player.proc and player.proc.poll() is None and not player.is_announcement:
                now = time.time()
                if now - last_report >= 5.0:
                    last_report = now
                    try:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "progress_report",
                                    "position_sec": round(player.current_position_sec(), 1),
                                }
                            )
                        )
                    except Exception:
                        return

    async def _stdin_loop(ws) -> None:
        loop = asyncio.get_running_loop()
        print("[EchoMind Agent] 交互模式已开启：输入自然语言指令回车即可对话/点播/语音采集（例如：帮我采集汪汪队第2季）")
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            txt = line.strip()
            if txt:
                await ws.send(json.dumps({"type": "chat", "text": txt}, ensure_ascii=False))

    while True:
        try:
            print(f"[EchoMind Agent] 正在连接 {ws_url} ...")
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                print("[EchoMind Agent] 已连接至 EchoMind 中枢！")
                watcher = asyncio.create_task(_watch_playback(ws))
                stdin_task = asyncio.create_task(_stdin_loop(ws)) if interactive else None
                try:
                    while True:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        mtype = msg.get("type")
                        if mtype == "pair_required":
                            print(
                                f"\n>>> 设备尚未绑定！请在 EchoMind 网页「音箱与设置」使用配对码认领: {msg.get('pair_code')} <<<\n"
                            )
                        elif mtype == "claimed":
                            print(f"[EchoMind Agent] 设备已被家庭认领！分配名称: {msg.get('name')}")
                        elif mtype == "set_volume":
                            vol = int(msg.get("volume", 50))
                            player.set_volume(vol)
                            print(f"[EchoMind Agent] 音量调整为 {vol}%")
                        elif mtype == "control":
                            cmd = msg.get("command")
                            if cmd in ("pause", "stop"):
                                pos = player.current_position_sec()
                                player.stop()
                                if cmd == "pause" and pos > 1.0:
                                    await ws.send(json.dumps({"type": "progress_report", "position_sec": round(pos, 1)}))
                                print(f"[EchoMind Agent] 收到控制指令: {cmd}")
                        elif mtype == "play_url":
                            url = msg.get("track_url")
                            if url:
                                full = url if url.startswith("http") else f"{http_base}{url}"
                                start_pos = float(msg.get("start_position_sec") or 0.0)
                                print(f"[EchoMind Agent] 开始播放: {msg.get('title') or full} (断点 {start_pos:.1f}s)")
                                player.play_url(full, start_sec=start_pos, is_announcement=False)
                        elif mtype == "play":
                            url = msg.get("track_url") or msg.get("tts_url")
                            if url:
                                full = url if url.startswith("http") else f"{http_base}{url}"
                                restore_after = bool(msg.get("restore_after", False))
                                print(f"[EchoMind Agent] 语音播报: {msg.get('text') or full}")
                                player.play_announcement_with_restore(full, restore_after=restore_after)
                        elif mtype == "reply":
                            print(f"[EchoMind 助手] {msg.get('reply_text', '')}")
                            tts_u = msg.get("tts_url")
                            if tts_u and not msg.get("track_url"):
                                full = tts_u if tts_u.startswith("http") else f"{http_base}{tts_u}"
                                player.play_url(full, start_sec=0.0, is_announcement=True)
                        elif mtype == "unpaired":
                            print("[EchoMind Agent] 设备已在控制台解绑，断开连接。")
                            player.stop()
                            return
                finally:
                    watcher.cancel()
                    if stdin_task:
                        stdin_task.cancel()
        except Exception as exc:
            print(f"[EchoMind Agent] 连接断开 ({exc})，5 秒后重连...")
            await asyncio.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description="EchoMind 智能音箱通用桥接客户端")
    parser.add_argument("--server", required=True, help="WebSocket 地址，例如 ws://192.168.1.10:8090/ws/speaker")
    parser.add_argument("--device-id", default=os.uname().nodename, help="设备唯一 ID")
    parser.add_argument("--token", default="", help="设备认证 Token（留空可触发 6 位配对码自动发现）")
    parser.add_argument("--name", default="智能音箱桥接节点", help="设备显示名")
    parser.add_argument("--interactive", action="store_true", help="开启终端交互指令模式")
    args = parser.parse_args()
    asyncio.run(run_agent(args.server, args.device_id, args.token, args.name, interactive=args.interactive))


if __name__ == "__main__":
    main()
