import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

/** First visit when `bi-escales-lang` is unset (demo / judge screenshots). */
const FIRST_VISIT_DEFAULT_LANG: "en" = "en";

/**
 * Reserved for a later browser-locale policy (not used for first-load default).
 * Intended future: `fr` → FR; else if `navigator.language` matches a BI Escales locale, use it; else EN.
 */
function browserDefaultLang(): "fr" | "en" {
  if (typeof navigator === "undefined") return "fr";
  const nav = String(navigator.language || "");
  return nav.toLowerCase().startsWith("en") ? "en" : "fr";
}
void browserDefaultLang;

const stored = typeof localStorage !== "undefined" ? localStorage.getItem("bi-escales-lang") : null;
const fallbackLng =
  stored === "en" || stored === "fr" ? stored : FIRST_VISIT_DEFAULT_LANG;

export function normalizeAppLang(lang?: string): "fr" | "en" {
  return String(lang || "fr").toLowerCase().startsWith("en") ? "en" : "fr";
}

export function applyDocumentLang(lang?: string) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = normalizeAppLang(lang);
}

function setMetaContent(selector: string, value: string) {
  const el = document.querySelector(selector);
  if (el) el.setAttribute("content", value);
}

/** Sync `<title>` and social meta tags when the UI language changes. */
export function applyDocumentMeta() {
  if (typeof document === "undefined") return;
  const title = i18n.t("app.title");
  document.title = title;
  const description = i18n.t("app.metaDescription");
  setMetaContent('meta[name="description"]', description);
  setMetaContent('meta[property="og:title"]', title);
  setMetaContent('meta[property="og:description"]', description);
  setMetaContent('meta[property="og:locale"]', i18n.t("app.ogLocale"));
  setMetaContent('meta[name="twitter:title"]', title);
  setMetaContent('meta[name="twitter:description"]', description);
}

void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, en: { translation: en } },
  lng: fallbackLng,
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

applyDocumentLang(fallbackLng);
i18n.on("initialized", () => {
  applyDocumentMeta();
});
i18n.on("languageChanged", (lng) => {
  applyDocumentLang(lng);
  applyDocumentMeta();
});
if (i18n.isInitialized) {
  applyDocumentMeta();
}

export default i18n;

export function setLanguage(lang: "fr" | "en") {
  void i18n.changeLanguage(lang);
  localStorage.setItem("bi-escales-lang", lang);
  applyDocumentLang(lang);
  applyDocumentMeta();
}
