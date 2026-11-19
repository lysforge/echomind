import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpenCheck,
  BookText,
  CheckCircle2,
  Disc3,
  Globe,
  Headphones,
  MessageSquareHeart,
  Moon,
  Play,
  Radio,
  Search,
  Sparkles,
  Speaker,
  Volume2,
  Wrench,
} from "lucide-react";
import { api, CategoryTag, DashboardData, MediaAlbum, MediaTrack } from "../api";
import { AGE_STAGE_LABELS, EmptyState, Modal } from "../components/Modal";
import { QueueItem } from "../components/PlayerBar";

const CHANNELS: Array<{ id: "all" | MediaAlbum["category"]; label: string; emoji: string }> = [
  { id: "all", label: "全部频道", emoji: "✨" },
  { id: "music", label: "音乐与儿歌", emoji: "🎵" },
  { id: "story", label: "绘本与故事", emoji: "📖" },
  { id: "english", label: "英语伴学课", emoji: "🎓" },
  { id: "podcast", label: "科普与播客", emoji: "🎙️" },
];

const COVER_THEME: Record<MediaAlbum["category"], string> = {
  music: "from-orange-500 to-rose-500",
  story: "from-amber-500 to-orange-600",
  english: "from-sky-600 to-indigo-700",
  podcast: "from-violet-600 to-purple-700",
};

const CHANNEL_DEFAULT_EMOJI: Record<MediaAlbum["category"], string> = {
  music: "🎵",
  story: "📖",
  english: "🎓",
  podcast: "🎙️",
};

export function ExplorePage({
  dashboard,
  isAdmin,
  currentQueueItem,
  isPlaying,
  onPlayQueue,
  onPlayUrl,
  onRefreshDashboard,
  onOpenStudioAlbum,
  onOpenVoiceDrawer,
  showToast,
}: {
  dashboard: DashboardData;
  isAdmin: boolean;
  currentQueueItem?: QueueItem | null;
  isPlaying?: boolean;
  onPlayQueue: (items: QueueItem[], startIndex: number) => void;
  onPlayUrl: (url: string) => void;
  onRefreshDashboard: () => void;
  onOpenStudioAlbum?: (albumId: number) => void;
  onOpenVoiceDrawer: () => void;
  showToast: (m: string) => void;
}) {
  const [albums, setAlbums] = useState<MediaAlbum[]>([]);
  const [tags, setTags] = useState<CategoryTag[]>([]);
  const [loading, setLoading] = useState(true);

  // 成员视角与频道过滤
  const [memberViewId, setMemberViewId] = useState<number | "all">("all");
  const [channel, setChannel] = useState<"all" | MediaAlbum["category"]>("all");
  const [subTag, setSubTag] = useState<string>("all");
  const [stageFilter, setStageFilter] = useState<string>("all");
  const [q, setQ] = useState("");

  // 沉浸式专辑详情页
  const [activeAlbId, setActiveAlbId] = useState<number | null>(null);
  const [expandedTrackId, setExpandedTrackId] = useState<number | null>(null);

  // 推送音箱弹窗
  const [pushModalOpen, setPushModalOpen] = useState(false);
  const [pushAlbum, setPushAlbum] = useState<MediaAlbum | null>(null);
  const [pushStartIndex, setPushStartIndex] = useState(0);
  const [selectedDevIds, setSelectedDevIds] = useState<string[]>([]);
  const [pushLoopMode, setPushLoopMode] = useState<"sequential" | "repeat_one" | "shuffle">("sequential");
  const [sleepOption, setSleepOption] = useState<"none" | "ep1" | "ep2" | "min20" | "min40">("none");
  const [pushing, setPushing] = useState(false);

  // 全网搜歌即点即播弹窗
  const [searchOpen, setSearchOpen] = useState(false);
  const [onlineQ, setOnlineQ] = useState("");
  const [onlineResults, setOnlineResults] = useState<Array<{ title: string; duration_sec: number; uploader: string; url: string }>>([]);
  const [searchingOnline, setSearchingOnline] = useState(false);

  const selectedMember = dashboard.members.find((m) => m.id === memberViewId) || null;
  const activeAlb = albums.find((a) => a.id === activeAlbId) || null;

  const loadContent = async () => {
    setLoading(true);
    try {
      const [albList, tagList] = await Promise.all([
        api.getAlbums({
          category: channel === "all" ? undefined : channel,
          sub_tag: subTag === "all" ? undefined : subTag,
          age_stage: stageFilter === "all" ? undefined : stageFilter,
          q: q.trim() || undefined,
          exclude_inbox: true,
        }),
        api.listTags(channel === "all" ? undefined : channel),
      ]);
      setAlbums(albList);
      setTags(tagList);
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadContent();
  }, [channel, subTag, stageFilter]);

  useEffect(() => {
    if (selectedDevIds.length === 0 && dashboard.devices.length > 0) {
      const firstOnline = dashboard.devices.find((d) => d.online === 1) || dashboard.devices[0];
      setSelectedDevIds([firstOnline.id]);
    }
  }, [dashboard.devices]);

  // 按当前成员适龄阶段优先排序展示
  const sortedAlbums = useMemo(() => {
    if (!selectedMember) return albums;
    const targetStage = selectedMember.age_stage;
    return [...albums].sort((a, b) => {
      const sa = a.age_stage === targetStage ? 0 : a.age_stage === "S6_ALL" ? 1 : 2;
      const sb = b.age_stage === targetStage ? 0 : b.age_stage === "S6_ALL" ? 1 : 2;
      return sa - sb;
    });
  }, [albums, selectedMember]);

  const continueAlbums = useMemo(
    () =>
      sortedAlbums
        .filter((a) => a.last_track_id && (a.tracks || []).length > 0)
        .slice(0, 4),
    [sortedAlbums]
  );

  const channelTags = useMemo(() => {
    if (channel === "all") return [];
    return tags.filter((t) => t.channel === channel);
  }, [tags, channel]);

  const toQueue = (alb: MediaAlbum): QueueItem[] =>
    (alb.tracks || []).map((t) => ({
      id: t.id,
      kind: "track",
      title: t.title,
      subtitle: alb.title,
      streamUrl: t.stream_url || `/api/media/tracks/${t.id}/stream`,
      parentId: alb.id,
      durationSec: t.duration_sec || 0,
    }));

  const openPushDialog = (alb: MediaAlbum, startIdx = 0) => {
    if (dashboard.devices.length === 0) {
      showToast("暂未绑定智能音箱，已改用本机浏览器播放器，也可在管理后台绑定音箱。");
      onPlayQueue(toQueue(alb), startIdx);
      return;
    }
    setPushAlbum(alb);
    setPushStartIndex(startIdx);
    setPushLoopMode(alb.play_mode || "sequential");
    setSleepOption("none");
    setPushModalOpen(true);
  };

  const handleConfirmPush = async () => {
    if (!pushAlbum || selectedDevIds.length === 0) return;
    setPushing(true);
    try {
      let sleepMinutes: number | null = null;
      let sleepEpisodes: number | null = null;
      if (sleepOption === "ep1") sleepEpisodes = 1;
      if (sleepOption === "ep2") sleepEpisodes = 2;
      if (sleepOption === "min20") sleepMinutes = 20;
      if (sleepOption === "min40") sleepMinutes = 40;

      await api.pushPlayback({
        device_ids: selectedDevIds,
        album_id: pushAlbum.id,
        start_index: pushStartIndex,
        loop_mode: pushLoopMode,
        sleep_minutes: sleepMinutes,
        sleep_episodes: sleepEpisodes,
      });
      setPushModalOpen(false);
      showToast(`已将《${pushAlbum.title}》连播队列推送至 ${selectedDevIds.length} 台音箱`);
      onRefreshDashboard();
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setPushing(false);
    }
  };

  const handleOnlineSearch = async () => {
    if (!onlineQ.trim()) return;
    setSearchingOnline(true);
    try {
      setOnlineResults(await api.searchOnline(onlineQ));
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setSearchingOnline(false);
    }
  };

  const handlePlayOnlineResult = async (title: string, url: string) => {
    try {
      showToast(`正在连接《${title}》…`);
      const res = await api.playAndCache({ title, url, category: "music" });
      onPlayQueue(
        [
          {
            id: res.track.id || 0,
            kind: res.is_cached && res.track.id > 0 ? "track" : "online",
            title: res.track.title || title,
            subtitle: res.is_cached ? "本地曲库命中" : "在线播放 · 已自动缓存到本地",
            streamUrl: res.stream_url,
            parentId: res.track.album_id || 0,
            durationSec: res.track.duration_sec || 0,
          },
        ],
        0
      );
      setSearchOpen(false);
      showToast(res.is_cached ? `本地已收录《${title}》，直接播放` : `已开始在线播放《${title}》，同时后台自动存入缓存池`);
    } catch (err) {
      showToast((err as Error).message);
    }
  };

  // ===================== 二级详情页：沉浸式专辑播放与伴读 =====================
  if (activeAlb) {
    const tracks = activeAlb.tracks || [];
    const resumeIdx = Math.max(0, tracks.findIndex((t) => t.id === activeAlb.last_track_id));

    return (
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button
            onClick={() => {
              setActiveAlbId(null);
              setExpandedTrackId(null);
            }}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-white px-3.5 py-2 text-xs font-semibold hover:bg-zinc-50"
          >
            <ArrowLeft className="h-4 w-4" /> 返回内容广场
          </button>

          {isAdmin && onOpenStudioAlbum && (
            <button
              onClick={() => onOpenStudioAlbum(activeAlb.id)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-white px-3.5 py-2 text-xs font-medium text-zinc-600 hover:bg-zinc-50"
            >
              <Wrench className="h-3.5 w-3.5" /> 去管理后台维护此专辑
            </button>
          )}
        </div>

        {/* 沉浸式专辑头 */}
        <section className="card-pro flex flex-col gap-5 p-6 sm:flex-row sm:items-center">
          <div
            className={`flex h-28 w-28 shrink-0 items-center justify-center rounded-3xl bg-gradient-to-br ${COVER_THEME[activeAlb.category]} text-4xl text-white shadow-md`}
          >
            {activeAlb.cover_emoji || CHANNEL_DEFAULT_EMOJI[activeAlb.category]}
          </div>

          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-md bg-[var(--brand-green-soft)] px-2.5 py-0.5 text-xs font-semibold text-[var(--brand-green)]">
                {CHANNELS.find((c) => c.id === activeAlb.category)?.label}
              </span>
              {activeAlb.sub_tag && (
                <span className="rounded-md bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                  #{activeAlb.sub_tag}
                </span>
              )}
              <span className="rounded-md bg-zinc-100 px-2.5 py-0.5 text-xs text-zinc-700">
                {AGE_STAGE_LABELS[activeAlb.age_stage]}
              </span>
              {activeAlb.author && (
                <span className="text-xs text-[var(--ink-muted)]">· {activeAlb.author}</span>
              )}
            </div>

            <h2 className="text-2xl font-extrabold tracking-tight">{activeAlb.title}</h2>
            <p className="text-xs text-[var(--ink-muted)]">{activeAlb.description || "已经过 -16 LUFS 护耳响度标准化处理"}</p>

            <div className="flex flex-wrap items-center gap-2.5 pt-2">
              <button
                disabled={tracks.length === 0}
                onClick={() => onPlayQueue(toQueue(activeAlb), 0)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-5 py-2.5 text-xs font-semibold text-white hover:bg-[var(--brand-green-hover)] disabled:opacity-40"
              >
                <Play className="h-4 w-4 fill-current" /> 播放全部（{tracks.length} 集）
              </button>

              {tracks.length > 0 && activeAlb.last_track_id && (
                <button
                  onClick={() => onPlayQueue(toQueue(activeAlb), resumeIdx)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-green)] bg-[var(--brand-green-soft)] px-4 py-2.5 text-xs font-semibold text-[var(--brand-green)]"
                >
                  断点续播（第 {tracks[resumeIdx]?.episode_num || resumeIdx + 1} 集）
                </button>
              )}

              <button
                disabled={tracks.length === 0}
                onClick={() => openPushDialog(activeAlb, resumeIdx)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-amber)] px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-40"
              >
                <Speaker className="h-4 w-4" /> 推送到音箱连播
              </button>

              {activeAlb.category === "english" && (
                <button
                  onClick={onOpenVoiceDrawer}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-white px-3.5 py-2.5 text-xs font-medium hover:bg-zinc-50"
                >
                  <MessageSquareHeart className="h-4 w-4 text-[var(--brand-green)]" /> 口语互动练习
                </button>
              )}
            </div>
          </div>
        </section>

        {/* 自适应单集列表 */}
        <section className="card-pro overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--border-soft)] bg-zinc-50/70 px-5 py-3 text-xs font-bold">
            <span>专辑内容列表（{tracks.length} 集）</span>
            <span className="font-normal text-[var(--ink-muted)]">点击整行开始连播</span>
          </div>

          {tracks.length === 0 ? (
            <EmptyState
              icon={Headphones}
              title="这张专辑还没有填充音频内容"
              description={isAdmin ? "可点击右上角「去管理后台维护此专辑」，支持本地扫描、批量上传或文本一键合成有声内容。" : "请让家庭管理员在后台内容填充中心为此专辑添加单集。"}
            />
          ) : (
            <div className="divide-y divide-[var(--border-soft)]">
              {tracks.map((t: MediaTrack, idx: number) => {
                const isCurrent = currentQueueItem?.kind === "track" && currentQueueItem?.id === t.id;
                const hasExtra = Boolean((t.vocab && t.vocab.length > 0) || (t.text_content && t.text_content.trim()));
                const isExpanded = expandedTrackId === t.id;

                return (
                  <div key={t.id} className={isCurrent ? "bg-[var(--brand-green-soft)]/50" : ""}>
                    <div
                      onClick={() => onPlayQueue(toQueue(activeAlb), idx)}
                      className="flex cursor-pointer items-center justify-between gap-3 px-5 py-3.5 text-xs hover:bg-zinc-50/80"
                    >
                      <div className="flex min-w-0 flex-1 items-center gap-3">
                        <span
                          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold ${
                            isCurrent ? "bg-[var(--brand-green)] text-white" : "bg-zinc-100 text-zinc-600"
                          }`}
                        >
                          {isCurrent && isPlaying ? "♪" : t.episode_num}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className={`flex items-center gap-1.5 truncate text-sm font-semibold ${isCurrent ? "text-[var(--brand-green)]" : ""}`}>
                            <span className="truncate">{t.title}</span>
                            {t.completed === 1 && <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />}
                          </div>
                          <div className="mt-0.5 text-[11px] text-[var(--ink-muted)]">
                            {t.duration_sec > 0 ? `${Math.round(t.duration_sec)} 秒` : "即时按需合成"} · 已播 {t.play_count} 次
                            {t.objective ? ` · 目标：${t.objective}` : ""}
                          </div>
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                        {hasExtra && (
                          <button
                            onClick={() => setExpandedTrackId(isExpanded ? null : t.id)}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-[11px] font-medium hover:bg-zinc-100"
                          >
                            <BookText className="h-3.5 w-3.5 text-[var(--brand-green)]" />
                            {t.vocab && t.vocab.length > 0 ? (isExpanded ? "收起词卡" : "词卡与讲稿") : isExpanded ? "收起文稿" : "伴读原文"}
                          </button>
                        )}
                        {activeAlb.category === "english" && (
                          <button
                            onClick={async () => {
                              await api.updateTrack(t.id, { completed: t.completed !== 1 });
                              await loadContent();
                              showToast(t.completed === 1 ? "已取消掌握标记" : "太棒了！已标记掌握本课");
                            }}
                            className={`rounded-lg px-2.5 py-1.5 text-[11px] font-medium ${
                              t.completed === 1 ? "bg-emerald-100 text-emerald-800" : "border border-[var(--border-soft)] bg-white text-zinc-600 hover:bg-zinc-50"
                            }`}
                          >
                            <BookOpenCheck className="inline h-3.5 w-3.5 mr-1" />
                            {t.completed === 1 ? "已掌握" : "打卡"}
                          </button>
                        )}
                        <button
                          onClick={() => openPushDialog(activeAlb, idx)}
                          className="rounded-lg bg-[var(--brand-green-soft)] p-1.5 text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)]"
                          title="从本集起推给音箱"
                        >
                          <Speaker className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => onPlayQueue(toQueue(activeAlb), idx)}
                          className="rounded-lg bg-[var(--brand-green)] p-1.5 text-white"
                          title="立即播放"
                        >
                          <Play className="h-3.5 w-3.5 fill-current" />
                        </button>
                      </div>
                    </div>

                    {/* 展开的英语词卡与双语伴读文稿 */}
                    {isExpanded && hasExtra && (
                      <div className="space-y-3 border-t border-[var(--border-soft)] bg-zinc-50/80 px-5 py-4">
                        {t.vocab && t.vocab.length > 0 && (
                          <div>
                            <div className="mb-2 text-[11px] font-bold text-[var(--ink-muted)]">重点词卡（点击卡片即可纯音点读）</div>
                            <div className="grid gap-2.5 sm:grid-cols-3">
                              {t.vocab.map((v, vi) => (
                                <div
                                  key={vi}
                                  onClick={async () => {
                                    const r = await api.previewTTS("en-US-AriaNeural", "-5%", `${v.en}. ${v.example}`);
                                    onPlayUrl(r.tts_url);
                                  }}
                                  className="cursor-pointer rounded-xl border border-[var(--border-soft)] bg-white p-3 transition hover:border-[var(--brand-green)]"
                                >
                                  <div className="flex items-center justify-between">
                                    <span className="text-sm font-extrabold text-[var(--brand-green)]">{v.en}</span>
                                    <Volume2 className="h-3.5 w-3.5 text-[var(--brand-green)]" />
                                  </div>
                                  <div className="text-xs font-medium text-zinc-700">{v.zh}</div>
                                  <div className="mt-1 text-[11px] text-[var(--ink-muted)]">{v.example}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        {t.text_content && (
                          <div className="rounded-xl border border-[var(--border-soft)] bg-white p-3.5 text-xs leading-relaxed text-zinc-700">
                            {t.text_content}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* 推送音箱 Modal */}
        <PushSpeakerModal
          open={pushModalOpen}
          album={pushAlbum}
          startIndex={pushStartIndex}
          devices={dashboard.devices}
          selectedDevIds={selectedDevIds}
          setSelectedDevIds={setSelectedDevIds}
          loopMode={pushLoopMode}
          setLoopMode={setPushLoopMode}
          sleepOption={sleepOption}
          setSleepOption={setSleepOption}
          pushing={pushing}
          onClose={() => setPushModalOpen(false)}
          onConfirm={handleConfirmPush}
        />
      </div>
    );
  }

  // ===================== 一级广场视图（零后台干扰） =====================
  return (
    <div className="space-y-6">
      {/* 顶部栏：成员适龄视角 + 全网语音/搜歌入口 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight">家庭声音内容广场</h2>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
            {selectedMember
              ? `已按「${selectedMember.nickname} · ${selectedMember.age_label || AGE_STAGE_LABELS[selectedMember.age_stage]}」智能置顶适龄音乐、绘本与英语课程`
              : "集中浏览全家共享的音乐儿歌、绘本故事、分级英语与科普播客，点击专辑即可畅听与推送音箱"}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setSearchOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-accent)] bg-[var(--brand-accent-soft)] px-3.5 py-2 text-xs font-semibold text-[var(--brand-accent)] transition hover:opacity-90"
          >
            <Globe className="h-4 w-4 text-[var(--brand-accent)]" /> 全网点播搜歌 / 故事
          </button>
        </div>
      </div>

      {/* 成员适龄视角切换栏 */}
      {dashboard.members.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-[var(--ink-muted)]">当前收听视角：</span>
          <button
            onClick={() => setMemberViewId("all")}
            className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition ${
              memberViewId === "all"
                ? "bg-[var(--brand-primary)] text-white"
                : "border border-[var(--border-soft)] bg-white text-zinc-700 hover:bg-zinc-50"
            }`}
          >
            🏠 全家全龄
          </button>
          {dashboard.members.map((m) => (
            <button
              key={m.id}
              onClick={() => setMemberViewId(m.id)}
              className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition ${
                memberViewId === m.id
                  ? "bg-[var(--brand-green)] text-white"
                  : "border border-[var(--border-soft)] bg-white text-zinc-700 hover:bg-zinc-50"
              }`}
            >
              {m.role === "child" ? "🧒" : "👤"} {m.nickname}
              {m.age_label ? ` · ${m.age_label}` : ""}
            </button>
          ))}
        </div>
      )}

      {/* 最近收听 · 快捷续播 */}
      {continueAlbums.length > 0 && !q.trim() && channel === "all" && stageFilter === "all" && (
        <section className="space-y-2.5">
          <div className="text-xs font-bold text-zinc-700">⏯ 继续收听（上次收听进度）</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {continueAlbums.map((alb) => {
              const tracks = alb.tracks || [];
              const rIdx = Math.max(0, tracks.findIndex((t) => t.id === alb.last_track_id));
              const lastTr = tracks[rIdx];
              return (
                <div
                  key={`cont_${alb.id}`}
                  onClick={() => setActiveAlbId(alb.id)}
                  className="card-pro flex cursor-pointer items-center justify-between gap-3 p-3.5 transition hover:border-[var(--brand-green)]"
                >
                  <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${COVER_THEME[alb.category]} text-xl text-white`}>
                    {alb.cover_emoji || CHANNEL_DEFAULT_EMOJI[alb.category]}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-bold">{alb.title}</div>
                    <div className="truncate text-[11px] text-[var(--ink-muted)]">
                      续播：{lastTr?.title || "第1集"}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onPlayQueue(toQueue(alb), rIdx);
                    }}
                    className="shrink-0 rounded-full bg-[var(--brand-green-soft)] p-2 text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)]"
                    title="直接续播"
                  >
                    <Play className="h-3.5 w-3.5 fill-current" />
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 四大固定频道切换 + 搜索 & 年龄过滤 */}
      <div className="space-y-3 rounded-2xl border border-[var(--border-soft)] bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            {CHANNELS.map((c) => (
              <button
                key={c.id}
                onClick={() => {
                  setChannel(c.id);
                  setSubTag("all");
                }}
                className={`rounded-xl px-4 py-2 text-xs font-bold transition ${
                  channel === c.id
                    ? "bg-[var(--brand-green)] text-white shadow-xs"
                    : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200"
                }`}
              >
                {c.emoji} {c.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
              className="rounded-xl border border-[var(--border-soft)] bg-zinc-50 px-3 py-1.5 text-xs font-medium"
            >
              <option value="all">全部年龄段</option>
              {Object.entries(AGE_STAGE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>

            <div className="relative">
              <Search className="absolute left-3 top-2 h-3.5 w-3.5 text-zinc-400" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void loadContent()}
                placeholder="搜专辑、歌曲、故事…"
                className="rounded-xl border border-[var(--border-soft)] bg-zinc-50 py-1.5 pl-8 pr-3 text-xs"
              />
            </div>
            <button onClick={() => void loadContent()} className="rounded-xl border border-[var(--border-soft)] px-3 py-1.5 text-xs font-semibold hover:bg-zinc-50">
              搜索
            </button>
          </div>
        </div>

        {/* 二级分类标签栏 */}
        {channelTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-t border-[var(--border-soft)] pt-3">
            <span className="mr-1 text-[11px] font-semibold text-[var(--ink-muted)]">分类标签：</span>
            <button
              onClick={() => setSubTag("all")}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                subTag === "all" ? "bg-[var(--brand-primary)] text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
              }`}
            >
              全部
            </button>
            {channelTags.map((tg) => (
              <button
                key={tg.id}
                onClick={() => setSubTag(tg.name)}
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  subTag === tg.name ? "bg-[var(--brand-green)] text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                }`}
              >
                #{tg.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 专辑网格 */}
      {loading ? (
        <div className="card-pro p-10 text-center text-xs text-[var(--ink-muted)]">正在加载家庭音像馆…</div>
      ) : sortedAlbums.length === 0 ? (
        <EmptyState
          icon={Disc3}
          title="当前筛选暂无专辑内容"
          description={
            isAdmin
              ? "您可点击左下角「内容工坊与管理后台」在「五大内容填充中心」导入全龄示范包、扫描本地文件夹或 AI 生成课程专辑。"
              : "请联系家庭管理员添加专辑或音频内容，或者点击上方「全网点播搜歌」直接在线搜歌收听。"
          }
          action={
            isAdmin && onOpenStudioAlbum ? (
              <button
                onClick={() => onOpenStudioAlbum(0)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-5 py-2.5 text-xs font-semibold text-white"
              >
                <Sparkles className="h-4 w-4" /> 前往管理后台填充内容
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sortedAlbums.map((alb) => {
            const count = (alb.tracks || []).length;
            const isStageMatch = selectedMember && alb.age_stage === selectedMember.age_stage;
            return (
              <div
                key={alb.id}
                onClick={() => setActiveAlbId(alb.id)}
                className={`card-pro group cursor-pointer overflow-hidden transition hover:-translate-y-0.5 hover:shadow-md ${
                  isStageMatch ? "ring-2 ring-[var(--brand-green)]/40" : ""
                }`}
              >
                <div className={`relative flex h-32 items-end justify-between bg-gradient-to-br ${COVER_THEME[alb.category]} p-4 text-white`}>
                  <div className="min-w-0 pr-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="rounded-md bg-black/25 px-2 py-0.5 text-[11px] font-medium backdrop-blur-xs">
                        {CHANNELS.find((c) => c.id === alb.category)?.label}
                      </span>
                      {alb.sub_tag && (
                        <span className="rounded-md bg-white/20 px-2 py-0.5 text-[11px] font-medium backdrop-blur-xs">
                          #{alb.sub_tag}
                        </span>
                      )}
                    </div>
                    <div className="mt-2 flex items-center gap-1.5 text-2xl">
                      <span>{alb.cover_emoji || CHANNEL_DEFAULT_EMOJI[alb.category]}</span>
                      <span className="text-xs font-medium text-white/90">
                        共 {count} 集 · {AGE_STAGE_LABELS[alb.age_stage].split(" ")[0]}
                      </span>
                    </div>
                  </div>

                  {count > 0 && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onPlayQueue(toQueue(alb), 0);
                      }}
                      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-[var(--brand-green)] shadow-lg transition group-hover:scale-105"
                      title="立即播放整张专辑"
                    >
                      <Play className="h-4 w-4 fill-current" />
                    </button>
                  )}
                </div>

                <div className="p-4">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="truncate text-base font-bold group-hover:text-[var(--brand-green)]">{alb.title}</h3>
                    {isStageMatch && (
                      <span className="shrink-0 rounded bg-[var(--brand-green-soft)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--brand-green)]">
                        适龄推荐
                      </span>
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-[var(--ink-muted)]">{alb.description || "点击进入专辑详情与收听"}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 推送音箱弹窗 */}
      <PushSpeakerModal
        open={pushModalOpen}
        album={pushAlbum}
        startIndex={pushStartIndex}
        devices={dashboard.devices}
        selectedDevIds={selectedDevIds}
        setSelectedDevIds={setSelectedDevIds}
        loopMode={pushLoopMode}
        setLoopMode={setPushLoopMode}
        sleepOption={sleepOption}
        setSleepOption={setSleepOption}
        pushing={pushing}
        onClose={() => setPushModalOpen(false)}
        onConfirm={handleConfirmPush}
      />

      {/* 全网搜播搜歌弹窗 */}
      <Modal open={searchOpen} title="全网搜歌 / 搜故事（即点即播 · 自动缓存到本地）" onClose={() => setSearchOpen(false)} maxWidth="max-w-2xl">
        <div className="space-y-4 text-xs">
          <div className="flex gap-2">
            <input
              value={onlineQ}
              onChange={(e) => setOnlineQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void handleOnlineSearch()}
              placeholder="输入歌名、绘本或故事关键词（如：小星星、三只小猪、Super Simple Songs）"
              className="flex-1 rounded-xl border border-[var(--border-soft)] px-3.5 py-2 text-sm"
            />
            <button
              disabled={searchingOnline}
              onClick={handleOnlineSearch}
              className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white"
            >
              {searchingOnline ? "搜索中…" : "全网搜索"}
            </button>
          </div>
          {onlineResults.length === 0 ? (
            <div className="rounded-xl bg-zinc-50 p-6 text-center text-[var(--ink-muted)]">
              搜索任意中文或英文音频，点击即可立即播放并自动护耳缓存存入本地《语音缓存池》。
            </div>
          ) : (
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {onlineResults.map((r, i) => (
                <div key={i} className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border-soft)] p-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">{r.title}</div>
                    <div className="text-[11px] text-[var(--ink-muted)]">{r.uploader} · {r.duration_sec}s</div>
                  </div>
                  <button
                    onClick={() => void handlePlayOnlineResult(r.title, r.url)}
                    className="inline-flex shrink-0 items-center gap-1 rounded-xl bg-[var(--brand-green)] px-3.5 py-2 font-semibold text-white"
                  >
                    <Play className="h-3.5 w-3.5 fill-current" /> 立即播放
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}

function PushSpeakerModal({
  open,
  album,
  startIndex,
  devices,
  selectedDevIds,
  setSelectedDevIds,
  loopMode,
  setLoopMode,
  sleepOption,
  setSleepOption,
  pushing,
  onClose,
  onConfirm,
}: {
  open: boolean;
  album: MediaAlbum | null;
  startIndex: number;
  devices: DashboardData["devices"];
  selectedDevIds: string[];
  setSelectedDevIds: React.Dispatch<React.SetStateAction<string[]>>;
  loopMode: "sequential" | "repeat_one" | "shuffle";
  setLoopMode: (m: "sequential" | "repeat_one" | "shuffle") => void;
  sleepOption: "none" | "ep1" | "ep2" | "min20" | "min40";
  setSleepOption: (s: "none" | "ep1" | "ep2" | "min20" | "min40") => void;
  pushing: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  if (!album) return null;
  const startTitle = album.tracks?.[startIndex]?.title || "第 1 集";

  return (
    <Modal open={open} title={`推送《${album.title}》到智能音箱连播`} onClose={onClose}>
      <div className="space-y-4 text-xs">
        <div className="rounded-xl bg-zinc-50 p-3 text-zinc-700">
          起始播放集数：<span className="font-bold">{startTitle}</span>（播完自动连播后续集数）
        </div>

        <div>
          <div className="mb-2 font-bold">1. 选择房间音箱（支持多房间同时播）：</div>
          <div className="grid gap-2 sm:grid-cols-2">
            {devices.map((d) => {
              const checked = selectedDevIds.includes(d.id);
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() =>
                    setSelectedDevIds((prev) =>
                      prev.includes(d.id) ? prev.filter((x) => x !== d.id) : [...prev, d.id]
                    )
                  }
                  className={`flex items-center justify-between rounded-xl border p-3 text-left transition ${
                    checked
                      ? "border-[var(--brand-green)] bg-[var(--brand-green-soft)]/70 font-semibold text-[var(--brand-green)]"
                      : "border-[var(--border-soft)] bg-white"
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-1.5">
                      <Radio className="h-3.5 w-3.5" />
                      <span>{d.name}</span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-[var(--ink-muted)]">
                      {d.room} · {d.online ? "在线" : "离线缓存队列"}
                    </div>
                  </div>
                  {checked && <CheckCircle2 className="h-4 w-4" />}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <div className="mb-1.5 font-bold">2. 队列循环方式：</div>
            <select
              value={loopMode}
              onChange={(e) => setLoopMode(e.target.value as "sequential" | "repeat_one" | "shuffle")}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
            >
              <option value="sequential">按集顺序连播</option>
              <option value="shuffle">随机播放</option>
              <option value="repeat_one">单集循环</option>
            </select>
          </div>

          <div>
            <div className="mb-1.5 flex items-center gap-1 font-bold">
              <Moon className="h-3.5 w-3.5 text-amber-600" /> 3. 伴睡定时停止：
            </div>
            <select
              value={sleepOption}
              onChange={(e) => setSleepOption(e.target.value as typeof sleepOption)}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
            >
              <option value="none">不限制（顺序播完）</option>
              <option value="ep1">播完当前 1 集自动停</option>
              <option value="ep2">播完 2 集后自动停</option>
              <option value="min20">20 分钟后轻柔停止</option>
              <option value="min40">40 分钟后轻柔停止</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="rounded-xl border border-[var(--border-soft)] px-4 py-2">
            取消
          </button>
          <button
            type="button"
            disabled={pushing || selectedDevIds.length === 0}
            onClick={onConfirm}
            className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white disabled:opacity-40"
          >
            {pushing ? "下发队列中…" : "确认推送并立即播放"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
