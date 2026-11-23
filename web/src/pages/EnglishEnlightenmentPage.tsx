import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Award,
  BookOpen,
  Calendar,
  CheckCircle2,
  Circle,
  Clock,
  Download,
  Flame,
  GraduationCap,
  Mic,
  Play,
  Plus,
  RotateCcw,
  Sparkles,
  Speaker,
  Star,
  Trash2,
  Upload,
  Volume2,
} from "lucide-react";
import { api, DashboardData, EnglishCheckinStats, EnglishLevel, MediaAlbum, MediaSeries, MediaTrack } from "../api";
import { EmptyState, Modal } from "../components/Modal";
import { QueueItem } from "../components/PlayerBar";
import { PushTargetSpec, QuickPushModal } from "../components/QuickPushModal";

interface LevelDef {
  code: "L1" | "L2" | "L3" | "L4" | "L5";
  stage: Exclude<EnglishLevel, "adult">;
  title: string;
  desc: string;
  badge: string;
}

const ENGLISH_LEVEL_LADDER: LevelDef[] = [
  { code: "L1", stage: "Pre_A1", title: "L1 · 磨耳朵儿歌", desc: "韵律儿歌与具象单词", badge: "Pre-A1" },
  { code: "L2", stage: "A1", title: "L2 · 拼读与日常", desc: "自然拼读与生活短句", badge: "A1" },
  { code: "L3", stage: "A2", title: "L3 · 分级绘本", desc: "牛津树/RAZ情景跟读", badge: "A2" },
  { code: "L4", stage: "B1", title: "L4 · 故事听说", desc: "桥梁章节与科普探索", badge: "B1" },
  { code: "L5", stage: "B2_PLUS", title: "L5 · 原版进阶", desc: "原版听读与思辨表达", badge: "B2+" },
];

function fmtTime(sec?: number): string {
  if (!sec || !Number.isFinite(sec) || sec <= 0) return "00:00";
  const s = Math.floor(sec);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function EnglishEnlightenmentPage({
  dashboard,
  memberKey = "",
  refreshSignal,
  onPlayQueue,
  onPlayUrl,
  onRefreshDashboard,
  showToast,
}: {
  dashboard: DashboardData;
  memberKey?: string;
  refreshSignal: number;
  onPlayQueue: (items: QueueItem[], startIndex: number) => void;
  onPlayUrl: (url: string) => void;
  onRefreshDashboard: () => void;
  showToast: (m: string) => void;
}) {
  const [allSeries, setAllSeries] = useState<MediaSeries[]>([]);
  const [checkinStats, setCheckinStats] = useState<EnglishCheckinStats | null>(null);
  const [activeLevel, setActiveLevel] = useState<LevelDef["code"]>("L1");
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | null>(null);
  const [selectedSeasonId, setSelectedSeasonId] = useState<number | null>(null);
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  // 慢速磨耳朵 / 单句点读 / 孩子跟读录音回放与打分
  const [slowMode, setSlowMode] = useState(false);
  const [recordingSentence, setRecordingSentence] = useState("");
  const [lastRecordUrl, setLastRecordUrl] = useState("");
  const [speechEval, setSpeechEval] = useState<{ expected_text: string; recognized_text: string; stars: number; feedback: string } | null>(null);
  const recordAudioRef = useRef<HTMLAudioElement | null>(null);

  // 音箱推送弹窗
  const [pushTarget, setPushTarget] = useState<PushTargetSpec | null>(null);

  // AI 生成新英语单元
  const [genOpen, setGenOpen] = useState(false);
  const [genTopic, setGenTopic] = useState("");
  const [genBusy, setGenBusy] = useState(false);

  // 导入自有分级英语音频（如牛津树 / RAZ / 佩奇英文）
  const [importOpen, setImportOpen] = useState(false);
  const [importTitle, setImportTitle] = useState("");
  const [importEmoji, setImportEmoji] = useState("📘");
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importBusy, setImportBusy] = useState(false);

  // AI 全网采集英语启蒙资源
  const [aiCollectOpen, setAiCollectOpen] = useState(false);
  const [aiQuery, setAiQuery] = useState("");
  const [aiDeviceId, setAiDeviceId] = useState("");

  // 点读发音中状态
  const [speakingWord, setSpeakingWord] = useState("");

  const loadEnglishSeries = useCallback(async () => {
    setLoading(true);
    try {
      const [data, st] = await Promise.all([
        api.listSeries({ channel: "english", member_key: memberKey || undefined }),
        api.getEnglishStats(memberKey || ""),
      ]);
      setAllSeries(data);
      setCheckinStats(st);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [memberKey, showToast]);

  useEffect(() => {
    void loadEnglishSeries();
  }, [loadEnglishSeries, refreshSignal]);

  // 找出最近学习过的一个英语系列用于顶部「继续上次启蒙」主卡
  const lastStudiedSeries = allSeries.find((s) => Boolean(s.resume_info)) || allSeries[0] || null;

  // 当前等级下的所有启蒙系列
  const levelSeries = allSeries.filter((s) => (s.level_code || "L1") === activeLevel);
  const currentSeries = levelSeries.find((s) => s.id === selectedSeriesId) || levelSeries[0] || null;
  const currentSeason: MediaAlbum | null =
    currentSeries?.seasons.find((a) => a.id === selectedSeasonId) ||
    (currentSeries?.resume_info && currentSeries.seasons.find((a) => a.id === currentSeries.resume_info?.album_id)) ||
    currentSeries?.seasons[0] ||
    null;
  const tracks = currentSeason?.tracks || [];
  const currentTrack: MediaTrack | null =
    tracks.find((t) => t.id === selectedTrackId) ||
    (currentSeries?.resume_info && tracks.find((t) => t.id === currentSeries.resume_info?.track_id)) ||
    tracks[0] ||
    null;

  useEffect(() => {
    if (currentSeries && currentSeries.id !== selectedSeriesId) {
      setSelectedSeriesId(currentSeries.id);
    }
  }, [currentSeries, selectedSeriesId]);

  useEffect(() => {
    if (currentSeason && currentSeason.id !== selectedSeasonId) {
      setSelectedSeasonId(currentSeason.id);
    }
  }, [currentSeason, selectedSeasonId]);

  useEffect(() => {
    if (currentTrack && currentTrack.id !== selectedTrackId) {
      setSelectedTrackId(currentTrack.id);
    }
  }, [currentTrack, selectedTrackId]);

  const activeLevelMeta = ENGLISH_LEVEL_LADDER.find((l) => l.code === activeLevel) || ENGLISH_LEVEL_LADDER[0];

  const playLessonQueue = (series: MediaSeries, season: MediaAlbum, startTrackId?: number, startPos = 0) => {
    const list = season.tracks || [];
    if (list.length === 0) {
      showToast("该单元暂无课时音频");
      return;
    }
    const seaLbl = season.season_label || `第${season.season_num || 1}单元`;
    const items: QueueItem[] = list.map((t) => ({
      id: t.id,
      kind: "track",
      title: t.title,
      subtitle: `${series.level_code || "L1"} · ${series.title} · ${seaLbl} 第${t.episode_num}课`,
      streamUrl: t.stream_url || `/api/media/tracks/${t.id}/stream`,
      parentId: season.id,
      durationSec: t.duration_sec || 0,
      startPositionSec: startTrackId && t.id === startTrackId ? startPos : 0,
      episodeNum: t.episode_num,
      seasonNum: season.season_num || 1,
      seasonLabel: seaLbl,
      seriesId: series.id,
      seriesTitle: series.title,
    }));
    const idx = startTrackId ? Math.max(0, items.findIndex((x) => x.id === startTrackId)) : 0;
    onPlayQueue(items, idx);
  };

  const handleContinueLastStudy = () => {
    if (!lastStudiedSeries) return;
    const lvl = (lastStudiedSeries.level_code || "L1") as LevelDef["code"];
    setActiveLevel(lvl);
    setSelectedSeriesId(lastStudiedSeries.id);
    const r = lastStudiedSeries.resume_info;
    const sea = (r && lastStudiedSeries.seasons.find((a) => a.id === r.album_id)) || lastStudiedSeries.seasons[0];
    if (sea) {
      setSelectedSeasonId(sea.id);
      if (r?.track_id) setSelectedTrackId(r.track_id);
      playLessonQueue(lastStudiedSeries, sea, r?.track_id, r?.position_sec || 0);
    }
  };

  const handleToggleCompleted = async (tr: MediaTrack) => {
    const next = !(tr.completed === 1);
    try {
      await api.updateTrack(tr.id, { completed: next });
      if (next) {
        const st = await api.recordEnglishCheckin({
          track_id: tr.id,
          duration_min: Math.max(3, Math.round((tr.duration_sec || 180) / 60)),
          note: `完成课时：${tr.title}`,
          member_key: memberKey || "",
        });
        setCheckinStats(st);
        showToast(`🎉 打卡成功！已连续启蒙 ${st.streak_days} 天`);
      } else {
        showToast(`已取消《${tr.title}》完成标记`);
      }
      await loadEnglishSeries();
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const handlePronounce = async (word: string, rateOverride?: string) => {
    setSpeakingWord(word);
    try {
      const res = await api.pronounceEnglish(word, rateOverride || (slowMode ? "-24%" : "-8%"));
      onPlayUrl(res.tts_url);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      window.setTimeout(() => setSpeakingWord(""), 800);
    }
  };

  const handleFollowReadRecord = async (sentence: string, trackId?: number) => {
    if (recordingSentence) return;
    setRecordingSentence(sentence);
    setSpeechEval(null);
    showToast("请跟着大声读出来（录音 3.5 秒）...");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (ev) => ev.data.size > 0 && chunks.push(ev.data);
      const blob = await new Promise<Blob>((resolve) => {
        rec.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          resolve(new Blob(chunks, { type: "audio/webm" }));
        };
        rec.start();
        window.setTimeout(() => rec.state !== "inactive" && rec.stop(), 3500);
      });
      if (lastRecordUrl) URL.revokeObjectURL(lastRecordUrl);
      const localUrl = URL.createObjectURL(blob);
      setLastRecordUrl(localUrl);
      const evalRes = await api.evaluateEnglishSpeech(sentence, blob, trackId, memberKey || "");
      setSpeechEval(evalRes);
      const st = await api.getEnglishStats(memberKey || "");
      setCheckinStats(st);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "麦克风录音失败，请检查浏览器录音权限");
    } finally {
      setRecordingSentence("");
    }
  };

  const handleSeedBuiltin = async () => {
    try {
      const res = await api.seedBuiltinCourses();
      showToast(`已导入 ${res.courses_added} 套内置分级英语课程（共 ${res.lessons_added} 课）`);
      await loadEnglishSeries();
      onRefreshDashboard();
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const handleGenerateUnit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!genTopic.trim()) return;
    setGenBusy(true);
    try {
      await api.generateEnglishCourse({ topic: genTopic.trim(), stage: activeLevelMeta.stage });
      showToast(`已为 ${activeLevelMeta.code} 生成主题启蒙单元《${genTopic.trim()}》`);
      setGenTopic("");
      setGenOpen(false);
      await loadEnglishSeries();
      onRefreshDashboard();
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setGenBusy(false);
    }
  };

  const handleImportCustomEnglish = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!importTitle.trim()) return;
    setImportBusy(true);
    try {
      const created = await api.createSeries({
        title: importTitle.trim(),
        channel: "english",
        level_code: activeLevel,
        cover_emoji: importEmoji.trim() || "📘",
        auto_create_first_season: true,
        first_season_label: "第1单元",
      });
      const albId = created.seasons[0]?.id;
      if (albId && importFiles.length > 0) {
        for (const f of importFiles) {
          await api.uploadAudio(albId, f);
        }
      }
      showToast(`已创建 ${activeLevel} 启蒙系列《${created.title}》${importFiles.length > 0 ? `并上传 ${importFiles.length} 课音频` : ""}`);
      setImportTitle("");
      setImportFiles([]);
      setImportOpen(false);
      await loadEnglishSeries();
      setSelectedSeriesId(created.id);
      onRefreshDashboard();
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setImportBusy(false);
    }
  };

  // 计算整体和本级打卡统计
  const levelTotalTracks = levelSeries.reduce((acc, s) => acc + s.total_tracks, 0);
  const levelDoneTracks = levelSeries.reduce((acc, s) => acc + s.completed_tracks, 0);
  const levelPct = levelTotalTracks > 0 ? Math.round((levelDoneTracks / levelTotalTracks) * 100) : 0;

  return (
    <div className="space-y-5">
      {/* 顶部大标题 + 快捷工具 */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight">英语分级启蒙</h2>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
            参考专业启蒙分级路线（L1 磨耳朵 → L5 原版进阶），自动记录上次学到哪一课第几秒，支持词卡点读、打卡成长与推音箱熏听。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setGenOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-4 py-2 text-xs font-bold text-white shadow-xs"
          >
            <Sparkles className="h-3.5 w-3.5" /> AI 生成新启蒙单元
          </button>
          <button
            onClick={() => {
              setAiQuery(`${activeLevel} 英语启蒙儿歌`);
              const online = dashboard.devices.find((d) => d.online === 1) || dashboard.devices[0];
              setAiDeviceId(online?.id || "");
              setAiCollectOpen(true);
            }}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-primary)] bg-[var(--brand-green-soft)] px-3.5 py-2 text-xs font-bold text-[var(--brand-primary)]"
          >
            <Download className="h-3.5 w-3.5" /> 全网采集英语
          </button>
          <button
            onClick={() => setImportOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-3.5 py-2 text-xs font-bold hover:bg-[var(--bg-subtle)]"
          >
            <Upload className="h-3.5 w-3.5" /> 导入绘本音频
          </button>
          {allSeries.length < 4 && (
            <button
              onClick={() => void handleSeedBuiltin()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-amber-300 bg-amber-50 px-3.5 py-2 text-xs font-bold text-amber-800 hover:bg-amber-100"
            >
              <GraduationCap className="h-3.5 w-3.5" /> 一键导入内置启蒙课
            </button>
          )}
        </div>
      </div>

      {/* 7 天英语打卡日历与成长成就条 */}
      {checkinStats && (
        <section className="card-pro flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <div className="flex items-center gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-100 text-amber-600">
                <Flame className="h-5 w-5" />
              </span>
              <div>
                <div className="text-[11px] text-[var(--ink-muted)]">连续启蒙打卡</div>
                <div className="text-base font-extrabold text-[var(--ink-primary)]">{checkinStats.streak_days} 天</div>
              </div>
            </div>
            <div className="h-8 w-px bg-[var(--border-soft)]" />
            <div>
              <div className="text-[11px] text-[var(--ink-muted)]">累计磨耳朵</div>
              <div className="text-sm font-extrabold text-[var(--ink-primary)]">
                {checkinStats.total_minutes} 分钟 · {checkinStats.total_checkins} 次
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <Calendar className="mr-1 hidden h-3.5 w-3.5 text-[var(--ink-muted)] sm:block" />
            {checkinStats.last_7_days.map((d) => (
              <div
                key={d.date}
                title={`${d.date}：${d.checked ? `已打卡 ${d.count} 次 (${d.minutes} 分钟)` : "未打卡"}`}
                className={`flex flex-col items-center rounded-xl border px-2.5 py-1.5 text-[10px] font-bold ${
                  d.checked
                    ? "border-[var(--brand-primary)] bg-[var(--brand-green-soft)] text-[var(--brand-primary)]"
                    : "border-[var(--border-soft)] bg-[var(--bg-subtle)] text-[var(--ink-muted)]"
                }`}
              >
                <span>{d.label}</span>
                <span className="mt-0.5 text-xs">{d.checked ? "🌸" : "·"}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 继续上次启蒙主卡 */}
      {lastStudiedSeries && (
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--brand-primary)]/30 bg-[var(--brand-green-soft)] p-4">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[var(--brand-primary)] text-2xl text-white shadow-xs">
              {lastStudiedSeries.cover_emoji || "🔤"}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs font-bold text-[var(--brand-primary)]">
                <Clock className="h-3.5 w-3.5" />
                <span>{lastStudiedSeries.resume_info ? "上次学到这里 · 一键接着磨耳朵" : "推荐从这里开始今日启蒙"}</span>
                <span className="rounded-full bg-white px-2 py-0.5 text-[10px]">
                  {lastStudiedSeries.level_code || "L1"}
                </span>
              </div>
              <div className="mt-0.5 truncate text-base font-extrabold text-[var(--ink-primary)]">
                {lastStudiedSeries.title}
                {lastStudiedSeries.resume_info
                  ? ` · ${lastStudiedSeries.resume_info.season_label} 第${lastStudiedSeries.resume_info.episode_num}课《${lastStudiedSeries.resume_info.track_title}》`
                  : ""}
              </div>
              {lastStudiedSeries.resume_info && lastStudiedSeries.resume_info.position_sec > 2 && (
                <div className="mt-0.5 text-[11px] font-semibold text-[var(--ink-secondary)]">
                  已记忆播放位置：{fmtTime(lastStudiedSeries.resume_info.position_sec)}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleContinueLastStudy}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-5 py-2.5 text-xs font-bold text-white shadow-xs"
            >
              <Play className="h-3.5 w-3.5" /> 继续学习
            </button>
            <button
              onClick={() =>
                setPushTarget({
                  label: `${lastStudiedSeries.level_code || "L1"} · ${lastStudiedSeries.title}`,
                  subtitle: "从上次学习的课时自动续播并推给音箱磨耳朵",
                  seriesId: lastStudiedSeries.id,
                  defaultResume: true,
                })
              }
              className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-primary)] bg-white px-4 py-2.5 text-xs font-bold text-[var(--brand-primary)]"
            >
              <Speaker className="h-3.5 w-3.5" /> 推音箱磨耳朵
            </button>
          </div>
        </section>
      )}

      {/* 五阶启蒙路线图（L1 -> L5） */}
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
        {ENGLISH_LEVEL_LADDER.map((lvl) => {
          const items = allSeries.filter((s) => (s.level_code || "L1") === lvl.code);
          const tot = items.reduce((a, b) => a + b.total_tracks, 0);
          const done = items.reduce((a, b) => a + b.completed_tracks, 0);
          const pct = tot > 0 ? Math.round((done / tot) * 100) : 0;
          const active = activeLevel === lvl.code;

          return (
            <button
              key={lvl.code}
              onClick={() => {
                setActiveLevel(lvl.code);
                setSelectedSeriesId(null);
                setSelectedSeasonId(null);
                setSelectedTrackId(null);
              }}
              className={`flex flex-col justify-between rounded-2xl border p-3.5 text-left transition ${
                active
                  ? "border-[var(--brand-primary)] bg-[var(--brand-primary)] text-white shadow-sm"
                  : "border-[var(--border-soft)] bg-[var(--bg-card)] hover:border-[var(--brand-primary)]/40"
              }`}
            >
              <div>
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-extrabold">{lvl.title}</span>
                  <span
                    className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${
                      active ? "bg-white/20 text-white" : "bg-[var(--bg-subtle)] text-[var(--ink-muted)]"
                    }`}
                  >
                    {lvl.badge}
                  </span>
                </div>
                <div className={`mt-1 text-[11px] ${active ? "text-white/85" : "text-[var(--ink-muted)]"}`}>
                  {lvl.desc}
                </div>
              </div>
              <div className="mt-3 space-y-1">
                <div className={`flex justify-between text-[10px] font-bold ${active ? "text-white/90" : "text-[var(--ink-secondary)]"}`}>
                  <span>{items.length} 套 · {tot} 课</span>
                  <span>{pct}%</span>
                </div>
                <div className={`h-1.5 w-full overflow-hidden rounded-full ${active ? "bg-white/25" : "bg-[var(--bg-subtle)]"}`}>
                  <div
                    className={`h-full rounded-full transition-all ${active ? "bg-white" : "bg-[var(--brand-primary)]"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* 当前级别主体学习区 */}
      {loading && allSeries.length === 0 ? (
        <div className="card-pro p-10 text-center text-xs text-[var(--ink-muted)]">正在加载英语启蒙课程…</div>
      ) : levelSeries.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title={`${activeLevelMeta.title} 暂无启蒙课程`}
          description="你可以一键导入内置的体系启蒙课、让 AI 根据孩子兴趣生成一套主题课，或直接上传牛津树 / RAZ 音频包。"
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <button
                onClick={() => void handleSeedBuiltin()}
                className="rounded-xl bg-[var(--brand-primary)] px-5 py-2.5 text-xs font-bold text-white"
              >
                📦 一键导入内置启蒙课
              </button>
              <button
                onClick={() => setGenOpen(true)}
                className="rounded-xl border border-[var(--brand-primary)] bg-[var(--brand-green-soft)] px-5 py-2.5 text-xs font-bold text-[var(--brand-primary)]"
              >
                ✨ AI 生成 {activeLevel} 新单元
              </button>
              <button
                onClick={() => setImportOpen(true)}
                className="rounded-xl border border-[var(--border-soft)] bg-white px-5 py-2.5 text-xs font-bold"
              >
                📤 导入自有分级音频
              </button>
            </div>
          }
        />
      ) : (
        <div className="grid gap-5 lg:grid-cols-12">
          {/* 左侧：本等级系列与单元目录 */}
          <div className="space-y-3 lg:col-span-4">
            <div className="flex items-center justify-between px-1 text-xs">
              <span className="font-extrabold text-[var(--ink-primary)]">
                {activeLevelMeta.title} 书单（{levelSeries.length}）
              </span>
              <span className="inline-flex items-center gap-1 font-bold text-[var(--brand-primary)]">
                <Award className="h-3.5 w-3.5" /> 已打卡 {levelDoneTracks}/{levelTotalTracks} ({levelPct}%)
              </span>
            </div>

            <div className="space-y-2.5">
              {levelSeries.map((s) => {
                const active = currentSeries?.id === s.id;
                const pct = s.total_tracks > 0 ? Math.round((s.completed_tracks / s.total_tracks) * 100) : 0;
                return (
                  <div
                    key={s.id}
                    onClick={() => {
                      setSelectedSeriesId(s.id);
                      setSelectedSeasonId(null);
                      setSelectedTrackId(null);
                    }}
                    className={`cursor-pointer rounded-2xl border p-4 transition ${
                      active
                        ? "border-[var(--brand-primary)] bg-[var(--brand-green-soft)]/70 shadow-xs"
                        : "border-[var(--border-soft)] bg-[var(--bg-card)] hover:border-[var(--brand-primary)]/40"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <span className="text-2xl">{s.cover_emoji || "📘"}</span>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-extrabold">{s.title}</div>
                          <div className="text-[11px] text-[var(--ink-muted)]">
                            {s.season_count} 单元 · 已打卡 {s.completed_tracks}/{s.total_tracks} 课
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          if (!window.confirm(`确定删除英语系列《${s.title}》吗？`)) return;
                          await api.deleteSeries(s.id);
                          showToast(`已删除《${s.title}》`);
                          await loadEnglishSeries();
                        }}
                        className="rounded-lg p-1 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-white/80">
                      <div className="h-full rounded-full bg-[var(--brand-primary)]" style={{ width: `${pct}%` }} />
                    </div>
                    {s.resume_info && (
                      <div className="mt-2 truncate text-[11px] font-semibold text-[var(--brand-primary)]">
                        上次学到：{s.resume_info.season_label} 第{s.resume_info.episode_num}课
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* 右侧：课时地图 + 词卡点读 + 双语伴读课堂 */}
          <div className="space-y-4 lg:col-span-8">
            {currentSeries && currentSeason && (
              <section className="card-pro p-5 space-y-4">
                {/* 单元切换条 */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-soft)] pb-3">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {currentSeries.seasons.map((sea) => {
                      const act = sea.id === currentSeason.id;
                      return (
                        <button
                          key={sea.id}
                          onClick={() => {
                            setSelectedSeasonId(sea.id);
                            setSelectedTrackId(null);
                          }}
                          className={`rounded-xl px-3 py-1.5 text-xs font-bold ${
                            act ? "bg-[var(--brand-primary)] text-white" : "bg-[var(--bg-subtle)] text-[var(--ink-secondary)]"
                          }`}
                        >
                          {sea.season_label || `第${sea.season_num}单元`} ({sea.tracks?.length || 0}课)
                        </button>
                      );
                    })}
                    <button
                      onClick={async () => {
                        const nextN = Math.max(0, ...currentSeries.seasons.map((x) => x.season_num || 0)) + 1;
                        const created = await api.createSeason(currentSeries.id, {
                          season_num: nextN,
                          season_label: `第${nextN}单元`,
                        });
                        showToast(`已新增 第${nextN}单元`);
                        await loadEnglishSeries();
                        setSelectedSeasonId(created.id);
                      }}
                      className="inline-flex items-center gap-1 rounded-xl border border-dashed border-[var(--brand-primary)] px-2.5 py-1.5 text-xs font-bold text-[var(--brand-primary)]"
                    >
                      <Plus className="h-3 w-3" /> 新单元
                    </button>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() =>
                        playLessonQueue(
                          currentSeries,
                          currentSeason,
                          currentTrack?.id,
                          currentTrack?.last_position_sec || 0
                        )
                      }
                      disabled={tracks.length === 0}
                      className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-primary)] px-3.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
                    >
                      <Play className="h-3.5 w-3.5" /> 连播本单元
                    </button>
                    <button
                      onClick={() =>
                        setPushTarget({
                          label: `${currentSeries.title} · ${currentSeason.season_label}`,
                          subtitle: "推送本单元至房间音箱顺序磨耳朵",
                          albumId: currentSeason.id,
                          seriesId: currentSeries.id,
                          defaultResume: true,
                        })
                      }
                      disabled={tracks.length === 0}
                      className="inline-flex items-center gap-1 rounded-xl border border-[var(--brand-primary)] bg-[var(--brand-green-soft)] px-3.5 py-1.5 text-xs font-bold text-[var(--brand-primary)] disabled:opacity-40"
                    >
                      <Speaker className="h-3.5 w-3.5" /> 推音箱
                    </button>
                  </div>
                </div>

                {/* 课时横排胶囊 */}
                {tracks.length > 0 ? (
                  <>
                    <div className="flex flex-wrap gap-2">
                      {tracks.map((tr) => {
                        const act = currentTrack?.id === tr.id;
                        const done = tr.completed === 1;
                        return (
                          <button
                            key={tr.id}
                            onClick={() => setSelectedTrackId(tr.id)}
                            className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-bold transition ${
                              act
                                ? "border-[var(--brand-primary)] bg-[var(--brand-green-soft)] text-[var(--brand-primary)]"
                                : "border-[var(--border-soft)] bg-white text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)]"
                            }`}
                          >
                            {done ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                            ) : (
                              <Circle className="h-3.5 w-3.5 text-zinc-300" />
                            )}
                            <span>第{tr.episode_num}课 · {tr.title}</span>
                          </button>
                        );
                      })}
                    </div>

                    {/* 选中课时沉浸课堂 */}
                    {currentTrack && (
                      <div className="space-y-4 rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/50 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="rounded-lg bg-[var(--brand-primary)] px-2 py-0.5 text-[11px] font-extrabold text-white">
                                第 {currentTrack.episode_num} 课
                              </span>
                              <h4 className="text-base font-extrabold">{currentTrack.title}</h4>
                            </div>
                            {currentTrack.objective && (
                              <p className="mt-1 text-xs text-[var(--ink-secondary)]">🎯 学习目标：{currentTrack.objective}</p>
                            )}
                          </div>

                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              onClick={() =>
                                playLessonQueue(
                                  currentSeries,
                                  currentSeason,
                                  currentTrack.id,
                                  currentTrack.last_position_sec || 0
                                )
                              }
                              className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-primary)] px-4 py-2 text-xs font-bold text-white"
                            >
                              <Play className="h-3.5 w-3.5" /> 播放本课
                            </button>
                            <button
                              onClick={() => void handleToggleCompleted(currentTrack)}
                              className={`inline-flex items-center gap-1 rounded-xl border px-3.5 py-2 text-xs font-bold transition ${
                                currentTrack.completed === 1
                                  ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                                  : "border-[var(--border-soft)] bg-white text-[var(--ink-primary)] hover:border-emerald-400"
                              }`}
                            >
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              {currentTrack.completed === 1 ? "已打卡完成" : "打卡完成"}
                            </button>
                          </div>
                        </div>

                        {/* 核心词汇点读卡 */}
                        {currentTrack.vocab && currentTrack.vocab.length > 0 && (
                          <div>
                            <div className="mb-2 text-xs font-bold text-[var(--ink-secondary)]">
                              🔊 核心词卡（点击卡片立即标准美音点读）
                            </div>
                            <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                              {currentTrack.vocab.map((v, idx) => (
                                <button
                                  key={idx}
                                  type="button"
                                  onClick={() => void handlePronounce(`${v.en}. ${v.example || ""}`)}
                                  className={`group rounded-2xl border p-3 text-left transition ${
                                    speakingWord.startsWith(v.en)
                                      ? "border-[var(--brand-primary)] bg-[var(--brand-green-soft)]"
                                      : "border-[var(--border-soft)] bg-white hover:border-[var(--brand-primary)]/50"
                                  }`}
                                >
                                  <div className="flex items-center justify-between gap-1">
                                    <span className="text-sm font-extrabold text-[var(--brand-primary)]">{v.en}</span>
                                    <Volume2 className="h-3.5 w-3.5 text-[var(--ink-muted)] group-hover:text-[var(--brand-primary)]" />
                                  </div>
                                  <div className="mt-0.5 text-xs font-semibold text-[var(--ink-primary)]">{v.zh}</div>
                                  {v.example && (
                                    <div className="mt-1 text-[11px] leading-snug text-[var(--ink-muted)]">{v.example}</div>
                                  )}
                                </button>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* 伴读讲稿：单句分句点读 + 0.75x 慢速磨耳朵 + 跟读录音回放打分 */}
                        {currentTrack.text_content && (
                          <div className="space-y-3 rounded-xl border border-[var(--border-soft)] bg-white p-3.5">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="text-xs font-bold text-[var(--ink-secondary)]">
                                📖 单句精听与开口跟读（点任意一句听标准发音，点麦克风跟读录音）
                              </div>
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => setSlowMode((v) => !v)}
                                  className={`rounded-lg border px-2.5 py-1 text-[11px] font-bold transition ${
                                    slowMode
                                      ? "border-[var(--brand-primary)] bg-[var(--brand-green-soft)] text-[var(--brand-primary)]"
                                      : "border-[var(--border-soft)] bg-zinc-50 text-[var(--ink-secondary)]"
                                  }`}
                                >
                                  {slowMode ? "🐢 0.75x 慢速磨耳朵" : "🐇 正常语速"}
                                </button>
                                {lastRecordUrl && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      if (!recordAudioRef.current) recordAudioRef.current = new Audio();
                                      recordAudioRef.current.src = lastRecordUrl;
                                      void recordAudioRef.current.play();
                                    }}
                                    className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-700 hover:bg-emerald-100"
                                  >
                                    <RotateCcw className="h-3 w-3" /> 回放我的录音
                                  </button>
                                )}
                              </div>
                            </div>

                            {/* 跟读星级评语卡 */}
                            {speechEval && (
                              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50/90 px-3 py-2 text-xs">
                                <div>
                                  <div className="flex items-center gap-1 font-extrabold text-amber-800">
                                    {Array.from({ length: 5 }).map((_, i) => (
                                      <Star
                                        key={i}
                                        className={`h-3.5 w-3.5 ${i < speechEval.stars ? "fill-amber-400 text-amber-500" : "text-amber-200"}`}
                                      />
                                    ))}
                                    <span className="ml-1">{speechEval.feedback}</span>
                                  </div>
                                  {speechEval.recognized_text && (
                                    <div className="mt-0.5 text-[11px] text-amber-700">
                                      识别内容：{speechEval.recognized_text}
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}

                            <div className="space-y-1.5">
                              {currentTrack.text_content
                                .split(/\n+|(?<=[.!?。！？])\s+/)
                                .map((line) => line.trim())
                                .filter((line) => line.length > 1)
                                .slice(0, 14)
                                .map((sentence, sIdx) => {
                                  const isRec = recordingSentence === sentence;
                                  return (
                                    <div
                                      key={sIdx}
                                      className="flex items-center justify-between gap-2 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-subtle)]/40 px-3 py-2 text-xs"
                                    >
                                      <button
                                        type="button"
                                        onClick={() => void handlePronounce(sentence)}
                                        className="flex min-w-0 flex-1 items-center gap-2 text-left hover:text-[var(--brand-primary)]"
                                      >
                                        <Volume2 className="h-3.5 w-3.5 shrink-0 text-[var(--brand-primary)]" />
                                        <span className="leading-relaxed">{sentence}</span>
                                      </button>
                                      <button
                                        type="button"
                                        disabled={Boolean(recordingSentence)}
                                        onClick={() => void handleFollowReadRecord(sentence, currentTrack.id)}
                                        className={`inline-flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1 text-[11px] font-bold transition ${
                                          isRec
                                            ? "animate-pulse bg-rose-500 text-white"
                                            : "border border-[var(--border-soft)] bg-white text-[var(--ink-secondary)] hover:border-[var(--brand-primary)] hover:text-[var(--brand-primary)]"
                                        }`}
                                      >
                                        <Mic className="h-3 w-3" /> {isRec ? "录音中..." : "跟读"}
                                      </button>
                                    </div>
                                  );
                                })}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="rounded-2xl border border-dashed border-[var(--border-soft)] p-6 text-center text-xs text-[var(--ink-muted)]">
                    本单元还没有音频课时，你可以给它上传 MP3 绘本音频。
                    <div className="mt-3">
                      <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-xl bg-[var(--brand-primary)] px-4 py-2 font-bold text-white">
                        <Upload className="h-3.5 w-3.5" /> 上传音频到本单元
                        <input
                          type="file"
                          accept="audio/*,.mp3,.m4a,.wav"
                          multiple
                          className="hidden"
                          onChange={async (e) => {
                            const fs = Array.from(e.target.files || []);
                            if (fs.length === 0) return;
                            for (const f of fs) {
                              await api.uploadAudio(currentSeason.id, f);
                            }
                            showToast(`已上传 ${fs.length} 课音频`);
                            await loadEnglishSeries();
                          }}
                        />
                      </label>
                    </div>
                  </div>
                )}
              </section>
            )}
          </div>
        </div>
      )}

      {/* AI 生成新启蒙单元弹窗 */}
      <Modal open={genOpen} title={`✨ AI 生成 ${activeLevelMeta.title} 新单元`} onClose={() => setGenOpen(false)} maxWidth="max-w-md">
        <form onSubmit={handleGenerateUnit} className="space-y-3 text-xs">
          <div className="rounded-xl bg-[var(--brand-green-soft)] p-3 text-[var(--brand-primary)]">
            输入孩子感兴趣的主题（如「恐龙冒险」「去超市买水果」「太空宇航员」），自动生成匹配 {activeLevelMeta.code} 难度的完整课时、词卡与双语音频。
          </div>
          <div>
            <label className="mb-1 block font-bold">主题名称</label>
            <input
              value={genTopic}
              onChange={(e) => setGenTopic(e.target.value)}
              placeholder="如：去动物园、恐龙世界、睡前晚安"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              required
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={() => setGenOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
              取消
            </button>
            <button
              type="submit"
              disabled={genBusy}
              className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white disabled:opacity-50"
            >
              {genBusy ? "正在生成课程..." : "立即生成"}
            </button>
          </div>
        </form>
      </Modal>

      {/* 导入自有分级英语音频弹窗 */}
      <Modal open={importOpen} title={`📤 导入音频到 ${activeLevelMeta.title}`} onClose={() => setImportOpen(false)} maxWidth="max-w-md">
        <form onSubmit={handleImportCustomEnglish} className="space-y-3 text-xs">
          <div className="grid grid-cols-4 gap-2">
            <div>
              <label className="mb-1 block font-bold">图标</label>
              <input
                value={importEmoji}
                onChange={(e) => setImportEmoji(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-center text-base"
              />
            </div>
            <div className="col-span-3">
              <label className="mb-1 block font-bold">分级系列名称</label>
              <input
                value={importTitle}
                onChange={(e) => setImportTitle(e.target.value)}
                placeholder="如：牛津树 Level 1、RAZ AA级、Peppa Pig"
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
                required
              />
            </div>
          </div>
          <div className="rounded-2xl border-2 border-dashed border-[var(--border-soft)] p-5 text-center">
            <input
              type="file"
              accept="audio/*,.mp3,.m4a,.wav,.flac"
              multiple
              onChange={(e) => setImportFiles(Array.from(e.target.files || []))}
              className="mx-auto block text-xs"
            />
            <div className="mt-2 text-[11px] text-[var(--ink-muted)]">
              可一次多选多个音频文件，系统自动编号排序并记忆播放进度
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={() => setImportOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
              取消
            </button>
            <button
              type="submit"
              disabled={importBusy}
              className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white disabled:opacity-50"
            >
              {importBusy ? "上传中..." : "创建并导入"}
            </button>
          </div>
        </form>
      </Modal>

      {/* 全网采集英语启蒙 */}
      <Modal open={aiCollectOpen} title={`🔍 全网采集英语到 ${activeLevel}`} onClose={() => setAiCollectOpen(false)} maxWidth="max-w-md">
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (!aiQuery.trim()) return;
            try {
              await api.aiCollect({
                query: aiQuery.trim(),
                channel_hint: "english",
                max_items: 5,
                device_id: aiDeviceId,
                notify_speaker: Boolean(aiDeviceId),
              });
              showToast(`已启动后台采集「${aiQuery.trim()}」，完成后自动归入英语启蒙并通知`);
              setAiCollectOpen(false);
            } catch (err) {
              showToast((err as Error).message);
            }
          }}
          className="space-y-3 text-xs"
        >
          <div>
            <label className="mb-1 block font-bold">采集内容关键词</label>
            <input
              value={aiQuery}
              onChange={(e) => setAiQuery(e.target.value)}
              placeholder="如：Super Simple Songs L1 儿歌、小猪佩奇英文故事"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2"
              required
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
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={() => setAiCollectOpen(false)} className="rounded-xl border px-4 py-2 font-semibold">
              取消
            </button>
            <button type="submit" className="rounded-xl bg-[var(--brand-primary)] px-5 py-2 font-bold text-white">
              开始采集
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
    </div>
  );
}
