import React, { useState } from "react";
import { CheckCircle2, Sparkles, Users, Volume2 } from "lucide-react";
import { api, EnglishLevel } from "../api";
import { Modal } from "../components/Modal";

export function OnboardingModal({
  open,
  onFinished,
  onSkip,
  showToast,
}: {
  open: boolean;
  onFinished: () => void;
  onSkip: () => void;
  showToast: (m: string) => void;
}) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [homeName, setHomeName] = useState("我的家");
  const [assistantName, setAssistantName] = useState("小音");
  const [llmKey, setLlmKey] = useState("");
  const [testMsg, setTestMsg] = useState("");

  const [memberName, setMemberName] = useState("宝宝");
  const [memberRole, setMemberRole] = useState<"child" | "adult">("child");
  const [birthDate, setBirthDate] = useState("2024-05");
  const [engLevel, setEngLevel] = useState<EnglishLevel>("Pre_A1");

  const [devName, setDevName] = useState("客厅小爱音箱");
  const [devRoom, setDevRoom] = useState("客厅");
  const [devCreated, setDevCreated] = useState<{ connect_cmd?: string } | null>(null);

  return (
    <Modal open={open} title="欢迎来到 EchoMind · 3 步开启家庭声音中枢" onClose={onSkip} maxWidth="max-w-2xl">
      <div className="mb-5 flex items-center gap-2 text-xs">
        {[
          { n: 1, t: "1. 家庭与 AI 设置" },
          { n: 2, t: "2. 添加家庭成员" },
          { n: 3, t: "3. 接入首台音箱" },
        ].map((it) => (
          <div
            key={it.n}
            className={`flex-1 rounded-xl px-3 py-2 text-center font-medium ${
              step === it.n ? "bg-[var(--brand-green)] text-white" : step > it.n ? "bg-[var(--brand-green-soft)] text-[var(--brand-green)]" : "bg-zinc-100 text-zinc-500"
            }`}
          >
            {it.t}
          </div>
        ))}
      </div>

      {step === 1 && (
        <div className="space-y-4 text-xs">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block font-medium text-[var(--ink-muted)]">家庭空间名称</label>
              <input
                value={homeName}
                onChange={(e) => setHomeName(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block font-medium text-[var(--ink-muted)]">语音助手称呼</label>
              <input
                value={assistantName}
                onChange={(e) => setAssistantName(e.target.value)}
                className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block font-medium text-[var(--ink-muted)]">DeepSeek API Key（可选，留空先用本地引擎体验）</label>
            <div className="flex gap-2">
              <input
                type="password"
                value={llmKey}
                onChange={(e) => setLlmKey(e.target.value)}
                placeholder="sk-..."
                className="flex-1 rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm"
              />
              <button
                type="button"
                onClick={async () => {
                  const r = await api.testLLM({ llm_api_key: llmKey });
                  setTestMsg(r.ok ? `连通成功！延迟 ${r.latency_ms}ms` : `失败：${r.error}`);
                }}
                className="rounded-xl border border-[var(--border-soft)] px-3 py-2 font-medium hover:bg-zinc-50"
              >
                测试连通
              </button>
            </div>
            {testMsg && <p className="mt-1 text-[11px] text-[var(--brand-green)]">{testMsg}</p>}
          </div>

          <div className="flex justify-between pt-2">
            <button onClick={onSkip} className="text-[var(--ink-muted)] hover:underline">
              先跳过向导，进入空白控制台
            </button>
            <button
              onClick={async () => {
                await api.updateSettings({
                  home_name: homeName,
                  assistant_name: assistantName,
                  ...(llmKey.trim() ? { llm_api_key: llmKey.trim() } : {}),
                });
                setStep(2);
              }}
              className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white"
            >
              <Sparkles className="h-4 w-4" /> 保存并下一步
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4 text-xs">
          <div className="rounded-2xl bg-zinc-50 p-4">
            <div className="mb-2 flex items-center gap-1.5 font-bold">
              <Users className="h-4 w-4 text-[var(--brand-green)]" /> 添加第一位家庭成员（可随时在家人档案增删改）
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <input
                value={memberName}
                onChange={(e) => setMemberName(e.target.value)}
                placeholder="成员称呼（如：乐乐、爸爸）"
                className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
              />
              <select
                value={memberRole}
                onChange={(e) => setMemberRole(e.target.value as "child" | "adult")}
                className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
              >
                <option value="child">孩子（按出生年月自动适配成长阶段）</option>
                <option value="adult">成人 / 家长</option>
              </select>
              {memberRole === "child" && (
                <>
                  <div>
                    <label className="mb-1 block text-[11px] text-[var(--ink-muted)]">出生年月 (YYYY-MM)</label>
                    <input
                      value={birthDate}
                      onChange={(e) => setBirthDate(e.target.value)}
                      className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-[11px] text-[var(--ink-muted)]">当前英语能力阶段</label>
                    <select
                      value={engLevel}
                      onChange={(e) => setEngLevel(e.target.value as EnglishLevel)}
                      className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
                    >
                      <option value="Pre_A1">Pre-A1 零基础磨耳朵</option>
                      <option value="A1">A1 拼读与日常短句</option>
                      <option value="A2">A2 桥梁阅读与问答</option>
                      <option value="B1">B1 章节独立听说</option>
                      <option value="B2_PLUS">B2+ 原版思辨对话</option>
                    </select>
                  </div>
                </>
              )}
            </div>
          </div>
          <div className="flex justify-between">
            <button onClick={() => setStep(3)} className="text-[var(--ink-muted)] hover:underline">
              稍后再添加
            </button>
            <button
              onClick={async () => {
                if (memberName.trim()) {
                  await api.createMember({
                    name: memberName.trim(),
                    nickname: memberName.trim(),
                    role: memberRole,
                    birth_date: memberRole === "child" ? birthDate : "",
                    english_stage: memberRole === "child" ? engLevel : "adult",
                  });
                }
                setStep(3);
              }}
              className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white"
            >
              添加并进入最后一步
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4 text-xs">
          {!devCreated ? (
            <div className="space-y-3 rounded-2xl bg-zinc-50 p-4">
              <div className="flex items-center gap-1.5 font-bold">
                <Volume2 className="h-4 w-4 text-[var(--brand-green)]" /> 添加你的第一台真实智能音箱
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <input
                  value={devName}
                  onChange={(e) => setDevName(e.target.value)}
                  placeholder="音箱名称（如：客厅小爱音箱）"
                  className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
                />
                <input
                  value={devRoom}
                  onChange={(e) => setDevRoom(e.target.value)}
                  placeholder="所在房间"
                  className="rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm"
                />
              </div>
              <button
                onClick={async () => {
                  const res = await api.createDevice({
                    name: devName,
                    device_type: "speaker_xiaoai",
                    room: devRoom,
                    max_volume: 75,
                    wake_word: `你好${assistantName}`,
                  });
                  setDevCreated(res);
                  showToast("音箱设备凭证已创建");
                }}
                className="rounded-xl bg-[var(--brand-green)] px-4 py-2 font-medium text-white"
              >
                生成设备连接凭证
              </button>
            </div>
          ) : (
            <div className="space-y-2 rounded-2xl bg-[var(--brand-green-soft)] p-4 text-[var(--brand-green)]">
              <div className="flex items-center gap-1.5 font-bold">
                <CheckCircle2 className="h-4 w-4" /> 设备已创建！复制下方命令在音箱桥接端运行即可上线：
              </div>
              <code className="block break-all rounded-xl bg-white p-3 text-[11px] text-zinc-800">
                {devCreated.connect_cmd}
              </code>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              onClick={async () => {
                await api.completeOnboarding({ home_name: homeName, assistant_name: assistantName });
                onFinished();
              }}
              className="rounded-xl bg-[var(--brand-green)] px-6 py-2.5 font-semibold text-white"
            >
              完成建家，进入控制台
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
