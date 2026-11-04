// Route tracée : longitudes ramenées à l'affichage et à l'export, une seule
// distance pour toutes les vues, indicateur de chargement après ↶, messages.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import fr from "../i18n/fr.js";
import en from "../i18n/en.js";
import { featuresToSegments, haversineNm, legsDistanceNm, routeStats, wrapLonParts } from "./geo.js";
import { buildGeoJSON, buildKML } from "./routeExport.js";
import { buildLocalCustomBriefing } from "./customRouteBriefing.js";
import { flattenRoute } from "../engine/routePlayhead.js";
import { legsStillLoading } from "../hooks/useRouteDrawing.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(join(HERE, rel), "utf8");

// Fidji → Tahiti, dépliée : la carte voit 178 → 214,02 sans saut.
const P = [
  { name: "Suva", lat: -18.1, lon: 178.4 },
  { name: "Mer", lat: -16.0, lon: 195.0 },
  { name: "Papeete", lat: -17.5, lon: 214.02 },
];
const SEGS = [
  { coords: [[178.4, -18.1], [186.0, -17.0], [195.0, -16.0]], nm: 1098, from: P[0], to: P[1] },
  { coords: [[195.0, -16.0], [205.0, -16.6], [214.02, -17.5]], nm: 1130.4, from: P[1], to: P[2] },
];

function allLons(geometry) {
  if (geometry.type === "Point") return [geometry.coordinates[0]];
  if (geometry.type === "LineString") return geometry.coordinates.map((c) => c[0]);
  return geometry.coordinates.flat().map((c) => c[0]);
}

describe("antiméridien : longitudes dans [−180, 180] à l'export", () => {
  it("wrapLonParts coupe à ±180 avec un point au bord", () => {
    const parts = wrapLonParts([[170, -10], [190, -12], [214.02, -15]]);
    assert.equal(parts.length, 2);
    assert.deepEqual(parts[0].at(-1).map((v) => Math.round(v * 1000) / 1000), [180, -11]);
    assert.equal(parts[1][0][0], -180);
    assert.ok(Math.abs(parts[1].at(-1)[0] - -145.98) < 1e-9);
    assert.deepEqual(wrapLonParts([[10, 1], [20, 2]]), [[[10, 1], [20, 2]]]);
  });

  it("GeoJSON : aucune lon hors [−180, 180], MultiLineString au franchissement", () => {
    const fc = buildGeoJSON(SEGS, P, "t");
    const lons = fc.features.flatMap((f) => allLons(f.geometry));
    assert.ok(lons.every((x) => x >= -180 && x <= 180), JSON.stringify(lons));
    assert.ok(!JSON.stringify(fc).includes("214.02"));
    assert.equal(fc.features[0].geometry.type, "MultiLineString");
    const papeete = fc.features.find((f) => f.properties.name === "Papeete");
    assert.ok(Math.abs(papeete.geometry.coordinates[0] - -145.98) < 1e-9);
    // La distance de la jambe ne change pas.
    assert.equal(fc.features[0].properties.nm, 1098);
  });

  // No piece of line may span the globe (a jump of more than 180° in lon).
  const maxJump = (line) => Math.max(0, ...line.slice(1).map((c, i) => Math.abs(c[0] - line[i][0])));
  // searoute, Suva → Papeete: vertices exactly on 180 before the crossing.
  const SEAROUTE_FJ_PF = [[178.4263, -18.3806], [178.7, -18.4], [180, -20], [180, -20], [184.5, -21], [190, -20], [194.9996, -20.0692], [200, -20], [205.189, -18.77], [209.484027, -17.273762], [210.3, -17.4]];

  it("a vertex exactly on 180 does not draw a line across the globe", () => {
    const parts = wrapLonParts([[178.7, -20], [180, -20], [180, -20], [184.5, -21]]);
    assert.equal(parts.length, 2);
    for (const part of parts) assert.ok(maxJump(part) <= 180, JSON.stringify(parts));
    assert.equal(parts[0].at(-1)[0], 180);
    assert.equal(parts[1][0][0], -180);
    assert.equal(parts[1].at(-1)[0], -175.5);
    // The same vertices given folded (−180 then 180) stay on one side.
    const folded = wrapLonParts([[-180, -20], [180, -20], [180, -20], [-175.5, -21]]);
    for (const part of folded) assert.ok(maxJump(part) <= 180, JSON.stringify(folded));
  });

  it("real searoute Fiji → Tahiti: GeoJSON and KML never span the globe", () => {
    const parts = wrapLonParts(SEAROUTE_FJ_PF);
    assert.equal(parts.length, 2);
    for (const part of parts) assert.ok(maxJump(part) <= 180, JSON.stringify(parts));
    const points = [
      { name: "Suva", lat: -18.38, lon: 178.4263 },
      { name: "Papeete", lat: -17.4, lon: 210.3 },
    ];
    const segs = [{ coords: SEAROUTE_FJ_PF, nm: 1730, from: points[0], to: points[1] }];
    const fc = buildGeoJSON(segs, points, "t");
    const line = fc.features.find((f) => f.geometry.type !== "Point").geometry;
    assert.equal(line.type, "MultiLineString");
    for (const part of line.coordinates) assert.ok(maxJump(part) <= 180, JSON.stringify(line.coordinates));
    const kml = buildKML(segs, points, "t");
    const lines = [...kml.matchAll(/<LineString>[\s\S]*?<coordinates>([\s\S]*?)<\/coordinates>/g)]
      .map((m) => m[1].trim().split(/\s+/).map((c) => c.split(",").map(Number)));
    assert.ok(lines.length >= 2);
    for (const l of lines) assert.ok(maxJump(l) <= 180, JSON.stringify(l));
  });

  it("KML : aucune lon hors [−180, 180]", () => {
    const kml = buildKML(SEGS, P, "t");
    const lons = [...kml.matchAll(/(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),0/g)].map((m) => Number(m[1]));
    assert.ok(lons.length > 0);
    assert.ok(lons.every((x) => x >= -180 && x <= 180), JSON.stringify(lons));
  });

  it("briefing local et listes de points affichent la lon ramenée", () => {
    const fc = {
      type: "FeatureCollection",
      features: [
        ...SEGS.map((s) => ({ type: "Feature", properties: { nm: s.nm }, geometry: { type: "LineString", coordinates: s.coords } })),
        ...P.map((p) => ({ type: "Feature", properties: { name: p.name }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } })),
      ],
    };
    const text = buildLocalCustomBriefing(fc, "fr").executive_briefing;
    assert.match(text, /Papeete \(17\.50°S, 145\.98°W\)/);
    assert.ok(!text.includes("214"));
    for (const rel of ["../components/Sidebar.jsx", "../components/ToolsSidebar.jsx"]) {
      assert.match(read(rel), /\{wrapLon\(p\.lon\)\.toFixed\(2\)\}°/, rel);
    }
    assert.match(read("../map/MapScene.jsx"), /wrapLon\(event\.latlng\.lng\)\.toFixed\(6\)/);
  });

  it("le tracé carte garde la forme dépliée", () => {
    const src = read("../hooks/useRouteDrawing.js");
    assert.match(src, /coords = unwrapPath\(coords, from\.lon\)/);
  });
});

describe("une seule distance pour toutes les vues", () => {
  it("panneau de tracé, Expédition, export, briefing et tête de lecture concordent", () => {
    const geom = SEGS[0].coords.slice(1).reduce((nm, c, i) => nm + haversineNm(SEGS[0].coords[i][1], SEGS[0].coords[i][0], c[1], c[0]), 0);
    assert.ok(Math.abs(geom - 1098) > 50, "la géométrie seule donnerait une autre distance");
    const drawingBox = Math.round(legsDistanceNm(SEGS));
    const expedition = Math.round(routeStats(SEGS).nm);
    const exported = Math.round(buildGeoJSON(SEGS, P).features.reduce((nm, f) => nm + (f.properties.nm || 0), 0));
    const flat = flattenRoute(SEGS);
    const playhead = Math.round(flat.totalNm);
    const fc = {
      type: "FeatureCollection",
      features: [
        ...SEGS.map((s) => ({ type: "Feature", properties: { nm: s.nm }, geometry: { type: "LineString", coordinates: s.coords } })),
        ...P.map((p) => ({ type: "Feature", properties: { name: p.name }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } })),
      ],
    };
    const briefing = Number(buildLocalCustomBriefing(fc, "en").summary.match(/about (\d+) NM/)[1]);
    const viaFeatures = Math.round(routeStats(featuresToSegments(fc)).nm);
    assert.deepEqual(
      { expedition, exported, playhead, briefing, viaFeatures },
      { expedition: drawingBox, exported: drawingBox, playhead: drawingBox, briefing: drawingBox, viaFeatures: drawingBox },
    );
    // Premier segment (carte Étape / légende) : la longueur de la jambe.
    const end0 = flat.points.find((p) => Math.abs(p.lon - 195) < 1e-9);
    assert.equal(Math.round(end0.cumNm), 1098);
    assert.equal(routeStats(SEGS).segments, 4);
    assert.match(read("../App.jsx"), /routeStats\(statsSegs\)/);
  });

  it("une route sans longueur de jambe garde la distance géométrique", () => {
    const plain = SEGS.map(({ nm: _nm, ...rest }) => rest);
    assert.equal(Math.round(flattenRoute(plain).totalNm), Math.round(legsDistanceNm(plain)));
  });
});

describe("tracé : ↶ et messages", () => {
  it("↶ ne coupe pas l'indicateur si une autre jambe calcule", () => {
    // Jambes 0 et 2 en cours, 3 points restent après ↶ (dernière jambe : 1).
    assert.equal(legsStillLoading(new Map([[0, 1], [2, 1]]), 3), true);
    assert.equal(legsStillLoading(new Map([[2, 1]]), 3), false);
    assert.equal(legsStillLoading(new Map(), 5), false);
    assert.doesNotMatch(read("../hooks/useRouteDrawing.js").split("const undo = useCallback")[1].split("const redo")[0], /setDrawingLoading\(false\)/);
  });

  it("point sur terre refusé et limite atteinte : message FR / EN visible sous la pilule", () => {
    assert.equal(fr.pointOnLand, "Point sur terre : non ajouté");
    assert.equal(en.pointOnLand, "Point on land: not added");
    assert.ok(fr.drawPointLimitReached.includes("{max}") && en.drawPointLimitReached.includes("{max}"));
    const app = read("../App.jsx");
    assert.match(app, /"drawPointLimitReached"/);
    assert.match(app, /role="status"/);
    assert.match(app, /drawNotice && !drawingMode/);
  });

  it("le commentaire de summarizeRoute est au-dessus de summarizeRoute", () => {
    const geo = read("./geo.js");
    assert.match(geo, /Distance nautique \+ nombre de segments[^]*?\*\/\nexport function summarizeRoute/);
    assert.doesNotMatch(geo, /`segments` : \[\{ coords: \[\[lon, lat\], \.\.\.\] \}\]\n \*\/\n\/\*\*/);
  });
});
