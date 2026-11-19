import React, { useEffect, useState } from "react";
import {
  BellRing,
  ChevronDown,
  ChevronUp,
  ListMusic,
  Moon,
  Pause,
  Play,
  Radio,
  Repeat,
  Send,
  Shield,
  Shuffle,
  SkipBack,
  SkipForward,
  Speaker,
  Square,
  Volume2,
  Wifi,
  WifiOff,
  Wrench,
} from "lucide-react";
import { api, DashboardData, DeviceInfo, RoomPlaybackState } from "../api";
import { EmptyState, Modal } from "../components/Modal";
import { SchedulesPage } from "./SchedulesPage";

function fmtRemaining(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function RoomsControlPage({
  dashboard,
  isAdmin,
  onRefreshDashboard,
  onPlayUrl,
  onOpenStudioSystem,
  showToast,
}: {
  dashboard: DashboardData;
  isAdmin: boolean;
  onRefreshDashboard: () => void;
  onPlayUrl: (url: string) => void;
  onOpenStudioSystem?: () => void;
  showToast: (m: string) => void;
}) {
  const [rooms, setRooms] = useState<RoomPlaybackState[]>([]);
  const [expandedQueueDevId, setExpandedQueueDevId] = useState<string | null>(null);

  // 待认领快速认领
  const [claimTarget, setClaimTarget] = useState<DeviceInfo | null>(null);
  const [claimName, setClaimName] = useState("");
  const [claimRoom, setClaimRoom] = useState("客厅");
  const [claimMaxVol, setClaimMaxVol] = useState(75);

  // 广播状态
  const [announceDevId, setAnnounceDevId] = useState("");
  const [announceText, setAnnounceText] = useState("");

  const loadRooms = async () => {
    try {
      setRooms(await api.listPlaybackRooms());
    } catch {
      // ignore polling error
    }
  };

  useEffect(() => {
    void loadRooms();
    const timer = window.setInterval(() => void loadRooms(), 3500);
    return () => window.clearInterval(timer);
  }, [dashboard.devices.length]);

  const handleRoomControl = async (
    devId: string,
    payload: Parameters<typeof api.controlRoomPlayback>[1],
    toastMsg?: string
  ) => {
    try {
      const updated = await api.controlRoomPlayback(devId, payload);
      setRooms((prev) => prev.map((r) => (r.id === devId ? updated : r)));
      if (toastMsg) showToast(toastMsg);
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  return (
    <div className="space-y-6">
      {/* 头部标题 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight">房间音箱与作息播控中心</h2>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
            像 Sonos 一样集中掌控全屋各房间音箱的当前连播队列、护耳音量、睡眠定时，以及每天自动早晚作息任务。
          </p>
        </div>
        {isAdmin && onOpenStudioSystem && (
          <button
            onClick={onOpenStudioSystem}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-white px-4 py-2 text-xs font-semibold hover:bg-zinc-50"
          >
            <Wrench className="h-3.5 w-3.5" /> 硬件配网与绑定管理
          </button>
        )}
      </div>

      {/* 待认领自动发现设备横幅 */}
      {dashboard.pending_devices.length > 0 && (
        <section className="rounded-2xl border border-amber-300 bg-amber-50/90 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-bold text-amber-900">
            <BellRing className="h-4 w-4 text-amber-600" /> 发现 {dashboard.pending_devices.length} 台新硬件设备等待认领
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {dashboard.pending_devices.map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded-xl bg-white p-3 shadow-xs">
                <div className="text-xs">
                  <div className="font-bold">{p.name}</div>
                  <div className="text-[var(--ink-muted)]">
                    配对码：<span className="font-mono font-bold text-amber-700">{p.pair_code}</span> · {p.client_ip || "局域网"}
                  </div>
                </div>
                <button
                  onClick={() => {
                    setClaimTarget(p);
                    setClaimName(p.name);
                  }}
                  className="rounded-lg bg-[var(--brand-green)] px-3.5 py-1.5 text-xs font-semibold text-white"
                >
                  认领入家
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 1. 全屋音箱实时播控卡片矩阵 */}
      {rooms.length === 0 ? (
        <EmptyState
          icon={Speaker}
          title="尚未绑定任何房间的智能音箱"
          description="请前往「管理工作台 → 硬件 · 账号 · 系统设置」添加您的第一台小爱音箱或 ESP32 语音终端，或者直接用音箱客户端连入服务器自动发现。"
          action={
            isAdmin && onOpenStudioSystem ? (
              <button
                onClick={onOpenStudioSystem}
                className="rounded-xl bg-[var(--brand-green)] px-5 py-2.5 text-xs font-semibold text-white"
              >
                前往添加音箱设备
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {rooms.map((room) => {
            const sess = room.session;
            const queueOpen = expandedQueueDevId === room.id;
            const isActivePlaying = sess?.status === "playing";

            return (
              <section key={room.id} className="card-pro flex flex-col justify-between p-5">
                <div className="space-y-4">
                  {/* 设备头部状态 */}
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2.5 py-0.5 text-[11px] font-semibold text-zinc-700">
                          {room.device_type === "speaker_xiaoai" ? <Speaker className="h-3 w-3" /> : <Radio className="h-3 w-3" />}
                          {room.room}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                            room.online ? "bg-emerald-100 text-emerald-700" : "bg-zinc-100 text-zinc-500"
                          }`}
                        >
                          {room.online ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
                          {room.online ? "在线" : "离线"}
                        </span>
                      </div>
                      <h3 className="mt-1.5 text-base font-extrabold">{room.name}</h3>
                    </div>

                    <button
                      onClick={async () => {
                        const r = await api.controlDevice(room.id, "test_sound");
                        if (r.tts_url) onPlayUrl(r.tts_url);
                        showToast(`已向【${room.name}】发送测试提示音`);
                      }}
                      className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5 text-xs font-semibold text-[var(--brand-green)] hover:bg-[var(--brand-green-soft)]/50"
                    >
                      响铃测试
                    </button>
                  </div>

                  {/* 房间播放会话控区 */}
                  <div className="rounded-2xl bg-zinc-50 p-4 text-xs">
                    {sess && sess.queue.length > 0 ? (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-[11px] font-semibold text-[var(--brand-green)]">
                              {sess.album_title || "当前连播队列"} · 第 {sess.current_index + 1}/{sess.queue.length} 集
                            </div>
                            <div className="truncate text-sm font-bold">{sess.current_track?.title || room.playing_title}</div>
                          </div>

                          {/* 播控按键 */}
                          <div className="flex shrink-0 items-center gap-1">
                            <button
                              onClick={() => void handleRoomControl(room.id, { action: "prev" })}
                              className="rounded-lg bg-white p-2 shadow-2xs hover:bg-zinc-100"
                              title="上一集"
                            >
                              <SkipBack className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => void handleRoomControl(room.id, { action: isActivePlaying ? "pause" : "resume" })}
                              className="rounded-lg bg-[var(--brand-green)] p-2 text-white shadow-xs"
                              title={isActivePlaying ? "暂停" : "继续播放"}
                            >
                              {isActivePlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5 fill-current" />}
                            </button>
                            <button
                              onClick={() => void handleRoomControl(room.id, { action: "next" })}
                              className="rounded-lg bg-white p-2 shadow-2xs hover:bg-zinc-100"
                              title="下一集"
                            >
                              <SkipForward className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => void handleRoomControl(room.id, { action: "stop" }, "已停止房间队列")}
                              className="rounded-lg bg-white p-2 text-zinc-500 shadow-2xs hover:text-rose-600"
                              title="停止"
                            >
                              <Square className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>

                        {/* 循环模式 + 睡眠定时 + 队列展开 */}
                        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-200/70 pt-2.5">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <button
                              onClick={() => {
                                const nextLoop =
                                  sess.loop_mode === "sequential" ? "shuffle" : sess.loop_mode === "shuffle" ? "repeat_one" : "sequential";
                                void handleRoomControl(room.id, { action: "set_loop", loop_mode: nextLoop });
                              }}
                              className="inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-[11px] font-medium shadow-2xs"
                            >
                              {sess.loop_mode === "shuffle" ? <Shuffle className="h-3 w-3" /> : <Repeat className="h-3 w-3" />}
                              {sess.loop_mode === "sequential" ? "顺序连播" : sess.loop_mode === "shuffle" ? "随机" : "单集循环"}
                            </button>

                            <select
                              value=""
                              onChange={(e) => {
                                const val = e.target.value;
                                if (!val) return;
                                if (val === "off") void handleRoomControl(room.id, { action: "set_sleep" }, "已关闭睡眠定时");
                                if (val === "ep2") void handleRoomControl(room.id, { action: "set_sleep", sleep_episodes: 2 }, "已设播完2集自动停");
                                if (val === "m20") void handleRoomControl(room.id, { action: "set_sleep", sleep_minutes: 20 }, "已设20分钟后自动停");
                                if (val === "m40") void handleRoomControl(room.id, { action: "set_sleep", sleep_minutes: 40 }, "已设40分钟后自动停");
                              }}
                              className="rounded-lg bg-white px-2 py-1 text-[11px] font-medium shadow-2xs"
                            >
                              <option value="">
                                {sess.sleep_remaining_sec
                                  ? `🌙 剩 ${fmtRemaining(sess.sleep_remaining_sec)}`
                                  : sess.sleep_remaining_episodes
                                  ? `🌙 剩 ${sess.sleep_remaining_episodes} 集`
                                  : "🌙 睡眠定时"}
                              </option>
                              <option value="off">关闭定时</option>
                              <option value="ep2">播完 2 集停</option>
                              <option value="m20">20 分钟后停</option>
                              <option value="m40">40 分钟后停</option>
                            </select>
                          </div>

                          <button
                            onClick={() => setExpandedQueueDevId(queueOpen ? null : room.id)}
                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--brand-green)]"
                          >
                            <ListMusic className="h-3.5 w-3.5" />
                            队列 ({sess.queue.length})
                            {queueOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                          </button>
                        </div>

                        {queueOpen && (
                          <div className="max-h-40 space-y-1 overflow-y-auto rounded-xl bg-white p-2">
                            {sess.queue.map((qItem, qi) => (
                              <button
                                key={`${qItem.id}_${qi}`}
                                onClick={() => void handleRoomControl(room.id, { action: "jump", index: qi })}
                                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-[11px] ${
                                  qi === sess.current_index
                                    ? "bg-[var(--brand-green-soft)] font-bold text-[var(--brand-green)]"
                                    : "hover:bg-zinc-50"
                                }`}
                              >
                                <span className="truncate">{qi + 1}. {qItem.title}</span>
                                {qi === sess.current_index && <span>播放中</span>}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="flex items-center justify-between text-[var(--ink-muted)]">
                        <span>{room.playing_title || "当前待机中 · 可在「发现与专辑库」推送专辑"}</span>
                      </div>
                    )}
                  </div>

                  {/* 护耳音量滑块 */}
                  <div className="space-y-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1 font-medium text-zinc-700">
                        <Volume2 className="h-3.5 w-3.5" /> 房间音量：{room.volume}%
                      </span>
                      <span className="inline-flex items-center gap-1 text-[11px] text-[var(--brand-green)]">
                        <Shield className="h-3 w-3" /> 护耳上限 {room.max_volume}%
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={room.volume}
                      onChange={async (e) => {
                        const val = Number(e.target.value);
                        await api.updateDevice(room.id, { volume: val });
                        if (val > room.max_volume) {
                          showToast(`已触发护耳上限保护：音量自动限制在 ${room.max_volume}%`);
                        }
                        void loadRooms();
                      }}
                      className="w-full accent-[var(--brand-green)]"
                    />
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* 2. 家庭语音广播卡 */}
      <section className="card-pro p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold">📢 家庭跨房间语音喊话广播</h3>
            <p className="mt-0.5 text-xs text-[var(--ink-muted)]">对指定房间的智能音箱即时语音播报通知（如喊吃饭、收玩具、睡觉）。</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <Moon className="h-3.5 w-3.5 text-zinc-500" />
            <span>{dashboard.quiet_hours_active ? "当前正处于夜间免打扰" : "正常护耳时段"}</span>
          </div>
        </div>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const target = announceDevId || dashboard.devices[0]?.id;
            if (!target || !announceText.trim()) return;
            const r = await api.announceDevice(target, announceText);
            if (r.tts_url) onPlayUrl(r.tts_url);
            showToast("广播已发送");
            setAnnounceText("");
            void loadRooms();
          }}
          className="mt-3 flex flex-wrap gap-2"
        >
          <select
            value={announceDevId || dashboard.devices[0]?.id || ""}
            onChange={(e) => setAnnounceDevId(e.target.value)}
            className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-xs"
          >
            {dashboard.devices.length === 0 ? (
              <option value="">请先绑定音箱</option>
            ) : (
              dashboard.devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.room} · {d.name}
                </option>
              ))
            )}
          </select>
          <input
            value={announceText}
            onChange={(e) => setAnnounceText(e.target.value)}
            placeholder="输入广播喊话内容（如：开饭啦，请小朋友去洗手）..."
            className="min-w-[200px] flex-1 rounded-xl border border-[var(--border-soft)] px-3.5 py-2 text-xs"
          />
          <button
            type="submit"
            disabled={dashboard.devices.length === 0}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-5 py-2 text-xs font-semibold text-white disabled:opacity-40"
          >
            <Send className="h-3.5 w-3.5" /> 立即播报
          </button>
        </form>
      </section>

      {/* 3. 下半区：每日作息定时播控（复用） */}
      <section className="border-t border-[var(--border-soft)] pt-5">
        <SchedulesPage dashboard={dashboard} onRefresh={onRefreshDashboard} showToast={showToast} />
      </section>

      {/* 快速认领弹窗 */}
      <Modal open={!!claimTarget} title="认领新发现设备入家" onClose={() => setClaimTarget(null)}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (!claimTarget) return;
            await api.claimDevice({ device_id: claimTarget.id, name: claimName, room: claimRoom, max_volume: claimMaxVol });
            setClaimTarget(null);
            showToast(`已成功认领「${claimName}」`);
            onRefreshDashboard();
            void loadRooms();
          }}
          className="space-y-3 text-xs"
        >
          <input required value={claimName} onChange={(e) => setClaimName(e.target.value)} placeholder="设备名称" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
          <input value={claimRoom} onChange={(e) => setClaimRoom(e.target.value)} placeholder="所在房间（如：儿童房）" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
          <div>
            <div className="mb-1">护耳音量上限：{claimMaxVol}%</div>
            <input type="range" min={30} max={90} value={claimMaxVol} onChange={(e) => setClaimMaxVol(Number(e.target.value))} className="w-full accent-[var(--brand-green)]" />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setClaimTarget(null)} className="rounded-xl border border-[var(--border-soft)] px-4 py-2">取消</button>
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">确认认领</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
