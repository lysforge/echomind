import React, { useEffect, useState } from "react";
import { CheckCircle2, Copy, Cpu, Disc3, Home, Mic, Moon, Save, Volume2, Wifi, Zap } from "lucide-react";
import { api, CloudMusicStatus, SettingsPayload } from "../api";

const LLM_PRESETS: Record<"deepseek" | "openai" | "ollama", { url: string; model: string; hint: string }> = {
  deepseek: {
    url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    hint: "性价比极高，支持中文绘本伴读与全龄英语引导",
  },
  openai: {
    url: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    hint: "标准 OpenAI 协议（兼容 OneAPI / OpenRouter 等中转地址）",
  },
  ollama: {
    url: "http://127.0.0.1:11434/v1",
    model: "qwen2.5:7b",
    hint: "纯本地局域网私有部署，无需外网 Key 即可对话",
  },
};

const VOICE_PRESETS = [
  { id: "zh-CN-XiaoxiaoNeural", label: "晓晓（温柔女声 · 适合少儿绘本）" },
  { id: "zh-CN-XiaoyiNeural", label: "晓伊（清脆女声 · 适合故事/日常）" },
  { id: "zh-CN-YunxiNeural", label: "云希（阳光男声 · 适合青少年/科普）" },
  { id: "zh-CN-YunyangNeural", label: "云扬（沉稳男声 · 适合成人新闻/播客）" },
  { id: "en-US-AnaNeural", label: "Ana（美式童声 · 适合英语磨耳朵）" },
  { id: "en-US-JennyNeural", label: "Jenny（标准美音 · 适合英语全阶段）" },
];

export function SettingsPage({
  onRefreshDashboard,
  showToast,
}: {
  onRefreshDashboard: () => void;
  showToast: (m: string) => void;
}) {
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // 可编辑表单态
  const [homeName, setHomeName] = useState("我的家");
  const [assistantName, setAssistantName] = useState("小音");
  const [loudnormLufs, setLoudnormLufs] = useState(-16);

  const [llmProvider, setLlmProvider] = useState<"deepseek" | "openai" | "ollama">("deepseek");
  const [llmBaseUrl, setLlmBaseUrl] = useState("https://api.deepseek.com/v1");
  const [llmModel, setLlmModel] = useState("deepseek-chat");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [testingLlm, setTestingLlm] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<{ ok: boolean; latency_ms: number; reply_preview?: string; error?: string } | null>(null);

  const [ttsVoiceChild, setTtsVoiceChild] = useState("zh-CN-XiaoxiaoNeural");
  const [ttsRateChild, setTtsRateChild] = useState("-8%");
  const [ttsVoiceAdult, setTtsVoiceAdult] = useState("zh-CN-YunxiNeural");
  const [ttsRateAdult, setTtsRateAdult] = useState("+0%");

  const [asrMode, setAsrMode] = useState<"local_or_fallback" | "siliconflow">("local_or_fallback");
  const [asrBaseUrl, setAsrBaseUrl] = useState("");
  const [asrModel, setAsrModel] = useState("");
  const [asrApiKey, setAsrApiKey] = useState("");

  const [voiceprintUrl, setVoiceprintUrl] = useState("");
  const [voiceprintThreshold, setVoiceprintThreshold] = useState(0.78);

  const [quietEnabled, setQuietEnabled] = useState(true);
  const [quietStart, setQuietStart] = useState("21:30");
  const [quietEnd, setQuietEnd] = useState("07:30");
  const [quietForce, setQuietForce] = useState(false);
  const [musicDlUrl, setMusicDlUrl] = useState("http://127.0.0.1:18080");
  const [musicDlSources, setMusicDlSources] = useState("netease,qq,kugou,kuwo,migu,bilibili");
  const [testingMusicDl, setTestingMusicDl] = useState(false);
  const [musicDlTestResult, setMusicDlTestResult] = useState<CloudMusicStatus | null>(null);

  const loadSettings = async () => {
    setLoading(true);
    try {
      const res = await api.getSettings();
      setData(res);
      setHomeName(res.home_name);
      setAssistantName(res.assistant_name);
      setLoudnormLufs(res.loudnorm_target_lufs);
      setLlmProvider(res.llm_provider);
      setLlmBaseUrl(res.llm_base_url);
      setLlmModel(res.llm_model);
      setTtsVoiceChild(res.tts_voice_child);
      setTtsRateChild(res.tts_rate_child);
      setTtsVoiceAdult(res.tts_voice_adult);
      setTtsRateAdult(res.tts_rate_adult);
      setAsrMode(res.asr_mode);
      setAsrBaseUrl(res.asr_base_url);
      setAsrModel(res.asr_model);
      setVoiceprintUrl(res.voiceprint_api_url);
      setVoiceprintThreshold(res.voiceprint_threshold);
      setQuietEnabled(res.quiet_hours_enabled);
      setQuietStart(res.quiet_hours_start);
      setQuietEnd(res.quiet_hours_end);
      setQuietForce(res.quiet_hours_force_active);
      setMusicDlUrl(res.music_dl_url || "");
      setMusicDlSources(res.music_dl_sources || "netease,qq,kugou,kuwo,migu,bilibili");
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSettings();
  }, []);

  const handleProviderChange = (next: "deepseek" | "openai" | "ollama") => {
    setLlmProvider(next);
    setLlmBaseUrl(LLM_PRESETS[next].url);
    setLlmModel(LLM_PRESETS[next].model);
    setLlmTestResult(null);
  };

  const handleSaveAll = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        home_name: homeName.trim() || "我的家",
        assistant_name: assistantName.trim() || "小音",
        loudnorm_target_lufs: loudnormLufs,
        llm_provider: llmProvider,
        llm_base_url: llmBaseUrl.trim(),
        llm_model: llmModel.trim(),
        tts_voice_child: ttsVoiceChild,
        tts_rate_child: ttsRateChild,
        tts_voice_adult: ttsVoiceAdult,
        tts_rate_adult: ttsRateAdult,
        asr_mode: asrMode,
        asr_base_url: asrBaseUrl.trim(),
        asr_model: asrModel.trim(),
        voiceprint_api_url: voiceprintUrl.trim(),
        voiceprint_threshold: voiceprintThreshold,
        quiet_hours_enabled: quietEnabled,
        quiet_hours_start: quietStart,
        quiet_hours_end: quietEnd,
        quiet_hours_force_active: quietForce,
        music_dl_url: musicDlUrl.trim(),
        music_dl_sources: musicDlSources.trim() || "netease,qq,kugou,kuwo,migu,bilibili",
      };
      if (llmApiKey.trim()) payload.llm_api_key = llmApiKey.trim();
      if (asrApiKey.trim()) payload.asr_api_key = asrApiKey.trim();

      const updated = await api.updateSettings(payload);
      setData(updated);
      setLlmApiKey("");
      setAsrApiKey("");
      showToast("系统与模型设置已保存生效");
      onRefreshDashboard();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleTestMusicDl = async () => {
    setTestingMusicDl(true);
    setMusicDlTestResult(null);
    try {
      const res = await api.testMusicDl(musicDlUrl.trim());
      setMusicDlTestResult(res);
      showToast(res.ok ? `多源音乐引擎连通正常 (${res.latency_ms} ms)` : `多源音乐引擎未连通: ${res.error || "请检查地址"}`);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setTestingMusicDl(false);
    }
  };

  const handleTestLlm = async () => {
    setTestingLlm(true);
    setLlmTestResult(null);
    try {
      const res = await api.testLLM({
        llm_base_url: llmBaseUrl.trim(),
        llm_model: llmModel.trim(),
        ...(llmApiKey.trim() ? { llm_api_key: llmApiKey.trim() } : {}),
      });
      setLlmTestResult(res);
      showToast(res.ok ? `大模型连通成功 (${res.latency_ms} ms)` : `大模型测试失败: ${res.error || "请检查地址与密钥"}`);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setTestingLlm(false);
    }
  };

  const handlePreviewVoice = async (voice: string, rate: string) => {
    try {
      const res = await api.previewTTS(voice, rate, `你好，我是${assistantName || "小音"}，正在为你试听当前音色。`);
      const audio = new Audio(res.tts_url);
      void audio.play();
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const copyText = (txt: string) => {
    navigator.clipboard?.writeText(txt);
    showToast("已复制到剪贴板");
  };

  if (loading || !data) {
    return <div className="card-pro p-8 text-center text-sm text-[var(--ink-muted)]">正在加载系统配置…</div>;
  }

  return (
    <form onSubmit={handleSaveAll} className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold tracking-tight">系统、模型与接入设置</h2>
          <p className="mt-0.5 text-sm text-[var(--ink-muted)]">
            配置家庭声枢品牌名称、大模型 API、TTS/声纹识别精度、护耳静音时段与局域网音箱接入地址
          </p>
        </div>
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-xl bg-[var(--brand-green)] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[var(--brand-green-hover)] disabled:opacity-60"
        >
          <Save className="h-4 w-4" />
          {saving ? "保存中…" : "保存全部设置"}
        </button>
      </div>

      {/* 1. 家庭身份与护耳响度 */}
      <div className="card-pro p-5">
        <div className="mb-4 flex items-center gap-2 border-b border-[var(--border-soft)] pb-3">
          <Home className="h-4 w-4 text-[var(--brand-green)]" />
          <h3 className="text-sm font-bold">家庭中枢身份与护耳规范</h3>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-semibold">家庭空间名称</label>
            <input
              value={homeName}
              onChange={(e) => setHomeName(e.target.value)}
              placeholder="如：林家小屋 / 我的家"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">AI 语音助手称呼</label>
            <input
              value={assistantName}
              onChange={(e) => setAssistantName(e.target.value)}
              placeholder="默认：小音"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">音频响度校准目标 ({loudnormLufs} LUFS)</label>
            <input
              type="range"
              min={-22}
              max={-12}
              step={1}
              value={loudnormLufs}
              onChange={(e) => setLoudnormLufs(Number(e.target.value))}
              className="mt-2 w-full accent-[var(--brand-green)]"
            />
            <div className="mt-1 flex justify-between text-[11px] text-[var(--ink-muted)]">
              <span>-22 LUFS (更轻柔)</span>
              <span>推荐 -16 LUFS</span>
              <span>-12 LUFS (更响亮)</span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. 大模型大脑配置 + 一键连通性测试 */}
      <div className="card-pro p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-soft)] pb-3">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-[var(--brand-green)]" />
            <h3 className="text-sm font-bold">大语言模型引擎 (OpenAI 兼容接口)</h3>
            {data.has_llm_key ? (
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                已配置 Key ({data.llm_api_key_masked})
              </span>
            ) : (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
                未填外部 Key · 使用离线兜底回复
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleTestLlm}
            disabled={testingLlm}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-green)] bg-[var(--brand-green-soft)] px-3.5 py-1.5 text-xs font-semibold text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)] disabled:opacity-60"
          >
            <Zap className="h-3.5 w-3.5" />
            {testingLlm ? "测试连通中…" : "一键测试大模型连通性"}
          </button>
        </div>

        <div className="mb-3 flex flex-wrap gap-2">
          {(["deepseek", "openai", "ollama"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => handleProviderChange(p)}
              className={`rounded-xl border px-3 py-1.5 text-xs font-semibold transition ${
                llmProvider === p
                  ? "border-[var(--brand-green)] bg-[var(--brand-green-soft)] text-[var(--brand-green)]"
                  : "border-[var(--border-soft)] bg-white text-zinc-600 hover:bg-zinc-50"
              }`}
            >
              {p === "deepseek" ? "DeepSeek 深度求索" : p === "openai" ? "OpenAI / 兼容中转" : "Ollama 本地私有模型"}
            </button>
          ))}
        </div>
        <p className="mb-4 text-xs text-[var(--ink-muted)]">{LLM_PRESETS[llmProvider].hint}</p>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-semibold">API Base URL</label>
            <input
              value={llmBaseUrl}
              onChange={(e) => setLlmBaseUrl(e.target.value)}
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">模型名称 (Model)</label>
            <input
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">API Key（留空则保持现有密钥）</label>
            <input
              type="password"
              value={llmApiKey}
              onChange={(e) => setLlmApiKey(e.target.value)}
              placeholder={data.has_llm_key ? `已保存 ${data.llm_api_key_masked}，输入新 Key 可覆盖` : "sk-..."}
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
        </div>

        {llmTestResult && (
          <div
            className={`mt-3 rounded-xl border px-4 py-3 text-xs ${
              llmTestResult.ok ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-rose-200 bg-rose-50 text-rose-900"
            }`}
          >
            <div className="flex items-center gap-2 font-semibold">
              <CheckCircle2 className="h-4 w-4" />
              {llmTestResult.ok
                ? `连接正常 · 耗时 ${llmTestResult.latency_ms} ms`
                : `连接异常 · ${llmTestResult.error || "请检查 Base URL、模型名与 API Key"}`}
            </div>
            {llmTestResult.reply_preview && (
              <div className="mt-1 text-zinc-700">模型试答：{llmTestResult.reply_preview}</div>
            )}
          </div>
        )}
      </div>

      {/* 2.5 多源云音乐伴生引擎配置 */}
      <div className="card-pro p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-soft)] pb-3">
          <div className="flex items-center gap-2">
            <Disc3 className="h-4 w-4 text-[var(--brand-green)]" />
            <h3 className="text-sm font-bold">多源无限听歌与云端批量下歌引擎 (go-music-dl)</h3>
            <span className="rounded-full bg-[var(--brand-green-soft)] px-2 py-0.5 text-[11px] font-semibold text-[var(--brand-green)]">
              网易云 / QQ / 酷狗 / 酷我 / 咪咕 / B站
            </span>
          </div>
          <button
            type="button"
            onClick={handleTestMusicDl}
            disabled={testingMusicDl}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--brand-green)] bg-[var(--brand-green-soft)] px-3.5 py-1.5 text-xs font-semibold text-[var(--brand-green)] hover:bg-[var(--brand-primary-soft-hover)] disabled:opacity-50"
          >
            <Zap className="h-3.5 w-3.5" />
            {testingMusicDl ? "探测中…" : "测试音乐引擎连通"}
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-semibold">伴生服务地址 (Docker Compose 内网默认 http://music-dl:8080)</label>
            <input
              value={musicDlUrl}
              onChange={(e) => setMusicDlUrl(e.target.value)}
              placeholder="http://127.0.0.1:18080 或 http://music-dl:8080"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 font-mono text-xs outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">默认聚合搜歌音源（英文逗号分隔）</label>
            <input
              value={musicDlSources}
              onChange={(e) => setMusicDlSources(e.target.value)}
              placeholder="netease,qq,kugou,kuwo,migu,bilibili"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 font-mono text-xs outline-none focus:border-[var(--brand-green)]"
            />
          </div>
        </div>

        {musicDlTestResult && (
          <div
            className={`mt-3 rounded-xl border px-4 py-3 text-xs ${
              musicDlTestResult.ok ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-rose-200 bg-rose-50 text-rose-900"
            }`}
          >
            <div className="flex items-center gap-2 font-semibold">
              <CheckCircle2 className="h-4 w-4" />
              {musicDlTestResult.ok
                ? `音乐引擎已连通 (${musicDlTestResult.base_url}) · 耗时 ${musicDlTestResult.latency_ms} ms · 可用源: ${musicDlTestResult.sources.join(", ")}`
                : `音乐引擎未连接 (${musicDlTestResult.base_url}) · ${musicDlTestResult.error || "请先启动 go-music-dl 服务"}`}
            </div>
          </div>
        )}
      </div>

      {/* 3. TTS 音色与声纹识别 */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="card-pro p-5">
          <div className="mb-4 flex items-center gap-2 border-b border-[var(--border-soft)] pb-3">
            <Volume2 className="h-4 w-4 text-[var(--brand-green)]" />
            <h3 className="text-sm font-bold">默认语音合成音色 (EdgeTTS / 离线降级)</h3>
          </div>
          <div className="space-y-4">
            <div className="rounded-xl bg-zinc-50 p-3.5">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-bold">少儿绘本默认音色与语速</span>
                <button
                  type="button"
                  onClick={() => handlePreviewVoice(ttsVoiceChild, ttsRateChild)}
                  className="rounded-lg bg-white px-2.5 py-1 text-[11px] font-semibold text-[var(--brand-green)] shadow-xs hover:bg-zinc-100"
                >
                  试听效果
                </button>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <select
                  value={ttsVoiceChild}
                  onChange={(e) => setTtsVoiceChild(e.target.value)}
                  className="col-span-2 rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs"
                >
                  {VOICE_PRESETS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
                <input
                  value={ttsRateChild}
                  onChange={(e) => setTtsRateChild(e.target.value)}
                  placeholder="-8%"
                  className="rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs"
                />
              </div>
            </div>

            <div className="rounded-xl bg-zinc-50 p-3.5">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-bold">青少年 / 成人默认音色与语速</span>
                <button
                  type="button"
                  onClick={() => handlePreviewVoice(ttsVoiceAdult, ttsRateAdult)}
                  className="rounded-lg bg-white px-2.5 py-1 text-[11px] font-semibold text-[var(--brand-green)] shadow-xs hover:bg-zinc-100"
                >
                  试听效果
                </button>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <select
                  value={ttsVoiceAdult}
                  onChange={(e) => setTtsVoiceAdult(e.target.value)}
                  className="col-span-2 rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs"
                >
                  {VOICE_PRESETS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
                <input
                  value={ttsRateAdult}
                  onChange={(e) => setTtsRateAdult(e.target.value)}
                  placeholder="+0%"
                  className="rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs"
                />
              </div>
            </div>
          </div>
        </div>

        {/* 声纹 & ASR */}
        <div className="card-pro p-5">
          <div className="mb-4 flex items-center gap-2 border-b border-[var(--border-soft)] pb-3">
            <Mic className="h-4 w-4 text-[var(--brand-green)]" />
            <h3 className="text-sm font-bold">声纹身份阈值与语音识别 (ASR)</h3>
          </div>
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-xs font-semibold">
                <span>家庭成员声纹匹配阈值</span>
                <span className="text-[var(--brand-green)]">{voiceprintThreshold.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min={0.55}
                max={0.92}
                step={0.01}
                value={voiceprintThreshold}
                onChange={(e) => setVoiceprintThreshold(Number(e.target.value))}
                className="mt-1.5 w-full accent-[var(--brand-green)]"
              />
              <p className="mt-1 text-[11px] text-[var(--ink-muted)]">
                未达到阈值时自动进入安全访客模式，推荐保留 0.78 以精准区分儿童与父母声音
              </p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-semibold">ASR 语音转文字模式</label>
                <select
                  value={asrMode}
                  onChange={(e) => setAsrMode(e.target.value as "local_or_fallback" | "siliconflow")}
                  className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-xs"
                >
                  <option value="local_or_fallback">本地 / 文本通道兜底</option>
                  <option value="siliconflow">SiliconFlow SenseVoice 云识别</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold">ASR 模型名</label>
                <input
                  value={asrModel}
                  onChange={(e) => setAsrModel(e.target.value)}
                  placeholder="FunAudioLLM/SenseVoiceSmall"
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-xs"
                />
              </div>
            </div>
            {asrMode === "siliconflow" && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <input
                  value={asrBaseUrl}
                  onChange={(e) => setAsrBaseUrl(e.target.value)}
                  placeholder="https://api.siliconflow.cn/v1"
                  className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-xs"
                />
                <input
                  type="password"
                  value={asrApiKey}
                  onChange={(e) => setAsrApiKey(e.target.value)}
                  placeholder={data.has_asr_key ? `已存 ${data.asr_api_key_masked}` : "ASR API Key"}
                  className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-xs"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 4. 夜间护耳免打扰 & 硬件接入端点 */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="card-pro p-5">
          <div className="mb-4 flex items-center gap-2 border-b border-[var(--border-soft)] pb-3">
            <Moon className="h-4 w-4 text-[var(--brand-green)]" />
            <h3 className="text-sm font-bold">夜间护耳静默守护</h3>
          </div>
          <div className="space-y-3 text-sm">
            <label className="flex items-center justify-between rounded-xl bg-zinc-50 px-3.5 py-2.5">
              <span>启用每日定时护耳免打扰</span>
              <input
                type="checkbox"
                checked={quietEnabled}
                onChange={(e) => setQuietEnabled(e.target.checked)}
                className="h-4 w-4 accent-[var(--brand-green)]"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-semibold">开始时间</label>
                <input
                  type="time"
                  value={quietStart}
                  onChange={(e) => setQuietStart(e.target.value)}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold">结束时间</label>
                <input
                  type="time"
                  value={quietEnd}
                  onChange={(e) => setQuietEnd(e.target.value)}
                  className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
                />
              </div>
            </div>
            <label className="flex items-center justify-between rounded-xl bg-amber-50/70 px-3.5 py-2.5 text-xs text-amber-900">
              <span>立即强制开启全局夜间免打扰</span>
              <input
                type="checkbox"
                checked={quietForce}
                onChange={(e) => setQuietForce(e.target.checked)}
                className="h-4 w-4 accent-[var(--brand-amber)]"
              />
            </label>
          </div>
        </div>

        <div className="card-pro p-5">
          <div className="mb-4 flex items-center gap-2 border-b border-[var(--border-soft)] pb-3">
            <Wifi className="h-4 w-4 text-[var(--brand-green)]" />
            <h3 className="text-sm font-bold">本机局域网硬件接入地址 (LAN: {data.hardware_endpoints.lan_ip})</h3>
          </div>
          <div className="space-y-2.5 text-xs">
            {[
              { label: "智能音箱 / 小爱桥接 WebSocket", val: data.hardware_endpoints.speaker_ws_url },
              { label: "ESP32 小智固件 OTA 地址", val: data.hardware_endpoints.robot_ota_url },
              { label: "ESP32 小智固件 WebSocket", val: data.hardware_endpoints.robot_ws_url },
            ].map((ep) => (
              <div key={ep.label} className="rounded-xl border border-[var(--border-soft)] bg-zinc-50 p-3">
                <div className="mb-1 text-[11px] font-semibold text-[var(--ink-muted)]">{ep.label}</div>
                <div className="flex items-center justify-between gap-2">
                  <code className="truncate font-mono text-xs text-zinc-800">{ep.val}</code>
                  <button
                    type="button"
                    onClick={() => copyText(ep.val)}
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-white px-2 py-1 text-[11px] font-medium shadow-xs hover:bg-zinc-100"
                  >
                    <Copy className="h-3 w-3" />
                    复制
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </form>
  );
}
