/** Deux boutons seulement. Pas de 3ᵉ interrupteur. */
export const VIEW_SUIVRE = "suivre";
export const VIEW_TRACER = "tracer";

/** Protocole serveur, inchangé. */
export const SERVER_MODE_TRACER = "simulation";

export function isSuivreView(view) {
  return view === VIEW_SUIVRE;
}

export function isTracerView(view) {
  return view === VIEW_TRACER;
}

/** Lecture, curseur et sauts sont réservés au film de Tracer. */
export function hasTracerPlaybackControls(view) {
  return isTracerView(view);
}
