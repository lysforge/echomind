import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  BookOpen,
  Disc3,
  GraduationCap,
  LogOut,
  Menu,
  MessageSquareHeart,
  Mic,
  Moon,
  Radio,
  Speaker,
  Volume2,
  X,
} from "lucide-react";
import { api, AuthUser, DashboardData, setOnUnauthorized, setStoredToken } from "./api";
import { PlayerBar, QueueItem } from "./components/PlayerBar";
import { ThemeSwitcher } from "./components/ThemeSwitcher";
import { VoiceChatDrawer } from "./components/VoiceChatDrawer";
import { AuthPage } from "./pages/AuthPage";
import { ChannelWorkspacePage } from "./pages/ChannelWorkspacePage";
import { EnglishEnlightenmentPage } from "./pages/EnglishEnlightenmentPage";
import { HubSettingsPage } from "./pages/HubSettingsPage";
import { OnboardingModal } from "./pages/OnboardingModal";

type MainNavTab = "story" | "music" | "english" | "podcast" | "hub";

interface CollectBanner {
  id: number;
  status: string;
  channel: "story" | "music" | "english" | "podcast";
  series_id?: number | null;
  series_title: string;
  season_label: string;
  tracks_added: number;
  summary_text: string;
  tts_url?: string | null;
}

export default function App() {
  const [authLoading, setAuthLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);

  // 极简统一 5 导航（彻底取消前后台割裂切换）
  const [activeTab, setActiveTab] = useState<MainNavTab>("story");
  const [hubSubTab, setHubSubTab] = useState<"rooms" | "hardware" | "family" | "tasks" | "system">("rooms");
  const [focusSeriesId, setFocusSeriesId] = useState<number | null>(null);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [activeMemberKey, setActiveMemberKey] = useState<string>("");

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [voiceDrawerOpen, setVoiceDrawerOpen] = useState(false);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);
  const [collectBanner, setCollectBanner] = useState<CollectBanner | null>(null);

  // Toast 通知
  const [toast, setToast] = useState<string>("");
  const toastTimerRef = useRef<number | null>(null);
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 3800);
  }, []);

  // 全局播放状态
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progressSec, setProgressSec] = useState(0);
  const [durationSec, setDurationSec] = useState(0);
  const [loopMode, setLoopMode] = useState<"sequential" | "repeat_one" | "shuffle">("sequential");
  const [playbackRate, setPlaybackRate] = useState<number>(1);
  const [outputTarget, setOutputTarget] = useState<string>("browser");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const pendingSeekRef = useRef<number>(0);
  const lastProgressSyncRef = useRef<number>(0);
  const browserSleepTimerRef = useRef<number | null>(null);

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

  // 播放短语音 / 试听音 / 词卡点读
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

  // 全局 /ws/web 实时推送：接收语音采集完成 & AI 自动分类通知、房间播控同步
  useEffect(() => {
    if (!user) return;
    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${proto}//${window.location.host}/ws/web`;
      try {
        ws = new WebSocket(wsUrl);
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            if (msg.type === "collect_completed") {
              setCollectBanner({
                id: msg.job_id || Date.now(),
                status: msg.status || "done",
                channel: msg.channel || "story",
                series_id: msg.series_id ?? null,
                series_title: msg.series_title || msg.query || "采集任务",
                season_label: msg.season_label || "",
                tracks_added: Number(msg.tracks_added || 0),
                summary_text: msg.summary_text || "采集与 AI 自动分类已完成",
                tts_url: msg.tts_url || null,
              });
              setRefreshSignal((n) => n + 1);
              void fetchDashboard();
              // 若非实体音箱发起（网页端发起的采集），自动播报温柔语音提示
              if (msg.tts_url && (!msg.device_id || msg.device_id === "web-console")) {
                playSingleUrl(msg.tts_url);
              }
            } else if (msg.type === "device_discovered" || msg.type === "device_state" || msg.type === "playback_session") {
              void fetchDashboard();
            }
          } catch {
            // ignore malformed ws message
          }
        };
        ws.onclose = () => {
          if (!closed) {
            reconnectTimer = window.setTimeout(connect, 4000);
          }
        };
      } catch {
        reconnectTimer = window.setTimeout(connect, 5000);
      }
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [user, fetchDashboard, playSingleUrl]);

  // 启动某一队列下标播放（浏览器支持精确断点秒数续播，或推音箱连播队列）
  const activateItemAt = useCallback(
    async (items: QueueItem[], idx: number, targetOverride?: string) => {
      const item = items[idx];
      if (!item) return;
      const target = targetOverride ?? outputTarget;
      const startPos = Math.max(0, Number(item.startPositionSec || 0));
      setQueue(items);
      setCurrentIndex(idx);
      setProgressSec(startPos);
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
              start_position_sec: startPos,
              resume: false,
              loop_mode: loopMode,
            });
          } else if (item.kind === "track" && item.id > 0) {
            await api.castTrack(item.id, target);
          } else {
            showToast("在线实时流先为您通过本机浏览器播放");
            if (audioRef.current) {
              pendingSeekRef.current = 0;
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
        pendingSeekRef.current = startPos;
        audioRef.current.src = item.streamUrl;
        audioRef.current.currentTime = startPos;
        audioRef.current.playbackRate = playbackRate;
        audioRef.current
          .play()
          .then(() => {
            setIsPlaying(true);
            if (item.kind === "track" && item.id > 0 && item.parentId > 0) {
              void api.saveProgress(item.parentId, item.id, startPos, activeMemberKey).catch(() => undefined);
            }
          })
          .catch((e) => {
            setIsPlaying(false);
            showToast(`浏览器播放失败: ${(e as Error).message}`);
          });
      }
    },
    [outputTarget, loopMode, playbackRate, activeMemberKey, dashboard, showToast, fetchDashboard]
  );

  // 浏览器端跨季无缝连播：播完当前季最后一集时自动切入同系列下一季第 1 集
  const tryAdvanceNextSeasonInBrowser = useCallback(async (): Promise<boolean> => {
    const cur = queue[currentIndex];
    if (!cur || !cur.seriesId) return false;
    try {
      const all = await api.listSeries({ member_key: activeMemberKey || undefined });
      const ser = all.find((s) => s.id === cur.seriesId);
      if (!ser || !ser.seasons || ser.seasons.length <= 1) return false;
      const curSeasonNum = cur.seasonNum || 1;
      const nextSea = ser.seasons.find(
        (sea) =>
          (sea.tracks?.length || 0) > 0 &&
          ((sea.season_num || 1) > curSeasonNum || ((sea.season_num || 1) === curSeasonNum && sea.id > cur.parentId))
      );
      if (!nextSea || !nextSea.tracks || nextSea.tracks.length === 0) return false;
      const seaLbl = nextSea.season_label || `第${nextSea.season_num || 1}季`;
      const nextItems: QueueItem[] = nextSea.tracks.map((t) => ({
        id: t.id,
        kind: "track",
        title: t.title,
        subtitle: `${ser.title} · ${seaLbl} · 第${t.episode_num}集`,
        streamUrl: t.stream_url || `/api/media/tracks/${t.id}/stream`,
        parentId: nextSea.id,
        durationSec: t.duration_sec || 0,
        startPositionSec: 0,
        episodeNum: t.episode_num,
        seasonNum: nextSea.season_num || 1,
        seasonLabel: seaLbl,
        seriesId: ser.id,
        seriesTitle: ser.title,
      }));
      showToast(`本季播完，已自动跨季连播《${ser.title} · ${seaLbl}》`);
      void activateItemAt(nextItems, 0, "browser");
      return true;
    } catch {
      return false;
    }
  }, [queue, currentIndex, activeMemberKey, activateItemAt, showToast]);

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
      if (delta > 0 && loopMode === "sequential" && currentIndex + delta >= queue.length) {
        void tryAdvanceNextSeasonInBrowser().then((switched) => {
          if (!switched) {
            const nextQueue = queue.map((q, i) => (i === 0 ? { ...q, startPositionSec: 0 } : q));
            void activateItemAt(nextQueue, 0);
          }
        });
        return;
      }
      let nextIdx = currentIndex + delta;
      if (loopMode === "shuffle" && queue.length > 1) {
        do {
          nextIdx = Math.floor(Math.random() * queue.length);
        } while (nextIdx === currentIndex);
      } else {
        if (nextIdx >= queue.length) nextIdx = 0;
        if (nextIdx < 0) nextIdx = queue.length - 1;
      }
      const nextQueue = queue.map((q, i) => (i === nextIdx ? { ...q, startPositionSec: 0 } : q));
      void activateItemAt(nextQueue, nextIdx);
    },
    [outputTarget, queue, currentIndex, loopMode, tryAdvanceNextSeasonInBrowser, activateItemAt, fetchDashboard, showToast]
  );

  const handleSeek = useCallback(
    (sec: number) => {
      const clamped = Math.max(0, Math.min(durationSec > 0 ? durationSec : sec, sec));
      setProgressSec(clamped);
      if (audioRef.current && outputTarget === "browser") {
        audioRef.current.currentTime = clamped;
        const cur = queue[currentIndex];
        if (cur && cur.kind === "track" && cur.id > 0 && cur.parentId > 0) {
          void api.saveProgress(cur.parentId, cur.id, clamped, activeMemberKey).catch(() => undefined);
        }
      }
    },
    [durationSec, outputTarget, queue, currentIndex, activeMemberKey]
  );

  const handleSeekDelta = useCallback(
    (deltaSec: number) => {
      if (outputTarget !== "browser") {
        void api
          .controlRoomPlayback(outputTarget, { action: "seek_delta", delta_sec: deltaSec })
          .then(() => showToast(deltaSec > 0 ? `音箱快进 ${deltaSec} 秒` : `音箱倒退 ${Math.abs(deltaSec)} 秒`))
          .catch((e) => showToast((e as Error).message));
        return;
      }
      const curTime = audioRef.current?.currentTime ?? progressSec;
      handleSeek(curTime + deltaSec);
    },
    [outputTarget, progressSec, handleSeek, showToast]
  );

  const handleCycleRate = useCallback(() => {
    const rates = [0.75, 1, 1.25, 1.5];
    const next = rates[(rates.indexOf(playbackRate) + 1) % rates.length];
    setPlaybackRate(next);
    if (audioRef.current) {
      audioRef.current.playbackRate = next;
    }
    showToast(`播放速度已切换为 ${next}x`);
  }, [playbackRate, showToast]);

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

  // 响应网页语音对讲的即时播控指令（含精准跳集）
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
    } else if (act === "jump") {
      if (typeof ctrl.index === "number" && ctrl.index >= 0 && ctrl.index < queue.length) {
        void activateItemAt(queue, ctrl.index);
      } else if (typeof ctrl.episode_num === "number") {
        const idx = queue.findIndex((q) => q.episodeNum === ctrl.episode_num);
        if (idx >= 0) void activateItemAt(queue, idx);
        else if (ctrl.episode_num >= 1 && ctrl.episode_num <= queue.length) void activateItemAt(queue, ctrl.episode_num - 1);
      }
    } else if (act === "replay") {
      handleSeek(0);
      if (audioRef.current && audioRef.current.src) {
        void audioRef.current.play().then(() => setIsPlaying(true));
      }
    } else if (act === "seek_delta" && typeof ctrl.delta_sec === "number") {
      handleSeekDelta(ctrl.delta_sec);
    } else if (act === "set_loop" && ctrl.loop_mode) {
      setLoopMode(ctrl.loop_mode);
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

  // 手机锁屏 / 耳机线控 MediaSession 集成
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
    const cur = queue[currentIndex];
    if (!cur) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: cur.title,
        artist: cur.subtitle || "EchoMind 声忆",
        album: cur.seriesTitle || "家庭声音中枢",
      });
      navigator.mediaSession.playbackState = isPlaying ? "playing" : "paused";
      navigator.mediaSession.setActionHandler("play", () => {
        if (audioRef.current && audioRef.current.paused) void audioRef.current.play();
      });
      navigator.mediaSession.setActionHandler("pause", () => {
        audioRef.current?.pause();
      });
      navigator.mediaSession.setActionHandler("previoustrack", () => handleStep(-1));
      navigator.mediaSession.setActionHandler("nexttrack", () => handleStep(1));
      navigator.mediaSession.setActionHandler("seekbackward", () => handleSeekDelta(-15));
      navigator.mediaSession.setActionHandler("seekforward", () => handleSeekDelta(15));
    } catch {
      // 部分旧浏览器不支持全部 MediaSession Handler
    }
  }, [queue, currentIndex, isPlaying, handleStep, handleSeekDelta]);

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
          setActiveTab("story");
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

  const navItems: Array<{ id: MainNavTab; label: string; hint: string; icon: React.ReactNode; badge?: string | number }> = [
    { id: "story", label: "故事书架", hint: "合集 · 季 · 集续播", icon: <BookOpen className="h-4 w-4" /> },
    { id: "music", label: "音乐曲库", hint: "私有歌单与无限下歌", icon: <Disc3 className="h-4 w-4" /> },
    { id: "english", label: "英语启蒙", hint: "L1-L5分级与点读", icon: <GraduationCap className="h-4 w-4" /> },
    { id: "podcast", label: "播客电台", hint: "RSS 订阅与续听", icon: <Radio className="h-4 w-4" /> },
    {
      id: "hub",
      label: "音箱与设置",
      hint: "推送 · 定时 · 家人 · 系统",
      icon: <Speaker className="h-4 w-4" />,
      badge: pendingCount > 0 ? `待认领 ${pendingCount}` : onlineSpeakers > 0 ? `${onlineSpeakers} 在线` : undefined,
    },
  ];

  const currentHeaderTitle = navItems.find((n) => n.id === activeTab)?.label || "故事书架";

  const renderSidebarContent = () => (
    <div className="flex h-full flex-col justify-between p-4">
      <div className="space-y-5 overflow-y-auto">
        {/* 品牌头 */}
        <div className="flex items-center gap-3 px-2 pt-1">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[var(--brand-primary)] text-white shadow-sm">
            <Mic className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex items-baseline gap-1.5">
              <span className="text-base font-extrabold tracking-tight">EchoMind</span>
              <span className="text-[11px] font-medium text-[var(--ink-muted)]">· 声忆</span>
            </div>
            <div className="truncate text-xs text-[var(--ink-muted)]">
              {dashboard?.home_name || "我的家"} · 助手「{dashboard?.assistant_name || "小音"}」
            </div>
          </div>
        </div>

        {/* 极简 5 导航 */}
        <div className="space-y-1.5">
          {navItems.map((item) => {
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  setActiveTab(item.id);
                  setMobileNavOpen(false);
                }}
                className={`flex w-full items-center justify-between rounded-2xl px-3.5 py-2.5 text-left transition ${
                  active
                    ? "bg-[var(--brand-primary)] text-white shadow-xs"
                    : "text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
                }`}
              >
                <span className="flex items-center gap-2.5 min-w-0">
                  {item.icon}
                  <span className="min-w-0">
                    <span className="block text-sm font-bold leading-tight">{item.label}</span>
                    <span className={`block truncate text-[10px] mt-0.5 ${active ? "text-white/80" : "text-[var(--ink-muted)]"}`}>
                      {item.hint}
                    </span>
                  </span>
                </span>
                {item.badge !== undefined && (
                  <span
                    className={`ml-2 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                      active ? "bg-white/20 text-white" : "bg-[var(--brand-green-soft)] text-[var(--brand-primary)]"
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* 底部：语音采集小贴士 + 服务器地址 */}
      <div className="mt-4 space-y-2">
        <button
          onClick={() => {
            setVoiceDrawerOpen(true);
            setMobileNavOpen(false);
          }}
          className="w-full rounded-2xl border border-[var(--brand-primary)]/30 bg-[var(--brand-green-soft)] p-3 text-left transition hover:border-[var(--brand-primary)]"
        >
          <div className="flex items-center gap-1.5 text-xs font-extrabold text-[var(--brand-primary)]">
            <MessageSquareHeart className="h-3.5 w-3.5" /> 语音操控与采集
          </div>
          <div className="mt-1 text-[11px] leading-snug text-[var(--ink-secondary)]">
            试试说：“帮我采集汪汪队第2季” 或 “播放汪汪队第2季第5集”
          </div>
        </button>

        <div className="rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)] px-3 py-2 text-[11px] text-[var(--ink-muted)]">
          <div className="flex items-center justify-between font-mono">
            <span>{dashboard?.lan_ip || "127.0.0.1"}:{dashboard?.server_port || 8090}</span>
            <span className={dashboard?.llm_configured ? "font-semibold text-emerald-700" : "text-amber-700"}>
              {dashboard?.llm_configured ? "AI 就绪" : "本地规则"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[var(--bg-canvas)] text-[var(--ink-primary)]">
      {/* 全局隐藏音频播放标签（支持精确断点跳转 + 5秒自动保存进度） */}
      <audio
        ref={audioRef}
        onTimeUpdate={(e) => {
          const t = e.currentTarget.currentTime;
          setProgressSec(t);
          const cur = queue[currentIndex];
          const now = Date.now();
          if (cur && cur.kind === "track" && cur.id > 0 && cur.parentId > 0 && now - lastProgressSyncRef.current > 5000) {
            lastProgressSyncRef.current = now;
            void api.saveProgress(cur.parentId, cur.id, t, activeMemberKey).catch(() => undefined);
          }
        }}
        onLoadedMetadata={(e) => {
          const d = e.currentTarget.duration;
          if (Number.isFinite(d) && d > 0) setDurationSec(d);
          e.currentTarget.playbackRate = playbackRate;
          if (pendingSeekRef.current > 1 && (!Number.isFinite(d) || pendingSeekRef.current < d - 1)) {
            e.currentTarget.currentTime = pendingSeekRef.current;
          }
          pendingSeekRef.current = 0;
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
        onPause={() => {
          setIsPlaying(false);
          const cur = queue[currentIndex];
          const t = audioRef.current?.currentTime || 0;
          if (cur && cur.kind === "track" && cur.id > 0 && cur.parentId > 0 && t > 1) {
            void api.saveProgress(cur.parentId, cur.id, t, activeMemberKey).catch(() => undefined);
          }
        }}
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
              {dashboard && !dashboard.llm_configured && isAdmin && (
                <button
                  onClick={() => {
                    setActiveTab("hub");
                    setHubSubTab("system");
                  }}
                  className="text-[11px] font-medium text-amber-700 hover:underline"
                >
                  大模型 API Key 未配置（当前使用本地智能分类与语音规则，点此配置大模型）→
                </button>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {dashboard && dashboard.members.length > 0 && (
              <select
                value={activeMemberKey}
                onChange={(e) => setActiveMemberKey(e.target.value)}
                title="切换听音成员（各自独立记住播放位置与英语打卡）"
                className="rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-2.5 py-1.5 text-xs font-semibold text-[var(--ink-primary)]"
              >
                <option value="">全家共享进度</option>
                {dashboard.members.map((m) => (
                  <option key={m.id} value={`member:${m.id}`}>
                    👤 {m.nickname} 的独立进度
                  </option>
                ))}
              </select>
            )}
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
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green-soft)] px-3.5 py-1.5 text-xs font-bold text-[var(--brand-primary)] hover:bg-[var(--brand-primary-soft-hover)]"
            >
              <MessageSquareHeart className="h-3.5 w-3.5" />
              喊「{dashboard?.assistant_name || "小音"}」控制
            </button>

            <div className="flex items-center gap-2 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3 py-1.5 text-xs">
              <span className="font-semibold">{user.display_name}</span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                  isAdmin ? "bg-[var(--brand-green-soft)] text-[var(--brand-primary)]" : "bg-zinc-100 text-zinc-600"
                }`}
              >
                {isAdmin ? "管理员" : "家人"}
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

        {/* 后台语音采集 + AI 自动分类实时完成通知横幅 */}
        {collectBanner && (
          <div className="mx-auto mt-3 w-full max-w-7xl px-4 sm:px-6">
            <div
              className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-xs shadow-sm ${
                collectBanner.status === "done"
                  ? "border-[var(--brand-primary)]/40 bg-[var(--brand-green-soft)] text-[var(--ink-primary)]"
                  : "border-amber-300 bg-amber-50 text-amber-900"
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0 flex-1">
                <Bell className="h-4 w-4 shrink-0 text-[var(--brand-primary)]" />
                <div className="min-w-0">
                  <div className="font-extrabold">
                    {collectBanner.status === "done"
                      ? `✨ 采集并 AI 分类完成：《${collectBanner.series_title}》${collectBanner.season_label}（+${collectBanner.tracks_added} 条）`
                      : `采集任务结束：《${collectBanner.series_title}》`}
                  </div>
                  <div className="mt-0.5 truncate text-[11px] opacity-85">{collectBanner.summary_text}</div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {collectBanner.tts_url && (
                  <button
                    onClick={() => playSingleUrl(collectBanner.tts_url!)}
                    className="inline-flex items-center gap-1 rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5 font-bold"
                  >
                    <Volume2 className="h-3.5 w-3.5" /> 听播报
                  </button>
                )}
                {collectBanner.status === "done" && (
                  <button
                    onClick={() => {
                      setActiveTab(collectBanner.channel);
                      if (collectBanner.series_id) setFocusSeriesId(collectBanner.series_id);
                      setCollectBanner(null);
                    }}
                    className="rounded-xl bg-[var(--brand-primary)] px-3.5 py-1.5 font-bold text-white"
                  >
                    去查看并播放 →
                  </button>
                )}
                <button
                  onClick={() => setCollectBanner(null)}
                  className="rounded-lg p-1 opacity-60 hover:opacity-100"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        )}

        <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">
          {!dashboard ? (
            <div className="card-pro p-10 text-center text-sm text-[var(--ink-muted)]">
              正在加载家庭声音中枢…
            </div>
          ) : (
            <>
              {(activeTab === "story" || activeTab === "music" || activeTab === "podcast") && (
                <ChannelWorkspacePage
                  channel={activeTab}
                  dashboard={dashboard}
                  memberKey={activeMemberKey}
                  refreshSignal={refreshSignal}
                  focusSeriesId={focusSeriesId}
                  onClearFocusSeries={() => setFocusSeriesId(null)}
                  onPlayQueue={(items, idx) => void activateItemAt(items, idx)}
                  onRefreshDashboard={() => {
                    void fetchDashboard();
                    setRefreshSignal((n) => n + 1);
                  }}
                  showToast={showToast}
                />
              )}
              {activeTab === "english" && (
                <EnglishEnlightenmentPage
                  dashboard={dashboard}
                  memberKey={activeMemberKey}
                  refreshSignal={refreshSignal}
                  onPlayQueue={(items, idx) => void activateItemAt(items, idx)}
                  onPlayUrl={playSingleUrl}
                  onRefreshDashboard={() => {
                    void fetchDashboard();
                    setRefreshSignal((n) => n + 1);
                  }}
                  showToast={showToast}
                />
              )}
              {activeTab === "hub" && (
                <HubSettingsPage
                  dashboard={dashboard}
                  user={user}
                  isAdmin={isAdmin}
                  initialSubTab={hubSubTab}
                  onRefreshDashboard={() => {
                    void fetchDashboard();
                    setRefreshSignal((n) => n + 1);
                  }}
                  onPlayUrl={playSingleUrl}
                  showToast={showToast}
                />
              )}
            </>
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
        playbackRate={playbackRate}
        outputTarget={outputTarget}
        devices={dashboard?.devices || []}
        onTogglePlay={handleTogglePlay}
        onStep={handleStep}
        onSeek={handleSeek}
        onSeekDelta={handleSeekDelta}
        onCycleRate={handleCycleRate}
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
        onRefresh={() => {
          void fetchDashboard();
          setRefreshSignal((n) => n + 1);
        }}
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
