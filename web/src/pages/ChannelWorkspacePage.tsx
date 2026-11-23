import React, { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Clock,
  Disc3,
  Download,
  Edit3,
  FileAudio,
  FolderPlus,
  Link2,
  Mic,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Sparkles,
  Speaker,
  Trash2,
  Upload,
} from "lucide-react";
import { api, ContentSource, DashboardData, MediaAlbum, MediaSeries, MediaTrack, SourcePreset } from "../api";
import { EmptyState, Modal } from "../components/Modal";
import { QueueItem } from "../components/PlayerBar";
import { PushTargetSpec, QuickPushModal } from "../components/QuickPushModal";
import { CloudMusicPage } from "./CloudMusicPage";

function fmtDur(sec?: number): string {
  if (!sec || !Number.isFinite(sec) || sec <= 0) return "--:--";
  const s = Math.floor(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

const CHANNEL_META = {
  story: {
    title: "故事书架",
    subtitle: "三级清晰整理：一级合集（如汪汪队） → 二级第几季 → 三级第几集，自动记忆续播位置，支持语音跳季跳集与跨季连播。",
    seriesNoun: "故事系列",
    seasonNoun: "季",
    trackNoun: "集",
    defaultEmoji: "📖",
    placeholderSeries: "如：汪汪队、西游记、小猪佩奇",
    placeholderSeason: "如：第1季、第2季",
    placeholderCollect: "如：汪汪队第2季、凯叔西游记第1季",
    emptyTitle: "故事书架还是空的",
    emptyDesc: "点右上角「✨ AI 全网采集」输入「汪汪队第2季」，或先手动新建一个故事系列再上传/采集音频。",
  },
  music: {
    title: "音乐曲库",
    subtitle: "按歌手或歌单分类整理你的私有云曲库，同时支持全网无限搜歌、热歌榜单与批量下歌到指定分类。",
    seriesNoun: "歌手 / 歌单合集",
    seasonNoun: "专辑",
    trackNoun: "首",
    defaultEmoji: "🎵",
    placeholderSeries: "如：周杰伦、哄睡轻音乐、经典儿歌",
    placeholderSeason: "如：精选辑、范特西、睡前钢琴",
    placeholderCollect: "如：周杰伦经典歌曲、哄睡轻音乐",
    emptyTitle: "私有音乐库还是空的",
    emptyDesc: "切换到「全网搜歌与下歌」把喜欢的歌手或榜单批量下载进来，或点「+ 新建歌手/歌单」开始整理。",
  },
  podcast: {
    title: "播客电台",
    subtitle: "按频道与节目季整理你的播客节目，支持 RSS 一键订阅、定时拉取最新期与精准续播记忆。",
    seriesNoun: "播客频道",
    seasonNoun: "季",
    trackNoun: "期",
    defaultEmoji: "🎙️",
    placeholderSeries: "如：凯叔科普电台、科技早知道",
    placeholderSeason: "如：第1季、2026精选",
    placeholderCollect: "如：少儿十万个为什么科普播客",
    emptyTitle: "还没有订阅或收录播客",
    emptyDesc: "点「📡 订阅 RSS 播客」一键导入精选频道，或直接新建播客合集。",
  },
} as const;

export function ChannelWorkspacePage({
  channel,
  dashboard,
  refreshSignal,
  focusSeriesId,
  onClearFocusSeries,
  onPlayQueue,
  onRefreshDashboard,
  showToast,
}: {
  channel: "story" | "music" | "podcast";
  dashboard: DashboardData;
  refreshSignal: number;
  focusSeriesId?: number | null;
  onClearFocusSeries?: () => void;
  onPlayQueue: (items: QueueItem[], startIndex: number) => void;
  onRefreshDashboard: () => void;
  showToast: (m: string) => void;
}) {
  const meta = CHANNEL_META[channel];
  const [musicView, setMusicView] = useState<"library" | "cloud">("library");
  const [seriesList, setSeriesList] = useState<MediaSeries[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQ, setSearchQ] = useState("");

  // 当前进入详情的一级系列与选中的二级季
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | null>(null);
  const [selectedAlbumId, setSelectedAlbumId] = useState<number | null>(null);

  // 推送音箱弹窗
  const [pushTarget, setPushTarget] = useState<PushTargetSpec | null>(null);

  // 新建/编辑一级系列弹窗
  const [seriesModalOpen, setSeriesModalOpen] = useState(false);
  const [editingSeries, setEditingSeries] = useState<MediaSeries | null>(null);
  const [sTitle, setSTitle] = useState("");
  const [sEmoji, setSEmoji] = useState<string>(meta.defaultEmoji);
  const [sAuthor, setSAuthor] = useState("");
  const [sFirstSeason, setSFirstSeason] = useState("");
  const [sDesc, setSDesc] = useState("");

  // 新增二级季/专辑弹窗
  const [seasonModalOpen, setSeasonModalOpen] = useState(false);
  const [newSeasonNum, setNewSeasonNum] = useState(1);
  const [newSeasonLabel, setNewSeasonLabel] = useState("");
  const [newSeasonDesc, setNewSeasonDesc] = useState("");

  // AI 全网采集弹窗
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [aiQuery, setAiQuery] = useState("");
  const [aiMaxItems, setAiMaxItems] = useState(5);
  const [aiDeviceId, setAiDeviceId] = useState("");
  const [aiTargetSeriesId, setAiTargetSeriesId] = useState<number | null>(null);
  const [aiTargetAlbumId, setAiTargetAlbumId] = useState<number | null>(null);
  const [aiBusy, setAiBusy] = useState(false);

  // 往当前季添加内容（4 合 1 就地弹窗）
  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestTab, setIngestTab] = useState<"search" | "url" | "upload" | "text">("search");
  const [onlineQ, setOnlineQ] = useState("");
  const [onlineSearching, setOnlineSearching] = useState(false);
  const [onlineResults, setOnlineResults] = useState<Array<{ title: string; duration_sec: number; uploader: string; url: string }>>([]);
  const [ytUrl, setYtUrl] = useState("");
  const [ytMax, setYtMax] = useState(10);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [ttsTitle, setTtsTitle] = useState("");
  const [ttsBody, setTtsBody] = useState("");
  const [ttsBusy, setTtsBusy] = useState(false);

  // 编辑单集（改名/集号/跨季移动）
  const [editingTrack, setEditingTrack] = useState<MediaTrack | null>(null);
  const [trTitle, setTrTitle] = useState("");
  const [trEpNum, setTrEpNum] = useState(1);
  const [trAlbumId, setTrAlbumId] = useState<number>(0);

  // 播客 RSS 订阅弹窗
  const [rssOpen, setRssOpen] = useState(false);
  const [rssSources, setRssSources] = useState<ContentSource[]>([]);
  const [rssPresets, setRssPresets] = useState<SourcePreset[]>([]);
  const [rssName, setRssName] = useState("");
  const [rssUrl, setRssUrl] = useState("");

  const loadSeries = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listSeries({ channel, q: searchQ.trim() || undefined });
      setSeriesList(data);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [channel, searchQ, showToast]);

  // 切换频道时复位选中项
  useEffect(() => {
    setSelectedSeriesId(null);
    setSelectedAlbumId(null);
    setMusicView("library");
    setSearchQ("");
  }, [channel]);

  useEffect(() => {
    void loadSeries();
  }, [loadSeries, refreshSignal]);

  useEffect(() => {
    if (focusSeriesId && seriesList.some((s) => s.id === focusSeriesId)) {
      setSelectedSeriesId(focusSeriesId);
      setMusicView("library");
      onClearFocusSeries?.();
    }
  }, [focusSeriesId, seriesList, onClearFocusSeries]);

  const activeSeries = seriesList.find((s) => s.id === selectedSeriesId) || null;
  const activeSeason: MediaAlbum | null =
    activeSeries?.seasons.find((sea) => sea.id === selectedAlbumId) ||
    (activeSeries?.resume_info && activeSeries.seasons.find((sea) => sea.id === activeSeries.resume_info?.album_id)) ||
    activeSeries?.seasons[0] ||
    null;

  useEffect(() => {
    if (activeSeries && activeSeason && activeSeason.id !== selectedAlbumId) {
      setSelectedAlbumId(activeSeason.id);
    }
  }, [activeSeries, activeSeason, selectedAlbumId]);

  const buildQueueFromSeason = (series: MediaSeries, season: MediaAlbum, resumeTrackId?: number | null, resumePosSec = 0): QueueItem[] => {
    const seaLbl = season.season_label || `第${season.season_num || 1}${meta.seasonNoun}`;
    return (season.tracks || []).map((t) => ({
      id: t.id,
      kind: "track" as const,
      title: t.title,
      subtitle: `${series.title} · ${seaLbl} · 第${t.episode_num}${meta.trackNoun}`,
      streamUrl: t.stream_url || `/api/media/tracks/${t.id}/stream`,
      parentId: season.id,
      durationSec: t.duration_sec || 0,
      startPositionSec: resumeTrackId && t.id === resumeTrackId ? resumePosSec : 0,
      episodeNum: t.episode_num,
      seasonLabel: seaLbl,
      seriesTitle: series.title,
    }));
  };

  const handleResumeSeriesInBrowser = (series: MediaSeries) => {
    const resume = series.resume_info;
    let targetSeason = resume ? series.seasons.find((a) => a.id === resume.album_id) : undefined;
    if (!targetSeason) {
      targetSeason = series.seasons.find((a) => (a.tracks?.length || 0) > 0);
    }
    if (!targetSeason || !targetSeason.tracks || targetSeason.tracks.length === 0) {
      showToast(`《${series.title}》暂无音频，点进去即可一键采集或上传`);
      setSelectedSeriesId(series.id);
      return;
    }
    const items = buildQueueFromSeason(series, targetSeason, resume?.track_id, resume?.position_sec || 0);
    const startIdx = resume ? Math.max(0, items.findIndex((i) => i.id === resume.track_id)) : 0;
    onPlayQueue(items, startIdx);
  };

  const handlePlaySeason = (series: MediaSeries, season: MediaAlbum, trackIdx?: number, useResume = false) => {
    const tracks = season.tracks || [];
    if (tracks.length === 0) {
      showToast("本季暂无单集，请先点击「+ 往本季添加」导入音频");
      return;
    }
    const resumeTid = useResume ? season.last_track_id : null;
    const resumePos = useResume ? season.last_position_sec || 0 : 0;
    const items = buildQueueFromSeason(series, season, resumeTid, resumePos);
    let idx = trackIdx ?? 0;
    if (trackIdx === undefined && useResume && resumeTid) {
      const found = items.findIndex((i) => i.id === resumeTid);
      if (found >= 0) idx = found;
    }
    onPlayQueue(items, idx);
  };

  const openCreateSeries = () => {
    setEditingSeries(null);
    setSTitle("");
    setSEmoji(meta.defaultEmoji);
    setSAuthor("");
    setSFirstSeason(channel === "music" ? "精选辑" : "第1季");
    setSDesc("");
    setSeriesModalOpen(true);
  };

  const openEditSeries = (s: MediaSeries) => {
    setEditingSeries(s);
    setSTitle(s.title);
    setSEmoji(s.cover_emoji || meta.defaultEmoji);
    setSAuthor(s.author || "");
    setSDesc(s.description || "");
    setSeriesModalOpen(true);
  };

  const handleSaveSeries = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sTitle.trim()) {
      showToast(`请填写${meta.seriesNoun}名称`);
      return;
    }
    try {
      if (editingSeries) {
        await api.updateSeries(editingSeries.id, {
          title: sTitle.trim(),
          cover_emoji: sEmoji.trim() || meta.defaultEmoji,
          author: sAuthor.trim(),
          description: sDesc.trim(),
        });
        showToast("已更新合集信息");
      } else {
        const created = await api.createSeries({
          title: sTitle.trim(),
          channel,
          cover_emoji: sEmoji.trim() || meta.defaultEmoji,
          author: sAuthor.trim(),
          description: sDesc.trim(),
          auto_create_first_season: true,
          first_season_label: sFirstSeason.trim() || (channel === "music" ? "精选辑" : "第1季"),
        });
        showToast(`已创建《${created.title}》，可直接添加音频或全网采集`);
        setSelectedSeriesId(created.id);
        if (created.seasons[0]) setSelectedAlbumId(created.seasons[0].id);
      }
      setSeriesModalOpen(false);
      await loadSeries();
      onRefreshDashboard();
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  const handleCreateSeason = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSeries) return;
    try {
      const created = await api.createSeason(activeSeries.id, {
        season_num: newSeasonNum,
        season_label: newSeasonLabel.trim() || (channel === "music" ? `专辑 ${newSeasonNum}` : `第${newSeasonNum}${meta.seasonNoun}`),
        description: newSeasonDesc.trim(),
      });
      showToast(`已新增 ${created.season_label}`);
      setSeasonModalOpen(false);
      await loadSeries();
      setSelectedAlbumId(created.id);
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  const openAiCollect = (targetSeries?: MediaSeries | null, targetAlb?: MediaAlbum | null) => {
    setAiTargetSeriesId(targetSeries?.id ?? null);
    setAiTargetAlbumId(targetAlb?.id ?? null);
    setAiQuery(
      targetSeries
        ? `${targetSeries.title} ${targetAlb?.season_label || ""}`.trim()
        : ""
    );
    setAiMaxItems(5);
    const firstOnline = dashboard.devices.find((d) => d.online === 1) || dashboard.devices[0];
    setAiDeviceId(firstOnline?.id || "");
    setAiModalOpen(true);
  };

  const handleStartAiCollect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!aiQuery.trim()) {
      showToast("请输入要采集的内容名称");
      return;
    }
    setAiBusy(true);
    try {
      const res = await api.aiCollect({
        query: aiQuery.trim(),
        channel_hint: channel,
        series_id: aiTargetSeriesId,
        album_id: aiTargetAlbumId,
        max_items: aiMaxItems,
        device_id: aiDeviceId,
        notify_speaker: Boolean(aiDeviceId),
      });
      const prev = res.preview;
      showToast(
        `后台已开始全网采集「${aiQuery.trim()}」` +
          (prev ? `，预计归类至《${prev.series_title} · ${prev.season_label}》，完成后会自动通知` : "")
      );
      setAiModalOpen(false);
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setAiBusy(false);
    }
  };

  const handleSearchOnlineForSeason = async () => {
    if (!onlineQ.trim()) return;
    setOnlineSearching(true);
    try {
      const items = await api.searchOnline(onlineQ.trim());
      setOnlineResults(items);
      if (items.length === 0) showToast("未搜到相关音频，可换个关键词或尝试粘贴链接");
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setOnlineSearching(false);
    }
  };

  const handleCollectSingleOnlineUrl = async (url: string, title: string) => {
    if (!activeSeason) return;
    try {
      await api.collectYtdlp(url, activeSeason.id, 1);
      showToast(`已将「${title.slice(0, 20)}」加入后台下载队列`);
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  const handleBatchUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSeason || uploadFiles.length === 0) return;
    setUploading(true);
    let ok = 0;
    try {
      for (const f of uploadFiles) {
        await api.uploadAudio(activeSeason.id, f);
        ok += 1;
      }
      showToast(`成功上传并护耳转码 ${ok} 个音频到「${activeSeason.season_label}」`);
      setUploadFiles([]);
      setIngestOpen(false);
      await loadSeries();
      onRefreshDashboard();
    } catch (err) {
      showToast(`已上传 ${ok} 个，部分失败：${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleAddTextTrack = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSeason || !ttsTitle.trim() || !ttsBody.trim()) return;
    setTtsBusy(true);
    try {
      await api.addTrackFromText(activeSeason.id, {
        title: ttsTitle.trim(),
        text_content: ttsBody.trim(),
      });
      showToast(`已合成《${ttsTitle.trim()}》并加入本季`);
      setTtsTitle("");
      setTtsBody("");
      setIngestOpen(false);
      await loadSeries();
      onRefreshDashboard();
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setTtsBusy(false);
    }
  };

  const handleSaveTrackEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingTrack) return;
    try {
      await api.updateTrack(editingTrack.id, {
        title: trTitle.trim(),
        episode_num: trEpNum,
        album_id: trAlbumId || editingTrack.album_id,
      });
      showToast("已更新单集信息");
      setEditingTrack(null);
      await loadSeries();
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  const loadRssModalData = async () => {
    setRssOpen(true);
    try {
      const [srcs, presets] = await Promise.all([api.listSources(), api.getSourcePresets()]);
      setRssSources(srcs);
      setRssPresets(presets.filter((p) => p.source_type === "podcast_rss"));
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  const handleCreateRssSource = async (name: string, url: string) => {
    if (!name.trim() || !url.trim()) return;
    try {
      const createdSeries = await api.createSeries({
        title: name.trim(),
        channel: "podcast",
        cover_emoji: "🎙️",
        auto_create_first_season: true,
        first_season_label: "第1季",
      }).catch(async () => {
        const list = await api.listSeries({ channel: "podcast" });
        return list.find((s) => s.title === name.trim()) || list[0];
      });
      const targetAlbId = createdSeries?.seasons?.[0]?.id ?? null;
      await api.createSource({
        name: name.trim(),
        source_type: "podcast_rss",
        url: url.trim(),
        target_album_id: targetAlbId,
        auto_sync: true,
        max_items_per_sync: 5,
      });
      showToast(`已订阅播客「${name.trim()}」，点击同步即可拉取最新期`);
      setRssName("");
      setRssUrl("");
      const srcs = await api.listSources();
      setRssSources(srcs);
      await loadSeries();
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  // ---------------- 音乐频道内置「全网无限搜歌与批量下歌」子视图 ----------------
  if (channel === "music" && musicView === "cloud") {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-card)] p-1 text-xs font-bold">
            <button
              onClick={() => {
                setMusicView("library");
                void loadSeries();
              }}
              className="rounded-xl px-4 py-2 text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
            >
              📚 我的分类曲库
            </button>
            <button className="rounded-xl bg-[var(--brand-primary)] px-4 py-2 text-white shadow-xs">
              🌐 全网搜歌与批量下歌
            </button>
          </div>
          <button
            onClick={() => {
              setMusicView("library");
              void loadSeries();
            }}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-white px-3.5 py-2 text-xs font-semibold hover:bg-zinc-50"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> 返回我的曲库
          </button>
        </div>

        <CloudMusicPage
          albums={dashboard.albums}
          onPlayQueue={onPlayQueue}
          onRefreshDashboard={() => {
            onRefreshDashboard();
            void loadSeries();
          }}
          onGoExplore={() => {
            setMusicView("library");
            void loadSeries();
          }}
          showToast={showToast}
        />
      </div>
    );
  }

  // ---------------- 二级（季/专辑） + 三级（单集）详情视图 ----------------
  if (activeSeries) {
    const seasons = activeSeries.seasons || [];
    const currentTracks = activeSeason?.tracks || [];
    const resume = activeSeries.resume_info;

    return (
      <div className="space-y-5">
        {/* 顶部面包屑 & 操作 */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <button
              onClick={() => {
                setSelectedSeriesId(null);
                setSelectedAlbumId(null);
              }}
              className="inline-flex items-center gap-1 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3 py-2 text-xs font-semibold hover:bg-[var(--bg-subtle)]"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> 返回{meta.title}
            </button>
            <span className="text-2xl">{activeSeries.cover_emoji || meta.defaultEmoji}</span>
            <div>
              <h2 className="text-lg font-extrabold tracking-tight">{activeSeries.title}</h2>
              <div className="text-xs text-[var(--ink-muted)]">
                共 {activeSeries.season_count} {meta.seasonNoun} · {activeSeries.total_tracks} {meta.trackNoun}
                {activeSeries.author ? ` · ${activeSeries.author}` : ""}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => openEditSeries(activeSeries)}
              className="inline-flex items-center gap-1 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3 py-2 text-xs font-semibold hover:bg-[var(--bg-subtle)]"
            >
              <Edit3 className="h-3.5 w-3.5" /> 编辑合集
            </button>
            <button
              onClick={async () => {
                if (!window.confirm(`确定删除整个《${activeSeries.title}》及下属全部音频吗？`)) return;
                await api.deleteSeries(activeSeries.id);
                showToast(`已删除《${activeSeries.title}》`);
                setSelectedSeriesId(null);
                await loadSeries();
                onRefreshDashboard();
              }}
              className="inline-flex items-center gap-1 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-100"
            >
              <Trash2 className="h-3.5 w-3.5" /> 删除合集
            </button>
          </div>
        </div>

        {/* 系列断点续播提示卡 */}
        {resume && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--brand-primary)]/30 bg-[var(--brand-green-soft)] px-4 py-3">
            <div className="flex items-center gap-2.5 text-xs">
              <Clock className="h-4 w-4 text-[var(--brand-primary)]" />
              <div>
                <span className="font-bold text-[var(--brand-primary)]">上次听到：</span>
                <span className="font-semibold text-[var(--ink-primary)]">
                  {resume.season_label} · 第{resume.episode_num}{meta.trackNoun}《{resume.track_title}》
                </span>
                {resume.position_sec > 2 && (
                  <span className="ml-1.5 rounded bg-white/80 px-1.5 py-0.5 font-mono text-[11px] font-bold text-[var(--brand-primary)]">
                    {fmtDur(resume.position_sec)}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleResumeSeriesInBrowser(activeSeries)}
                className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-primary)] px-3.5 py-1.5 text-xs font-bold text-white shadow-xs"
              >
                <Play className="h-3.5 w-3.5" /> 继续听
              </button>
              <button
                onClick={() =>
                  setPushTarget({
                    label: `${activeSeries.title}（续播）`,
                    subtitle: `从 ${resume.season_label} 第${resume.episode_num}${meta.trackNoun} ${fmtDur(resume.position_sec)} 起顺序跨季连播`,
                    seriesId: activeSeries.id,
                    defaultResume: true,
                  })
                }
                className="inline-flex items-center gap-1 rounded-xl border border-[var(--brand-primary)] bg-white px-3.5 py-1.5 text-xs font-bold text-[var(--brand-primary)]"
              >
                <Speaker className="h-3.5 w-3.5" /> 推音箱续播
              </button>
            </div>
          </div>
        )}

        {/* 二级分类：季 / 专辑 横排切换条 */}
        <div className="flex flex-wrap items-center gap-2">
          {seasons.map((sea) => {
            const active = activeSeason?.id === sea.id;
            const lbl = sea.season_label || `第${sea.season_num || 1}${meta.seasonNoun}`;
            return (
              <button
                key={sea.id}
                onClick={() => setSelectedAlbumId(sea.id)}
                className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold transition ${
                  active
                    ? "bg-[var(--brand-primary)] text-white shadow-xs"
                    : "border border-[var(--border-soft)] bg-[var(--bg-card)] text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
                }`}
              >
                <span>{lbl}</span>
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${active ? "bg-white/20 text-white" : "bg-[var(--bg-subtle)]"}`}>
                  {sea.tracks?.length || 0} {meta.trackNoun}
                </span>
              </button>
            );
          })}

          <button
            onClick={() => {
              const nextN = Math.max(0, ...seasons.map((s) => s.season_num || 0)) + 1;
              setNewSeasonNum(nextN);
              setNewSeasonLabel(channel === "music" ? `专辑 ${nextN}` : `第${nextN}${meta.seasonNoun}`);
              setNewSeasonDesc("");
              setSeasonModalOpen(true);
            }}
            className="inline-flex items-center gap-1 rounded-xl border border-dashed border-[var(--brand-primary)] bg-[var(--bg-card)] px-3.5 py-2 text-xs font-bold text-[var(--brand-primary)] hover:bg-[var(--brand-green-soft)]"
          >
            <Plus className="h-3.5 w-3.5" /> 新增第 {Math.max(0, ...seasons.map((s) => s.season_num || 0)) + 1} {meta.seasonNoun}
          </button>
        </div>

        {/* 当前季主面板 & 三级单集列表 */}
        {activeSeason ? (
          <section className="card-pro p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-soft)] pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-extrabold">
                    {activeSeason.season_label || `第${activeSeason.season_num || 1}${meta.seasonNoun}`}
                  </h3>
                  <span className="rounded-full bg-[var(--bg-subtle)] px-2.5 py-0.5 text-[11px] font-semibold text-[var(--ink-muted)]">
                    语音口令：「播放{activeSeries.title}{activeSeason.season_label || ""}第1{meta.trackNoun}」
                  </span>
                </div>
                {activeSeason.description && (
                  <p className="mt-1 text-xs text-[var(--ink-muted)]">{activeSeason.description}</p>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => handlePlaySeason(activeSeries, activeSeason, undefined, true)}
                  disabled={currentTracks.length === 0}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-4 py-2 text-xs font-bold text-white shadow-xs disabled:opacity-40"
                >
                  <Play className="h-3.5 w-3.5" /> 播放本{meta.seasonNoun}
                </button>
                <button
                  onClick={() =>
                    setPushTarget({
                      label: `${activeSeries.title} · ${activeSeason.season_label}`,
                      subtitle: `共 ${currentTracks.length} ${meta.trackNoun}，播完本${meta.seasonNoun}自动跨${meta.seasonNoun}连播`,
                      albumId: activeSeason.id,
                      seriesId: activeSeries.id,
                      defaultResume: true,
                    })
                  }
                  disabled={currentTracks.length === 0}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-primary)] bg-[var(--brand-green-soft)] px-4 py-2 text-xs font-bold text-[var(--brand-primary)] disabled:opacity-40"
                >
                  <Speaker className="h-3.5 w-3.5" /> 推音箱连播
                </button>
                <button
                  onClick={() => {
                    setOnlineQ(`${activeSeries.title} ${activeSeason.season_label || ""}`.trim());
                    setOnlineResults([]);
                    setIngestTab("search");
                    setIngestOpen(true);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-zinc-900 px-4 py-2 text-xs font-bold text-white hover:bg-zinc-800"
                >
                  <Plus className="h-3.5 w-3.5" /> 往本{meta.seasonNoun}添加音频
                </button>
                {seasons.length > 1 && (
                  <button
                    onClick={async () => {
                      if (!window.confirm(`确定删除「${activeSeason.season_label}」及其全部 ${currentTracks.length} 集吗？`)) return;
                      await api.deleteAlbum(activeSeason.id);
                      showToast(`已删除 ${activeSeason.season_label}`);
                      setSelectedAlbumId(null);
                      await loadSeries();
                    }}
                    className="rounded-xl p-2 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                    title={`删除本${meta.seasonNoun}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>

            {currentTracks.length === 0 ? (
              <EmptyState
                icon={FileAudio}
                title={`本${meta.seasonNoun}还没有音频`}
                description={`点上方「+ 往本${meta.seasonNoun}添加音频」，可直接全网搜集下载、粘贴链接抓取、批量上传本地 MP3，或粘贴文字合成温柔朗读。`}
                action={
                  <button
                    onClick={() => {
                      setOnlineQ(`${activeSeries.title} ${activeSeason.season_label || ""}`.trim());
                      setOnlineResults([]);
                      setIngestTab("search");
                      setIngestOpen(true);
                    }}
                    className="rounded-xl bg-[var(--brand-primary)] px-5 py-2.5 text-xs font-bold text-white"
                  >
                    + 立即采集或上传到本{meta.seasonNoun}
                  </button>
                }
              />
            ) : (
              <div className="divide-y divide-[var(--border-soft)]">
                {currentTracks.map((tr, idx) => {
                  const isResumeTrack = resume?.track_id === tr.id;
                  const savedPos = tr.last_position_sec || (isResumeTrack ? resume?.position_sec : 0) || 0;
                  return (
                    <div
                      key={tr.id}
                      className={`flex flex-wrap items-center justify-between gap-3 py-3 transition ${
                        isResumeTrack ? "rounded-xl bg-[var(--brand-green-soft)]/60 px-3 -mx-3" : ""
                      }`}
                    >
                      <div className="flex min-w-0 flex-1 items-center gap-3">
                        <span
                          className={`flex h-8 w-14 shrink-0 items-center justify-center rounded-lg text-xs font-extrabold ${
                            isResumeTrack
                              ? "bg-[var(--brand-primary)] text-white"
                              : "bg-[var(--bg-subtle)] text-[var(--ink-secondary)]"
                          }`}
                        >
                          第{tr.episode_num}{meta.trackNoun}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-bold text-[var(--ink-primary)]">{tr.title}</div>
                          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-[var(--ink-muted)]">
                            <span>时长 {fmtDur(tr.duration_sec)}</span>
                            <span>· 已播 {tr.play_count} 次</span>
                            {isResumeTrack && (
                              <span className="rounded bg-white px-1.5 py-0.5 font-semibold text-[var(--brand-primary)]">
                                上次听到 {savedPos > 2 ? fmtDur(savedPos) : "本集"}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-1.5">
                        <button
                          onClick={() => handlePlaySeason(activeSeries, activeSeason, idx, isResumeTrack)}
                          className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-green-soft)] px-3 py-1.5 text-xs font-bold text-[var(--brand-primary)] hover:bg-[var(--brand-primary)] hover:text-white transition"
                        >
                          <Play className="h-3.5 w-3.5" /> {isResumeTrack && savedPos > 2 ? "续播" : "播放"}
                        </button>
                        <button
                          onClick={() =>
                            setPushTarget({
                              label: `${activeSeries.title} · ${activeSeason.season_label} 第${tr.episode_num}${meta.trackNoun}`,
                              subtitle: `从《${tr.title}》开始顺序连播`,
                              albumId: activeSeason.id,
                              seriesId: activeSeries.id,
                              startIndex: idx,
                              startPositionSec: isResumeTrack ? savedPos : 0,
                              defaultResume: false,
                            })
                          }
                          className="rounded-xl border border-[var(--border-soft)] bg-white p-2 text-zinc-600 hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)]"
                          title="从本集推送音箱"
                        >
                          <Speaker className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => {
                            setEditingTrack(tr);
                            setTrTitle(tr.title);
                            setTrEpNum(tr.episode_num);
                            setTrAlbumId(tr.album_id);
                          }}
                          className="rounded-xl border border-[var(--border-soft)] bg-white p-2 text-zinc-500 hover:bg-zinc-50"
                          title="改标题 / 集号 / 移动季"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={async () => {
                            if (!window.confirm(`确定删除《${tr.title}》吗？`)) return;
                            await api.deleteTrack(tr.id);
                            showToast("已删除单集");
                            await loadSeries();
                          }}
                          className="rounded-xl border border-[var(--border-soft)] bg-white p-2 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                          title="删除"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        ) : null}

        {/* 新增二级季弹窗 */}
        <Modal open={seasonModalOpen} title={`新增${meta.seasonNoun}`} onClose={() => setSeasonModalOpen(false)} maxWidth="max-w-md">
          <form onSubmit={handleCreateSeason} className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block font-bold">序号（用于跨季连播与语音跳季）</label>
                <input
                  type="number"
                  min={1}
                  value={newSeasonNum}
                  onChange={(e) => {
                    const n = Math.max(1, Number(e.target.value));
                    setNewSeasonNum(n);
                    setNewSeasonLabel(channel === "music" ? `专辑 ${n}` : `第${n}${meta.seasonNoun}`);
                  }}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                />
              </div>
              <div>
                <label className="mb-1 block font-bold">显示名称</label>
                <input
                  value={newSeasonLabel}
                  onChange={(e) => setNewSeasonLabel(e.target.value)}
                  placeholder={meta.placeholderSeason}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block font-bold">简介（可选）</label>
              <input
                value={newSeasonDesc}
                onChange={(e) => setNewSeasonDesc(e.target.value)}
                placeholder="一句话备注这一季的内容"
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setSeasonModalOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
                取消
              </button>
              <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white">
                确认新增
              </button>
            </div>
          </form>
        </Modal>

        {/* 往当前季添加内容（4 合 1 就地采集弹窗） */}
        <Modal
          open={ingestOpen}
          title={`往「${activeSeries.title} · ${activeSeason?.season_label || ""}」添加音频`}
          onClose={() => setIngestOpen(false)}
          maxWidth="max-w-2xl"
        >
          <div className="space-y-4 text-xs">
            <div className="flex flex-wrap gap-1.5 border-b border-[var(--border-soft)] pb-3">
              {[
                { id: "search", label: "🔍 全网搜集下载", icon: <Search className="h-3.5 w-3.5" /> },
                { id: "url", label: "🔗 粘贴链接抓取", icon: <Link2 className="h-3.5 w-3.5" /> },
                { id: "upload", label: "📤 批量上传音频", icon: <Upload className="h-3.5 w-3.5" /> },
                { id: "text", label: "🗣️ 文本合成朗读", icon: <Mic className="h-3.5 w-3.5" /> },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setIngestTab(t.id as typeof ingestTab)}
                  className={`inline-flex items-center gap-1 rounded-xl px-3.5 py-2 font-bold transition ${
                    ingestTab === t.id
                      ? "bg-[var(--brand-primary)] text-white"
                      : "bg-[var(--bg-subtle)] text-[var(--ink-secondary)] hover:bg-zinc-200/70"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {ingestTab === "search" && (
              <div className="space-y-3">
                <div className="flex gap-2">
                  <input
                    value={onlineQ}
                    onChange={(e) => setOnlineQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && void handleSearchOnlineForSeason()}
                    placeholder="输入关键词搜集，如：汪汪队第2季 故事"
                    className="flex-1 rounded-xl border border-[var(--border-soft)] px-3 py-2"
                  />
                  <button
                    type="button"
                    disabled={onlineSearching}
                    onClick={() => void handleSearchOnlineForSeason()}
                    className="rounded-xl bg-zinc-900 px-4 py-2 font-bold text-white disabled:opacity-50"
                  >
                    {onlineSearching ? "搜索中..." : "搜索"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setIngestOpen(false);
                      openAiCollect(activeSeries, activeSeason);
                    }}
                    className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-primary)] px-3.5 py-2 font-bold text-white"
                  >
                    <Sparkles className="h-3.5 w-3.5" /> AI 批量采到本季
                  </button>
                </div>

                {onlineResults.length > 0 && (
                  <div className="max-h-72 space-y-1.5 overflow-y-auto">
                    {onlineResults.map((item, idx) => (
                      <div key={idx} className="flex items-center justify-between gap-2 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/50 p-2.5">
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-bold">{item.title}</div>
                          <div className="text-[11px] text-[var(--ink-muted)]">
                            {item.uploader || "全网音频"} · {fmtDur(item.duration_sec)}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => void handleCollectSingleOnlineUrl(item.url, item.title)}
                          className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[var(--brand-primary)] px-3 py-1.5 font-bold text-white"
                        >
                          <Download className="h-3 w-3" /> 下载入本季
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {ingestTab === "url" && (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!activeSeason || !ytUrl.trim()) return;
                  try {
                    await api.collectYtdlp(ytUrl.trim(), activeSeason.id, ytMax);
                    showToast("已提交链接抓取任务，完成后会自动归入本季");
                    setYtUrl("");
                    setIngestOpen(false);
                  } catch (err) {
                    showToast((err as Error).message);
                  }
                }}
                className="space-y-3"
              >
                <div>
                  <label className="mb-1 block font-bold">视频 / 合集 / 音频直链（支持 B站、YouTube 等）</label>
                  <input
                    value={ytUrl}
                    onChange={(e) => setYtUrl(e.target.value)}
                    placeholder="https://..."
                    className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                    required
                  />
                </div>
                <div className="flex items-center gap-3">
                  <label className="font-bold">合集最多抓取集数：</label>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={ytMax}
                    onChange={(e) => setYtMax(Number(e.target.value))}
                    className="w-24 rounded-xl border border-[var(--border-soft)] px-3 py-1.5"
                  />
                </div>
                <div className="flex justify-end">
                  <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white">
                    开始抓取入本季
                  </button>
                </div>
              </form>
            )}

            {ingestTab === "upload" && (
              <form onSubmit={handleBatchUpload} className="space-y-3">
                <div className="rounded-2xl border-2 border-dashed border-[var(--border-soft)] p-6 text-center">
                  <input
                    type="file"
                    accept="audio/*,.mp3,.m4a,.wav,.flac,.ogg,.opus"
                    multiple
                    onChange={(e) => setUploadFiles(Array.from(e.target.files || []))}
                    className="mx-auto block text-xs"
                  />
                  <p className="mt-2 text-[11px] text-[var(--ink-muted)]">
                    支持一次多选多个 MP3 / M4A / FLAC / WAV 文件，自动进行 -16 LUFS 护耳音量校准
                  </p>
                  {uploadFiles.length > 0 && (
                    <div className="mt-2 font-bold text-[var(--brand-primary)]">已选择 {uploadFiles.length} 个音频文件</div>
                  )}
                </div>
                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={uploading || uploadFiles.length === 0}
                    className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white disabled:opacity-40"
                  >
                    {uploading ? "上传转码中..." : `开始上传（${uploadFiles.length} 个文件）`}
                  </button>
                </div>
              </form>
            )}

            {ingestTab === "text" && (
              <form onSubmit={handleAddTextTrack} className="space-y-3">
                <div>
                  <label className="mb-1 block font-bold">单集标题</label>
                  <input
                    value={ttsTitle}
                    onChange={(e) => setTtsTitle(e.target.value)}
                    placeholder="如：第1集 莱德队长出发救援"
                    className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                    required
                  />
                </div>
                <div>
                  <label className="mb-1 block font-bold">故事正文 / 讲稿（自动合成护耳人声）</label>
                  <textarea
                    rows={5}
                    value={ttsBody}
                    onChange={(e) => setTtsBody(e.target.value)}
                    placeholder="粘贴故事全文，系统会自动合成温柔人声并加入本季..."
                    className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                    required
                  />
                </div>
                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={ttsBusy}
                    className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white disabled:opacity-40"
                  >
                    {ttsBusy ? "正在合成音频..." : "合成人声并加入本季"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </Modal>

        {/* 编辑单集弹窗（改名 / 集号 / 移动到其他季） */}
        <Modal open={Boolean(editingTrack)} title="编辑单集信息" onClose={() => setEditingTrack(null)} maxWidth="max-w-md">
          <form onSubmit={handleSaveTrackEdit} className="space-y-3 text-xs">
            <div>
              <label className="mb-1 block font-bold">单集标题</label>
              <input
                value={trTitle}
                onChange={(e) => setTrTitle(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block font-bold">第几{meta.trackNoun}（语音跳集用）</label>
                <input
                  type="number"
                  min={1}
                  value={trEpNum}
                  onChange={(e) => setTrEpNum(Math.max(1, Number(e.target.value)))}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                />
              </div>
              <div>
                <label className="mb-1 block font-bold">所属{meta.seasonNoun}</label>
                <select
                  value={trAlbumId}
                  onChange={(e) => setTrAlbumId(Number(e.target.value))}
                  className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
                >
                  {seasons.map((sea) => (
                    <option key={sea.id} value={sea.id}>
                      {sea.season_label || `第${sea.season_num}${meta.seasonNoun}`}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setEditingTrack(null)} className="rounded-xl border px-4 py-2 font-semibold">
                取消
              </button>
              <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white">
                保存修改
              </button>
            </div>
          </form>
        </Modal>

        <QuickPushModal
          target={pushTarget}
          devices={dashboard.devices}
          onClose={() => setPushTarget(null)}
          onSuccess={onRefreshDashboard}
          showToast={showToast}
        />

        {/* 编辑系列弹窗 */}
        <Modal
          open={seriesModalOpen}
          title={editingSeries ? `编辑${meta.seriesNoun}` : `新建${meta.seriesNoun}`}
          onClose={() => setSeriesModalOpen(false)}
          maxWidth="max-w-md"
        >
          <form onSubmit={handleSaveSeries} className="space-y-3 text-xs">
            <div className="grid grid-cols-4 gap-2">
              <div>
                <label className="mb-1 block font-bold">图标</label>
                <input
                  value={sEmoji}
                  onChange={(e) => setSEmoji(e.target.value)}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-center text-base"
                />
              </div>
              <div className="col-span-3">
                <label className="mb-1 block font-bold">名称</label>
                <input
                  value={sTitle}
                  onChange={(e) => setSTitle(e.target.value)}
                  placeholder={meta.placeholderSeries}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                  required
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block font-bold">作者 / 歌手（可选）</label>
              <input
                value={sAuthor}
                onChange={(e) => setSAuthor(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              />
            </div>
            <div>
              <label className="mb-1 block font-bold">简介（可选）</label>
              <input
                value={sDesc}
                onChange={(e) => setSDesc(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setSeriesModalOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
                取消
              </button>
              <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white">
                保存
              </button>
            </div>
          </form>
        </Modal>

        {/* AI 全网采集弹窗 */}
        <Modal open={aiModalOpen} title="✨ AI 全网采集并自动分类" onClose={() => setAiModalOpen(false)} maxWidth="max-w-md">
          <form onSubmit={handleStartAiCollect} className="space-y-3.5 text-xs">
            <div className="rounded-xl bg-[var(--brand-green-soft)] p-3 text-[var(--brand-primary)] leading-relaxed">
              只需输入名称（如「汪汪队第2季」），系统自动全网采集音频并按「一级合集 → 二级季 → 三级集」归类，完成后会在网页和音箱语音通知你！
            </div>
            <div>
              <label className="mb-1 block font-bold">想采集什么内容？</label>
              <input
                value={aiQuery}
                onChange={(e) => setAiQuery(e.target.value)}
                placeholder={meta.placeholderCollect}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block font-bold">采集数量（集/首）</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={aiMaxItems}
                  onChange={(e) => setAiMaxItems(Math.max(1, Math.min(20, Number(e.target.value))))}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                />
              </div>
              <div>
                <label className="mb-1 block font-bold">完成后播报通知音箱</label>
                <select
                  value={aiDeviceId}
                  onChange={(e) => setAiDeviceId(e.target.value)}
                  className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
                >
                  <option value="">仅在网页提示</option>
                  {dashboard.devices.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.room} · {d.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setAiModalOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
                取消
              </button>
              <button
                type="submit"
                disabled={aiBusy}
                className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white disabled:opacity-50"
              >
                <Sparkles className="h-3.5 w-3.5" /> {aiBusy ? "启动中..." : "立即采集并自动分类"}
              </button>
            </div>
          </form>
        </Modal>
      </div>
    );
  }

  // ---------------- 一级视图：清晰的合集卡片网格 ----------------
  return (
    <div className="space-y-5">
      {/* 顶部标题与直白操作栏 */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight">{meta.title}</h2>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">{meta.subtitle}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {channel === "music" && (
            <button
              onClick={() => setMusicView("cloud")}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-primary)] bg-[var(--brand-green-soft)] px-4 py-2 text-xs font-bold text-[var(--brand-primary)] hover:bg-[var(--brand-primary)] hover:text-white transition"
            >
              <Disc3 className="h-3.5 w-3.5" /> 🌐 全网搜歌与批量下歌
            </button>
          )}
          {channel === "podcast" && (
            <button
              onClick={() => void loadRssModalData()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-primary)] bg-[var(--brand-green-soft)] px-4 py-2 text-xs font-bold text-[var(--brand-primary)]"
            >
              <Radio className="h-3.5 w-3.5" /> 订阅 RSS 播客
            </button>
          )}
          <button
            onClick={() => openAiCollect(null, null)}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-4 py-2 text-xs font-bold text-white shadow-xs"
          >
            <Sparkles className="h-3.5 w-3.5" /> AI 全网采集
          </button>
          <button
            onClick={openCreateSeries}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-4 py-2 text-xs font-bold text-[var(--ink-primary)] hover:bg-[var(--bg-subtle)]"
          >
            <FolderPlus className="h-3.5 w-3.5" /> 新建{meta.seriesNoun}
          </button>
        </div>
      </div>

      {/* 搜索条 + 语音快捷提示 */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="pointer-events-none absolute left-3.5 top-2.5 h-4 w-4 text-[var(--ink-muted)]" />
          <input
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder={`搜索${meta.seriesNoun}、${meta.seasonNoun}或单集标题...`}
            className="w-full rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-card)] py-2 pl-10 pr-4 text-xs"
          />
        </div>
        <button
          onClick={() => void loadSeries()}
          className="inline-flex items-center gap-1 rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3.5 py-2 text-xs font-semibold text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> 刷新
        </button>
      </div>

      {/* 系列合集卡片网格 */}
      {seriesList.length === 0 ? (
        <EmptyState
          icon={channel === "music" ? Disc3 : channel === "podcast" ? Radio : FolderPlus}
          title={meta.emptyTitle}
          description={meta.emptyDesc}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <button
                onClick={() => openAiCollect(null, null)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-5 py-2.5 text-xs font-bold text-white"
              >
                <Sparkles className="h-3.5 w-3.5" /> AI 全网采集并自动分类
              </button>
              <button
                onClick={openCreateSeries}
                className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-white px-5 py-2.5 text-xs font-bold"
              >
                <Plus className="h-3.5 w-3.5" /> 手动新建{meta.seriesNoun}
              </button>
            </div>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {seriesList.map((series) => {
            const resume = series.resume_info;
            return (
              <div
                key={series.id}
                className="card-pro group flex flex-col justify-between p-5 transition hover:border-[var(--brand-primary)]/50 hover:shadow-md"
              >
                <div
                  onClick={() => setSelectedSeriesId(series.id)}
                  className="cursor-pointer space-y-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[var(--brand-green-soft)] text-2xl">
                        {series.cover_emoji || meta.defaultEmoji}
                      </div>
                      <div className="min-w-0">
                        <h3 className="truncate text-base font-extrabold group-hover:text-[var(--brand-primary)] transition">
                          {series.title}
                        </h3>
                        <div className="mt-0.5 text-xs text-[var(--ink-muted)]">
                          {series.season_count} {meta.seasonNoun} · 共 {series.total_tracks} {meta.trackNoun}
                        </div>
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-[var(--ink-muted)] group-hover:translate-x-0.5 group-hover:text-[var(--brand-primary)] transition" />
                  </div>

                  {/* 季标签预览 */}
                  {series.seasons.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {series.seasons.slice(0, 4).map((sea) => (
                        <span
                          key={sea.id}
                          className="rounded-lg bg-[var(--bg-subtle)] px-2 py-0.5 text-[11px] font-medium text-[var(--ink-secondary)]"
                        >
                          {sea.season_label || `第${sea.season_num}${meta.seasonNoun}`} ({sea.tracks?.length || 0})
                        </span>
                      ))}
                      {series.seasons.length > 4 && (
                        <span className="rounded-lg bg-[var(--bg-subtle)] px-2 py-0.5 text-[11px] text-[var(--ink-muted)]">
                          +{series.seasons.length - 4}
                        </span>
                      )}
                    </div>
                  )}

                  {/* 断点续播状态行 */}
                  <div
                    className={`rounded-xl px-3 py-2 text-[11px] ${
                      resume
                        ? "bg-[var(--brand-green-soft)] font-semibold text-[var(--brand-primary)]"
                        : "bg-[var(--bg-subtle)] text-[var(--ink-muted)]"
                    }`}
                  >
                    {resume ? (
                      <div className="flex items-center gap-1.5 truncate">
                        <Clock className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">
                          上次听到：{resume.season_label} 第{resume.episode_num}{meta.trackNoun}
                          {resume.position_sec > 2 ? ` · ${fmtDur(resume.position_sec)}` : ""}
                        </span>
                      </div>
                    ) : (
                      <span>尚未开始 · 点击续播将从第1{meta.seasonNoun}第1{meta.trackNoun}顺序播放</span>
                    )}
                  </div>
                </div>

                {/* 底部直白双按钮 */}
                <div className="mt-4 flex items-center gap-2 border-t border-[var(--border-soft)] pt-3">
                  <button
                    onClick={() => handleResumeSeriesInBrowser(series)}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-[var(--brand-primary)] py-2 text-xs font-bold text-white shadow-xs hover:opacity-95"
                  >
                    <Play className="h-3.5 w-3.5" /> {resume ? "继续播放" : "开始播放"}
                  </button>
                  <button
                    onClick={() =>
                      setPushTarget({
                        label: series.title,
                        subtitle: resume
                          ? `将从 ${resume.season_label} 第${resume.episode_num}${meta.trackNoun} 续播并自动跨${meta.seasonNoun}连播`
                          : `从第1${meta.seasonNoun}第1${meta.trackNoun}起在音箱顺序连播`,
                        seriesId: series.id,
                        defaultResume: true,
                      })
                    }
                    disabled={series.total_tracks === 0}
                    className="inline-flex items-center gap-1 rounded-xl border border-[var(--border-soft)] bg-white px-3.5 py-2 text-xs font-bold text-[var(--ink-primary)] hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)] disabled:opacity-40"
                  >
                    <Speaker className="h-3.5 w-3.5" /> 推音箱
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 新建合集弹窗 */}
      <Modal
        open={seriesModalOpen}
        title={editingSeries ? `编辑${meta.seriesNoun}` : `新建${meta.seriesNoun}`}
        onClose={() => setSeriesModalOpen(false)}
        maxWidth="max-w-md"
      >
        <form onSubmit={handleSaveSeries} className="space-y-3 text-xs">
          <div className="grid grid-cols-4 gap-2">
            <div>
              <label className="mb-1 block font-bold">图标</label>
              <input
                value={sEmoji}
                onChange={(e) => setSEmoji(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-center text-base"
              />
            </div>
            <div className="col-span-3">
              <label className="mb-1 block font-bold">一级合集名称</label>
              <input
                value={sTitle}
                onChange={(e) => setSTitle(e.target.value)}
                placeholder={meta.placeholderSeries}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                required
              />
            </div>
          </div>
          {!editingSeries && (
            <div>
              <label className="mb-1 block font-bold">默认首个二级{meta.seasonNoun}名</label>
              <input
                value={sFirstSeason}
                onChange={(e) => setSFirstSeason(e.target.value)}
                placeholder={meta.placeholderSeason}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block font-bold">作者 / 歌手（可选）</label>
            <input
              value={sAuthor}
              onChange={(e) => setSAuthor(e.target.value)}
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={() => setSeriesModalOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
              取消
            </button>
            <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white">
              创建并进入管理
            </button>
          </div>
        </form>
      </Modal>

      {/* AI 全网采集弹窗 */}
      <Modal open={aiModalOpen} title="✨ AI 全网采集并自动分类" onClose={() => setAiModalOpen(false)} maxWidth="max-w-md">
        <form onSubmit={handleStartAiCollect} className="space-y-3.5 text-xs">
          <div className="rounded-xl bg-[var(--brand-green-soft)] p-3 text-[var(--brand-primary)] leading-relaxed">
            输入你想听的故事、歌手或播客（如「汪汪队第2季」），系统会自动上网采集并由 AI 按「一级合集 → 二级季 → 三级集」归类，完成后会在网页和音箱语音通知你！
          </div>
          <div>
            <label className="mb-1 block font-bold">想采集什么内容？</label>
            <input
              value={aiQuery}
              onChange={(e) => setAiQuery(e.target.value)}
              placeholder={meta.placeholderCollect}
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block font-bold">采集数量（集/首）</label>
              <input
                type="number"
                min={1}
                max={20}
                value={aiMaxItems}
                onChange={(e) => setAiMaxItems(Math.max(1, Math.min(20, Number(e.target.value))))}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              />
            </div>
            <div>
              <label className="mb-1 block font-bold">完成后播报通知音箱</label>
              <select
                value={aiDeviceId}
                onChange={(e) => setAiDeviceId(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
              >
                <option value="">仅在网页提示</option>
                {dashboard.devices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.room} · {d.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={() => setAiModalOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
              取消
            </button>
            <button
              type="submit"
              disabled={aiBusy}
              className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" /> {aiBusy ? "启动中..." : "立即采集并自动分类"}
            </button>
          </div>
        </form>
      </Modal>

      {/* 播客 RSS 订阅弹窗 */}
      <Modal open={rssOpen} title="📡 订阅 RSS 播客频道" onClose={() => setRssOpen(false)} maxWidth="max-w-xl">
        <div className="space-y-4 text-xs">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleCreateRssSource(rssName, rssUrl);
            }}
            className="grid gap-2 sm:grid-cols-5"
          >
            <input
              value={rssName}
              onChange={(e) => setRssName(e.target.value)}
              placeholder="播客频道名"
              className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-2"
              required
            />
            <input
              value={rssUrl}
              onChange={(e) => setRssUrl(e.target.value)}
              placeholder="RSS 订阅地址 https://..."
              className="rounded-xl border border-[var(--border-soft)] px-3 py-2 sm:col-span-2"
              required
            />
            <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-3 py-2 font-bold text-white">
              添加订阅
            </button>
          </form>

          {rssPresets.length > 0 && (
            <div>
              <div className="mb-1.5 font-bold text-[var(--ink-secondary)]">精选播客一键订阅</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {rssPresets.map((p, i) => (
                  <div key={i} className="flex items-center justify-between gap-2 rounded-xl border border-[var(--border-soft)] p-2.5">
                    <div className="min-w-0">
                      <div className="truncate font-bold">{p.name}</div>
                      <div className="truncate text-[11px] text-[var(--ink-muted)]">{p.description}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleCreateRssSource(p.name, p.url)}
                      className="shrink-0 rounded-lg bg-[var(--brand-green-soft)] px-2.5 py-1 font-bold text-[var(--brand-primary)]"
                    >
                      订阅
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {rssSources.length > 0 && (
            <div>
              <div className="mb-1.5 font-bold text-[var(--ink-secondary)]">已订阅源（{rssSources.length}）</div>
              <div className="max-h-52 space-y-1.5 overflow-y-auto">
                {rssSources.map((src) => (
                  <div key={src.id} className="flex items-center justify-between gap-2 rounded-xl bg-[var(--bg-subtle)] px-3 py-2">
                    <div className="min-w-0">
                      <div className="truncate font-bold">{src.name}</div>
                      <div className="truncate text-[11px] text-[var(--ink-muted)]">{src.last_status}</div>
                    </div>
                    <div className="flex shrink-0 gap-1.5">
                      <button
                        type="button"
                        onClick={async () => {
                          await api.syncSource(src.id);
                          showToast(`正在同步「${src.name}」最新期...`);
                        }}
                        className="rounded-lg bg-white px-2.5 py-1 font-bold text-[var(--brand-primary)] shadow-2xs"
                      >
                        立即同步
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          await api.deleteSource(src.id);
                          setRssSources((p) => p.filter((x) => x.id !== src.id));
                        }}
                        className="rounded-lg bg-white px-2 py-1 text-rose-600 shadow-2xs"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Modal>

      <QuickPushModal
        target={pushTarget}
        devices={dashboard.devices}
        onClose={() => setPushTarget(null)}
        onSuccess={onRefreshDashboard}
        showToast={showToast}
      />
    </div>
  );
}
