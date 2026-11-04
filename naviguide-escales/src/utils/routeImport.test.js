import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseRouteFile, ROUTE_IMPORT_MAX_POINTS } from "./routeImport.js";

const A = { name: "La Rochelle", lat: 46.157, lon: -1.151 };
const B = { name: "Gijon", lat: 43.545, lon: -5.662 };
const C = { name: "Lisbonne", lat: 38.722, lon: -9.139 };

const GEOJSON_POINTS = JSON.stringify({
  type: "FeatureCollection",
  features: [
    { type: "Feature", properties: { name: A.name }, geometry: { type: "Point", coordinates: [A.lon, A.lat] } },
    { type: "Feature", properties: { name: B.name }, geometry: { type: "Point", coordinates: [B.lon, B.lat] } },
    { type: "Feature", properties: { name: C.name }, geometry: { type: "Point", coordinates: [C.lon, C.lat] } },
  ],
});

const GEOJSON_LINE = JSON.stringify({
  type: "Feature",
  properties: { name: "Atlantique" },
  geometry: { type: "LineString", coordinates: [[A.lon, A.lat], [B.lon, B.lat], [C.lon, C.lat]] },
});

const KML_POINTS = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark><name>La Rochelle</name><Point><coordinates>-1.151,46.157,0</coordinates></Point></Placemark>
    <Placemark><name>Gijon</name><Point><coordinates>-5.662,43.545,0</coordinates></Point></Placemark>
    <Placemark><name>Lisbonne</name><Point><coordinates>-9.139,38.722,0</coordinates></Point></Placemark>
  </Document>
</kml>`;

const KML_LINE = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>Atlantique</name>
    <LineString>
      <coordinates>
        -1.151,46.157,0
        -5.662,43.545,0
        -9.139,38.722,0
      </coordinates>
    </LineString>
  </Placemark>
</kml>`;

function assertABC(parsed, source) {
  assert.equal(parsed.error, undefined);
  assert.equal(parsed.source, source);
  assert.equal(parsed.points.length, 3);
  assert.equal(parsed.points[0].name, A.name);
  assert.equal(parsed.points[0].lat, A.lat);
  assert.equal(parsed.points[0].lon, A.lon);
  assert.equal(parsed.points[1].name, B.name);
  assert.equal(parsed.points[2].name, C.name);
  assert.equal(parsed.points[2].lon, C.lon);
}

describe("parseRouteFile", () => {
  it("lit une FeatureCollection de Points dans l'ordre, avec properties.name", () => {
    assertABC(parseRouteFile(GEOJSON_POINTS, "trois.geojson"), "geojson");
  });

  it("prend les sommets d'une LineString s'il n'y a pas de Point", () => {
    const parsed = parseRouteFile(GEOJSON_LINE, "ligne.json");
    assert.equal(parsed.source, "geojson");
    assert.equal(parsed.points.length, 3);
    assert.equal(parsed.points[0].name, "Atlantique");
    assert.equal(parsed.points[0].lat, A.lat);
    assert.equal(parsed.points[1].lat, B.lat);
    assert.equal(parsed.points[2].lon, C.lon);
    assert.equal(parsed.points[1].name, "Point 2");
  });

  it("ignore la LineString dès qu'il y a au moins un Point", () => {
    const parsed = parseRouteFile(JSON.stringify({
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { name: "Seul" }, geometry: { type: "Point", coordinates: [A.lon, A.lat] } },
        { type: "Feature", geometry: { type: "LineString", coordinates: [[B.lon, B.lat], [C.lon, C.lat]] } },
      ],
    }), "mix.geojson");
    assert.equal(parsed.points.length, 1);
    assert.equal(parsed.points[0].name, "Seul");
  });

  it("lit les Placemark Point KML dans l'ordre du fichier", () => {
    assertABC(parseRouteFile(KML_POINTS, "trois.kml"), "kml");
  });

  it("lit une LineString KML s'il n'y a pas de Point", () => {
    const parsed = parseRouteFile(KML_LINE, "ligne.kml");
    assert.equal(parsed.source, "kml");
    assert.equal(parsed.points.length, 3);
    assert.equal(parsed.points[0].name, "Atlantique");
    assert.equal(parsed.points[1].lat, B.lat);
    assert.equal(parsed.points[2].lon, C.lon);
  });

  it("refuse un fichier vide ou illisible", () => {
    assert.equal(parseRouteFile("", "vide.geojson").error, "empty");
    assert.equal(parseRouteFile("   ", "vide.json").error, "empty");
    assert.equal(parseRouteFile("{", "cassé.geojson").error, "invalid");
    assert.equal(parseRouteFile("bonjour", "x.kml").error, "invalid");
    assert.equal(parseRouteFile(JSON.stringify({ type: "FeatureCollection", features: [] }), "vide.geojson").error, "noPoints");
  });

  it("dédoublonne les points consécutifs à moins de 0,1 nm", () => {
    const parsed = parseRouteFile(JSON.stringify({
      type: "FeatureCollection",
      features: [
        { type: "Feature", properties: { name: "A" }, geometry: { type: "Point", coordinates: [0, 0] } },
        { type: "Feature", properties: { name: "A2" }, geometry: { type: "Point", coordinates: [0.0004, 0] } },
        { type: "Feature", properties: { name: "B" }, geometry: { type: "Point", coordinates: [1, 0] } },
      ],
    }), "dedup.geojson");
    assert.equal(parsed.points.length, 2);
    assert.equal(parsed.points[0].name, "A");
    assert.equal(parsed.points[1].name, "B");
  });

  it("accepte lat,lon dans l'ordre carte (copier-coller)", () => {
    const parsed = parseRouteFile("46.157,-1.151 43.545,-5.662", "points.txt");
    assert.equal(parsed.error, undefined);
    assert.equal(parsed.points[0].lat, 46.157);
    assert.equal(parsed.points[0].lon, -1.151);
  });

  it("tronque au-delà de 60 points", () => {
    const features = Array.from({ length: ROUTE_IMPORT_MAX_POINTS + 1 }, (_, i) => ({
      type: "Feature",
      properties: { name: `P${i + 1}` },
      geometry: { type: "Point", coordinates: [i, 0] },
    }));
    const parsed = parseRouteFile(JSON.stringify({ type: "FeatureCollection", features }), "long.geojson");
    assert.equal(parsed.points.length, 60);
    assert.equal(parsed.truncated, true);
    assert.equal(parsed.points[0].name, "P1");
    assert.equal(parsed.points[59].name, "P60");
  });
});
