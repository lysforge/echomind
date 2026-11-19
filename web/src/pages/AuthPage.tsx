import React, { useState } from "react";
import { ShieldCheck, Volume2 } from "lucide-react";
import { api, AuthUser, setStoredToken } from "../api";
import { ThemeSwitcher } from "../components/ThemeSwitcher";

export function AuthPage({
  initialized,
  onSuccess,
}: {
  initialized: boolean;
  onSuccess: (user: AuthUser) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">(initialized ? "login" : "register");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res =
        mode === "register"
          ? await api.register({ username, password, display_name: displayName || username })
          : await api.login({ username, password });
      setStoredToken(res.token);
      onSuccess(res.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-[var(--bg-canvas)] p-4 text-[var(--ink-primary)]">
      <div className="fixed right-5 top-5 z-10">
        <ThemeSwitcher />
      </div>
      <div className="w-full max-w-md rounded-3xl border border-[var(--border-soft)] bg-[var(--bg-card)] p-8 shadow-xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[var(--brand-green)] text-white">
            <Volume2 className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">EchoMind · 声忆智能中枢</h1>
            <p className="text-xs text-[var(--ink-muted)]">全龄段家庭音频库 · 声纹记忆 · 音箱播控台</p>
          </div>
        </div>

        {!initialized && (
          <div className="mb-5 flex items-start gap-2.5 rounded-2xl bg-[var(--brand-green-soft)] p-3.5 text-xs text-[var(--brand-green)]">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-bold">首次部署初始化：创建平台超级管理员</div>
              <div className="mt-0.5 opacity-90">首个注册账号将自动获得管理员权限，用于管理家庭用户、播客采集源与全阶有声内容库。</div>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--ink-muted)]">登录账号</label>
            <input
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="例如 admin"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          {mode === "register" && (
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--ink-muted)]">显示昵称（选填）</label>
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="例如 家庭管理员 / 爸爸"
                className="w-full rounded-xl border border-[var(--border-soft)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--brand-green)]"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--ink-muted)]">密码（至少 4 位）</label>
            <input
              required
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>

          {error && <div className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</div>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-[var(--brand-green)] py-2.5 text-sm font-semibold text-white transition hover:bg-[var(--brand-green-hover)] disabled:opacity-50"
          >
            {loading ? "处理中..." : mode === "register" ? (initialized ? "注册普通账号" : "创建管理员并进入平台") : "登录控制台"}
          </button>
        </form>

        {initialized && (
          <div className="mt-4 text-center text-xs text-[var(--ink-muted)]">
            {mode === "login" ? (
              <button onClick={() => setMode("register")} className="text-[var(--brand-green)] hover:underline">
                没有账号？注册新的家庭成员账号
              </button>
            ) : (
              <button onClick={() => setMode("login")} className="text-[var(--brand-green)] hover:underline">
                已有账号？返回登录
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
