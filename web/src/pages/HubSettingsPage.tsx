import React, { useEffect, useState } from "react";
import {
  Check,
  Cloud,
  Copy,
  Cpu,
  Database,
  Eye,
  FolderSync,
  HardDrive,
  Radio,
  RefreshCw,
  Settings,
  Sparkles,
  Speaker,
  Trash2,
  Users,
} from "lucide-react";
import {
  api,
  AuthUser,
  DashboardData,
  DownloadJob,
  LocalFolder,
  StorageOverview,
  WebDavMount,
  XiaoAiBridgeStatus,
  XiaoAiDiscoveredDevice,
} from "../api";
import { FamilyPage } from "./FamilyPage";
import { RoomsControlPage } from "./RoomsControlPage";
import { StudioSystemPage } from "./StudioSystemPage";

type HubSubTab = "rooms" | "hardware" | "family" | "tasks" | "system";

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

  // 小爱真机直连 + 小智 MCP 状态
  const [miStatus, setMiStatus] = useState<XiaoAiBridgeStatus | null>(null);
  const [miUser, setMiUser] = useState("");
  const [miPass, setMiPass] = useState("");
  const [publicBaseUrl, setPublicBaseUrl] = useState("");
  const [miTriggerWords, setMiTriggerWords] = useState("播放,采集,下载,继续听,跳到,下一集,上一集,暂停,停止,重播,快进,倒退");
  const [miDiscovering, setMiDiscovering] = useState(false);
  const [miDiscovered, setMiDiscovered] = useState<XiaoAiDiscoveredDevice[]>([]);
  const [bindRoomMap, setBindRoomMap] = useState<Record<string, string>>({});
  const [mcpTools, setMcpTools] = useState<Array<{ name: string; description: string }>>([]);
  const [copiedKey, setCopiedKey] = useState("");

  // 采集任务 + 本地目录 + WebDAV + 存储空间
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [folders, setFolders] = useState<LocalFolder[]>([]);
  const [suggestedPaths, setSuggestedPaths] = useState<Array<{ name: string; path: string }>>([]);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderPath, setNewFolderPath] = useState("");
  const [newFolderType, setNewFolderType] = useState<LocalFolder["media_type"]>("auto");
  const [scanningId, setScanningId] = useState<number | null>(null);

  // WebDAV
  const [webdavMounts, setWebdavMounts] = useState<WebDavMount[]>([]);
  const [wdName, setWdName] = useState("");
  const [wdUrl, setWdUrl] = useState("");
  const [wdUser, setWdUser] = useState("");
  const [wdPass, setWdPass] = useState("");
  const [wdPath, setWdPath] = useState("/");
  const [wdChannel, setWdChannel] = useState<WebDavMount["channel"]>("story");
  const [wdLevel, setWdLevel] = useState("L1");
  const [wdPreview, setWdPreview] = useState<Array<{ name: string; is_dir: boolean; size: number; path: string }>>([]);
  const [wdSyncingId, setWdSyncingId] = useState<number | null>(null);

  // 存储空间
  const [storage, setStorage] = useState<StorageOverview | null>(null);
  const [cleaningCache, setCleaningCache] = useState(false);

  useEffect(() => {
    setSubTab(initialSubTab);
  }, [initialSubTab]);

  const copyText = (key: string, val: string) => {
    void navigator.clipboard?.writeText(val);
    setCopiedKey(key);
    showToast("已复制到剪贴板");
    window.setTimeout(() => setCopiedKey(""), 1500);
  };

  const loadHardwarePanel = async () => {
    try {
      const [st, sett, mcp] = await Promise.all([api.getXiaoAiStatus(), api.getSettings(), api.listMcpTools()]);
      setMiStatus(st);
      setMiUser(sett.mi_user || "");
      setPublicBaseUrl(sett.public_base_url || sett.resolved_public_base_url || "");
      if (sett.mi_trigger_keywords) setMiTriggerWords(sett.mi_trigger_keywords);
      setMcpTools(mcp.tools || []);
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const loadTasksAndStorage = async () => {
    try {
      const [jList, fRes, wdList, stOverview] = await Promise.all([
        api.getJobs(),
        api.listLocalFolders(),
        api.listWebDavMounts(),
        api.getStorageOverview(),
      ]);
      setJobs(jList);
      setFolders(fRes.folders);
      setSuggestedPaths(fRes.suggested_paths);
      setWebdavMounts(wdList);
      setStorage(stOverview);
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  useEffect(() => {
    if (subTab === "hardware") {
      void loadHardwarePanel();
    } else if (subTab === "tasks") {
      void loadTasksAndStorage();
      const timer = window.setInterval(() => void loadTasksAndStorage(), 5000);
      return () => window.clearInterval(timer);
    }
  }, [subTab]);

  const tabs: Array<{ id: HubSubTab; label: string; icon: React.ReactNode; adminOnly?: boolean }> = [
    { id: "rooms", label: "房间音箱与定时", icon: <Speaker className="h-3.5 w-3.5" /> },
    { id: "hardware", label: "小爱真机与小智MCP", icon: <Radio className="h-3.5 w-3.5" /> },
    { id: "family", label: "家人与声纹记忆", icon: <Users className="h-3.5 w-3.5" /> },
    { id: "tasks", label: "采集 · 网盘WebDAV · 存储", icon: <FolderSync className="h-3.5 w-3.5" /> },
    { id: "system", label: "模型 · 账号 · 系统", icon: <Settings className="h-3.5 w-3.5" />, adminOnly: true },
  ];

  const mcpEndpoint = `http://${dashboard.lan_ip}:${dashboard.server_port}/api/mcp`;
  const xiaozhiOta = `http://${dashboard.lan_ip}:${dashboard.server_port}/xiaozhi/ota/`;

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
          onOpenStudioSystem={isAdmin ? () => setSubTab("hardware") : undefined}
          showToast={showToast}
        />
      )}

      {/* 小米小爱真机直连 + 小智 ESP32 MCP 接入台 */}
      {subTab === "hardware" && (
        <div className="space-y-5 text-xs">
          {/* 1. 真·小米小爱音箱直连卡片 */}
          <section className="card-pro p-5 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="flex items-center gap-2 text-base font-extrabold">
                  <Speaker className="h-4 w-4 text-[var(--brand-primary)]" /> 小米小爱音箱 · 真机直连控制（免刷机）
                </h3>
                <p className="mt-0.5 text-[var(--ink-muted)]">
                  直接登录小米账号自动发现家里全部小爱音箱，推送私有曲库与故事跨季连播、播报采集完成结果，并支持直接捕获你对着小爱说的话！
                </p>
              </div>
              {miStatus && (
                <span
                  className={`rounded-full px-3 py-1 font-bold ${
                    miStatus.bound_count > 0 ? "bg-emerald-100 text-emerald-700" : "bg-zinc-100 text-zinc-600"
                  }`}
                >
                  已绑定 {miStatus.bound_count} 台真小爱 · 语音监听{miStatus.poll_enabled ? "已开启" : "未开启"}
                </span>
              )}
            </div>

            {isAdmin ? (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  setMiDiscovering(true);
                  try {
                    const res = await api.discoverXiaoAiDevices({
                      mi_user: miUser.trim(),
                      mi_pass: miPass.trim() || undefined,
                      public_base_url: publicBaseUrl.trim(),
                      save_credentials: true,
                    });
                    setMiDiscovered(res.devices);
                    showToast(`发现 ${res.count} 台小米小爱音箱，点击右侧按钮一键绑定`);
                    await loadHardwarePanel();
                  } catch (err) {
                    showToast((err as Error).message);
                  } finally {
                    setMiDiscovering(false);
                  }
                }}
                className="grid gap-3 sm:grid-cols-12"
              >
                <div className="sm:col-span-3">
                  <label className="mb-1 block font-bold">小米账号（手机号/小米ID）</label>
                  <input
                    value={miUser}
                    onChange={(e) => setMiUser(e.target.value)}
                    placeholder="如：13800138000"
                    className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                    required
                  />
                </div>
                <div className="sm:col-span-3">
                  <label className="mb-1 block font-bold">小米密码（留空沿用已保存）</label>
                  <input
                    type="password"
                    value={miPass}
                    onChange={(e) => setMiPass(e.target.value)}
                    placeholder={miStatus?.configured ? "已保存（如需修改再填写）" : "请输入小米账号密码"}
                    className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                  />
                </div>
                <div className="sm:col-span-4">
                  <label className="mb-1 block font-bold">小爱可访问的服务器地址（局域网IP或公网域名）</label>
                  <input
                    value={publicBaseUrl}
                    onChange={(e) => setPublicBaseUrl(e.target.value)}
                    placeholder={`http://${dashboard.lan_ip}:${dashboard.server_port}`}
                    className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 font-mono"
                  />
                </div>
                <div className="flex items-end sm:col-span-2">
                  <button
                    type="submit"
                    disabled={miDiscovering}
                    className="w-full rounded-xl bg-[var(--brand-primary)] px-3 py-2 font-bold text-white disabled:opacity-50"
                  >
                    {miDiscovering ? "登录发现中..." : "发现小爱音箱"}
                  </button>
                </div>
              </form>
            ) : (
              <div className="rounded-xl bg-[var(--bg-subtle)] p-3 text-[var(--ink-muted)]">仅管理员可配置小米账号并绑定音箱。</div>
            )}

            {/* 发现的小爱音箱列表 */}
            {miDiscovered.length > 0 && (
              <div className="space-y-2 rounded-2xl border border-[var(--brand-primary)]/30 bg-[var(--brand-green-soft)]/50 p-3.5">
                <div className="font-extrabold text-[var(--brand-primary)]">发现以下小米小爱音箱（点一键绑定即可推送播放）：</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {miDiscovered.map((d) => (
                    <div key={d.mi_device_id} className="flex items-center justify-between gap-2 rounded-xl bg-white p-3 shadow-2xs">
                      <div className="min-w-0">
                        <div className="truncate font-bold">
                          {d.name} <span className="font-mono text-[10px] text-[var(--ink-muted)]">({d.hardware})</span>
                        </div>
                        <div className="text-[11px] text-[var(--ink-muted)]">
                          状态：{d.online ? "在线" : d.presence || "未知"} · MAC {d.mac || "-"}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <input
                          value={bindRoomMap[d.mi_device_id] ?? "客厅"}
                          onChange={(e) => setBindRoomMap((p) => ({ ...p, [d.mi_device_id]: e.target.value }))}
                          className="w-16 rounded-lg border border-[var(--border-soft)] px-2 py-1 text-[11px]"
                          placeholder="房间"
                        />
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              await api.bindXiaoAiDevice({
                                mi_device_id: d.mi_device_id,
                                miot_did: d.miot_did,
                                name: d.name,
                                hardware: d.hardware,
                                room: bindRoomMap[d.mi_device_id] || "客厅",
                                max_volume: 75,
                              });
                              showToast(`已成功绑定真小爱音箱「${d.name}」`);
                              await loadHardwarePanel();
                              onRefreshDashboard();
                            } catch (err) {
                              showToast((err as Error).message);
                            }
                          }}
                          className="rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 font-bold text-white"
                        >
                          绑定
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 小爱语音指令轮询开关 */}
            {isAdmin && miStatus && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/70 p-3.5">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="font-bold text-[var(--ink-primary)]">
                    语音指令自动接管（对着小爱说「帮我采集汪汪队第2季 / 播放汪汪队第2季第5集」直接执行）
                  </div>
                  <input
                    value={miTriggerWords}
                    onChange={(e) => setMiTriggerWords(e.target.value)}
                    className="w-full rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1 text-[11px]"
                    placeholder="触发关键词（逗号分隔）"
                  />
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const next = !miStatus.poll_enabled;
                      const st = await api.toggleXiaoAiPolling({ enabled: next, trigger_keywords: miTriggerWords });
                      setMiStatus(st);
                      showToast(next ? "已开启小爱语音指令自动接管与跨季连播监控" : "已关闭小爱语音轮询");
                    } catch (err) {
                      showToast((err as Error).message);
                    }
                  }}
                  className={`shrink-0 rounded-xl px-4 py-2 font-bold text-white ${
                    miStatus.poll_enabled ? "bg-emerald-600 hover:bg-emerald-700" : "bg-zinc-800 hover:bg-zinc-900"
                  }`}
                >
                  {miStatus.poll_enabled ? "● 监听运行中（点此关闭）" : "开启语音指令接管"}
                </button>
              </div>
            )}

            {miStatus?.last_error && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
                最近小爱提示：{miStatus.last_error}
              </div>
            )}
          </section>

          {/* 2. 小智 ESP32 标准 MCP Server 接入卡片 */}
          <section className="card-pro p-5 space-y-4">
            <div>
              <h3 className="flex items-center gap-2 text-base font-extrabold">
                <Cpu className="h-4 w-4 text-[var(--brand-primary)]" /> 小智 ESP32 语音终端 · 原生协议 & 标准 MCP Server
              </h3>
              <p className="mt-0.5 text-[var(--ink-muted)]">
                支持两种方式接入你家的小智 ESP32：① 直接把固件 OTA 指向 EchoMind 享受 Opus 断点续播与跨季连播；② 在现有的 <code className="rounded bg-zinc-100 px-1">xiaozhi-esp32-server</code> 中挂载下方标准 MCP 地址，让小智直接调用 EchoMind 放故事、跳季跳集与全网采集！
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/60 p-3.5">
                <div className="font-bold text-[var(--ink-secondary)]">标准 MCP Server HTTP 接入地址（JSON-RPC 2.0）</div>
                <div className="mt-1.5 flex items-center justify-between gap-2 rounded-xl bg-white px-3 py-2 font-mono text-[11px]">
                  <span className="truncate">{mcpEndpoint}</span>
                  <button
                    type="button"
                    onClick={() => copyText("mcp", mcpEndpoint)}
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[var(--brand-green-soft)] px-2 py-1 font-sans font-bold text-[var(--brand-primary)]"
                  >
                    {copiedKey === "mcp" ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />} 复制
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/60 p-3.5">
                <div className="font-bold text-[var(--ink-secondary)]">小智 ESP32 直连 OTA 地址（自动配对 + 跨季 Opus 连播）</div>
                <div className="mt-1.5 flex items-center justify-between gap-2 rounded-xl bg-white px-3 py-2 font-mono text-[11px]">
                  <span className="truncate">{xiaozhiOta}</span>
                  <button
                    type="button"
                    onClick={() => copyText("ota", xiaozhiOta)}
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[var(--brand-green-soft)] px-2 py-1 font-sans font-bold text-[var(--brand-primary)]"
                  >
                    {copiedKey === "ota" ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />} 复制
                  </button>
                </div>
              </div>
            </div>

            {mcpTools.length > 0 && (
              <div>
                <div className="mb-2 font-bold text-[var(--ink-secondary)]">已暴露的 MCP 工具清单（{mcpTools.length} 个）</div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {mcpTools.map((t) => (
                    <div key={t.name} className="rounded-xl border border-[var(--border-soft)] bg-white p-3">
                      <div className="font-mono font-bold text-[var(--brand-primary)]">{t.name}</div>
                      <div className="mt-1 text-[11px] leading-snug text-[var(--ink-muted)]">{t.description}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {subTab === "family" && (
        <FamilyPage
          onRefreshDashboard={onRefreshDashboard}
          onPlayUrl={onPlayUrl}
          showToast={showToast}
        />
      )}

      {subTab === "tasks" && (
        <div className="space-y-5 text-xs">
          {/* 1. 云服务器磁盘空间与存储清理运维面板 */}
          {storage && (
            <section className="card-pro p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="flex items-center gap-1.5 text-base font-extrabold">
                    <Database className="h-4 w-4 text-[var(--brand-primary)]" /> 服务器存储空间与缓存运维
                  </h3>
                  <p className="mt-0.5 text-[var(--ink-muted)]">
                    目录 <code className="rounded bg-zinc-100 px-1">{storage.data_dir}</code> · 可用空间{" "}
                    <b>{storage.disk_free_gb} GB</b> / 总计 {storage.disk_total_gb} GB（已用 {storage.disk_used_pct}%）
                  </p>
                </div>
                {isAdmin && (
                  <button
                    disabled={cleaningCache}
                    onClick={async () => {
                      setCleaningCache(true);
                      try {
                        const r = await api.cleanStorageCache();
                        showToast(`已清理 ${r.removed_files} 个临时与过期缓存文件，释放 ${r.freed_mb} MB`);
                        await loadTasksAndStorage();
                      } catch (err) {
                        showToast((err as Error).message);
                      } finally {
                        setCleaningCache(false);
                      }
                    }}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-4 py-2 font-bold text-white disabled:opacity-50"
                  >
                    <Sparkles className="h-3.5 w-3.5" /> {cleaningCache ? "清理中..." : `一键清理临时缓存 (${(storage.raw_cache_mb + storage.tts_cache_mb).toFixed(1)} MB)`}
                  </button>
                )}
              </div>

              <div className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--bg-subtle)]">
                <div
                  className={`h-full rounded-full ${storage.disk_used_pct > 85 ? "bg-rose-500" : "bg-[var(--brand-primary)]"}`}
                  style={{ width: `${Math.min(100, storage.disk_used_pct)}%` }}
                />
              </div>

              <div className="grid gap-2.5 sm:grid-cols-4">
                {[
                  { label: "正式音频曲库", val: `${storage.media_tracks_mb} MB` },
                  { label: "故事书架占用", val: `${storage.channel_usage_mb.story || 0} MB` },
                  { label: "音乐曲库占用", val: `${storage.channel_usage_mb.music || 0} MB` },
                  { label: "英语与播客占用", val: `${((storage.channel_usage_mb.english || 0) + (storage.channel_usage_mb.podcast || 0)).toFixed(1)} MB` },
                ].map((c) => (
                  <div key={c.label} className="rounded-xl bg-[var(--bg-subtle)] p-3">
                    <div className="text-[11px] text-[var(--ink-muted)]">{c.label}</div>
                    <div className="mt-0.5 text-sm font-extrabold">{c.val}</div>
                  </div>
                ))}
              </div>

              {storage.series_usage.length > 0 && (
                <div>
                  <div className="mb-1.5 font-bold text-[var(--ink-secondary)]">各合集空间占用排行（前 8 项）</div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {storage.series_usage.slice(0, 8).map((item) => (
                      <div key={item.series_id} className="flex items-center justify-between rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
                        <span className="truncate font-bold">
                          {item.cover_emoji || "📁"} {item.title}{" "}
                          <span className="font-normal text-[var(--ink-muted)]">({item.track_count} 条)</span>
                        </span>
                        <span className="ml-2 shrink-0 font-mono font-bold text-[var(--brand-primary)]">{item.size_mb} MB</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          {/* 2. 网盘 / OpenList / AList (WebDAV) 挂载与三级同步 */}
          <section className="card-pro p-5 space-y-4">
            <div>
              <h3 className="flex items-center gap-1.5 text-base font-extrabold">
                <Cloud className="h-4 w-4 text-[var(--brand-primary)]" /> 网盘 / OpenList / AList（WebDAV）批量同步导入
              </h3>
              <p className="mt-0.5 text-[var(--ink-muted)]">
                直接对接网盘的 WebDAV 接口，按目录结构 <code className="rounded bg-zinc-100 px-1">汪汪队/第1季/01.mp3</code> 一键自动建好三级树并护耳转码入库，最适合成百上千集全套故事与牛津树/RAZ 导入。
              </p>
            </div>

            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!wdName.trim() || !wdUrl.trim()) return;
                try {
                  await api.createWebDavMount({
                    name: wdName.trim(),
                    base_url: wdUrl.trim(),
                    username: wdUser.trim(),
                    password: wdPass,
                    remote_path: wdPath.trim() || "/",
                    channel: wdChannel,
                    level_code: wdChannel === "english" ? wdLevel : "",
                  });
                  showToast("已添加 WebDAV 网盘挂载，点击「一键同步」即可导入");
                  setWdName("");
                  setWdUrl("");
                  setWdPass("");
                  setWdPreview([]);
                  await loadTasksAndStorage();
                } catch (err) {
                  showToast((err as Error).message);
                }
              }}
              className="grid gap-2.5 sm:grid-cols-12"
            >
              <input
                value={wdName}
                onChange={(e) => setWdName(e.target.value)}
                placeholder="挂载别名（如：家庭OpenList故事盘）"
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-3"
                required
              />
              <input
                value={wdUrl}
                onChange={(e) => setWdUrl(e.target.value)}
                placeholder="WebDAV 地址（如 http://192.168.1.5:5244/dav）"
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-5"
                required
              />
              <input
                value={wdPath}
                onChange={(e) => setWdPath(e.target.value)}
                placeholder="远程子目录（如 /儿童故事）"
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-4"
              />
              <input
                value={wdUser}
                onChange={(e) => setWdUser(e.target.value)}
                placeholder="用户名（可选）"
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-3"
              />
              <input
                type="password"
                value={wdPass}
                onChange={(e) => setWdPass(e.target.value)}
                placeholder="密码（可选）"
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-3"
              />
              <select
                value={wdChannel}
                onChange={(e) => setWdChannel(e.target.value as WebDavMount["channel"])}
                className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 sm:col-span-2"
              >
                <option value="story">导入故事书架</option>
                <option value="music">导入音乐曲库</option>
                <option value="english">导入英语启蒙</option>
                <option value="podcast">导入播客电台</option>
              </select>
              {wdChannel === "english" && (
                <select
                  value={wdLevel}
                  onChange={(e) => setWdLevel(e.target.value)}
                  className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 sm:col-span-1"
                >
                  {["L1", "L2", "L3", "L4", "L5"].map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              )}
              <div className={`flex gap-2 ${wdChannel === "english" ? "sm:col-span-3" : "sm:col-span-4"}`}>
                <button
                  type="button"
                  onClick={async () => {
                    if (!wdUrl.trim()) return;
                    try {
                      const r = await api.previewWebDav({
                        base_url: wdUrl.trim(),
                        remote_path: wdPath.trim() || "/",
                        username: wdUser.trim(),
                        password: wdPass,
                      });
                      setWdPreview(r.entries);
                      showToast(`连通成功，该目录下发现 ${r.count} 个项目`);
                    } catch (err) {
                      showToast((err as Error).message);
                    }
                  }}
                  className="inline-flex items-center gap-1 rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 font-bold"
                >
                  <Eye className="h-3.5 w-3.5" /> 预览
                </button>
                <button type="submit" className="flex-1 rounded-xl bg-[var(--brand-primary)] px-3 py-2 font-bold text-white">
                  添加网盘挂载
                </button>
              </div>
            </form>

            {wdPreview.length > 0 && (
              <div className="rounded-xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/60 p-3">
                <div className="mb-1.5 font-bold">远程目录预览（前 12 项）：</div>
                <div className="flex flex-wrap gap-1.5">
                  {wdPreview.slice(0, 12).map((e) => (
                    <span key={e.path} className="rounded-lg bg-white px-2 py-1 text-[11px] font-medium">
                      {e.is_dir ? "📁" : "🎵"} {e.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {webdavMounts.length > 0 && (
              <div className="space-y-2">
                {webdavMounts.map((m) => (
                  <div key={m.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/40 p-3">
                    <div className="min-w-0 flex-1">
                      <div className="font-bold">
                        {m.name} <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold">{m.channel}</span>
                      </div>
                      <div className="truncate font-mono text-[11px] text-[var(--ink-muted)]">
                        {m.base_url} · {m.remote_path}
                      </div>
                      <div className="mt-0.5 text-[11px] text-[var(--ink-secondary)]">{m.last_status}</div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        disabled={wdSyncingId === m.id}
                        onClick={async () => {
                          setWdSyncingId(m.id);
                          try {
                            const r = await api.syncWebDavMount(m.id, 100);
                            showToast(r.summary);
                            await loadTasksAndStorage();
                            onRefreshDashboard();
                          } catch (err) {
                            showToast((err as Error).message);
                          } finally {
                            setWdSyncingId(null);
                          }
                        }}
                        className="rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 font-bold text-white disabled:opacity-50"
                      >
                        {wdSyncingId === m.id ? "同步中..." : "一键同步入库"}
                      </button>
                      <button
                        onClick={async () => {
                          await api.deleteWebDavMount(m.id);
                          await loadTasksAndStorage();
                        }}
                        className="rounded-lg p-1.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 3. 服务器 / 本机音频文件夹扫描挂载（支持两级目录建树 + ID3 自动分歌手专辑） */}
          <section className="card-pro p-5 space-y-4">
            <div>
              <h3 className="flex items-center gap-1.5 text-base font-extrabold">
                <HardDrive className="h-4 w-4 text-[var(--brand-primary)]" /> 服务器本地音频目录一键扫描（支持三级目录与 ID3 标签）
              </h3>
              <p className="mt-0.5 text-[var(--ink-muted)]">
                故事目录按 <code className="rounded bg-zinc-100 px-1">汪汪队/第2季/01.mp3</code> 自动建三级树；音乐文件自动读取内嵌 ID3 标签按「歌手 → 专辑 → 单曲」归档！
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
                  await loadTasksAndStorage();
                } catch (err) {
                  showToast((err as Error).message);
                }
              }}
              className="grid gap-2 sm:grid-cols-12"
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
                <option value="music">音乐(ID3)</option>
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

            <div className="space-y-2">
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
                          await loadTasksAndStorage();
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
                        await loadTasksAndStorage();
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

          {/* 4. 后台采集与 AI 自动分类任务日志 */}
          <section className="card-pro p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-extrabold">后台采集与 AI 自动分类任务</h3>
                <p className="text-[var(--ink-muted)]">实时展示音箱语音采集、网页 AI 采集、云端下歌与 RSS 同步状态。</p>
              </div>
              <button
                onClick={() => void loadTasksAndStorage()}
                className="inline-flex items-center gap-1 rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5 font-semibold hover:bg-zinc-50"
              >
                <RefreshCw className="h-3.5 w-3.5" /> 刷新
              </button>
            </div>

            {jobs.length === 0 ? (
              <div className="rounded-xl bg-[var(--bg-subtle)] p-6 text-center text-[var(--ink-muted)]">
                暂无后台采集记录。对音箱说“帮我采集汪汪队第二季”或点「AI 全网采集」即可启动。
              </div>
            ) : (
              <div className="divide-y divide-[var(--border-soft)]">
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
