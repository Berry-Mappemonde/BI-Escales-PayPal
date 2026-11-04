/**
 * EtapePanel — leg metrics (nm, ETA, heading).
 *
 * Purely geometric calculation from useLegContext.
 * No API call — data available instantly on drag.
 *
 * Props:
 *   legContext   — LegContext object from the useLegContext hook
 *   onAdvance    — callback to advance to the midpoint of the next segment
 *   canAdvance   — boolean, disables the button at the end of the route
 */

import { Navigation, Clock, Compass, Map as MapIcon } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { getCardinalDirection, numberLocale } from "../utils/getCardinalDirection.js";
import { destinationPortLabel, displayStopName } from "../utils/stopLabels.js";

// ── Formatting ────────────────────────────────────────────────────────────────

function formatEta(hours, lang = "fr") {
  if (hours == null || Number.isNaN(hours)) return "—";
  if (hours < 1 / 60) return "0 min";
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours >= 48) return `${Math.round(hours / 24)} ${lang === "en" ? "d" : "j"}`;
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (m === 0) return `${h} h`;
  return `${h} h ${String(m).padStart(2, "0")}`;
}

function formatNm(nm, lang = "fr") {
  if (nm == null) return "—";
  return `${nm.toLocaleString(numberLocale(lang))} nm`;
}

function formatBearing(deg, lang = "fr") {
  if (deg == null) return "—";
  return `${Math.round(deg)}° ${getCardinalDirection(deg, lang)}`;
}

// ── Main component ──────────────────────────────────────────────────────

export function EtapePanel({
  legContext,
  clockSample = null,
  kindLabel = "",
  atQuay = false,
  quayDays = 0,
  liveFollow = false,
  previewing = false,
  forecastStatus = null,
  onRecompute,
  canRecompute = false,
  showRecompute = false,
  recomputeBusy = false,
  onGoLive,
}) {
  const { t, lang } = useLang();

  if (!legContext) {
    return (
      <div className="bg-slate-800/60 rounded-lg p-2 border border-blue-700/30">
        <div className="text-[10px] text-slate-400 text-center">
          {t("tracerDragPrompt")}
        </div>
      </div>
    );
  }

  const {
    fromStop, toStop,
    nmCovered, nmRemainingToStop,
    etaHours, bearing, speedKnots,
    finished,
  } = legContext;

  const fromLabel = displayStopName(fromStop, lang, t);
  const toLabel = displayStopName(toStop, lang, t);

  return (
    <div className="bg-slate-800/70 rounded-lg border border-blue-600/30 overflow-hidden">

      <div className="flex items-center justify-between px-2 py-1 bg-blue-900/30 border-b border-blue-700/20">
        <div className="flex items-center gap-1 min-w-0 flex-wrap">
          <Navigation size={10} className="text-blue-400 flex-shrink-0" />
          <span className="text-[10px] font-semibold text-blue-300 leading-tight">
            {finished ? t("filmArrived", { name: fromLabel }) : fromLabel}
          </span>
          {!finished && (
            <>
              <span className="text-white/30 text-[10px]">→</span>
              <span className="text-[10px] font-semibold text-cyan-300 leading-tight">
                {toLabel}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px bg-slate-700/20">

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <MapIcon size={9} className="text-cyan-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("nmRemaining")}
            </span>
          </div>
          <span data-testid="nm-to-destination-port" className="text-xs font-bold text-white leading-tight">{destinationPortLabel(nmRemainingToStop, t, lang)}</span>
        </div>

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <Clock size={9} className="text-amber-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("eta")}
            </span>
          </div>
          <span className="text-xs font-bold text-white leading-tight">{formatEta(etaHours, lang)}</span>
          <span className="text-[8px] text-slate-500 leading-tight">
            {clockSample?.vehicle === "plane"
              ? t("filmAirVehicle")
              : clockSample?.speedKnots != null
                ? t("voyageLocalKnots", { knots: Number(clockSample.speedKnots).toFixed(1) })
                : speedKnots != null
                  ? t("voyageLocalKnots", { knots: speedKnots })
                  : "—"}
          </span>
        </div>

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <Navigation size={9} className="text-green-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("nmCovered")}
            </span>
          </div>
          <span className="text-xs font-bold text-white leading-tight">{formatNm(nmCovered, lang)}</span>
        </div>

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <Compass size={9} className="text-purple-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("bearing")}
            </span>
          </div>
          <span className="text-xs font-bold text-white leading-tight">{formatBearing(bearing, lang)}</span>
        </div>

      </div>

      {(kindLabel || clockSample?.twa != null || atQuay) && (
        <div className="px-2 py-1 text-[9px] text-sky-100/90 border-t border-white/5 space-y-0 leading-tight">
          <div className="flex flex-wrap gap-x-2 text-white/55">
            {kindLabel ? <span>{kindLabel}</span> : null}
            {clockSample?.twa != null && clockSample?.vehicle !== "plane" ? (
              <span>{t("voyageTwa", { deg: Math.round(clockSample.twa) })}</span>
            ) : null}
          </div>
          {atQuay && quayDays > 0 ? (
            <div className="text-amber-200 font-semibold uppercase tracking-wide">
              {t("voyageAtQuay", { days: quayDays })}
            </div>
          ) : null}
        </div>
      )}

      {liveFollow && (clockSample?.status === "waiting" || (previewing && onGoLive)) && (
        <div className="px-2 py-1 border-t border-white/5 flex items-center justify-between gap-2">
          {clockSample?.status === "waiting" && clockSample.countdownHours != null ? (
            <span className="text-[9px] text-amber-200/90">
              {t("departsIn", { hours: formatEta(clockSample.countdownHours, lang) })}
            </span>
          ) : null}
          {previewing && onGoLive ? (
            <button
              type="button"
              onClick={onGoLive}
              className="text-[9px] font-semibold text-cyan-200 hover:text-cyan-100"
              title="L"
            >
              {t("returnToLive")}
            </button>
          ) : null}
        </div>
      )}

      {forecastStatus === "pending" && (
        <div className="px-2 py-1 text-[9px] text-sky-200/80 bg-sky-950/40">{t("forecastPending")}</div>
      )}
      {forecastStatus === "unavailable" && (
        <div className="px-2 py-1 text-[9px] text-amber-200/80 bg-amber-950/30">{t("forecastUnavailable")}</div>
      )}

      {showRecompute && (
        <div className="px-1.5 pb-1.5">
          <button
            type="button"
            data-testid="ask-advice"
            disabled={!canRecompute || recomputeBusy || forecastStatus === "pending"}
            onClick={onRecompute}
            className="w-full rounded-md border border-cyan-500/40 bg-cyan-900/30 py-1 text-[10px] font-semibold text-cyan-100 hover:bg-cyan-800/40 disabled:opacity-40"
          >
            {recomputeBusy ? t("recomputeBusy") : t("recomputeButton")}
          </button>
        </div>
      )}

    </div>
  );
}
