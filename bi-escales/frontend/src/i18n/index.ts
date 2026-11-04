import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

const stored = typeof localStorage !== "undefined" ? localStorage.getItem("bi-escales-lang") : null;
const fallbackLng = stored === "en" || stored === "fr" ? stored : "fr";

void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr }, en: { translation: en } },
  lng: fallbackLng,
  fallbackLng: "fr",
  interpolation: { escapeValue: false },
});

export default i18n;

export function setLanguage(lang: "fr" | "en") {
  void i18n.changeLanguage(lang);
  localStorage.setItem("bi-escales-lang", lang);
}
