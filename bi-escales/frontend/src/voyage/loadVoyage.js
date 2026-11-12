/**
 * Route officielle, milles cumulés et horloge.
 * Dérivé de featuresToSegments (utils/geo.js), flattenRoute (engine/routePlayhead.js),
 * buildVoyageClock / sampleClockAtTime (engine/voyageClock.js)
 * et getFlagsForWaypoint (constants/waypoints.js).
 */
import { featuresToSegments, haversineNm } from "../../../../naviguide-escales/src/utils/geo.js";
import { dropRepeatedStops } from "../../../../naviguide-escales/src/utils/escales.js";
import { flattenRoute } from "../../../../naviguide-escales/src/engine/routePlayhead.js";
import {
  buildVoyageClock,
  sampleClockAtTime,
} from "./voyageClock.js";
import { getFlagsForWaypoint } from "../../../../naviguide-escales/src/constants/waypoints.js";
import { milestoneIdFromName } from "./milestoneId.js";
import { alignClockToSchedule } from "./scheduleTimes.js";

export function segmentsFromRoute(fc) {
  const lines = (fc?.features || []).filter(
    (feature) => feature?.geometry?.type === "LineString" && feature.geometry.coordinates?.length >= 2,
  );
  return featuresToSegments({ type: "FeatureCollection", features: lines }).map((segment, index) => {
    const props = lines[index]?.properties || {};
    return {
      ...segment,
      nonMaritime: props.type === "overland",
      from: { name: props.from || segment.from?.name || "" },
      to: { name: props.to || segment.to?.name || "" },
    };
  });
}

export function stopsFromRoute(fc, flat) {
  const points = flat?.points || [];
  const mapped = (fc?.features || [])
    .filter((feature) => feature?.geometry?.type === "Point" && feature.properties?.point_type === "escale")
    .map((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      let best = points[0];
      let bestD = Infinity;
      for (const point of points) {
        const distance = haversineNm(lat, lon, point.lat, point.lon);
        if (distance < bestD) {
          bestD = distance;
          best = point;
        }
      }
      const name = feature.properties.name;
      return {
        name,
        lat,
        lon,
        nm: best?.cumNm ?? 0,
        filmNm: best?.filmCum ?? best?.cumNm ?? 0,
        flag: true,
        flags: getFlagsForWaypoint(name),
        milestoneId: milestoneIdFromName(name),
      };
    });
  return dropRepeatedStops(mapped);
}

/**
 * With the API schedule, the clock keeps the schedule's arrival and departure
 * times (scheduleTimes.js), so the boat on the map agrees with the stop statuses.
 *
 * @param {any} fc
 * @param {string} t0
 * @param {any} [schedule]
 */
export function voyageFromRoute(fc, t0, schedule = null) {
  const segments = segmentsFromRoute(fc);
  const flat = flattenRoute(segments);
  const stops = stopsFromRoute(fc, flat);
  const built = buildVoyageClock({ flat, marks: stops, stops, t0 });
  const clock = schedule ? alignClockToSchedule(built, stops, schedule) : built;
  return { segments, flat, stops, clock };
}

export function sampleAt(clock, when) {
  return sampleClockAtTime(clock, when);
}

export async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.json();
}
