import React, { useEffect, useState } from "react";
import { CalendarClock, Edit3, Moon, Play, Plus, Trash2 } from "lucide-react";
import { api, BookItem, DashboardData, ScheduleItem } from "../api";
import { ConfirmDialog, EmptyState, Modal } from "../components/Modal";

const WEEK_DAYS = [
  { id: "1", label: "一" },
  { id: "2", label: "二" },
  { id: "3", label: "三" },
  { id: "4", label: "四" },
  { id: "5", label: "五" },
  { id: "6", label: "六" },
  { id: "7", label: "日" },
];

const TASK_LABELS: Record<ScheduleItem["task_type"], string> = {
  play_album: "专辑音乐播控",
  play_book: "有声书续播",
  english_immersion: "英语熏听课表",
  bedtime_story: "睡前故事哄睡",
  quiet_mode: "夜间免打扰",
};

export function SchedulesPage({
  dashboard,
  onRefresh,
  showToast,
}: {
  dashboard: DashboardData;
  onRefresh: () => void;
  showToast: (m: string) => void;
}) {
  const [books, setBooks] = useState<BookItem[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ScheduleItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ScheduleItem | null>(null);

  const [name, setName] = useState("");
  const [cronTime, setCronTime] = useState("20:00");
  const [days, setDays] = useState<string[]>(["1", "2", "3", "4", "5", "6", "7"]);
  const [taskType, setTaskType] = useState<ScheduleItem["task_type"]>("play_album");
  const [deviceId, setDeviceId] = useState("");
  const [albumId, setAlbumId] = useState<number | "">("");
  const [bookId, setBookId] = useState<number | "">("");
  const [targetVol, setTargetVol] = useState(45);
  const [fadeOut, setFadeOut] = useState(false);

  useEffect(() => {
    api.listBooks().then(setBooks).catch(() => {});
  }, []);

  const openCreate = () => {
    setEditing(null);
    setName("");
    setCronTime("20:00");
    setDays(["1", "2", "3", "4", "5", "6", "7"]);
    setTaskType("play_album");
    setDeviceId(dashboard.devices[0]?.id || "");
    setAlbumId(dashboard.albums[0]?.id || "");
    setBookId("");
    setTargetVol(45);
    setFadeOut(false);
    setModalOpen(true);
  };

  const openEdit = (s: ScheduleItem) => {
    setEditing(s);
    setName(s.name);
    setCronTime(s.cron_time);
    setDays((s.days_of_week || "1,2,3,4,5,6,7").split(",").filter(Boolean));
    setTaskType(s.task_type);
    setDeviceId(s.target_device_id || "");
    setAlbumId(s.album_id ?? "");
    setBookId(s.book_id ?? "");
    setTargetVol(s.target_volume ?? 50);
    setFadeOut(Boolean(s.fade_out));
    setModalOpen(true);
  };

  const toggleDay = (d: string) => {
    setDays((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d].sort()));
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">每日定时播控与作息守护</h2>
          <p className="text-xs text-[var(--ink-muted)]">
            支持自定义工作日/周末执行周期、定时预设音量、关联专辑或有声书以及睡前音量渐弱。
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={async () => {
              const next = !dashboard.quiet_hours_active;
              await api.toggleQuietHours(next);
              showToast(next ? "已开启夜间睡眠免打扰" : "已恢复正常时段");
              onRefresh();
            }}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-medium ${
              dashboard.quiet_hours_active ? "bg-indigo-900 text-white" : "border border-[var(--border-soft)] bg-white"
            }`}
          >
            <Moon className="h-4 w-4" />
            {dashboard.quiet_hours_active ? "夜间免打扰生效中" : "测试夜间免打扰"}
          </button>
          <button
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-4 py-2 text-xs font-semibold text-white"
          >
            <Plus className="h-4 w-4" /> 新建定时计划
          </button>
        </div>
      </div>

      {dashboard.schedules.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="暂未设置任何音箱定时播控任务"
          description="点击「新建定时计划」，为家里设定早上英语熏听、放学音乐或晚上睡前有声书定时播放。"
        />
      ) : (
        <div className="space-y-3">
          {dashboard.schedules.map((s) => (
            <div key={s.id} className="card-pro flex flex-wrap items-center justify-between gap-3 p-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="text-lg font-bold text-[var(--brand-green)]">{s.cron_time}</span>
                  <span className="text-sm font-bold">{s.name}</span>
                  <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-[11px]">{TASK_LABELS[s.task_type]}</span>
                </div>
                <div className="mt-1 text-xs text-[var(--ink-muted)]">
                  星期：{s.days_of_week} ｜ 预设音量：{s.target_volume}% ｜ 目标设备：{s.device_name || s.target_device_id || "未绑定设备"}
                  {s.fade_out ? " ｜ 睡前渐弱" : ""}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={async () => {
                    const r = await api.triggerSchedule(s.id);
                    showToast(r.message || "已试播");
                    onRefresh();
                  }}
                  className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-amber-soft)] px-3 py-1.5 text-xs font-medium text-[var(--brand-amber)]"
                >
                  <Play className="h-3.5 w-3.5" /> 立即试播
                </button>
                <button
                  onClick={() => api.toggleSchedule(s.id, !s.enabled).then(() => onRefresh())}
                  className={`rounded-xl px-3 py-1.5 text-xs font-medium ${
                    s.enabled ? "bg-[var(--brand-green)] text-white" : "bg-zinc-200 text-zinc-600"
                  }`}
                >
                  {s.enabled ? "已启用" : "已暂停"}
                </button>
                <button onClick={() => openEdit(s)} className="rounded-xl border border-[var(--border-soft)] p-2 text-zinc-500">
                  <Edit3 className="h-3.5 w-3.5" />
                </button>
                <button onClick={() => setDeleteTarget(s)} className="rounded-xl border border-[var(--border-soft)] p-2 text-zinc-400 hover:text-rose-600">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal open={modalOpen} title={editing ? "编辑定时计划" : "新建定时播控计划"} onClose={() => setModalOpen(false)}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const payload = {
              name,
              cron_time: cronTime,
              days_of_week: days.join(",") || "1,2,3,4,5,6,7",
              task_type: taskType,
              target_device_id: deviceId || null,
              album_id: taskType !== "play_book" && taskType !== "quiet_mode" && albumId !== "" ? Number(albumId) : null,
              book_id: taskType === "play_book" && bookId !== "" ? Number(bookId) : null,
              target_volume: targetVol,
              fade_out: fadeOut,
              enabled: true,
            };
            if (editing) {
              await api.replaceSchedule(editing.id, payload);
              showToast("定时计划已更新");
            } else {
              await api.createSchedule(payload);
              showToast("定时计划已创建");
            }
            setModalOpen(false);
            onRefresh();
          }}
          className="space-y-3 text-xs"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="计划名称 *"
              className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
            />
            <input
              required
              type="time"
              value={cronTime}
              onChange={(e) => setCronTime(e.target.value)}
              className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
            />
          </div>

          <div>
            <div className="mb-1.5 font-medium text-[var(--ink-muted)]">重复周期（星期）</div>
            <div className="flex gap-1.5">
              {WEEK_DAYS.map((wd) => (
                <button
                  key={wd.id}
                  type="button"
                  onClick={() => toggleDay(wd.id)}
                  className={`h-8 w-8 rounded-lg font-bold ${
                    days.includes(wd.id) ? "bg-[var(--brand-green)] text-white" : "bg-zinc-100 text-zinc-600"
                  }`}
                >
                  {wd.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <select
              value={taskType}
              onChange={(e) => setTaskType(e.target.value as ScheduleItem["task_type"])}
              className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
            >
              {Object.entries(TASK_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <select
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
              className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
            >
              <option value="">不指定设备（仅记录/网页播报）</option>
              {dashboard.devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>

          {taskType === "play_book" ? (
            <select
              value={bookId}
              onChange={(e) => setBookId(e.target.value ? Number(e.target.value) : "")}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
            >
              <option value="">自动挑选有声书籍</option>
              {books.map((b) => (
                <option key={b.id} value={b.id}>
                  书籍：{b.title}
                </option>
              ))}
            </select>
          ) : (
            taskType !== "quiet_mode" && (
              <select
                value={albumId}
                onChange={(e) => setAlbumId(e.target.value ? Number(e.target.value) : "")}
                className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
              >
                <option value="">自动挑选匹配分类专辑</option>
                {dashboard.albums.map((a) => (
                  <option key={a.id} value={a.id}>
                    专辑：{a.title}
                  </option>
                ))}
              </select>
            )
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-zinc-50 p-3">
            <div className="flex-1">
              <div className="mb-1">定时启动音量：{targetVol}%</div>
              <input
                type="range"
                min={10}
                max={100}
                value={targetVol}
                onChange={(e) => setTargetVol(Number(e.target.value))}
                className="w-full accent-[var(--brand-green)]"
              />
            </div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={fadeOut} onChange={(e) => setFadeOut(e.target.checked)} />
              睡前最后 2 分钟渐弱
            </label>
          </div>

          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setModalOpen(false)} className="rounded-xl border border-[var(--border-soft)] px-4 py-2">
              取消
            </button>
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">
              保存计划
            </button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!deleteTarget}
        title="删除定时任务"
        message={`确认删除定时计划「${deleteTarget?.name}」？`}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (!deleteTarget) return;
          await api.deleteSchedule(deleteTarget.id);
          setDeleteTarget(null);
          showToast("定时任务已删除");
          onRefresh();
        }}
      />
    </div>
  );
}
