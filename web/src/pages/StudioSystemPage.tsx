import React, { useState } from "react";
import { Copy, Download, Edit3, Plus, Radio, Settings, Shield, Trash2, UserCog, Volume2 } from "lucide-react";
import { api, AuthUser, DashboardData, DeviceInfo } from "../api";
import { ConfirmDialog, EmptyState, Modal, SlideDrawer } from "../components/Modal";
import { AdminUsersPage } from "./AdminUsersPage";
import { SettingsPage } from "./SettingsPage";

type SysTab = "hardware" | "users" | "settings";

export function StudioSystemPage({
  dashboard,
  currentUser,
  onRefreshDashboard,
  showToast,
}: {
  dashboard: DashboardData;
  currentUser: AuthUser;
  onRefreshDashboard: () => void;
  showToast: (m: string) => void;
}) {
  const [sysTab, setSysTab] = useState<SysTab>("hardware");

  // 硬件添加/配网/解绑态
  const [addOpen, setAddOpen] = useState(false);
  const [addStep, setAddStep] = useState<1 | 2>(1);
  const [newType, setNewType] = useState<"speaker_xiaoai" | "esp32_robot">("speaker_xiaoai");
  const [newName, setNewName] = useState("");
  const [newRoom, setNewRoom] = useState("客厅");
  const [newMaxVol, setNewMaxVol] = useState(75);
  const [newWakeWord, setNewWakeWord] = useState(`你好${dashboard.assistant_name || "小音"}`);
  const [createdDev, setCreatedDev] = useState<DeviceInfo | null>(null);

  const [editDev, setEditDev] = useState<DeviceInfo | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeviceInfo | null>(null);

  const handleDownloadScript = async (devId: string) => {
    const token = localStorage.getItem("echomind_auth_token") || "";
    const res = await fetch(`/api/devices/${devId}/bridge-script`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      showToast("下载脚本失败");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `echomind_agent_${devId}.py`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2 border-b border-[var(--border-soft)] pb-3">
        {[
          { id: "hardware", label: `🔊 硬件设备绑定与配网 (${dashboard.devices.length})`, icon: <Volume2 className="h-3.5 w-3.5" /> },
          { id: "users", label: "👥 家庭账号与 RBAC 权限", icon: <UserCog className="h-3.5 w-3.5" /> },
          { id: "settings", label: "🧠 大模型 · 语音 · 护耳设置", icon: <Settings className="h-3.5 w-3.5" /> },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setSysTab(t.id as SysTab)}
            className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold transition ${
              sysTab === t.id
                ? "bg-[var(--brand-green)] text-white"
                : "border border-[var(--border-soft)] bg-white text-zinc-700 hover:bg-zinc-50"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* 子栏 1：纯硬件设备管理（无前台广播和统计干扰） */}
      {sysTab === "hardware" && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-xl font-extrabold">智能音箱与硬件终端配网中心</h2>
              <p className="mt-0.5 text-xs text-[var(--ink-muted)]">
                添加音箱生成专属 Token 与一键下载 `echomind_xiaoai_agent.py` 桥接脚本，设置护耳上限或解绑设备。
              </p>
            </div>
            <button
              onClick={() => {
                setNewName("");
                setCreatedDev(null);
                setAddStep(1);
                setAddOpen(true);
              }}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--brand-green)] px-4 py-2.5 text-xs font-semibold text-white"
            >
              <Plus className="h-4 w-4" /> 新增绑定音箱 / 终端
            </button>
          </div>

          {dashboard.devices.length === 0 ? (
            <EmptyState
              icon={Volume2}
              title="暂无已绑定硬件"
              description="点击右上角创建设备凭证并下载连接脚本，或直接让音箱接入本机 8090 端口触发自动发现。"
            />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {dashboard.devices.map((dev) => (
                <div key={dev.id} className="card-pro space-y-3 p-5 text-xs">
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2.5 py-0.5 text-[11px] font-semibold">
                        {dev.device_type === "speaker_xiaoai" ? <Volume2 className="h-3 w-3" /> : <Radio className="h-3 w-3" />}
                        {dev.room} · {dev.device_type === "speaker_xiaoai" ? "智能音箱" : "ESP32"}
                      </span>
                      <h3 className="mt-2 text-base font-bold">{dev.name}</h3>
                    </div>
                    <span className={`rounded-full px-2 py-0.5 font-semibold ${dev.online ? "bg-emerald-100 text-emerald-700" : "bg-zinc-100 text-zinc-500"}`}>
                      {dev.online ? "在线" : "离线"}
                    </span>
                  </div>
                  <div className="rounded-xl bg-zinc-50 p-3 space-y-1 text-[11px] text-zinc-600">
                    <div>Device ID: <code className="font-mono text-zinc-800">{dev.id}</code></div>
                    <div className="flex items-center gap-1"><Shield className="h-3 w-3 text-[var(--brand-green)]" /> 护耳上限 {dev.max_volume}% · 唤醒词「{dev.wake_word}」</div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleDownloadScript(dev.id)}
                      className="flex-1 inline-flex items-center justify-center gap-1 rounded-xl border border-[var(--border-soft)] bg-white py-2 font-semibold hover:bg-zinc-50"
                    >
                      <Download className="h-3.5 w-3.5" /> 下载脚本
                    </button>
                    <button
                      onClick={() => setEditDev(dev)}
                      className="rounded-xl border border-[var(--border-soft)] px-3 py-2 hover:bg-zinc-50"
                      title="配置参数与连接命令"
                    >
                      <Edit3 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => setDeleteTarget(dev)}
                      className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-rose-600"
                      title="解绑删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 添加向导 */}
          <Modal open={addOpen} title="新增智能音箱 / 硬件终端" onClose={() => setAddOpen(false)}>
            {addStep === 1 ? (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  const dev = await api.createDevice({
                    name: newName,
                    device_type: newType,
                    room: newRoom,
                    max_volume: newMaxVol,
                    wake_word: newWakeWord,
                  });
                  setCreatedDev(dev);
                  setAddStep(2);
                  onRefreshDashboard();
                }}
                className="space-y-3 text-xs"
              >
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setNewType("speaker_xiaoai")}
                    className={`rounded-xl border p-3 text-left ${newType === "speaker_xiaoai" ? "border-[var(--brand-green)] bg-[var(--brand-green-soft)]" : "border-[var(--border-soft)]"}`}
                  >
                    <div className="font-bold">智能音箱 (Open-XiaoAI)</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setNewType("esp32_robot")}
                    className={`rounded-xl border p-3 text-left ${newType === "esp32_robot" ? "border-[var(--brand-green)] bg-[var(--brand-green-soft)]" : "border-[var(--border-soft)]"}`}
                  >
                    <div className="font-bold">ESP32 语音终端</div>
                  </button>
                </div>
                <input required value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="设备名称（如：客厅小爱Pro）*" className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
                <div className="grid grid-cols-2 gap-3">
                  <input value={newRoom} onChange={(e) => setNewRoom(e.target.value)} placeholder="所在房间" className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
                  <input value={newWakeWord} onChange={(e) => setNewWakeWord(e.target.value)} placeholder="唤醒词" className="rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm" />
                </div>
                <div>
                  <div>护耳最大音量限制：{newMaxVol}%</div>
                  <input type="range" min={20} max={100} value={newMaxVol} onChange={(e) => setNewMaxVol(Number(e.target.value))} className="w-full accent-[var(--brand-green)]" />
                </div>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setAddOpen(false)} className="rounded-xl border px-4 py-2">取消</button>
                  <button type="submit" className="rounded-xl bg-[var(--brand-green)] px-5 py-2 font-semibold text-white">生成凭证</button>
                </div>
              </form>
            ) : (
              createdDev && (
                <div className="space-y-3 text-xs">
                  <div className="rounded-xl bg-[var(--brand-green-soft)] p-3 font-bold text-[var(--brand-green)]">
                    设备已创建！在音箱终端运行以下连接命令或直接下载预填脚本：
                  </div>
                  <code className="block break-all rounded-xl bg-[#0b1120] p-3 font-mono text-[11px] text-cyan-300">
                    {createdDev.connect_cmd}
                  </code>
                  <div className="flex justify-between">
                    <button onClick={() => { navigator.clipboard?.writeText(createdDev.connect_cmd || ""); showToast("已复制命令行"); }} className="inline-flex items-center gap-1 rounded-xl border px-3 py-2">
                      <Copy className="h-3.5 w-3.5" /> 复制命令
                    </button>
                    <button onClick={() => handleDownloadScript(createdDev.id)} className="inline-flex items-center gap-1 rounded-xl bg-[var(--brand-green)] px-4 py-2 font-semibold text-white">
                      <Download className="h-3.5 w-3.5" /> 下载专属脚本
                    </button>
                  </div>
                </div>
              )
            )}
          </Modal>

          <SlideDrawer open={!!editDev} title={`设备配置 · ${editDev?.name || ""}`} onClose={() => setEditDev(null)}>
            {editDev && (
              <div className="space-y-4 text-xs">
                <input value={editDev.name} onChange={(e) => setEditDev({ ...editDev, name: e.target.value })} className="w-full rounded-xl border px-3 py-2 text-sm" placeholder="设备名称" />
                <input value={editDev.room} onChange={(e) => setEditDev({ ...editDev, room: e.target.value })} className="w-full rounded-xl border px-3 py-2 text-sm" placeholder="房间" />
                <div>
                  <div>护耳最大音量上限：{editDev.max_volume}%</div>
                  <input type="range" min={20} max={100} value={editDev.max_volume} onChange={(e) => setEditDev({ ...editDev, max_volume: Number(e.target.value) })} className="w-full accent-[var(--brand-green)]" />
                </div>
                {editDev.connect_cmd && (
                  <code className="block break-all rounded-xl bg-[#0b1120] p-3 font-mono text-[11px] text-cyan-300">
                    {editDev.connect_cmd}
                  </code>
                )}
                <button
                  onClick={async () => {
                    await api.updateDevice(editDev.id, { name: editDev.name, room: editDev.room, max_volume: editDev.max_volume });
                    setEditDev(null);
                    showToast("设备参数已更新");
                    onRefreshDashboard();
                  }}
                  className="w-full rounded-xl bg-[var(--brand-green)] py-2.5 font-semibold text-white"
                >
                  保存配置
                </button>
              </div>
            )}
          </SlideDrawer>

          <ConfirmDialog
            open={!!deleteTarget}
            title="解绑并删除设备？"
            message={`将把「${deleteTarget?.name}」从家庭控制台移除并断开连接。`}
            confirmLabel="确认解绑"
            onCancel={() => setDeleteTarget(null)}
            onConfirm={async () => {
              if (!deleteTarget) return;
              await api.deleteDevice(deleteTarget.id);
              setDeleteTarget(null);
              showToast("设备已解绑移除");
              onRefreshDashboard();
            }}
          />
        </div>
      )}

      {sysTab === "users" && <AdminUsersPage currentUser={currentUser} showToast={showToast} />}
      {sysTab === "settings" && <SettingsPage onRefreshDashboard={onRefreshDashboard} showToast={showToast} />}
    </div>
  );
}
