import { haversineNm, unwrapLon } from "../utils/geo.js";

/** Film units of an air hop (real duration = airHopSeconds, not sea nm). */
export const AIR_FILM_NM = 80;

/** Two hops form an episode if the second lands near the start of the first. */
export const AIR_HOP_RETURN_NM = 80;

function filmOf(p) {
  return p?.filmCum ?? p?.cumNm ?? 0;
}

function initialBearing(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const lon2u = unwrapLon(lon1, lon2);
  const φ1 = toRad(lat1);
  const φ2 = toRad(lat2);
  const Δλ = toRad(lon2u - lon1);
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function lerpLatLon(a, b, t) {
  const lat = a.lat + t * (b.lat - a.lat);
  const lon = a.lon + t * (b.lon - a.lon);
  return {
    lat,
    lon,
    bearing: initialBearing(a.lat, a.lon, b.lat, b.lon),
  };
}

function nearestName(stops, pos, fallback) {
  if (!pos || !stops?.length) return fallback;
  let best = fallback;
  let bestD = 80;
  for (const stop of stops) {
    if (!stop?.name || !Number.isFinite(stop.lat) || !Number.isFinite(stop.lon)) continue;
    const d = haversineNm(pos.lat, pos.lon, stop.lat, stop.lon);
    if (d < bestD) {
      bestD = d;
      best = stop.name;
    }
  }
  return best;
}

function farthestPoint(points, fromIdx, toIdx, origin) {
  let bestIdx = fromIdx;
  let bestD = -1;
  for (let i = fromIdx; i <= toIdx; i++) {
    const d = haversineNm(origin.lat, origin.lon, points[i].lat, points[i].lon);
    if (d > bestD) {
      bestD = d;
      bestIdx = i;
    }
  }
  return { point: points[bestIdx], index: bestIdx };
}

/**
 * Outbound / return air-hop pair (Cayenne → Halifax … Halifax → Cayenne).
 * Between them: decoupled sailing (Halifax ↔ Saint-Pierre).
 */
export function detectAirEpisodes(points) {
  const pts = points || [];
  const jumpIdx = [];
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].jump) jumpIdx.push(i);
  }
  const episodes = [];
  const used = new Set();
  for (let a = 0; a < jumpIdx.length; a++) {
    const ja = jumpIdx[a];
    if (used.has(ja) || ja < 1) continue;
    const origin = pts[ja - 1];
    for (let b = a + 1; b < jumpIdx.length; b++) {
      const jb = jumpIdx[b];
      if (used.has(jb)) continue;
      const dest = pts[jb];
      if (haversineNm(origin.lat, origin.lon, dest.lat, dest.lon) > AIR_HOP_RETURN_NM) continue;
      const hub = pts[ja];
      const viaFrom = Math.min(ja + 1, jb - 1);
      const viaTo = Math.max(ja, jb - 1);
      const viaHit = viaTo >= viaFrom ? farthestPoint(pts, viaFrom, viaTo, hub) : { point: hub, index: ja };
      const via = viaHit.point;
      const parkBearing = ja >= 2
        ? initialBearing(pts[ja - 2].lat, pts[ja - 2].lon, origin.lat, origin.lon)
        : initialBearing(origin.lat, origin.lon, hub.lat, hub.lon);
      episodes.push({
        ja,
        jb,
        viaIdx: viaHit.index,
        park: { lat: origin.lat, lon: origin.lon, bearing: parkBearing },
        hub: { lat: hub.lat, lon: hub.lon },
        via: { lat: via.lat, lon: via.lon },
        midSailNm: (hub.cumNm + pts[jb - 1].cumNm) / 2,
        endSailNm: pts[jb - 1].cumNm,
      });
      used.add(ja);
      used.add(jb);
      break;
    }
  }
  return episodes;
}

/** Snap SPM and re-insert Cayenne on the return, for the Cayenne → Papeete HUD. */
export function mergeEpisodeMarks(marks, flat, stops) {
  const episodes = nameAirEpisodes(flat?.episodes || detectAirEpisodes(flat?.points || []), stops);
  const out = [...(marks || [])];
  for (const ep of episodes) {
    const viaP = flat.points[ep.viaIdx];
    const retP = flat.points[ep.jb];
    if (viaP) {
      const existing = out.find((m) => m.name === ep.viaName);
      if (existing) {
        existing.nm = viaP.cumNm;
        existing.filmNm = viaP.filmCum ?? viaP.cumNm;
        existing.lat = viaP.lat;
        existing.lon = viaP.lon;
        existing.index = ep.viaIdx;
      } else {
        out.push({
          name: ep.viaName,
          lat: viaP.lat,
          lon: viaP.lon,
          nm: viaP.cumNm,
          filmNm: viaP.filmCum ?? viaP.cumNm,
          index: ep.viaIdx,
        });
      }
    }
    if (retP) {
      out.push({
        name: ep.parkName,
        lat: retP.lat,
        lon: retP.lon,
        nm: retP.cumNm,
        filmNm: retP.filmCum ?? retP.cumNm,
        index: ep.jb,
      });
    }
  }
  out.sort((a, b) => (a.filmNm ?? a.nm) - (b.filmNm ?? b.nm));
  return out;
}

export function nameAirEpisodes(episodes, stops) {
  return (episodes || []).map((ep) => ({
    ...ep,
    parkName: nearestName(stops, ep.park, "Cayenne (Guyane)"),
    hubName: nearestName(stops, ep.hub, "Halifax (Nouvelle-Écosse)"),
    viaName: nearestName(stops, ep.via, "Saint-Pierre (Saint-Pierre-et-Miquelon)"),
  }));
}

export function filmLength(flat) {
  if (!flat?.points?.length) return 0;
  return flat.totalFilmNm ?? filmOf(flat.points[flat.points.length - 1]);
}

export function edgeAtFilmNm(flat, filmNm) {
  const pts = flat?.points || [];
  if (pts.length < 2) return null;
  const raw = Number(filmNm);
  if (!Number.isFinite(raw)) return null;
  const target = Math.max(0, Math.min(filmLength(flat), raw));
  let i = 0;
  while (i < pts.length - 2 && filmOf(pts[i + 1]) <= target) i += 1;
  const a = pts[i];
  const b = pts[i + 1];
  return {
    i,
    jump: Boolean(b.jump),
    filmSpan: filmOf(b) - filmOf(a),
    a,
    b,
  };
}

export function filmNmToSailNm(flat, filmNm) {
  const edge = edgeAtFilmNm(flat, filmNm);
  if (!edge) return 0;
  if (edge.jump || edge.filmSpan <= 0) return edge.a.cumNm;
  const target = Math.max(0, Math.min(filmLength(flat), Number(filmNm) || 0));
  const t = (target - filmOf(edge.a)) / edge.filmSpan;
  return edge.a.cumNm + t * (edge.b.cumNm - edge.a.cumNm);
}

export function sailNmToFilmNm(flat, sailNm) {
  const pts = flat?.points || [];
  if (pts.length < 2) return 0;
  const target = Math.max(0, Math.min(flat.totalNm || 0, Number(sailNm) || 0));
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (b.jump) continue;
    if (target >= a.cumNm - 1e-9 && target <= b.cumNm + 1e-9) {
      const span = b.cumNm - a.cumNm;
      const t = span > 0 ? (target - a.cumNm) / span : 0;
      return filmOf(a) + t * (filmOf(b) - filmOf(a));
    }
  }
  return filmOf(pts[pts.length - 1]);
}

function episodeForEdge(episodes, bIndex, jump) {
  for (const ep of episodes) {
    if (jump && bIndex === ep.ja) return { ep, phase: "air-out" };
    if (jump && bIndex === ep.jb) return { ep, phase: "air-return" };
    if (!jump && bIndex > ep.ja && bIndex < ep.jb) return { ep, phase: "side-sail" };
  }
  return null;
}

function hiddenActor() {
  return { visible: false, lat: null, lon: null, bearing: 0 };
}

function actorFrom(pos, bearing) {
  return {
    visible: true,
    lat: pos.lat,
    lon: pos.lon,
    bearing: bearing ?? pos.bearing ?? 0,
  };
}

/** Position interpolée le long du trait (jamais le sommet le plus proche). */
export function positionAlongTrait(flat, filmNm) {
  const edge = edgeAtFilmNm(flat, filmNm);
  if (!edge) return null;
  const { a, b, filmSpan } = edge;
  const raw = Number(filmNm);
  const target = Math.max(0, Math.min(filmLength(flat), raw));
  const t = filmSpan > 0 ? (target - filmOf(a)) / filmSpan : 1;
  return lerpLatLon(a, b, t);
}

/**
 * Trois acteurs : bateau Berry (main), avion (plane), bateau relais (side).
 * During the Guiana episode, the main boat stays alongside in Cayenne.
 */
export function interpolateCast(flat, filmNm, { stops } = {}) {
  const pts = flat?.points || [];
  const raw = Number(filmNm);
  const target = Number.isFinite(raw) ? Math.max(0, Math.min(filmLength(flat), raw)) : 0;
  if (!pts.length) return null;
  const episodes = nameAirEpisodes(flat.episodes || detectAirEpisodes(pts), stops);
  const hidden = hiddenActor();

  if (pts.length === 1) {
    const main = actorFrom(pts[0], 0);
    return {
      phase: "sail",
      vehicle: "main",
      sailNm: 0,
      filmNm: 0,
      main,
      plane: hidden,
      side: hidden,
      follow: main,
      fromName: null,
      toName: null,
      hopFrom: null,
      hopTo: null,
    };
  }

  const edge = edgeAtFilmNm(flat, target);
  const { a, b, i, jump, filmSpan } = edge;
  const t = filmSpan > 0 ? (target - filmOf(a)) / filmSpan : 1;
  const pos = lerpLatLon(a, b, t);
  const matched = episodeForEdge(episodes, i + 1, jump);

  if (jump && matched) {
    const plane = actorFrom(pos);
    const main = actorFrom(matched.ep.park, matched.ep.park.bearing);
    const outbound = matched.phase === "air-out";
    return {
      phase: matched.phase,
      vehicle: "plane",
      sailNm: a.cumNm,
      filmNm: target,
      main,
      plane,
      side: hidden,
      follow: plane,
      fromName: outbound ? matched.ep.parkName : matched.ep.hubName,
      toName: outbound ? matched.ep.hubName : matched.ep.parkName,
      hopFrom: outbound ? matched.ep.park : matched.ep.hub,
      hopTo: outbound ? matched.ep.hub : matched.ep.park,
    };
  }

  if (jump) {
    const plane = actorFrom(pos);
    const main = actorFrom(a, initialBearing(a.lat, a.lon, b.lat, b.lon));
    return {
      phase: "air",
      vehicle: "plane",
      sailNm: a.cumNm,
      filmNm: target,
      main,
      plane,
      side: hidden,
      follow: plane,
      fromName: nearestName(stops, a, null),
      toName: nearestName(stops, b, null),
      hopFrom: { lat: a.lat, lon: a.lon },
      hopTo: { lat: b.lat, lon: b.lon },
    };
  }

  if (matched?.phase === "side-sail") {
    const side = actorFrom(pos);
    const main = actorFrom(matched.ep.park, matched.ep.park.bearing);
    const sailNm = a.cumNm + t * (b.cumNm - a.cumNm);
    const outbound = sailNm <= matched.ep.midSailNm;
    return {
      phase: "side-sail",
      vehicle: "side",
      sailNm,
      filmNm: target,
      main,
      plane: hidden,
      side,
      follow: side,
      fromName: outbound ? matched.ep.hubName : matched.ep.viaName,
      toName: outbound ? matched.ep.viaName : matched.ep.hubName,
      hopFrom: null,
      hopTo: null,
    };
  }

  const main = actorFrom(pos);
  return {
    phase: "sail",
    vehicle: "main",
    sailNm: a.cumNm + t * (b.cumNm - a.cumNm),
    filmNm: target,
    main,
    plane: hidden,
    side: hidden,
    follow: main,
    fromName: null,
    toName: null,
    hopFrom: null,
    hopTo: null,
  };
}

export function isAirPhase(phase) {
  return phase === "air-out" || phase === "air-return" || phase === "air";
}
