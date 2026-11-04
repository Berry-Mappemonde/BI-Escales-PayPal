import { describe, expect, it } from "vitest";
import { marinasToFeatures } from "./marinasToFeatures.js";
import { visibleSections } from "../components/EscaleSheet.jsx";

describe("marinasToFeatures", () => {
  it("reprend les marinas de la fiche /escale", () => {
    const fc = marinasToFeatures({
      sections: {
        mooring: {
          marinas: [{ name: "Minimes", lat: 46.14, lon: -1.17, url: "https://example.org" }],
        },
      },
    });
    expect(fc.features).toHaveLength(1);
    expect(fc.features[0].properties.name).toBe("Minimes");
    expect(fc.features[0].geometry.coordinates).toEqual([-1.17, 46.14]);
  });
});

describe("visibleSections", () => {
  it("retire les formalités et le PoE", () => {
    const sections = visibleSections({
      mooring: { marinas: [{ name: "Minimes" }] },
      formalities: { poe: [{ name: "Douane" }] },
    });
    expect(sections.mooring.marinas).toHaveLength(1);
    expect(sections.formalities).toBeUndefined();
  });
});
