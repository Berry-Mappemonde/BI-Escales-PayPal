import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import {
  buildGeoJSON,
  buildKML,
  canExportRoute,
  dashChunks,
  downloadFile,
  exportFilename,
  isEscalePoint,
  viewExportMode,
} from "./routeExport.js";

const LR = { name: "La Rochelle", lat: 46.157, lon: -1.151, country: "France", flag: true };
const GI = { name: "Gijon", lat: 43.545, lon: -5.662, country: "Espagne", flag: true };
const LX = { name: "Lisbonne", lat: 38.722, lon: -9.139, country: "Portugal", flag: true };
const CAY = { name: "Cayenne (Guyane)", lat: 4.9333, lon: -52.3533, flag: true };
const HAL = { name: "Halifax (Nouvelle-Écosse)", lat: 44.6488, lon: -63.5652, flag: true };

const seaSeg = {
  from: LR,
  to: GI,
  coords: [[LR.lon, LR.lat], [GI.lon, GI.lat]],
};
const landSeg = {
  from: { name: "Saint-Maur (Berry, Indre)" },
  to: { name: "La Rochelle" },
  nonMaritime: true,
  coords: [[1.6358, 46.8075], [-1.167, 46.1541]],
};
const airSeg = {
  from: CAY,
  to: HAL,
  air: true,
  coords: [[CAY.lon, CAY.lat], [HAL.lon, HAL.lat]],
};

function parseKml(xml) {
  if (typeof DOMParser !== "undefined") {
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    const err = doc.querySelector?.("parsererror");
    if (err) throw new Error(err.textContent);
    return doc;
  }
  const stack = [];
  const names = [];
  const re = /<(\/?)([A-Za-z][\w:]*)[^>]*?(\/?)>/g;
  let m;
  while ((m = re.exec(xml))) {
    if (m[0].startsWith("<?") || m[0].startsWith("<!")) continue;
    const name = m[2];
    names.push(name);
    if (m[1] === "/") {
      const open = stack.pop();
      assert.equal(open, name, `KML mal formé : ${open} fermé par ${name}`);
    } else if (!m[3]) {
      stack.push(name);
    }
  }
  assert.equal(stack.length, 0, `KML mal formé : ouvert ${stack.join(", ")}`);
  return {
    getElementsByTagName(tag) {
      const count = names.filter((n) => n === tag).length;
      return { length: count };
    },
    querySelector() { return null; },
  };
}

describe("routeExport", () => {
  it("viewExportMode : Suivre / Tracer / Simulation", () => {
    assert.equal(viewExportMode(true, false), "tracer");
    assert.equal(viewExportMode(true, true), "tracer");
    assert.equal(viewExportMode(false, true), "suivre");
    assert.equal(viewExportMode(false, false), "simulation");
  });

  it("nom naviguide-<mode>-<AAAA-MM-JJ>", () => {
    const when = new Date(2026, 8, 22);
    assert.equal(exportFilename("suivre", "geojson", when), "naviguide-suivre-2026-09-22.geojson");
    assert.equal(exportFilename("tracer", "kml", when), "naviguide-tracer-2026-09-22.kml");
    assert.equal(exportFilename("simulation", ".geojson", when), "naviguide-simulation-2026-09-22.geojson");
    assert.equal(exportFilename("follow", "kml", when), "naviguide-suivre-2026-09-22.kml");
    assert.equal(exportFilename("drawn", "geojson", when), "naviguide-tracer-2026-09-22.geojson");
  });

  it("GeoJSON valide : types, kind mer|terre|air, nm", () => {
    const fc = buildGeoJSON([seaSeg, landSeg, airSeg], [LR, GI, LX], "naviguide-test");
    assert.equal(fc.type, "FeatureCollection");
    const json = JSON.parse(JSON.stringify(fc));
    assert.equal(json.type, "FeatureCollection");
    const lines = json.features.filter((f) => f.geometry.type === "LineString");
    assert.equal(lines.length, 3);
    assert.equal(lines[0].properties.kind, "mer");
    assert.equal(lines[0].properties.from, "La Rochelle");
    assert.equal(lines[0].properties.to, "Gijon");
    assert.equal(typeof lines[0].properties.nm, "number");
    assert.ok(lines[0].properties.nm > 0);
    assert.equal(lines[1].properties.kind, "terre");
    assert.equal(lines[2].properties.kind, "air");
    assert.equal(lines[2].properties.from, "Cayenne (Guyane)");
    assert.deepEqual(lines[0].geometry.coordinates[0], [LR.lon, LR.lat]);
  });

  it("N escales → N Points ; intermédiaires exclus", () => {
    const mid = { name: "Point intermédiaire", lat: 41.18, lon: 8.44, flag: "", point_type: "intermediate" };
    const fc = buildGeoJSON([seaSeg], [LR, mid, GI, LX], "t");
    const pts = fc.features.filter((f) => f.geometry.type === "Point");
    assert.equal(pts.length, 3);
    assert.deepEqual(pts.map((p) => p.properties.name), ["La Rochelle", "Gijon", "Lisbonne"]);
    assert.equal(pts[0].properties.country, "France");
    assert.deepEqual(pts[0].geometry.coordinates, [LR.lon, LR.lat]);
    assert.equal(isEscalePoint(mid), false);
    assert.equal(isEscalePoint(LR), true);
  });

  it("KML bien formé (DOMParser) et jambe avion marquée", () => {
    const xml = buildKML([seaSeg, airSeg], [CAY, HAL], "naviguide-air");
    const doc = parseKml(xml);
    assert.ok(doc.getElementsByTagName("kml").length >= 1);
    assert.ok(doc.getElementsByTagName("Placemark").length >= 3);
    assert.ok(doc.getElementsByTagName("LineString").length >= 2);
    assert.ok(doc.getElementsByTagName("Point").length >= 2);
    assert.match(xml, /<value>air<\/value>/);
    assert.match(xml, /styleUrl>#air-style/);
    assert.match(xml, /Cayenne/);
    assert.match(xml, /Halifax/);
  });

  it("dashChunks produit plusieurs tirets sur une longue jambe", () => {
    const chunks = dashChunks([[CAY.lon, CAY.lat], [HAL.lon, HAL.lat]], 40, 24);
    assert.ok(chunks.length > 1, `attendu plusieurs tirets, reçu ${chunks.length}`);
    assert.ok(chunks.every((c) => c.length >= 2));
  });

  it("canExportRoute : vide → non ; ligne ou escale → oui", () => {
    assert.equal(canExportRoute([], []), false);
    assert.equal(canExportRoute([seaSeg], []), true);
    assert.equal(canExportRoute([], [LR]), true);
  });

  it("rejette une position hors bornes et échappe le XML", () => {
    const wild = {
      from: { name: "A & B <C>", lat: 46, lon: -1 },
      to: { name: "D", lat: 47, lon: -2 },
      coords: [[-1, 46], [600, 10], [-2, 47]],
    };
    const fc = buildGeoJSON([wild], [], "n");
    const line = fc.features.find((f) => f.geometry.type === "LineString");
    assert.deepEqual(line.geometry.coordinates, [[-1, 46], [-2, 47]]);
    // Copies du monde (±540°) : une longitude déroulée reste valide et revient dans [−180, 180].
    const unwrapped = { from: { name: "E", lat: 10, lon: 170 }, to: { name: "F", lat: 11, lon: -170 }, coords: [[170, 10], [190, 11]] };
    const out = buildGeoJSON([unwrapped], [], "n");
    for (const f of out.features.filter((x) => x.geometry.type !== "Point")) {
      const lines = f.geometry.type === "MultiLineString" ? f.geometry.coordinates : [f.geometry.coordinates];
      for (const l of lines) for (const [lon] of l) assert.ok(lon >= -180 && lon <= 180);
    }
    assert.ok(out.features.some((f) => f.geometry.type !== "Point"));
    const xml = buildKML([wild], [{ name: "A & B <C>", lat: 46, lon: -1, flag: true }], "n");
    assert.match(xml, /A &amp; B &lt;C&gt;/);
    assert.doesNotMatch(xml, /A & B/);
    parseKml(xml);
  });

  it("la route officielle donne un GeoJSON et un KML valides", () => {
    const fc = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../public/route.geojson"), "utf8"));
    const segments = [];
    const stops = [];
    for (const f of fc.features || []) {
      const g = f.geometry;
      const p = f.properties || {};
      if (g?.type === "LineString" && g.coordinates?.length >= 2) {
        segments.push({
          from: { name: p.from || "" },
          to: { name: p.to || "" },
          coords: g.coordinates,
          nonMaritime: p.type === "overland",
          air: p.type === "air",
        });
      } else if (g?.type === "Point") {
        stops.push({
          name: p.name || "",
          lon: g.coordinates[0],
          lat: g.coordinates[1],
          flag: p.point_type === "escale",
        });
      }
    }
    assert.equal(canExportRoute(segments, stops), true);
    const out = buildGeoJSON(segments, stops, "naviguide-suivre");
    assert.equal(out.type, "FeatureCollection");
    assert.ok(Array.isArray(out.features) && out.features.length > 0);
    for (const feature of out.features) {
      assert.equal(feature.type, "Feature");
      assert.ok(feature.geometry.type === "LineString" || feature.geometry.type === "Point");
      const coords = feature.geometry.type === "Point" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
      assert.ok(coords.length >= (feature.geometry.type === "Point" ? 1 : 2));
      for (const [lon, lat] of coords) {
        assert.equal(typeof lon, "number");
        assert.equal(typeof lat, "number");
        assert.ok(lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90);
      }
    }
    const xml = buildKML(segments, stops, "naviguide-suivre");
    const doc = parseKml(xml);
    assert.ok(doc.getElementsByTagName("kml").length >= 1);
    assert.ok(doc.getElementsByTagName("Document").length >= 1);
    assert.ok(doc.getElementsByTagName("Placemark").length >= 1);
    assert.match(xml, /<\?xml version="1\.0" encoding="UTF-8"\?>/);
  });

  it("downloadFile clique un <a download>", () => {
    const clicks = [];
    const removed = [];
    const el = { href: "", download: "", click() { clicks.push(this.download); } };
    const doc = {
      createElement: () => el,
      body: {
        appendChild() {},
        removeChild(node) { removed.push(node); },
      },
    };
    const prevURL = globalThis.URL;
    const prevBlob = globalThis.Blob;
    globalThis.Blob = class MockBlob {
      constructor(parts, opts) { this.parts = parts; this.type = opts?.type; }
    };
    globalThis.URL = {
      createObjectURL: () => "blob:mock",
      revokeObjectURL() {},
    };
    try {
      assert.equal(downloadFile("{ }", "naviguide-suivre-2026-09-22.geojson", "application/geo+json", doc), true);
      assert.deepEqual(clicks, ["naviguide-suivre-2026-09-22.geojson"]);
      assert.equal(removed.length, 1);
    } finally {
      globalThis.URL = prevURL;
      globalThis.Blob = prevBlob;
    }
  });
});
