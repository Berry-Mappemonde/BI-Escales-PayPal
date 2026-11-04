import { getCardinalDirection } from "./getCardinalDirection.js";

export function formatMetNumber(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Number(n.toFixed(digits)).toString();
}

/** Code 16 rumbs (N, ENE, SSE, …). Vide si pas d’angle. */
export function formatCardinal(degrees, lang = "fr") {
  const n = Number(degrees);
  if (!Number.isFinite(n)) return "";
  return getCardinalDirection(((n % 360) + 360) % 360, lang);
}

/** Cardinale d’abord, puis degrés : « SSE · 162.5° ». */
export function formatBearingCardinal(degrees, lang = "fr") {
  const n = Number(degrees);
  if (!Number.isFinite(n)) return "";
  const wrapped = ((n % 360) + 360) % 360;
  const shown = formatMetNumber(wrapped, 1);
  const card = formatCardinal(wrapped, lang);
  return card ? `${card} · ${shown}°` : `${shown}°`;
}

export function formatMetTime(value) {
  if (value == null || value === "") return "";
  const text = String(value);
  const d = new Date(text);
  if (Number.isNaN(d.getTime())) return text.replace("T", " ").replace(/Z$/, " UTC");
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function formatCellLabel(cell) {
  if (!cell || typeof cell !== "object") return "";
  const lat = formatMetNumber(cell.lat, 3);
  const lon = formatMetNumber(cell.lon, 3);
  const deg = cell.deg != null ? `${cell.deg}°` : "";
  if (lat == null || lon == null) return deg;
  return `${lat}, ${lon}${deg ? ` (${deg})` : ""}`;
}
