import React from "react";
import { AlertTriangle, X } from "lucide-react";
import { AgeStage, BookItem, EnglishLevel } from "../api";

export const AGE_STAGE_LABELS: Record<AgeStage, string> = {
  S1_0_3: "0-3岁 · 感官韵律",
  S2_3_6: "3-6岁 · 绘本习惯",
  S3_6_9: "6-9岁 · 桥梁科普",
  S4_9_12: "9-12岁 · 少年文学",
  S5_12_18: "12-18岁 · 青少年进阶",
  S6_ALL: "全龄 / 家庭共享",
};

export const ENGLISH_LEVEL_LABELS: Record<EnglishLevel, string> = {
  Pre_A1: "Pre-A1 · 零基础磨耳朵",
  A1: "A1 · 拼读日常短句",
  A2: "A2 · 桥梁阅读问答",
  B1: "B1 · 章节独立听说",
  B2_PLUS: "B2+ · 原版思辨对话",
  adult: "成人通用",
};

export const BOOK_CATEGORY_LABELS: Record<BookItem["category"], string> = {
  picture_book: "绘本故事",
  bridge_book: "桥梁书",
  chapter_lit: "章节文学",
  science: "科普百科",
  english_graded: "英语分级读物",
};

export function Modal({
  open,
  title,
  onClose,
  children,
  maxWidth = "max-w-xl",
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  maxWidth?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]">
      <div className={`w-full ${maxWidth} max-h-[90vh] overflow-y-auto rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-card)] p-6 text-[var(--ink-primary)] shadow-2xl`}>
        <div className="mb-4 flex items-center justify-between border-b border-[var(--border-soft)] pb-3">
          <h3 className="text-base font-bold">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700">
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function SlideDrawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/35 backdrop-blur-[1px]">
      <div className="flex h-full w-full max-w-lg flex-col border-l border-[var(--border-soft)] bg-[var(--bg-card)] text-[var(--ink-primary)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--border-soft)] px-5 py-4">
          <h3 className="text-base font-bold">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认删除",
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border-soft)] bg-[var(--bg-card)] p-6 text-[var(--ink-primary)] shadow-2xl">
        <div className="flex items-start gap-3">
          <div className="rounded-full bg-rose-100 p-2 text-rose-600">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base font-bold">{title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-[var(--ink-muted)]">{message}</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-xl border border-[var(--border-soft)] px-4 py-2 text-xs font-medium hover:bg-zinc-50"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-medium text-white hover:bg-rose-700"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="card-pro flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--brand-green-soft)] text-[var(--brand-green)]">
        <Icon className="h-6 w-6" />
      </div>
      <h4 className="text-sm font-bold">{title}</h4>
      <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--ink-muted)]">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
