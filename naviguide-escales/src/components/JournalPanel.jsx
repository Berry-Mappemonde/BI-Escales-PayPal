import { memo, useMemo } from "react";
import { useLang } from "../i18n/LangContext.jsx";
import { groupJournalByDay } from "../engine/journalFormat.js";

function DayBlock({ group }) {
  return (
    <div data-testid="journal-day">
      <div className="text-[10px] font-semibold text-blue-200 mt-1">{group.label}</div>
      <ul className="mt-0.5 space-y-0.5">
        {group.entries.map((e) => (
          <li key={e.id || `${group.day}-${e.time}-${e.kind}`} className="flex gap-1.5 text-[11px] text-slate-300 leading-snug" data-kind={e.kind}>
            <span className="flex-shrink-0 w-4 text-center">{e.icon}</span>
            <span className="flex-shrink-0 text-slate-500 tabular-nums">{e.time}</span>
            <span className="min-w-0 break-words [overflow-wrap:anywhere]">{e.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Journal de bord du voyage officiel (Suivre) — la mémoire du produit,
 * écrite par le serveur : positions 00/06/12/18 UTC, escales franchies,
 * GRIB au bateau, mots du skipper. Lecture seule, rien d'inventé.
 *
 * Revue du 19 sept. : compact — le jour courant seulement ; les jours
 * précédents restent lisibles, repliés, en faisant défiler.
 */
export const JournalPanel = memo(function JournalPanel({ journal, loading = false, error = null }) {
  const { t, lang } = useLang();
  const groups = useMemo(() => groupJournalByDay(journal?.latest || [], lang, { maxDays: 14 }), [journal, lang]);
  const count = journal?.count ?? 0;
  const [today, ...earlier] = groups;

  return (
    <details className="bg-slate-800/50 rounded-lg border border-slate-700/50 group" data-testid="journal-panel" open={false}>
      <summary className="cursor-pointer select-none px-2 py-1.5 flex items-center gap-2 text-[11px] font-semibold text-slate-200">
        <span>📓</span>
        <span>{t("journalTitle")}</span>
        <span className="ml-auto text-[10px] font-normal text-slate-400">
          {loading && !journal ? "…" : (today ? today.label : t("journalCount", { n: count }))}
        </span>
      </summary>
      <div className="px-2 pb-2 space-y-1.5">
        {error && !journal ? (
          <p className="text-[10px] text-amber-300/90">{t("journalUnavailable")}</p>
        ) : null}
        {journal && groups.length === 0 ? (
          <p className="text-[11px] text-slate-400">{t("journalEmpty")}</p>
        ) : null}
        {today ? <DayBlock group={today} /> : null}
        {earlier.length ? (
          <details className="mt-1" data-testid="journal-earlier">
            <summary className="cursor-pointer select-none text-[10px] text-slate-400 hover:text-slate-200">
              {t("journalEarlier", { n: earlier.length })}
            </summary>
            <div className="max-h-48 overflow-y-auto sidebar-scroll pr-1">
              {earlier.map((g) => <DayBlock key={g.day} group={g} />)}
            </div>
          </details>
        ) : null}
        <p className="text-[9px] text-slate-500 leading-snug">{t("journalHint")}</p>
      </div>
    </details>
  );
});
