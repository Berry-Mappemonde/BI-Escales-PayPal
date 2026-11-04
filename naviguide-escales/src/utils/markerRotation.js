export function normalizeMarkerBearing(bearing) {
  const raw = Number(bearing);
  if (!Number.isFinite(raw)) return 0;
  return ((raw % 360) + 360) % 360;
}

/**
 * Leaflet garde le divIcon ; seule sa variable CSS de rotation est modifiée.
 * Aucun `setIcon` n'est nécessaire pendant l'animation.
 */
export function applyMarkerRotation(marker, bearing) {
  const node = marker?.getElement?.()?.querySelector?.("[data-marker-rotatable]");
  if (!node) return false;
  const degrees = normalizeMarkerBearing(bearing);
  node.style.setProperty("--marker-bearing", `${degrees}deg`);
  node.dataset.heading = String(degrees);
  return true;
}
