import React, { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Edit3,
  Library,
  Play,
  Plus,
  Search,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import { AgeStage, api, CategoryTag, EnglishLevel, MediaAlbum, MediaTrack } from "../api";
import { AGE_STAGE_LABELS, ConfirmDialog, ENGLISH_LEVEL_LABELS, Modal, SlideDrawer } from "../components/Modal";
import { QueueItem } from "../components/PlayerBar";

const CHANNELS: Array<{ id: MediaAlbum["category"]; label: string }> = [
  { id: "music", label: "🎵 音乐与儿歌" },
  { id: "story", label: "📖 绘本与故事" },
  { id: "english", label: "🎓 英语伴学课" },
  { id: "podcast", label: "🎙️ 科普与播客" },
];

export function StudioCatalogPage({
  initialAlbumId,
  onPlayQueue,
  onRefreshDashboard,
  showToast,
}: {
  initialAlbumId?: number | null;
  onPlayQueue: (items: QueueItem[], startIndex: number) => void;
  onRefreshDashboard: () => void;
  showToast: (m: string) => void;
}) {
  const [tags, setTags] = useState<CategoryTag[]>([]);
  const [albums, setAlbums] = useState<MediaAlbum[]>([]);
  const [channelFilter, setChannelFilter] = useState<string>("all");
  const [searchQ, setSearchQ] = useState("");

  // 标签新增输入
  const [tagChannel, setTagChannel] = useState<MediaAlbum["category"]>("music");
  const [newTagName, setNewTagName] = useState("");

  // 新建/编辑专辑弹窗
  const [albModalOpen, setAlbModalOpen] = useState(false);
  const [editingAlb, setEditingAlb] = useState<MediaAlbum | null>(null);
  const [albTitle, setAlbTitle] = useState("");
  const [albCat, setAlbCat] = useState<MediaAlbum["category"]>("music");
  const [albTag, setAlbTag] = useState("");
  const [albStage, setAlbStage] = useState<AgeStage>("S6_ALL");
  const [albEng, setAlbEng] = useState<EnglishLevel>("Pre_A1");
  const [albMode, setAlbMode] = useState<MediaAlbum["play_mode"]>("sequential");
  const [albEmoji, setAlbEmoji] = useState("🎵");
  const [albDesc, setAlbDesc] = useState("");

  // 单集编排抽屉
  const [drawerAlbId, setDrawerAlbId] = useState<number | null>(initialAlbumId || null);
  const [editingTrack, setEditingTrack] = useState<{ id: number; title: string; text_content: string } | null>(null);
  const [moveTargets, setMoveTargets] = useState<Record<number, number>>({});
  const [deleteAlbTarget, setDeleteAlbTarget] = useState<MediaAlbum | null>(null);

  const drawerAlb = albums.find((a) => a.id === drawerAlbId) || null;

  const loadAll = async () => {
    const [tList, aList] = await Promise.all([
      api.listTags(),
      api.getAlbums({ category: channelFilter === "all" ? undefined : channelFilter, q: searchQ.trim() || undefined }),
    ]);
    setTags(tList);
    setAlbums(aList);
  };

  useEffect(() => {
    void loadAll();
  }, [channelFilter]);

  useEffect(() => {
    if (initialAlbumId) setDrawerAlbId(initialAlbumId);
  }, [initialAlbumId]);

  const openCreateAlb = () => {
    setEditingAlb(null);
    setAlbTitle("");
    setAlbCat("music");
    setAlbTag("");
    setAlbStage("S6_ALL");
    setAlbEng("Pre_A1");
    setAlbMode("sequential");
    setAlbEmoji("🎵");
    setAlbDesc("");
    setAlbModalOpen(true);
  };

  const openEditAlb = (a: MediaAlbum) => {
    setEditingAlb(a);
    setAlbTitle(a.title);
    setAlbCat(a.category);
    setAlbTag(a.sub_tag || "");
    setAlbStage(a.age_stage);
    setAlbEng(a.english_level);
    setAlbMode(a.play_mode);
    setAlbEmoji(a.cover_emoji || "🎵");
    setAlbDesc(a.description || "");
    setAlbModalOpen(true);
  };

  const moveOrder = async (alb: MediaAlbum, idx: number, delta: number) => {
    const trs = alb.tracks || [];
    const swapIdx = idx + delta;
    if (swapIdx < 0 || swapIdx >= trs.length) return;
    await Promise.all([
      api.updateTrack(trs[idx].id, { episode_num: trs[swapIdx].episode_num }),
      api.updateTrack(trs[swapIdx].id, { episode_num: trs[idx].episode_num }),
    ]);
    await loadAll();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight">专辑编目与二级分类管理</h2>
          <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
            统一定义四大频道下的二级分类标签，批量修正任意专辑的分龄、频道标签，并支持单集调序、文稿编辑与跨专辑转移。
          </p>
        </div>
        <button
          onClick={openCreateAlb}
          className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-4 py-2.5 text-xs font-semibold text-white"
        >
          <Plus className="h-4 w-4" /> 新建标准专辑
        </button>
      </div>

      {/* 模块 A：二级分类标签管理 */}
      <section className="card-pro space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-soft)] pb-3">
          <div className="flex items-center gap-2 text-sm font-bold">
            <Tag className="h-4 w-4 text-[var(--brand-green)]" /> 一级频道 · 二级分类标签体系
          </div>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!newTagName.trim()) return;
              try {
                await api.createTag({ channel: tagChannel, name: newTagName.trim() });
                setNewTagName("");
                showToast("二级标签已添加");
                await loadAll();
              } catch (err) {
                showToast((err as Error).message);
              }
            }}
            className="flex flex-wrap items-center gap-2 text-xs"
          >
            <select
              value={tagChannel}
              onChange={(e) => setTagChannel(e.target.value as MediaAlbum["category"])}
              className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5"
            >
              {CHANNELS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
            <input
              value={newTagName}
              onChange={(e) => setNewTagName(e.target.value)}
              placeholder="新增二级标签（如：哄睡白噪音）"
              className="rounded-xl border border-[var(--border-soft)] px-3 py-1.5"
            />
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-3.5 py-1.5 font-semibold text-white">
              + 新增标签
            </button>
          </form>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {CHANNELS.map((c) => {
            const chTags = tags.filter((t) => t.channel === c.id);
            return (
              <div key={c.id} className="rounded-xl bg-zinc-50 p-3.5">
                <div className="mb-2 text-xs font-bold text-zinc-700">{c.label}</div>
                <div className="flex flex-wrap gap-1.5">
                  {chTags.length === 0 ? (
                    <span className="text-[11px] text-[var(--ink-muted)]">暂无二级标签</span>
                  ) : (
                    chTags.map((tg) => (
                      <span
                        key={tg.id}
                        className="inline-flex items-center gap-1 rounded-full border border-[var(--border-soft)] bg-white px-2.5 py-1 text-xs font-medium text-zinc-700"
                      >
                        #{tg.name}
                        <button
                          onClick={async () => {
                            await api.deleteTag(tg.id);
                            showToast(`已移除标签 #${tg.name}`);
                            await loadAll();
                          }}
                          className="ml-0.5 rounded-full p-0.5 text-zinc-400 hover:bg-rose-50 hover:text-rose-600"
                          title="删除标签"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 模块 B：全站专辑编目总表 */}
      <section className="card-pro overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-soft)] bg-zinc-50/70 px-5 py-3.5">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Library className="h-4 w-4 text-[var(--brand-green)]" />
            <span className="font-bold">全站专辑编目总表（{albums.length}）</span>
            <select
              value={channelFilter}
              onChange={(e) => setChannelFilter(e.target.value)}
              className="ml-2 rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1"
            >
              <option value="all">全部频道</option>
              {CHANNELS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <div className="relative">
              <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-zinc-400" />
              <input
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void loadAll()}
                placeholder="筛选专辑或单集..."
                className="rounded-xl border border-[var(--border-soft)] bg-white py-1.5 pl-8 pr-3"
              />
            </div>
            <button onClick={() => void loadAll()} className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5">
              筛选
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[780px] border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-[var(--border-soft)] bg-zinc-50 text-[11px] text-[var(--ink-muted)]">
                <th className="px-4 py-3">专辑名称</th>
                <th className="px-4 py-3">所属频道</th>
                <th className="px-4 py-3">二级标签（实时改）</th>
                <th className="px-4 py-3">适龄阶段（实时改）</th>
                <th className="px-4 py-3">集数</th>
                <th className="px-4 py-3 text-right">维护操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-soft)]">
              {albums.map((a) => {
                const availTags = tags.filter((t) => t.channel === a.category);
                return (
                  <tr key={a.id} className="hover:bg-zinc-50/60">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-base">{a.cover_emoji || "💿"}</span>
                        <div>
                          <div className="font-bold">
                            {a.title}
                            {a.is_inbox === 1 && (
                              <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                                缓存收件箱
                              </span>
                            )}
                          </div>
                          {a.author && <div className="text-[10px] text-[var(--ink-muted)]">{a.author}</div>}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={a.category}
                        onChange={async (e) => {
                          await api.updateAlbum(a.id, { category: e.target.value as MediaAlbum["category"], sub_tag: "" });
                          showToast(`已切换《${a.title}》频道`);
                          await loadAll();
                          onRefreshDashboard();
                        }}
                        className="rounded-lg border border-[var(--border-soft)] bg-white px-2 py-1"
                      >
                        {CHANNELS.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={a.sub_tag || ""}
                        onChange={async (e) => {
                          await api.updateAlbum(a.id, { sub_tag: e.target.value });
                          showToast(`已调整二级分类为 #${e.target.value || "未分类"}`);
                          await loadAll();
                        }}
                        className="rounded-lg border border-[var(--border-soft)] bg-white px-2 py-1"
                      >
                        <option value="">-- 未归类 --</option>
                        {availTags.map((tg) => (
                          <option key={tg.id} value={tg.name}>
                            #{tg.name}
                          </option>
                        ))}
                        {a.sub_tag && !availTags.some((t) => t.name === a.sub_tag) && (
                          <option value={a.sub_tag}>#{a.sub_tag}</option>
                        )}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={a.age_stage}
                        onChange={async (e) => {
                          await api.updateAlbum(a.id, { age_stage: e.target.value as AgeStage });
                          showToast(`已修改《${a.title}》适龄阶段`);
                          await loadAll();
                        }}
                        className="rounded-lg border border-[var(--border-soft)] bg-white px-2 py-1"
                      >
                        {Object.entries(AGE_STAGE_LABELS).map(([k, v]) => (
                          <option key={k} value={k}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 font-semibold">{(a.tracks || []).length} 集</td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex gap-1.5">
                        <button
                          onClick={() => setDrawerAlbId(a.id)}
                          className="rounded-lg bg-[var(--brand-green-soft)] px-2.5 py-1.5 font-semibold text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)]"
                        >
                          编排单集 ({(a.tracks || []).length})
                        </button>
                        <button
                          onClick={() => openEditAlb(a)}
                          className="rounded-lg border border-[var(--border-soft)] bg-white p-1.5 text-zinc-600"
                          title="编辑资料"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => setDeleteAlbTarget(a)}
                          className="rounded-lg border border-rose-200 bg-rose-50 p-1.5 text-rose-600"
                          title="删除专辑"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* 单集编排抽屉 */}
      <SlideDrawer open={!!drawerAlb} title={`单集编排：${drawerAlb?.title || ""}`} onClose={() => setDrawerAlbId(null)}>
        {drawerAlb && (
          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between rounded-xl bg-zinc-50 p-3">
              <span>共 {(drawerAlb.tracks || []).length} 集 · 支持调序、修改文稿或转移到其他专辑</span>
              {(drawerAlb.tracks || []).length > 0 && (
                <button
                  onClick={() =>
                    onPlayQueue(
                      (drawerAlb.tracks || []).map((t) => ({
                        id: t.id,
                        kind: "track",
                        title: t.title,
                        subtitle: drawerAlb.title,
                        streamUrl: t.stream_url || `/api/media/tracks/${t.id}/stream`,
                        parentId: drawerAlb.id,
                        durationSec: t.duration_sec,
                      })),
                      0
                    )
                  }
                  className="inline-flex items-center gap-1 rounded-lg bg-[var(--brand-green)] px-2.5 py-1 font-semibold text-white"
                >
                  <Play className="h-3 w-3" /> 试听全辑
                </button>
              )}
            </div>

            {(drawerAlb.tracks || []).map((t: MediaTrack, idx: number) => (
              <div key={t.id} className="space-y-2 rounded-xl border border-[var(--border-soft)] p-3">
                {editingTrack?.id === t.id ? (
                  <div className="space-y-2">
                    <input
                      value={editingTrack.title}
                      onChange={(e) => setEditingTrack({ ...editingTrack, title: e.target.value })}
                      className="w-full rounded-lg border px-2.5 py-1.5"
                    />
                    <textarea
                      value={editingTrack.text_content}
                      onChange={(e) => setEditingTrack({ ...editingTrack, text_content: e.target.value })}
                      rows={3}
                      placeholder="可选：伴读原文或课程讲稿"
                      className="w-full rounded-lg border px-2.5 py-1.5"
                    />
                    <div className="flex justify-end gap-1.5">
                      <button onClick={() => setEditingTrack(null)} className="rounded-lg border px-2.5 py-1">
                        取消
                      </button>
                      <button
                        onClick={async () => {
                          await api.updateTrack(t.id, { title: editingTrack.title, text_content: editingTrack.text_content });
                          setEditingTrack(null);
                          showToast("单集已保存");
                          await loadAll();
                        }}
                        className="rounded-lg bg-[var(--brand-green)] px-3 py-1 font-semibold text-white"
                      >
                        保存
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-bold">
                          {t.episode_num}. {t.title}
                        </div>
                        <div className="text-[11px] text-[var(--ink-muted)]">{Math.round(t.duration_sec)}s · 已播 {t.play_count} 次</div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button onClick={() => moveOrder(drawerAlb, idx, -1)} className="rounded p-1 hover:bg-zinc-100">
                          <ArrowUp className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => moveOrder(drawerAlb, idx, 1)} className="rounded p-1 hover:bg-zinc-100">
                          <ArrowDown className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => setEditingTrack({ id: t.id, title: t.title, text_content: t.text_content || "" })}
                          className="rounded p-1.5 text-zinc-500 hover:bg-zinc-100"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={async () => {
                            await api.deleteTrack(t.id);
                            await loadAll();
                          }}
                          className="rounded p-1.5 text-zinc-400 hover:text-rose-600"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>

                    {/* 跨专辑转移 */}
                    <div className="flex items-center gap-1.5 border-t border-zinc-100 pt-2">
                      <select
                        value={moveTargets[t.id] || ""}
                        onChange={(e) => setMoveTargets((p) => ({ ...p, [t.id]: Number(e.target.value) }))}
                        className="min-w-0 flex-1 rounded-lg border border-[var(--border-soft)] bg-zinc-50 px-2 py-1 text-[11px]"
                      >
                        <option value="">转移到其他正式专辑...</option>
                        {albums
                          .filter((other) => other.id !== drawerAlb.id && other.is_inbox !== 1)
                          .map((other) => (
                            <option key={other.id} value={other.id}>
                              {other.title}
                            </option>
                          ))}
                      </select>
                      <button
                        disabled={!moveTargets[t.id]}
                        onClick={async () => {
                          const targetId = moveTargets[t.id];
                          if (!targetId) return;
                          await api.updateTrack(t.id, { album_id: targetId });
                          showToast(`已将《${t.title}》转移至目标专辑`);
                          await loadAll();
                        }}
                        className="rounded-lg bg-zinc-800 px-2.5 py-1 text-[11px] font-medium text-white disabled:opacity-35"
                      >
                        确认转移
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </SlideDrawer>

      {/* 新建 / 编辑专辑弹窗 */}
      <Modal open={albModalOpen} title={editingAlb ? "编辑标准专辑" : "新建标准专辑"} onClose={() => setAlbModalOpen(false)}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const payload = {
              title: albTitle,
              category: albCat,
              sub_tag: albTag,
              age_stage: albStage,
              english_level: albEng,
              play_mode: albMode,
              cover_emoji: albEmoji,
              description: albDesc,
            };
            if (editingAlb) {
              await api.updateAlbum(editingAlb.id, payload);
              showToast("专辑已更新");
            } else {
              await api.createAlbum(payload);
              showToast("专辑已创建");
            }
            setAlbModalOpen(false);
            await loadAll();
            onRefreshDashboard();
          }}
          className="space-y-3 text-xs"
        >
          <div className="grid gap-3 sm:grid-cols-4">
            <input required value={albTitle} onChange={(e) => setAlbTitle(e.target.value)} placeholder="专辑标题 *" className="sm:col-span-3 rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
            <input value={albEmoji} onChange={(e) => setAlbEmoji(e.target.value)} placeholder="Emoji 图标" className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-center text-sm" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <select value={albCat} onChange={(e) => { setAlbCat(e.target.value as MediaAlbum["category"]); setAlbTag(""); }} className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
              {CHANNELS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
            <select value={albTag} onChange={(e) => setAlbTag(e.target.value)} className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
              <option value="">选择二级分类标签</option>
              {tags.filter((t) => t.channel === albCat).map((tg) => <option key={tg.id} value={tg.name}>#{tg.name}</option>)}
            </select>
            <select value={albStage} onChange={(e) => setAlbStage(e.target.value as AgeStage)} className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
              {Object.entries(AGE_STAGE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select value={albEng} onChange={(e) => setAlbEng(e.target.value as EnglishLevel)} className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
              {Object.entries(ENGLISH_LEVEL_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </div>
          <select value={albMode} onChange={(e) => setAlbMode(e.target.value as MediaAlbum["play_mode"])} className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2">
            <option value="sequential">顺序续播</option>
            <option value="shuffle">随机播放</option>
          </select>
          <textarea value={albDesc} onChange={(e) => setAlbDesc(e.target.value)} rows={2} placeholder="专辑简介说明" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setAlbModalOpen(false)} className="rounded-xl border border-[var(--border-soft)] px-4 py-2">取消</button>
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">保存</button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!deleteAlbTarget}
        title="确认删除整张专辑？"
        message={`将永久删除专辑《${deleteAlbTarget?.title}》及包含的音轨磁盘文件。`}
        onCancel={() => setDeleteAlbTarget(null)}
        onConfirm={async () => {
          if (!deleteAlbTarget) return;
          await api.deleteAlbum(deleteAlbTarget.id);
          setDeleteAlbTarget(null);
          showToast("专辑已删除");
          await loadAll();
          onRefreshDashboard();
        }}
      />
    </div>
  );
}
