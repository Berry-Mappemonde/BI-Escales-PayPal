import { describe, expect, it } from "vitest";
import {
  applyMarinaPlacePolicy,
  evaluateGooglePlaceLink,
  isGooglePlaceUrl,
  summarizePlaceSafety,
} from "./marinaPlaceLink.js";
import { marinasToFeatures } from "./marinasToFeatures.js";

const BAS_DU_FORT = {
  name: "Marina de Bas-du-Fort",
  lat: 16.2203478,
  lon: -61.5297219,
  maps_url:
    "https://www.google.com/maps/place/Auto+%C3%89cole+de+la+Pointe-%C3%A0-Pitre/@16.2510,-61.5480,17z",
};

describe("marinaPlaceLink", () => {
  it("rejects Bas-du-Fort boat-school plural place name", () => {
    const ev = evaluateGooglePlaceLink({
      name: "Marina de Bas-du-Fort",
      lat: 16.2203478,
      lon: -61.5297219,
      maps_url:
        "https://www.google.com/maps/place/Bateaux+Ecoles+De+Guadeloupe+Marina+Bas+Du+Fort/@16.2510,-61.5480,17z",
    });
    expect(ev.safePlace).toBe(false);
    expect(ev.rejectedReason).toBe("suspicious_name");
  });

  it("rejects Bas-du-Fort driving-school place and keeps search link", () => {
    const ev = evaluateGooglePlaceLink(BAS_DU_FORT);
    expect(ev.safePlace).toBe(false);
    expect(ev.rejectedReason).toBe("suspicious_name");
    expect(ev.mapsLink).toContain("/maps/search/");
    expect(ev.mapsLink).not.toContain("/maps/place/");
  });

  it("accepts a nearby marina-named place within 1 km", () => {
    const ev = evaluateGooglePlaceLink({
      name: "Port des Minimes",
      lat: 46.1467598,
      lon: -1.1660647,
      maps_url:
        "https://www.google.com/maps/place/Port+des+Minimes/@46.14680,-1.16610,17z",
    });
    expect(ev.safePlace).toBe(true);
    expect(isGooglePlaceUrl(ev.mapsLink)).toBe(true);
  });

  it("keeps every stopover marina in the feature collection", () => {
    const items = Array.from({ length: 12 }, (_, i) => ({
      name: `Marina ${i}`,
      lat: 46.1 + i * 0.01,
      lon: -1.1,
      osm_id: `way/${i}`,
    }));
    const fc = marinasToFeatures({ sections: { mooring: { marinas: items } } });
    expect(fc.features).toHaveLength(12);
  });

  it("counts safe vs rejected place URLs", () => {
    const stats = summarizePlaceSafety([
      BAS_DU_FORT,
      {
        name: "Minimes",
        lat: 46.1467598,
        lon: -1.1660647,
        maps_url: "https://www.google.com/maps/place/Port+des+Minimes/@46.1468,-1.1661,17z",
      },
    ]);
    expect(stats.safe).toBe(1);
    expect(stats.rejected).toBe(1);
  });

  it("applyMarinaPlacePolicy exposes safe_google_place flag", () => {
    const row = applyMarinaPlacePolicy({
      name: "Minimes",
      lat: 46.1467598,
      lon: -1.1660647,
      maps_url: "https://www.google.com/maps/place/Port+des+Minimes/@46.1468,-1.1661,17z",
    });
    expect(row.safe_google_place).toBe(true);
  });
});
