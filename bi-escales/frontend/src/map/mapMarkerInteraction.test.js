import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { PRODUCTION_T0_ISO } from "../voyage/departureT0.js";
import { resolveBoatStop } from "../voyage/boatStop.js";
import { sampleAt, voyageFromRoute } from "../voyage/loadVoyage.js";
import { dedupeStopsByMilestone } from "../voyage/stopsForMap.js";

const here = dirname(fileURLToPath(import.meta.url));

describe("map marker selection helpers", () => {
  const fc = JSON.parse(readFileSync(join(here, "../../public/route.geojson"), "utf8"));
  const voyage = voyageFromRoute(fc, PRODUCTION_T0_ISO);
  const sample = sampleAt(voyage.clock, new Date("2026-11-09T12:00:00.000Z"));
  const stops = dedupeStopsByMilestone(voyage.stops);

  it("routes boat focus to Saint-Maur and La Rochelle to its own milestone before departure", () => {
    const laRochelle = stops.find((row) => row.milestoneId === "dep-la-rochelle");
    expect(resolveBoatStop(stops, sample)?.milestoneId).toBe("dep-saint-maur-berry-indre");
    expect(laRochelle?.milestoneId).toBe("dep-la-rochelle");
  });
});
