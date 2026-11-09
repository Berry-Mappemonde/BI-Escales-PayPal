import { describe, expect, it } from "vitest";
import { mockCatalogItem } from "./fixtures";
import { unitPriceFields, wishlistLineQuantity } from "./wishlistLine";
import { formatNativePrice } from "./channel3Format";

describe("wishlistLine", () => {
  it("prefers line quantity over catalogue quantity_needed", () => {
    const item = mockCatalogItem({
      channel3_product_id: "mock-qty",
      project_id: "gear-mock-qty",
      name: "Qty",
      quantity: 4,
      quantity_needed: 9,
    });
    expect(wishlistLineQuantity(item)).toBe(4);
  });

  it("falls back to quantity_needed when quantity absent", () => {
    expect(
      wishlistLineQuantity(
        mockCatalogItem({ channel3_product_id: "x", project_id: "y", name: "n", quantity_needed: 6 }),
      ),
    ).toBe(6);
  });

  it("formats unit price without multiplying by line quantity", () => {
    const item = mockCatalogItem({
      channel3_product_id: "mock-unit",
      project_id: "gear-mock-unit",
      name: "Unit",
      quantity: 5,
      price_display: "99.00",
      price_amount_minor: 9900,
      unit_price_amount_minor: 1000,
      unit_price_display: "10.00",
      unit_price_currency: "EUR",
      target_display: "50.00",
    });
    const unit = unitPriceFields(item);
    expect(unit.price_display).toBe("10.00");
    expect(formatNativePrice(item, "en")).toMatch(/10/);
  });
});
