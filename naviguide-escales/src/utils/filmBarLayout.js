/** Largeur d’une sidebar (gauche ou droite), en px. */
export const SIDEBAR_WIDTH_PX = 320;

/**
 * Sous cette largeur (px), le panneau gauche est un tiroir : il recouvre la
 * carte au lieu de réserver une colonne. 600 px pile reste le bureau.
 */
export const NARROW_LAYOUT_MAX_PX = 599;

/** Décalage Tailwind `bottom-5` de la barre film (1,25 rem = 20 px). */
export const FILM_BAR_BOTTOM_GAP_PX = 20;

/** Espace entre le bas des crédits Leaflet et le haut de la barre film. */
export const ATTRIBUTION_FILM_GAP_PX = 10;

/**
 * La barre du bas occupe l’espace entre les deux sidebars ouvertes.
 * Si une sidebar se range, la barre s’élargit dans le trou.
 */
export function filmBarInsets({
  sidebarOpen = true,
  toolsOpen = true,
  width = SIDEBAR_WIDTH_PX,
  gutter = 8,
} = {}) {
  return {
    left: sidebarOpen ? width : gutter,
    right: toolsOpen ? width : gutter,
  };
}

/** Hauteur occupée par la barre film (contenu), selon ses lignes — premier rendu seulement. */
export const FILM_BAR_HEIGHT_PX = Object.freeze({
  hidden: 0,
  compact: 96, // Titre + horloge + piste + une rangée de commandes
  controls: 96, // même rangée compacte en Simulation (pilules text-[9px])
  narrow: 168, // même contenu, commandes sur deux lignes (largeur < 600)
});

/**
 * Largeur d’écran connue. Un argument gagne. Sinon le viewport du navigateur.
 * Les tests Node n’ont pas de `window` : on reste sur le bureau.
 */
export function readViewportWidth(explicit) {
  if (explicit != null && explicit !== "") {
    const given = Number(explicit);
    if (Number.isFinite(given) && given > 0) return given;
  }
  if (typeof window !== "undefined" && Number.isFinite(window.innerWidth) && window.innerWidth > 0) {
    return window.innerWidth;
  }
  return null;
}

/** Vrai seulement pour une largeur connue, strictement sous 600 px. */
export function isNarrowLayout(viewportWidth) {
  const width = readViewportWidth(viewportWidth);
  return width != null && width <= NARROW_LAYOUT_MAX_PX;
}

/**
 * Cadre de la barre du film. Au bureau, identique à `filmBarInsets` (entre
 * les panneaux). Sous 600 px la barre passe sous le tiroir, sur toute la
 * largeur : elle ne se coince pas dans la colonne restante. Les crédits
 * Leaflet continuent d’utiliser `filmBarInsets` (colonne visible).
 */
export function drawerFilmBarInsets({
  sidebarOpen = true,
  toolsOpen = true,
  width = SIDEBAR_WIDTH_PX,
  gutter = 8,
  viewportWidth,
} = {}) {
  if (isNarrowLayout(viewportWidth)) return { left: gutter, right: gutter };
  return filmBarInsets({ sidebarOpen, toolsOpen, width, gutter });
}

/** `left` / `right` de la barre, en pixels. Au bureau : le tiroir. Sous 600 : la gouttière. */
export function filmBarEdgeStyle(options) {
  const box = drawerFilmBarInsets(options);
  return { left: `${box.left}px`, right: `${box.right}px` };
}

/**
 * Espace réel du bas de la carte jusqu’au haut de la barre film (ou du
 * bouton « Afficher »). Inclut le `bottom-5` : c’est cette mesure, pas la
 * constante 96, qui positionne les crédits.
 */
export function measureFilmBarOccupiedPx(el, viewportBottom) {
  if (!el || typeof el.getBoundingClientRect !== "function") return 0;
  const top = Number(el.getBoundingClientRect().top);
  if (!Number.isFinite(top)) return 0;
  let bottom = Number(viewportBottom);
  if (!Number.isFinite(bottom)) {
    const root = typeof el.closest === "function" ? el.closest("[data-testid='sim-root']") : null;
    bottom = root
      ? root.getBoundingClientRect().bottom
      : Number(globalThis.innerHeight) || 0;
  }
  return Math.max(0, Math.round(bottom - top));
}

/**
 * Variables CSS posées sur la racine : les crédits Leaflet (bas droite)
 * restent dans la carte visible — à gauche du panneau Outils, juste au-dessus
 * de la barre film (mesure + 10 px), pas sous un panneau translucide.
 */
export function mapInsetVars({
  sidebarOpen = true,
  toolsOpen = true,
  filmBarVisible = true,
  filmBarControls = false,
  filmBarMeasuredPx = null,
  viewportWidth,
} = {}) {
  const insets = filmBarInsets({ sidebarOpen, toolsOpen });
  const narrow = isNarrowLayout(viewportWidth);
  const bar = drawerFilmBarInsets({ sidebarOpen, toolsOpen, viewportWidth });
  let bottom = FILM_BAR_HEIGHT_PX.hidden;
  if (filmBarVisible) {
    const fallbackBase = narrow
      ? FILM_BAR_HEIGHT_PX.narrow
      : (filmBarControls ? FILM_BAR_HEIGHT_PX.controls : FILM_BAR_HEIGHT_PX.compact);
    const fallback = fallbackBase + FILM_BAR_BOTTOM_GAP_PX;
    const occupied = Number.isFinite(filmBarMeasuredPx) ? filmBarMeasuredPx : fallback;
    bottom = occupied + ATTRIBUTION_FILM_GAP_PX;
  }
  return {
    "--sidebar-width": `${SIDEBAR_WIDTH_PX}px`,
    "--sim-inset-left": `${insets.left}px`,
    "--sim-inset-right": `${toolsOpen ? insets.right : 0}px`,
    "--sim-inset-bottom": `${bottom}px`,
    "--film-bar-left": `${bar.left}px`,
    "--film-bar-right": `${bar.right}px`,
  };
}
