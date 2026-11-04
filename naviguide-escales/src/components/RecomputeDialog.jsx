import { RouteAdviceText } from "../hooks/useVirtualVessel.js";
import { useLang } from "../i18n/LangContext.jsx";

function hoursLabel(h) {
  if (h == null || Number.isNaN(h)) return "—";
  if (h >= 48) return `${Math.round(h / 24)} j`;
  return `${Math.round(h * 10) / 10} h`;
}

export function RecomputeDialog({ draft, busy, onAccept, onReject }) {
  const { t, lang } = useLang();
  if (!draft) return null;
  const vs = draft.versus_searoute || {};
  const best = draft.planAdvice?.best;
  const cascade = Array.isArray(best?.cascade) ? best.cascade : [];
  const todayLabel = best ? t("planCompareToday") : t("recomputeSearoute");
  const advisedLabel = best ? t("planCompareAdvised") : t("recomputeProposed");
  const day = (iso) => {
    const a = new Date(iso);
    if (Number.isNaN(a.getTime())) return String(iso || "").slice(0, 10);
    return a.toLocaleDateString(lang === "en" ? "en-GB" : "fr-FR", { day: "numeric", month: "short", timeZone: "UTC" });
  };
  return (
    <div className="fixed inset-0 z-[2400] flex items-center justify-center bg-slate-950/70 px-4">
      <div className="w-full max-w-md rounded-2xl border border-white/15 bg-slate-900 p-4 text-white shadow-2xl" data-testid="route-compare">
        <div className="text-sm font-semibold mb-1">{t("recomputeTitle")}</div>
        <p className="text-[11px] text-white/60 mb-3">
          {t("recomputeTo", { name: draft.to_name || "—" })} · {draft.status}
        </p>
        <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
          <div className="rounded-lg bg-slate-800/80 p-2" data-testid="route-compare-today">
            <div className="text-white/40 uppercase text-[9px]">{todayLabel}</div>
            <div>{vs.distance_nm ?? "—"} nm</div>
            <div>{hoursLabel(vs.hours)}</div>
            {best && Number.isFinite(Number(best.alertsBefore)) ? (
              <div>{t("planCompareAlerts", { n: String(best.alertsBefore) })}</div>
            ) : null}
            {cascade.map((row, i) => (
              <div key={`was-${i}`}>{t("planCompareStop", { stop: row.stop || "—", date: day(row.was) })}</div>
            ))}
          </div>
          <div className="rounded-lg bg-cyan-950/50 p-2 border border-cyan-500/30" data-testid="route-compare-advised">
            <div className="text-cyan-300/70 uppercase text-[9px]">{advisedLabel}</div>
            <div>{draft.distance_nm ?? "—"} nm</div>
            <div>{hoursLabel(draft.hours)}</div>
            {best && Number.isFinite(Number(best.alertsAfter)) ? (
              <div>{t("planCompareAlerts", { n: String(best.alertsAfter) })}</div>
            ) : null}
            {cascade.map((row, i) => (
              <div key={`now-${i}`}>{t("planCompareStop", { stop: row.stop || "—", date: day(row.now) })}</div>
            ))}
          </div>
        </div>
        {draft.constraints ? (
          <p data-testid="recompute-constraints" className="text-[10px] text-amber-200/80 mb-2">
            {draft.constraints.source === "skipper"
              ? t("recomputeConstraintsSkipper", {
                wind: draft.constraints.windMaxKt != null ? `${Math.round(draft.constraints.windMaxKt)} kn` : "—",
                hs: draft.constraints.hsMaxM != null ? `${draft.constraints.hsMaxM} m` : "—",
              })
              : t("recomputeConstraintsDefault", { hs: draft.constraints.hsMaxM != null ? `${draft.constraints.hsMaxM} m` : "—" })}
          </p>
        ) : null}
        <RouteAdviceText draft={draft} />
        <p className="text-[10px] text-white/45 mb-3">{t("recomputeHint")}</p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onReject}
            disabled={busy}
            className="flex-1 rounded-lg border border-white/15 py-1.5 text-[11px] font-semibold hover:bg-white/5"
          >
            {t("recomputeKeep")}
          </button>
          <button
            type="button"
            onClick={onAccept}
            disabled={busy || draft.status === "failed"}
            className="flex-1 rounded-lg bg-cyan-600 py-1.5 text-[11px] font-semibold hover:bg-cyan-500 disabled:opacity-40"
          >
            {t("recomputeAccept")}
          </button>
        </div>
      </div>
    </div>
  );
}
