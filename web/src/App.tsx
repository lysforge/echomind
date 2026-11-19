import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Compass,
  FolderInput,
  Library,
  LogOut,
  Menu,
  MessageSquareHeart,
  Mic,
  Moon,
  Settings,
  ShieldCheck,
  Speaker,
  Users,
  Wrench,
  X,
} from "lucide-react";
import { api, AuthUser, DashboardData, setOnUnauthorized, setStoredToken } from "./api";
import { PlayerBar, QueueItem } from "./components/PlayerBar";
import { ThemeSwitcher } from "./components/ThemeSwitcher";
import { VoiceChatDrawer } from "./components/VoiceChatDrawer";
import { AuthPage } from "./pages/AuthPage";
import { ExplorePage } from "./pages/ExplorePage";
import { FamilyPage } from "./pages/FamilyPage";
import { OnboardingModal } from "./pages/OnboardingModal";
import { RoomsControlPage } from "./pages/RoomsControlPage";
import { StudioCatalogPage } from "./pages/StudioCatalogPage";
import { StudioIngestPage } from "./pages/StudioIngestPage";
import { StudioSystemPage } from "./pages/StudioSystemPage";

type WorkspaceMode = "front" | "studio";
type FrontTab = "explore" | "rooms" | "family";
type StudioTab = "catalog" | "ingest" | "system";

export default function App() {
  const [authLoading, setAuthLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);

  // 前后台双空间导航
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("front");
  const [frontTab, setFrontTab] = useState<FrontTab>("explore");
  const [studioTab, setStudioTab] = useState<StudioTab>("catalog");
  const [studioFocusAlbumId, setStudioFocusAlbumId] = useState<number | null>(null);

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [voiceDrawerOpen, setVoiceDrawerOpen] = useState(false);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);

  // Toast 通知
  const [toast, setToast] = useState<string>("");
  const toastTimerRef = useRef<number | null>(null);
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 3600);
  }, []);

  // 全局播放状态
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progressSec, setProgressSec] = useState(0);
  const [durationSec, setDurationSec] = useState(0);
  const [loopMode, setLoopMode] = useState<"sequential" | "repeat_one" | "shuffle">("sequential");
  const [outputTarget, setOutputTarget] = useState<string>("browser");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const lastProgressSyncRef = useRef<number>(0);
  const browserSleepTimerRef = useRef<number | null>(null);

  // 刷新仪表盘数据
  const fetchDashboard = useCallback(async () => {
    try {
      const data = await api.getDashboard();
      setDashboard(data);
    } catch (e) {
      showToast((e as Error).message);
    }
  }, [showToast]);

  // 初始化认证检查
  useEffect(() => {
    setOnUnauthorized(() => {
      setUser(null);
      setDashboard(null);
      setInitialized(true);
    });
    const bootstrap = async () => {
      try {
        const st = await api.authStatus();
        setInitialized(st.initialized);
        if (st.user) {
          setUser(st.user);
        }
      } catch {
        // 保持未登录态
      } finally {
        setAuthLoading(false);
      }
    };
    void bootstrap();
  }, []);

  useEffect(() => {
    if (user) {
      void fetchDashboard();
    }
  }, [user, fetchDashboard]);

  // 非管理员禁止停留于后台模式
  useEffect(() => {
    if (user && user.role !== "admin" && workspaceMode === "studio") {
      setWorkspaceMode("front");
    }
  }, [user, workspaceMode]);

  // 播放短语音 / 试听音（支持播放结束回调）
  const playSingleUrl = useCallback(
    (url: string, onEnded?: () => void) => {
      if (!url) {
        onEnded?.();
        return;
      }
      if (ttsAudioRef.current) {
        ttsAudioRef.current.pause();
      }
      const a = new Audio(url);
      ttsAudioRef.current = a;
      if (onEnded) {
        a.onended = () => onEnded();
      }
      a.play().catch((err) => {
        showToast(`音频播放受阻: ${(err as Error).message}`);
        onEnded?.();
      });
    },
    [showToast]
  );

  // 启动某一队列下标播放（浏览器或音箱连接队列推送）
  const activateItemAt = useCallback(
    async (items: QueueItem[], idx: number, targetOverride?: string) => {
      const item = items[idx];
      if (!item) return;
      const target = targetOverride ?? outputTarget;
      setQueue(items);
      setCurrentIndex(idx);
      setProgressSec(0);
      setDurationSec(item.durationSec || 0);

      if (target !== "browser") {
        audioRef.current?.pause();
        setIsPlaying(false);
        try {
          if (item.kind === "track" && item.parentId > 0) {
            await api.pushPlayback({
              device_ids: [target],
              album_id: item.parentId,
              start_index: idx,
              loop_mode: loopMode,
            });
          } else if (item.kind === "track" && item.id > 0) {
            await api.castTrack(item.id, target);
          } else {
            showToast("在线实时流先为您通过本机浏览器播放");
            if (audioRef.current) {
              audioRef.current.src = item.streamUrl;
              void audioRef.current.play().then(() => setIsPlaying(true));
            }
            return;
          }
          const devName = dashboard?.devices.find((d) => d.id === target)?.name || target;
          showToast(`已推送连播队列「${item.title}」到 ${devName}`);
          setIsPlaying(true);
          void fetchDashboard();
        } catch (e) {
          showToast((e as Error).message);
        }
        return;
      }

      if (audioRef.current) {
        audioRef.current.src = item.streamUrl;
        audioRef.current.currentTime = 0;
        audioRef.current
          .play()
          .then(() => setIsPlaying(true))
          .catch((e) => {
            setIsPlaying(false);
            showToast(`浏览器播放失败: ${(e as Error).message}`);
          });
      }
    },
    [outputTarget, loopMode, dashboard, showToast, fetchDashboard]
  );

  const handleStep = useCallback(
    (delta: number) => {
      if (outputTarget !== "browser") {
        void api
          .controlRoomPlayback(outputTarget, { action: delta > 0 ? "next" : "prev" })
          .then(() => fetchDashboard())
          .catch((e) => showToast((e as Error).message));
        return;
      }
      if (queue.length === 0) return;
      let nextIdx = currentIndex + delta;
      if (loopMode === "shuffle" && queue.length > 1) {
        do {
          nextIdx = Math.floor(Math.random() * queue.length);
        } while (nextIdx === currentIndex);
      } else {
        if (nextIdx >= queue.length) nextIdx = 0;
        if (nextIdx < 0) nextIdx = queue.length - 1;
      }
      void activateItemAt(queue, nextIdx);
    },
    [outputTarget, queue, currentIndex, loopMode, activateItemAt, fetchDashboard, showToast]
  );

  const handleTogglePlay = () => {
    const cur = queue[currentIndex];
    if (outputTarget !== "browser") {
      void api
        .controlRoomPlayback(outputTarget, { action: isPlaying ? "pause" : "resume" })
        .then(() => {
          setIsPlaying(!isPlaying);
          showToast(isPlaying ? "已暂停音箱" : "已恢复音箱播放");
        })
        .catch(() => {
          if (cur) void activateItemAt(queue, currentIndex);
        });
      return;
    }
    if (!cur) return;
    const audio = audioRef.current;
    if (!audio) return;
    if (!audio.src) {
      void activateItemAt(queue, currentIndex);
      return;
    }
    if (audio.paused) {
      void audio.play().then(() => setIsPlaying(true));
    } else {
      audio.pause();
      setIsPlaying(false);
    }
  };

  // 响应网页语音对讲的即时播控指令
  const handleVoiceControlAction = (
    ctrl: NonNullable<Awaited<ReturnType<typeof api.interact>>["control_action"]>
  ) => {
    const act = ctrl.action;
    if (act === "pause" || act === "stop") {
      audioRef.current?.pause();
      setIsPlaying(false);
    } else if (act === "resume") {
      if (audioRef.current && audioRef.current.src) {
        void audioRef.current.play().then(() => setIsPlaying(true));
      }
    } else if (act === "next") {
      handleStep(1);
    } else if (act === "prev") {
      handleStep(-1);
    } else if (act === "volume_set" && typeof ctrl.value === "number") {
      if (audioRef.current) audioRef.current.volume = Math.max(0, Math.min(1, ctrl.value / 100));
    } else if (act === "volume_delta" && typeof ctrl.delta === "number") {
      if (audioRef.current) {
        audioRef.current.volume = Math.max(0, Math.min(1, audioRef.current.volume + ctrl.delta / 100));
      }
    } else if (act === "sleep_minutes" && typeof ctrl.minutes === "number") {
      if (browserSleepTimerRef.current) window.clearTimeout(browserSleepTimerRef.current);
      browserSleepTimerRef.current = window.setTimeout(() => {
        audioRef.current?.pause();
        setIsPlaying(false);
        showToast("睡眠定时到，已轻柔停止播放");
      }, ctrl.minutes * 60 * 1000);
    }
  };

  const handleSeek = (sec: number) => {
    setProgressSec(sec);
    if (audioRef.current && outputTarget === "browser") {
      audioRef.current.currentTime = sec;
    }
  };

  const handleCycleLoop = () => {
    const next = loopMode === "sequential" ? "repeat_one" : loopMode === "repeat_one" ? "shuffle" : "sequential";
    setLoopMode(next);
    if (outputTarget !== "browser") {
      void api.controlRoomPlayback(outputTarget, { action: "set_loop", loop_mode: next }).catch(() => undefined);
    }
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      // ignore
    }
    audioRef.current?.pause();
    setStoredToken("");
    setUser(null);
    setDashboard(null);
    setInitialized(true);
    setQueue([]);
    showToast("已安全退出登录");
  };

  const handleToggleQuiet = async () => {
    if (!dashboard) return;
    try {
      const next = !dashboard.quiet_hours_active;
      await api.toggleQuietHours(next);
      showToast(next ? "已开启夜间护耳免打扰" : "已关闭夜间免打扰");
      await fetchDashboard();
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--bg-canvas)] text-sm text-[var(--ink-muted)]">
        正在连接 EchoMind 家庭声音中枢…
      </div>
    );
  }

  if (!user) {
    return (
      <AuthPage
        initialized={initialized}
        onSuccess={(loggedUser) => {
          setUser(loggedUser);
          setInitialized(true);
          setWorkspaceMode("front");
          setFrontTab("explore");
        }}
      />
    );
  }

  const isAdmin = user.role === "admin";
  const onlineSpeakers = (dashboard?.devices || []).filter((d) => d.online === 1).length;
  const pendingCount = dashboard?.pending_devices?.length || 0;

  const shouldShowOnboarding =
    Boolean(dashboard) &&
    !dashboard!.onboarding_completed &&
    isAdmin &&
    !onboardingDismissed &&
    dashboard!.devices.length === 0 &&
    dashboard!.members.length === 0;

  const frontNavItems: Array<{ id: FrontTab; label: string; icon: React.ReactNode; badge?: string | number }> = [
    { id: "explore", label: "发现与专辑库", icon: <Compass className="h-4 w-4" /> },
    {
      id: "rooms",
      label: "房间音箱与定时",
      icon: <Speaker className="h-4 w-4" />,
      badge: pendingCount > 0 ? `待认领 ${pendingCount}` : onlineSpeakers > 0 ? `${onlineSpeakers} 在线` : undefined,
    },
    {
      id: "family",
      label: "家人声纹与记忆",
      icon: <Users className="h-4 w-4" />,
      badge: dashboard && dashboard.members.length > 0 ? dashboard.members.length : undefined,
    },
  ];

  const studioNavItems: Array<{ id: StudioTab; label: string; icon: React.ReactNode }> = [
    { id: "catalog", label: "专辑编目与分类", icon: <Library className="h-4 w-4" /> },
    { id: "ingest", label: "五大内容填充中心", icon: <FolderInput className="h-4 w-4" /> },
    { id: "system", label: "硬件 · 账号 · 系统设置", icon: <Settings className="h-4 w-4" /> },
  ];

  const currentHeaderTitle =
    workspaceMode === "front"
      ? frontNavItems.find((n) => n.id === frontTab)?.label || "发现与专辑库"
      : studioNavItems.find((n) => n.id === studioTab)?.label || "管理工作台";

  const renderSidebarContent = () => (
    <div className="flex h-full flex-col justify-between p-4">
      <div className="space-y-5 overflow-y-auto">
        {/* 品牌头 */}
        <div className="flex items-center gap-3 px-2 pt-1">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl shadow-sm ${
              workspaceMode === "studio" ? "bg-[var(--ink-primary)] text-[var(--bg-card)]" : "bg-[var(--brand-green)] text-white"
            }`}
          >
            {workspaceMode === "studio" ? <Wrench className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
          </div>
          <div className="min-w-0">
            <div className="flex items-baseline gap-1.5">
              <span className="text-base font-extrabold tracking-tight">EchoMind</span>
              <span className="text-[11px] font-medium text-[var(--ink-muted)]">· 声忆</span>
            </div>
            <div className="truncate text-xs text-[var(--ink-muted)]">
              {workspaceMode === "studio" ? "内容工坊与管理后台" : `${dashboard?.home_name || "我的家"} · 助手「${dashboard?.assistant_name || "小音"}」`}
            </div>
          </div>
        </div>

        {/* 前台模式：极简 3 栏 */}
        {workspaceMode === "front" ? (
          <div>
            <div className="mb-1.5 px-3 text-[11px] font-bold tracking-wider text-[var(--ink-muted)] uppercase">
              家庭听音与播控
            </div>
            <div className="space-y-1">
              {frontNavItems.map((item) => {
                const active = frontTab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      setFrontTab(item.id);
                      setMobileNavOpen(false);
                    }}
                    className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-sm font-semibold transition ${
                      active ? "bg-[var(--brand-green)] text-white shadow-xs" : "text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
                    }`}
                  >
                    <span className="flex items-center gap-2.5">
                      {item.icon}
                      <span>{item.label}</span>
                    </span>
                    {item.badge !== undefined && (
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${active ? "bg-white/20 text-white" : "bg-[var(--bg-subtle)] text-[var(--ink-secondary)]"}`}>
                        {item.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          /* 后台模式：返回按钮 + 专业 3 栏管理 */
          <div className="space-y-4">
            <button
              onClick={() => {
                setWorkspaceMode("front");
                setMobileNavOpen(false);
              }}
              className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-[var(--brand-green)] bg-[var(--brand-green-soft)] px-3 py-2 text-xs font-bold text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)]"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回家庭听音台
            </button>

            <div>
              <div className="mb-1.5 flex items-center gap-1 px-3 text-[11px] font-bold tracking-wider text-[var(--brand-accent)] uppercase">
                <ShieldCheck className="h-3.5 w-3.5" />
                内容与系统工作台
              </div>
              <div className="space-y-1">
                {studioNavItems.map((item) => {
                  const active = studioTab === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => {
                        setStudioTab(item.id);
                        setMobileNavOpen(false);
                      }}
                      className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-semibold transition ${
                        active ? "bg-[var(--brand-primary)] text-white shadow-xs" : "text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
                      }`}
                    >
                      {item.icon}
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 底部：管理员进入后台切换卡（前台） / 局域网状态摘要（后台） */}
      <div className="mt-4 space-y-2">
        {workspaceMode === "front" && isAdmin && (
          <button
            onClick={() => {
              setWorkspaceMode("studio");
              setMobileNavOpen(false);
            }}
            className="flex w-full items-center justify-between rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)] p-3.5 text-left transition hover:border-[var(--brand-primary)]"
          >
            <div>
              <div className="flex items-center gap-1.5 text-xs font-extrabold text-[var(--ink-primary)]">
                <Wrench className="h-3.5 w-3.5 text-[var(--brand-primary)]" />
                内容工坊与管理后台
              </div>
              <div className="mt-0.5 text-[11px] text-[var(--ink-muted)]">分类、填充内容、音箱与模型 →</div>
            </div>
          </button>
        )}

        <div className="rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)] px-3 py-2.5 text-[11px] text-[var(--ink-muted)]">
          <div className="flex items-center justify-between font-mono">
            <span>{dashboard?.lan_ip || "127.0.0.1"}:{dashboard?.server_port || 8090}</span>
            <span className={dashboard?.llm_configured ? "text-emerald-700 font-semibold" : "text-amber-700"}>
              {dashboard?.llm_configured ? "LLM 就绪" : "离线兜底"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[var(--bg-canvas)] text-[var(--ink-primary)]">
      {/* 隐藏全局音频标签（浏览器直出播放） */}
      <audio
        ref={audioRef}
        onTimeUpdate={(e) => {
          const t = e.currentTarget.currentTime;
          setProgressSec(t);
          const cur = queue[currentIndex];
          const now = Date.now();
          if (cur && cur.kind === "track" && cur.id > 0 && now - lastProgressSyncRef.current > 5000) {
            lastProgressSyncRef.current = now;
            void api.saveProgress(cur.parentId, cur.id, t).catch(() => undefined);
          }
        }}
        onLoadedMetadata={(e) => {
          const d = e.currentTarget.duration;
          if (Number.isFinite(d) && d > 0) setDurationSec(d);
        }}
        onEnded={() => {
          if (loopMode === "repeat_one") {
            void activateItemAt(queue, currentIndex);
          } else if (queue.length > 0) {
            handleStep(1);
          } else {
            setIsPlaying(false);
          }
        }}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
      />

      {/* 桌面端固定侧边栏 */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-[var(--border-soft)] bg-[var(--bg-sidebar)] lg:block">
        {renderSidebarContent()}
      </aside>

      {/* 移动端侧边栏抽屉 */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div className="fixed inset-0 bg-black/40" onClick={() => setMobileNavOpen(false)} />
          <aside className="relative z-10 w-68 bg-[var(--bg-sidebar)] shadow-2xl">
            <button
              onClick={() => setMobileNavOpen(false)}
              className="absolute right-3 top-3 rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100"
            >
              <X className="h-5 w-5" />
            </button>
            {renderSidebarContent()}
          </aside>
        </div>
      )}

      {/* 主内容区 */}
      <div className="flex min-h-screen flex-col pb-28 lg:pl-64">
        <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-soft)] bg-[var(--bg-canvas)]/90 px-4 py-3 backdrop-blur-md sm:px-6">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileNavOpen(true)}
              className="rounded-xl border border-[var(--border-soft)] bg-white p-2 lg:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div>
              <h1 className="text-base font-bold sm:text-lg">{currentHeaderTitle}</h1>
              {dashboard && !dashboard.llm_configured && isAdmin && workspaceMode === "front" && (
                <button
                  onClick={() => {
                    setWorkspaceMode("studio");
                    setStudioTab("system");
                  }}
                  className="text-[11px] font-medium text-amber-700 hover:underline"
                >
                  大模型 API Key 未配置（正使用本地兜底模式，点此前往管理后台配置）→
                </button>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ThemeSwitcher />
            {dashboard && (
              <button
                onClick={handleToggleQuiet}
                className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition ${
                  dashboard.quiet_hours_active
                    ? "border-amber-300 bg-amber-50 text-amber-800"
                    : "border-[var(--border-soft)] bg-[var(--bg-card)] text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
                }`}
              >
                <Moon className="h-3.5 w-3.5" />
                {dashboard.quiet_hours_active ? "夜间免打扰中" : "护耳正常时段"}
              </button>
            )}

            <button
              onClick={() => setVoiceDrawerOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green-soft)] px-3.5 py-1.5 text-xs font-semibold text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)]"
            >
              <MessageSquareHeart className="h-3.5 w-3.5" />
              喊「{dashboard?.assistant_name || "小音"}」控制
            </button>

            <div className="flex items-center gap-2 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3 py-1.5 text-xs">
              <span className="font-semibold">{user.display_name}</span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                  isAdmin ? "bg-[var(--brand-green-soft)] text-[var(--brand-green)]" : "bg-zinc-100 text-zinc-600"
                }`}
              >
                {isAdmin ? "管理员" : "家庭成员"}
              </span>
              <button
                onClick={handleLogout}
                title="退出登录"
                className="ml-1 rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-rose-600"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">
          {!dashboard ? (
            <div className="card-pro p-10 text-center text-sm text-[var(--ink-muted)]">
              正在加载家庭声音中枢…
            </div>
          ) : workspaceMode === "front" ? (
            <>
              {frontTab === "explore" && (
                <ExplorePage
                  dashboard={dashboard}
                  isAdmin={isAdmin}
                  currentQueueItem={queue[currentIndex] || null}
                  isPlaying={isPlaying}
                  onPlayQueue={(items, idx) => void activateItemAt(items, idx)}
                  onPlayUrl={playSingleUrl}
                  onRefreshDashboard={fetchDashboard}
                  onOpenStudioAlbum={(albumId) => {
                    setWorkspaceMode("studio");
                    if (albumId && albumId > 0) {
                      setStudioTab("catalog");
                      setStudioFocusAlbumId(albumId);
                    } else {
                      setStudioTab("ingest");
                      setStudioFocusAlbumId(null);
                    }
                  }}
                  onOpenVoiceDrawer={() => setVoiceDrawerOpen(true)}
                  showToast={showToast}
                />
              )}
              {frontTab === "rooms" && (
                <RoomsControlPage
                  dashboard={dashboard}
                  isAdmin={isAdmin}
                  onRefreshDashboard={fetchDashboard}
                  onPlayUrl={playSingleUrl}
                  onOpenStudioSystem={() => {
                    setWorkspaceMode("studio");
                    setStudioTab("system");
                  }}
                  showToast={showToast}
                />
              )}
              {frontTab === "family" && (
                <FamilyPage
                  onPlayUrl={playSingleUrl}
                  onRefreshDashboard={fetchDashboard}
                  showToast={showToast}
                />
              )}
            </>
          ) : (
            isAdmin && (
              <>
                {studioTab === "catalog" && (
                  <StudioCatalogPage
                    initialAlbumId={studioFocusAlbumId}
                    onPlayQueue={(items, idx) => void activateItemAt(items, idx)}
                    onRefreshDashboard={fetchDashboard}
                    showToast={showToast}
                  />
                )}
                {studioTab === "ingest" && (
                  <StudioIngestPage
                    onPlayQueue={(items, idx) => void activateItemAt(items, idx)}
                    onRefreshDashboard={fetchDashboard}
                    showToast={showToast}
                  />
                )}
                {studioTab === "system" && (
                  <StudioSystemPage
                    dashboard={dashboard}
                    currentUser={user}
                    onRefreshDashboard={fetchDashboard}
                    showToast={showToast}
                  />
                )}
              </>
            )
          )}
        </main>
      </div>

      {/* 全局底部 Connect 播放器 */}
      <PlayerBar
        queue={queue}
        currentIndex={currentIndex}
        isPlaying={isPlaying}
        progressSec={progressSec}
        durationSec={durationSec}
        loopMode={loopMode}
        outputTarget={outputTarget}
        devices={dashboard?.devices || []}
        onTogglePlay={handleTogglePlay}
        onStep={handleStep}
        onSeek={handleSeek}
        onCycleLoop={handleCycleLoop}
        onSelectOutput={(nextTarget) => {
          setOutputTarget(nextTarget);
          const cur = queue[currentIndex];
          if (cur) {
            void activateItemAt(queue, currentIndex, nextTarget);
          } else {
            const devName =
              nextTarget === "browser"
                ? "本机浏览器"
                : dashboard?.devices.find((d) => d.id === nextTarget)?.name || nextTarget;
            showToast(`输出目标已切换至：${devName}`);
          }
        }}
        onSelectIndex={(idx) => void activateItemAt(queue, idx)}
        onBrowserVolume={(v) => {
          if (audioRef.current) audioRef.current.volume = Math.max(0, Math.min(1, v / 100));
          if (ttsAudioRef.current) ttsAudioRef.current.volume = Math.max(0, Math.min(1, v / 100));
        }}
      />

      {/* 右侧语音控制与对讲抽屉 */}
      <VoiceChatDrawer
        open={voiceDrawerOpen}
        onClose={() => setVoiceDrawerOpen(false)}
        members={dashboard?.members || []}
        devices={dashboard?.devices || []}
        onPlayUrl={playSingleUrl}
        onPlayTrackItem={(item) => void activateItemAt([item], 0, "browser")}
        onPlayQueueItems={(items, idx) => void activateItemAt(items, idx, "browser")}
        onControlAction={handleVoiceControlAction}
        onRefresh={fetchDashboard}
        showToast={showToast}
      />

      {/* 新手管理员 3 步建家向导 */}
      <OnboardingModal
        open={shouldShowOnboarding}
        onFinished={() => {
          setOnboardingDismissed(true);
          void fetchDashboard();
        }}
        onSkip={() => {
          setOnboardingDismissed(true);
          void api.completeOnboarding({}).then(() => fetchDashboard()).catch(() => undefined);
        }}
        showToast={showToast}
      />

      {toast && (
        <div className="fixed right-5 top-20 z-50 max-w-sm rounded-2xl bg-[var(--ink-primary)] px-4 py-3 text-xs font-medium text-[var(--bg-card)] shadow-xl">
          {toast}
        </div>
      )}
    </div>
  );
}
