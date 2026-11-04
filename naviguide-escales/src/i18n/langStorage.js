/** Clé du choix déjà fait. Elle passe devant DEFAULT_LANG. */
export const STORAGE_KEY = "naviguide_lang_v4";

/** Clé précédente (défaut français). Lue une fois, puis recopiée dans STORAGE_KEY. */
export const LEGACY_STORAGE_KEY = "naviguide_lang_v3";

/**
 * Langue à l'ouverture, quand rien n'est enregistré.
 * Le fichier index.html doit porter le même code dans <html lang="…">.
 */
export const DEFAULT_LANG = "en";

export const VALID_LANGS = new Set(["en", "fr"]);

/** Choix enregistré s'il est connu, sinon la langue d'ouverture. */
export function resolveLang(stored) {
  return VALID_LANGS.has(stored) ? stored : DEFAULT_LANG;
}

/**
 * v4 si elle est connue, sinon l'ancienne v3 (recopiée dans v4), sinon l'anglais.
 * Une seule clé reste après la copie.
 */
export function readStoredLang(storage = typeof localStorage !== "undefined" ? localStorage : null) {
  if (!storage?.getItem) return DEFAULT_LANG;
  const current = storage.getItem(STORAGE_KEY);
  if (VALID_LANGS.has(current)) return current;
  const legacy = storage.getItem(LEGACY_STORAGE_KEY);
  if (VALID_LANGS.has(legacy)) {
    try {
      storage.setItem?.(STORAGE_KEY, legacy);
      storage.removeItem?.(LEGACY_STORAGE_KEY);
    } catch {
      /* navigation privée : on respecte le choix sans l'écrire */
    }
    return legacy;
  }
  return DEFAULT_LANG;
}
