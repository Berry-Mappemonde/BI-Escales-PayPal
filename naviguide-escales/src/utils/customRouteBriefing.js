import { featuresToSegments, legsDistanceNm, wrapLon } from "./geo.js";
import { waypointsFromCollection } from "./waypointsFromCollection.js";

/** Côte lisible pour un point tracé — pas le voyage Berry. */
export function coastNameNear(lat, lon, language = "fr") {
  const y = Number(lat);
  const x = Number(lon);
  if (!Number.isFinite(y) || !Number.isFinite(x)) return "";
  const fr = language !== "en";
  // Large de Nouadhibou / cap Blanc.
  if (y >= 15 && y <= 21.5 && x >= -20 && x <= -16) {
    return fr ? "Mauritanie" : "Mauritania";
  }
  return "";
}

function coastAlongTrack(points, language = "fr") {
  for (const p of points || []) {
    const name = coastNameNear(p.lat, p.lon, language);
    if (name) return name;
  }
  return "";
}

/**
 * Fallback briefing when the orchestrator is unreachable.
 * Describes only the displayed GeoJSON — never the Berry track.
 */
export function buildLocalCustomBriefing(geojson, language = "fr") {
  const wps = waypointsFromCollection(geojson);
  const legs = featuresToSegments(geojson);
  // One segment per leg (N points → N − 1), not one per polyline vertex.
  const segs = wps.length >= 2 ? wps.length - 1 : legs.length;
  const nm = legsDistanceNm(legs);
  if (wps.length < 2 && segs < 1) return null;
  const coast = coastAlongTrack(wps, language);
  const dist = Math.round(nm);
  const pts = wps.length;
  const fr = language !== "en";
  const trail = wps
    .map((p) => {
      const lat = `${Math.abs(p.lat).toFixed(2)}°${p.lat >= 0 ? "N" : "S"}`;
      const shownLon = wrapLon(Number(p.lon));
      const lon = `${Math.abs(shownLon).toFixed(2)}°${shownLon >= 0 ? "E" : "W"}`;
      return `${p.name} (${lat}, ${lon})`;
    })
    .join(" → ");

  const summary = fr
    ? `Route personnalisée — ${pts || segs + 1} points, ${segs} segment${segs > 1 ? "s" : ""}, environ ${dist} NM.`
    : `Custom route — ${pts || segs + 1} points, ${segs} segment${segs > 1 ? "s" : ""}, about ${dist} NM.`;

  const whereFr = coast ? ` au large de la ${coast}` : " sur la carte";
  const whereEn = coast ? ` off ${coast}` : " on the map";
  const narrative = fr
    ? `Cette route a été tracée à la main${whereFr}. Elle ne suit pas le voyage par défaut de l'expédition. Distance estimée ${dist} milles nautiques sur ${segs} segment${segs > 1 ? "s" : ""}.${trail ? ` Waypoints : ${trail}.` : ""}`
    : `This route was drawn by hand${whereEn}. It is not the default expedition voyage. Estimated distance ${dist} nautical miles over ${segs} segment${segs > 1 ? "s" : ""}.${trail ? ` Waypoints: ${trail}.` : ""}`;

  return {
    executive_briefing: `${summary}\n\n${narrative}`,
    summary,
    narrative,
    legs: [],
    localFallback: true,
  };
}
