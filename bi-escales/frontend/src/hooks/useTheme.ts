import { useCallback, useEffect, useState } from "react";

export type ThemeId = "light" | "dark";

export const THEME_STORAGE_KEY = "escales.theme";

export function readThemeFromSearch(search: string): ThemeId | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const raw = params.get("theme");
  if (raw === "light" || raw === "dark") return raw;
  return null;
}

export function readStoredTheme(): ThemeId | null {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (raw === "light" || raw === "dark") return raw;
  } catch {
    /* private mode */
  }
  return null;
}

export function resolveTheme(search: string): ThemeId {
  return readThemeFromSearch(search) ?? readStoredTheme() ?? "dark";
}

export function applyTheme(theme: ThemeId): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* private mode */
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeId>(() => resolveTheme(window.location.search));

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: ThemeId) => {
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current) => (current === "light" ? "dark" : "light"));
  }, []);

  return { theme, setTheme, toggleTheme };
}
