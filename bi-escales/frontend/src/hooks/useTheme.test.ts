import { beforeEach, describe, expect, it } from "vitest";
import {
  THEME_STORAGE_KEY,
  applyTheme,
  readStoredTheme,
  readThemeFromSearch,
  resolveTheme,
} from "./useTheme";

describe("useTheme helpers", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("readThemeFromSearch accepts ?theme=light|dark", () => {
    expect(readThemeFromSearch("?theme=light")).toBe("light");
    expect(readThemeFromSearch("?theme=dark")).toBe("dark");
    expect(readThemeFromSearch("?theme=invalid")).toBeNull();
  });

  it("resolveTheme prefers the URL param over localStorage", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(resolveTheme("?theme=light")).toBe("light");
  });

  it("resolveTheme falls back to localStorage then dark", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(resolveTheme("")).toBe("light");
    expect(resolveTheme("?foo=1")).toBe("light");
    localStorage.removeItem(THEME_STORAGE_KEY);
    expect(resolveTheme("")).toBe("dark");
  });

  it("applyTheme sets dataset.theme and persists", () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(readStoredTheme()).toBe("light");
  });
});
