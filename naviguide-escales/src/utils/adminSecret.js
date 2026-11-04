/**
 * Clé admin partagée (sécurité P0). Le serveur exige l'en-tête
 * `X-Naviguide-Admin` sur les écritures officielles (route, GRIB, polaire).
 *
 * La clé se pose une fois : `?admin=LA_CLE` dans l'URL (retirée aussitôt de
 * la barre d'adresse) ou le champ « Clé admin » des outils. Elle reste dans
 * localStorage de ce navigateur uniquement ; un visiteur sans clé lit tout,
 * n'écrit rien.
 */
export const ADMIN_HEADER = "X-Naviguide-Admin";
export const ADMIN_STORAGE_KEY = "ng.sim.adminSecret";
const URL_PARAM = "admin";

function storage() {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function getAdminSecret() {
  const s = storage();
  if (!s) return "";
  try {
    return (s.getItem(ADMIN_STORAGE_KEY) || "").trim();
  } catch {
    return "";
  }
}

export function setAdminSecret(value) {
  const s = storage();
  if (!s) return;
  const v = String(value || "").trim();
  try {
    if (v) s.setItem(ADMIN_STORAGE_KEY, v);
    else s.removeItem(ADMIN_STORAGE_KEY);
  } catch {
    /* quota / private mode: the key simply does not persist */
  }
}

export function hasAdminSecret() {
  return Boolean(getAdminSecret());
}

/** Headers to spread into a fetch(): empty for a visitor, the admin header otherwise. */
export function adminHeaders() {
  const secret = getAdminSecret();
  return secret ? { [ADMIN_HEADER]: secret } : {};
}

/**
 * `?admin=…` in the address bar → stored, then removed from the URL so the
 * key never lands in a screenshot, a bookmark or a shared link.
 * Returns true when a key was captured.
 */
export function captureAdminSecretFromUrl(win = typeof window !== "undefined" ? window : null) {
  if (!win?.location) return false;
  let url;
  try {
    url = new URL(win.location.href);
  } catch {
    return false;
  }
  if (!url.searchParams.has(URL_PARAM)) return false;
  const value = url.searchParams.get(URL_PARAM) || "";
  url.searchParams.delete(URL_PARAM);
  setAdminSecret(value);
  try {
    win.history.replaceState(win.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  } catch {
    /* history API unavailable: the key is stored anyway */
  }
  return Boolean(value.trim());
}
