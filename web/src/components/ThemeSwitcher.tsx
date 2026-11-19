import React, { useEffect, useState } from "react";

export type ThemeId = "radio" | "indigo" | "sky" | "vinyl";

export interface ThemeMeta {
  id: ThemeId;
  label: string;
  swatch: string;
  ring: string;
}

export const THEMES: ThemeMeta[] = [
  { id: "radio", label: "暖阳电台 · 珊瑚橙", swatch: "#ea580c", ring: "#fdba74" },
  { id: "indigo", label: "极简科技 · 靛蓝", swatch: "#4f46e5", ring: "#a5b4fc" },
  { id: "sky", label: "晴空伴学 · 海洋蓝", swatch: "#0284c7", ring: "#7dd3fc" },
  { id: "vinyl", label: "深邃黑胶 · 夜间模式", swatch: "#0f172a", ring: "#22d3ee" },
];

const THEME_KEY = "echomind_theme";

function normalizeTheme(raw: string | null): ThemeId {
  if (raw === "radio" || raw === "indigo" || raw === "sky" || raw === "vinyl") {
    return raw;
  }
  return "radio";
}

export function useTheme(): [ThemeId, (next: ThemeId) => void] {
  const [theme, setTheme] = useState<ThemeId>(() => {
    try {
      return normalizeTheme(document.documentElement.dataset.theme || localStorage.getItem(THEME_KEY));
    } catch {
      return "radio";
    }
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // ignore storage quota errors
    }
  }, [theme]);

  return [theme, setTheme];
}

export function ThemeSwitcher() {
  const [theme, setTheme] = useTheme();

  return (
    <div
      className="inline-flex items-center gap-1.5 rounded-xl border border-[var(--border-soft)] bg-[var(--bg-card)] px-2.5 py-1.5"
      title="切换界面主题配色"
    >
      {THEMES.map((item) => {
        const active = theme === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => setTheme(item.id)}
            title={item.label}
            aria-label={item.label}
            aria-pressed={active}
            className="relative flex h-4 w-4 items-center justify-center rounded-full transition-transform hover:scale-110"
            style={{
              backgroundColor: item.swatch,
              boxShadow: active ? `0 0 0 2px var(--bg-card), 0 0 0 3.5px ${item.ring}` : undefined,
              border: item.id === "vinyl" ? "1px solid #334155" : "1px solid rgba(0,0,0,0.08)",
            }}
          />
        );
      })}
    </div>
  );
}
