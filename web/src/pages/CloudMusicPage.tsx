import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  CloudDownload,
  Disc3,
  Flame,
  FolderPlus,
  Headphones,
  ListMusic,
  Loader2,
  Music,
  Play,
  RefreshCw,
  Search,
  ServerOff,
  Sparkles,
} from "lucide-react";
import {
  api,
  CloudCollection,
  CloudMusicStatus,
  CloudSong,
  CloudTopList,
  DownloadJob,
  MediaAlbum,
} from "../api";
import { EmptyState, Modal } from "../components/Modal";
import { QueueItem } from "../components/PlayerBar";

const SOURCE_BADGES: Record<string, { label: string; tone: string }> = {
  netease: { label: "网易云", tone: "bg-rose-50 text-rose-700 border-rose-200" },
  qq: { label: "QQ音乐", tone: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  kugou: { label: "酷狗", tone: "bg-sky-50 text-sky-700 border-sky-200" },
  kuwo: { label: "酷我", tone: "bg-amber-50 text-amber-700 border-amber-200" },
  migu: { label: "咪咕", tone: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200" },
  bilibili: { label: "Bilibili", tone: "bg-cyan-50 text-cyan-700 border-cyan-200" },
  qianqian: { label: "千千", tone: "bg-indigo-50 text-indigo-700 border-indigo-200" },
  joox: { label: "JOOX", tone: "bg-lime-50 text-lime-700 border-lime-200" },
};

function fmtDur(sec: number): string {
  const s = Math.max(0, Math.floor(sec || 0));
  if (!s) return "--:--";
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function songKey(s: CloudSong): string {
  return `${s.source}:${s.id}`;
}

export function CloudMusicPage({
  albums,
  onPlayQueue,
  onRefreshDashboard,
  onGoExplore,
  onOpenSettings,
  showToast,
}: {
  albums: MediaAlbum[];
  onPlayQueue: (items: QueueItem[], startIndex: number) => void;
  onRefreshDashboard: () => void;
  onGoExplore: () => void;
  onOpenSettings?: () => void;
  showToast: (m: string) => void;
}) {
  const [status, setStatus] = useState<CloudMusicStatus | null>(null);
  const [selectedSources, setSelectedSources] = useState<string[]>([
    "netease",
    "qq",
    "kugou",
    "kuwo",
    "migu",
    "bilibili",
  ]);
  const [tab, setTab] = useState<"toplists" | "song" | "playlist" | "album">("toplists");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);

  // 搜索 / 榜单数据
  const [toplists, setToplists] = useState<CloudTopList[]>([]);
  const [loadingTop, setLoadingTop] = useState(false);
  const [songs, setSongs] = useState<CloudSong[]>([]);
  const [collections, setCollections] = useState<CloudCollection[]>([]);

  // 歌单/专辑/榜单二级详情视图
  const [detailHeader, setDetailHeader] = useState<{ title: string; subtitle: string } | null>(null);
  const [detailSongs, setDetailSongs] = useState<CloudSong[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // 勾选与批量下载入库弹窗
  const [checkedKeys, setCheckedKeys] = useState<Record<string, boolean>>({});
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchPendingSongs, setBatchPendingSongs] = useState<CloudSong[]>([]);
  const [targetMode, setTargetMode] = useState<"auto_artist" | "new" | "existing">("auto_artist");
  const [newAlbumTitle, setNewAlbumTitle] = useState("云端下载精选");
  const [newSeasonLabel, setNewSeasonLabel] = useState("精选辑");
  const [existingAlbumId, setExistingAlbumId] = useState<number>(0);
  const [submittingBatch, setSubmittingBatch] = useState(false);

  // 云端下载队列轮询
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const hadRunningRef = useRef(false);

  const musicAlbums = useMemo(
    () => albums.filter((a) => !a.is_inbox && (a.category === "music" || a.category === "podcast")),
    [albums]
  );

  const fetchStatusAndToplists = async () => {
    setLoadingTop(true);
    try {
      const st = await api.cloudMusicStatus();
      setStatus(st);
      if (st.ok) {
        const list = await api.cloudMusicToplists(selectedSources);
        setToplists(list);
      }
    } catch {
      // 忽略首次未连接异常
    } finally {
      setLoadingTop(false);
    }
  };

  const fetchJobs = async () => {
    try {
      const list = await api.cloudMusicJobs(12);
      setJobs(list);
      const anyRunning = list.some((j) => j.status === "running" || j.status === "pending");
      if (hadRunningRef.current && !anyRunning) {
        onRefreshDashboard();
      }
      hadRunningRef.current = anyRunning;
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    void fetchStatusAndToplists();
    void fetchJobs();
  }, []);

  useEffect(() => {
    const hasActive = jobs.some((j) => j.status === "running" || j.status === "pending");
    if (!hasActive) return;
    const t = window.setInterval(() => {
      void fetchJobs();
    }, 2200);
    return () => window.clearInterval(t);
  }, [jobs]);

  const toQueueItems = (list: CloudSong[]): QueueItem[] =>
    list.map((s) => ({
      id: 0,
      kind: "online",
      title: s.artist ? `${s.name} - ${s.artist}` : s.name,
      subtitle: `${SOURCE_BADGES[s.source]?.label || s.source}${s.album ? ` · ${s.album}` : ""}`,
      streamUrl: api.cloudMusicStreamUrl(s),
      parentId: 0,
      durationSec: s.duration || 0,
    }));

  const handleToggleSource = (id: string) => {
    setSelectedSources((prev) => {
      if (prev.includes(id)) {
        if (prev.length <= 1) return prev;
        return prev.filter((x) => x !== id);
      }
      return [...prev, id];
    });
  };

  const handleSearch = async (e?: React.FormEvent, modeOverride?: "song" | "playlist" | "album") => {
    e?.preventDefault();
    const q = query.trim();
    const targetModeTab = modeOverride || (tab === "toplists" ? "song" : tab);
    if (!q) {
      if (!modeOverride && tab === "toplists") {
        void fetchStatusAndToplists();
      }
      return;
    }
    if (tab === "toplists" && !modeOverride) {
      setTab("song");
    }
    setDetailHeader(null);
    setDetailSongs([]);
    setCheckedKeys({});
    setSearching(true);
    try {
      const res = await api.cloudMusicSearch(q, targetModeTab, selectedSources, 1);
      if (targetModeTab === "song") {
        setSongs(res.songs || []);
      } else {
        setCollections(res.collections || []);
      }
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setSearching(false);
    }
  };

  const openToplist = async (tp: CloudTopList) => {
    setDetailHeader({
      title: tp.name,
      subtitle: `${SOURCE_BADGES[tp.source]?.label || tp.source}${tp.update_frequency ? ` · ${tp.update_frequency}` : ""}`,
    });
    setCheckedKeys({});
    setLoadingDetail(true);
    try {
      const res = await api.cloudMusicToplistSongs(tp.source, tp.toplist_id);
      setDetailSongs(res);
    } catch (err) {
      showToast((err as Error).message);
      setDetailHeader(null);
    } finally {
      setLoadingDetail(false);
    }
  };

  const openCollection = async (col: CloudCollection) => {
    setDetailHeader({
      title: col.title,
      subtitle: `${SOURCE_BADGES[col.source]?.label || col.source}${col.creator ? ` · ${col.creator}` : ""}`,
    });
    setCheckedKeys({});
    setLoadingDetail(true);
    try {
      const res = await api.cloudMusicCollectionSongs(col.source, col.id, col.content_type);
      setDetailSongs(res);
    } catch (err) {
      showToast((err as Error).message);
      setDetailHeader(null);
    } finally {
      setLoadingDetail(false);
    }
  };

  const activeSongList = detailHeader ? detailSongs : songs;
  const checkedSongs = useMemo(
    () => activeSongList.filter((s) => checkedKeys[songKey(s)]),
    [activeSongList, checkedKeys]
  );

  const openBatchModal = (targetList: CloudSong[], defaultTitle: string) => {
    if (targetList.length === 0) {
      showToast("请先勾选或打开要下载的歌曲");
      return;
    }
    setBatchPendingSongs(targetList);
    setNewAlbumTitle(defaultTitle || "云端下载精选");
    setNewSeasonLabel("精选辑");
    setTargetMode("auto_artist");
    if (musicAlbums.length > 0 && !existingAlbumId) {
      setExistingAlbumId(musicAlbums[0].id);
    }
    setBatchModalOpen(true);
  };

  const handleConfirmBatchDownload = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmittingBatch(true);
    try {
      const res = await api.cloudMusicBatchDownload({
        songs: batchPendingSongs,
        auto_group_by_artist: targetMode === "auto_artist",
        album_id: targetMode === "existing" && existingAlbumId > 0 ? existingAlbumId : null,
        new_series_title: targetMode === "new" ? newAlbumTitle.trim() || "云端下载精选" : "",
        season_label: targetMode === "new" ? newSeasonLabel.trim() || "精选辑" : "",
        new_album_title: targetMode === "new" ? newAlbumTitle.trim() || "云端下载精选" : "云端下载精选",
        category: "music",
        age_stage: "S6_ALL",
      });
      setBatchModalOpen(false);
      setCheckedKeys({});
      showToast(`已提交 ${res.total_requested} 首歌曲到云端队列，正在后台转码入库《${res.album_title}》`);
      hadRunningRef.current = true;
      await fetchJobs();
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setSubmittingBatch(false);
    }
  };

  const renderSongTable = (list: CloudSong[], defaultAlbumTitle: string) => {
    const allChecked = list.length > 0 && list.every((s) => checkedKeys[songKey(s)]);
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)] px-4 py-2.5 text-xs">
          <label className="inline-flex cursor-pointer items-center gap-2 font-semibold">
            <input
              type="checkbox"
              checked={allChecked}
              onChange={(e) => {
                const next: Record<string, boolean> = {};
                if (e.target.checked) {
                  for (const s of list) next[songKey(s)] = true;
                }
                setCheckedKeys(next);
              }}
              className="h-4 w-4 accent-[var(--brand-primary)]"
            />
            全选当前列表（共 {list.length} 首{checkedSongs.length > 0 ? `，已选 ${checkedSongs.length} 首` : ""}）
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => onPlayQueue(toQueueItems(list), 0)}
              disabled={list.length === 0}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3 py-1.5 font-semibold hover:border-[var(--brand-primary)] disabled:opacity-40"
            >
              <Play className="h-3.5 w-3.5 text-[var(--brand-primary)]" /> 播放全部
            </button>
            <button
              onClick={() =>
                openBatchModal(checkedSongs.length > 0 ? checkedSongs : list, defaultAlbumTitle)
              }
              disabled={list.length === 0}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-3.5 py-1.5 font-semibold text-white hover:bg-[var(--brand-primary-hover)] disabled:opacity-40"
            >
              <CloudDownload className="h-3.5 w-3.5" />
              {checkedSongs.length > 0
                ? `下载选中 (${checkedSongs.length} 首) 入库`
                : `整批下载 (${list.length} 首) 入库`}
            </button>
          </div>
        </div>

        <div className="card-pro divide-y divide-[var(--border-soft)] overflow-hidden">
          {list.map((s, idx) => {
            const key = songKey(s);
            const badge = SOURCE_BADGES[s.source] || {
              label: s.source,
              tone: "bg-zinc-100 text-zinc-700 border-zinc-200",
            };
            return (
              <div
                key={`${key}_${idx}`}
                className="flex items-center gap-3 px-4 py-2.5 text-xs transition hover:bg-[var(--bg-subtle)]"
              >
                <input
                  type="checkbox"
                  checked={!!checkedKeys[key]}
                  onChange={(e) => setCheckedKeys((p) => ({ ...p, [key]: e.target.checked }))}
                  className="h-4 w-4 shrink-0 accent-[var(--brand-primary)]"
                />
                <span className="w-6 shrink-0 text-center font-mono text-[11px] text-[var(--ink-muted)]">
                  {idx + 1}
                </span>
                <button
                  onClick={() => onPlayQueue(toQueueItems(list), idx)}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--brand-primary-soft)] text-[var(--brand-primary)] hover:bg-[var(--brand-primary-soft-hover)]"
                  title="立即云端试听（支持自动换源）"
                >
                  <Play className="h-3.5 w-3.5 fill-current" />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-bold">{s.name}</div>
                  <div className="truncate text-[11px] text-[var(--ink-muted)]">
                    {s.artist || "未知歌手"}
                    {s.album ? ` · 《${s.album}》` : ""}
                  </div>
                </div>
                <span className={`hidden shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold sm:inline-block ${badge.tone}`}>
                  {badge.label}
                </span>
                <span className="w-11 shrink-0 text-right font-mono text-[11px] text-[var(--ink-muted)]">
                  {fmtDur(s.duration)}
                </span>
                <button
                  onClick={() => openBatchModal([s], s.album || `${s.artist || "精选"}单曲集`)}
                  className="shrink-0 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-card)] px-2.5 py-1 text-[11px] font-semibold hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)]"
                  title="下载保存至云服务器曲库"
                >
                  ⬇ 存库
                </button>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* 顶部标题与引擎连通态 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight">全网无限听歌与云端批量下歌</h2>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
            多平台并发搜歌、热门排行榜与整张歌单解析——点击即听，或一键批量下载至服务器持久化私有曲库（含 LRC 歌词与 -16 LUFS 均衡）
          </p>
        </div>

        <div className="flex items-center gap-2">
          {status?.ok ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 border border-emerald-200">
              <CheckCircle2 className="h-3.5 w-3.5" /> 多源音乐引擎已连通（{status.latency_ms}ms）
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-800 border border-amber-200">
              <ServerOff className="h-3.5 w-3.5" /> 音乐伴生引擎未连接
            </span>
          )}
          <button
            onClick={() => void fetchStatusAndToplists()}
            className="rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] p-2 text-xs hover:bg-[var(--bg-subtle)]"
            title="刷新连接状态"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* 未连通温和指引 */}
      {status && !status.ok && (
        <div className="card-pro border-amber-200 bg-amber-50/60 p-4 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="font-bold text-amber-900">
              暂未检测到伴生 `go-music-dl` 引擎（当前地址：{status.base_url || "未配置"}）
            </div>
            {onOpenSettings && (
              <button
                onClick={onOpenSettings}
                className="rounded-lg bg-amber-700 px-3 py-1 font-semibold text-white hover:bg-amber-800"
              >
                前往系统设置修改地址 →
              </button>
            )}
          </div>
          <p className="mt-1.5 text-amber-800">
            推荐使用仓库根目录 <code className="rounded bg-white/80 px-1.5 py-0.5 font-mono">docker compose up -d</code> 一键同时启动 EchoMind 与多源音乐容器；
            或在本机启动测试容器：
            <code className="ml-1 rounded bg-white/80 px-1.5 py-0.5 font-mono">
              docker run -d -p 127.0.0.1:18080:8080 guohuiyuan/go-music-dl:latest ./music-dl web --port 8080 --no-browser
            </code>
          </p>
        </div>
      )}

      {/* 搜索条 + 多源平台选择 + 视图切换 */}
      <section className="card-pro space-y-3 p-4">
        <form onSubmit={(e) => void handleSearch(e)} className="flex flex-wrap gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[var(--ink-muted)]" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜歌手、歌名、专辑名，或直接粘贴网易云/QQ音乐歌单链接…"
              className="w-full rounded-xl border border-[var(--border-soft)] bg-[var(--bg-subtle)] py-2 pl-9 pr-3 text-sm outline-none focus:border-[var(--brand-primary)]"
            />
          </div>
          <button
            type="submit"
            disabled={searching}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-5 py-2 text-xs font-semibold text-white hover:bg-[var(--brand-primary-hover)] disabled:opacity-50"
          >
            {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            全网聚合搜歌
          </button>
        </form>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border-soft)] pt-3">
          {/* 4 个视图切换 */}
          <div className="flex flex-wrap gap-1.5 text-xs">
            {[
              { id: "toplists" as const, label: "🔥 热门榜单", icon: <Flame className="h-3.5 w-3.5" /> },
              { id: "song" as const, label: "🎵 单曲结果", icon: <Music className="h-3.5 w-3.5" /> },
              { id: "playlist" as const, label: "📑 搜歌单", icon: <ListMusic className="h-3.5 w-3.5" /> },
              { id: "album" as const, label: "💿 搜专辑", icon: <Disc3 className="h-3.5 w-3.5" /> },
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setTab(item.id);
                  setDetailHeader(null);
                  setCheckedKeys({});
                  if (item.id === "toplists" && toplists.length === 0) {
                    void fetchStatusAndToplists();
                  } else if (item.id !== "toplists" && query.trim()) {
                    void handleSearch(undefined, item.id);
                  }
                }}
                className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 font-semibold transition ${
                  tab === item.id
                    ? "bg-[var(--brand-primary)] text-white"
                    : "bg-[var(--bg-subtle)] text-[var(--ink-secondary)] hover:opacity-80"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          {/* 平台多选芯片 */}
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="font-semibold text-[var(--ink-muted)]">音源：</span>
            {(status?.supported_sources || [
              { id: "netease", label: "网易云" },
              { id: "qq", label: "QQ音乐" },
              { id: "kugou", label: "酷狗" },
              { id: "kuwo", label: "酷我" },
              { id: "migu", label: "咪咕" },
              { id: "bilibili", label: "B站" },
            ]).map((src) => {
              const active = selectedSources.includes(src.id);
              return (
                <button
                  key={src.id}
                  type="button"
                  onClick={() => handleToggleSource(src.id)}
                  className={`rounded-full border px-2.5 py-0.5 font-medium transition ${
                    active
                      ? "border-[var(--brand-primary)] bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]"
                      : "border-[var(--border-soft)] text-[var(--ink-muted)]"
                  }`}
                >
                  {src.label}
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* 云端批量下载队列进度条 */}
      {jobs.length > 0 && (
        <section className="card-pro space-y-2 p-4">
          <div className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-1.5 font-bold">
              <CloudDownload className="h-4 w-4 text-[var(--brand-primary)]" /> 云端批量下载入库进度
            </span>
            <button onClick={onGoExplore} className="font-semibold text-[var(--brand-primary)] hover:underline">
              前往私有曲库收听 →
            </button>
          </div>
          <div className="space-y-1.5">
            {jobs.slice(0, 4).map((j) => (
              <div
                key={j.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-subtle)] px-3 py-2 text-xs"
              >
                <div className="flex items-center gap-2">
                  {j.status === "running" || j.status === "pending" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--brand-primary)]" />
                  ) : j.status === "done" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5 text-rose-500" />
                  )}
                  <span className="font-medium">{j.progress_text}</span>
                </div>
                <span className="text-[11px] font-semibold text-[var(--ink-muted)]">
                  新增 {j.tracks_added} 首
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 主内容展示区 */}
      {detailHeader ? (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              onClick={() => {
                setDetailHeader(null);
                setCheckedKeys({});
              }}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3 py-1.5 text-xs font-semibold hover:bg-[var(--bg-subtle)]"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回列表
            </button>
            <div className="text-right">
              <div className="text-sm font-extrabold">{detailHeader.title}</div>
              <div className="text-[11px] text-[var(--ink-muted)]">{detailHeader.subtitle}</div>
            </div>
          </div>

          {loadingDetail ? (
            <div className="card-pro p-10 text-center text-xs text-[var(--ink-muted)]">
              <Loader2 className="mx-auto mb-2 h-6 w-6 animate-spin text-[var(--brand-primary)]" />
              正在拉取歌单曲目列表…
            </div>
          ) : detailSongs.length === 0 ? (
            <EmptyState icon={Music} title="列表暂无歌曲" description="该榜单或歌单暂未返回可解析曲目，请尝试更换音源或搜索关键词。" />
          ) : (
            renderSongTable(detailSongs, detailHeader.title)
          )}
        </section>
      ) : tab === "toplists" ? (
        loadingTop ? (
          <div className="card-pro p-10 text-center text-xs text-[var(--ink-muted)]">正在加载全平台热门排行榜…</div>
        ) : toplists.length === 0 ? (
          <EmptyState
            icon={Flame}
            title="暂无可展示的热歌榜"
            description="请确认伴生多源引擎已启动，或在上方直接输入关键词全网搜歌。"
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {toplists.map((tp) => {
              const badge = SOURCE_BADGES[tp.source] || {
                label: tp.source,
                tone: "bg-zinc-100 text-zinc-700 border-zinc-200",
              };
              return (
                <div
                  key={`${tp.source}_${tp.toplist_id}`}
                  onClick={() => void openToplist(tp)}
                  className="card-pro flex cursor-pointer items-center justify-between gap-3 p-4 transition hover:-translate-y-0.5 hover:border-[var(--brand-primary)]"
                >
                  <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]">
                    <Flame className="h-6 w-6" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-sm font-bold">{tp.name}</span>
                      <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-bold ${badge.tone}`}>
                        {badge.label}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-[11px] text-[var(--ink-muted)]">
                      {tp.update_frequency || "实时榜单"}
                      {tp.play_count_text ? ` · ${tp.play_count_text}` : ""}
                      {tp.track_count > 0 ? ` · ${tp.track_count} 首` : ""}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : tab === "song" ? (
        songs.length === 0 ? (
          <EmptyState
            icon={Headphones}
            title="输入歌手、歌名即可全网听歌与存库"
            description="例如输入「周杰伦 稻香」「陈奕迅」或粘贴网易云/QQ音乐分享链接，即刻试听或批量下载到你的云服务器曲库。"
          />
        ) : (
          renderSongTable(songs, `${query.trim() || "全网精选"} 曲库`)
        )
      ) : collections.length === 0 ? (
        <EmptyState
          icon={Disc3}
          title={tab === "playlist" ? "搜索跨平台主题歌单" : "搜索歌手精选专辑"}
          description="点击搜到的任意歌单或专辑，即可一键整张试听或批量下载为你的私有常驻专辑。"
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {collections.map((col) => {
            const badge = SOURCE_BADGES[col.source] || {
              label: col.source,
              tone: "bg-zinc-100 text-zinc-700 border-zinc-200",
            };
            return (
              <div
                key={`${col.source}_${col.id}`}
                onClick={() => void openCollection(col)}
                className="card-pro flex cursor-pointer items-center justify-between gap-3 p-4 transition hover:-translate-y-0.5 hover:border-[var(--brand-primary)]"
              >
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]">
                  <Disc3 className="h-6 w-6" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-bold">{col.title}</div>
                  <div className="mt-1 flex items-center gap-1.5 text-[11px] text-[var(--ink-muted)]">
                    <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-bold ${badge.tone}`}>
                      {badge.label}
                    </span>
                    <span className="truncate">
                      {col.creator ? `${col.creator} · ` : ""}
                      {col.track_count > 0 ? `${col.track_count} 首` : "点此展开曲目"}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 批量下载入库目标选择弹窗 */}
      <Modal
        open={batchModalOpen}
        title={`批量下载 ${batchPendingSongs.length} 首歌曲至私有云曲库`}
        onClose={() => setBatchModalOpen(false)}
        maxWidth="max-w-md"
      >
        <form onSubmit={handleConfirmBatchDownload} className="space-y-4 text-xs">
          <div className="rounded-xl bg-[var(--brand-primary-soft)] p-3 text-[var(--brand-primary)]">
            歌曲将从全网多源引擎自动下载并经过 -16 LUFS 响度校准持久化存入服务器，同时自动同步 LRC 歌词，断网后也能在音箱离线畅听。
          </div>

          <div className="grid grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => setTargetMode("auto_artist")}
              className={`rounded-xl border px-2 py-2 font-semibold ${
                targetMode === "auto_artist"
                  ? "border-[var(--brand-primary)] bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]"
                  : "border-[var(--border-soft)]"
              }`}
            >
              <Sparkles className="mx-auto mb-1 h-4 w-4" /> 按歌手自动分类
            </button>
            <button
              type="button"
              onClick={() => setTargetMode("new")}
              className={`rounded-xl border px-2 py-2 font-semibold ${
                targetMode === "new"
                  ? "border-[var(--brand-primary)] bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]"
                  : "border-[var(--border-soft)]"
              }`}
            >
              <FolderPlus className="mx-auto mb-1 h-4 w-4" /> 新建歌手/歌单
            </button>
            <button
              type="button"
              onClick={() => setTargetMode("existing")}
              disabled={musicAlbums.length === 0}
              className={`rounded-xl border px-2 py-2 font-semibold disabled:opacity-40 ${
                targetMode === "existing"
                  ? "border-[var(--brand-primary)] bg-[var(--brand-primary-soft)] text-[var(--brand-primary)]"
                  : "border-[var(--border-soft)]"
              }`}
            >
              <ListMusic className="mx-auto mb-1 h-4 w-4" /> 追加现有专辑
            </button>
          </div>

          {targetMode === "auto_artist" ? (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-emerald-800">
              ✨ 推荐模式：系统会自动按每首歌的<b>歌手名</b>建立一级分类，再按<b>原专辑名</b>建立二级专辑（例如「周杰伦 → 范特西 → 晴天」），彻底告别曲库杂乱！
            </div>
          ) : targetMode === "new" ? (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block font-semibold">一级歌手/歌单合集名</label>
                <input
                  required
                  value={newAlbumTitle}
                  onChange={(e) => setNewAlbumTitle(e.target.value)}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-xs"
                  placeholder="例如：周杰伦 / 车载流行"
                />
              </div>
              <div>
                <label className="mb-1 block font-semibold">二级专辑名</label>
                <input
                  value={newSeasonLabel}
                  onChange={(e) => setNewSeasonLabel(e.target.value)}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-xs"
                  placeholder="例如：精选辑 / 2026热歌"
                />
              </div>
            </div>
          ) : (
            <div>
              <label className="mb-1 block font-semibold">选择现有专辑</label>
              <select
                value={existingAlbumId}
                onChange={(e) => setExistingAlbumId(Number(e.target.value))}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
              >
                {musicAlbums.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.title}（现有 {(a.tracks || []).length} 首）
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setBatchModalOpen(false)}
              className="rounded-xl border border-[var(--border-soft)] px-4 py-2 font-medium"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submittingBatch}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-semibold text-white hover:bg-[var(--brand-primary-hover)] disabled:opacity-50"
            >
              {submittingBatch ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CloudDownload className="h-3.5 w-3.5" />}
              立即开始云端下歌
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
