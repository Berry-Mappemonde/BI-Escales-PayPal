import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

function browserDefaultLang(): "fr" | "en" {
  if (typeof navigator === "undefined") return "fr";
  const nav = String(navigator.language || "");
  return nav.toLowerCase().startsWith("en") ? "en" : "fr";
}

const stored = typeof localStorage !== "undefined" ? localStorage.getItem("bi-escales-lang") : null;
const fallbackLng = stored === "en" || stored === "fr" ? stored : browserDefaultLang();

export function normalizeAppLang(lang?: string): "fr" | "en" {
  return String(lang || "fr").toLowerCase().startsWith("en") ? "en" : "fr";
}

export function applyDocumentLang(lang?: string) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = normalizeAppLang(lang);
}

void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, en: { translation: en } },
  lng: fallbackLng,
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

applyDocumentLang(fallbackLng);
i18n.on("languageChanged", (lng) => {
  applyDocumentLang(lng);
});

export default i18n;

export function setLanguage(lang: "fr" | "en") {
  void i18n.changeLanguage(lang);
  localStorage.setItem("bi-escales-lang", lang);
  applyDocumentLang(lang);
}
