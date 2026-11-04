// Tracé à travers l'antiméridien : la carte garde la route dépliée, mais le
// panneau et l'export GeoJSON / KML donnent des longitudes dans [−180, 180].
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { dismissNotForNav, enterTracer, showLeftPanel, showRightPanel } from "../helpers.js";

const POINTS = [
  { lat: -18.1, lon: 178.4, name: "Suva" },
  { lat: -16.0, lon: 195.0, name: "Mer" },
  { lat: -17.5, lon: 214.02, name: "Papeete" },
];

async function stubRoute(page) {
  await page.route("**/route?*", async (route) => {
    const url = new URL(route.request().url());
    const slat = Number(url.searchParams.get("start_lat"));
    const slon = Number(url.searchParams.get("start_lon"));
    const elat = Number(url.searchParams.get("end_lat"));
    const elon = Number(url.searchParams.get("end_lon"));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        type: "Feature",
        geometry: { type: "LineString", coordinates: [[slon, slat], [elon, elat]] },
        properties: { length: 1852, units: "km" },
      }),
    });
  });
}

function lonsOf(geo) {
  return geo.features.flatMap((f) => {
    const g = f.geometry;
    if (g.type === "Point") return [g.coordinates[0]];
    if (g.type === "LineString") return g.coordinates.map((c) => c[0]);
    return g.coordinates.flat().map((c) => c[0]);
  });
}

test("antiméridien : panneau et exports en [−180, 180], carte dépliée", async ({ page }) => {
  test.setTimeout(90_000);
  await stubRoute(page);
  await page.goto("/");
  await dismissNotForNav(page);
  await expect(page.getByTestId("film-bar")).toBeVisible({ timeout: 30_000 });
  await enterTracer(page);
  await page.waitForFunction(() => typeof window.__naviguideAddDrawnPoint === "function");
  for (const p of POINTS) {
    await page.evaluate((q) => window.__naviguideAddDrawnPoint(q.lat, q.lon, { name: q.name }), p);
  }
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) === 2, null, { timeout: 20_000 });

  // La carte : coordonnées dépliées, sans saut de 360°.
  const mapLons = await page.evaluate(() => window.__naviguideDrawn.coords.map((c) => c[0]));
  expect(Math.max(...mapLons)).toBeGreaterThan(180);
  for (let i = 1; i < mapLons.length; i += 1) expect(Math.abs(mapLons[i] - mapLons[i - 1])).toBeLessThan(180);

  await showLeftPanel(page);
  const panel = page.getByTestId("drawing-points");
  await expect(panel).toContainText("-145.98°");
  await expect(panel).not.toContainText("214.02");

  await showRightPanel(page);
  const exported = {};
  for (const [testId, parse] of [
    ["export-geojson", (raw) => lonsOf(JSON.parse(raw))],
    ["export-kml", (raw) => [...raw.matchAll(/(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),0/g)].map((m) => Number(m[1]))],
  ]) {
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId(testId).click()]);
    const raw = readFileSync(await download.path(), "utf8");
    const lons = parse(raw);
    expect(lons.length, testId).toBeGreaterThan(0);
    expect(lons.filter((x) => x < -180 || x > 180), testId).toEqual([]);
    expect(raw, testId).not.toContain("214.02");
    exported[testId] = raw;
  }

  // The line is cut at the antimeridian: parts that end / start on ±180 at
  // the same latitude, none of them crossing the map.
  const geo = JSON.parse(exported["export-geojson"]);
  const parts = geo.features.flatMap((f) => {
    if (f.geometry.type === "LineString") return [f.geometry.coordinates];
    if (f.geometry.type === "MultiLineString") return f.geometry.coordinates;
    return [];
  });
  expect(parts.length).toBeGreaterThanOrEqual(2);
  for (const part of parts) {
    for (let i = 1; i < part.length; i += 1) expect(Math.abs(part[i][0] - part[i - 1][0])).toBeLessThan(180);
  }
  const cuts = [];
  for (let i = 1; i < parts.length; i += 1) {
    const end = parts[i - 1].at(-1);
    const start = parts[i][0];
    if (Math.abs(end[0]) === 180 && Math.abs(start[0]) === 180) cuts.push([end, start]);
  }
  expect(cuts.length).toBe(1);
  const [[endLon, endLat], [startLon, startLat]] = cuts[0];
  expect(endLon).toBe(180);
  expect(startLon).toBe(-180);
  expect(startLat).toBeCloseTo(endLat, 6);
  const kmlLines = exported["export-kml"].match(/<LineString>/g) || [];
  expect(kmlLines.length).toBeGreaterThanOrEqual(2);

  // Re-import of that file gives the same three points, unfolded again on
  // the map, and no point added at the cut.
  await showLeftPanel(page);
  await page.getByTestId("route-import-file").setInputFiles({
    name: "antimeridien.geojson",
    mimeType: "application/geo+json",
    buffer: Buffer.from(exported["export-geojson"]),
  });
  await expect.poll(() => page.evaluate(() => window.__naviguideDrawn?.points?.length || 0), { timeout: 20_000 }).toBe(3);
  await page.waitForFunction(() => (window.__naviguideDrawn?.segments?.length || 0) === 2, null, { timeout: 20_000 });
  const back = await page.evaluate(() => ({
    points: window.__naviguideDrawn.points.map((p) => [p.lat, p.lon]),
    lons: window.__naviguideDrawn.coords.map((c) => c[0]),
  }));
  POINTS.forEach((p, i) => {
    expect(back.points[i][0]).toBeCloseTo(p.lat, 2);
    const lon = back.points[i][1];
    expect(Math.abs(lon - p.lon) < 0.01 || Math.abs(lon + 360 - p.lon) < 0.01 || Math.abs(lon - 360 - p.lon) < 0.01, `${p.name} ${lon}`).toBe(true);
  });
  for (let i = 1; i < back.lons.length; i += 1) expect(Math.abs(back.lons[i] - back.lons[i - 1])).toBeLessThan(180);
  await expect(page.getByTestId("drawing-points")).toContainText("-145.98°");
  await expect(page.getByTestId("drawing-points")).not.toContainText("214.02");
});
