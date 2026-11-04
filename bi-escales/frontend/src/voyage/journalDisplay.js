/**
 * Affichage journal read-only — adapté de
 * naviguide-escales/src/components/iciMaintenant.js (formatJournalDate,
 * formatJournalPos, formatJournalLine) et bi-escales voyageClock.js (formatCivilDate).
 */
import { formatCivilDate } from "./voyageClock.js";

export function formatJournalPos(pos, lang = "fr") {
  const lat = Number(pos?.lat);
  const lon = Number(pos?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return "";
  const locale = lang === "en" ? "en-US" : "fr-FR";
  const fmt = (value) =>
    new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);
  return `${fmt(lat)} · ${fmt(lon)}`;
}

/** One server logbook row (label_fr / label_en from navigation_logbook.py). */
export function formatLogbookEntry(entry, lang = "fr") {
  if (!entry || typeof entry !== "object") return "";
  const label = lang === "en" ? entry.label_en : entry.label_fr;
  return [formatCivilDate(entry.t, lang), formatJournalPos(entry.pos, lang), label]
    .filter(Boolean)
    .join(" · ");
}

export function escaleArrivalIso(schedule, milestoneId) {
  const id = String(milestoneId || "").trim();
  if (!id || !schedule) return "";
  const rows = schedule.export?.escales || schedule.milestones || [];
  const hit = rows.find((row) => row?.milestone_id === id || row?._id === id);
  return String(hit?.arrival_iso || "");
}

export function logbookEntriesForStop(schedule, milestoneId) {
  const id = String(milestoneId || "").trim();
  if (!id || !schedule?.logbook) return [];
  const list = schedule.logbook[id];
  return Array.isArray(list) ? list : [];
}
