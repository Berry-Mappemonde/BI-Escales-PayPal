import { memo, useState } from "react";
import { useLang } from "../i18n/LangContext.jsx";
import {
  buildAdviceCompare,
  formatAdvicePills,
  formatEtaRange,
  formatEtaRangeTitle,
  isAdviceDone,
  localizeAdviceSentence,
} from "../hooks/usePlanReview.js";
import { adviceApplyDisabled } from "../engine/planReview.js";
import { REGIME_COLORS } from "../layers/regimeRoute.js";
import { LlmSourceBadge } from "./LlmSourceBadge.jsx";

const LEVEL_DOT = {
  ok: "bg-emerald-400",
  info: "bg-slate-400",
  watch: "bg-amber-400",
  alert: "bg-rose-400",
  muted: "bg-slate-600",
};

const BADGE = {
  ok: "border-emerald-500/40 text-emerald-200",
  info: "border-white/10 text-white/70",
  watch: "border-amber-400/50 text-amber-200",
  alert: "border-rose-400/60 text-rose-200",
  muted: "border-white/10 text-white/40",
};

/**
 * « Revue du plan »: one row per leg — dates, badges (sea days, rest,
 * EEZ / Gold, MPA, gale season, cyclones), notes. Collapsed by default under
 * the Expedition box; every figure comes from the server review or the atlas.
 */
function alertsTint(n) {
  if (!Number.isFinite(n) || n <= 0) return "border-emerald-500/40 text-emerald-200";
  if (n <= 2) return "border-amber-400/50 text-amber-200";
  return "border-rose-400/60 text-rose-200";
}

function AdviceCompare({ compare, todayLabel, advisedLabel }) {
  if (!compare) return null;
  return (
    <div className="grid grid-cols-2 gap-1.5 mt-1.5" data-testid="plan-advice-compare">
      {[["today", compare.today, todayLabel], ["advised", compare.advised, advisedLabel]].map(([id, col, label]) => (
        <div key={id} className={`rounded-md p-1.5 ${id === "advised" ? "bg-cyan-950/40 border border-cyan-500/30" : "bg-slate-900/60"}`} data-testid={`plan-advice-col-${id}`}>
          <div className="text-[9px] uppercase text-white/40">{label}</div>
          <div className="text-[10px] tabular-nums">{col.distance}</div>
          <div className="text-[10px] tabular-nums">{col.seaDays}</div>
          <div className="text-[10px] tabular-nums">{col.alerts}</div>
          {col.stops.map((line, i) => (
            <div key={i} className="text-[10px] text-white/80">{line}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

export const PlanReview = memo(function PlanReview({
  legs = [], loading = false, error = null, summary = null,
  comment = null, commentSource = null,
  advice = null, onApply,
  startOpen = false,
}) {
  const { t, lang } = useLang();
  const [applied, setApplied] = useState(false);
  const alerts = legs.reduce((n, l) => n + (Number.isFinite(Number(l.alertCount)) ? Number(l.alertCount) : (l.level === "alert" ? 1 : 0)), 0);
  const watches = legs.filter((l) => l.level === "watch").length;
  const best = isAdviceDone(advice) || advice?.source === "fixture" ? advice?.best : null;
  const sentence = best ? localizeAdviceSentence(best, t, lang) : "";
  const pills = best ? formatAdvicePills(best, t) : null;
  const advisedLeg = best
    ? legs[Number.isFinite(Number(advice?.leg)) ? Number(advice.leg) : 0] || legs[0]
    : null;
  const compare = applied && best ? buildAdviceCompare(best, advisedLeg, t, lang) : null;
  const applyOff = best ? adviceApplyDisabled(best) : true;
  const source = (best && (advice?.best?.sentenceSource || commentSource)) || commentSource || "rules";
  const body = (
      <div className={startOpen ? "" : "border-t border-white/5"}>
        {summary ? (
          <p className="px-2 pt-1 text-[9px] text-white/45 leading-snug">{summary}</p>
        ) : null}
        <div
          data-testid="plan-review-regime-legend"
          aria-label={t("regimeLegend")}
          className="flex items-center gap-2.5 px-2 pt-1 text-[9px] text-white/45 leading-tight"
        >
          {[["hindcast", "clockRegimeHindcast", "regimeTooltipHindcast"], ["forecast", "clockRegimeForecast", "regimeTooltipForecast"], ["climatology", "clockRegimeClimatology", "regimeTooltipClimatology"]].map(([id, key, tip]) => (
            <span key={id} className="inline-flex items-center gap-1" title={t(tip)} aria-label={t(key)}>
              <span
                className="inline-block w-2 h-2 rounded-[2px]"
                style={{ background: REGIME_COLORS[id] }}
                aria-hidden="true"
              />
            </span>
          ))}
        </div>
        <ul className="max-h-64 overflow-y-auto sidebar-scroll">
          {legs.map((leg) => {
            const etaLabel = formatEtaRange(leg.etaRange, t, lang);
            const etaTitle = formatEtaRangeTitle(leg.etaRange, t);
            return (
            <li key={leg.key} className="px-2 py-1.5 border-t border-white/5 first:border-t-0" data-level={leg.level} data-testid="plan-review-leg" data-days-at-sea={leg.daysAtSea ?? ""}>
              <div className="flex items-baseline gap-1.5 min-w-0">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${LEVEL_DOT[leg.level] || LEVEL_DOT.info}`} />
                <span className="text-[11px] font-medium text-white leading-tight truncate">{leg.title}</span>
                <span className={`ml-auto px-1 py-0.5 rounded border text-[9px] leading-tight shrink-0 tabular-nums ${alertsTint(Number(leg.alertCount))}`} data-testid="plan-review-leg-alerts">
                  {t("planReviewLegAlerts", { n: Number.isFinite(Number(leg.alertCount)) ? String(leg.alertCount) : "0" })}
                </span>
                <span className="text-[9px] text-white/40 shrink-0 tabular-nums" data-testid="plan-review-leg-dates">{leg.dates}</span>
              </div>
              {leg.antiShipping?.lanes?.length ? (
                <p
                  data-testid="plan-review-lanes"
                  className={`text-[9px] mt-0.5 pl-3 ${Number(leg.antiShipping.score) < 0.55 ? "text-amber-200" : "text-white/50"}`}
                >
                  {t("planReviewLanes", { names: leg.antiShipping.lanes.join(", ") })}
                </p>
              ) : null}
              {etaLabel ? (
                <p className="text-[9px] text-white/40 mt-0.5 pl-3" data-testid="plan-review-eta-range" title={etaTitle || undefined}>{etaLabel}</p>
              ) : null}
              <div className="flex flex-wrap gap-1 mt-1">
                {leg.badges.map((b, i) => (
                  <span key={`${b.kind}-${i}`} className={`px-1.5 py-0.5 rounded-md border text-[9px] leading-tight ${BADGE[b.level] || BADGE.info}`}>{b.text}</span>
                ))}
              </div>
              {leg.notes.map((n, i) => (
                <p key={i} className="text-[10px] text-amber-100/80 leading-snug mt-1 break-words [overflow-wrap:anywhere]">{n}</p>
              ))}
            </li>
            );
          })}
          {!legs.length && !loading ? <li className="px-2 py-1.5 text-[10px] text-white/50">{t("planReviewEmpty")}</li> : null}
        </ul>
        <div
          data-testid="plan-review-comment"
          data-source={source}
          className="px-2 py-1.5 border-t border-white/10"
        >
          <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-300">{t("planReviewCommentTitle")}</p>
          {sentence ? (
            <p className="text-[10px] text-white/80 leading-snug mt-1 break-words [overflow-wrap:anywhere]" data-testid="plan-advice-sentence">{sentence}</p>
          ) : (
            <p className="text-[10px] text-white/60 leading-snug mt-1" data-testid="plan-advice-none">{t("planReviewNoChange")}</p>
          )}
          {pills ? (
            <div className="flex flex-wrap gap-1 mt-1" data-testid="plan-advice-pills">
              <span className="px-1.5 py-0.5 rounded-md border border-rose-400/50 text-rose-100 text-[9px]">{pills.alerts}</span>
              <span className="px-1.5 py-0.5 rounded-md border border-white/15 text-white/80 text-[9px]">{pills.nm}</span>
              <span className="px-1.5 py-0.5 rounded-md border border-white/15 text-white/80 text-[9px]">{pills.days}</span>
            </div>
          ) : null}
          {best ? (
            <button
              type="button"
              data-testid="plan-advice-apply"
              disabled={applyOff}
              onClick={() => { if (applyOff) return; setApplied(true); onApply?.(); }}
              className="mt-1.5 w-full rounded-md bg-cyan-700/80 py-1 text-[10px] font-semibold text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-white/40"
            >
              {t("planReviewApply")}
            </button>
          ) : null}
          <AdviceCompare compare={compare} todayLabel={t("planCompareToday")} advisedLabel={t("planCompareAdvised")} />
          {/* Sans proposition, pas d'étiquette de source seule sous le titre (« règles » isolé, revue du 29/10). */}
          {best ? (
            <LlmSourceBadge source={source} testId="plan-review-source" className="mt-1 [&_span]:text-xs [&_span]:text-white" />
          ) : null}
        </div>
      </div>
  );
  const shell = "rounded-lg border border-white/10 bg-slate-800/50 overflow-hidden group";
  if (startOpen) {
    return <div className={shell} data-testid="plan-review">{body}</div>;
  }
  return (
    <details className={shell} data-testid="plan-review">
      <summary className="cursor-pointer select-none list-none px-2 py-1 flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-200">{t("planReviewTitle")}</span>
        <span className="ml-auto text-[9px] text-white/50">
          {loading ? t("planReviewLoading") : error ? t("planReviewError") : (
            alerts ? `${alerts} ${t("planReviewAlerts")}` : watches ? `${watches} ${t("planReviewWatch")}` : t("planReviewOk")
          )}
        </span>
        <span className="text-white/40 text-[10px] transition-transform group-open:rotate-90">›</span>
      </summary>
      {body}
    </details>
  );
});
