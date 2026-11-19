#!/usr/bin/env python3
"""
EchoMind 智能音箱通用桥接客户端（适配 Open-XiaoAI / 树莓派 / Linux / macOS）。
用法：
  python3 echomind_xiaoai_agent.py --server ws://192.168.1.10:8090/ws/speaker --device-id spk_xxx --token xxx
或者不带 token 直接连入触发“6位配对码自动发现”。
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
        # macOS 或 ALSA 环境下尝试同步系统音量，否则在 mpv 参数里控制
        if sys.platform == "darwin" and shutil.which("osascript"):
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {self.volume}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def play_url(self, full_url: str) -> None:
        self.stop()
        self.manual_stopped = False
        if not self.player_cmd:
            print(f"[EchoMind Agent] 未检测到 mpv/ffplay/afplay，收到播放指令: {full_url}")
            return
        cmd = list(self.player_cmd)
        if cmd[0] == "mpv":
            cmd.append(f"--volume={self.volume}")
        if cmd[0] == "afplay":
            # afplay 不支持直接拉 HTTP URL，先下载到临时文件
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            with urlopen(full_url, timeout=15) as r:
                tmp.write(r.read())
            tmp.close()
            cmd.append(tmp.name)
        else:
            cmd.append(full_url)
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def poll_natural_finish(self) -> bool:
        """检测单集是否自然播放结束（非人工 stop/pause 打断）。"""
        if self.proc is None:
            return False
        rc = self.proc.poll()
        if rc is None:
            return False
        self.proc = None
        if self.manual_stopped:
            self.manual_stopped = False
            return False
        return rc == 0


async def run_agent(server_ws: str, device_id: str, token: str, name: str) -> None:
    parsed = urlparse(server_ws)
    http_base = f"{'https' if parsed.scheme == 'wss' else 'http'}://{parsed.netloc}"
    query = urlencode({"device_id": device_id, "token": token, "name": name})
    sep = "&" if "?" in server_ws else "?"
    ws_url = f"{server_ws}{sep}{query}"
    player = AudioPlayer()

    async def _watch_playback(ws) -> None:
        while True:
            await asyncio.sleep(0.5)
            if player.poll_natural_finish():
                try:
                    await ws.send(json.dumps({"type": "track_ended"}))
                    print("[EchoMind Agent] 本集播放完成，已通知中枢推下一集。")
                except Exception:
                    return

    while True:
        try:
            print(f"[EchoMind Agent] 正在连接 {ws_url} ...")
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                print("[EchoMind Agent] 已连接至 EchoMind 中枢！")
                watcher = asyncio.create_task(_watch_playback(ws))
                try:
                    while True:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        mtype = msg.get("type")
                        if mtype == "pair_required":
                            print(
                                f"\n>>> 设备尚未绑定！请在 EchoMind 网页「音箱与终端」页使用配对码认领: {msg.get('pair_code')} <<<\n"
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
                                player.stop()
                                print(f"[EchoMind Agent] 收到控制指令: {cmd}")
                        elif mtype in ("play_url", "play", "reply"):
                            url = msg.get("track_url") or msg.get("tts_url")
                            if url:
                                full = url if url.startswith("http") else f"{http_base}{url}"
                                print(f"[EchoMind Agent] 开始播放: {msg.get('title') or msg.get('text') or full}")
                                player.play_url(full)
                        elif mtype == "unpaired":
                            print("[EchoMind Agent] 设备已在控制台解绑，断开连接。")
                            player.stop()
                            return
                finally:
                    watcher.cancel()
        except Exception as exc:
            print(f"[EchoMind Agent] 连接断开 ({exc})，5 秒后重连...")
            await asyncio.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description="EchoMind 智能音箱桥接客户端")
    parser.add_argument("--server", required=True, help="例如 ws://192.168.1.10:8090/ws/speaker")
    parser.add_argument("--device-id", default=os.uname().nodename, help="设备唯一 ID")
    parser.add_argument("--token", default="", help="控制面板生成的设备 Token（留空可触发配对码发现）")
    parser.add_argument("--name", default="智能音箱终端", help="自动发现时上报的初始名称")
    args = parser.parse_args()
    asyncio.run(run_agent(args.server, args.device_id, args.token, args.name))


if __name__ == "__main__":
    main()
