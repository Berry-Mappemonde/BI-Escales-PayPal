/** Shared map-layer constants (tiles, colors, styles, helpers). */

export const TILE_URLS = {
  dark: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  light: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
};

/**
 * Base-map credit shown by Leaflet's attribution control. Leaflet already
 * prefixes its own link ("Leaflet") — never repeat the word here.
 */
export function tileAttribution(lang = "fr") {
  const lead = String(lang || "fr").toLowerCase().startsWith("en") ? "Tiles" : "Tuiles";
  return `${lead} &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener noreferrer">Esri</a> — <a href="https://www.here.com/" target="_blank" rel="noopener noreferrer">HERE</a>, <a href="https://www.garmin.com/" target="_blank" rel="noopener noreferrer">Garmin</a>, &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>`;
}

export const TILE_ATTRIBUTION = tileAttribution("fr");

/**
 * Marge basse min. des crédits Leaflet (px) : hauteur barre film (96) +
 * `bottom-5` (20). `--sim-inset-bottom` ne doit jamais passer sous ce plancher
 * tant que la barre est visible.
 */
export const LEAFLET_ATTRIBUTION_BOTTOM_MIN_PX = 116;

export const FALLBACK_COLORS = {
  "MPA": "#00f0ff", "Conservation": "#39ff14", "Research": "#c084fc",
  "Fisheries": "#fbbf24", "Policy & Advocacy": "#f472b6", "Pollution": "#ff4a4a",
  "Coastal & Habitat": "#34d399", "Education": "#60a5fa", "Other": "#94a3b8",
};

// Formalities mode = world EEZ choropleth + PoE markers.
export const ZONE_COLORS = {
  non_generee: "#64748b", ia: "#fbbf24", ia_sans_source: "#fbbf24", erreur: "#ff4a4a",
};

/** ProtectedSeas fishing-protection level (LFP 0–5). */
export const LFP_COLORS = {
  0: "#64748b",
  1: "#86efac",
  2: "#4ade80",
  3: "#38bdf8",
  4: "#f59e0b",
  5: "#ef4444",
};

export const ampStyle = (lfp) => {
  const n = Number(lfp);
  const color = LFP_COLORS[n] || LFP_COLORS[0];
  return {
    color,
    weight: 1.4,
    opacity: 0.9,
    fillColor: color,
    fillOpacity: n >= 4 ? 0.28 : n >= 3 ? 0.18 : 0.12,
  };
};

export const zoneStyle = (status) => {
  const s = status || "non_generee";
  return {
    color: ZONE_COLORS[s] || ZONE_COLORS.non_generee,
    weight: 1,
    opacity: s === "non_generee" ? 0.35 : 0.75,
    fillColor: ZONE_COLORS[s] || ZONE_COLORS.non_generee,
    fillOpacity: s === "ia" ? 0.16 : s === "ia_sans_source" ? 0.1 : s === "erreur" ? 0.1 : 0.04,
    dashArray: s === "ia_sans_source" ? "4 4" : null,
  };
};

export const flagEmoji = (iso2) => {
  if (!iso2 || iso2.length !== 2) return "🌐";
  const cc = iso2.toUpperCase();
  return String.fromCodePoint(0x1f1e6 + cc.charCodeAt(0) - 65, 0x1f1e6 + cc.charCodeAt(1) - 65);
};

/** HTML escape for any content injected into Leaflet popups. */
export const escH = (s) => String(s ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// Neutral route styling that reads on both dark and light basemaps.
// Two-layer stroke (dark casing + light main) gives contrast in every context.
export const ROUTE_MAIN_COLOR = "#e2e8f0";     // slate-200 top line
export const ROUTE_CASING_COLOR = "#0f172a";   // deep navy casing for contrast on light map
export const ROUTE_MAIN_WEIGHT = 2.5;
export const ROUTE_CASING_WEIGHT = 5;
/** Accompli (wake) vs reste à parcourir. */
export const WAKE_DONE_COLOR = "#7dd3fc";
export const WAKE_REST_COLOR = "#1d4ed8";
export const ESCALE_FILL = "#f8fafc";
export const ESCALE_STROKE = "#0f172a";
export const INTERMEDIATE_FILL = "#94a3b8";
export const INTERMEDIATE_STROKE = "#475569";
