/**
 * “Days at sea” clock: the playhead stays in film nm, the displayed
 * scale can switch to time at a boat speed (knots).
 * ~39 000 nm Berry at 7 kt ≈ 232 days.
 */

import { FALLBACK_EXPEDITION_KNOTS } from "./playSpeeds.js";

export function boatKnotsOrCruise(knots) {
  const n = Number(knots);
  return Number.isFinite(n) && n > 0 ? n : FALLBACK_EXPEDITION_KNOTS;
}

/** Hours at sea for a sailing distance (nm), excluding air hops. */
export function seaHours(sailNm, knots) {
  const nm = Number(sailNm);
  if (!Number.isFinite(nm) || nm <= 0) return 0;
  return nm / boatKnotsOrCruise(knots);
}

export function seaDays(sailNm, knots) {
  return seaHours(sailNm, knots) / 24;
}

/**
 * Compact label: “4 h”, “2 d 6 h”, “232 d”.
 * @param {number} hours
 */
export function formatSeaTime(hours, { compact = false } = {}) {
  const h = Number(hours);
  if (!Number.isFinite(h) || h <= 0) return compact ? "0 h" : "0 h";
  if (h < 24) {
    const rounded = h < 10 ? Math.round(h * 10) / 10 : Math.round(h);
    return `${rounded} h`;
  }
  let days = Math.floor(h / 24);
  let rem = Math.round(h - days * 24);
  if (rem >= 24) {
    days += 1;
    rem = 0;
  }
  if (compact && days >= 10) return `${days} j`;
  if (rem <= 0) return `${days} j`;
  return `${days} j ${rem} h`;
}

export function formatSeaClock(sailNm, knots, opts) {
  return formatSeaTime(seaHours(sailNm, knots), opts);
}

/**
 * Ancien barème nœuds constants — ne plus servir la barre film.
 * Les graduations HUD passent par `filmBarTicks` / `clockTickLabelsFromClock`.
 */
export function clockTickLabels({ playheadTotal, sailTotalNm, knots, scale = "both" } = {}) {
  const maxFilm = Number(playheadTotal) || 0;
  const sail = Math.max(0, Number(sailTotalNm) || 0);
  if (maxFilm <= 0) return [];
  const fractions = [0, 0.5, 1];
  if (scale === "both") {
    return fractions.map((frac) => {
      const nm = Math.round(sail * frac);
      const days = Math.round(seaHours(sail * frac, knots) / 24);
      return {
        filmNm: maxFilm * frac,
        label: `${nm.toLocaleString()} nm · j${days}`,
      };
    });
  }
  if (scale === "days") {
    const totalH = seaHours(sail, knots);
    return fractions.map((t) => {
      const hours = totalH * t;
      const days = Math.round(hours / 24);
      return {
        filmNm: maxFilm * t,
        label: hours < 24 && t > 0 ? formatSeaTime(hours, { compact: true }) : `J${days}`,
      };
    });
  }
  return fractions.map((t) => ({
    filmNm: maxFilm * t,
    label: t === 0
      ? "0"
      : t === 1
        ? `${Math.round(sail).toLocaleString()} nm`
        : `${Math.round(sail * t).toLocaleString()}`,
  }));
}
