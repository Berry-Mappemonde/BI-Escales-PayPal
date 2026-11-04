/** Optional `?climo=cyclones&map=28,180,3` for recette / deep links. */

export function recetteClimoFlags(search = typeof window !== "undefined" ? window.location.search : "") {
  const raw = new URLSearchParams(search).get("climo") || "";
  const parts = raw.toLowerCase().split(/[,+\s]+/).filter(Boolean);
  return {
    wind: parts.includes("wind"),
    wave: parts.includes("wave"),
    current: parts.includes("current"),
    cyclones: parts.includes("cyclones"),
  };
}

export function recetteMonth(search = typeof window !== "undefined" ? window.location.search : "") {
  const n = Number(new URLSearchParams(search).get("month"));
  if (!Number.isFinite(n)) return null;
  const m = Math.round(n);
  return m >= 1 && m <= 12 ? m : null;
}

export function recetteMapView(search = typeof window !== "undefined" ? window.location.search : "") {
  const raw = new URLSearchParams(search).get("map");
  if (!raw) return null;
  const [lat, lon, z] = raw.split(",").map(Number);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { lat, lon, z: Number.isFinite(z) ? z : 3 };
}
