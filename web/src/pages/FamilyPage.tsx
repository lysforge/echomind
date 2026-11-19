import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Edit3, Mic, Plus, RotateCcw, ShieldCheck, Trash2, Users, Volume2 } from "lucide-react";
import { AgeStage, api, EnglishLevel, FamilyMember, MemoryItem } from "../api";
import { AGE_STAGE_LABELS, ConfirmDialog, EmptyState, ENGLISH_LEVEL_LABELS, Modal } from "../components/Modal";

const VOICE_OPTIONS = [
  { id: "zh-CN-XiaoyiNeural", label: "晓伊（温柔童声/亲切女声）" },
  { id: "zh-CN-XiaoxiaoNeural", label: "晓晓（自然标准女声）" },
  { id: "zh-CN-YunxiNeural", label: "云希（阳光男声）" },
  { id: "en-US-AriaNeural", label: "Aria（地道美式英语女声）" },
];

export function FamilyPage({
  onPlayUrl,
  onRefreshDashboard,
  showToast,
}: {
  onPlayUrl: (url: string) => void;
  onRefreshDashboard: () => void;
  showToast: (m: string) => void;
}) {
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memScopeFilter, setMemScopeFilter] = useState("all");
  const [memQ, setMemQ] = useState("");

  // 成员新建/编辑 Modal
  const [memberModalOpen, setMemberModalOpen] = useState(false);
  const [editingMember, setEditingMember] = useState<FamilyMember | null>(null);
  const [mName, setMName] = useState("");
  const [mNickname, setMNickname] = useState("");
  const [mRole, setMRole] = useState<"child" | "adult">("child");
  const [mBirth, setMBirth] = useState("2024-05");
  const [mAgeStage, setMAgeStage] = useState<AgeStage>("S1_0_3");
  const [mEngStage, setMEngStage] = useState<EnglishLevel>("Pre_A1");
  const [mVoice, setMVoice] = useState("zh-CN-XiaoyiNeural");
  const [mRate, setMRate] = useState("-12%");
  const [deleteMemberTarget, setDeleteMemberTarget] = useState<FamilyMember | null>(null);

  // 声纹录音工作室 Modal（带实时 20 柱 Web Audio 波形）
  const [vpTarget, setVpTarget] = useState<FamilyMember | null>(null);
  const [vpRecording, setVpRecording] = useState(false);
  const [vpCountdown, setVpCountdown] = useState(4);
  const [vpBars, setVpBars] = useState<number[]>(new Array(20).fill(10));
  const [vpBlob, setVpBlob] = useState<Blob | null>(null);
  const [vpPreviewUrl, setVpPreviewUrl] = useState<string>("");
  const [probeMsg, setProbeMsg] = useState<string>("");
  const animRef = useRef<number | null>(null);

  // 记忆编辑
  const [memModalOpen, setMemModalOpen] = useState(false);
  const [editingMem, setEditingMem] = useState<MemoryItem | null>(null);
  const [memScope, setMemScope] = useState<"family" | "personal" | "growth">("family");
  const [memMemberId, setMemMemberId] = useState<number>(0);
  const [memContent, setMemContent] = useState("");

  const loadAll = async () => {
    const [m, ms] = await Promise.all([api.listMembers(), api.listMemories(memScopeFilter, memQ)]);
    setMembers(m);
    setMemories(ms);
    if (m.length > 0 && memMemberId === 0) setMemMemberId(m[0].id);
  };

  useEffect(() => {
    loadAll().catch(() => {});
  }, [memScopeFilter]);

  const openMemberCreate = () => {
    setEditingMember(null);
    setMName("");
    setMNickname("");
    setMRole("child");
    setMBirth("2020-05");
    setMAgeStage("S3_6_9");
    setMEngStage("A1");
    setMVoice("zh-CN-XiaoyiNeural");
    setMRate("-10%");
    setMemberModalOpen(true);
  };

  const openMemberEdit = (m: FamilyMember) => {
    setEditingMember(m);
    setMName(m.name);
    setMNickname(m.nickname);
    setMRole(m.role);
    setMBirth(m.birth_date || "");
    setMAgeStage(m.age_stage);
    setMEngStage(m.english_stage);
    setMVoice(m.tts_voice);
    setMRate(m.tts_rate);
    setMemberModalOpen(true);
  };

  const startStudioRecording = async () => {
    if (vpRecording) return;
    setVpBlob(null);
    if (vpPreviewUrl) URL.revokeObjectURL(vpPreviewUrl);
    setVpPreviewUrl("");
    setVpRecording(true);
    setVpCountdown(4);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      src.connect(analyser);
      const dataArr = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        analyser.getByteFrequencyData(dataArr);
        const bars = Array.from({ length: 20 }, (_, i) => Math.max(8, Math.min(100, Math.round((dataArr[i % dataArr.length] / 255) * 100))));
        setVpBars(bars);
        animRef.current = requestAnimationFrame(tick);
      };
      tick();

      const rec = new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (ev) => ev.data.size > 0 && chunks.push(ev.data);
      rec.onstop = () => {
        if (animRef.current) cancelAnimationFrame(animRef.current);
        setVpBars(new Array(20).fill(10));
        stream.getTracks().forEach((t) => t.stop());
        ctx.close().catch(() => {});
        const blob = new Blob(chunks, { type: "audio/webm" });
        setVpBlob(blob);
        setVpPreviewUrl(URL.createObjectURL(blob));
        setVpRecording(false);
      };
      rec.start();

      let rem = 4;
      const cd = setInterval(() => {
        rem -= 1;
        setVpCountdown(rem);
        if (rem <= 0) {
          clearInterval(cd);
          if (rec.state !== "inactive") rec.stop();
        }
      }, 1000);
    } catch {
      setVpRecording(false);
      showToast("无法打开麦克风，请检查浏览器权限");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">家庭成员 · 声纹隔离 · 三层记忆中心</h2>
          <p className="text-xs text-[var(--ink-muted)]">
            出生年月自动计算成长阶段（0-18+ 岁），支持实时声纹录入、清空重置及个人私密/家庭共享记忆隔离。
          </p>
        </div>
        <button
          onClick={openMemberCreate}
          className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-4 py-2 text-xs font-semibold text-white"
        >
          <Plus className="h-4 w-4" /> 添加家庭成员
        </button>
      </div>

      {members.length === 0 ? (
        <EmptyState
          icon={Users}
          title="尚未添加家庭成员"
          description="添加孩子（设定出生年月与英语阶段）或父母成员，即可为每个人分配独立声纹与专属记忆空间。"
          action={
            <button onClick={openMemberCreate} className="rounded-xl bg-[var(--brand-green)] px-5 py-2 text-xs font-semibold text-white">
              + 添加第一位成员
            </button>
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {members.map((m) => (
            <div key={m.id} className="card-pro flex flex-col justify-between p-5">
              <div>
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-base font-bold">
                      {m.name}（{m.nickname}）
                    </h3>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
                      <span className="rounded-full bg-zinc-100 px-2.5 py-0.5 font-medium text-zinc-700">
                        {m.role === "child" ? m.age_label || "孩子" : "成人家长"}
                      </span>
                      <span className="rounded-full bg-[var(--brand-green-soft)] px-2.5 py-0.5 font-medium text-[var(--brand-green)]">
                        {AGE_STAGE_LABELS[m.age_stage]}
                      </span>
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <button onClick={() => openMemberEdit(m)} className="rounded p-1 text-zinc-400 hover:text-zinc-700">
                      <Edit3 className="h-4 w-4" />
                    </button>
                    <button onClick={() => setDeleteMemberTarget(m)} className="rounded p-1 text-zinc-400 hover:text-rose-600">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                <div className="mt-2 text-xs text-[var(--ink-muted)]">
                  英语级别：{ENGLISH_LEVEL_LABELS[m.english_stage]} · 音色：{m.tts_voice}
                </div>

                <div className="mt-3 flex items-center justify-between rounded-xl bg-zinc-50 px-3 py-2 text-xs">
                  {m.has_voiceprint ? (
                    <span className="inline-flex items-center gap-1 font-medium text-emerald-700">
                      <CheckCircle2 className="h-3.5 w-3.5" /> 已录声纹（{m.voiceprint_samples} 段）
                    </span>
                  ) : (
                    <span className="text-zinc-400">未录入声纹</span>
                  )}
                  {m.has_voiceprint && (
                    <button
                      onClick={async () => {
                        await api.clearVoiceprint(m.id);
                        showToast(`已清空【${m.nickname}】的声纹`);
                        loadAll();
                        onRefreshDashboard();
                      }}
                      className="inline-flex items-center gap-0.5 text-[11px] text-zinc-500 hover:text-rose-600"
                    >
                      <RotateCcw className="h-3 w-3" /> 重置
                    </button>
                  )}
                </div>
              </div>

              <button
                onClick={() => {
                  setVpTarget(m);
                  setVpBlob(null);
                  setVpPreviewUrl("");
                }}
                className="mt-4 flex w-full items-center justify-center gap-1.5 rounded-xl bg-[var(--brand-green-soft)] py-2 text-xs font-semibold text-[var(--brand-green)]"
              >
                <Mic className="h-3.5 w-3.5" /> 打开声纹录制工作室
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 声纹现场验证条 */}
      <section className="card-pro flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="flex items-center gap-2.5 text-xs">
          <ShieldCheck className="h-5 w-5 text-[var(--brand-green)]" />
          <div>
            <div className="font-bold">声纹识别与儿童安全隔离测试</div>
            <div className="text-[var(--ink-muted)]">
              {probeMsg || "录 3 秒说话即可验证当前声纹命中哪位成员，未命中成人将自动强制进入 child_safe 安全模式。"}
            </div>
          </div>
        </div>
        <button
          onClick={async () => {
            setProbeMsg("正在采集 3 秒语音...");
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
                setTimeout(() => rec.state !== "inactive" && rec.stop(), 3000);
              });
              const r = await api.identifyVoiceprint(blob);
              setProbeMsg(`识别为：${r.name} ｜ 安全模式：${r.safety_mode} ｜ 置信度：${r.confidence}`);
            } catch {
              setProbeMsg("测试失败：请检查浏览器麦克风权限");
            }
          }}
          className="rounded-xl bg-[var(--brand-amber)] px-4 py-2 text-xs font-semibold text-white"
        >
          现场声纹校验 (3s)
        </button>
      </section>

      {/* 三层记忆库 */}
      <section className="card-pro space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-bold">三层隔离记忆库</h3>
            <p className="text-xs text-[var(--ink-muted)]">家庭共享备忘（全员可见） · 个人私密记忆（声纹鉴权隔离） · 孩子成长档案</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select
              value={memScopeFilter}
              onChange={(e) => setMemScopeFilter(e.target.value)}
              className="rounded-xl border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs"
            >
              <option value="all">全部层级</option>
              <option value="family">家庭共享</option>
              <option value="personal">个人私密</option>
              <option value="growth">成长记录</option>
            </select>
            <input
              value={memQ}
              onChange={(e) => setMemQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadAll()}
              placeholder="搜索记忆关键词..."
              className="rounded-xl border border-[var(--border-soft)] px-3 py-1.5 text-xs"
            />
            <button
              onClick={() => {
                setEditingMem(null);
                setMemScope("family");
                setMemContent("");
                setMemModalOpen(true);
              }}
              className="rounded-xl bg-[var(--brand-green)] px-3.5 py-1.5 text-xs font-semibold text-white"
            >
              + 新增记忆
            </button>
          </div>
        </div>

        {memories.length === 0 ? (
          <div className="rounded-xl bg-zinc-50 p-6 text-center text-xs text-[var(--ink-muted)]">暂无记忆条目，可通过对话或点击右上角新增。</div>
        ) : (
          <div className="grid gap-2.5 md:grid-cols-2">
            {memories.map((m) => (
              <div key={m.id} className="flex items-start justify-between gap-2 rounded-xl border border-[var(--border-soft)] p-3 text-xs">
                <div>
                  <span
                    className={`mr-1.5 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                      m.scope === "personal"
                        ? "bg-amber-100 text-amber-800"
                        : m.scope === "growth"
                          ? "bg-sky-100 text-sky-800"
                          : "bg-emerald-100 text-emerald-800"
                    }`}
                  >
                    {m.scope === "personal" ? `个人私密·${m.member_name || ""}` : m.scope === "growth" ? `成长·${m.member_name || ""}` : "家庭共享"}
                  </span>
                  <span>{m.content}</span>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    onClick={() => {
                      setEditingMem(m);
                      setMemContent(m.content);
                      setMemModalOpen(true);
                    }}
                    className="rounded p-1 text-zinc-400 hover:text-zinc-700"
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => api.deleteMemory(m.id).then(() => loadAll())}
                    className="rounded p-1 text-zinc-400 hover:text-rose-600"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 新增/编辑成员 Modal */}
      <Modal open={memberModalOpen} title={editingMember ? "编辑成员成长档案" : "添加家庭成员"} onClose={() => setMemberModalOpen(false)}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const payload = {
              name: mName,
              nickname: mNickname || mName,
              role: mRole,
              birth_date: mRole === "child" ? mBirth : "",
              age_stage: mRole === "child" ? mAgeStage : "S6_ALL",
              english_stage: mRole === "child" ? mEngStage : "adult",
              tts_voice: mVoice,
              tts_rate: mRate,
            };
            if (editingMember) {
              await api.updateMember(editingMember.id, payload);
              showToast("成员档案已更新");
            } else {
              await api.createMember(payload);
              showToast("已添加家庭成员");
            }
            setMemberModalOpen(false);
            loadAll();
            onRefreshDashboard();
          }}
          className="space-y-3 text-xs"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <input
              required
              value={mName}
              onChange={(e) => setMName(e.target.value)}
              placeholder="成员称呼（如 乐乐 / 爸爸）*"
              className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
            />
            <input
              value={mNickname}
              onChange={(e) => setMNickname(e.target.value)}
              placeholder="语音昵称（选填）"
              className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
            />
            <select
              value={mRole}
              onChange={(e) => setMRole(e.target.value as "child" | "adult")}
              className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
            >
              <option value="child">孩子（动态成长档案）</option>
              <option value="adult">成人 / 家长</option>
            </select>
            {mRole === "child" && (
              <>
                <input
                  value={mBirth}
                  onChange={(e) => setMBirth(e.target.value)}
                  placeholder="出生年月 YYYY-MM"
                  className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
                />
                <select
                  value={mAgeStage}
                  onChange={(e) => setMAgeStage(e.target.value as AgeStage)}
                  className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
                >
                  {Object.entries(AGE_STAGE_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
                <select
                  value={mEngStage}
                  onChange={(e) => setMEngStage(e.target.value as EnglishLevel)}
                  className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
                >
                  {Object.entries(ENGLISH_LEVEL_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </>
            )}
          </div>

          <div className="rounded-xl bg-zinc-50 p-3">
            <div className="mb-2 font-semibold">专属播报音色与语速</div>
            <div className="flex flex-wrap gap-2">
              <select
                value={mVoice}
                onChange={(e) => setMVoice(e.target.value)}
                className="flex-1 rounded-xl border border-[var(--border-soft)] bg-white px-3 py-1.5"
              >
                {VOICE_OPTIONS.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
              <input
                value={mRate}
                onChange={(e) => setMRate(e.target.value)}
                placeholder="语速如 -12% / +0%"
                className="w-24 rounded-xl border border-[var(--border-soft)] bg-white px-2.5 py-1.5"
              />
              <button
                type="button"
                onClick={async () => {
                  const r = await api.previewTTS(mVoice, mRate, `你好${mNickname || mName || ""}，这是我的声音效果试听。`);
                  onPlayUrl(r.tts_url);
                }}
                className="inline-flex items-center gap-1 rounded-xl bg-white px-3 py-1.5 font-medium shadow-xs"
              >
                <Volume2 className="h-3.5 w-3.5" /> 试听音色
              </button>
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setMemberModalOpen(false)} className="rounded-xl border border-[var(--border-soft)] px-4 py-2">
              取消
            </button>
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">
              保存档案
            </button>
          </div>
        </form>
      </Modal>

      {/* 可视化实时波形声纹工作室 Modal */}
      <Modal open={!!vpTarget} title={`声纹录制工作室：${vpTarget?.name || ""}`} onClose={() => setVpTarget(null)}>
        {vpTarget && (
          <div className="space-y-4 text-xs">
            <div className="rounded-2xl bg-[var(--brand-green-soft)] p-4 text-[var(--brand-green)]">
              <div className="font-bold">推荐朗读提示词（请用平时在客厅说话的语气朗读 4 秒）：</div>
              <div className="mt-1 text-sm font-semibold">“你好小音，今天天气不错，帮我放一首轻音乐或者讲个故事吧。”</div>
            </div>

            {/* 20 柱实时波形图 */}
            <div className="flex h-24 items-end justify-center gap-1.5 rounded-2xl bg-[#0b1120] px-6 py-4">
              {vpBars.map((h, idx) => (
                <div
                  key={idx}
                  style={{ height: `${h}%` }}
                  className="w-2 rounded-full bg-[var(--brand-primary)] transition-all duration-75"
                />
              ))}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <button
                onClick={startStudioRecording}
                disabled={vpRecording}
                className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 font-semibold text-white ${
                  vpRecording ? "bg-rose-500" : "bg-[var(--brand-amber)]"
                }`}
              >
                <Mic className="h-4 w-4" /> {vpRecording ? `正在录音 (${vpCountdown}s)...` : "开始 4 秒声纹录制"}
              </button>

              {vpPreviewUrl && (
                <div className="flex items-center gap-2">
                  <audio controls src={vpPreviewUrl} className="h-8 w-44" />
                  <button
                    onClick={async () => {
                      if (!vpBlob) return;
                      const res = await api.uploadVoiceprint(vpTarget.id, vpBlob);
                      showToast(`【${vpTarget.nickname}】声纹保存成功（样本数：${res.voiceprint_samples}）`);
                      setVpTarget(null);
                      loadAll();
                      onRefreshDashboard();
                    }}
                    className="rounded-xl bg-[var(--brand-green)] px-4 py-2 font-semibold text-white"
                  >
                    确认上传并录入
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* 新增/编辑记忆 Modal */}
      <Modal open={memModalOpen} title={editingMem ? "编辑记忆内容" : "新增家庭/个人记忆"} onClose={() => setMemModalOpen(false)}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (editingMem) {
              await api.updateMemory(editingMem.id, memContent);
              showToast("记忆已更新");
            } else {
              await api.createMemory({
                member_id: memScope === "family" ? null : memMemberId,
                scope: memScope,
                content: memContent,
              });
              showToast("记忆已保存");
            }
            setMemModalOpen(false);
            loadAll();
          }}
          className="space-y-3 text-xs"
        >
          {!editingMem && (
            <div className="grid grid-cols-2 gap-3">
              <select
                value={memScope}
                onChange={(e) => setMemScope(e.target.value as typeof memScope)}
                className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
              >
                <option value="family">家庭共享备忘</option>
                <option value="personal">个人私密记忆（声纹隔离）</option>
                <option value="growth">孩子成长记录</option>
              </select>
              {memScope !== "family" && (
                <select
                  value={memMemberId}
                  onChange={(e) => setMemMemberId(Number(e.target.value))}
                  className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2"
                >
                  {members.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
          <textarea
            required
            rows={3}
            value={memContent}
            onChange={(e) => setMemContent(e.target.value)}
            placeholder="输入记忆或备忘内容..."
            className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
          />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setMemModalOpen(false)} className="rounded-xl border border-[var(--border-soft)] px-4 py-2">
              取消
            </button>
            <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">
              保存
            </button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={!!deleteMemberTarget}
        title="确认删除该家庭成员？"
        message={`删除「${deleteMemberTarget?.name}」将同时清理其个人声纹与专属记忆。`}
        onCancel={() => setDeleteMemberTarget(null)}
        onConfirm={async () => {
          if (!deleteMemberTarget) return;
          await api.deleteMember(deleteMemberTarget.id);
          setDeleteMemberTarget(null);
          showToast("成员已移除");
          loadAll();
          onRefreshDashboard();
        }}
      />
    </div>
  );
}
