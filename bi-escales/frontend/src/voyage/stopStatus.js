/**
 * What the stop panel may say, derived only from API fields. Anything missing
 * returns null or an empty list, so the panel omits it rather than guessing.
 */
import { formatJournalPos } from "./journalDisplay.js";

function moment(iso) {
  const ms = Date.parse(String(iso ?? ""));
  return Number.isNaN(ms) ? null : ms;
}

function legMatches(leg, side, milestoneId, name) {
  const id = String(leg?.[`${side}_milestone_id`] || "").trim();
  if (id && milestoneId) return id === milestoneId;
  return Boolean(name) && String(leg?.[`${side}_name`] || "").trim() === name;
}

/**
 * The schedule fields for one stop. `startIso` is when the boat is due to leave
 * for this stop: the inbound leg's departure or, for a stop with no inbound
 * leg, the previous stop's scheduled arrival. `departureIso` is only ever a
 * leg's own departure, never calculated.
 */
export function stopTimeline(schedule, stop) {
  const milestoneId = String(stop?.milestoneId || "").trim();
  const name = String(stop?.name || "").trim();
  const legs = schedule?.legs || [];
  const inbound = legs.find((leg) => legMatches(leg, "to", milestoneId, name));
  const outbound = legs.find((leg) => legMatches(leg, "from", milestoneId, name));

  const rows = (schedule?.export?.escales || schedule?.milestones || [])
    .filter((row) => moment(row?.arrival_iso) !== null)
    .sort((a, b) => moment(a.arrival_iso) - moment(b.arrival_iso));
  const index = rows.findIndex((row) => row?.milestone_id === milestoneId || row?._id === milestoneId);
  const previous = index > 0 ? rows[index - 1] : null;

  return {
    startIso: inbound?.departure_iso || previous?.arrival_iso || "",
    departureIso: outbound?.departure_iso || "",
  };
}

/** Same rule as ``_cancelled`` in departure_clock.py. */
export function isMilestoneCancelled(milestone) {
  const evidence = Array.isArray(milestone?.evidence) ? milestone.evidence : [];
  const facts = evidence[evidence.length - 1]?.facts;
  if (facts && typeof facts === "object" && (facts.cancelled === true || facts.departed === false)) {
    return true;
  }
  return milestone?.meta?.cancelled === true;
}

/** "arrived" means the scheduled time has passed, not that arrival is confirmed. */
export function stopStatus({ now, arrivalIso, startIso, cancelled }) {
  const nowMs = moment(now);
  const arrival = moment(arrivalIso);
  if (nowMs === null) return null;
  if (cancelled) return "cancelled";
  if (arrival === null) return null;
  if (nowMs >= arrival) return "arrived";
  const start = moment(startIso);
  return start !== null && nowMs >= start ? "en_route" : "upcoming";
}

/** The logbook is computed ahead of time, so only what the clock has reached may show. */
export function logbookUpTo(entries, now) {
  const nowMs = moment(now);
  if (nowMs === null) return [];
  return (entries || []).filter((entry) => {
    const at = moment(entry?.t);
    return at !== null && at <= nowMs;
  });
}

function positiveEur(value) {
  const amount = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(amount) && amount > 0 ? amount : null;
}

/** Non-zero totals only. A missing, redacted or zero field gives null. */
export function fundTotals(fund) {
  return { heldEur: positiveEur(fund?.authorized_eur), capturedEur: positiveEur(fund?.captured_eur) };
}

const LOCALES = { fr: "fr-FR", en: "en-GB" };

export function formatScheduleDate(iso, lang = "fr") {
  const ms = moment(iso);
  if (ms === null) return "";
  return new Intl.DateTimeFormat(LOCALES[lang] || LOCALES.fr, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(ms));
}

export function formatEurAmount(amount, lang = "fr") {
  return new Intl.NumberFormat(LOCALES[lang] || LOCALES.fr, {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function logbookLine(entry, lang = "fr") {
  const label = lang === "en" ? entry?.label_en : entry?.label_fr;
  return [formatScheduleDate(entry?.t, lang), formatJournalPos(entry?.pos, lang), label].filter(Boolean).join(" · ");
}
