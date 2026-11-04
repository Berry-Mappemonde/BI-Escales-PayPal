import { useLang } from "../i18n/LangContext.jsx";
import { filmSpeedProfileState } from "../engine/playSpeeds.js";

const VB_W = 200;
const VB_H = 32;
const PAD_Y = 4;

function polyline(samples, key, maxY, maxX) {
  const pts = [];
  for (const s of samples) {
    const v = s[key];
    if (v == null || !Number.isFinite(Number(v))) continue;
    const x = maxX > 0 ? (s.filmNm / maxX) * VB_W : 0;
    const y = VB_H - PAD_Y - (Number(v) / maxY) * (VB_H - PAD_Y * 2);
    pts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return pts.join(" ");
}

export function FilmSpeedProfile({
  series,
  filmNm,
  playheadTotal,
  onSeek,
  loading = false,
  durationSeconds = 0,
  estimates = null,
}) {
  const { t } = useLang();
  const speed = filmSpeedProfileState({ durationSeconds, estimates });
  const speedTitle = t(speed.grey ? speed.titleKey : "filmSpeedProfile");
  const rows = series || [];
  const maxX = Number(playheadTotal) > 0 ? Number(playheadTotal) : 1;
  const maxVal = rows.reduce((m, s) => {
    const a = Number(s.tws);
    const b = Number(s.boatKnots);
    return Math.max(m, Number.isFinite(a) ? a : 0, Number.isFinite(b) ? b : 0);
  }, 0);
  const maxY = Math.max(12, Math.ceil(maxVal / 5) * 5);
  const windPts = polyline(rows, "tws", maxY, maxX);
  const boatPts = polyline(rows, "boatKnots", maxY, maxX);
  const playX = Math.max(0, Math.min(VB_W, (Number(filmNm) || 0) / maxX * VB_W));

  const onClick = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const t0 = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    onSeek?.(t0 * (Number(playheadTotal) || 0));
  };

  return (
    <div
      className={`mb-1.5 ${loading || speed.grey ? "opacity-60" : ""}`}
      data-variant-absent={speed.grey ? "1" : "0"}
      title={speedTitle}
    >
      <div className="flex items-center justify-between mb-0.5 px-0.5">
        <span className="text-[9px] text-white/40">{t("filmSpeedProfile")}</span>
        <span className="text-[9px] text-white/40">
          <span className="text-amber-300/90">{t("filmWindLegend")}</span>
          <span className="mx-1 text-white/25">·</span>
          <span className="text-cyan-300/90">{t("filmKnotsLegend")}</span>
        </span>
      </div>
      <button
        type="button"
        onClick={onClick}
        className={`relative w-full h-8 rounded-md bg-white/5 border border-white/10 block overflow-hidden ${speed.grey ? "opacity-30 cursor-not-allowed" : ""}`}
        aria-label={t("filmSpeedProfile")}
        title={speedTitle}
      >
        <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="absolute inset-0 w-full h-full" preserveAspectRatio="none">
          {windPts ? (
            <polyline
              points={windPts}
              fill="none"
              stroke="rgb(251 191 36)"
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
          {boatPts ? (
            <polyline
              points={boatPts}
              fill="none"
              stroke="rgb(34 211 238)"
              strokeWidth="2.2"
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
          <line
            x1={playX}
            x2={playX}
            y1="0"
            y2={VB_H}
            stroke="white"
            strokeOpacity="0.75"
            strokeWidth="1.2"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </button>
    </div>
  );
}
