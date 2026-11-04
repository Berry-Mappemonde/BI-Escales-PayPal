import { haversineNm } from "./geo.js";

/** Porte d’affichage : rien n’est peint tant que route + horloge + caméra ne sont pas prêts. */

/**
 * Horloge live officielle.
 * Le serveur gagne dès qu’il est là. Sinon on fige le premier snapshot client
 * pour qu’une polaire tardive ne recalcule pas la position ni le masque.
 * Ne jamais préférer `clock || serverClock` (horloge cliente mutable).
 */
export function pickOfficialLiveClock(serverClock, clientClock, frozenClient = null) {
  if (serverClock) {
    return {
      liveClock: serverClock,
      frozenClient: frozenClient || clientClock || null,
    };
  }
  const frozen = frozenClient || clientClock || null;
  return { liveClock: frozen, frozenClient: frozen };
}

/** Une fois la scène ouverte, un resync playhead / horloge serveur ne ramène pas le masque. */
export function shouldKeepSceneVisible({ revealed, routeReady, hasRoute } = {}) {
  return Boolean(revealed && routeReady && hasRoute);
}

export function sceneMaskKey({ routeReady } = {}) {
  return routeReady ? "positioningExpedition" : "calculatingRoutes";
}

export function playheadAligned({
  isSuivre,
  previewing,
  playbackNm,
  liveFilmNm,
  slack = 2,
} = {}) {
  if (!isSuivre || previewing) return true;
  if (liveFilmNm == null || !Number.isFinite(Number(liveFilmNm))) return false;
  return Math.abs((Number(playbackNm) || 0) - Number(liveFilmNm)) <= slack;
}

export function isSceneReady({
  routeReady,
  hasRoute,
  cameraPlaced,
  playheadReady,
  isSuivre,
  hasLive,
  previewing,
} = {}) {
  if (!routeReady || !hasRoute || !cameraPlaced) return false;
  if (isSuivre && !hasLive && !previewing) return false;
  if (isSuivre && !playheadReady) return false;
  return true;
}

/** Une navigation manuelle pendant le chargement garde la vue choisie par la personne. */
export function shouldPlaceInitialCamera({ userNavigated = false } = {}) {
  return !userNavigated;
}

/** Un saut manuel arrêté en Tracer recentre une fois, sans suivi cinéma. */
export function shouldFocusTracerJump({ isTracer, playing } = {}) {
  return Boolean(isTracer && !playing);
}

/** Premier snap, ou téléport (horloge serveur wrappée → horloge client dépliée). */
export function shouldResnapCamera(prev, next, nm = 80) {
  if (next?.lat == null || next?.lon == null) return false;
  if (!prev || prev.lat == null || prev.lon == null) return true;
  return haversineNm(prev.lat, prev.lon, next.lat, next.lon) >= nm;
}
