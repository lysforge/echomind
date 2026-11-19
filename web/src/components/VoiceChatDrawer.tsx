import React, { useState } from "react";
import { Mic, Music, Play, Send } from "lucide-react";
import { api, DeviceInfo, FamilyMember } from "../api";
import { SlideDrawer } from "./Modal";
import { QueueItem } from "./PlayerBar";

interface Msg {
  id: string;
  role: "user" | "assistant";
  text: string;
  meta?: string;
  queueItems?: QueueItem[];
  startIdx?: number;
  sourceLabel?: string;
}

export function VoiceChatDrawer({
  open,
  onClose,
  members,
  devices,
  onPlayUrl,
  onPlayTrackItem,
  onPlayQueueItems,
  onControlAction,
  onRefresh,
  showToast,
}: {
  open: boolean;
  onClose: () => void;
  members: FamilyMember[];
  devices: DeviceInfo[];
  onPlayUrl: (url: string, onEnded?: () => void) => void;
  onPlayTrackItem?: (item: QueueItem) => void;
  onPlayQueueItems?: (items: QueueItem[], startIndex: number) => void;
  onControlAction?: (ctrl: NonNullable<Awaited<ReturnType<typeof api.interact>>["control_action"]>) => void;
  onRefresh: () => void;
  showToast: (msg: string) => void;
}) {
  const [simMemberId, setSimMemberId] = useState<number | null>(null);
  const [targetDeviceId, setTargetDeviceId] = useState<string>("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [recording, setRecording] = useState(false);

  const handleInteractResult = (
    res: Awaited<ReturnType<typeof api.interact>>,
    metaOverride?: string
  ) => {
    let queueItems: QueueItem[] | undefined;
    let startIdx = 0;
    let sourceLabel = "";

    if (res.play_track && res.track_url) {
      const pt = res.play_track;
      const isOnline = pt.media_kind === "online_live" || (!pt.is_cached && pt.caching);
      sourceLabel = isOnline ? "在线实时播 · 自动缓存本地中" : "本地媒体库命中";

      const rawQ = res.queue_tracks && res.queue_tracks.length > 0 ? res.queue_tracks : [pt];
      queueItems = rawQ.map((qt) => ({
        id: qt.id || 0,
        kind: pt.media_kind === "book_chapter" ? "chapter" : isOnline ? "online" : "track",
        title: qt.title,
        subtitle: qt.album_title || pt.album_title || sourceLabel,
        streamUrl: qt.stream_url || (qt.id > 0 ? `/api/media/tracks/${qt.id}/stream` : res.track_url!),
        parentId: qt.album_id || 0,
        durationSec: qt.duration_sec || 0,
      }));
      const foundIdx = queueItems.findIndex((x) => x.id === pt.id && x.title === pt.title);
      startIdx = foundIdx >= 0 ? foundIdx : 0;
    }

    setMessages((p) => [
      ...p,
      {
        id: `${Date.now()}_a`,
        role: "assistant",
        text: res.reply_text,
        meta:
          metaOverride ||
          `${res.speaker.name} · ${res.speaker.safety_mode === "adult_private" ? "成人授权" : "儿童安全保护"} (${res.speaker.english_stage})`,
        queueItems,
        startIdx,
        sourceLabel,
      },
    ]);

    if (res.control_action && res.control_action.action && !targetDeviceId) {
      onControlAction?.(res.control_action);
    }

    const startTrackAfterReply = () => {
      if (queueItems && queueItems.length > 0 && !targetDeviceId) {
        if (onPlayQueueItems) onPlayQueueItems(queueItems, startIdx);
        else onPlayTrackItem?.(queueItems[startIdx]);
      }
    };

    if (res.tts_url) {
      onPlayUrl(res.tts_url, startTrackAfterReply);
    } else {
      startTrackAfterReply();
    }
    onRefresh();
  };

  const sendText = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const txt = input.trim();
    if (!txt) return;
    setMessages((p) => [...p, { id: `${Date.now()}_u`, role: "user", text: txt }]);
    setInput("");
    try {
      const res = await api.interact(txt, simMemberId, targetDeviceId);
      handleInteractResult(res);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "对话失败");
    }
  };

  const handleVoiceRecord = async () => {
    setRecording(true);
    showToast("请说话 3 秒...");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (ev) => ev.data.size > 0 && chunks.push(ev.data);
      const blob = await new Promise<Blob>((resolve) => {
        rec.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          resolve(new Blob(chunks, { type: "audio/webm" }));
        };
        rec.start();
        setTimeout(() => rec.state !== "inactive" && rec.stop(), 3000);
      });
      const ident = await api.identifyVoiceprint(blob);
      const txt = input.trim() || "放点适合我的内容";
      setMessages((p) => [...p, { id: `${Date.now()}_u`, role: "user", text: `[语音识别身份：${ident.name}] ${txt}` }]);
      const res = await api.interact(txt, null, targetDeviceId);
      handleInteractResult(res, `真实声纹：${ident.name} (相似度 ${ident.confidence})`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "无法获取麦克风权限");
    } finally {
      setRecording(false);
    }
  };

  return (
    <SlideDrawer open={open} title="语音控制与 AI 对讲台" onClose={onClose}>
      <div className="flex h-full flex-col justify-between gap-3">
        <div className="space-y-2 border-b border-[var(--border-soft)] pb-3">
          <div className="text-xs font-medium text-[var(--ink-muted)]">模拟或校验说话人身份（自动匹配适龄内容与记忆隔离）：</div>
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => setSimMemberId(null)}
              className={`rounded-full px-2.5 py-1 text-xs ${simMemberId === null ? "bg-zinc-800 text-white" : "bg-zinc-100"}`}
            >
              默认安全态
            </button>
            {members.map((m) => (
              <button
                key={m.id}
                onClick={() => setSimMemberId(m.id)}
                className={`rounded-full px-2.5 py-1 text-xs ${simMemberId === m.id ? "bg-[var(--brand-green)] text-white" : "bg-zinc-100"}`}
              >
                {m.nickname} ({m.age_stage})
              </button>
            ))}
            <button
              onClick={() => setSimMemberId(0)}
              className={`rounded-full px-2.5 py-1 text-xs ${simMemberId === 0 ? "bg-amber-600 text-white" : "bg-zinc-100"}`}
            >
              陌生访客
            </button>
          </div>
          {devices.length > 0 && (
            <select
              value={targetDeviceId}
              onChange={(e) => setTargetDeviceId(e.target.value)}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5 text-xs"
            >
              <option value="">在网页测试（语音点歌/播控直接驱动本机播放器）</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>
                  直接控制实体音箱：{d.room} · {d.name}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto rounded-2xl bg-zinc-50 p-3">
          {messages.length === 0 && (
            <div className="space-y-2 text-xs text-[var(--ink-muted)]">
              <p>快捷语音指令体验（支持点播、续播、切集、调音量、睡眠定时）：</p>
              <div className="flex flex-wrap gap-1.5">
                {["播放小星星", "放点哄睡轻音乐", "讲个三只小猪的故事", "下一首", "音量调到 45", "20分钟后停止", "暂停播放", "继续播放"].map((q) => (
                  <button
                    key={q}
                    onClick={() => setInput(q)}
                    className="rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1 text-zinc-700 hover:border-[var(--brand-green)]"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-xs leading-relaxed ${
                  m.role === "user" ? "bg-[var(--brand-green)] text-white" : "border border-[var(--border-soft)] bg-white"
                }`}
              >
                {m.text}
                {m.queueItems && m.queueItems[m.startIdx || 0] && (
                  <button
                    onClick={() => {
                      if (onPlayQueueItems) onPlayQueueItems(m.queueItems!, m.startIdx || 0);
                      else onPlayTrackItem?.(m.queueItems![m.startIdx || 0]);
                    }}
                    className="mt-2 flex w-full items-center justify-between gap-2 rounded-xl bg-[var(--brand-green-soft)] px-3 py-2 text-left text-[11px] font-semibold text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)]"
                  >
                    <span className="flex min-w-0 items-center gap-1.5">
                      <Music className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">《{m.queueItems[m.startIdx || 0].title}》· {m.sourceLabel}</span>
                    </span>
                    <Play className="h-3.5 w-3.5 shrink-0" />
                  </button>
                )}
              </div>
              {m.meta && <span className="mt-1 text-[10px] text-[var(--ink-muted)]">{m.meta}</span>}
            </div>
          ))}
        </div>

        <form onSubmit={sendText} className="flex gap-2">
          <button
            type="button"
            onClick={handleVoiceRecord}
            disabled={recording}
            className={`rounded-xl px-3 py-2 text-white ${recording ? "animate-pulse bg-rose-500" : "bg-[var(--brand-amber)]"}`}
          >
            <Mic className="h-4 w-4" />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="试试：播放小星星 / 下一首 / 20分钟后停止..."
            className="flex-1 rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
          />
          <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-4 py-2 text-white">
            <Send className="h-4 w-4" />
          </button>
        </form>
      </div>
    </SlideDrawer>
  );
}
