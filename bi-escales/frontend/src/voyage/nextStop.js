/**
 * Which stop "Back the next stop" opens: the first one, in route order, that the
 * boat has not reached and that is not cancelled. Same schedule fields and same
 * status rule as the stop sheet's chip (stopStatus), so the button and the chip
 * can never disagree.
 */
import { escaleArrivalIso } from "./journalDisplay.js";
import { isMilestoneCancelled, stopStatus, stopTimeline } from "./stopStatus.js";

const OPEN = new Set(["upcoming", "en_route"]);

export function nextOpenStop(stops, schedule, now, milestones) {
  const seen = new Set();
  for (const stop of stops || []) {
    const id = String(stop?.milestoneId || "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const milestone = Array.isArray(milestones) ? milestones.find((row) => row?.id === id) : null;
    const status = stopStatus({
      now,
      arrivalIso: escaleArrivalIso(schedule, id),
      startIso: stopTimeline(schedule, stop).startIso,
      cancelled: isMilestoneCancelled(milestone),
    });
    if (OPEN.has(status)) return stop;
  }
  return null;
}
