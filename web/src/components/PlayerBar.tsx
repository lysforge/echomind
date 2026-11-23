import React, { useState } from "react";
import { ListMusic, Pause, Play, Repeat, Shuffle, SkipBack, SkipForward, Speaker, Volume2 } from "lucide-react";
import { api, DeviceInfo } from "../api";

export interface QueueItem {
  id: number;
  kind: "track" | "chapter" | "lesson" | "online";
  title: string;
  subtitle: string;
  streamUrl: string;
  parentId: number;
  durationSec: number;
  startPositionSec?: number;
  episodeNum?: number;
  seasonLabel?: string;
  seriesTitle?: string;
}

function fmtTime(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

export function PlayerBar({
  queue,
  currentIndex,
  isPlaying,
  progressSec,
  durationSec,
  loopMode,
  outputTarget,
  devices,
  onTogglePlay,
  onStep,
  onSeek,
  onCycleLoop,
  onSelectOutput,
  onSelectIndex,
  onBrowserVolume,
}: {
  queue: QueueItem[];
  currentIndex: number;
  isPlaying: boolean;
  progressSec: number;
  durationSec: number;
  loopMode: "sequential" | "repeat_one" | "shuffle";
  outputTarget: string; // "browser" or device_id
  devices: DeviceInfo[];
  onTogglePlay: () => void;
  onStep: (delta: number) => void;
  onSeek: (sec: number) => void;
  onCycleLoop: () => void;
  onSelectOutput: (target: string) => void;
  onSelectIndex: (idx: number) => void;
  onBrowserVolume: (vol: number) => void;
}) {
  const [showDevices, setShowDevices] = useState(false);
  const [showQueue, setShowQueue] = useState(false);
  const [vol, setVol] = useState(75);
  const current = queue[currentIndex] || null;
  const activeDevice = devices.find((d) => d.id === outputTarget);

  return (
    <footer className="fixed bottom-0 left-0 right-0 z-30 border-t border-[var(--border-soft)] bg-[var(--bg-card)]/95 backdrop-blur-md lg:left-64">
      {showQueue && (
        <div className="border-b border-[var(--border-soft)] bg-[var(--bg-subtle)] px-5 py-3">
          <div className="mb-2 flex items-center justify-between text-xs font-bold">
            <span>播放队列（{queue.length}）</span>
            <button onClick={() => setShowQueue(false)} className="text-[var(--ink-muted)] hover:text-zinc-900">
              收起
            </button>
          </div>
          <div className="max-h-44 space-y-1 overflow-y-auto">
            {queue.length === 0 ? (
              <div className="text-xs text-[var(--ink-muted)]">队列为空，可在书架或曲库点击播放</div>
            ) : (
              queue.map((q, i) => (
                <button
                  key={`${q.kind}_${q.id}_${i}`}
                  onClick={() => onSelectIndex(i)}
                  className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs ${
                    i === currentIndex ? "bg-[var(--brand-green-soft)] font-semibold text-[var(--brand-green)]" : "hover:bg-white"
                  }`}
                >
                  <span className="truncate">
                    {i + 1}. {q.title}
                  </span>
                  <span className="ml-2 shrink-0 text-[11px] text-[var(--ink-muted)]">{q.subtitle}</span>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-bold">{current ? current.title : "EchoMind 云端播放器"}</div>
          <div className="truncate text-xs text-[var(--ink-muted)]">
            {current ? `${current.subtitle} · -16 LUFS 均衡` : "畅听私有云曲库、全网热歌与播客电台"}
          </div>
        </div>

        {/* 中间主控区 */}
        <div className="flex flex-col items-center gap-1">
          <div className="flex items-center gap-2">
            <button
              onClick={onCycleLoop}
              title={loopMode === "shuffle" ? "随机" : loopMode === "repeat_one" ? "单曲循环" : "顺序循环"}
              className="rounded-lg p-1.5 text-xs text-[var(--ink-muted)] hover:bg-zinc-100"
            >
              {loopMode === "shuffle" ? <Shuffle className="h-3.5 w-3.5" /> : <Repeat className="h-3.5 w-3.5" />}
            </button>
            <button
              onClick={() => onStep(-1)}
              disabled={!current}
              className="rounded-full p-1.5 text-zinc-600 hover:bg-zinc-100 disabled:opacity-40"
            >
              <SkipBack className="h-4 w-4" />
            </button>
            <button
              onClick={onTogglePlay}
              disabled={!current}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--brand-green)] text-white shadow-sm disabled:opacity-40"
            >
              {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </button>
            <button
              onClick={() => onStep(1)}
              disabled={!current}
              className="rounded-full p-1.5 text-zinc-600 hover:bg-zinc-100 disabled:opacity-40"
            >
              <SkipForward className="h-4 w-4" />
            </button>
          </div>
          <div className="hidden items-center gap-2 text-[11px] text-[var(--ink-muted)] sm:flex">
            <span>{fmtTime(progressSec)}</span>
            <input
              type="range"
              min={0}
              max={Math.max(1, Math.floor(durationSec))}
              value={Math.floor(progressSec)}
              onChange={(e) => onSeek(Number(e.target.value))}
              className="h-1 w-44 accent-[var(--brand-green)]"
            />
            <span>{fmtTime(durationSec)}</span>
          </div>
        </div>

        {/* 右侧：输出设备切换 + 音量 + 队列 */}
        <div className="relative flex items-center gap-2">
          <button
            onClick={() => setShowDevices((v) => !v)}
            className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-medium ${
              outputTarget === "browser"
                ? "border-[var(--border-soft)] bg-white text-zinc-700"
                : "border-[var(--brand-green)] bg-[var(--brand-green-soft)] text-[var(--brand-green)]"
            }`}
          >
            <Speaker className="h-3.5 w-3.5" />
            <span className="max-w-[96px] truncate">{activeDevice ? activeDevice.name : "本机浏览器"}</span>
          </button>

          {showDevices && (
            <div className="absolute bottom-12 right-0 w-60 rounded-2xl border border-[var(--border-soft)] bg-white p-2 shadow-xl">
              <div className="px-2 py-1 text-[11px] font-bold text-[var(--ink-muted)]">选择播放输出终端</div>
              <button
                onClick={() => {
                  onSelectOutput("browser");
                  setShowDevices(false);
                }}
                className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-xs ${
                  outputTarget === "browser" ? "bg-[var(--brand-green-soft)] font-semibold text-[var(--brand-green)]" : "hover:bg-zinc-50"
                }`}
              >
                <span>本机浏览器试听</span>
                {outputTarget === "browser" && <span>●</span>}
              </button>
              {devices.map((d) => (
                <button
                  key={d.id}
                  onClick={() => {
                    onSelectOutput(d.id);
                    setShowDevices(false);
                  }}
                  className={`mt-1 flex w-full items-center justify-between rounded-xl px-3 py-2 text-xs ${
                    outputTarget === d.id ? "bg-[var(--brand-green-soft)] font-semibold text-[var(--brand-green)]" : "hover:bg-zinc-50"
                  }`}
                >
                  <span className="truncate">{d.name}</span>
                  <span className="text-[10px] text-[var(--ink-muted)]">{d.online ? "在线" : "离线"}</span>
                </button>
              ))}
            </div>
          )}

          <div className="hidden items-center gap-1.5 md:flex">
            <Volume2 className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
            <input
              type="range"
              min={0}
              max={100}
              value={activeDevice ? activeDevice.volume : vol}
              onChange={(e) => {
                const v = Number(e.target.value);
                setVol(v);
                if (activeDevice) {
                  api.updateDevice(activeDevice.id, { volume: v }).catch(() => {});
                } else {
                  onBrowserVolume(v);
                }
              }}
              className="h-1 w-20 accent-[var(--brand-green)]"
            />
          </div>

          <button
            onClick={() => setShowQueue((v) => !v)}
            className="rounded-xl border border-[var(--border-soft)] p-2 text-zinc-600 hover:bg-zinc-50"
            title="播放队列"
          >
            <ListMusic className="h-4 w-4" />
          </button>
        </div>
      </div>
    </footer>
  );
}
