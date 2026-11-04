import { zoneWindAt } from "../utils/climatologyWind.js";
const COLOR = "#2dd4bf";

export function escHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function roseSvg(p) {
  const ml = Number(p.wind_direction_from_deg) || 0;
  const kn = Number(p.wind_speed_knots) || 0;
  const calm = Number(p.calm_pct) || 0;
  const gale = Number(p.gale_pct) || 0;
  const centre = gale >= 8 ? "#ef4444" : calm >= 20 ? "#38bdf8" : COLOR;
  const petals = (p.directions_from || []).map((d) => {
    const rad = ((Number(d.dir_deg) || 0) * Math.PI) / 180;
    const len = Math.max(4, Math.min(14, (Number(d.pct) || 0) * 0.28));
    const x2 = 16 + Math.sin(rad) * len;
    const y2 = 16 - Math.cos(rad) * len;
    return `<line x1="16" y1="16" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${COLOR}" stroke-width="1.4" stroke-opacity="0.85" />`;
  });
  if (!petals.length) {
    const len = Math.max(6, Math.min(18, kn));
    const rad = (ml * Math.PI) / 180;
    const x2 = 16 + Math.sin(rad) * len;
    const y2 = 16 - Math.cos(rad) * len;
    petals.push(`<line x1="16" y1="16" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${COLOR}" stroke-width="1.6" />`);
  }
  return `<svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
    ${petals.join("")}
    <circle cx="16" cy="16" r="3.2" fill="${centre}" />
  </svg>`;
}

export function waveColor(hs, stat) {
  if (stat === "p90") {
    if (hs >= 4) return "#7f1d1d";
    if (hs >= 2.5) return "#b45309";
    return "#0f766e";
  }
  if (hs >= 3) return "#155e75";
  if (hs >= 1.5) return "#0d9488";
  return "#5eead4";
}

export function currentArrowHtml(directionToDeg) {
  const to = Number(directionToDeg) || 0;
  return `<div style="width:18px;height:18px;transform:rotate(${to}deg);color:${COLOR};font-size:14px;line-height:18px;text-align:center;">↑</div>`;
}

const CAPTION_STYLE = "font-family:system-ui,sans-serif;font-size:13px;line-height:1.35;color:#e2e8f0;margin:4px 0;";

function knownMonth(month) {
  const n = Number(month);
  if (!Number.isFinite(n)) return null;
  const rounded = Math.round(n);
  if (rounded < 1 || rounded > 12) return null;
  return rounded;
}

/** Lisible (≥ 12 px) : moyenne mensuelle, jamais « kind: » ni une prévision. */
export function climoCaptionText(month, t) {
  const n = knownMonth(month);
  if (typeof t !== "function") return n ? String(n) : "";
  if (!n) {
    return t("fv2ClimoCaption", { month: "" })
      .replace(/\s*\(\s*\)/g, "")
      .replace(/\s{2,}/g, " ")
      .trim();
  }
  return t("fv2ClimoCaption", { month: t(`fv2Month${n}`) });
}

function climoCaptionHtml(month, t) {
  return `<div data-testid="climatology-caption" style="${CAPTION_STYLE}">${escHtml(climoCaptionText(month, t))}</div>`;
}

export function layerPopupHtml(kind, p, t) {
  const rows = [];
  if (kind === "wind") {
    if (p.stat === "average" || !p.directions_from?.length) {
      rows.push(`${escHtml(t("climoAverage"))}: ${escHtml(p.vector_mean_knots ?? p.wind_speed_knots)} kn / ${escHtml(p.vector_mean_from_deg ?? p.wind_direction_from_deg)}°`);
    } else {
      rows.push(`${escHtml(t("climoMostLikely"))}: ${escHtml(p.wind_speed_knots)} kn / ${escHtml(p.wind_direction_from_deg)}°`);
      rows.push(`${escHtml(t("climoAverage"))}: ${escHtml(p.vector_mean_knots)} kn / ${escHtml(p.vector_mean_from_deg)}°`);
      rows.push(`calm ${escHtml(p.calm_pct)}% · gale ${escHtml(p.gale_pct)}% · n=${escHtml(p.sample_count)}`);
    }
  } else if (kind === "wave") {
    rows.push(`Hs ${escHtml(p.stat)}: ${escHtml(p.hs_m)} m`);
    if (p.period_s != null) rows.push(`T ${escHtml(p.period_s)} s`);
    if (p.dir_deg != null) rows.push(`dir ${escHtml(p.dir_deg)}°`);
    if (p.stat === "p50") rows.push(escHtml(t("climoWaveP50Hint")));
    if (p.stat === "p90") rows.push(escHtml(t("climoWaveP90Hint")));
  } else if (kind === "current") {
    rows.push(`${escHtml(p.speed_knots)} kn → ${escHtml(p.direction_to_deg)}°`);
    if (p.below_threshold) rows.push("below_threshold");
  } else if (kind === "cyclones") {
    rows.push(`${escHtml(p.name || p.sid)} · ${escHtml(p.season)} · ${escHtml(p.basin)}`);
    rows.push(`max ${escHtml(p.max_wind_kn)} kn · ${escHtml(p.wind_source || "")}`);
  }
  return `<div style="min-width:200px;max-width:280px;" data-testid="climatology-popup">
    <div style="font-weight:700;color:#fff;font-size:12px;">${escHtml(t("modeClimatologyFull"))}</div>
    ${climoCaptionHtml(p.month, t)}
    ${rows.map((r) => `<div style="font-size:11px;color:#e2e8f0;margin-top:3px;">${r}</div>`).join("")}
    <div style="font-size:10px;color:#94a3b8;margin-top:8px;">${escHtml(t("climoDisclaimer"))}</div>
  </div>`;
}

/**
 * Popup d'un clic sur la carte. `where` ({ lat, lon, month }) sert au repli :
 * si l'atlas ne donne aucune valeur (coupé, hors ligne), le vent de zone est
 * affiché et signalé comme tel, au lieu d'une case vide.
 */
export function pointPopupHtml(data, t, where = null) {
  const w = data?.wind_atlas?.most_likely || data?.wind_atlas?.vector_mean;
  const wave = data?.wave;
  const cur = data?.current;
  const bits = [];
  if (w) bits.push(`vent ${escHtml(w.speed_knots)} kn / ${escHtml(w.dir_deg)}°`);
  if (wave?.hs_p50_m != null) bits.push(`Hs P50 ${escHtml(wave.hs_p50_m)} m`);
  if (wave?.hs_p90_m != null) bits.push(`Hs P90 ${escHtml(wave.hs_p90_m)} m`);
  if (cur && !cur.below_threshold) bits.push(`courant ${escHtml(cur.speed_knots)} kn`);
  let fallbackNote = "";
  if (!bits.length && where && Number.isFinite(Number(where.lat)) && Number.isFinite(Number(where.lon))) {
    const zone = zoneWindAt(Number(where.lat), Number(where.lon), data?.month ?? where.month);
    bits.push(`vent ${escHtml(Math.round(zone.speedKnots))} kn / ${escHtml(Math.round(zone.dirFromDeg))}°`);
    fallbackNote = `<div style="font-size:10px;color:#fcd34d;margin-top:3px;" data-testid="climatology-zone-fallback">${escHtml(t("climatologyAtlasDown"))}</div>`;
  }
  return `<div data-testid="climatology-map-popup" style="min-width:210px;">
    <div style="font-weight:700;color:#fff;font-size:13px;">${escHtml(t("modeClimatologyFull"))}</div>
    ${climoCaptionHtml(data?.month, t)}
    <div style="font-size:11px;color:#e2e8f0;">${bits.join(" · ") || escHtml(data?.coordinates?.cell_selection)}</div>
    ${fallbackNote}
    <div style="font-size:10px;color:#fde68a;margin-top:8px;">${escHtml(t("climoDisclaimer"))}</div>
  </div>`;
}

export const CLIMO_COLOR = COLOR;
