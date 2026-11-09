import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import L from "leaflet";
import { afterEach, describe, expect, it } from "vitest";
import { computeMarkerOffsets } from "../../../../naviguide-escales/src/utils/markerOffsets.js";
import { PRODUCTION_T0_ISO } from "../voyage/departureT0.js";
import { dedupeStopsByMilestone } from "../voyage/stopsForMap.js";
import { sampleAt, voyageFromRoute } from "../voyage/loadVoyage.js";
import {
  boatMarkerAnchorOffset,
  boatOverlapsStopFlag,
  boatScreenRect,
  computeStopOffsets,
  rectSamplePoints,
  stopFlagScreenRect,
} from "./stopMarkerLayout.js";

const here = dirname(fileURLToPath(import.meta.url));

function leafProjector(width, height, bounds) {
  const el = document.createElement("div");
  el.style.width = `${width}px`;
  el.style.height = `${height}px`;
  document.body.appendChild(el);
  const map = L.map(el, { zoomSnap: 0.25, minZoom: 2, maxZoom: 12 });
  map.fitBounds(bounds, { padding: [24, 24] });
  return {
    project: (lon, lat) => {
      const point = map.latLngToLayerPoint([lat, lon]);
      return { x: point.x, y: point.y };
    },
    setZoom: (zoom) => map.setZoom(zoom),
    getZoom: () => map.getZoom(),
    destroy: () => {
      map.remove();
      el.remove();
    },
  };
}

describe("stopMarkerLayout", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("spreads coincident screen positions so each flag keeps its own hit target", () => {
    const stops = [
      { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358, flag: true, flags: ["x.png"] },
      { name: "La Rochelle", lat: 46.1541, lon: -1.167, flag: true, flags: ["y.png"] },
    ];
    const project = () => ({ x: 240, y: 180 });
    const offsets = computeMarkerOffsets(stops, project, []);
    expect(offsets[0]).not.toEqual(offsets[1]);
  });

  it("offsets the catamaran away from all flag hit boxes, including La Rochelle at default and max zoom", () => {
    const fc = JSON.parse(readFileSync(join(here, "../../public/route.geojson"), "utf8"));
    const voyage = voyageFromRoute(fc, PRODUCTION_T0_ISO);
    const sample = sampleAt(voyage.clock, new Date("2026-11-09T12:00:00.000Z"));
    const stops = dedupeStopsByMilestone(voyage.stops);
    const laRochelle = stops.find((row) => row.milestoneId === "dep-la-rochelle");
    const saintMaur = stops.find((row) => /saint-maur/i.test(row.name || ""));
    expect(laRochelle).toBeTruthy();
    expect(saintMaur).toBeTruthy();
    const boat = { lat: sample.lat, lon: sample.lon };
    const bounds = [];
    (voyage.segments || []).forEach((segment) => {
      (segment.coords || []).forEach(([lon, lat]) => bounds.push([lat, lon]));
    });
    const view = leafProjector(960, 640, bounds);

  const zoomLevels = [view.getZoom(), 12];
    for (const zoom of zoomLevels) {
      view.setZoom(zoom);
      const project = view.project;
      const offsets = computeStopOffsets(stops, voyage.segments, project);
      const lrIndex = stops.findIndex((row) => row.milestoneId === "dep-la-rochelle");
      const boatOffset = boatMarkerAnchorOffset(boat, stops, offsets, project);
      const lrOrigin = project(laRochelle.lon, laRochelle.lat);
      const boatOrigin = project(boat.lon, boat.lat);
      expect(boatOverlapsStopFlag(boatOffset, boatOrigin, lrOrigin, offsets[lrIndex])).toBe(false);

      const flagRect = stopFlagScreenRect(lrOrigin, offsets[lrIndex]);
      const boatRect = boatScreenRect(boatOrigin, boatOffset);
      const probes = rectSamplePoints(flagRect, 7);
      const boatHits = probes.filter((pt) =>
        pt.x >= boatRect.x - 4 &&
        pt.x <= boatRect.x + boatRect.w + 4 &&
        pt.y >= boatRect.y - 4 &&
        pt.y <= boatRect.y + boatRect.h + 4,
      );
      expect(boatHits).toEqual([]);
    }
    view.destroy();
  });

  it("picks a non-zero offset when the boat shares Saint-Maur coordinates", () => {
    const stops = [
      { name: "Saint-Maur (Berry, Indre)", lat: 46.8075, lon: 1.6358, flag: true, flags: ["x.png"] },
      { name: "La Rochelle", lat: 46.1541, lon: -1.167, flag: true, flags: ["y.png"] },
    ];
    const boat = { lat: 46.8075, lon: 1.6358 };
    const project = (lon, lat) => ({ x: lon * 120 + 400, y: -lat * 120 + 300 });
    const offsets = computeMarkerOffsets(stops, project, []);
    const boatOffset = boatMarkerAnchorOffset(boat, stops, offsets, project);
    expect(Math.hypot(boatOffset[0], boatOffset[1])).toBeGreaterThan(24);
    const lr = stops[1];
    const lrOrigin = project(lr.lon, lr.lat);
    const boatOrigin = project(boat.lon, boat.lat);
    expect(boatOverlapsStopFlag(boatOffset, boatOrigin, lrOrigin, offsets[1])).toBe(false);
  });
});
