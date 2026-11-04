import { memo } from "react";
import { Clapperboard, LoaderCircle, Maximize2, Minimize2, Pause, Play } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { filmBarEdgeStyle, readViewportWidth } from "../utils/filmBarLayout.js";
import { VIEW_SUIVRE, VIEW_TRACER } from "../constants/viewMode.js";
import { SAINT_MAUR_LAND_HOURS } from "../engine/voyageClock.js";
import { isLandLegNames } from "../utils/berryLegs.js";
import { displayStopName, filmClockWithoutRoadNm, roadTransferLabel } from "../utils/stopLabels.js";
import { ListenButton } from "./ListenButton.jsx";
import { LlmSourceBadge } from "./LlmSourceBadge.jsx";
import FilmReceipt from "./FilmReceipt.jsx";
import { DepartureField } from "./DepartureField.jsx";
import { clockRegimeText, clockWeatherTooltip, nextFilmSpeed, PROFILES } from "./filmBarClock.js";
import { isKeyboardClick, scrubKeyTarget } from "./filmScrub.js";
import { filmDurationClass, filmDurationPill } from "../engine/playSpeeds.js";
import { filmSourceKey, filmSubtitleHighlight, filmSubtitleShowsAir, formatFilmEstimateClock, pickFilmEstimateSeconds, visibleFilmSubtitle, writtenPillEnabled } from "../hooks/useReplay.js";
import { normalizeFilmWebSourceUrl } from "../utils/filmWebSources.js";

function filmPill(replay, sec) {
  return filmDurationPill({ seconds: sec, active: replay?.active, estimates: replay?.variantEstimates });
}

function filmEstimateLabel(replay, t) {
  const clock = formatFilmEstimateClock(pickFilmEstimateSeconds(
    replay?.targetSeconds,
    replay?.variantEstimates,
    replay?.estimatedSeconds,
  ));
  return clock ? t("filmDurationEstimate", { time: clock }) : "";
}

function clockSpeedBasis(clock, clockCurrent, barNm) {
  const direct = clockCurrent?.basis;
  if (direct === "polar" || direct === "fallback") return direct;
  const verts = clock?.vertices;
  if (!verts?.length) return null;
  const x = Number(clockCurrent?.filmNm ?? barNm);
  if (!Number.isFinite(x)) return null;
  let best = null;
  let bestD = Infinity;
  for (const v of verts) {
    if (v?.basis !== "polar" && v?.basis !== "fallback") continue;
    const d = Math.abs(Number(v.filmNm) - x);
    if (d < bestD) {
      bestD = d;
      best = v.basis;
    }
  }
  return best;
}

export const SimulationFilmBar = memo(function SimulationFilmBar({
  fromName,
  toName,
  finished,
  nm,
  totalNm,
  playhead,
  playheadTotal,
  remainingNm,
  etaHours,
  boatKnots,
  profile,
  onProfile,
  playing,
  onTogglePlay,
  marks,
  onSeekNm,
  onPrev,
  canPrev,
  onNext,
  canNext,
  showPlaybackControls = true,
  cinema,
  onCinema,
  hideBar = false,
  replay = null,
  drawing = null,
  onHideBar,
  liveSpeed,
  windKind,
  phase,
  vehicle,
  windSeries,
  windLoading,
  holding,
  clockLine = "",
  atQuay = false,
  quayDays = 0,
  twa = null,
  liveStatus = null,
  weatherLine = "",
  showSpeeds = false,
  showWindProfile = false,
  stopAuto = false,
  onStopAuto,
  showStopAuto = false,
  sidebarOpen = true,
  toolsOpen = true,
  filmFullscreen = false,
  onFilmFullscreen,
  gribLine = "",
  clock = null,
  clockCurrent = null,
  disclaimer = "",
  eventMarks = [],
  onEventClick,
  storiesPending = 0,
  speechText = null,
  view = null,
  onView,
  ref,
  barRef,
}) {
  const rootRef = ref || barRef;
  const { t, lang } = useLang();
  const edge = filmBarEdgeStyle({
    sidebarOpen,
    toolsOpen,
    viewportWidth: readViewportWidth(),
  });
  const regimeTitle = [
    t("regimeTooltipHindcast"),
    t("regimeTooltipForecast"),
    t("regimeTooltipClimatology"),
  ].join(" · ");
  const regimeLabel = clockRegimeText({
    regime: clockCurrent?.regime || clockCurrent?.kind,
    sources: clockCurrent?.sources,
    spread: clockCurrent?.spread,
    realUntil: clock?.realUntil,
    weatherLine,
    t,
    lang,
  });
  const weatherTip = clockWeatherTooltip({
    sources: clockCurrent?.sources,
    spread: clockCurrent?.spread,
    weatherLine,
    regimeTitle,
    t,
    lang,
  });
  const speed = PROFILES.find((p) => p.id === profile) || PROFILES[0];
  const barTotal = playheadTotal ?? totalNm;
  const barNm = playhead ?? nm;
  const speedBasis = clockSpeedBasis(clock, clockCurrent, barNm);
  const pct = barTotal > 0 ? Math.min(100, (barNm / barTotal) * 100) : 0;
  const landLeg = isLandLegNames(fromName, toName) || phase === "land" || vehicle === "land";
  const landNm = Number(remainingNm) > 0.5
    ? Number(remainingNm)
    : (Number(nm) > 0.5 ? Number(nm) : null);
  const landClock = landLeg
    ? formatLandLegClock(landNm, SAINT_MAUR_LAND_HOURS, t, lang, fromName, toName)
    : "";
  const phaseLabel = phase === "air-out" || phase === "air"
    ? t("filmPhaseAir")
    : phase === "air-return"
      ? t("filmPhaseAirReturn")
      : phase === "side-sail"
        ? t("filmPhaseSide")
        : "";
  const onBarClick = (e) => {
    if (!showPlaybackControls) return;
    if (isKeyboardClick(e)) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const t0 = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    onSeekNm(t0 * barTotal);
  };
  const onBarKeyDown = (e) => {
    if (!showPlaybackControls) return;
    const target = scrubKeyTarget(e.key, e.shiftKey, barNm, barTotal);
    if (target == null) return;
    e.preventDefault();
    onSeekNm(target);
  };
  const nmLocale = lang === "en" ? "en-US" : "fr-FR";
  const scrubValueText = t("filmScrubValue", {
    at: Math.round(barNm || 0).toLocaleString(nmLocale),
    total: Math.round(barTotal || 0).toLocaleString(nmLocale),
  });
  const filmSubtitle = visibleFilmSubtitle(replay?.subtitle || "", {
    fromName: replay?.fromName || fromName,
    toName: replay?.toName || toName,
  });
  const filmSubtitleAir = filmSubtitleShowsAir(filmSubtitle);
  const filmSubtitleParts = filmSubtitleHighlight(filmSubtitle, replay?.subtitlePlace || "");

  if (hideBar) {
    return (
      <div
        ref={rootRef}
        className="absolute bottom-5 z-[2020] pointer-events-auto"
        style={edge}
      >
        <button
          type="button"
          data-testid="show-film-bar"
          onClick={() => onHideBar?.(false)}
          aria-label={t("showFilmBar")}
          className="mx-auto block px-2 py-1 rounded-md text-[10px] font-semibold bg-slate-950/80 border border-white/15 text-white/80"
        >
          {t("showFilmBar")}
        </button>
      </div>
    );
  }

  // Le dessin est le défaut de Tracer : la barre garde Suivre | Tracer,
  // Play et le départ (plus de barre allégée qui les retirait).
  return (
    <div
      ref={rootRef}
      data-testid="film-bar"
      data-tour="film"
      data-drawing={drawing ? "1" : undefined}
      className="absolute bottom-5 z-[2020] pointer-events-auto"
      style={edge}
    >
        <div className={`naviguide-film-bar relative overflow-visible rounded-xl border ${drawing ? "border-emerald-400/30" : "border-white/15"} bg-slate-950/92 shadow-2xl px-2.5 pt-1 pb-1 text-white backdrop-blur-sm`}>
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 font-semibold leading-tight text-[12px] truncate">
            {drawing ? (
              <>
                <span className="text-emerald-200">{t("drawingInProgress")}</span>
                <span className="text-white/60 font-normal ml-2">{drawing.message}</span>
              </>
            ) : finished
              ? t("filmArrived", { name: displayStopName(fromName, lang, t) || "—" })
              : (
                <span data-testid="film-leg" data-from={fromName || ""} data-to={toName || ""}>
                  {landClock ? (
                    <span
                      data-testid="film-land-leg"
                      title={landClock}
                      className="block truncate font-normal text-[13px] leading-tight text-cyan-100"
                    >
                      {landClock}
                    </span>
                  ) : (
                    <>
                      <span className="text-blue-200">{displayStopName(fromName, lang, t) || "—"}</span>
                      <span className="text-white/35 mx-1">→</span>
                      <span className="text-cyan-200">{displayStopName(toName, lang, t) || "—"}</span>
                    </>
                  )}
                </span>
              )}
            {!landClock && phaseLabel ? (
              <span className="text-[10px] font-normal text-cyan-300/80 ml-2">{phaseLabel}</span>
            ) : null}
          </div>
          {disclaimer ? (
            <span data-testid="nav-disclaimer" className="text-[9px] text-amber-100/80 leading-tight max-w-[9rem] text-right flex-shrink-0">
              {disclaimer}
            </span>
          ) : null}
        </div>

        <div data-testid="film-clock-line" className="text-[11px] text-white/75 tabular-nums leading-tight mt-0.5 truncate">
          <span data-testid="clock-line">
            {landClock
              ? filmClockWithoutRoadNm(clockLine)
              : (clockLine || `${Math.round(nm).toLocaleString(lang === "en" ? "en-US" : "fr-FR")} nm`)}
            {!landClock && remainingNm > 0.5 && !finished && vehicle !== "plane"
              ? ` · ${t("nmRemaining")} ${Math.round(remainingNm).toLocaleString(lang === "en" ? "en-US" : "fr-FR")} nm`
              : ""}
            {!landClock && etaHours != null && etaHours > 0 && !finished && vehicle !== "plane" ? ` · ${t("eta")} ${formatEta(etaHours, lang)}` : ""}
            {vehicle === "plane"
              ? ` · ${t("filmAirVehicle")}`
              : (
                <>
                  {" · "}
                  <span
                    data-testid="regime-legend"
                    title={regimeTitle}
                    aria-label={regimeTitle}
                    className="inline-flex items-center rounded-md px-1 border border-white/15 bg-white/10"
                  >
                    <span data-testid="speed-regime-pill" title={regimeTitle}>
                      {atQuay
                        ? (quayDays > 0 ? t("voyageAtQuay", { days: quayDays }) : t("filmAtQuay"))
                        : `${Number(boatKnots || 0).toFixed(1)} kt${speedBasis === "fallback" ? ` ${t("speedFallback")}` : ""}`}
                    </span>
                  </span>
                </>
              )}
            {twa != null && vehicle !== "plane" ? ` · ${t("voyageTwa", { deg: Math.round(twa) })}` : ""}
            {liveStatus ? ` · ${liveStatus}` : ""}
            {atQuay && quayDays > 0 ? "" : (holding ? ` · ${t("filmArrivalHold")}` : "")}
          </span>
          {regimeLabel ? (
            <span data-testid="clock-regime" title={weatherTip || regimeTitle}>
              {" · "}
              {regimeLabel}
            </span>
          ) : null}
          {weatherLine ? <span data-testid="weather-line" className="text-cyan-200/85"></span> : null}
        </div>
        {gribLine ? (
          <div data-testid="grib-warning" className="text-[10px] text-amber-200/90 leading-tight">
            {gribLine}
          </div>
        ) : null}

        <div className="relative w-full h-2 rounded-full bg-white/10 mt-1">
          <button
            type="button"
            data-testid="film-scrub"
            role="slider"
            aria-label={t("filmScrub")}
            aria-valuemin={0}
            aria-valuemax={Math.round(barTotal || 0)}
            aria-valuenow={Math.round(barNm || 0)}
            aria-valuetext={scrubValueText}
            aria-orientation="horizontal"
            onClick={onBarClick}
            onKeyDown={onBarKeyDown}
            disabled={!showPlaybackControls}
            aria-label={showPlaybackControls ? t("filmScrub") : undefined}
            className="absolute inset-0 w-full h-full rounded-full before:absolute before:-inset-y-2 before:inset-x-0 before:content-['']"
            title={showPlaybackControls ? t("filmScrub") : undefined}
          >
            <span className="absolute inset-y-0 left-0 rounded-full bg-cyan-400/80" style={{ width: `${pct}%` }} />
          </button>
          {(marks || []).map((m) => (
            <span
              key={`${m.name}-${m.nm}`}
              className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-white pointer-events-none"
              style={{ left: `${barTotal > 0 ? ((m.filmNm ?? m.nm) / barTotal) * 100 : 0}%` }}
              title={displayStopName(m.name, lang, t)}
            />
          ))}
          {(eventMarks || []).map((ev) => {
            const full = ev.judge === "now" || ev.story?.status === "ready";
            const left = barTotal > 0 ? ((ev.filmCum ?? 0) / barTotal) * 100 : 0;
            return (
              <button
                key={ev.id || ev.stableKey}
                type="button"
                data-testid={`event-pill-${ev.type}`}
                data-judge={ev.judge || ""}
                className={`absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border z-10 ${
                  full
                    ? "bg-cyan-300 border-cyan-50"
                    : "bg-transparent border-cyan-200"
                }`}
                style={{ left: `${left}%` }}
                aria-label={ev.phrase || ev.type}
                title={ev.phrase || ev.type}
                onClick={(e) => {
                  e.stopPropagation();
                  onEventClick?.(ev);
                }}
              />
            );
          })}
        </div>
        {(replay?.active || replay?.subtitle) ? (
          <div
            data-testid="film-subtitle"
            className={`text-[10px] text-sky-100/90 leading-tight mt-0.5 ${
              filmSubtitleAir ? "whitespace-normal" : "truncate"
            }`}
          >
            {filmSubtitleParts.place ? (
              <>
                {filmSubtitleParts.before}
                <strong data-testid="film-subtitle-place" className="text-cyan-200 font-semibold">
                  {filmSubtitleParts.place}
                </strong>
                {filmSubtitleParts.after}
              </>
            ) : filmSubtitle}
          </div>
        ) : null}
        {replay?.chapterProvenance?.model && replay?.chapterProvenance?.source ? (
          <LlmSourceBadge
            source={replay.chapterProvenance.source}
            label={`${filmSourceLabel(replay.chapterProvenance.source, "", t, replay.chapterProvenance.model)} · ${replay.chapterProvenance.model} · ${replay.chapterProvenance.tier}`}
            testId="film-chapter-served-model"
            textOnly
            className="mt-0.5 [&_span]:text-[9px] [&_span]:text-white/65"
          />
        ) : null}
        {storiesPending > 0 ? (
          <div data-testid="stories-pending" className="text-[10px] text-white/55 leading-tight mt-0.5">
            {t("storiesPending", { n: storiesPending })}
          </div>
        ) : null}

        <div className="flex items-start gap-1 mt-1 min-w-0">
          {onHideBar ? (
            <button
              type="button"
              data-testid="hide-film-bar"
              onClick={() => onHideBar(true)}
              className="h-6 px-1.5 rounded-md text-[9px] font-semibold border bg-white/5 border-white/10 hover:bg-white/10 whitespace-nowrap shrink-0"
            >
              {t("hideFilmBar")}
            </button>
          ) : null}
          <div data-testid="film-commands" className="flex flex-wrap items-start gap-1 min-w-0 flex-1">
          <div className="flex items-center gap-1 flex-wrap flex-1">
            {onCinema ? (
              <button
                type="button"
                onClick={onCinema}
                className={`flex items-center gap-1 h-6 px-1.5 rounded-md text-[9px] font-semibold border whitespace-nowrap ${
                  cinema ? "bg-cyan-700/70 border-cyan-400/50" : "bg-white/5 border-white/10 hover:bg-white/10"
                }`}
                title={t("cinemaTooltip")}
              >
                <Clapperboard size={11} />
                {t("cinema")}
              </button>
            ) : null}
            {onFilmFullscreen ? (
              <button
                type="button"
                data-testid="film-fullscreen"
                onClick={() => onFilmFullscreen(!filmFullscreen)}
                aria-pressed={filmFullscreen}
                aria-label={filmFullscreen ? t("filmFullscreenExit") : t("filmFullscreen")}
                className={`flex items-center justify-center w-6 h-6 rounded-md border ${
                  filmFullscreen
                    ? "bg-sky-700/70 border-sky-300/40"
                    : "bg-white/5 border-white/10 hover:bg-white/10"
                }`}
                title={t("filmFullscreenTitle")}
              >
                {filmFullscreen ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
              </button>
            ) : null}
            <ListenButton
              text={speechText}
              t={t}
              lang={lang}
              compact
              iconOnly
              testId="listen"
              showWhenEmpty
              listening={replay ? Boolean(replay.voice) : undefined}
              onListening={replay?.onVoice}
              deferSpeak={Boolean(replay?.active)}
              className="!rounded-md"
            />
            {replay && !replay.unavailable ? (
              <>
                {replay.remoteStatus && replay.remoteStatus !== "ready" ? (
                  <div
                    data-testid="film-load-status"
                    role={replay.writtenUnavailable ? undefined : "status"}
                    aria-live="polite"
                    className="flex min-w-0 max-w-full items-center gap-1 text-[10px] text-white/65"
                  >
                    {replay.remoteStatus === "pending" || replay.remoteStatus === "preparing" ? (
                      <LoaderCircle size={11} className="animate-spin shrink-0" aria-hidden="true" />
                    ) : null}
                    <span className="min-w-0 truncate">{t({ pending: "filmLoadPending", preparing: "filmLoadPreparing", empty: "filmLoadEmpty", absent: "filmLoadError", timeout: "filmLoadTimeout", stale: "filmLoadStale" }[replay.remoteStatus] || "filmLoadPending")}</span>
                    {["empty", "absent", "timeout", "stale"].includes(replay.remoteStatus) && replay.onRetryLoad ? (
                      <button type="button" data-testid="film-load-retry" className="underline" onClick={replay.onRetryLoad}>{t("filmLoadRetry")}</button>
                    ) : null}
                  </div>
                ) : null}
                {replay.writing ? (
                  <div
                    data-testid="film-source"
                    className="min-w-0 max-w-full whitespace-normal break-words text-xs leading-snug text-white/90"
                  >
                    <LlmSourceBadge
                      source={replay.source}
                      reviewedBy={replay.reviewedBy}
                      label={filmSourceLabel(replay.source, replay.reviewedBy, t, replay.model)}
                      textOnly
                      className="min-w-0 max-w-full whitespace-normal break-words [&_span]:text-xs [&_span]:text-white/90"
                    />
                    <p className="mt-0.5 text-white/80">
                      {replay.filmWriteError ? t("ed2WriteFailed") : t("ed2WritingNemotron")}
                    </p>
                  </div>
                ) : (
                  <LlmSourceBadge
                    source={replay.source}
                    reviewedBy={replay.reviewedBy}
                    label={filmSourceLabel(replay.source, replay.reviewedBy, t, replay.model)}
                    testId="film-source"
                    textOnly
                    hidden={(replay.style || "raw") !== "written" || !replay.hasWritten}
                    className="min-w-0 max-w-full whitespace-normal break-words [&_span]:text-xs [&_span]:text-white/90"
                  />
                )}
                {replay.webContext?.sources?.length
                && !replay.writing
                && (replay.style || "raw") === "written"
                && replay.hasWritten ? (
                  <div
                    data-testid="film-web-sources"
                    className="min-w-0 max-w-full whitespace-normal break-words text-[10px] leading-snug text-violet-200/90"
                  >
                    <span>{t("filmWebSourcesTitle", { port: replay.webContext.port })}</span>{" "}
                    {replay.webContext.sources.map((s, i) => (
                      <span key={normalizeFilmWebSourceUrl(s.url) || s.url}>
                        {i ? " · " : ""}
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={s.title}
                          className="underline underline-offset-2"
                        >
                          {s.domain}
                        </a>
                      </span>
                    ))}
                  </div>
                ) : null}
                {replay.receipt && !replay.writing && (replay.style || "raw") === "written" && replay.hasWritten ? (
                  <FilmReceipt
                    receipt={replay.receipt}
                    webSourceCount={replay.receipt.webSourceCount ?? (replay.webContext?.sources?.length || 0)}
                    t={t}
                    lang={lang}
                  />
                ) : null}
                <div data-testid="film-style" className="flex bg-white/5 border border-white/10 rounded-md p-0.5 gap-0.5 flex-shrink-0">
                  {[["raw", "filmStoryRaw"], ["written", "filmStoryWritten"]].map(([id, key]) => {
                    const locked = Boolean(replay.active) || (id === "written" && !writtenPillEnabled({ customFilm: replay.customFilm }));
                    const lockTitle = replay.active
                      ? t("filmStoryLockedPlaying")
                      : id === "written" && !writtenPillEnabled({ customFilm: replay.customFilm })
                        ? t("filmStoryWrittenCustomUnavailable")
                      : id === "written" && replay.writtenUnavailable
                        ? t("filmStoryWrittenUnavailable") : undefined;
                    return (
                    <button
                      key={id}
                      type="button"
                      data-testid={`film-style-${id}`}
                      aria-pressed={(replay.style || "raw") === id}
                      aria-disabled={locked}
                      disabled={id === "written" && !writtenPillEnabled({ customFilm: replay.customFilm })}
                      title={lockTitle}
                      onClick={() => {
                        if (locked) return;
                        replay.onStyle?.(id);
                      }}
                      className={`px-1 py-0.5 rounded text-[9px] font-semibold whitespace-nowrap ${locked ? "opacity-40 cursor-not-allowed" : ""} ${
                        (replay.style || "raw") === id
                          ? "bg-sky-700/70 text-sky-50 border border-sky-300/40"
                          : "text-white/70 hover:text-white border border-transparent"
                      }`}
                    >
                      {t(key)}
                    </button>
                    );
                  })}
                </div>
                {replay.writtenUnavailable ? (
                  <div className="basis-full flex items-center gap-2 text-[9px] leading-tight text-white/65">
                    <span role="status">{t("filmStoryWrittenUnavailable")}</span>
                    <button
                      type="button"
                      className="underline"
                      onClick={() => {
                        if (!replay.active) replay.onStyle?.("written");
                      }}
                    >
                      {t("filmStoryWrittenRetry")}
                    </button>
                  </div>
                ) : null}
              </>
            ) : null}
            {onView ? (
              <div
                role="radiogroup"
                aria-label={t("viewModeGroup")}
                data-testid="film-view-switch"
                className="flex bg-white/5 border border-white/10 rounded-md p-0.5 gap-0.5 flex-shrink-0"
              >
                {[[VIEW_SUIVRE, t("followExpeditionButton"), "view-suivre", "mode-follow", null], [VIEW_TRACER, t("tracerButton"), "view-tracer", "mode-tracer", t("tracerModeTooltip")]].map(([id, label, testId, alias, tip]) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={view === id}
                    data-testid={testId}
                    data-mode={alias}
                    title={tip || undefined}
                    onClick={() => onView(id)}
                    className={`px-1.5 py-0.5 rounded text-[9px] font-semibold whitespace-nowrap ${
                      view === id ? "bg-cyan-700/70 text-cyan-50 border border-cyan-400/50" : "text-white/70 hover:text-white border border-transparent"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : null}
            {replay && !replay.unavailable ? (
              <div className="flex items-center gap-1 flex-wrap min-w-0" data-testid="replay-controls">
                <div data-testid="replay-departure" className="w-max shrink-0">
                  <DepartureField
                    t0={replay.t0}
                    onT0={replay.onT0}
                    compact
                    testId="replay-departure-field"
                    disabled={Boolean(replay.active)}
                  />
                </div>
                <div className="flex flex-wrap items-center gap-1 min-w-0">
                  {replay.active ? (
                    <>
                      <button
                        type="button"
                        onClick={replay.onStop}
                        data-testid="replay-stop"
                        className="h-6 px-1.5 rounded-md text-[9px] font-semibold border bg-rose-700/70 border-rose-300/40 hover:bg-rose-600/70 whitespace-nowrap"
                        title={t("replayStopTitle")}
                      >
                        ■ {t("replayStop")}
                      </button>
                      <div className="w-16 h-1.5 rounded-full bg-white/10 overflow-hidden" title={t("replayProgress", { pct: Math.round((replay.progress || 0) * 100) })}>
                        <div className="h-full bg-sky-400" style={{ width: `${Math.round((replay.progress || 0) * 100)}%` }} />
                      </div>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={replay.onStart}
                      disabled={!replay.canStart}
                      aria-disabled={!replay.canStart}
                      data-testid="replay-start"
                      className="relative z-10 h-6 px-1.5 rounded-md text-[9px] font-semibold border bg-sky-700/60 border-sky-300/40 hover:bg-sky-600/70 whitespace-nowrap disabled:opacity-30 disabled:cursor-not-allowed disabled:pointer-events-none"
                      title={replay.canStart ? t("replayStartTitle") : t("replayPreparing")}
                    >
                      ↺ {t("replayStart")}
                    </button>
                  )}
                  {replay.canStart || replay.active ? (
                    <div
                      data-testid="film-duration"
                      {...(replay.active ? { "data-testid": undefined } : {})}
                      className="flex bg-white/5 border border-white/10 rounded-md p-0.5 gap-0.5"
                      title={t("filmDuration")}
                    >
                      {[[150, "filmDuration150"], [180, "filmDuration180"]].map(([sec, key]) => {
                        const pill = filmPill(replay, sec);
                        return (<button
                          key={sec}
                          type="button"
                          data-seconds={sec}
                          data-variant-absent={pill.grey ? "1" : "0"}
                          aria-pressed={Number(replay.targetSeconds) === sec}
                          aria-disabled={Boolean(replay.active)}
                          disabled={Boolean(replay.active)}
                          title={pill.grey ? t("fm1VariantAbsent") : t(key)}
                          onClick={() => { if (pill.grey) return; replay.onDuration?.(Number(replay.targetSeconds) === sec ? 0 : sec); }}
                          className={`px-1 py-0.5 rounded text-[9px] font-semibold whitespace-nowrap disabled:opacity-30 disabled:cursor-not-allowed ${filmDurationClass(Number(replay.targetSeconds) === sec, pill.grey)}`}
                        >
                          {t(key)}
                        </button>);
                      })}
                      {filmEstimateLabel(replay, t) ? (
                        <span
                          data-testid="film-duration-estimate"
                          className="px-1 py-0.5 text-[9px] font-semibold text-white/70 whitespace-nowrap"
                        >
                          {filmEstimateLabel(replay, t)}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : replay?.unavailable ? (
              <div className="flex items-center gap-1 flex-wrap min-w-0" data-testid="replay-controls">
                <button
                  type="button"
                  disabled
                  aria-disabled="true"
                  aria-label={`${t("replayStart")}: ${t("replayUnavailable")}`}
                  data-testid="replay-start"
                  className="h-6 px-1.5 rounded-md text-[9px] font-semibold border bg-sky-700/60 border-sky-300/40 whitespace-nowrap disabled:opacity-30 disabled:cursor-not-allowed disabled:pointer-events-none"
                  title={t("replayUnavailable")}
                >
                  ↺ {t("replayStart")}
                </button>
                <span role="status" className="min-w-0 text-[9px] leading-tight text-sky-100/90">
                  {t("replayUnavailable")}
                </span>
              </div>
            ) : null}
          </div>
          <div className="flex items-center gap-1 flex-nowrap shrink-0">
            {showPlaybackControls ? (
              <>
                <button
                  type="button"
                  onClick={onTogglePlay}
                  aria-label={playing ? t("pause") : t("play")}
                  className="w-7 h-6 rounded-md bg-cyan-600 hover:bg-cyan-500 flex items-center justify-center"
                  aria-label={playing ? t("pause") : t("play")}
                  title={playing ? t("pause") : t("play")}
                >
                  {playing ? <Pause size={12} /> : <Play size={12} className="ml-0.5" />}
                </button>
                <button
                  type="button"
                  data-testid="prev-stop"
                  onClick={onPrev}
                  disabled={!canPrev}
                  className="relative w-6 h-6 rounded-md bg-white/10 disabled:opacity-30 flex items-center justify-center text-[14px] font-semibold leading-none"
                  title={t("previousEscale")}
                  aria-label={t("previousEscale")}
                >
                  <span aria-hidden="true">‹</span>
                  <span className="absolute w-px h-px overflow-hidden">{t("previousEscale")}</span>
                </button>
                <button
                  type="button"
                  data-testid="next-stop"
                  onClick={onNext}
                  disabled={!canNext}
                  className="relative w-6 h-6 rounded-md bg-white/10 disabled:opacity-30 flex items-center justify-center text-[14px] font-semibold leading-none"
                  title={t("goToNextStop")}
                  aria-label={t("goToNextStop")}
                >
                  <span aria-hidden="true">›</span>
                  <span className="absolute w-px h-px overflow-hidden">{t("goToNextStop")}</span>
                </button>
              </>
            ) : null}
            {showStopAuto ? (
              <button
                type="button"
                data-testid="stop-auto"
                role="switch"
                aria-checked={stopAuto}
                onClick={() => onStopAuto?.(!stopAuto)}
                className={`h-6 px-1.5 rounded-md text-[9px] font-semibold border whitespace-nowrap ${
                  stopAuto
                    ? "bg-amber-600/80 border-amber-300/50"
                    : "bg-white/5 border-white/10 text-white/70"
                }`}
                title={stopAuto ? t("stopAutoOn") : t("stopAutoOff")}
              >
                {t("stopAuto")}
              </button>
            ) : null}
            {showSpeeds ? (
              <button
                type="button"
                data-testid="film-speed"
                onClick={() => onProfile(nextFilmSpeed(profile))}
                className="h-6 px-1.5 rounded-md text-[9px] font-semibold border whitespace-nowrap bg-white text-slate-900 border-white"
                title={t(`${speed.labelKey}Title`)}
              >
                {t(speed.labelKey)}
              </button>
            ) : null}
          </div>
          </div>
        </div>
      </div>
    </div>
  );
});

function filmSourceLabel(source, reviewedBy, t, model) {
  return t(filmSourceKey(source, reviewedBy, model));
}

/** Jambe terrestre (Saint-Maur → La Rochelle) : km par la route, pas de nm. */
export function formatLandLegClock(nm, hours, t, lang = "fr", fromName = "", toName = "") {
  return roadTransferLabel(nm, hours, t, lang, fromName, toName, t("byRoad"), t("unitRoadHours"), t("unitKm"));
}

function formatEta(hours, lang = "fr") {
  if (hours == null || Number.isNaN(hours)) return "—";
  if (hours < 1 / 60) return "0 min";
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (hours >= 48) return `${Math.round(hours / 24)} ${lang === "en" ? "d" : "j"}`;
  if (m === 0) return `${h} h`;
  return `${h} h ${String(m).padStart(2, "0")}`;
}
