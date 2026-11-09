import { describe, expect, it } from "vitest";
import i18n from "../i18n";
import type { ScheduleResponse } from "../api/types";
import { googleMapsLinkLabel, looksLikeRawMilestoneId, marinaDisplayName, milestoneDisplayName } from "./displayLabels";

const schedule: ScheduleResponse = {
  export: {
    escales: [
      { milestone_id: "dep-la-rochelle", name: "La Rochelle", arrival_iso: "2026-11-12T08:00:00Z" },
      { milestone_id: "dep-ajaccio-corse", name: "Ajaccio (Corse)", arrival_iso: "2026-11-28T22:02:54Z" },
    ],
  },
};

describe("milestoneDisplayName", () => {
  const t = i18n.getFixedT("en");

  it("returns schedule names instead of dep-* slugs", () => {
    expect(milestoneDisplayName("dep-ajaccio-corse", schedule, [], t)).toBe("Ajaccio (Corse)");
  });

  it("falls back to a neutral label for unknown slugs", () => {
    expect(milestoneDisplayName("dep-unknown-port", null, [], t)).toBe("Stop");
  });

  it("detects raw ids", () => {
    expect(looksLikeRawMilestoneId("way/123")).toBe(true);
    expect(looksLikeRawMilestoneId("dep-la-rochelle")).toBe(true);
    expect(looksLikeRawMilestoneId("La Rochelle")).toBe(false);
  });
});

describe("marinaDisplayName", () => {
  const t = i18n.getFixedT("fr");

  it("never surfaces osm way ids as the visible title", () => {
    expect(marinaDisplayName({ osm_id: "way/991", id: "way/991" }, t)).toBe("Sans nom");
  });
});

describe("googleMapsLinkLabel", () => {
  const t = i18n.getFixedT("en");

  it("uses the place title from a /place/ URL", () => {
    const label = googleMapsLinkLabel(
      "https://www.google.com/maps/place/Port+des+Minimes/@46.14,-1.16,17z",
      t,
    );
    expect(label).toBe("Port des Minimes");
  });
});
