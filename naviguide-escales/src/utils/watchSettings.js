/**
 * R42 : interrupteur « Veille Tavily » des réglages. L'état vit côté serveur
 * (GET/POST /escale/watch/settings, gardé dans pearl_store) : le navigateur
 * n'appelle jamais Tavily, il ne fait que lire et changer le drapeau.
 */
import { adminHeaders } from "./adminSecret.js";

const API_URL = import.meta.env?.VITE_API_URL ?? "";
export const WATCH_SETTINGS_PATH = "/escale/watch/settings";

export function parseWatchSettings(data) {
  if (!data || typeof data.enabled !== "boolean") return null;
  return { enabled: data.enabled, source: data.source === "setting" ? "setting" : "env" };
}

export async function fetchWatchSettings(fetchImpl = fetch, base = API_URL) {
  const res = await fetchImpl(`${base}${WATCH_SETTINGS_PATH}`);
  if (!res.ok) throw new Error(`http ${res.status}`);
  return parseWatchSettings(await res.json());
}

/** Renvoie { ok, settings } ou { ok: false, reason: "admin" | "error" }. */
export async function saveWatchSettings(enabled, fetchImpl = fetch, base = API_URL, headers = adminHeaders()) {
  try {
    const res = await fetchImpl(`${base}${WATCH_SETTINGS_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    });
    if (res.status === 401 || res.status === 403) return { ok: false, reason: "admin" };
    if (!res.ok) return { ok: false, reason: "error" };
    const settings = parseWatchSettings(await res.json());
    return settings ? { ok: true, settings } : { ok: false, reason: "error" };
  } catch {
    return { ok: false, reason: "error" };
  }
}
