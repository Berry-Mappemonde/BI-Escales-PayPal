import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildBerryLegs,
  isAirLegNames,
  isAirSegment,
  isLandLegNames,
  isNonMaritimeLeg,
  legKind,
  nmToRoundedKm,
  officialAirRouteStyles,
  officialRouteLineStyle,
  isSideLegNames,
  isSideSegment,
  SIDE_ROUTE_COLOR,
  NM_TO_KM,
  orientCoords,
} from "./berryLegs.js";

describe("berryLegs", () => {
  it("skips Marigot / Halifax and inserts Marigot→Cayenne", () => {
    const pts = [
      { name: "Gustavia (Saint-Barthélemy)", lat: 1, lon: 1 },
      { name: "Marigot (Saint-Martin)", lat: 2, lon: 2 },
      { name: "Cayenne (Guyane)", lat: 3, lon: 3 },
      { name: "Halifax (Nouvelle-Écosse)", lat: 4, lon: 4 },
      { name: "Saint-Pierre (Saint-Pierre-et-Miquelon)", lat: 5, lon: 5 },
      { name: "Papeete (Polynésie française)", lat: 6, lon: 6 },
    ];
    const legs = buildBerryLegs(pts);
    const keys = legs.map((l) => `${l.from.name}|${l.to.name}`);
    assert.ok(keys.includes("Marigot (Saint-Martin)|Cayenne (Guyane)"));
    assert.ok(keys.includes("Cayenne (Guyane)|Papeete (Polynésie française)"));
    assert.ok(!keys.includes("Marigot (Saint-Martin)|Cayenne (Guyane)".replace("Cayenne", "Halifax")));
    assert.ok(!keys.some((k) => k.startsWith("Marigot (Saint-Martin)|Cayenne") === false && k.startsWith("Marigot")));
  });

  it("marque overland Saint-Maur ↔ La Rochelle", () => {
    assert.equal(isNonMaritimeLeg("Saint-Maur (Berry, Indre)", "La Rochelle"), true);
    assert.equal(isLandLegNames("Saint-Maur (Berry)", "La Rochelle"), true);
    assert.equal(isLandLegNames("Saint-Maur (Indre)", "La Rochelle"), true);
    assert.equal(isLandLegNames("La Rochelle", "Saint-Maur (Berry)"), true);
    assert.equal(isNonMaritimeLeg("La Rochelle", "Ajaccio (Corse)"), false);
    assert.equal(isLandLegNames("Saint-Maur", "La Rochelle"), true);
    assert.equal(isLandLegNames("La Rochelle", "Ajaccio (Corse)"), false);
    assert.equal(nmToRoundedKm(122), Math.round(122 * NM_TO_KM));
  });

  it("marque avion seulement Cayenne ↔ Halifax ; Halifax ↔ Saint-Pierre est mer", () => {
    assert.equal(isAirLegNames("Cayenne (Guyane)", "Halifax (Nouvelle-Écosse)"), true);
    assert.equal(isAirLegNames("Halifax (Nouvelle-Écosse)", "Cayenne (Guyane)"), true);
    assert.equal(isAirLegNames("Halifax (Nouvelle-Écosse)", "Saint-Pierre (Saint-Pierre-et-Miquelon)"), false);
    assert.equal(isAirLegNames("Saint-Pierre (Saint-Pierre-et-Miquelon)", "Halifax (Nouvelle-Écosse)"), false);
    assert.equal(isAirLegNames("Cayenne (Guyane)", "Saint-Pierre (Saint-Pierre-et-Miquelon)"), false);
    assert.equal(isAirLegNames("Cayenne (Guyane)", "Papeete (Polynésie française)"), false);
    assert.equal(isAirLegNames("La Rochelle", "Ajaccio (Corse)"), false);
    assert.equal(legKind("Cayenne (Guyane)", "Halifax (Nouvelle-Écosse)"), "air");
    assert.equal(legKind("Halifax (Nouvelle-Écosse)", "Cayenne (Guyane)"), "air");
    assert.equal(legKind("Halifax (Nouvelle-Écosse)", "Saint-Pierre (Saint-Pierre-et-Miquelon)"), "sea");
    assert.equal(legKind("Saint-Pierre (Saint-Pierre-et-Miquelon)", "Halifax (Nouvelle-Écosse)"), "sea");
    assert.equal(legKind("Saint-Maur", "La Rochelle"), "land");
    assert.equal(legKind("La Rochelle", "Ajaccio (Corse)"), "sea");
    const air = officialRouteLineStyle({
      from: { name: "Cayenne (Guyane)" },
      to: { name: "Halifax (Nouvelle-Écosse)" },
      coords: [[-52.3, 4.9], [-63.6, 44.6]],
    });
    assert.equal(air.color, "#111111");
    assert.equal(air.dash, "7 7");
    assert.equal(air.interactive, false);
    assert.equal(isSideLegNames("Halifax (Nouvelle-Écosse)", "Saint-Pierre (Saint-Pierre-et-Miquelon)"), true);
    assert.equal(isSideSegment({
      from: { name: "Halifax (Nouvelle-Écosse)" },
      to: { name: "Saint-Pierre (Saint-Pierre-et-Miquelon)" },
    }), true);
    const seaOut = officialRouteLineStyle({
      from: { name: "Halifax (Nouvelle-Écosse)" },
      to: { name: "Saint-Pierre (Saint-Pierre-et-Miquelon)" },
      coords: [[-63.6, 44.6], [-56.2, 46.8]],
    });
    assert.equal(seaOut.color, SIDE_ROUTE_COLOR);
    assert.equal(seaOut.weight, 2.5);
    assert.equal(seaOut.dash, null);
    const seaBack = officialRouteLineStyle({
      from: { name: "Saint-Pierre (Saint-Pierre-et-Miquelon)" },
      to: { name: "Halifax (Nouvelle-Écosse)" },
    });
    assert.equal(seaBack.color, SIDE_ROUTE_COLOR);
    const layered = officialAirRouteStyles({ air: true });
    assert.equal(layered.length, 2);
    assert.equal(layered[0].color, "#e5e7eb");
    assert.equal(layered[1].color, "#111111");
    assert.equal(isAirSegment({ air: true, coords: [[0, 0], [1, 1]] }), true);
    assert.equal(isAirSegment({
      from: { name: "Halifax (Nouvelle-Écosse)" },
      to: { name: "Saint-Pierre (Saint-Pierre-et-Miquelon)" },
    }), false);
    assert.equal(officialRouteLineStyle({ nonMaritime: true })?.color, "orange");
    assert.equal(officialRouteLineStyle({ coords: [[0, 0], [1, 1]] }), null);
  });

  it("oriente A→B", () => {
    const from = { lat: 0, lon: 0 };
    const to = { lat: 1, lon: 1 };
    const rev = orientCoords([[1, 1], [0, 0]], from, to);
    assert.deepEqual(rev[0], [0, 0]);
  });
});
