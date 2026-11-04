import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Compass, Loader2, Play, X } from "lucide-react";
import { driver } from "driver.js";
import "driver.js/dist/driver.css";
import { useLang } from "../i18n/LangContext.jsx";
import { describeModelRoles, getDemoSteps, tourEditedOffer, computePanelPosition, computeArrowDirection, getStagePadding } from "./demoWalkthrough.js";
import { describeTfLatency } from "../utils/tfLatency.js";

const API_URL = import.meta.env?.VITE_API_URL ?? "";

async function defaultFetchStatus() {
  const r = await fetch(`${API_URL}/ici/warm/status`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export { getDemoSteps } from "./demoWalkthrough.js";

/**
 * Visite guidée des juges. N'injecte aucune donnée : elle ne fait que changer la vue.
 * Masquée en plein écran du film et pendant une fenêtre modale ; réduite à une pastille
 * pendant la lecture du film ; panneau du côté opposé à celui que l'étape ouvre,
 * et en bas de l'écran sous 768 px.
 */
/** Nombre d'images (rAF) pendant lesquelles on attend le bouton Tracer monté tard. */
export const PULSE_MAX_ATTEMPTS = 30;

export function DemoWalkthrough({
  replayReady = false,
  replayActive = false,
  customRoute = false,
  hidden = false,
  isLightMode = false,
  autoStart = false,
  fetchStatus = defaultFetchStatus,
  onStepChange,
  onPlayReplay,
  editedReady = false,
  editedSource = "",
  editedPending = false,
  editedFellBack = false,
  onPlayEdited,
  onClose,
}) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [expanded, setExpanded] = useState(true);
  const launchRef = useRef(null);
  const headingRef = useRef(null);
  const chipRef = useRef(null);
  const panelRef = useRef(null);
  const returnFocusRef = useRef(false);
  const autoStartedRef = useRef(false);
  // Étape « Qui fait quoi » : une lecture de /ici/warm/status par ouverture de la visite.
  const [status, setStatus] = useState({ state: "idle", llm: null });
  const replayState = replayActive ? "playing" : replayReady ? "ready" : "unavailable";
  const steps = getDemoSteps(t, { replayState, custom: customRoute });
  const step = steps[index];
  const total = steps.length;
  const collapsed = open && replayActive && !expanded;

  // Film en lecture : la visite se réduit à une pastille ; elle se rouvre quand le film s'arrête.
  useEffect(() => { setExpanded(!replayActive); }, [replayActive]);

  // Focus : le titre de l'étape à l'ouverture et à chaque étape ; le lanceur à la fermeture.
  useEffect(() => {
    if (open && !collapsed && !hidden) headingRef.current?.focus({ preventScroll: true });
  }, [open, index, collapsed, hidden]);
  useEffect(() => {
    if (!open && returnFocusRef.current) {
      returnFocusRef.current = false;
      launchRef.current?.focus({ preventScroll: true });
    }
  }, [open]);

  const close = () => {
    returnFocusRef.current = true;
    setOpen(false);
    onClose?.();
  };
  const closeRef = useRef(close);
  closeRef.current = close;

  // Échap ferme la visite. Phase de capture + stopPropagation : sinon l'écouteur
  // d'App (onEscDraw) annule le tracé et efface le brouillon à l'étape Tracer.
  useEffect(() => {
    if (!open || hidden) return undefined;
    const onEsc = (e) => {
      if (e.key !== "Escape" && e.key !== "Esc" && e.code !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      closeRef.current();
    };
    window.addEventListener("keydown", onEsc, true);
    return () => window.removeEventListener("keydown", onEsc, true);
  }, [open, hidden]);

  // La réponse d'une ancienne ouverture (session dépassée) est ignorée.
  const sessionRef = useRef(0);
  useEffect(() => {
    if (!open || step?.id !== "models" || status.state !== "idle") return;
    const session = sessionRef.current;
    setStatus({ state: "loading", llm: null });
    Promise.resolve()
      .then(() => fetchStatus())
      .then((data) => {
        if (session !== sessionRef.current) return;
        const llm = data && data.llm && typeof data.llm === "object" ? data.llm : null;
        setStatus({ state: llm ? "ready" : "error", llm });
      })
      .catch(() => { if (session === sessionRef.current) setStatus({ state: "error", llm: null }); });
  }, [open, step?.id, status.state, fetchStatus]);

  const start = () => {
    setIndex(0);
    setExpanded(true);
    sessionRef.current += 1;
    setStatus({ state: "idle", llm: null });
    setOpen(true);
    onStepChange?.(steps[0].action);
  };
  const startRef = useRef(start);
  startRef.current = start;

  // Lien profond `?tour=1` : la visite s'ouvre une fois au chargement.
  useEffect(() => {
    if (!autoStart || autoStartedRef.current) return;
    autoStartedRef.current = true;
    startRef.current();
  }, [autoStart]);

  // Projecteur driver.js (MIT) : assombrit tout l'écran sauf l'élément réel de l'étape.
  // Le panneau React reste la bulle (boutons, i18n, focus) ; driver.js ne gère que le spot.
  const driverRef = useRef(null);
  const [anchor, setAnchor] = useState(null);
  const spotOn = open && !hidden && !collapsed;
  const target = step?.target || null;

  // Destruction immédiate si la cible est null (étapes welcome, models, return) :
  // on tue l'instance AVANT tout rAF pour éviter tout overlay/dimming résiduel et la classe driver-active.
  useEffect(() => {
    if (spotOn && target === null) {
      driverRef.current?.destroy();
      driverRef.current = null;
      setAnchor(null);
    }
  }, [spotOn, target]);

  useEffect(() => {
    if (!spotOn || !target) {
      driverRef.current?.destroy();
      driverRef.current = null;
      setAnchor(null);
      return undefined;
    }
    let raf = 0;
    let tries = 0;
    let last = "";
    let stable = 0;
    const stagePadding = getStagePadding(step.id);
    const make = () => driver({
      animate: false,
      allowClose: false,
      allowKeyboardControl: false,
      overlayClickBehavior: () => {},
      overlayOpacity: 0.62,
      stagePadding,
      stageRadius: 10,
      smoothScroll: false,
    });
    const show = (el) => {
      // Nouvelle instance à chaque mesure : refresh() / highlight() du même élément gardent l'ancien cadre.
      driverRef.current?.destroy();
      driverRef.current = make();
      driverRef.current.highlight({ element: el });
      const r = el.getBoundingClientRect();
      setAnchor({ top: r.top, bottom: r.bottom, height: r.height });
    };
    // Les panneaux s'ouvrent puis glissent : on suit la position de l'élément et on recale
    // le projecteur dès qu'il bouge (pas de projecteur sur un élément encore hors écran).
    let shown = "";
    const track = () => {
      const el = document.querySelector(target);
      if (el) {
        const r = el.getBoundingClientRect();
        const key = `${Math.round(r.left)},${Math.round(r.top)},${Math.round(r.width)},${Math.round(r.height)}`;
        stable = key === last ? stable + 1 : 0;
        last = key;
        if (stable >= 3 && key !== shown) { shown = key; show(el); }
      } else if (driverRef.current) {
        driverRef.current.destroy();
        driverRef.current = null;
        shown = "";
        setAnchor(null);
      }
      tries += 1;
      raf = window.requestAnimationFrame(track);
    };
    raf = window.requestAnimationFrame(track);
    const onResize = () => {
      shown = "";
      last = "";
      stable = 0;
      tries = 0;
      window.cancelAnimationFrame(raf);
      raf = window.requestAnimationFrame(track);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [spotOn, target, step.id]);
  useEffect(() => () => { driverRef.current?.destroy(); driverRef.current = null; }, []);

  // R13 : Tab / Maj+Tab restent dans le panneau tant que la visite est ouverte.
  useEffect(() => {
    if (!open || hidden || collapsed) return undefined;
    const root = panelRef.current;
    if (!root) return undefined;
    const focusables = () => [...root.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter((el) => el.getClientRects().length > 0);
    const onTab = (e) => {
      if (e.key !== "Tab") return;
      const items = focusables();
      if (items.length < 2) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    const onFocusOut = (e) => {
      const next = e.relatedTarget;
      if (next && root.contains(next)) return;
      requestAnimationFrame(() => {
        if (!root.contains(document.activeElement)) {
          focusables()[0]?.focus({ preventScroll: true });
        }
      });
    };
    root.addEventListener("keydown", onTab);
    root.addEventListener("focusout", onFocusOut);
    return () => {
      root.removeEventListener("keydown", onTab);
      root.removeEventListener("focusout", onFocusOut);
    };
  }, [open, hidden, collapsed, index, step.id]);

  // Pulse animation on "trace" step target — unique useEffect, réessaye si le bouton n'existe pas encore
  useEffect(() => {
    if (step.id !== "trace" || !target) return;
    let el = null;
    // checkRaf ne sert qu'à l'annulation : un id rAF n'est pas un nombre d'essais.
    let checkRaf = 0;
    let attempts = 0;
    const tryAdd = () => {
      el = document.querySelector(target);
      if (el) {
        el.classList.add("naviguide-tour-pulse");
      } else if (++attempts < PULSE_MAX_ATTEMPTS) {
        checkRaf = window.requestAnimationFrame(tryAdd);
      }
    };
    tryAdd();
    return () => {
      window.cancelAnimationFrame(checkRaf);
      if (el) el.classList.remove("naviguide-tour-pulse");
    };
  }, [step.id, target]);

  if (hidden) return null;

  const goTo = (nextIndex) => {
    const next = Math.max(0, Math.min(total - 1, nextIndex));
    setIndex(next);
    onStepChange?.(steps[next].action);
  };

  const light = isLightMode;
  const primaryButton = light
    ? "inline-flex items-center justify-center gap-1.5 rounded-lg border border-cyan-700/40 bg-cyan-600/10 px-3 py-2 text-xs font-semibold text-cyan-900 hover:bg-cyan-600/20 disabled:cursor-not-allowed disabled:opacity-45"
    : "inline-flex items-center justify-center gap-1.5 rounded-lg border border-cyan-300/40 bg-cyan-300/15 px-3 py-2 text-xs font-semibold text-cyan-50 hover:bg-cyan-300/25 disabled:cursor-not-allowed disabled:opacity-45";
  const secondaryButton = light
    ? "inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
    : "inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-xs font-semibold text-white/85 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40";
  const surface = light
    ? "border-slate-300 bg-white/97 text-slate-900"
    : "border-white/15 bg-slate-950/96 text-white";
  const muted = light ? "text-slate-500" : "text-white/45";
  const bodyText = light ? "text-slate-700" : "text-white/75";
  // Desktop : côté opposé au panneau ouvert par l'étape. Mobile : feuille en bas.
  const side = step.side === "left" ? "md:left-3 md:right-auto" : "md:right-3 md:left-auto";

  if (!open) {
    return (
      <button
        ref={launchRef}
        type="button"
        data-testid="demo-walkthrough-launch"
        onClick={start}
        className={`naviguide-demo-launch fixed right-3 top-14 z-[2300] inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold shadow-xl backdrop-blur-sm ${light ? "border-cyan-700/30 bg-white/95 text-slate-900 hover:bg-slate-100" : "border-cyan-200/35 bg-slate-950/95 text-white hover:bg-slate-900"}`}
        title={t("demoLaunchTitle")}
      >
        <Compass size={15} aria-hidden="true" />
        {t("demoLaunch")}
      </button>
    );
  }

  if (collapsed) {
    return (
      <button
        ref={chipRef}
        type="button"
        data-testid="demo-walkthrough-chip"
        onClick={() => setExpanded(true)}
        title={t("demoChipTitle")}
        className={`naviguide-demo-launch fixed right-3 top-14 z-[2300] inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-semibold shadow-xl ${surface}`}
      >
        <Compass size={13} aria-hidden="true" />
        {t("demoChip", { n: index + 1, total })}
      </button>
    );
  }

  // Compute panel position using pure logic from demoWalkthrough.js
  const panelStyle = anchor && typeof window !== "undefined" && window.innerWidth >= 768
    ? computePanelPosition(anchor, step.id, window.innerWidth, window.innerHeight)
    : undefined;

  const arrowDir = (anchor && window && window.innerWidth >= 768)
    ? computeArrowDirection(anchor, step.id, window.innerWidth, window.innerHeight)
    : undefined;

  return (
    <div
      data-arrow={arrowDir || undefined}
      style={panelStyle}
      className={`naviguide-demo-panel fixed z-[2300] inset-x-2 bottom-2 md:inset-x-auto md:bottom-auto md:top-14 md:w-[min(23rem,calc(100vw-1.5rem))] ${side}`}
    >
    <aside
      ref={panelRef}
      role="region"
      aria-label={t("demoRegion")}
      data-testid="demo-walkthrough-panel"
      data-arrow={arrowDir || undefined}
      data-step={step.id}
      data-side={step.side}
      data-target={step.target || ""}
      data-spot={anchor ? "on" : "off"}
      className={`flex max-h-[45dvh] flex-col overflow-y-auto rounded-2xl border p-4 shadow-2xl backdrop-blur-md md:max-h-[calc(100dvh-5rem)] ${surface}`}
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
      <p className="sr-only" aria-live="polite" data-testid="demo-walkthrough-live">
        {t("demoStepLive", { n: index + 1, total, title: step.title })}
      </p>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className={`flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] ${light ? "text-cyan-800" : "text-cyan-100/80"}`}>
          <Compass size={14} aria-hidden="true" />
          {t("demoKicker")}
        </div>
        <button
          type="button"
          data-testid="demo-walkthrough-close"
          onClick={close}
          aria-label={t("demoClose")}
          className={`rounded-md p-1 ${light ? "text-slate-500 hover:bg-slate-100" : "text-white/65 hover:bg-white/10 hover:text-white"}`}
        >
          <X size={17} aria-hidden="true" />
        </button>
      </div>

      <div
        role="progressbar"
        aria-label={t("demoProgress")}
        aria-valuemin={1}
        aria-valuemax={total}
        aria-valuenow={index + 1}
        aria-valuetext={t("demoStepOf", { n: index + 1, total })}
        className={`mb-4 h-1.5 overflow-hidden rounded-full ${light ? "bg-slate-200" : "bg-white/10"}`}
      >
        <div className="h-full rounded-full bg-cyan-400/80 transition-[width]" style={{ width: `${((index + 1) / total) * 100}%` }} />
      </div>

      <p className={`mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${muted}`}>
        {t("demoStepOf", { n: index + 1, total })}
      </p>
      <h2 ref={headingRef} tabIndex={-1} data-testid="demo-walkthrough-title" className="text-base font-semibold leading-snug outline-none">{step.title}</h2>
      <p data-testid="demo-walkthrough-body" className={`mt-2 text-sm leading-relaxed ${bodyText}`}>{step.body}</p>

      {step.id === "models" ? (() => {
        const roles = status.state === "loading" || status.state === "idle" ? null : describeModelRoles(status.llm, t);
        return (
          <div data-testid="demo-models" data-live={roles?.live ? "true" : "false"} className={`mt-3 rounded-xl border p-3 text-xs leading-relaxed ${light ? "border-slate-200 bg-slate-50 text-slate-700" : "border-white/10 bg-white/5 text-white/80"}`}>
            {roles ? (
              <>
                <ul className="space-y-1.5">
                  {roles.rows.map((r) => (
                    <li key={r.id} data-testid={`demo-models-${r.id}`}>{r.text}</li>
                  ))}
                </ul>
                {roles.today ? <p data-testid="demo-models-today" className={`mt-2 ${muted}`}>{roles.today}</p> : null}
                {(() => {
                  const tf = describeTfLatency(status.llm, t);
                  return (
                    <>
                      {tf.latency ? <p data-testid="demo-models-latency" className={`mt-1 ${muted}`}>{tf.latency}</p> : null}
                      {tf.missing.map((m) => (
                        <p key={m.tier} data-testid={`demo-models-missing-${m.tier}`} className="mt-1 font-medium">{m.text}</p>
                      ))}
                    </>
                  );
                })()}
                {!roles.live ? <p data-testid="demo-models-default" className={`mt-2 ${muted}`}>{t("demoModelsDefault")}</p> : null}
              </>
            ) : (
              <p className={muted}>{t("demoModelsLoading")}</p>
            )}
            <p data-testid="demo-models-thesis" className={`mt-2 font-semibold ${light ? "text-cyan-900" : "text-cyan-100"}`}>{t("demoModelsThesis")}</p>
          </div>
        );
      })() : null}

      {step.id === "replay" ? (() => {
        const offer = tourEditedOffer({ hasWritten: editedReady });
        const showEdited = offer === "edited" && replayReady && !replayActive;
        return (
          <div data-testid="demo-replay-box" data-edited={offer} className={`mt-4 rounded-xl border p-3 ${light ? "border-slate-200 bg-slate-50" : "border-white/10 bg-white/5"}`}>
            {showEdited ? (
              <>
                <button
                  type="button"
                  data-testid="demo-walkthrough-play-edited"
                  onClick={onPlayEdited}
                  disabled={editedPending}
                  aria-busy={editedPending}
                  className={primaryButton}
                >
                  {editedPending ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
                  {editedPending ? t("demoEditedLoading") : t("demoPlayEdited")}
                </button>
                <p data-testid="demo-edited-source" className={`mt-2 text-xs leading-relaxed ${bodyText}`}>
                  {t("demoEditedBy", { source: editedSource || t("storySourceSuper") })}
                </p>
              </>
            ) : null}
            {replayActive ? null : (
              <button
                type="button"
                data-testid="demo-walkthrough-play"
                onClick={onPlayReplay}
                disabled={!replayReady || editedPending}
                className={`${showEdited ? secondaryButton : primaryButton}${showEdited ? " mt-2" : ""}`}
              >
                <Play size={14} aria-hidden="true" />
                {t("replayStart")}
              </button>
            )}
            {offer === "fallback" && replayReady && !replayActive ? (
              <p data-testid="demo-edited-fallback" className={`mt-2 text-xs leading-relaxed ${bodyText}`}>
                {t(customRoute ? "demoEditedFallbackCustom" : "demoEditedFallback")}
              </p>
            ) : null}
            {editedFellBack ? (
              <p data-testid="demo-edited-fell-back" role="status" className={`mt-2 text-xs leading-relaxed ${bodyText}`}>
                {t("demoEditedFellBack")}
              </p>
            ) : null}
            {!replayReady && !replayActive ? (
              <p className={`mt-2 text-xs leading-relaxed ${muted}`}>{t("demoNoFake")}</p>
            ) : null}
          </div>
        );
      })() : null}

      <div className={`mt-5 flex items-center justify-between gap-2 border-t pt-3 ${light ? "border-slate-200" : "border-white/10"}`}>
        <button type="button" data-testid="demo-walkthrough-prev" onClick={() => goTo(index - 1)} disabled={index === 0} className={secondaryButton}>
          <ArrowLeft size={14} aria-hidden="true" />
          {t("demoPrev")}
        </button>
        {index < total - 1 ? (
          <button type="button" data-testid="demo-walkthrough-next" onClick={() => goTo(index + 1)} className={primaryButton}>
            {t("demoNext")}
            <ArrowRight size={14} aria-hidden="true" />
          </button>
        ) : (
          <button type="button" data-testid="demo-walkthrough-end" onClick={close} className={primaryButton}>
            {t("demoEnd")}
          </button>
        )}
      </div>
      <button
        type="button"
        data-testid="demo-walkthrough-exit"
        onClick={close}
        className={`mt-2 self-start rounded-md px-1 py-1 text-xs underline underline-offset-2 ${muted}`}
      >
        {t("demoExit")}
      </button>
      </div>
    </aside>
    </div>
  );
}
