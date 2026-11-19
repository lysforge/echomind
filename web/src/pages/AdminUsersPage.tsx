import React, { useEffect, useState } from "react";
import { KeyRound, Plus, ShieldCheck, Trash2, UserCheck, UserCog, UserX } from "lucide-react";
import { api, AuthUser } from "../api";
import { ConfirmDialog, EmptyState, Modal } from "../components/Modal";

export function AdminUsersPage({
  currentUser,
  showToast,
}: {
  currentUser: AuthUser;
  showToast: (m: string) => void;
}) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(true);

  // 新建用户 Modal
  const [createOpen, setCreateOpen] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<"user" | "admin">("user");
  const [submitting, setSubmitting] = useState(false);

  // 编辑/重置密码 Modal
  const [editTarget, setEditTarget] = useState<AuthUser | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editRole, setEditRole] = useState<"user" | "admin">("user");
  const [editNewPassword, setEditNewPassword] = useState("");

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<AuthUser | null>(null);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const list = await api.adminListUsers();
      setUsers(list);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadUsers();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim() || newPassword.length < 6) {
      showToast("请填写用户名且密码不少于 6 位");
      return;
    }
    setSubmitting(true);
    try {
      await api.adminCreateUser({
        username: newUsername.trim(),
        display_name: newDisplayName.trim() || newUsername.trim(),
        password: newPassword,
        role: newRole,
      });
      showToast(`已创建账号「${newUsername.trim()}」`);
      setCreateOpen(false);
      setNewUsername("");
      setNewDisplayName("");
      setNewPassword("");
      setNewRole("user");
      await loadUsers();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editTarget) return;
    if (editNewPassword && editNewPassword.length < 6) {
      showToast("新密码至少需要 6 位");
      return;
    }
    try {
      await api.adminUpdateUser(editTarget.id, {
        display_name: editDisplayName.trim() || editTarget.username,
        role: editRole,
        ...(editNewPassword ? { new_password: editNewPassword } : {}),
      });
      showToast(`已更新账号「${editTarget.username}」`);
      setEditTarget(null);
      setEditNewPassword("");
      await loadUsers();
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const handleToggleActive = async (u: AuthUser) => {
    if (u.id === currentUser.id) {
      showToast("不能停用当前正在使用的账号");
      return;
    }
    const nextActive = u.is_active === 1 ? false : true;
    try {
      await api.adminUpdateUser(u.id, { is_active: nextActive });
      showToast(`${u.username} 已${nextActive ? "启用" : "停用"}`);
      await loadUsers();
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await api.adminDeleteUser(deleteTarget.id);
      showToast(`已删除账号「${deleteTarget.username}」`);
      setDeleteTarget(null);
      await loadUsers();
    } catch (e) {
      showToast((e as Error).message);
    }
  };

  const adminCount = users.filter((u) => u.role === "admin").length;
  const activeCount = users.filter((u) => u.is_active === 1).length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold tracking-tight">平台账号与权限管理</h2>
          <p className="mt-0.5 text-sm text-[var(--ink-muted)]">
            为家庭成员或共同照顾者分配独立登录账号与 RBAC 角色（管理员可配置音源、模型与系统参数）
          </p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="inline-flex items-center gap-2 rounded-xl bg-[var(--brand-green)] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[var(--brand-green-hover)]"
        >
          <Plus className="h-4 w-4" />
          新建账号
        </button>
      </div>

      {/* 统计卡 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="card-pro p-4">
          <div className="text-xs text-[var(--ink-muted)]">总注册账号</div>
          <div className="mt-1 text-2xl font-bold">{users.length}</div>
        </div>
        <div className="card-pro p-4">
          <div className="text-xs text-[var(--ink-muted)]">超级管理员</div>
          <div className="mt-1 text-2xl font-bold text-[var(--brand-green)]">{adminCount}</div>
        </div>
        <div className="card-pro p-4">
          <div className="text-xs text-[var(--ink-muted)]">活跃启用账号</div>
          <div className="mt-1 text-2xl font-bold text-amber-700">{activeCount}</div>
        </div>
      </div>

      {/* 用户列表 */}
      <div className="card-pro overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-[var(--ink-muted)]">正在加载账号列表…</div>
        ) : users.length === 0 ? (
          <EmptyState
            icon={UserCog}
            title="暂无账号记录"
            description="点击右上角新建家庭普通账号或管理员账号"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--border-soft)] bg-zinc-50/80 text-xs text-[var(--ink-muted)]">
                  <th className="px-4 py-3 font-semibold">用户 / 显示名</th>
                  <th className="px-4 py-3 font-semibold">角色权限</th>
                  <th className="px-4 py-3 font-semibold">状态</th>
                  <th className="px-4 py-3 font-semibold">最近登录</th>
                  <th className="px-4 py-3 text-right font-semibold">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-soft)]">
                {users.map((u) => {
                  const isSelf = u.id === currentUser.id;
                  return (
                    <tr key={u.id} className="hover:bg-zinc-50/50">
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--brand-green-soft)] text-xs font-bold text-[var(--brand-green)]">
                            {(u.display_name || u.username).slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <div className="flex items-center gap-1.5 font-semibold">
                              <span>{u.display_name}</span>
                              {isSelf && (
                                <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] font-medium text-zinc-700">
                                  当前登录
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-[var(--ink-muted)]">@{u.username}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        {u.role === "admin" ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--brand-green-soft)] px-2.5 py-1 text-xs font-semibold text-[var(--brand-green)]">
                            <ShieldCheck className="h-3.5 w-3.5" />
                            平台管理员
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-700">
                            <UserCheck className="h-3.5 w-3.5" />
                            普通家庭账号
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        {u.is_active === 1 ? (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
                            <span className="h-2 w-2 rounded-full bg-emerald-500" />
                            已启用
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-rose-600">
                            <span className="h-2 w-2 rounded-full bg-rose-500" />
                            已停用
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-xs text-[var(--ink-muted)]">
                        {u.last_login_at ? u.last_login_at.replace("T", " ").slice(0, 16) : "尚未登录"}
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          <button
                            onClick={() => {
                              setEditTarget(u);
                              setEditDisplayName(u.display_name);
                              setEditRole(u.role);
                              setEditNewPassword("");
                            }}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs font-medium hover:bg-zinc-50"
                            title="编辑资料 / 改密"
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                            编辑 / 改密
                          </button>
                          <button
                            onClick={() => handleToggleActive(u)}
                            disabled={isSelf}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--border-soft)] bg-white px-2.5 py-1.5 text-xs font-medium hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-45"
                            title={u.is_active === 1 ? "停用该账号" : "恢复启用"}
                          >
                            {u.is_active === 1 ? <UserX className="h-3.5 w-3.5" /> : <UserCheck className="h-3.5 w-3.5" />}
                            {u.is_active === 1 ? "停用" : "启用"}
                          </button>
                          <button
                            onClick={() => setDeleteTarget(u)}
                            disabled={isSelf}
                            className="inline-flex items-center rounded-lg border border-rose-200 bg-rose-50 p-1.5 text-rose-600 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-40"
                            title="删除账号"
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
        )}
      </div>

      {/* 新建用户弹窗 */}
      <Modal open={createOpen} title="新建平台账号" onClose={() => setCreateOpen(false)}>
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold">登录用户名 *</label>
            <input
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              placeholder="例如：mom / grandma / dad"
              required
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">展示昵称</label>
            <input
              value={newDisplayName}
              onChange={(e) => setNewDisplayName(e.target.value)}
              placeholder="例如：妈妈、外婆"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">初始密码（至少 6 位）*</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="设置初始登录密码"
              required
              minLength={6}
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">账号角色</label>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as "user" | "admin")}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            >
              <option value="user">普通家庭账号（使用书架、音箱播控、英语、成员声纹）</option>
              <option value="admin">平台管理员（含采集源配置、模型密钥、账号权限管理）</option>
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              className="rounded-xl border border-[var(--border-soft)] px-4 py-2 text-sm font-medium"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-xl bg-[var(--brand-green)] px-5 py-2 text-sm font-semibold text-white hover:bg-[var(--brand-green-hover)] disabled:opacity-60"
            >
              {submitting ? "创建中…" : "确认创建"}
            </button>
          </div>
        </form>
      </Modal>

      {/* 编辑/重置密码弹窗 */}
      <Modal open={Boolean(editTarget)} title={`编辑账号 · ${editTarget?.username || ""}`} onClose={() => setEditTarget(null)}>
        <form onSubmit={handleSaveEdit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-semibold">展示昵称</label>
            <input
              value={editDisplayName}
              onChange={(e) => setEditDisplayName(e.target.value)}
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">角色权限</label>
            <select
              value={editRole}
              disabled={editTarget?.id === currentUser.id}
              onChange={(e) => setEditRole(e.target.value as "user" | "admin")}
              className="w-full rounded-xl border border-[var(--border-soft)] bg-white px-3 py-2 text-sm outline-none disabled:bg-zinc-100"
            >
              <option value="user">普通家庭账号 (user)</option>
              <option value="admin">平台管理员 (admin)</option>
            </select>
            {editTarget?.id === currentUser.id && (
              <p className="mt-1 text-[11px] text-[var(--ink-muted)]">当前登录账号不可自降权限</p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold">重置密码（留空则不修改密码）</label>
            <input
              type="password"
              value={editNewPassword}
              onChange={(e) => setEditNewPassword(e.target.value)}
              placeholder="如需修改请输入至少 6 位新密码"
              className="w-full rounded-xl border border-[var(--border-soft)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-green)]"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setEditTarget(null)}
              className="rounded-xl border border-[var(--border-soft)] px-4 py-2 text-sm font-medium"
            >
              取消
            </button>
            <button
              type="submit"
              className="rounded-xl bg-[var(--brand-green)] px-5 py-2 text-sm font-semibold text-white hover:bg-[var(--brand-green-hover)]"
            >
              保存修改
            </button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="确认删除账号"
        message={`删除账号「${deleteTarget?.username || ""}」后，该账号将立即失效且不可恢复（其名下的家庭成员与音箱不受影响）。确定继续吗？`}
        confirmLabel="永久删除"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}
