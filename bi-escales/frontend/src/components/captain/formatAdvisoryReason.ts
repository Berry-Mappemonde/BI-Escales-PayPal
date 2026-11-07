import type { TFunction } from "i18next";
import { formatScheduleDate } from "../../voyage/stopStatus.js";

/** Translate known model field summaries. Keep ordinary prose, hide raw leftovers. */
export function formatAdvisoryReason(reason: string | null | undefined, language: string, t: TFunction) {
  if (!reason?.trim()) return null;
  const lang = language.startsWith("en") ? "en" : "fr";
  let formattedField = false;
  const parts = reason.split(/[,;·]\s*/).map((part) => {
    const clause = part.trim().replace(/\.$/, "");
    const age = clause.match(/^authorization_age_days\s*(?:is|=|:)\s*(\d+)$/i);
    if (age) {
      formattedField = true;
      const count = Number(age[1]);
      return count === 0 ? t("captainCard.authorisedToday") : t("captainCard.authorisedDaysAgo", { count });
    }
    const schedule = clause.match(/^(?:schedule\s+)?(arrival|departure)(?:_iso)?\s*(?:is|=|:)\s*(\d{4}-\d{2}-\d{2}(?:T\S+)?)$/i);
    if (schedule) {
      const date = formatScheduleDate(schedule[2], lang);
      if (date) {
        formattedField = true;
        return t(schedule[1].toLowerCase() === "arrival" ? "captainCard.advisoryArrival" : "captainCard.advisoryDeparture", { date });
      }
    }
    return part.trim();
  });
  const note = formattedField ? parts.join(" · ") : reason.trim();
  // Unknown field names and dates must never leak into the donor-facing note.
  if (/\b\w+_\w+\b|\b\d{4}-\d{2}-\d{2}(?:T|\b)/.test(note)) return null;
  return note;
}
