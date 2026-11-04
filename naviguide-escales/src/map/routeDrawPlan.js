/**
 * Quelle route la couche `route` dessine, et une seule à la fois :
 * le tracé en cours (drawing), SINON la route perso choisie (custom), SINON la
 * route Berry-Mappemonde (berry) — passé ET à venir. Jamais deux routes
 * superposées (revue du porteur du 14 oct., B2/B3).
 */
export function routeDrawPlan({ sceneReady, drawingMode, customRoute } = {}) {
  const visible = Boolean(sceneReady || drawingMode);
  if (!visible) return { visible: false, kind: null };
  if (drawingMode) return { visible: true, kind: "drawing" };
  if (customRoute?.features) return { visible: true, kind: "custom" };
  return { visible: true, kind: "berry" };
}
