import React, { useEffect, useState } from "react";
import { FolderSync, HardDrive, RefreshCw, Settings, Speaker, Trash2, Users } from "lucide-react";
import { api, AuthUser, DashboardData, DownloadJob, LocalFolder } from "../api";
import { FamilyPage } from "./FamilyPage";
import { RoomsControlPage } from "./RoomsControlPage";
import { StudioSystemPage } from "./StudioSystemPage";

type HubSubTab = "rooms" | "family" | "tasks" | "system";

export function HubSettingsPage({
  dashboard,
  user,
  isAdmin,
  initialSubTab = "rooms",
  onRefreshDashboard,
  onPlayUrl,
  showToast,
}: {
  dashboard: DashboardData;
  user: AuthUser;
  isAdmin: boolean;
  initialSubTab?: HubSubTab;
  onRefreshDashboard: () => void;
  onPlayUrl: (url: string) => void;
  showToast: (m: string) => void;
}) {
  const [subTab, setSubTab] = useState<HubSubTab>(initialSubTab);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [folders, setFolders] = useState<LocalFolder[]>([]);
  const [suggestedPaths, setSuggestedPaths] = useState<Array<{ name: string; path: string }>>([]);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderPath, setNewFolderPath] = useState("");
  const [newFolderType, setNewFolderType] = useState<LocalFolder["media_type"]>("auto");
  const [scanningId, setScanningId] = useState<number | null>(null);

  useEffect(() => {
    setSubTab(initialSubTab);
  }, [initialSubTab]);

  const loadTasksAndFolders = async () => {
    try {
      const [jList, fRes] = await Promise.all([api.getJobs(), api.listLocalFolders()]);
      setJobs(jList);
      setFolders(fRes.folders);
      setSuggestedPaths(fRes.suggested_paths);
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  useEffect(() => {
    if (subTab !== "tasks") return;
    void loadTasksAndFolders();
    const timer = window.setInterval(() => void loadTasksAndFolders(), 4000);
    return () => window.clearInterval(timer);
  }, [subTab]);

  const tabs: Array<{ id: HubSubTab; label: string; icon: React.ReactNode; adminOnly?: boolean }> = [
    { id: "rooms", label: "房间音箱与定时", icon: <Speaker className="h-3.5 w-3.5" /> },
    { id: "family", label: "家人与声纹记忆", icon: <Users className="h-3.5 w-3.5" /> },
    { id: "tasks", label: "采集任务与本地目录", icon: <FolderSync className="h-3.5 w-3.5" /> },
    { id: "system", label: "硬件 · 模型 · 账号", icon: <Settings className="h-3.5 w-3.5" />, adminOnly: true },
  ];

  return (
    <div className="space-y-5">
      {/* 顶部清晰二级胶囊导航 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border-soft)] pb-3">
        {tabs
          .filter((t) => !t.adminOnly || isAdmin)
          .map((t) => {
            const active = subTab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setSubTab(t.id)}
                className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold transition ${
                  active
                    ? "bg-[var(--brand-primary)] text-white shadow-xs"
                    : "border border-[var(--border-soft)] bg-[var(--bg-card)] text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
                }`}
              >
                {t.icon}
                <span>{t.label}</span>
              </button>
            );
          })}
      </div>

      {subTab === "rooms" && (
        <RoomsControlPage
          dashboard={dashboard}
          isAdmin={isAdmin}
          onRefreshDashboard={onRefreshDashboard}
          onPlayUrl={onPlayUrl}
          onOpenStudioSystem={isAdmin ? () => setSubTab("system") : undefined}
          showToast={showToast}
        />
      )}

      {subTab === "family" && (
        <FamilyPage
          onRefreshDashboard={onRefreshDashboard}
          onPlayUrl={onPlayUrl}
          showToast={showToast}
        />
      )}

      {subTab === "tasks" && (
        <div className="space-y-5">
          {/* 1. 后台采集与 AI 自动分类任务日志 */}
          <section className="card-pro p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-extrabold">后台采集与 AI 自动分类任务</h3>
                <p className="text-xs text-[var(--ink-muted)]">
                  展示音箱语音采集、网页 AI 采集、云端批量下歌与 RSS 同步的实时进度。
                </p>
              </div>
              <button
                onClick={() => void loadTasksAndFolders()}
                className="inline-flex items-center gap-1 rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5 text-xs font-semibold hover:bg-zinc-50"
              >
                <RefreshCw className="h-3.5 w-3.5" /> 刷新
              </button>
            </div>

            {jobs.length === 0 ? (
              <div className="rounded-xl bg-[var(--bg-subtle)] p-6 text-center text-xs text-[var(--ink-muted)]">
                暂无后台采集记录。对音箱说“帮我采集汪汪队第二季”或点击书架上的「AI 全网采集」即可启动。
              </div>
            ) : (
              <div className="divide-y divide-[var(--border-soft)] text-xs">
                {jobs.map((j) => (
                  <div key={j.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                            j.status === "done"
                              ? "bg-emerald-100 text-emerald-700"
                              : j.status === "failed"
                              ? "bg-rose-100 text-rose-700"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          {j.status === "done" ? "已完成" : j.status === "failed" ? "失败" : "进行中"}
                        </span>
                        <span className="truncate font-bold">{j.album_title || j.source_url}</span>
                      </div>
                      <div className="mt-0.5 text-[11px] text-[var(--ink-muted)]">
                        {j.progress_text}
                        {j.error_msg ? ` · 错误：${j.error_msg}` : ""}
                      </div>
                    </div>
                    <div className="shrink-0 text-right text-[11px] text-[var(--ink-muted)]">
                      <div className="font-bold text-[var(--ink-primary)]">入库 {j.tracks_added} 条</div>
                      <div>{j.created_at?.slice(0, 16).replace("T", " ")}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 2. 服务器 / 本机音频文件夹扫描挂载 */}
          <section className="card-pro p-5 space-y-4">
            <div>
              <h3 className="flex items-center gap-1.5 text-base font-extrabold">
                <HardDrive className="h-4 w-4 text-[var(--brand-primary)]" /> 服务器本地音频目录一键扫描
              </h3>
              <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
                把你服务器或 NAS 里已有的 MP3 / FLAC 文件夹挂进来，一键扫描入库并自动归类。
              </p>
            </div>

            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!newFolderPath.trim()) return;
                try {
                  await api.createLocalFolder({
                    name: newFolderName.trim() || "本地音频目录",
                    folder_path: newFolderPath.trim(),
                    media_type: newFolderType,
                    age_stage: "S6_ALL",
                  });
                  showToast("已挂载目录，点击扫描即可入库");
                  setNewFolderName("");
                  setNewFolderPath("");
                  await loadTasksAndFolders();
                } catch (err) {
                  showToast((err as Error).message);
                }
              }}
              className="grid gap-2 sm:grid-cols-12 text-xs"
            >
              <input
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="目录别名（如：NAS故事库）"
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-3"
              />
              <input
                value={newFolderPath}
                onChange={(e) => setNewFolderPath(e.target.value)}
                placeholder="服务器磁盘绝对路径（如 /data/music）"
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-5"
                required
              />
              <select
                value={newFolderType}
                onChange={(e) => setNewFolderType(e.target.value as LocalFolder["media_type"])}
                className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 sm:col-span-2"
              >
                <option value="auto">自动识别</option>
                <option value="story">故事书</option>
                <option value="music">音乐</option>
              </select>
              <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-4 py-2 font-bold text-white sm:col-span-2">
                添加目录
              </button>
            </form>

            {suggestedPaths.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className="text-[var(--ink-muted)]">快捷填充：</span>
                {suggestedPaths.map((sp) => (
                  <button
                    key={sp.path}
                    type="button"
                    onClick={() => {
                      setNewFolderName(sp.name);
                      setNewFolderPath(sp.path);
                    }}
                    className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-subtle)] px-2.5 py-1 hover:border-[var(--brand-primary)]"
                  >
                    {sp.name} ({sp.path})
                  </button>
                ))}
              </div>
            )}

            <div className="space-y-2 text-xs">
              {folders.map((f) => (
                <div key={f.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/50 p-3">
                  <div className="min-w-0 flex-1">
                    <div className="font-bold">{f.name}</div>
                    <div className="truncate font-mono text-[11px] text-[var(--ink-muted)]">{f.folder_path}</div>
                    <div className="mt-0.5 text-[11px] text-[var(--ink-secondary)]">{f.last_scan_summary}</div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button
                      disabled={scanningId === f.id}
                      onClick={async () => {
                        setScanningId(f.id);
                        try {
                          const r = await api.scanLocalFolder(f.id);
                          showToast(r.summary || `扫描完成，新增 ${r.tracks_added} 条`);
                          await loadTasksAndFolders();
                          onRefreshDashboard();
                        } catch (err) {
                          showToast((err as Error).message);
                        } finally {
                          setScanningId(null);
                        }
                      }}
                      className="rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 font-bold text-white disabled:opacity-50"
                    >
                      {scanningId === f.id ? "扫描中..." : "立即扫描"}
                    </button>
                    <button
                      onClick={async () => {
                        await api.deleteLocalFolder(f.id);
                        await loadTasksAndFolders();
                      }}
                      className="rounded-lg p-1.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {subTab === "system" && isAdmin && (
        <StudioSystemPage
          dashboard={dashboard}
          currentUser={user}
          onRefreshDashboard={onRefreshDashboard}
          showToast={showToast}
        />
      )}
    </div>
  );
}
