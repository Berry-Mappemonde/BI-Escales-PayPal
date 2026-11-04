// Visite guidée des juges : étapes et textes via t() (clés demo* dans i18n/en.js et fr.js).
// `custom` = une route terminée de l'utilisateur est la source (carte, briefing, film) :
// le texte ne parle alors ni de « film officiel » ni de la route Berry-Mappemonde.

export const DEMO_STEP_IDS = ["welcome", "models", "live", "briefing", "layers", "replay", "trace", "return"];

/** Côté du panneau sur grand écran : à l'opposé du panneau que l'étape ouvre. */
export const DEMO_PANEL_SIDE = {
  welcome: "right",
  models: "right",
  live: "right",
  briefing: "right",
  layers: "left",
  replay: "right",
  trace: "left",
  return: "right",
};

/**
 * Élément réel éclairé par driver.js à chaque étape (le reste de l'écran est assombri).
 * Sélecteurs stables : `data-tour=…` posés sur les composants, `.leaflet-container` (Leaflet)
 * et `view-tracer` (bouton Tracer). `null` = étape sans élément : rien n'est assombri.
 */
export const DEMO_TOUR_TARGETS = {
  welcome: null,
  models: null,
  live: ".leaflet-container",
  briefing: '[data-tour="logbook"]',
  layers: '[data-tour="layers"]',
  replay: '[data-tour="film"]',
  trace: '[data-testid="view-tracer"]',
  return: null,
};

/**
 * @param {(key: string, vars?: object) => string} t
 * @param {{ replayState?: "ready" | "playing" | "unavailable", custom?: boolean }} [opts]
 */
export function getDemoSteps(t, { replayState = "unavailable", custom = false } = {}) {
  const replayBody = replayState === "playing"
    ? t("demoPlaying")
    : replayState === "ready"
      ? t(custom ? "demoReplayReadyCustom" : "demoReplayReady")
      : t(custom ? "demoReplayUnavailableCustom" : "demoReplayUnavailable");
  const body = {
    welcome: t("demoWelcomeBody"),
    models: t("demoModelsBody"),
    live: t(custom ? "demoLiveBodyCustom" : "demoLiveBody"),
    briefing: t("demoBriefingBody"),
    layers: t("demoLayersBody"),
    replay: replayBody,
    trace: t(custom ? "demoTraceBodyFinished" : "demoTraceBody"),
    return: t(custom ? "demoReturnBodyCustom" : "demoReturnBody"),
  };
  const title = {
    welcome: t("demoWelcomeTitle"),
    models: t("demoModelsTitle"),
    live: t("demoLiveTitle"),
    briefing: t("demoBriefingTitle"),
    layers: t("demoLayersTitle"),
    replay: t("replayStart"),
    trace: t("demoTraceTitle"),
    return: t("demoReturnTitle"),
  };
  return DEMO_STEP_IDS.map((id) => ({ id, action: id, title: title[id], body: body[id], side: DEMO_PANEL_SIDE[id], target: DEMO_TOUR_TARGETS[id] }));
}

// Étape « Qui fait quoi » : modèles Nemotron (Nebius Token Factory) par palier, lus en direct
// dans /ici/warm/status (`llm.configuredModels`). Sans réponse, on montre les défauts du code,
// signalés comme tels. Miroir de server/llm_budget.py DEFAULT_MODELS (un test pytest compare).
export const TOUR_DEFAULT_MODELS = {
  nano: "nvidia/Nemotron-3_5-Lightning",
  fast: "nvidia/Nemotron-3_5-Lightning",
  write: "nvidia/Nemotron-3.5-Super-VL",
  deep: "nvidia/Nemotron-3-Ultra-550b-a55b",
  judge: "nvidia/Nemotron-3-Ultra-550b-a55b",
};

const MODEL_NAMES = {
  "nvidia/nemotron-3_5-lightning": "Nemotron 3.5 Lightning",
  "nvidia/nemotron-3.5-super-vl": "Nemotron 3.5 Super VL",
  "nvidia/nemotron-3-ultra-550b-a55b": "Nemotron 3 Ultra",
  "nvidia/nemotron-3-super-120b-a12b": "Nemotron 3 Super 120B",
  "nvidia/nemotron-3-nano-30b-a3b": "Nemotron 3 Nano 30B",
  "nvidia/nvidia-nemotron-3-nano-30b-a3b": "Nemotron 3 Nano 30B",
};

/** Nom lisible d'un id Token Factory ; un id inconnu reste tel quel (rien d'inventé). */
export function modelDisplayName(id) {
  const raw = typeof id === "string" ? id.trim() : "";
  if (!raw) return "";
  return MODEL_NAMES[raw.toLowerCase()] || raw;
}

// Rôle → paliers de llm_budget.TIERS qui le servent (voir les appels cascade(tier=…)).
export const TOUR_MODEL_ROLES = [
  { id: "quick", tiers: ["nano", "fast"], key: "demoModelsQuick" },
  { id: "write", tiers: ["write"], key: "demoModelsWrite" },
  { id: "deep", tiers: ["deep", "judge"], key: "demoModelsDeep" },
];

/**
 * Lignes de l'étape « Qui fait quoi ».
 * @param {any} llm  bloc `llm` de /ici/warm/status (ou null si indisponible)
 * @param {(key: string, vars?: object) => string} t
 * @returns {{ live: boolean, rows: {id: string, text: string}[], today: string | null }}
 */
export function describeModelRoles(llm, t) {
  const cm = llm && typeof llm === "object" && llm.configuredModels && typeof llm.configuredModels === "object"
    ? llm.configuredModels
    : null;
  const live = Boolean(cm);
  const models = { ...TOUR_DEFAULT_MODELS, ...(cm || {}) };
  const rows = TOUR_MODEL_ROLES.map(({ id, tiers, key }) => {
    const names = [...new Set(tiers.map((tier) => modelDisplayName(models[tier])).filter(Boolean))];
    return { id, text: t(key, { models: names.join(" + ") }) };
  });
  rows.push({ id: "tavily", text: t("demoModelsTavily") });
  let today = null;
  if (llm && typeof llm === "object") {
    const calls = ["nano", "fast", "write", "deep", "judge"]
      .reduce((n, tier) => n + (Number(llm?.[tier]?.calls) || 0), 0);
    const tavily = Number(llm?.tavily?.calls) || 0;
    today = t("demoModelsToday", { calls: String(calls), tavily: String(tavily) });
  }
  return { live, rows, today };
}

/** `?tour=1` (ou true / yes / on) ouvre la visite au chargement. */
export function wantsTourFromUrl(search) {
  try {
    const v = new URLSearchParams(search || "").get("tour");
    return typeof v === "string" && ["1", "true", "yes", "on"].includes(v.trim().toLowerCase());
  } catch {
    return false;
  }
}

// Étape film : bouton « Lire le film Rédigé » en un clic (idée C2-b, IDEATION-CRITERES-1005).
// Le bouton n'est proposé que si le serveur a un rédigé pour cette durée (`hasWritten`) ;
// sinon le repli Brut est annoncé AVANT le clic (aucun appel Nemotron lancé par la visite).

/** "edited" : le rédigé existe, la visite propose le bouton Rédigé ; "fallback" : seul le Brut joue. */
export function tourEditedOffer({ hasWritten = false } = {}) {
  return hasWritten ? "edited" : "fallback";
}

/** Délai au-delà duquel une demande de rédigé non servie retombe sur le Brut, annoncé. */
export const TOUR_EDITED_WAIT_MS = 45_000;

/**
 * Que faire d'une demande « Lire le film Rédigé » en attente ?
 * `loadedStyle` = style du plan chargé quand le serveur a servi le style demandé
 * ("written" ou "raw"), "mismatch" quand il a servi le Brut à une demande Rédigé, "" sinon.
 * @returns {"idle" | "wait" | "edited" | "raw"}
 */
export function tourEditedStep({
  pending = false, active = false, filmStyle = "raw", loadedStyle = "", remoteStatus = "pending", canStart = false,
} = {}) {
  if (!pending || active) return "idle";
  if (remoteStatus !== "ready" || !canStart) return "wait";
  if (filmStyle === "written" && loadedStyle === "written") return "edited";
  if (filmStyle !== "written" && loadedStyle === "raw") return "raw";
  return "wait";
}

export const PANEL_HEIGHT = 420;
const MIN_TOP = 56;
const MOBILE_BREAKPOINT = 768;
const MIN_BOTTOM = 56;

/**
 * Compute panel position (top/bottom CSS) for the demo walkthrough panel.
 * @param {{top: number, bottom: number, height: number} | null} anchor - Anchor element bounding rect
 * @param {string} stepId - Current step id
 * @param {number} innerWidth - window.innerWidth
 * @param {number} innerHeight - window.innerHeight
 * @returns {{top?: string, bottom?: string} | undefined}
 */
export function computePanelPosition(
  anchor, stepId, innerWidth, innerHeight, panelHeight = PANEL_HEIGHT,
) {
  if (!anchor || innerWidth < MOBILE_BREAKPOINT) return undefined;

  const requested = Math.max(120, Number(panelHeight) || PANEL_HEIGHT);
  const height = Math.min(requested, Math.max(120, innerHeight - MIN_TOP - MIN_BOTTOM));
  const maxTop = innerHeight - height;

  // Step "replay": position above film bar when anchor is in bottom half
  if (stepId === "replay") {
    const anchorCenterY = anchor.top + anchor.height / 2;
    const screenCenterY = innerHeight / 2;
    if (anchorCenterY > screenCenterY) {
      let bottom = innerHeight - anchor.top + 12;
      const topOfPanel = innerHeight - bottom - height;
      if (topOfPanel < MIN_TOP) {
        bottom = innerHeight - MIN_TOP - height;
      }
      bottom = Math.max(MIN_BOTTOM, bottom);
      return { bottom: `${Math.round(bottom)}px`, top: "auto" };
    }
  }

  // Default: clamp top between MIN_TOP and maxTop, ensure bottom >= MIN_BOTTOM
  const maxTopClamped = innerHeight - height - MIN_TOP;
  const clampedTop = Math.max(MIN_TOP, Math.min(anchor.top, maxTopClamped));
  const bottom = innerHeight - clampedTop - height;
  if (bottom < MIN_BOTTOM) {
    const clampedBottom = Math.max(MIN_BOTTOM, bottom);
    const topFromBottom = innerHeight - height - clampedBottom;
    return { top: `${Math.round(topFromBottom)}px` };
  }
  return { top: `${Math.round(clampedTop)}px` };
}

/**
 * Compute data-arrow attribute for the bubble arrow based on anchor and panel position.
 * @param {{top: number, bottom: number, height: number, left?: number, width?: number} | null} anchor - Anchor element bounding rect
 * @param {string} stepId - Current step id
 * @param {number} innerWidth - window.innerWidth
 * @param {number} innerHeight - window.innerHeight
 * @returns {"up" | "down" | "left" | "right" | undefined}
 */
export function computeArrowDirection(
  anchor, stepId, innerWidth, innerHeight, panelHeight = PANEL_HEIGHT,
) {
  if (!anchor || innerWidth < MOBILE_BREAKPOINT) return undefined;
  
  const panelPos = computePanelPosition(anchor, stepId, innerWidth, innerHeight, panelHeight);
  if (!panelPos) return undefined;

  // Special case for replay step: panel is conceptually above film bar at bottom, arrow always points down
  if (stepId === "replay") {
    return "down";
  }

  // For all other steps with a target, arrow points horizontally based on panel side
  // Panel is always on left or right side (never center) for demo steps
  const panelSide = DEMO_PANEL_SIDE[stepId];
  if (panelSide === "left") {
    return "right";  // Arrow points from left panel toward anchor (right)
  }
  return "left";      // Arrow points from right panel toward anchor (left)
}

/**
 * Get stagePadding for a specific step.
 * @param {string} stepId - Current step id
 * @returns {number}
 */
export function getStagePadding(stepId) {
  if (stepId === "trace") return 14;
  return 6;
}
