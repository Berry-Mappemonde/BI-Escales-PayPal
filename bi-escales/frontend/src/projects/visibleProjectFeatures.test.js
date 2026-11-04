import { describe, expect, it } from "vitest";
import { visibleProjectFeatures } from "./visibleProjectFeatures.js";

describe("visibleProjectFeatures", () => {
  const feature = (id, title) => ({
    properties: { id, title },
  });

  it("ajoute un projet sélectionné absent du top 100", () => {
    const filtered = Array.from({ length: 101 }, (_, index) => feature(`p-${index}`, `P${index}`));
    const pinned = feature("map-pick", "Map");
    const all = [...filtered, pinned];
    const visible = visibleProjectFeatures(all, filtered, "map-pick", 100);
    expect(visible[0].properties.id).toBe("map-pick");
    expect(visible).toHaveLength(100);
  });
});
