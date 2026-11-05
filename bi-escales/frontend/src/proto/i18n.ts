import { createInstance, type i18n as I18n } from "i18next";
import type { Lang } from "./format";
import { en, fr } from "./strings";

/**
 * A private instance, passed through I18nextProvider. It never registers as
 * the react-i18next global, so the app's strings and language stay untouched.
 */
export function createProtoI18n(lang: Lang): I18n {
  const instance = createInstance();
  void instance.init({
    resources: { fr: { translation: fr }, en: { translation: en } },
    lng: lang,
    fallbackLng: "fr",
    initAsync: false,
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });
  return instance;
}
