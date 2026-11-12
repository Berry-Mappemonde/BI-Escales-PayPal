/**
 * Where the boat is, in words a visitor can read: waiting before departure,
 * stopped at a stop, or under way between two stops.
 */
import { formatScheduleDate } from "./stopStatus.js";

/**
 * A boat this close to a stop along the route has reached it. The clock puts the
 * boat exactly on the stop's point at its arrival, so this only absorbs rounding;
 * anything larger would name a stop minutes before the schedule reaches it.
 */
export const AT_STOP_TOLERANCE_NM = 0.01;

const distanceOf = (point) => {
  const film = Number(point?.filmNm);
  if (Number.isFinite(film)) return film;
  const nm = Number(point?.nm);
  return Number.isFinite(nm) ? nm : null;
};

function moment(value) {
  const ms = value instanceof Date ? value.getTime() : Date.parse(String(value ?? ""));
  return Number.isNaN(ms) ? null : ms;
}

/**
 * `stops` are the voyage stops, each with its distance along the route (`filmNm`,
 * or `nm`); `sample` is the clock sample for "now". Once the schedule is loaded
 * the clock keeps its arrival and departure times (scheduleTimes.js), so this line
 * changes when the stop statuses do.
 */
/**
 * Each stop's distance along the route. The route's list ends with the return to
 * La Rochelle, which is given La Rochelle's departure point (same coordinates); a
 * stop listed after one further along is that return, so it lies at the route's end.
 */
function routeDistances(list) {
  let furthest = -Infinity;
  return list.map((stop) => {
    const at = distanceOf(stop);
    if (at < furthest) return { stop, at: Infinity };
    furthest = at;
    return { stop, at };
  });
}

export function boatPosition(stops, sample) {
  const list = (stops || []).filter((stop) => stop?.name && distanceOf(stop) !== null);
  if (!sample || !list.length) return null;
  const here = distanceOf(sample);
  if (here === null) return null;
  const last = list[list.length - 1];

  // The furthest stop already reached and the nearest one still ahead.
  let behind = null;
  let ahead = null;
  for (const entry of routeDistances(list)) {
    if (entry.at <= here + AT_STOP_TOLERANCE_NM) {
      if (!behind || entry.at > behind.at) behind = entry;
    } else if (!ahead || entry.at < ahead.at) {
      ahead = entry;
    }
  }

  if (sample.status === "waiting") return { kind: "waiting", stop: (behind?.stop ?? list[0]).name };
  if (sample.status === "arrived") return { kind: "stop", stop: last.name };
  if (!ahead) return { kind: "stop", stop: (behind?.stop ?? last).name };
  if (sample.atQuay && behind) return { kind: "stop", stop: behind.stop.name };
  if (!behind) return { kind: "waiting", stop: list[0].name };
  return { kind: "underway", from: behind.stop.name, to: ahead.stop.name };
}

/** The voyage's first scheduled departure, or "" without a schedule. */
export function scheduleDepartureIso(schedule) {
  const times = (schedule?.legs || []).map((leg) => moment(leg?.departure_iso)).filter((ms) => ms !== null);
  return times.length ? new Date(Math.min(...times)).toISOString() : "";
}

/** The departure day alone ("12 Nov 2026", "12 nov. 2026"), from the schedule when known. */
export function departureDate(schedule, fallbackIso, lang = "fr") {
  return formatScheduleDate(scheduleDepartureIso(schedule) || fallbackIso, lang);
}
