/**
 * Short pause at a stopover during continuous Play (MovingMarker style).
 * Un seek / Next / Prev saute la pause (jump: true).
 */

export const DWELL_MS = Object.freeze({
  real: 2400,
  read: 2200,
  normal: 1800,
  fast: 1100,
});

export function dwellMsForProfile(profileId) {
  return DWELL_MS[profileId] ?? DWELL_MS.normal;
}

/** Jours à quai : même table que l'horloge (Cayenne 3, Halifax 1, Saint-Maur 0). */
export function portDwellDays(name) {
  const n = String(name || "");
  if (/saint[- ]?maur/i.test(n)) return 0;
  if (/halifax/i.test(n)) return 1;
  return 3;
}

/** Pause de lecture proportionnelle au séjour. 3 jours = la pause du profil. */
export function dwellMsForStation(station, profileId) {
  const base = dwellMsForProfile(profileId);
  const days = Number.isFinite(Number(station?.holdDays))
    ? Number(station.holdDays)
    : portDwellDays(station?.name);
  if (!(days > 0)) return 0;
  return Math.round(base * (days / 3));
}

/**
 * Next stopover strictly after filmNm (not the start at 0).
 * @returns {{ filmNm: number, name: string, kind: string } | null}
 */
export function nextStationAfter(filmNm, stations, { epsilon = 0.35 } = {}) {
  if (!Array.isArray(stations) || !stations.length) return null;
  const x = Number(filmNm) || 0;
  let best = null;
  for (const s of stations) {
    const f = Number(s.filmNm ?? s.nm);
    if (!Number.isFinite(f) || f <= epsilon) continue;
    if (f <= x + 1e-6) continue;
    if (!best || f < Number(best.filmNm ?? best.nm)) best = s;
  }
  return best;
}

/** Stop auto ON → pause franche à l’escale. OFF → on traverse. */
export function shouldPauseAtStop(stopAuto, arrived) {
  return Boolean(stopAuto && arrived);
}

export function stationAt(filmNm, stations, { epsilon = 0.45 } = {}) {
  if (!Array.isArray(stations)) return null;
  const x = Number(filmNm) || 0;
  return (
    stations.find((s) => {
      const f = Number(s.filmNm ?? s.nm);
      return Number.isFinite(f) && f > 0.35 && Math.abs(f - x) <= epsilon;
    }) ?? null
  );
}

/**
 * Advance one playback step. Pure — no Date.now.
 *
 * @returns {{
 *   filmNm: number,
 *   dwellMsLeft: number,
 *   holding: boolean,
 *   arrived: null | object,
 * }}
 */
export function stepPlayback({
  filmNm,
  dwellMsLeft = 0,
  deltaMs,
  rate,
  stations,
  maxFilmNm,
  dwellMs,
  jump = false,
}) {
  const max = Math.max(0, Number(maxFilmNm) || 0);
  let x = Math.max(0, Math.min(max, Number(filmNm) || 0));
  let left = Math.max(0, Number(dwellMsLeft) || 0);

  if (jump || !(Number(rate) > 0)) {
    return {
      filmNm: x,
      dwellMsLeft: 0,
      holding: false,
      arrived: null,
    };
  }

  let dt = Math.max(0, Number(deltaMs) || 0);
  let arrived = null;

  if (left > 0) {
    if (dt >= left) {
      dt -= left;
      left = 0;
    } else {
      left -= dt;
      return { filmNm: x, dwellMsLeft: left, holding: true, arrived: null };
    }
  }

  const next = nextStationAfter(x, stations);
  const nextAt = next ? Number(next.filmNm ?? next.nm) : max;
  const target = next ? Math.min(nextAt, max) : max;
  const step = (Number(rate) || 0) * (dt / 1000);
  const remaining = target - x;

  if (next && remaining > 0 && step >= remaining - 1e-9) {
    x = Math.min(max, nextAt);
    const days = Number.isFinite(Number(next.holdDays)) ? Number(next.holdDays) : portDwellDays(next.name);
    const pause = Math.round(Math.max(0, Number(dwellMs) || 0) * (days / 3));
    left = pause;
    arrived = next;
    return { filmNm: x, dwellMsLeft: left, holding: pause > 0, arrived };
  }

  x = Math.min(max, x + step);
  return { filmNm: x, dwellMsLeft: 0, holding: false, arrived: null };
}
