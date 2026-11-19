import React, { useEffect, useState } from "react";
import {
  ArrowRightCircle,
  FileAudio,
  FolderOpen,
  FolderPlus,
  Inbox,
  Play,
  Plus,
  Rss,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import {
  AgeStage,
  api,
  ContentSource,
  DownloadJob,
  EnglishLevel,
  LocalFolder,
  MediaAlbum,
  MediaTrack,
  PodcastEpisode,
  SourcePreset,
} from "../api";
import { AGE_STAGE_LABELS, EmptyState, ENGLISH_LEVEL_LABELS, Modal } from "../components/Modal";
import { QueueItem } from "../components/PlayerBar";

type PipeId = "inbox" | "local" | "upload" | "rss" | "workshop";

export function StudioIngestPage({
  onPlayQueue,
  onRefreshDashboard,
  showToast,
}: {
  onPlayQueue: (items: QueueItem[], startIndex: number) => void;
  onRefreshDashboard: () => void;
  showToast: (m: string) => void;
}) {
  const [pipe, setPipe] = useState<PipeId>("inbox");
  const [inboxAlbums, setInboxAlbums] = useState<MediaAlbum[]>([]);
  const [formalAlbums, setFormalAlbums] = useState<MediaAlbum[]>([]);
  const [promoteTargets, setPromoteTargets] = useState<Record<number, number>>({});

  // 本地目录
  const [folders, setFolders] = useState<LocalFolder[]>([]);
  const [suggested, setSuggested] = useState<Array<{ name: string; path: string }>>([]);
  const [scanningId, setScanningId] = useState<number | null>(null);
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [fName, setFName] = useState("");
  const [fPath, setFPath] = useState("");
  const [fType, setFType] = useState<LocalFolder["media_type"]>("auto");

  // 批量上传
  const [uploadAlbId, setUploadAlbId] = useState<number>(0);
  const [uploading, setUploading] = useState(false);
  const [ytUrl, setYtUrl] = useState("");

  // 播客 RSS & 队列
  const [sources, setSources] = useState<ContentSource[]>([]);
  const [presets, setPresets] = useState<SourcePreset[]>([]);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [activeSrcEpisodes, setActiveSrcEpisodes] = useState<{ srcName: string; albumId: number | null; list: PodcastEpisode[] } | null>(null);
  const [srcModalOpen, setSrcModalOpen] = useState(false);
  const [sName, setSName] = useState("");
  const [sUrl, setSUrl] = useState("");
  const [sType, setSType] = useState<ContentSource["source_type"]>("podcast_rss");
  const [sAlbId, setSAlbId] = useState<number | "">("");

  // AI 创编工坊
  const [storyAlbId, setStoryAlbId] = useState<number>(0);
  const [storyTitle, setStoryTitle] = useState("");
  const [storyLang, setStoryLang] = useState("zh");
  const [storyText, setStoryText] = useState("");
  const [storyLoading, setStoryLoading] = useState(false);

  const [engTopic, setEngTopic] = useState("");
  const [engStage, setEngStage] = useState<Exclude<EnglishLevel, "adult">>("A1");
  const [engLoading, setEngLoading] = useState(false);

  const loadAll = async () => {
    const [inbox, formal, fldRes, srcList, presetList, jobList] = await Promise.all([
      api.getAlbums({ only_inbox: true }),
      api.getAlbums({ exclude_inbox: true }),
      api.listLocalFolders(),
      api.listSources(),
      api.getSourcePresets(),
      api.getJobs(),
    ]);
    setInboxAlbums(inbox);
    setFormalAlbums(formal);
    setFolders(fldRes.folders);
    setSuggested(fldRes.suggested_paths);
    setSources(srcList);
    setPresets(presetList);
    setJobs(jobList);
    if (formal.length > 0) {
      if (!uploadAlbId) setUploadAlbId(formal[0].id);
      if (!storyAlbId) {
        const storyOne = formal.find((a) => a.category === "story") || formal[0];
        setStoryAlbId(storyOne.id);
      }
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  const inboxTracks = inboxAlbums.flatMap((alb) =>
    (alb.tracks || []).map((t) => ({ track: t, alb }))
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight">五大标准化内容填充中心</h2>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
            无论来自语音缓存、本地磁盘、文件上传、RSS 播客追更还是 AI 文本创编，所有音频统一通过 `-16 LUFS` 护耳校准入库对应专辑。
          </p>
        </div>
        <button
          onClick={async () => {
            showToast("正在为您导入全年龄段示范书籍、专辑音频、6 套英语系列课及播客预设…");
            const r = await api.adminSeedSampleCatalog();
            showToast(
              `已补齐 ${r.books_added} 本书、${r.albums_added} 张专辑、${r.tracks_added} 首示范音、${r.courses_added || 0} 套英语系列课`
            );
            await loadAll();
            onRefreshDashboard();
          }}
          className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-green)] bg-[var(--brand-green-soft)] px-4 py-2 text-xs font-semibold text-[var(--brand-green)]"
        >
          <Sparkles className="h-4 w-4" /> 一键导入 / 补全全龄示范内容包
        </button>
      </div>

      {/* 5 大管道切换 */}
      <div className="flex flex-wrap gap-2 border-b border-[var(--border-soft)] pb-3">
        {[
          { id: "inbox", label: `📥 1. 语音缓存收件箱 (${inboxTracks.length})` },
          { id: "local", label: `📂 2. 本地目录映射扫描 (${folders.length})` },
          { id: "upload", label: "⬆️ 3. 批量上传与链接抓取" },
          { id: "rss", label: `📡 4. 播客 RSS 订阅追更 (${sources.length})` },
          { id: "workshop", label: "✨ 5. AI 绘本合音与英语制课" },
        ].map((p) => (
          <button
            key={p.id}
            onClick={() => setPipe(p.id as PipeId)}
            className={`rounded-xl px-3.5 py-2 text-xs font-semibold transition ${
              pipe === p.id
                ? "bg-[var(--brand-green)] text-white shadow-xs"
                : "border border-[var(--border-soft)] bg-white text-zinc-700 hover:bg-zinc-50"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* ---------------- 管道 1：语音缓存收件箱 ---------------- */}
      {pipe === "inbox" && (
        <section className="card-pro overflow-hidden">
          <div className="border-b border-[var(--border-soft)] bg-zinc-50/70 px-5 py-3 text-xs font-bold">
            自动缓存池单曲（家人通过语音或在线点播自动落盘的歌曲/故事，可试听后一键归档转正到正式专辑）
          </div>
          {inboxTracks.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title="缓存收件箱暂无待整理歌曲"
              description="当家人在前台搜歌或通过语音点播未收藏的歌曲时，系统会实时播放并自动存入此处等待您的整理。"
            />
          ) : (
            <div className="divide-y divide-[var(--border-soft)]">
              {inboxTracks.map(({ track: t, alb }) => (
                <div key={t.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 text-xs">
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <button
                      onClick={() =>
                        onPlayQueue(
                          [
                            {
                              id: t.id,
                              kind: "track",
                              title: t.title,
                              subtitle: alb.title,
                              streamUrl: t.stream_url || `/api/media/tracks/${t.id}/stream`,
                              parentId: alb.id,
                              durationSec: t.duration_sec,
                            },
                          ],
                          0
                        )
                      }
                      className="rounded-lg bg-[var(--brand-green-soft)] p-2 text-[var(--brand-green)]"
                    >
                      <Play className="h-3.5 w-3.5 fill-current" />
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-bold">{t.title}</div>
                      <div className="truncate text-[11px] text-[var(--ink-muted)]">
                        所在收件箱：{alb.title} · {Math.round(t.duration_sec)} 秒
                      </div>
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                    <select
                      value={promoteTargets[t.id] || ""}
                      onChange={(e) => setPromoteTargets((p) => ({ ...p, [t.id]: Number(e.target.value) }))}
                      className="rounded-xl border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs"
                    >
                      <option value="">选目标正式专辑...</option>
                      {formalAlbums.map((fa) => (
                        <option key={fa.id} value={fa.id}>
                          {fa.title}
                        </option>
                      ))}
                    </select>
                    <button
                      disabled={!promoteTargets[t.id]}
                      onClick={async () => {
                        const tid = promoteTargets[t.id];
                        if (!tid) return;
                        await api.updateTrack(t.id, { album_id: tid });
                        showToast(`已归档《${t.title}》到正式专辑`);
                        await loadAll();
                        onRefreshDashboard();
                      }}
                      className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-green)] px-3 py-1.5 font-semibold text-white disabled:opacity-40"
                    >
                      <ArrowRightCircle className="h-3.5 w-3.5" /> 归档转正
                    </button>
                    <button
                      onClick={async () => {
                        await api.deleteTrack(t.id);
                        showToast("已删除该缓存");
                        await loadAll();
                      }}
                      className="rounded-xl border border-[var(--border-soft)] p-1.5 text-zinc-400 hover:text-rose-600"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ---------------- 管道 2：本地目录映射与扫描 ---------------- */}
      {pipe === "local" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-[var(--ink-muted)]">
              将磁盘文件夹映射到中枢：`books/` / `绘本` 子目录自动建入绘本故事，同名 `.txt` 自动做伴读文稿，其余归为音乐专辑。
            </span>
            <button
              onClick={() => {
                setFName("");
                setFPath("");
                setFolderModalOpen(true);
              }}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-4 py-2 text-xs font-semibold text-white"
            >
              <FolderPlus className="h-4 w-4" /> 挂载新本地目录
            </button>
          </div>
          <div className="space-y-3">
            {folders.map((f) => (
              <div key={f.id} className="card-pro flex flex-wrap items-center justify-between gap-3 p-4 text-xs">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-bold text-sm">
                    <FolderOpen className="h-4 w-4 text-[var(--brand-green)]" />
                    <span>{f.name}</span>
                    <span className="rounded bg-zinc-100 px-2 py-0.5 text-[11px] font-normal">已索引 {f.file_count} 文件</span>
                  </div>
                  <div className="mt-1 truncate font-mono text-[var(--ink-muted)]">{f.folder_path}</div>
                  <div className="mt-0.5 text-zinc-600">{f.last_scan_summary}</div>
                </div>
                <div className="flex gap-2">
                  <button
                    disabled={scanningId === f.id}
                    onClick={async () => {
                      setScanningId(f.id);
                      try {
                        const r = await api.scanLocalFolder(f.id);
                        showToast(r.summary);
                        await loadAll();
                        onRefreshDashboard();
                      } finally {
                        setScanningId(null);
                      }
                    }}
                    className="rounded-xl bg-[var(--brand-green)] px-4 py-2 font-semibold text-white disabled:opacity-50"
                  >
                    {scanningId === f.id ? "扫描入库中…" : "立即扫描入库"}
                  </button>
                  <button
                    onClick={async () => {
                      await api.deleteLocalFolder(f.id);
                      await loadAll();
                    }}
                    className="rounded-xl border border-[var(--border-soft)] p-2 text-zinc-400 hover:text-rose-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---------------- 管道 3：批量上传与网址抓取 ---------------- */}
      {pipe === "upload" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <section className="card-pro space-y-4 p-5 text-xs">
            <h3 className="text-sm font-bold">⬆️ 批量上传本地 MP3 / M4A / WAV 音频入专辑</h3>
            <div>
              <label className="mb-1 block font-semibold">1. 选择入库目标专辑：</label>
              <select
                value={uploadAlbId}
                onChange={(e) => setUploadAlbId(Number(e.target.value))}
                className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
              >
                {formalAlbums.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.title} ({a.category})
                  </option>
                ))}
              </select>
            </div>
            <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-[var(--brand-green)] bg-[var(--brand-green-soft)]/30 py-8 font-bold text-[var(--brand-green)] hover:bg-[var(--brand-green-soft)]/50">
              <Upload className="h-6 w-6" />
              <span>{uploading ? "正在上传并校准 -16 LUFS…" : "点击选择多个本地音频文件"}</span>
              <input
                type="file"
                accept="audio/*"
                multiple
                disabled={!uploadAlbId || uploading}
                className="hidden"
                onChange={async (e) => {
                  const files = Array.from(e.target.files || []);
                  if (!files.length || !uploadAlbId) return;
                  setUploading(true);
                  try {
                    for (const f of files) await api.uploadAudio(uploadAlbId, f);
                    showToast(`已成功上传并护耳入库 ${files.length} 首曲目`);
                    await loadAll();
                    onRefreshDashboard();
                  } finally {
                    setUploading(false);
                  }
                }}
              />
            </label>
          </section>

          <section className="card-pro space-y-4 p-5 text-xs">
            <h3 className="text-sm font-bold">🌐 粘贴 B站 / YouTube / 合集链接批量抓取</h3>
            <p className="text-[var(--ink-muted)]">支持单个视频或整个系列合集链接，后台自动提取音频流并执行 -16 LUFS 响度均衡入选定专辑。</p>
            <input
              value={ytUrl}
              onChange={(e) => setYtUrl(e.target.value)}
              placeholder="https://www.bilibili.com/video/... 或 YouTube URL"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2.5 text-sm"
            />
            <button
              disabled={!uploadAlbId || !ytUrl.trim()}
              onClick={async () => {
                await api.collectYtdlp(ytUrl.trim(), uploadAlbId, 10);
                setYtUrl("");
                showToast("已加入后台抓取与护耳校准队列");
                await loadAll();
              }}
              className="w-full rounded-xl bg-[var(--brand-amber)] py-2.5 font-semibold text-white disabled:opacity-40"
            >
              提交抓取并入库到上方选定专辑
            </button>

            {jobs.length > 0 && (
              <div className="space-y-1.5 border-t border-[var(--border-soft)] pt-3">
                <div className="font-bold">最近任务队列：</div>
                {jobs.slice(0, 4).map((j) => (
                  <div key={j.id} className="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-1.5">
                    <span className="truncate">{j.progress_text}</span>
                    <span className="ml-2 shrink-0 font-semibold">{j.status}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      {/* ---------------- 管道 4：播客 RSS 订阅追更 ---------------- */}
      {pipe === "rss" && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-[var(--ink-muted)]">配置持久化 RSS 播客与频道，支持开启自动定期追更或单集点抓入库。</span>
            <button
              onClick={() => setSrcModalOpen(true)}
              className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-green)] px-4 py-2 text-xs font-semibold text-white"
            >
              <Plus className="h-4 w-4" /> 新增自定义 RSS / 合集源
            </button>
          </div>

          <div className="space-y-3">
            {sources.map((s) => (
              <div key={s.id} className="card-pro flex flex-wrap items-center justify-between gap-3 p-4 text-xs">
                <div className="min-w-0 flex-1">
                  <div className="font-bold text-sm">{s.name}</div>
                  <div className="truncate text-[var(--ink-muted)]">{s.url}</div>
                  <div className="mt-1 text-zinc-600">状态：{s.last_status} ｜ 目标专辑：{s.album_title || "自动创建"}</div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={async () => {
                      showToast("正在拉取节目单集…");
                      const r = await api.getSourceEpisodes(s.id);
                      setActiveSrcEpisodes({ srcName: s.name, albumId: s.target_album_id, list: r.episodes });
                    }}
                    className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5 font-medium"
                  >
                    预览单集
                  </button>
                  <button
                    onClick={async () => {
                      await api.syncSource(s.id);
                      showToast(`已触发「${s.name}」后台增量同步`);
                    }}
                    className="rounded-xl bg-[var(--brand-amber)] px-3 py-1.5 font-semibold text-white"
                  >
                    立即同步
                  </button>
                  <button
                    onClick={async () => {
                      await api.updateSource(s.id, { auto_sync: !s.auto_sync });
                      await loadAll();
                    }}
                    className={`rounded-xl px-3 py-1.5 font-medium ${s.auto_sync ? "bg-[var(--brand-green)] text-white" : "bg-zinc-200 text-zinc-600"}`}
                  >
                    {s.auto_sync ? "自动同步开" : "已暂停"}
                  </button>
                  <button
                    onClick={async () => {
                      await api.deleteSource(s.id);
                      await loadAll();
                    }}
                    className="rounded-xl border border-[var(--border-soft)] p-1.5 text-zinc-400 hover:text-rose-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {activeSrcEpisodes && (
            <section className="card-pro p-4 text-xs">
              <div className="mb-2 flex items-center justify-between font-bold">
                <span>《{activeSrcEpisodes.srcName}》单集预览（点击抓入专辑）</span>
                <button onClick={() => setActiveSrcEpisodes(null)} className="text-zinc-400">收起</button>
              </div>
              <div className="max-h-60 space-y-1.5 overflow-y-auto">
                {activeSrcEpisodes.list.map((ep, idx) => (
                  <div key={ep.guid + idx} className="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-2">
                    <span className="truncate font-medium">{ep.title}</span>
                    {ep.cached ? (
                      <span className="ml-2 shrink-0 text-emerald-700 font-semibold">✓ 已入本地</span>
                    ) : (
                      <button
                        onClick={async () => {
                          await api.playAndCache({
                            title: ep.title,
                            url: ep.audio_url,
                            category: "podcast",
                            album_id: activeSrcEpisodes.albumId,
                            external_guid: ep.guid,
                          });
                          showToast(`已提交后台抓取保存《${ep.title}》`);
                        }}
                        className="ml-2 shrink-0 rounded-lg bg-[var(--brand-green)] px-2.5 py-1 text-white"
                      >
                        缓存入库
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 精选预设 */}
          <section className="card-pro p-4">
            <div className="mb-2 text-xs font-bold">精选播客推荐预设（一键订阅）：</div>
            <div className="grid gap-2.5 md:grid-cols-2">
              {presets.map((p) => (
                <div key={p.url} className="flex items-center justify-between gap-2 rounded-xl bg-zinc-50 p-3 text-xs">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-bold">{p.name}</div>
                    <div className="truncate text-[11px] text-[var(--ink-muted)]">{p.description}</div>
                  </div>
                  <button
                    onClick={async () => {
                      await api.createSource({ ...p, auto_sync: false, max_items_per_sync: 5 });
                      showToast(`已订阅「${p.name}」`);
                      await loadAll();
                    }}
                    className="shrink-0 rounded-lg bg-[var(--brand-green)] px-3 py-1.5 font-semibold text-white"
                  >
                    + 订阅
                  </button>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {/* ---------------- 管道 5：AI 绘本合音 & 英语制课 ---------------- */}
      {pipe === "workshop" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <section className="card-pro space-y-3 p-5 text-xs">
            <div className="flex items-center gap-2 text-sm font-bold">
              <FileAudio className="h-4 w-4 text-[var(--brand-green)]" /> 绘本 / 故事文本一键合成有声单集
            </div>
            <select
              value={storyAlbId}
              onChange={(e) => setStoryAlbId(Number(e.target.value))}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
            >
              {formalAlbums.map((a) => (
                <option key={a.id} value={a.id}>
                  入库专辑：{a.title}
                </option>
              ))}
            </select>
            <div className="grid gap-2 sm:grid-cols-3">
              <input
                value={storyTitle}
                onChange={(e) => setStoryTitle(e.target.value)}
                placeholder="单集 / 章节标题 *"
                className="sm:col-span-2 rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
              />
              <select value={storyLang} onChange={(e) => setStoryLang(e.target.value)} className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
                <option value="zh">中文朗读</option>
                <option value="en">纯英朗读</option>
                <option value="bilingual">中英双语</option>
              </select>
            </div>
            <textarea
              value={storyText}
              onChange={(e) => setStoryText(e.target.value)}
              rows={4}
              placeholder="粘贴绘本故事全文，自动合成 -16 LUFS 语音单集并保留文稿供前台伴读…"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
            />
            <button
              disabled={storyLoading || !storyAlbId || !storyTitle.trim() || !storyText.trim()}
              onClick={async () => {
                setStoryLoading(true);
                try {
                  await api.addTrackFromText(storyAlbId, { title: storyTitle, text_content: storyText, language: storyLang });
                  setStoryTitle("");
                  setStoryText("");
                  showToast("已合成有声单集并保存至该专辑");
                  onRefreshDashboard();
                } finally {
                  setStoryLoading(false);
                }
              }}
              className="w-full rounded-xl bg-[var(--brand-green)] py-2.5 font-semibold text-white disabled:opacity-45"
            >
              {storyLoading ? "正在合成语音…" : "合成护耳有声单集"}
            </button>
          </section>

          <section className="card-pro space-y-3 p-5 text-xs">
            <div className="flex items-center gap-2 text-sm font-bold">
              <Sparkles className="h-4 w-4 text-[var(--brand-amber)]" /> 英语主题系列课一键定制生成（自动成为标准专辑）
            </div>
            <p className="text-[var(--ink-muted)]">
              输入孩子的兴趣主题，AI 将一次性编排生成一套含 4 节渐进课时、核心词卡与伴学讲稿的英语专辑！
            </p>
            <input
              value={engTopic}
              onChange={(e) => setEngTopic(e.target.value)}
              placeholder="输入兴趣主题（如：恐龙世界探险 / 太空漫游 / 奇妙厨房）"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2.5 text-sm"
            />
            <select
              value={engStage}
              onChange={(e) => setEngStage(e.target.value as Exclude<EnglishLevel, "adult">)}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
            >
              {Object.entries(ENGLISH_LEVEL_LABELS)
                .filter(([k]) => k !== "adult")
                .map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
            </select>
            <button
              disabled={engLoading || !engTopic.trim()}
              onClick={async () => {
                setEngLoading(true);
                try {
                  const res = await api.generateEnglishCourse({ topic: engTopic, stage: engStage });
                  setEngTopic("");
                  showToast(`已生成英语课程专辑《${res.title}》（${res.total_lessons} 课时）`);
                  await loadAll();
                  onRefreshDashboard();
                } finally {
                  setEngLoading(false);
                }
              }}
              className="w-full rounded-xl bg-[var(--brand-amber)] py-2.5 font-semibold text-white disabled:opacity-45"
            >
              {engLoading ? "正在生成系列课程…" : "立即生成 4 节定制英语系列课专辑"}
            </button>
          </section>
        </div>
      )}

      {/* 挂载目录 Modal */}
      <Modal open={folderModalOpen} title="挂载本机磁盘目录" onClose={() => setFolderModalOpen(false)}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            await api.createLocalFolder({ name: fName, folder_path: fPath, media_type: fType, age_stage: "S6_ALL" });
            setFolderModalOpen(false);
            showToast("目录挂载成功，请点击扫描入库");
            await loadAll();
          }}
          className="space-y-3 text-xs"
        >
          {suggested.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {suggested.map((sp) => (
                <button
                  key={sp.path}
                  type="button"
                  onClick={() => { setFName(sp.name); setFPath(sp.path); }}
                  className="rounded-lg bg-zinc-100 px-2.5 py-1 hover:bg-zinc-200"
                >
                  填入 {sp.name}
                </button>
              ))}
            </div>
          )}
          <input required value={fName} onChange={(e) => setFName(e.target.value)} placeholder="目录名称 *" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
          <input required value={fPath} onChange={(e) => setFPath(e.target.value)} placeholder="/Users/.../Music *" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 font-mono text-xs" />
          <select value={fType} onChange={(e) => setFType(e.target.value as LocalFolder["media_type"])} className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
            <option value="auto">智能按子目录自动归类</option>
            <option value="music">全部归入音乐</option>
            <option value="story">全部归入故事</option>
            <option value="book">全部归入绘本/图书</option>
          </select>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setFolderModalOpen(false)} className="rounded-xl border px-4 py-2">取消</button>
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">确认挂载</button>
          </div>
        </form>
      </Modal>

      {/* 新增 RSS 源 Modal */}
      <Modal open={srcModalOpen} title="新增 RSS / 合集订阅源" onClose={() => setSrcModalOpen(false)}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            await api.createSource({
              name: sName,
              source_type: sType,
              url: sUrl,
              target_album_id: sAlbId === "" ? null : Number(sAlbId),
              auto_sync: true,
              max_items_per_sync: 5,
            });
            setSrcModalOpen(false);
            setSName("");
            setSUrl("");
            showToast("订阅源已保存");
            await loadAll();
            onRefreshDashboard();
          }}
          className="space-y-3 text-xs"
        >
          <input required value={sName} onChange={(e) => setSName(e.target.value)} placeholder="名称 *" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
          <select value={sType} onChange={(e) => setSType(e.target.value as ContentSource["source_type"])} className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
            <option value="podcast_rss">播客 RSS XML 订阅</option>
            <option value="ytdlp_playlist">B站 / YouTube 合集链接</option>
          </select>
          <input required value={sUrl} onChange={(e) => setSUrl(e.target.value)} placeholder="https://... *" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
          <select value={sAlbId} onChange={(e) => setSAlbId(e.target.value ? Number(e.target.value) : "")} className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
            <option value="">自动按源名称创建专辑</option>
            {formalAlbums.map((a) => <option key={a.id} value={a.id}>同步到：{a.title}</option>)}
          </select>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setSrcModalOpen(false)} className="rounded-xl border px-4 py-2">取消</button>
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">确认添加</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
