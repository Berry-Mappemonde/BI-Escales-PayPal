import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { computeMarkerOffsets } from "../../../../naviguide-escales/src/utils/markerOffsets.js";
import { PRODUCTION_T0_ISO } from "../voyage/departureT0.js";
import { resolveBoatStop } from "../voyage/boatStop.js";
import { sampleAt, voyageFromRoute } from "../voyage/loadVoyage.js";
import { dedupeStopsByMilestone } from "../voyage/stopsForMap.js";

const here = dirname(fileURLToPath(import.meta.url));

function markerSelection(stop) {
  return stop.milestoneId;
}

describe("map marker clicks before departure", () => {
  const fc = JSON.parse(readFileSync(join(here, "../../public/route.geojson"), "utf8"));
  const voyage = voyageFromRoute(fc, PRODUCTION_T0_ISO);
  const sample = sampleAt(voyage.clock, new Date("2026-11-09T12:00:00.000Z"));
  const stops = dedupeStopsByMilestone(voyage.stops);

  it("routes Saint-Maur, La Rochelle and boat to their own cards", () => {
    const saintMaur = stops.find((row) => row.milestoneId === "dep-saint-maur-berry-indre");
    const laRochelle = stops.find((row) => row.milestoneId === "dep-la-rochelle");
    expect(markerSelection(saintMaur)).toBe("dep-saint-maur-berry-indre");
    expect(markerSelection(laRochelle)).toBe("dep-la-rochelle");
    expect(markerSelection(resolveBoatStop(stops, sample))).toBe("dep-saint-maur-berry-indre");
  });

  it("keeps stop handlers bound to the marker stop when offsets move flags apart", () => {
    const picks = stops.filter((row) => /saint-maur|rochell/i.test(row.name));
    const handlers = new Map();
    const bind = (stop) => {
      handlers.set(stop.name, () => markerSelection(stop));
    };
    picks.forEach(bind);
    const project = (lon, lat) => ({ x: lon * 10, y: lat * 10 });
    const offsets = computeMarkerOffsets(picks, project, []);
    expect(offsets[0]).not.toEqual(offsets[1]);
    expect(handlers.get("Saint-Maur (Berry, Indre)")()).toBe("dep-saint-maur-berry-indre");
    expect(handlers.get("La Rochelle")()).toBe("dep-la-rochelle");
    const locateBoat = vi.fn(() => markerSelection(resolveBoatStop(picks, sample)));
    locateBoat();
    expect(locateBoat).toHaveReturnedWith("dep-saint-maur-berry-indre");
  });
});
