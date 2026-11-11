import { afterEach, describe, expect, it, vi } from "vitest";
import { LANG_STORAGE_KEY, readLangFromSearch, resolveInitialLang } from "./index";

describe("?lang= in the page address", () => {
  afterEach(() => {
    localStorage.removeItem(LANG_STORAGE_KEY);
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("reads fr and en, with or without a region, in any case", () => {
    expect(readLangFromSearch("?lang=fr")).toBe("fr");
    expect(readLangFromSearch("?lang=en")).toBe("en");
    expect(readLangFromSearch("lang=FR")).toBe("fr");
    expect(readLangFromSearch("?theme=light&lang=fr-FR")).toBe("fr");
    expect(readLangFromSearch("?lang=en-GB")).toBe("en");
  });

  it("ignores anything else", () => {
    expect(readLangFromSearch("")).toBeNull();
    expect(readLangFromSearch("?lang=")).toBeNull();
    expect(readLangFromSearch("?lang=de")).toBeNull();
    expect(readLangFromSearch("?language=fr")).toBeNull();
  });

  it("puts the address before the remembered choice, and the remembered choice before the default", () => {
    expect(resolveInitialLang("")).toBe("en");
    localStorage.setItem(LANG_STORAGE_KEY, "fr");
    expect(resolveInitialLang("")).toBe("fr");
    expect(resolveInitialLang("?lang=en")).toBe("en");
    expect(resolveInitialLang("?lang=de")).toBe("fr");
  });

  it("starts the page in the address's language and remembers it", async () => {
    localStorage.setItem(LANG_STORAGE_KEY, "en");
    vi.resetModules();
    vi.stubGlobal("location", { ...window.location, search: "?lang=fr" });
    const fresh = (await import("./index")).default;
    expect(fresh.language).toBe("fr");
    expect(document.documentElement.lang).toBe("fr");
    expect(localStorage.getItem(LANG_STORAGE_KEY)).toBe("fr");
  });

  it("leaves the remembered choice alone when the address names no language", async () => {
    localStorage.setItem(LANG_STORAGE_KEY, "fr");
    vi.resetModules();
    vi.stubGlobal("location", { ...window.location, search: "?theme=light" });
    const fresh = (await import("./index")).default;
    expect(fresh.language).toBe("fr");
    expect(localStorage.getItem(LANG_STORAGE_KEY)).toBe("fr");
  });
});
