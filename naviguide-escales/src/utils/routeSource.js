/**
 * La SOURCE de route affichée (Berry-Mappemonde ou ma route) est un
 * état indépendant du mode (Suivre | Tracer). Elle remplace l'implicite
 * `routeForView = isSuivre ? null : customRoute` qui forçait Berry en Suivre
 * (revue du porteur du 14 oct., B1-B4).
 */

/** "custom" seulement quand une route perso existe ET qu'elle est choisie. */
export function resolveRouteSource(routeKind, customRoute) {
  return routeKind === "custom" && customRoute ? "custom" : "berry";
}

/** La route que la vue dessine : la perso pour "custom", la Berry sinon (null). */
export function routeForSource(source, customRoute) {
  return source === "custom" ? customRoute : null;
}
