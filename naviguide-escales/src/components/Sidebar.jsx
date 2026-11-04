import { memo, useEffect, useRef, useState } from "react";
import { CheckCircle, ChevronLeft, ChevronRight, Pencil, Trash2 } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { EtapePanel } from "./EtapePanel";
import { JournalPanel } from "./JournalPanel.jsx";
import { IciMaintenant } from "./IciMaintenant.jsx";
import { LogbookChat } from "./LogbookChat.jsx";
import { VIEW_SUIVRE, VIEW_TRACER } from "../constants/viewMode.js";
import { canFocus, entityLinks } from "../engine/briefingLinks.js";
import { ICI_BRIEFING_SOURCE } from "../engine/iciBriefing.js";
import { LlmSourceBadge } from "./LlmSourceBadge.jsx";
import { wrapLon } from "../utils/geo.js";

const NAVIGUIDE_LOGO = "/logo-naviguide.png";
const BERRY_LOGO = "/logo-berry-mappemonde.png";

function BerryCard({
  onCustomRoute, onRouteSwitchToBerry, onRouteSwitchToCustom, isDrawing,
  onDrawStart, onDrawContinue, onDrawFinish, onDrawCancel, onCustomDelete, canContinueDraw,
  canFinishDraw = true,
  onImportRoute, importBusy = false,
  isTracerView = false,
}) {
  const { t } = useLang();
  const importRef = useRef(null);
  const [cardMode, setCardMode] = useState("berry-active");
  const [drawnRoute, setDrawnRoute] = useState(null);
  const [drawnName, setDrawnName] = useState(null);
  const hasCustom = Boolean(drawnRoute);
  const drawingOn = isDrawing || cardMode === "draw-mode";
  const customOn = cardMode === "file-active" && !drawingOn;

  const startOrResumeDraw = () => {
    setCardMode("draw-mode");
    (canContinueDraw ? onDrawContinue : onDrawStart)?.();
  };

  useEffect(() => {
    if (!isDrawing && cardMode === "draw-mode") {
      setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
    }
  }, [isDrawing, cardMode, hasCustom]);

  const activateBerry = () => {
    setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
    onRouteSwitchToBerry();
  };

  const activateCustom = () => {
    if (!drawnRoute) return;
    setCardMode("file-active");
    // La pilule bascule la source sans changer de mode (Suivre ou Tracer).
    (onRouteSwitchToCustom || onCustomRoute)(drawnRoute);
  };

  const handleFinishDrawing = () => {
    const geojson = onDrawFinish();
    if (geojson?.features?.length > 0) {
      setDrawnRoute(geojson);
      setDrawnName(t("customRoute"));
      setCardMode("file-active");
      onCustomRoute(geojson);
    } else {
      setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
    }
  };

  const handleDelete = (e) => {
    e.stopPropagation();
    setDrawnRoute(null);
    setDrawnName(null);
    setCardMode("berry-active");
    onCustomDelete?.();
    onRouteSwitchToBerry();
  };

  const pillOn = "flex-1 min-w-0 px-2 py-1.5 rounded-lg text-[10px] font-semibold leading-tight border border-blue-400/60 bg-blue-600/30 text-blue-100";
  const pillOff = "flex-1 min-w-0 px-2 py-1.5 rounded-lg text-[10px] font-semibold leading-tight border border-slate-600/50 bg-slate-800/50 text-slate-400 hover:text-white hover:border-slate-500";

  // Les pilules Berry-Mappemonde | <ma route> sont toujours rendues en
  // Tracer (VIEW_TRACER) ou pendant un tracé ; sans route perso, la seconde
  // pilule reprend le brouillon ou ouvre un dessin vide.
  const switcher = (hasCustom || isTracerView || isDrawing) ? (
    <div className="flex gap-1 mb-1.5">
      <button type="button" data-testid="route-switch-berry" onClick={activateBerry} className={(customOn || drawingOn) ? pillOff : pillOn} title={t("backToBerry")}>
        {t("berryMappemonde")} {/* pragma: allowlist secret */}
      </button>
      {hasCustom ? (
        <button type="button" data-testid="route-switch-custom" onClick={activateCustom} className={(customOn || drawingOn) ? pillOn : pillOff} title={t("showRoute", { name: drawnName })}>
          {drawnName || t("customRoute")}
        </button>
      ) : (
        <button
          type="button"
          data-testid="route-switch-draw"
          // Même nom accessible que le bouton du bas qu'elle remplace en Tracer
          // (les specs de N4/R9a/R13 le cherchent par ce nom).
          aria-label={`${t("berryMappemonde")} · ${t("drawOwnRoute")}`}
          onClick={startOrResumeDraw}
          className={drawingOn ? pillOn : pillOff}
          title={t("drawOwnRoute")}
        >
          {t("drawOwnRoute")}
        </button>
      )}
    </div>
  ) : null;

  if (cardMode === "draw-mode" || isDrawing) {
    return (
      <div className="rounded-lg px-2 py-1.5 border border-slate-700/50 bg-slate-800/60">
        {switcher}
        {isDrawing ? (
          <div className="flex gap-1">
            <button
              type="button"
              data-testid="route-import"
              disabled={importBusy}
              onClick={() => importRef.current?.click()}
              className="flex-1 flex items-center justify-center gap-1.5 bg-slate-700/40 hover:bg-slate-700/70
                border border-slate-500/50 rounded-lg px-2 py-1.5 text-[10px] text-slate-200 font-semibold
                disabled:opacity-40 disabled:pointer-events-none"
            >
              {t("importRoute")}
            </button>
            <input
              ref={importRef}
              name="route-import-file"
              type="file"
              accept=".geojson,.json,.kml"
              data-testid="route-import-file"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) onImportRoute?.(file);
              }}
            />
            <button
              type="button"
              onClick={() => {
                setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
                onDrawCancel?.();
              }}
              className="flex-1 flex items-center justify-center gap-1.5 bg-slate-700/40 hover:bg-slate-700/70
                border border-slate-500/50 rounded-lg px-2 py-1.5 text-[10px] text-slate-200 font-semibold"
            >
              {t("cancel")}
            </button>
            <button
              type="button"
              onClick={handleFinishDrawing}
              disabled={!canFinishDraw}
              className="flex-1 flex items-center justify-center gap-1.5 bg-green-600/30 hover:bg-green-600/50
                border border-green-500/50 rounded-lg px-2 py-1.5 text-[10px] text-green-300 font-semibold
                disabled:opacity-40 disabled:pointer-events-none"
            >
              <CheckCircle size={11} /> {t("finish")}
            </button>
          </div>
        ) : (
          <button
            onClick={startOrResumeDraw}
            className="w-full flex items-center justify-center gap-1.5 bg-violet-600/20 hover:bg-violet-600/40
              border border-violet-500/40 rounded-lg px-2 py-1.5 text-[10px] text-violet-300 font-medium"
          >
            <Pencil size={11} /> {t("drawOwnRoute")}
          </button>
        )}
      </div>
    );
  }

  // En Tracer sans route perso, la carte montre les pilules et Importer ;
  // le geste « Tracer votre propre route » est la seconde pilule (le bouton du
  // bas reste tel quel en Suivre).
  if (isTracerView && !hasCustom) {
    return (
      <div className="rounded-lg px-2 py-1.5 border border-blue-500/70 bg-blue-950/30">
        {switcher}
        <button
          type="button"
          data-testid="route-import"
          disabled={importBusy}
          onClick={() => importRef.current?.click()}
          className="w-full flex items-center justify-center gap-1.5 bg-slate-700/40 hover:bg-slate-700/70
            border border-slate-500/50 rounded-lg px-2 py-1.5 text-[10px] text-slate-200 font-semibold
            disabled:opacity-40 disabled:pointer-events-none"
        >
          {t("importRoute")}
        </button>
        <input
          ref={importRef}
          name="route-import-file"
          type="file"
          accept=".geojson,.json,.kml"
          data-testid="route-import-file"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            // Même chemin qu'aujourd'hui : l'import se joue dans le mode dessin.
            setCardMode("draw-mode");
            onDrawStart();
            onImportRoute?.(file);
          }}
        />
      </div>
    );
  }

  if (cardMode === "file-active") {
    return (
      <div className="rounded-lg px-2 py-1.5 border border-blue-500/70 bg-blue-950/30">
        {switcher}
        <div className="flex gap-1">
          <button
            type="button"
            onClick={startOrResumeDraw}
            className="flex-1 flex items-center justify-center gap-1 px-1.5 py-1 rounded-lg text-[10px]
              font-medium border border-violet-500/40 text-violet-300 hover:bg-violet-600/20"
          >
            <Pencil size={10} /> {canContinueDraw ? t("continueDrawing") : t("drawOwnRoute")}
          </button>
          <button
            type="button"
            onClick={handleDelete}
            title={t("deleteCustomRoute")}
            className="flex items-center justify-center px-2 py-1 rounded-lg text-[10px]
              border border-red-500/40 text-red-300 hover:bg-red-600/20"
          >
            <Trash2 size={10} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg px-2 py-1.5 border border-blue-500/70 bg-blue-950/30">
      {switcher}
      <button
        onClick={() => { setCardMode("draw-mode"); onDrawStart(); }}
        title={t("drawOwnRoute")}
        className="w-full flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-blue-900/30 cursor-pointer"
      >
        <img src={BERRY_LOGO} alt="Berry-Mappemonde" className="h-7 w-auto object-contain rounded flex-shrink-0" style={{ maxWidth: 48 }} /> {/* pragma: allowlist secret */}
        <div className="text-left">
          <div className="text-white font-bold text-[11px] leading-tight tracking-wide">{t("berryMappemonde")}</div> {/* pragma: allowlist secret */}
          <div className="text-[10px] text-violet-300">{t("drawOwnRoute")}</div>
        </div>
      </button>
    </div>
  );
}

/**
 * Briefing with links. Each place the bag named:
 *   - the name → "voir sur la carte" (layer on + fit boat & place), when it has coordinates
 *   - ↗ → official sheet (Sextant, douane, marina site…) when the bag has a URL
 *   - ◎ → Google Maps sheet, for real places (marinas, ports, anchorages, AtoN, PoE)
 * Plain text is untouched: segments joined === narrateIci().
 */
function BriefingText({ segments, onFocus, t }) {
  return segments.map((seg, i) => {
    if (!seg.entity) return <span key={i}>{seg.text}</span>;
    const e = seg.entity;
    if (e.kind === "source" && e.url) {
      return (
        <a
          key={i}
          href={e.url}
          target="_blank"
          rel="noopener noreferrer"
          title={t("briefingSourceLink")}
          data-testid="briefing-source-link"
          data-kind="source"
          className="text-sky-200 underline decoration-sky-400/70 underline-offset-2 hover:text-white"
        >
          {seg.text}
        </a>
      );
    }
    const links = entityLinks(e);
    const focusable = canFocus(e) && typeof onFocus === "function";
    return (
      <span key={i} className="inline whitespace-nowrap" data-testid="briefing-entity" data-kind={e.kind}>
        {focusable ? (
          <button
            type="button"
            onClick={() => onFocus(e)}
            title={t("briefingSeeOnMap")}
            className="inline text-sky-200 underline decoration-dotted decoration-sky-400/70 underline-offset-2 hover:text-white whitespace-normal text-left"
          >
            {seg.text}
          </button>
        ) : (
          <span className="text-slate-200">{seg.text}</span>
        )}
        {links.map((l) => (
          <a
            key={l.kind}
            href={l.href}
            target="_blank"
            rel="noopener noreferrer"
            title={l.kind === "site" ? `${t("briefingOfficialSheet")} — ${l.host || ""}` : t("briefingGoogleMaps")}
            aria-label={l.kind === "site" ? t("briefingOfficialSheet") : t("briefingGoogleMaps")}
            data-testid={`briefing-link-${l.kind}`}
            className="ml-0.5 text-[10px] text-sky-300/80 hover:text-white align-baseline no-underline"
          >
            {l.kind === "site" ? "↗" : "◎"}
          </a>
        ))}
      </span>
    );
  });
}

export const Sidebar = memo(function Sidebar({
  plan, open, onToggle, onCustomRoute, onRouteSwitchToBerry, onRouteSwitchToCustom, isDrawing,
  onDrawStart, onDrawContinue, onDrawFinish, onDrawCancel, onCustomDelete, canContinueDraw,
  canFinishDraw, drawing = null, onDrawUndo, onImportRoute, importBusy = false,
  isCockpit, polarData, view = VIEW_SUIVRE,
  legContext, nowLeg = null, briefingLoading, officialFallback,
  iciBriefing = null,
  iciBriefingSegments = null, onBriefingFocus,
  skipperNotice = null,
  clockSample = null, atQuay = false, quayDays = 0,
  previewing = false, forecastStatus = null,
  onRecompute, canRecompute = false, recomputeBusy = false, onGoLive,
  journal = null, journalLoading = false, journalError = null,
  story = null, storyReplay = false,
  momentNow = null, momentNowLeft = 0, onMomentDismiss,
  momentFree = null, momentFreeLeft = 0, onMomentNext,
  chat = null, onChatAsk,
  moment = null,
  momentHighSeasRuledOut = false,
  journalEntries = null,
  onSeek = null,
  momentMode = "follow",
  routeSource = "berry",
  planReview = null,
  escaleStop = null,
  escaleFiche = null,
  escaleLoading = false,
  escaleError = null,
  onEscaleClose,
  todayPosition = false,
  replayFrame = null,
}) {
  const { t, lang } = useLang();
  const isTracer = view === VIEW_TRACER;
  const isSuivre = view === VIEW_SUIVRE;
  const expeditionBriefing = plan?.executive_briefing || "";
  const briefing = iciBriefing || expeditionBriefing;
  const briefingTitle = !iciBriefing && typeof plan?.briefing_title === "string"
    ? plan.briefing_title.trim()
    : "";
  // Tracer ouvre le dessin, mais un brouillon vide garde la vitrine
  // Berry (briefing, revue, fiche d'escale). Les scénarios M et R7 cliquent
  // Tracer sans poser de point : le briefing et Ajaccio restent là.
  const drawingHidesBerry = Boolean(isDrawing && drawing?.points?.length);
  const showIciBriefing = !drawingHidesBerry && (isCockpit || briefing || briefingLoading || skipperNotice);
  const drawerRef = useRef(null);
  const [drawerSettled, setDrawerSettled] = useState(false);
  useEffect(() => {
    if (!open) {
      setDrawerSettled(false);
      return undefined;
    }
    const panel = drawerRef.current;
    if (!panel) return undefined;
    let settled = false;
    const finish = (event) => {
      if (settled) return;
      if (event && (event.target !== panel || event.propertyName !== "transform")) return;
      settled = true;
      setDrawerSettled(true);
    };
    panel.addEventListener("transitionend", finish);
    const timer = setTimeout(finish, 350);
    return () => {
      panel.removeEventListener("transitionend", finish);
      clearTimeout(timer);
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open ? "true" : "false"}
        aria-label={open ? t("hideSidebar") : t("showExpeditionPanel")}
        className={`naviguide-sidebar-toggle naviguide-sidebar-toggle--left absolute top-4 z-30 bg-slate-900/95 text-white
          rounded-full flex items-center justify-center shadow-lg
          hover:bg-slate-800 transition-all duration-300
          w-9 h-9 border border-slate-700
          ${open ? "left-[322px]" : "left-4"}`}
        aria-label={open ? t("hideSidebar") : t("showExpeditionPanel")}
        title={open ? t("hideSidebar") : t("showExpeditionPanel")}
      >
        {open ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
      </button>

      <div
        ref={drawerRef}
        className={`naviguide-sidebar-panel naviguide-sidebar-drawer absolute top-0 left-0 h-full z-20 flex flex-col bg-slate-900/97
          shadow-2xl transition-transform duration-300 border-r border-slate-700/60
          ${open ? "translate-x-0" : "-translate-x-full"}
          ${drawerSettled ? "naviguide-drawer-settled" : ""}`}
        style={{ width: 320 }}
      >
        <div className="px-2.5 pt-1.5 pb-1.5 border-b border-slate-700/60 flex-shrink-0">
          <div className="flex items-center gap-2 mb-1">
            <img src={NAVIGUIDE_LOGO} alt={t("brandTitle")} className="h-9 w-9 object-contain drop-shadow" />
            <span className="text-white font-bold text-[11px] leading-tight tracking-wide">{t("brandTitle")}</span>
          </div>

          <BerryCard
            onCustomRoute={onCustomRoute}
            onRouteSwitchToBerry={onRouteSwitchToBerry}
            onRouteSwitchToCustom={onRouteSwitchToCustom}
            isDrawing={isDrawing}
            onDrawStart={onDrawStart}
            onDrawContinue={onDrawContinue}
            onDrawFinish={onDrawFinish}
            onDrawCancel={onDrawCancel}
            onCustomDelete={onCustomDelete}
            canContinueDraw={canContinueDraw}
            canFinishDraw={canFinishDraw}
            onImportRoute={onImportRoute}
            importBusy={importBusy}
            isTracerView={isTracer}
          />

          {!drawingHidesBerry && chat ? (
            <div className="mt-1.5">
              <LogbookChat messages={chat.messages} pending={chat.pending} error={chat.error} onAsk={onChatAsk} />
            </div>
          ) : null}
        </div>

        <div className="naviguide-sidebar-drawer-body flex-1 min-h-0 overflow-hidden flex flex-col px-2.5 py-1.5 gap-1.5">
          {!isCockpit && !plan && !briefingLoading && !isDrawing && (
            <div className="rounded-lg border border-blue-700/30 bg-blue-950/20 p-2 shrink-0">
              <div className="text-[10px] font-semibold text-blue-300 mb-1">{t("gettingStarted")}</div>
              <p className="text-[11px] text-slate-400 leading-snug">{t("gettingStartedText")}</p>
            </div>
          )}

          {isDrawing && (
            <div className="bg-slate-800/50 rounded-lg p-2 border border-slate-700/50 shrink-0">
              <p className="text-[11px] text-slate-300 leading-snug whitespace-pre-line">{t("briefingDrawHint")}</p>
            </div>
          )}
          {isDrawing && drawing ? (
            <div data-testid="drawing-points" className="rounded-lg border border-emerald-500/30 bg-emerald-950/30 p-2 min-w-0 shrink-0">
              <div className="flex items-center gap-2 mb-1">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-200 leading-snug flex-1">
                  {t("drawingInProgress")} · {drawing.points.length} {t("drawingPoints")} · {Number(drawing.distanceNm || 0).toLocaleString(lang === "en" ? "en-US" : "fr-FR")} nm
                </div>
                {drawing.points.length && onDrawUndo ? (
                  <button type="button" onClick={onDrawUndo} className="text-[10px] px-1.5 py-0.5 rounded-md bg-white/5 border border-white/10 hover:bg-white/10 text-white/80" title={t("drawingUndoLast")}>
                    ↶ {t("drawingUndoLast")}
                  </button>
                ) : null}
              </div>
              {drawing.points.length ? (
                <ol className="space-y-0.5">
                  {drawing.points.map((p, i) => (
                    <li key={`${p.lat}-${p.lon}-${i}`} className="text-[11px] text-slate-100 leading-snug flex items-baseline gap-1">
                      <span className="text-[9px] text-emerald-300/80 w-4 shrink-0">{i + 1}</span>
                      <span className="truncate">{p.name}</span>
                      <span className="ml-auto text-[9px] text-slate-500 tabular-nums shrink-0">{p.lat.toFixed(2)}° · {wrapLon(p.lon).toFixed(2)}°</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-[10px] text-slate-400 leading-snug">{drawing.message}</p>
              )}
            </div>
          ) : null}

          {officialFallback && (
            <p className="text-[10px] text-amber-300/90 border border-amber-500/30 rounded-md px-2 py-1 shrink-0">
              {t("searouteUnavailable")}
            </p>
          )}

          <IciMaintenant
            moment={moment}
            highSeasRuledOut={momentHighSeasRuledOut}
            journalEntries={journalEntries}
            journalDays={journal?.days}
            onSeek={onSeek}
            mode={momentMode}
            routeSource={routeSource}
            nowLeg={nowLeg}
            momentNow={!isDrawing ? momentNow : null}
            momentFree={!isDrawing ? momentFree : null}
            onMomentDismiss={onMomentDismiss}
            onMomentNext={onMomentNext}
            onMomentFocus={onBriefingFocus}
            etape={(
              <EtapePanel
                legContext={legContext}
                clockSample={clockSample}
                kindLabel=""
                atQuay={atQuay}
                quayDays={quayDays}
                liveFollow={isSuivre}
                previewing={previewing}
                forecastStatus={isSuivre ? forecastStatus : null}
                onRecompute={onRecompute}
                canRecompute={canRecompute}
                showRecompute={isTracer}
                recomputeBusy={recomputeBusy}
                onGoLive={onGoLive}
              />
            )}
            hereText={!drawingHidesBerry ? (
              plan?.localFallback && expeditionBriefing
                ? expeditionBriefing
                : iciBriefing && iciBriefingSegments?.length ? iciBriefing : (briefing || "")
            ) : ""}
            hereBody={!drawingHidesBerry ? (
              <div data-testid="here-product">
                <div data-testid="briefing" className="sim-box-ici min-w-0 overflow-x-hidden h-auto">
                  {briefingTitle ? (
                    <div className="text-[10px] font-semibold text-blue-200 mb-1 leading-snug break-words [overflow-wrap:anywhere]">
                      {briefingTitle}
                    </div>
                  ) : null}
                  {skipperNotice ? (
                    <p data-testid="skipper-notice" className="text-[10px] font-semibold text-cyan-300 mb-1 leading-snug break-words [overflow-wrap:anywhere]">
                      {skipperNotice}
                    </p>
                  ) : null}
                  <p
                    data-testid="ici-briefing"
                    className="text-[11px] text-slate-300 leading-snug whitespace-pre-line break-words [overflow-wrap:anywhere] max-w-full"
                  >
                    {plan?.localFallback && expeditionBriefing
                      ? expeditionBriefing
                      : iciBriefing && iciBriefingSegments?.length
                        ? <BriefingText segments={iciBriefingSegments} onFocus={onBriefingFocus} t={t} />
                        : (briefingLoading && !(moment?.here?.sentences || []).length ? t("iciBriefingLoading") : (briefing || null))}
                  </p>
                  <LlmSourceBadge source={ICI_BRIEFING_SOURCE} testId="story-source" className="mt-1" />
                </div>
              </div>
            ) : null}
            story={routeSource !== "custom" && (Array.isArray(story) ? story : []).some(Boolean) ? (
              <div data-testid="expedition-story" data-replay={storyReplay ? "1" : "0"} className={`sim-box-story !h-auto rounded-lg border p-2 min-w-0 ${storyReplay ? "border-sky-400/60 bg-sky-900/40" : "border-sky-500/25 bg-sky-950/30"}`}>
                <div className="text-[10px] font-semibold text-sky-200 leading-snug">
                  {t("storyTitle")}{storyReplay ? <span className="ml-1 text-[9px] font-normal text-sky-100/80">· {t("replayBadge")}</span> : null}
                </div>
                {(Array.isArray(story) ? story : []).filter(Boolean).map((paragraph, i, rows) => {
                  const current = storyReplay && i === rows.length - 1;
                  return (
                    <p
                      key={i}
                      data-testid="story-paragraph"
                      data-current={current ? "1" : "0"}
                      className={`text-[11px] leading-snug break-words [overflow-wrap:anywhere] mt-1 ${current ? "text-white font-medium border-l-2 border-sky-300 pl-1.5" : "text-slate-200"}`}
                    >
                      {paragraph}
                    </p>
                  );
                })}
              </div>
            ) : null}
            journal={isSuivre && !isDrawing ? (
              <JournalPanel journal={journal} loading={journalLoading} error={journalError} />
            ) : null}
            planReview={!drawingHidesBerry ? planReview : null}
            escale={!drawingHidesBerry && escaleStop ? {
              stop: escaleStop,
              fiche: escaleFiche,
              loading: escaleLoading,
              error: escaleError,
              onClose: onEscaleClose,
              onFocus: onBriefingFocus,
            } : null}
            todayPosition={todayPosition}
            replayFrame={replayFrame}
          />
        </div>
      </div>
    </>
  );
});
