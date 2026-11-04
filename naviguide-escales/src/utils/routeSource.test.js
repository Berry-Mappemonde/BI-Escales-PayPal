// La source de route (Berry | ma route) est indépendante du mode :
// elle survit à Tracer → Suivre → Tracer et remplace l'implicite
// `routeForView = isSuivre ? null : customRoute` (revue du 14 oct., B1).
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { resolveRouteSource, routeForSource } from "./routeSource.js";

const drawn = {
  type: "FeatureCollection",
  features: [
    { type: "Feature", geometry: { type: "LineString", coordinates: [[-1.5, 46.1], [-61.0, 15.3]] }, properties: {} },
  ],
};

describe("routeSource", () => {
  it("sans route perso, la source est Berry", () => {
    assert.equal(resolveRouteSource("berry", null), "berry");
    assert.equal(resolveRouteSource("custom", null), "berry");
    assert.equal(routeForSource("berry", drawn), null);
  });

  it("Terminer un tracé → source custom, et la vue dessine la route perso", () => {
    const source = resolveRouteSource("custom", drawn);
    assert.equal(source, "custom");
    assert.equal(routeForSource(source, drawn), drawn);
  });

  it("la source survit à Tracer → Suivre → Tracer (elle ignore le mode)", () => {
    // L'état App (routeKind, customRoute) ne bouge pas quand la vue change :
    // la même paire donne la même route dans les deux modes, à chaque passage.
    const state = { routeKind: "custom", customRoute: drawn };
    const seenRoutes = ["tracer", "suivre", "tracer"].map(() => {
      const source = resolveRouteSource(state.routeKind, state.customRoute);
      return routeForSource(source, state.customRoute);
    });
    assert.deepEqual(seenRoutes, [drawn, drawn, drawn]);
  });

  it("pilule Berry → berry ; pilule <ma route> → custom", () => {
    assert.equal(resolveRouteSource("berry", null), "berry"); // après handleRouteSwitchToBerry
    assert.equal(resolveRouteSource("custom", drawn), "custom"); // après handleRouteSwitchToCustom
  });
});
