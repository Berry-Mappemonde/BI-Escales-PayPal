/**
 * Plancher de dézoom (27 sept. / RG15) : le monde tient AU PLUS une fois dans
 * l'écran — largeur 256·2^z px ≥ plus grand côté de la carte. Même formule en
 * Suivre, Simulation, film et Tracer ; la navigation gauche/droite reste libre
 * (±540°, une répétition de chaque côté). Tracer pose la vue à ce plancher
 * (monde entier, une fois), sans redescendre à un zoom qui répéterait le globe.
 */
export const WORLD_TILE_PX = 256;

export function followMinZoom(size, snap = 0.25, floor = 0) {
  const w = Number(size?.x) || 0;
  const h = Number(size?.y) || 0;
  const side = Math.max(w, h);
  const base = Number.isFinite(Number(floor)) ? Number(floor) : 0;
  if (!(side > 0)) return base;
  const exact = Math.log2(side / WORLD_TILE_PX);
  const step = Number(snap) > 0 ? Number(snap) : 0.25;
  return Math.max(base, Math.ceil(exact / step - 1e-9) * step);
}

/** Vue monde « une fois » : au moins WORLD_ZOOM, jamais sous le plancher anti-répétition. */
export function worldViewZoom(size, snap = 0.25, worldZoom = 2, floor = 0) {
  const want = Number.isFinite(Number(worldZoom)) ? Number(worldZoom) : 2;
  return Math.max(want, followMinZoom(size, snap, floor));
}

/** Largeur du monde en pixels au zoom donné (Web Mercator, tuiles 256 px). */
export function worldWidthPx(zoom) {
  return WORLD_TILE_PX * 2 ** Number(zoom || 0);
}
