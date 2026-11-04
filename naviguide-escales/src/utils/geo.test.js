import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { flattenRoute, mapEscalesOnRoute } from "../engine/routePlayhead.js";
import { mergeEpisodeMarks } from "../engine/filmCast.js";
import { routeFromOfficial } from "./routeFromOfficial.js";
import { bearingDeg } from "../engine/routeWindProfile.js";
import {
  haversineNm,
  summarizeRoute,
  summarizeLegs,
  marksForSummary,
  featuresToSegments,
  splitAntimeridianCoords,
  unwrapLon,
  unwrapLineCoords,
  unwrapPath,
  wrapLon,
  worldCopyCoords,
  worldCopyLineCoords,
  worldCopyLngs,
  worldCopyOffsets,
  worldCopyParts,
  worldCopyPolygonCoords,
  WORLD_COPY_LON_BOUND,
  markerCopyLngs,
  stabilizeWorldLng,
  worldCopyKey,
} from "./geo.js";

/** Officiel Berry (`public/route.geojson`). */
const SAINT_MAUR = { lat: 46.8075, lon: 1.6358 };
const LA_ROCHELLE = { lat: 46.1541, lon: -1.167 };
const AJACCIO = { lat: 41.9192, lon: 8.7386 };

const OFFICIAL_ESCALES = [
  "Saint-Maur (Berry, Indre)",
  "La Rochelle",
  "Ajaccio (Corse)",
  "Fort-de-France (Martinique)",
  "Pointe-à-Pitre (Guadeloupe)",
  "Gustavia (Saint-Barthélemy)",
  "Marigot (Saint-Martin)",
  "Cayenne (Guyane)",
  "Saint-Pierre (Saint-Pierre-et-Miquelon)",
  "Papeete (Polynésie française)",
  "Mata-Utu (Wallis-et-Futuna)",
  "Nouméa (Nouvelle-Calédonie)",
  "Dzaoudzi (Mayotte)",
  "Tromelin (TAAF)",
  "Saint-Gilles (La Réunion)",
  "Europa (TAAF)",
  "La Rochelle",
];

describe("summarizeRoute", () => {
  it("counts segments and a distance > 0", () => {
    const { nm, segments } = summarizeRoute([
      { coords: [[-1.16, 46.15], [-16.15, 28.55]] },
      { coords: [[-16.15, 28.55], [-23.6, 15.1]] },
    ]);
    assert.equal(segments, 2);
    assert.ok(nm > 1000);
  });

  it("ignores LineStrings that are too short", () => {
    assert.deepEqual(summarizeRoute([{ coords: [[0, 0]] }]), { nm: 0, segments: 0 });
  });

  it("N points give N-1 segments", () => {
    const coords = [[-1.15, 46.16], [-5.66, 43.55], [-9.14, 38.72], [-10, 36]];
    assert.equal(summarizeRoute([{ coords }]).segments, coords.length - 1);
    assert.equal(summarizeRoute([
      { coords: [coords[0], coords[1]] },
      { coords: [coords[1], coords[2]] },
    ]).segments, 2);
  });
});

describe("summarizeLegs", () => {
  const landSeg = {
    coords: [[1.6358, 46.8075], [-1.167, 46.1541]],
    nonMaritime: true,
    from: { name: "Saint-Maur (Berry, Indre)" },
    to: { name: "La Rochelle" },
  };
  const seaSeg = {
    coords: [[-1.167, 46.1541], [8.7386, 41.9192]],
    nonMaritime: false,
    from: { name: "La Rochelle" },
    to: { name: "Ajaccio (Corse)" },
  };

  it("17 marques → 16 étapes, Saint-Maur → La Rochelle à terre", () => {
    const marks = OFFICIAL_ESCALES.map((name) => ({ name }));
    const out = summarizeLegs(marks, [landSeg, seaSeg]);
    assert.equal(out.legs, 16);
    assert.equal(out.escales, 17);
    assert.equal(out.land, 1);
    assert.equal(out.sea, 15);
  });

  it("route dessinée sans marques → 1 étape", () => {
    const out = summarizeLegs([], [{ coords: [[0, 0], [1, 1]], nonMaritime: false }]);
    assert.equal(out.legs, 1);
    assert.equal(out.sea, 1);
    assert.equal(out.land, 0);
    assert.equal(out.escales, 0);
  });

  it("3 points sans marques → 2 segments", () => {
    const out = summarizeLegs([], [
      { coords: [[-1.15, 46.16], [-5.66, 43.55]], nonMaritime: false },
      { coords: [[-5.66, 43.55], [-9.14, 38.72]], nonMaritime: false },
    ]);
    assert.equal(out.legs, 2);
    assert.equal(out.sea, 2);
    assert.equal(out.land, 0);
  });

  it("route perso : N points posés → N − 1 étapes, pas un compte de sommets", () => {
    // 3 points, searoute legs with intermediate vertices.
    const out = summarizeLegs([], [
      { coords: [[-1.15, 46.16], [-3, 45], [-5.66, 43.55]], nonMaritime: false },
      { coords: [[-5.66, 43.55], [-8, 42], [-9.3, 40], [-9.14, 38.72]], nonMaritime: false },
    ]);
    assert.equal(out.legs, 2);
    assert.equal(out.sea, 2);
    assert.equal(out.land, 0);
    assert.equal(out.points, 7);
  });

  it("Cayenne réinséré (HUD aérien) ne crée pas d'escale de plus", () => {
    const marks = [
      ...OFFICIAL_ESCALES.slice(0, 9).map((name) => ({ name })),
      { name: "Cayenne (Guyane)" },
      ...OFFICIAL_ESCALES.slice(9).map((name) => ({ name })),
    ];
    assert.equal(marks.length, 18);
    assert.equal(marksForSummary(marks).length, 17);
    const out = summarizeLegs(marks, [landSeg]);
    assert.equal(out.escales, 17);
    assert.equal(out.legs, 16);
  });

  it("route officielle Berry : 16 étapes (15 mer, 1 terre), 17 escales, 1224 sommets", () => {
    const raw = JSON.parse(readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "../../public/route.geojson"),
      "utf8",
    ));
    const { segments, stops } = routeFromOfficial(raw);
    const flat = flattenRoute(segments);
    const marks = mergeEpisodeMarks(mapEscalesOnRoute(stops, flat), flat, stops);
    const out = summarizeLegs(marks, segments);
    assert.equal(out.legs, 16);
    assert.equal(out.sea, 15);
    assert.equal(out.land, 1);
    assert.equal(out.escales, 17);
    assert.equal(out.points, 1224);
    assert.equal(out.waypoints, 36);
  });
});

describe("wrapLon / unwrapPath", () => {
  it("replie 236,84° (SF dépliée) dans [−180, 180]", () => {
    assert.equal(Number(wrapLon(236.84).toFixed(2)), -123.16);
    assert.ok(wrapLon(236.84) >= -180 && wrapLon(236.84) <= 180);
    assert.equal(wrapLon(-122.4), -122.4);
  });

  it("unwrapPath reste continu depuis Brisbane", () => {
    const path = unwrapPath(
      [[153.4, -27], [179, 0], [-179, 10], [-122.4, 37.7]],
      153.4,
    );
    const lons = path.map(([lon]) => lon);
    for (let i = 1; i < lons.length; i++) {
      assert.ok(Math.abs(lons[i] - lons[i - 1]) <= 180);
    }
    assert.ok(lons[lons.length - 1] > 180);
    assert.ok(path.every(([, lat]) => lat <= 50));
  });
});

describe("antimeridian geo", () => {
  it("measures the short path on both sides of 180°", () => {
    const d = haversineNm(-15, 179.5, -15, -179.5);
    assert.ok(d < 80);
    assert.ok(d > 20);
    assert.equal(unwrapLon(179.5, -179.5), 180.5);
  });

  it("splits a polyline at 180°", () => {
    const parts = splitAntimeridianCoords([[179, 0], [179.9, 0], [-179.9, 0], [-179, 0]]);
    assert.equal(parts.length, 2);
  });

  it("copies a track at ±360° so Africa stays visible from the Pacific", () => {
    const copies = worldCopyCoords([[166, -22], [45, -13]]);
    assert.equal(copies.length, 3);
    assert.equal(copies[1][0][0], 526);
    assert.equal(copies[2][0][0], -194);
    assert.equal(worldCopyParts(copies.slice(0, 1)).length, 3);
  });

  it("déplie et copie les lignes, y compris 179° → −179°", () => {
    const unwrapped = unwrapLineCoords([[170, -15], [179, -16], [-179, -17], [-170, -18]]);
    assert.deepEqual(unwrapped.map(([lon]) => lon), [170, 179, 181, 190]);
    const copies = worldCopyLineCoords(unwrapped);
    assert.ok(copies.length >= 3);
    const west = copies.find((line) => Math.abs(line[0][0] - (170 - 360)) < 1e-6);
    assert.ok(west, "copie −360°");
    assert.deepEqual(west.map(([lon]) => lon), [-190, -181, -179, -170]);
    copies.forEach((line) => {
      line.slice(1).forEach(([lon], index) => {
        assert.ok(Math.abs(lon - line[index][0]) <= 180);
      });
    });
  });

  it("une ligne dépliée sur 360° produit des copies couvrant [−540, 540]", () => {
    const line = [];
    for (let lon = -360; lon <= 0; lon += 5) line.push([lon, 12]);
    const copies = worldCopyCoords(line);
    assert.ok(worldCopyOffsets(line).includes(720), " +720° pour le côté africain à droite");
    const intervals = copies.map((copy) => {
      const lons = copy.map(([lon]) => lon);
      return [Math.min(...lons), Math.max(...lons)];
    }).sort((a, b) => a[0] - b[0]);
    let covered = -WORLD_COPY_LON_BOUND;
    for (const [start, end] of intervals) {
      if (start > covered + 1e-6) break;
      covered = Math.max(covered, end);
    }
    assert.ok(covered >= WORLD_COPY_LON_BOUND - 1e-6, `couverture jusqu'à ${covered}`);
    const east = copies.flat().filter(([lon]) => lon >= 360 && lon <= WORLD_COPY_LON_BOUND);
    assert.ok(east.length > 0, "fenêtre est [360, 540] sans point");
  });

  it("triple les points et conserve les anneaux d’un polygone Pacifique", () => {
    assert.deepEqual(worldCopyLngs(179), [179, 539, -181]);
    const copies = worldCopyPolygonCoords([[
      [170, -10], [-170, -10], [-170, 10], [170, 10], [170, -10],
    ]]);
    assert.equal(copies.length, 3);
    assert.deepEqual(copies[0][0].map(([lon]) => lon), [170, 190, 190, 170, 170]);
    assert.deepEqual(copies[1][0].map(([lon]) => lon), [530, 550, 550, 530, 530]);
  });
});

describe("copies monde stables", () => {
  it("clé de copie ancrée sur wrap(lon)", () => {
    assert.equal(worldCopyKey(-176.2036, -176.2036), 0);
    assert.equal(worldCopyKey(-176.2036, 183.7964), 1);
    assert.equal(worldCopyKey(166.4572, 166.4572), 0);
    assert.equal(worldCopyKey(166.4572, -193.5428), -1);
  });

  it("Wallis : dézoom vers le centre monde ne change pas de copie", () => {
    const wallis = -176.2036;
    const atIsland = stabilizeWorldLng(wallis, -176.2, wallis);
    assert.ok(Math.abs(atIsland - wallis) < 1e-6);
    const afterOut = stabilizeWorldLng(wallis, 5, atIsland);
    assert.ok(Math.abs(afterOut - wallis) < 1e-6, `saut vers ${afterOut}`);
    assert.ok(markerCopyLngs(wallis).some((lng) => Math.abs(lng - 183.7964) < 1e-3));
  });

  it("Nouméa : dézoom vers le centre monde ne change pas de copie", () => {
    const noumea = 166.4572;
    const atIsland = stabilizeWorldLng(noumea, 166.5, noumea);
    const afterOut = stabilizeWorldLng(noumea, 5, atIsland);
    assert.ok(Math.abs(afterOut - noumea) < 1e-6, `saut vers ${afterOut}`);
  });
});

describe("Orthodromie et cardinaux", () => {
  it("Saint-Maur → La Rochelle ≈ 122 nm ± 5 (haversine ; le plan visait 190)", () => {
    const nm = haversineNm(SAINT_MAUR.lat, SAINT_MAUR.lon, LA_ROCHELLE.lat, LA_ROCHELLE.lon);
    assert.ok(Math.abs(nm - 122.3) <= 5, `orthodromie ${nm} nm`);
  });

  it("La Rochelle → Ajaccio ≈ 497 nm (ordre de grandeur Méditerranée)", () => {
    const nm = haversineNm(LA_ROCHELLE.lat, LA_ROCHELLE.lon, AJACCIO.lat, AJACCIO.lon);
    assert.ok(nm > 450 && nm < 550, `orthodromie ${nm} nm`);
  });

  it("cardinaux du cap : N 0°, E 90°, S 180°, O 270°", () => {
    const n = bearingDeg({ lat: 0, lon: 0 }, { lat: 1, lon: 0 });
    const e = bearingDeg({ lat: 0, lon: 0 }, { lat: 0, lon: 1 });
    const s = bearingDeg({ lat: 0, lon: 0 }, { lat: -1, lon: 0 });
    const w = bearingDeg({ lat: 0, lon: 0 }, { lat: 0, lon: -1 });
    assert.ok(Math.abs(n - 0) < 1, `N ${n}`);
    assert.ok(Math.abs(e - 90) < 1, `E ${e}`);
    assert.ok(Math.abs(s - 180) < 1, `S ${s}`);
    assert.ok(Math.abs(w - 270) < 1, `O ${w}`);
  });

  it("Saint-Maur → La Rochelle : cap OSO (~252°)", () => {
    const brg = bearingDeg(SAINT_MAUR, LA_ROCHELLE);
    assert.ok(brg > 240 && brg < 270, `cap ${brg}`);
  });
});

describe("featuresToSegments", () => {
  it("extracts LineStrings from a FeatureCollection", () => {
    const segs = featuresToSegments({
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: { type: "Point", coordinates: [0, 0] } },
        { type: "Feature", geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } },
      ],
    });
    assert.equal(segs.length, 1);
    assert.equal(haversineNm(0, 0, 1, 1) > 0, true);
  });
});
