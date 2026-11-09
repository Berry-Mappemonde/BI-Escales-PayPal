import { describe, expect, it } from "vitest";
import { catalogMapFromItems, linesFromTreasurerItems } from "./catalogMap";
import { fixtureCatalogEur } from "./fixtures";

describe("catalogMap", () => {
  it("marks missing catalogue rows as unavailable", () => {
    const map = catalogMapFromItems([fixtureCatalogEur]);
    const lines = linesFromTreasurerItems(
      [
        { channel3_product_id: fixtureCatalogEur.channel3_product_id, quantity: 2 },
        { channel3_product_id: "missing-mock-id", quantity: 1 },
      ],
      map,
    );
    expect(lines[0].state).toBe("ready");
    expect(lines[1]).toEqual({ state: "unavailable", channel3_product_id: "missing-mock-id" });
  });
});
