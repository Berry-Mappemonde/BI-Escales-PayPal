/**
 * NAVIGUIDE — Lightweight i18n context
 * Provides useLang() hook with t(key, vars) translation function.
 * Language is persisted in localStorage. Opening language: DEFAULT_LANG.
 */
import { createContext, useCallback, useContext, useLayoutEffect, useState } from "react";
import en from "./en";
import fr from "./fr";
import { LEGACY_STORAGE_KEY, STORAGE_KEY, VALID_LANGS, readStoredLang } from "./langStorage";

const translations = { en, fr };

const LangContext = createContext(null);

export function LangProvider({ children }) {
  const [lang, setLang] = useState(() => readStoredLang());

  useLayoutEffect(() => {
    if (typeof document !== "undefined") document.documentElement.lang = lang;
  }, [lang]);

  const switchLang = useCallback((l) => {
    if (!VALID_LANGS.has(l)) return;
    if (typeof document !== "undefined") document.documentElement.lang = l;
    setLang(l);
    localStorage.setItem(STORAGE_KEY, l);
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  }, []);

  /**
   * Translate a key with optional variable interpolation.
   * t("currentSpeed", { speed: "3.2" }) → "Current: 3.2 knots"
   * Falls back to English, then to the key itself.
   */
  const t = useCallback(
    (key, vars = {}) => {
      const str =
        translations[lang]?.[key] ??
        translations.en?.[key] ??
        key;
      return Object.entries(vars).reduce(
        (s, [k, v]) => s.replace(`{${k}}`, v),
        str
      );
    },
    [lang]
  );

  return (
    <LangContext.Provider value={{ lang, switchLang, t }}>
      {children}
    </LangContext.Provider>
  );
}

export function useLang() {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used inside LangProvider");
  return ctx;
}
