import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  catalogPointRadiusPx,
  ficheFromHit,
  pickCatalogHit,
} from "./catalogHit.js";

const project = (lon, lat) => ({ x: lon * 10, y: lat * 10 });

const point = (lon, lat, properties) => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [lon, lat] },
  properties,
});

const square = (west, south, east, north, properties) => ({
  type: "Feature",
  geometry: {
    type: "Polygon",
    coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
  },
  properties,
});

describe("catalog click", () => {
  it("opens the point card inside the click radius and ignores a far click", () => {
    const feature = point(-5.2, 44.4, {
      name: "Port des Minimes",
      website: "https://example.org/marina",
    });
    const radiusPx = catalogPointRadiusPx(8, 1);
    const entries = [{ feature, kind: "marina", z: 400, order: 1, radiusPx }];
    const hit = pickCatalogHit(entries, 44.4, -5.2, project);
    const fiche = ficheFromHit(hit, 44.4, -5.2);
    assert.equal(fiche.kind, "marina");
    assert.equal(fiche.props.website, "https://example.org/marina");
    assert.equal(pickCatalogHit(entries, 50, 10, project), null);
  });

  it("keeps a marina outside an MPA when the MPA canvas sits above it", () => {
    const marina = point(-5.2, 44.4, { name: "Port des Minimes", website: "https://example.org/marina" });
    const amp = square(-2.2, 45.6, -0.6, 46.8, {
      name: "Pertuis Charentais",
      manager_url: "https://example.org/manager",
      visit_url: "https://example.org/visit",
    });
    const entries = [
      { feature: marina, kind: "marina", z: 400, order: 1, radiusPx: catalogPointRadiusPx(8, 1) },
      { feature: amp, kind: "amp", z: 420, order: 2, radiusPx: 8 },
    ];
    const outside = ficheFromHit(pickCatalogHit(entries, 44.4, -5.2, project), 44.4, -5.2);
    assert.equal(outside.kind, "marina");
    assert.equal(outside.props.website, "https://example.org/marina");
    const inside = ficheFromHit(pickCatalogHit(entries, 46.2, -1.4, project), 46.2, -1.4);
    assert.equal(inside.kind, "amp");
    assert.notEqual(inside.props.manager_url, inside.props.visit_url);
    assert.equal(inside.props.manager_url, "https://example.org/manager");
    assert.equal(inside.props.visit_url, "https://example.org/visit");
  });

  it("opens a card for a clustered point (its count, not one point's link)", () => {
    const feature = point(-1.5, 46.2, {
      name: "4 points regroupés",
      title: "Sentinelle",
      url: "https://example.org/cluster",
      clusterCount: 4,
    });
    const hit = pickCatalogHit(
      [{ feature, kind: "project", z: 400, order: 0, radiusPx: catalogPointRadiusPx(7, 4) }],
      46.2,
      -1.5,
      project,
    );
    const fiche = ficheFromHit(hit, 46.2, -1.5);
    assert.equal(fiche.kind, "project");
    assert.equal(fiche.props.clusterCount, 4);
    // The card itself never shows a link for a group (LayerFichePopup).
    const popup = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "components", "LayerFichePopup.jsx"), "utf8");
    assert.match(popup, /if \(clusterCount > 1\) \{[\s\S]{0,200}?extra = <div[^>]*>\{t\("layerFicheClusterZoom"\)\}/);
  });

  it("lets a later point in the same pane win over an earlier one", () => {
    const first = point(0, 0, { name: "A", url: "https://example.org/a" });
    const second = point(0, 0, { name: "B", url: "https://example.org/b" });
    const radiusPx = catalogPointRadiusPx(6, 1);
    const hit = pickCatalogHit([
      { feature: first, kind: "project", z: 400, order: 1, radiusPx },
      { feature: second, kind: "marina", z: 400, order: 2, radiusPx },
    ], 0, 0, project);
    assert.equal(ficheFromHit(hit, 0, 0).props.name, "B");
  });
});

describe("catalog polygon holes", () => {
  it("a click in a hole of an MPA is not in the MPA", () => {
    const donut = {
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [
          [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
          [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
        ],
      },
      properties: { name: "Anneau" },
    };
    const entries = [{ feature: donut, kind: "amp", z: 600, order: 0, radiusPx: 8 }];
    assert.equal(pickCatalogHit(entries, 5, 5, project), null);
    assert.equal(ficheFromHit(pickCatalogHit(entries, 2, 2, project), 2, 2).props.name, "Anneau");
    const multi = { ...donut, geometry: { type: "MultiPolygon", coordinates: [donut.geometry.coordinates] } };
    assert.equal(pickCatalogHit([{ ...entries[0], feature: multi }], 5, 5, project), null);
  });
});
