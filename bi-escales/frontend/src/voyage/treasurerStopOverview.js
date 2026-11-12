/**
 * The treasurer's view of each stop (brief item B3): has the boat arrived, and how many
 * held pledges does the stop carry. Read-only: computed from what the treasurer page has
 * already loaded (the schedule, the API clock, the milestones and the pledge queue).
 *
 * The status rule is the stop sheet's own (`stopStatus`), so the calendar and the sheet
 * cannot disagree. A pledge counts as held while it is authorised or saved; on a stop the
 * boat has reached those pledges are due for capture. Cabin pledges belong to a leg, not
 * to a stop, and are not counted here.
 */
import { escaleArrivalIso } from "./journalDisplay.js";
import { isMilestoneCancelled, stopStatus, stopTimeline } from "./stopStatus.js";

const HELD = new Set(["authorized", "vaulted"]);

const cents = (value) => {
  const amount = Math.round(Number(String(value ?? "").replace(",", ".")) * 100);
  return Number.isFinite(amount) ? amount : 0;
};

/**
 * @returns {Record<string, { status: string | null, held: number, heldEur: number, due: boolean }>}
 *   by milestone id, for every stop of the schedule.
 */
export function treasurerStopOverview(schedule, now, milestones, pledges) {
  const held = new Map();
  for (const pledge of Array.isArray(pledges) ? pledges : []) {
    const id = String(pledge?.milestone_id || "").trim();
    if (!id || !HELD.has(String(pledge?.status || ""))) continue;
    const row = held.get(id) || { count: 0, cents: 0 };
    row.count += 1;
    row.cents += cents(pledge.amount_eur);
    held.set(id, row);
  }
  const out = {};
  for (const row of schedule?.export?.escales || schedule?.escales || []) {
    const id = String(row?.milestone_id || "").trim();
    if (!id) continue;
    const milestone = Array.isArray(milestones) ? milestones.find((item) => item?.id === id) : null;
    const status = stopStatus({
      now,
      arrivalIso: escaleArrivalIso(schedule, id),
      startIso: stopTimeline(schedule, { milestoneId: id, name: row.name }).startIso,
      cancelled: isMilestoneCancelled(milestone),
    });
    const mine = held.get(id) || { count: 0, cents: 0 };
    out[id] = { status, held: mine.count, heldEur: mine.cents / 100, due: status === "arrived" && mine.count > 0 };
  }
  return out;
}
