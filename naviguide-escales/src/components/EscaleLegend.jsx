import { memo, useMemo } from "react";
import { useLang } from "../i18n/LangContext.jsx";
import { formatStopoverDate } from "../engine/voyageClock.js";
import { displayStopName } from "../utils/stopLabels.js";
import { formatEtaRange, formatEtaRangeTitle, nextStopFromMarks, nextStopRowIndex, useOfficialEta } from "../hooks/usePlanReview.js";
import { regimeLegendHex } from "../utils/riskColors.js";

const REGIME_PILLS = [
  ["hindcast", "clockRegimeHindcast", "regimeTooltipHindcast"],
  ["forecast", "clockRegimeForecast", "regimeTooltipForecast"],
  ["climatology", "clockRegimeClimatology", "regimeTooltipClimatology"],
];

function markAt(m) {
  return Number(m.filmNm ?? m.nm) || 0;
}

/**
 * One escale row. Memoised: the HUD publishes `filmNm` up to 4×/s, and only the
 * `active` flag of two rows changes then — not the 18 formatted labels
 * (profile 18 sept. 2026: this list was 12 % of main-thread self time).
 */
function EscaleRowBody({ name, label, nmLabel, dateLabel, quayLabel, etaLabel, etaTitle }) {
  return (
    <>
      <span className="font-medium leading-tight block truncate">{label || name}</span>
      <span className="text-[9px] text-white/40">
        {nmLabel}
        {dateLabel}
        {quayLabel}
      </span>
      {etaLabel ? (
        <span className="text-[9px] text-white/40 block leading-tight" data-testid="eta-range" title={etaTitle || undefined}>{etaLabel}</span>
      ) : null}
    </>
  );
}

const EscaleRow = memo(function EscaleRow({ name, label, nmLabel, dateLabel, quayLabel, etaLabel, etaTitle, active }) {
  const idle = active ? "bg-cyan-700/40 text-white" : "text-white/70";
  return (
    <li
      data-testid="escale-legend-row"
      data-escale={name}
      data-interactive="false"
      className={`flex items-stretch border-t border-white/5 ${idle}`}
    >
      <div className="flex-1 min-w-0 text-left px-2 py-1 text-[11px] cursor-default">
        <EscaleRowBody
          name={name}
          label={label}
          nmLabel={nmLabel}
          dateLabel={dateLabel}
          quayLabel={quayLabel}
          etaLabel={etaLabel}
          etaTitle={etaTitle}
        />
      </div>
    </li>
  );
});

export const EscaleLegend = memo(function EscaleLegend({
  marks, filmNm, frozen = false, nowMs, liveFilmNm, officialEta = false,
}) {
  const { t, lang } = useLang();

  // Labels depend on marks + language only: built once per route / language.
  const rows = useMemo(() => (marks || [])
    .filter((m) => m?.name)
    .map((m) => {
      const at = markAt(m);
      return {
        key: `${m.name}-${at}`,
        name: m.name,
        label: displayStopName(m.name, lang, t),
        at,
        mark: m,
        nmLabel: `${Math.round(Number(m.nm) || 0).toLocaleString(lang === "en" ? "en-US" : "fr-FR")} nm`,
        dateLabel: m.iso ? ` · ${formatStopoverDate(m.iso, m.holdHours, lang)}` : "",
        quayLabel: m.holdHours > 0 ? ` · ${t("escalesQuay", { days: Math.round(m.holdHours / 24) })}` : "",
      };
    }), [marks, lang, t]);

  const x = Number(filmNm) || 0;
  let current = 0;
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].at <= x + 0.4) current = i;
  }
  const nextName = nextStopFromMarks(marks, nowMs, liveFilmNm);
  const nextIndex = nextStopRowIndex(rows, marks, nowMs, liveFilmNm);
  const eta = useOfficialEta(nextName, {
    enabled: Boolean(nextName),
    frozen,
    officialClock: officialEta,
  });
  const etaLabel = formatEtaRange(eta, t, lang);
  const etaTitle = formatEtaRangeTitle(eta, t);

  if (!rows.length) return null;

  return (
    <div className="rounded-lg border border-white/10 bg-slate-800/50 overflow-hidden" data-testid="escale-legend">
      <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-200">
        {t("escalesList")}
      </div>
      <div
        data-testid="escale-regime-legend"
        aria-label={t("regimeLegend")}
        className="flex items-center gap-2 px-2 pb-1 text-[9px] text-slate-400"
      >
        {REGIME_PILLS.map(([id, key, tip]) => (
          <span
            key={id}
            role="img"
            className="inline-flex items-center"
            title={`${t(key)} · ${t(tip)}`}
            aria-label={t(key)}
          >
            <span
              data-testid="escale-regime-pill"
              data-regime={id}
              className="inline-block w-2 h-2 rounded-[2px]"
              style={{ background: regimeLegendHex[id] }}
              aria-hidden="true"
            />
          </span>
        ))}
      </div>
      <ul className="max-h-36 overflow-y-auto sidebar-scroll">
        {rows.map((r, i) => (
          <EscaleRow
            key={r.key}
            name={r.name}
            label={r.label}
            nmLabel={r.nmLabel}
            dateLabel={r.dateLabel}
            quayLabel={r.quayLabel}
            etaLabel={etaLabel && i === nextIndex ? etaLabel : ""}
            etaTitle={etaLabel && i === nextIndex ? etaTitle : ""}
            active={i === current}
          />
        ))}
      </ul>
    </div>
  );
});
