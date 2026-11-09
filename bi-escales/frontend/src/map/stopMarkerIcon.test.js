import { describe, expect, it } from "vitest";
import { stopMarkerIconHtml } from "./stopMarkerIcon.js";

describe("stopMarkerIconHtml", () => {
  it("adds an aria-label with the stop name on flag markers", () => {
    const html = stopMarkerIconHtml({
      name: "Ajaccio (Corse)",
      flags: ["/flags/fr.svg"],
    });
    expect(html).toContain('aria-label="Ajaccio (Corse)"');
  });

  it("adds an aria-label on drawing-pin markers without flags", () => {
    const html = stopMarkerIconHtml({ name: "La Rochelle" });
    expect(html).toContain('aria-label="La Rochelle"');
  });
});
