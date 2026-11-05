/**
 * Fiche d'escale : GET /escale de naviguide-escales/server/escale_api.py
 * quand VITE_NAVIGUIDE_API_URL est défini. Sinon le snapshot
 * public/escale-marinas.json (marinas BI proches des escales, même forme
 * sections.mooring.marinas que _slim).
 */
import { marinasToFeatures } from "./marinasToFeatures.js";

function apiBase() {
  return String(import.meta.env.VITE_API_BASE ?? "").trim().replace(/\/$/, "");
}

function escaleFicheUrl(path) {
  const base = apiBase();
  const p = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${p}` : p;
}

export async function loadEscaleFiche(stop, lang) {
  const base = String(import.meta.env.VITE_NAVIGUIDE_API_URL || "").trim().replace(/\/$/, "");
  if (base && stop?.name) {
    const query = new URLSearchParams({
      name: stop.name,
      lat: String(stop.lat),
      lon: String(stop.lon),
      lang: lang === "en" ? "en" : "fr",
    });
    const res = await fetch(`${base}/escale?${query}`);
    if (res.ok) return res.json();
  }
  if (stop?.name) {
    const query = new URLSearchParams({
      name: stop.name,
      lat: String(stop.lat),
      lon: String(stop.lon),
      lang: lang === "en" ? "en" : "fr",
    });
    const res = await fetch(`${escaleFicheUrl("/api/escale-fiche")}?${query}`);
    if (res.ok) return res.json();
  }
  const res = await fetch("/escale-marinas.json");
  if (!res.ok) return { sections: {} };
  const snapshot = await res.json();
  return snapshot.escales?.[stop?.name] || { name: stop?.name, sections: {} };
}

export function ficheMarinas(fiche) {
  return marinasToFeatures(fiche);
}
