import React, { useEffect, useState } from "react";
import { Check, Moon, Speaker } from "lucide-react";
import { api, DeviceInfo } from "../api";
import { Modal } from "./Modal";

export interface PushTargetSpec {
  label: string;
  subtitle?: string;
  seriesId?: number;
  albumId?: number;
  trackIds?: number[];
  startIndex?: number;
  startPositionSec?: number;
  defaultResume?: boolean;
}

export function QuickPushModal({
  target,
  devices,
  onClose,
  onSuccess,
  showToast,
}: {
  target: PushTargetSpec | null;
  devices: DeviceInfo[];
  onClose: () => void;
  onSuccess?: () => void;
  showToast: (m: string) => void;
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [resumeMode, setResumeMode] = useState(true);
  const [sleepOption, setSleepOption] = useState<"none" | "min15" | "min30" | "ep1" | "ep2">("none");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!target) return;
    const online = devices.filter((d) => d.online === 1).map((d) => d.id);
    setSelectedIds(online.length > 0 ? online : devices.slice(0, 1).map((d) => d.id));
    setResumeMode(target.defaultResume !== false);
    setSleepOption("none");
  }, [target, devices]);

  if (!target) return null;

  const toggleDev = (id: string) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const handlePush = async () => {
    if (selectedIds.length === 0) {
      showToast("请至少选择一台房间音箱");
      return;
    }
    setBusy(true);
    try {
      const payload: Parameters<typeof api.pushPlayback>[0] = {
        device_ids: selectedIds,
        loop_mode: "sequential",
        resume: resumeMode,
      };
      if (target.seriesId) payload.series_id = target.seriesId;
      if (target.albumId) payload.album_id = target.albumId;
      if (target.trackIds && target.trackIds.length > 0) payload.track_ids = target.trackIds;
      if (target.startIndex !== undefined) payload.start_index = target.startIndex;
      if (target.startPositionSec !== undefined && resumeMode) payload.start_position_sec = target.startPositionSec;
      if (sleepOption === "min15") payload.sleep_minutes = 15;
      else if (sleepOption === "min30") payload.sleep_minutes = 30;
      else if (sleepOption === "ep1") payload.sleep_episodes = 1;
      else if (sleepOption === "ep2") payload.sleep_episodes = 2;

      await api.pushPlayback(payload);
      showToast(`已推送「${target.label}」到 ${selectedIds.length} 台房间音箱顺序连播`);
      onSuccess?.();
      onClose();
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={Boolean(target)} title="推送到房间音箱播放" onClose={onClose} maxWidth="max-w-md">
      <div className="space-y-4 text-xs">
        <div className="rounded-xl bg-[var(--bg-subtle)] p-3">
          <div className="font-bold text-sm text-[var(--ink-primary)]">{target.label}</div>
          {target.subtitle && <div className="mt-0.5 text-[var(--ink-muted)]">{target.subtitle}</div>}
        </div>

        <div>
          <div className="mb-2 font-bold text-[var(--ink-secondary)]">选择目标音箱</div>
          {devices.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--border-soft)] p-4 text-center text-[var(--ink-muted)]">
              暂未绑定音箱，请先前往「音箱与设置」绑定房间音箱。
            </div>
          ) : (
            <div className="space-y-1.5">
              {devices.map((d) => {
                const checked = selectedIds.includes(d.id);
                return (
                  <button
                    key={d.id}
                    type="button"
                    onClick={() => toggleDev(d.id)}
                    className={`flex w-full items-center justify-between rounded-xl border px-3 py-2.5 text-left transition ${
                      checked
                        ? "border-[var(--brand-primary)] bg-[var(--brand-green-soft)]"
                        : "border-[var(--border-soft)] bg-white hover:bg-zinc-50"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Speaker className="h-4 w-4 text-[var(--brand-primary)]" />
                      <div>
                        <div className="font-bold text-[var(--ink-primary)]">
                          {d.room} · {d.name}
                        </div>
                        <div className="text-[11px] text-[var(--ink-muted)]">
                          {d.online ? "在线就绪" : "离线（上线可收听）"} · 音量 {d.volume}%
                        </div>
                      </div>
                    </div>
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded-full ${
                        checked ? "bg-[var(--brand-primary)] text-white" : "border border-zinc-300"
                      }`}
                    >
                      {checked && <Check className="h-3 w-3" />}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {target.startIndex === undefined && (
          <label className="flex items-center justify-between rounded-xl border border-[var(--border-soft)] px-3 py-2.5">
            <div>
              <div className="font-bold text-[var(--ink-primary)]">从上次记忆的位置继续播</div>
              <div className="text-[11px] text-[var(--ink-muted)]">自动衔接上次的季、集和秒数，播完本季自动跨季续播</div>
            </div>
            <input
              type="checkbox"
              checked={resumeMode}
              onChange={(e) => setResumeMode(e.target.checked)}
              className="h-4 w-4 accent-[var(--brand-primary)]"
            />
          </label>
        )}

        <div>
          <div className="mb-1.5 flex items-center gap-1 font-bold text-[var(--ink-secondary)]">
            <Moon className="h-3.5 w-3.5" /> 睡眠定时（可选）
          </div>
          <div className="flex flex-wrap gap-1.5">
            {[
              { id: "none", label: "连续播放" },
              { id: "ep1", label: "播完1集停" },
              { id: "ep2", label: "播完2集停" },
              { id: "min15", label: "15分钟停" },
              { id: "min30", label: "30分钟停" },
            ].map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setSleepOption(opt.id as typeof sleepOption)}
                className={`rounded-lg px-2.5 py-1.5 font-semibold transition ${
                  sleepOption === opt.id
                    ? "bg-[var(--brand-primary)] text-white"
                    : "border border-[var(--border-soft)] bg-white text-zinc-600 hover:bg-zinc-50"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[var(--border-soft)] px-4 py-2 font-semibold text-zinc-600 hover:bg-zinc-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={busy || devices.length === 0}
            onClick={() => void handlePush()}
            className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white shadow-xs disabled:opacity-50"
          >
            {busy ? "推送中..." : "立即推送到音箱"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
